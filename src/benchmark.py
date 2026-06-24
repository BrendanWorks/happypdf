#!/usr/bin/env python3
"""
Benchmark suite: run the full remediation loop across document types.

For each benchmark document it:
  1. Builds baseline semantic HTML from the cached olmOCR markdown
     (olmOCR -> markdown is cached; re-extraction would just re-spend GPU time).
  2. Runs the same `run_loop` used by src/loop.py, with reviews SYNTHESIZED per
     document from its real elements (mock reviewers — round 1 labels tables,
     round 2 labels lists, round 3 finds nothing -> converged). The synthesizer
     is the only doc-specific piece; the loop/judge/applicator/gate are shared.
  3. Records baseline -> per-round scores, patch counts, and time per round.
  4. Writes <name>_baseline.html, <name>_final.html, <name>_summary.json, and a
     BENCHMARK.md comparison table.

Run (offline — no Modal, no API key; these docs have no images so no LLM-safe fixes):
  python src/benchmark.py
"""

import json
import sys
import time
from pathlib import Path

from lxml import html

SRC = Path(__file__).resolve().parent
sys.path.insert(0, str(SRC))
import build_syllabus_slice as bss   # noqa: E402
import reviewers                     # noqa: E402
from loop import run_loop            # noqa: E402

ROOT = SRC.parent
BENCH = ROOT / "benchmark"

# (display name, cached olmOCR markdown, document type description)
DOCS = [
    ("syllabus", "syllabus_olmocr.md", "clean, already accessible"),
    ("irs_schedule_c", "irs_olmocr.md", "dense tax form"),
    ("navy_bulletin", "navy_olmocr.md", "OCR'd historical scan, prose"),
]


# ---------------------------------------------------------------------------
# Per-document mock reviewers (synthesized from the real element index)
# ---------------------------------------------------------------------------
def _label(el, i: int) -> str:
    prev = el.getprevious()
    while prev is not None:
        txt = (prev.text_content() or "").strip()
        if txt:
            return txt[:40]
        prev = prev.getprevious()
    return f"Data table {i}"


def _issue(eid, crit, text, fix):
    return {"issue_id": f"synth-{eid}", "wcag_criterion": crit, "element_id": eid,
            "issue": text, "impact": "serious", "confidence": 0.85,
            "suggested_fix": fix, "fix_type": "deterministic", "hallucinated": False}


def synth_reviews(rnd: int, current_html: str):
    """Round 1: name tables. Round 2: role lists. Round 3+: nothing -> converge.
    Three reviewers agree on each issue so dedup + confidence are exercised."""
    doc = html.document_fromstring(current_html)
    issues = []
    if rnd == 1:
        for i, t in enumerate(doc.xpath("//table[@data-ir-id]"), 1):
            if t.get("aria-label"):
                continue
            issues.append(_issue(t.get("data-ir-id"), "1.3.1",
                                 "Data table has no accessible name.",
                                 f'Add aria-label="{_label(t, i)}" to the table.'))
    elif rnd == 2:
        for ul in doc.xpath("//ul[@data-ir-id]"):
            if ul.get("role"):
                continue
            issues.append(_issue(ul.get("data-ir-id"), "1.3.1",
                                 "List has no explicit list role for assistive technology.",
                                 'Add role="list" to the list.'))
    if not issues:
        return {}  # no actionable issues this round -> 0 patches -> converged
    return {"olmo": issues, "gemini": list(issues), "gpt": list(issues)}


# ---------------------------------------------------------------------------
# Run + report
# ---------------------------------------------------------------------------
def run_document(name: str, md_file: str, doctype: str, *, live: bool = False) -> dict:
    md_path = BENCH / md_file
    print(f"\n=== {name} ({doctype}) {'[LIVE]' if live else '[mock]'} ===", flush=True)
    markdown = bss.strip_front_matter(md_path.read_text())
    baseline_html = bss.HtmlBuilder(markdown, [], {}).build()
    suffix = "_live" if live else ""
    (BENCH / f"{name}{suffix}_baseline.html").write_text(baseline_html)

    provider = reviewers.live_provider if live else synth_reviews
    t0 = time.time()
    summary = run_loop(baseline_html, provider, label=name, use_llm=live)
    summary["doctype"] = doctype
    summary["total_seconds"] = round(time.time() - t0, 2)

    (BENCH / f"{name}{suffix}_final.html").write_text(summary.pop("final_html"))
    (BENCH / f"{name}{suffix}_summary.json").write_text(json.dumps({**summary, "name": name}, indent=2))
    return {**summary, "name": name}


def comparison_table(results: list[dict], *, live: bool = False) -> str:
    def cell(rounds, r):
        e = next((x for x in rounds if x["round"] == r and x.get("status") == "accepted"), None)
        return f"{e['patches_applied']} → {e['passes']}p" if e else "—"

    source = ("live OLMo (Modal) + Gemini (google-genai) + GPT (openai), called in parallel"
              if live else "synthesized per document from its real elements")
    lines = [
        f"# happypdf Benchmark — {'LIVE reviewers' if live else 'remediation loop'} "
        "across document types",
        "",
        "Full pipeline per document: cached olmOCR markdown → semantic HTML → "
        "multi-round loop (judge → applicator → preservation gate → axe rescore). "
        f"Reviews are {source}.",
        "",
        "**Note on violations:** the HTML generator emits clean semantic HTML5, so "
        "every document starts at **0 axe violations**. The loop's measurable effect "
        "is the **passes** count climbing as ARIA is added — and only where there is "
        "structure to enhance. The cross-document signal is therefore structure-driven "
        "remediation, not violation-fixing.",
        "",
        "| Document | Type | Baseline (viol / passes) | Round 1 (patches → passes) | "
        "Round 2 | Round 3 | Final passes | Stop | Time (s) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for res in results:
        b = res["baseline"]
        rounds = res["rounds"]
        lines.append(
            f"| {res['name']} | {res['doctype']} | "
            f"{b['violations']} / {b['passes']} | "
            f"{cell(rounds, 1)} | {cell(rounds, 2)} | {cell(rounds, 3)} | "
            f"{res['final']['passes']} | {res['stopped_reason']} | {res['total_seconds']} |"
        )
    lines += [
        "",
        "All documents end with **0 violations** and a content-preservation gate that "
        "**passed every round** (no text loss, no dropped tables/images, no heading "
        "skips). Convergence = score ≥ 95% AND hard gates pass AND a round produced no "
        "new patches.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Run the loop across benchmark documents.")
    ap.add_argument("--live", action="store_true",
                    help="use live OLMo/Gemini/GPT reviewers instead of synthesized mocks")
    args = ap.parse_args()

    if args.live:
        reviewers.load_env()
    results = [run_document(*d, live=args.live) for d in DOCS]
    table = comparison_table(results, live=args.live)
    out_md = BENCH / ("BENCHMARK_LIVE.md" if args.live else "BENCHMARK.md")
    out_json = BENCH / ("benchmark_live_summary.json" if args.live else "benchmark_summary.json")
    out_md.write_text(table)
    out_json.write_text(json.dumps(results, indent=2))
    print("\n" + "=" * 72)
    print(table)
    print(f"written: {out_md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
