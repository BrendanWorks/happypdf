#!/usr/bin/env python3
"""
Claude-based judge: synthesize peer reviews into a deterministic patch manifest.

Input
-----
- Baseline HTML (the vertical-slice output) — parsed for `data-ir-id` -> element.
- Peer reviews: JSON object mapping reviewer name -> list of issues. Each issue:
    {issue_id, wcag_criterion, element_id, issue, impact, confidence,
     suggested_fix, fix_type, hallucinated}
  The reviewer-supplied `fix_type` / `hallucinated` are treated as ADVISORY — the
  judge re-derives them from the HTML structure and (for LLM-safe fixes) Claude.

Output
------
- output/patch_manifest.json : JSON array of deterministic patches. Each patch
  targets exactly one element by `data-ir-id` and needs NO further LLM call to
  apply. Schema:
    {element_id, operation, target_attribute, new_value, wcag_criterion,
     confidence, reasoning, llm_safe?}
- output/judge_rejected.json : issues that were skipped (hallucinated / needs_human),
  logged separately with the reasoning.

Operation contract (consumed by the downstream applicator)
----------------------------------------------------------
  annotate : set `target_attribute` = `new_value` on the element
  replace  : replace the element's text content with `new_value`
  wrap     : wrap the element in a parent element named `new_value`
  insert   : insert an adjacent node described by `new_value`

Run
---
  # offline — deterministic + hallucination + needs_human paths only (no API key)
  python src/judge.py --no-llm
  # live — also generates LLM-safe fixes via Claude (needs ANTHROPIC_API_KEY)
  python src/judge.py
"""

import argparse
import difflib
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from bs4 import BeautifulSoup

MODEL = "claude-opus-4-8"

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_HTML = ROOT / "output" / "syllabus_scored.html"
DEFAULT_REVIEWS = ROOT / "tests" / "mock_reviews.json"
OUT_MANIFEST = ROOT / "output" / "patch_manifest.json"
OUT_REJECTED = ROOT / "output" / "judge_rejected.json"
OUT_AUDIT = ROOT / "output" / "judge_audit.json"

# Confidence as a function of agreement count (see spec).
CONF_BY_COUNT = {1: 0.60, 2: 0.80, 3: 0.95}
FUZZY_THRESHOLD = 0.50  # SequenceMatcher ratio when no target attribute can be derived

# Issue language that routes to a human: content meaning, structure, reading order.
HUMAN_KW = (
    "reading order", "header structure", "table structure", "wrong header",
    "scope", "header association", "semantic structure", "incorrect data",
    "missing content", "restructure", "merge cells", "rowspan", "colspan",
)
# Attributes a patch may set deterministically when a concrete value is supplied.
DET_ATTRS = ("role", "aria-label", "aria-describedby", "aria-labelledby", "lang")
# Self-sufficient ARIA roles — safe to add without companion attributes. Roles
# like "heading" (needs aria-level) or "checkbox" (needs aria-checked) are NOT
# here: applying them bare introduces an aria-required-attr violation, so they
# route to needs_human instead.
SAFE_ROLES = frozenset({
    "navigation", "banner", "main", "contentinfo", "complementary", "region",
    "search", "form", "list", "listitem", "table", "row", "cell", "columnheader",
    "rowheader", "group", "figure", "note", "article", "document", "img",
})


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------
def parse_html(path: Path) -> dict[str, dict]:
    """Map data-ir-id -> {tag, text, alt, empty}."""
    soup = BeautifulSoup(path.read_text(), "html.parser")
    index: dict[str, dict] = {}
    for el in soup.select("[data-ir-id]"):
        text = el.get_text(strip=True)
        index[el["data-ir-id"]] = {
            "tag": el.name,
            "text": text,
            "alt": el.get("alt", ""),
            "empty": not text and not el.get("alt"),
            "attrs": {k: v for k, v in el.attrs.items()},
        }
    return index


def load_reviews(path: Path) -> dict[str, list[dict]]:
    data = json.loads(path.read_text())
    return {rev: issues for rev, issues in data.items()}


def parse_fix(suggested: str) -> tuple[str | None, str | None]:
    """Extract (target_attribute, concrete_value) from a suggested-fix string."""
    m = re.search(
        r'(alt|aria-label|aria-describedby|aria-labelledby|role|lang)\s*=\s*"([^"]*)"',
        suggested or "", re.I,
    )
    if m:
        return m.group(1).lower(), m.group(2)
    m = re.search(r'\b(alt|aria-label|aria-describedby|aria-labelledby|role|lang)\b',
                  suggested or "", re.I)
    if m:
        return m.group(1).lower(), None
    return None, None


# ---------------------------------------------------------------------------
# Deduplication across reviewers
# ---------------------------------------------------------------------------
@dataclass
class Group:
    element_id: str
    wcag_criterion: str
    issue: str
    impact: str
    suggested_fix: str
    reviewers: set = field(default_factory=set)
    reviewer_confidences: list = field(default_factory=list)
    hallucinated_hints: list = field(default_factory=list)
    fix_type_hints: list = field(default_factory=list)

    @property
    def confidence(self) -> float:
        return CONF_BY_COUNT.get(len(self.reviewers), 0.95)


def _same_issue(g: Group, it: dict) -> bool:
    """Two issues on the same element+criterion are 'the same' when their derived
    target attribute matches, or (when no attribute is derivable) their text is
    fuzzy-similar. Different reviewers phrase the same problem differently, so the
    target attribute is a more robust signal than raw description text."""
    if g.element_id != it.get("element_id") or g.wcag_criterion != it.get("wcag_criterion"):
        return False
    g_target = parse_fix(g.suggested_fix)[0]
    it_target = parse_fix(it.get("suggested_fix", ""))[0]
    if g_target and it_target:
        return g_target == it_target
    ratio = difflib.SequenceMatcher(None, g.issue.lower(), it.get("issue", "").lower()).ratio()
    return ratio >= FUZZY_THRESHOLD


def deduplicate(reviews: dict[str, list[dict]]) -> list[Group]:
    """Cluster issues with the same (element_id, wcag_criterion) and same intent."""
    groups: list[Group] = []
    for reviewer, issues in reviews.items():
        for it in issues:
            match = None
            for g in groups:
                if _same_issue(g, it):
                    match = g
                    break
            if match is None:
                match = Group(
                    element_id=it.get("element_id"),
                    wcag_criterion=it.get("wcag_criterion"),
                    issue=it.get("issue", ""),
                    impact=it.get("impact", "moderate"),
                    suggested_fix=it.get("suggested_fix", ""),
                )
                groups.append(match)
            match.reviewers.add(reviewer)
            match.reviewer_confidences.append(it.get("confidence"))
            match.hallucinated_hints.append(it.get("hallucinated"))
            match.fix_type_hints.append(it.get("fix_type"))
    return groups


# ---------------------------------------------------------------------------
# Classification (advisory re-derivation + conservative human-gate)
# ---------------------------------------------------------------------------
def classify(g: Group, el: dict | None) -> tuple[str, str, str | None, str | None]:
    """Return (decision, reason, target_attribute, concrete_value).

    decision in {deterministic, llm_safe, needs_human, hallucinated}.
    """
    target, value = parse_fix(g.suggested_fix)
    blob = f"{g.issue} {g.suggested_fix}".lower()

    # 1. Structural hallucination checks (deterministic, no API).
    if el is None:
        return "hallucinated", "targets a data-ir-id not present in the HTML", target, value
    if target == "alt" and el["tag"] != "img":
        return ("hallucinated",
                f"alt text requested on a non-image <{el['tag']}> element", target, value)
    if target in ("aria-label", "alt") and el["empty"] and el["tag"] in ("p", "span", "div"):
        return ("hallucinated",
                f"accessible name requested on an empty <{el['tag']}> with no content",
                target, value)

    # 2. Conservative human-gate: content meaning / structure / reading order.
    if any(kw in blob for kw in HUMAN_KW):
        return "needs_human", "touches content meaning, table structure, or reading order", target, value

    # 3. LLM-required: alt text on a real image (rewrite/generate).
    if target == "alt" and el["tag"] == "img":
        return "llm_safe", "alt text for an image requires model judgment", target, value

    # 4. Deterministic: a concrete attribute value on a safe target.
    if target == "role" and value and value.lower() not in SAFE_ROLES:
        return ("needs_human",
                f'role="{value}" needs validation/companion attributes (not a self-sufficient role)',
                target, value)
    if target in DET_ATTRS and value:
        return "deterministic", "reviewer supplied a concrete, non-destructive attribute value", target, value

    # 5. Conservative default — anything ambiguous goes to a human.
    return "needs_human", "no safe deterministic transformation could be derived", target, value


# ---------------------------------------------------------------------------
# Claude: generate LLM-safe fixes (alt text) and judge safety
# ---------------------------------------------------------------------------
def claude_alt_fix(g: Group, el: dict) -> dict:
    """Ask Claude to produce concise alt text and judge whether the fix is safe."""
    import anthropic

    client = anthropic.Anthropic()
    system = (
        "You are an accessibility remediation judge. You rewrite or generate HTML "
        "image alt text to satisfy WCAG. Be specific and concise (screen-reader "
        "friendly). If the correct alt text cannot be determined safely from the "
        "given context (e.g. the image conveys data that needs a long description, "
        "or you would have to invent facts), set safe=false so a human can handle it. "
        "Respond with a single JSON object and nothing else."
    )
    payload = {
        "wcag_criterion": g.wcag_criterion,
        "issue": g.issue,
        "current_alt": el.get("alt", ""),
        "suggested_fix": g.suggested_fix,
    }
    user = (
        "Peer reviewers flagged the alt text on an image. Context:\n"
        f"{json.dumps(payload, indent=2)}\n\n"
        'Return JSON: {"new_value": "<improved alt text>", "safe": true|false, '
        '"confidence": 0.0-1.0, "reasoning": "<why this is correct and safe>"}'
    )
    resp = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        thinking={"type": "adaptive"},
        output_config={"effort": "high"},
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    text = "".join(b.text for b in resp.content if b.type == "text")
    return _extract_json(text)


def _extract_json(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            return json.loads(m.group(0))
        raise


# ---------------------------------------------------------------------------
# Manifest assembly
# ---------------------------------------------------------------------------
def build_manifest(html: Path, reviews: Path, use_llm: bool) -> tuple[list, list, list]:
    index = parse_html(html)
    reviews_dict = load_reviews(reviews)
    total_reviewers = len(reviews_dict)
    groups = deduplicate(reviews_dict)
    log(f"deduplicated {sum(len(g.reviewers) for g in groups)} raw issues "
        f"-> {len(groups)} unique issue(s)")

    patches, rejected, deferred, audit = [], [], [], []

    def record(g, decision, structural, patch_generated, claude_call=False, claude=None):
        """One auditable per-issue decision row for output/judge_audit.json."""
        audit.append({
            "issue_id": f"{g.element_id}:{g.wcag_criterion}",
            "element_id": g.element_id,
            "wcag_criterion": g.wcag_criterion,
            "reviewers": sorted(g.reviewers),
            "dedup_status": (f"{len(g.reviewers)}/{total_reviewers} agree "
                             f"(confidence {g.confidence})"),
            "issue": g.issue,
            "suggested_fix": g.suggested_fix,
            "structural_check": structural,
            "advisory_flags": {"hallucinated": g.hallucinated_hints, "fix_type": g.fix_type_hints},
            "claude_call": claude_call,
            "claude_reasoning": (claude or {}).get("reasoning") if claude else None,
            "decision": decision,
            "patch_generated": patch_generated,
        })

    for g in groups:
        el = index.get(g.element_id)
        decision, reason, target, value = classify(g, el)
        agree = f"{len(g.reviewers)} reviewer(s): {', '.join(sorted(g.reviewers))}"

        if decision == "hallucinated":
            record(g, "REJECT_HALLUCINATED", reason, False)
            rejected.append({
                "element_id": g.element_id, "wcag_criterion": g.wcag_criterion,
                "status": "hallucinated", "reason": reason, "flagged_by": sorted(g.reviewers),
                "advisory_hallucinated_flags": g.hallucinated_hints,
            })
            log(f"  ✗ hallucination skipped [{g.element_id}] {reason}")
            continue

        if decision == "needs_human":
            rejected.append({
                "element_id": g.element_id, "wcag_criterion": g.wcag_criterion,
                "status": "needs_human", "reason": reason, "flagged_by": sorted(g.reviewers),
                "confidence": g.confidence, "issue": g.issue,
            })
            record(g, "NEEDS_HUMAN", reason, False)
            log(f"  ⚠ needs_human [{g.element_id}] {reason}")
            continue

        # No-op suppression: a fix that doesn't change the DOM is not progress.
        # This is what lets live runs converge — reviewers re-flag already-fixed
        # elements every round, but re-setting an attribute to its current value
        # produces no patch.
        if decision == "deterministic" and el and el["attrs"].get(target) == value:
            rejected.append({
                "element_id": g.element_id, "wcag_criterion": g.wcag_criterion,
                "status": "already_satisfied", "flagged_by": sorted(g.reviewers),
                "reason": f'{target}="{value}" is already present on the element',
            })
            record(g, "ALREADY_SATISFIED", f'{target}="{value}" already present', False)
            log(f"  = already satisfied [{g.element_id}] {target}=\"{value}\"")
            continue
        if decision == "llm_safe" and el and len((el.get("alt") or "").strip()) >= 15:
            rejected.append({
                "element_id": g.element_id, "wcag_criterion": g.wcag_criterion,
                "status": "already_satisfied", "flagged_by": sorted(g.reviewers),
                "reason": "element already has substantive alt text",
            })
            record(g, "ALREADY_SATISFIED", "element already has substantive alt text", False)
            log(f"  = already satisfied [{g.element_id}] alt already present")
            continue

        if decision == "deterministic":
            patches.append({
                "element_id": g.element_id,
                "operation": "annotate",
                "target_attribute": target,
                "new_value": value,
                "wcag_criterion": g.wcag_criterion,
                "confidence": g.confidence,
                "reasoning": (f"Deterministic fix accepted ({agree}, confidence "
                              f"{g.confidence}). {reason}. Setting {target}=\"{value}\" is "
                              f"non-destructive and needs no model call."),
            })
            record(g, "ACCEPT", f'{reason}; target {target} is valid', True)
            log(f"  ✓ deterministic patch [{g.element_id}] {target}=\"{value}\"")
            continue

        # decision == "llm_safe"
        if not use_llm:
            deferred.append({
                "element_id": g.element_id, "wcag_criterion": g.wcag_criterion,
                "status": "deferred_llm", "reason": "LLM-safe fix; run without --no-llm to generate",
                "flagged_by": sorted(g.reviewers),
            })
            record(g, "DEFERRED_LLM", "LLM-safe fix; deferred (--no-llm)", False)
            log(f"  … llm_safe deferred [{g.element_id}] (--no-llm)")
            continue

        log(f"  → calling Claude ({MODEL}) for llm_safe fix [{g.element_id}]...")
        result = claude_alt_fix(g, el)
        if not result.get("safe", False):
            rejected.append({
                "element_id": g.element_id, "wcag_criterion": g.wcag_criterion,
                "status": "needs_human", "reason": "Claude judged the fix unsafe to auto-generate",
                "claude": result, "flagged_by": sorted(g.reviewers),
            })
            record(g, "NEEDS_HUMAN", f"alt on <{el['tag']}> is valid; Claude judged fix unsafe",
                   False, claude_call=True, claude=result)
            log(f"  ⚠ needs_human [{g.element_id}] Claude declined to auto-fix")
            continue

        conf = round(min(g.confidence, float(result.get("confidence", g.confidence))), 2)
        patches.append({
            "element_id": g.element_id,
            "operation": "annotate",
            "target_attribute": target or "alt",
            "new_value": result.get("new_value", ""),
            "wcag_criterion": g.wcag_criterion,
            "confidence": conf,
            "llm_safe": True,
            "reasoning": (f"LLM-safe fix accepted ({agree}). Claude ({MODEL}) generated the "
                          f"alt text and judged it safe. Claude reasoning: "
                          f"{result.get('reasoning', '')}"),
        })
        record(g, "ACCEPT", f"alt on <{el['tag']}> is valid; Claude generated + approved", True,
               claude_call=True, claude=result)
        log(f"  ✓ llm_safe patch [{g.element_id}] alt=\"{result.get('new_value','')[:60]}\"")

    OUT_AUDIT.parent.mkdir(parents=True, exist_ok=True)
    OUT_AUDIT.write_text(json.dumps(audit, indent=2))
    return patches, rejected, deferred, audit


def main() -> int:
    ap = argparse.ArgumentParser(description="Peer reviews -> deterministic patch manifest.")
    ap.add_argument("--html", type=Path, default=DEFAULT_HTML)
    ap.add_argument("--reviews", type=Path, default=DEFAULT_REVIEWS)
    ap.add_argument("--no-llm", action="store_true",
                    help="skip Claude calls; defer LLM-safe fixes (offline-testable)")
    args = ap.parse_args()

    log("=" * 70)
    log(f"Judge starting  html={args.html.name}  reviews={args.reviews.name}  "
        f"llm={'off' if args.no_llm else 'on'}")
    if not args.html.exists():
        log(f"FATAL: HTML not found: {args.html}")
        return 1
    if not args.reviews.exists():
        log(f"FATAL: reviews not found: {args.reviews}")
        return 1

    patches, rejected, deferred, audit = build_manifest(args.html, args.reviews, use_llm=not args.no_llm)

    OUT_MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    OUT_MANIFEST.write_text(json.dumps(patches, indent=2))
    OUT_REJECTED.write_text(json.dumps(
        {"rejected": rejected, "deferred": deferred}, indent=2))

    log("=" * 70)
    log(f"DONE  patches={len(patches)}  rejected={len(rejected)}  deferred={len(deferred)}")
    log(f"  manifest: {OUT_MANIFEST}")
    log(f"  rejected: {OUT_REJECTED}")
    log(f"  audit:    {OUT_AUDIT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
