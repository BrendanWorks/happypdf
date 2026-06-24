#!/usr/bin/env python3
"""
Multi-round remediation loop — the vertical slice's iteration driver.

For each round (1..MAX_ROUNDS):
  1. Judge re-reviews the current HTML using that round's mock reviews
     (tests/mock_reviews_rN.json) and emits a patch manifest.
  2. Applicator applies the manifest deterministically -> patched HTML.
  3. Preservation gate compares the round's input HTML to the patched HTML.
     If it fails, the round is discarded (no progress) and the loop stops.
  4. axe-core rescores the patched HTML.
  5. Stop condition: axe score >= threshold AND hard gates pass AND the round
     produced no new patches (nothing left to fix) -> converged.

The orchestrator is review-source agnostic: swap the per-round mock files for
live OLMo/Gemini/GPT calls without touching this loop.

Note: the gate is a pre/post comparison, so it necessarily runs *after* the
applicator each round (against that round's input), rather than at the very top.

Run (needs ANTHROPIC_API_KEY for the judge's LLM-safe fixes):
  python src/loop.py
"""

import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

SRC = Path(__file__).resolve().parent
sys.path.insert(0, str(SRC))
import judge        # noqa: E402
import applicator   # noqa: E402
import gate         # noqa: E402

ROOT = SRC.parent
BASELINE = ROOT / "output" / "syllabus_scored.html"
REVIEWS_FOR = lambda r: ROOT / "tests" / f"mock_reviews_r{r}.json"
ROUND_HTML = lambda r: ROOT / "output" / f"loop_round{r}.html"
FINAL_HTML = ROOT / "output" / "syllabus_final.html"
SUMMARY = ROOT / "output" / "loop_summary.json"

MAX_ROUNDS = 3
SCORE_THRESHOLD = 95.0  # percent: passes / (passes + violations)

AXE_CANDIDATES = [
    ROOT / "node_modules/axe-core/axe.min.js",
    Path("/Users/brendanworks/node_modules/axe-core/axe.min.js"),
]


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def axe_score(html_str: str) -> dict:
    """Run axe-core on an HTML string in headless Chromium."""
    axe_path = next((p for p in AXE_CANDIDATES if p.exists()), None)
    if axe_path is None:
        raise FileNotFoundError("axe-core not found")
    axe_src = axe_path.read_text()
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False) as f:
        f.write(html_str)
        tmp = Path(f.name)
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            page = b.new_page()
            page.goto(f"file://{tmp}")
            page.evaluate(axe_src)
            r = page.evaluate("async () => await axe.run()")
            b.close()
    finally:
        tmp.unlink(missing_ok=True)
    violations = r.get("violations", [])
    passes = len(r.get("passes", []))
    nv = len(violations)
    score = round(passes / (passes + nv) * 100, 1) if (passes + nv) else 100.0
    crit = sum(1 for v in violations if v.get("impact") in ("critical", "serious"))
    return {"score": score, "violations": nv, "passes": passes, "critical_serious": crit}


def hard_gates_pass(gate_res: dict, axe: dict) -> bool:
    """Hard gates: content preserved AND no critical/serious axe violations."""
    return gate_res["passed"] and axe["critical_serious"] == 0


def main() -> int:
    log("=" * 72)
    log("Remediation loop starting")
    if not BASELINE.exists():
        log(f"FATAL: baseline not found: {BASELINE}")
        return 1

    current_path = BASELINE
    current_html = BASELINE.read_text()
    base_axe = axe_score(current_html)
    log(f"baseline: score {base_axe['score']}%  violations {base_axe['violations']}  "
        f"passes {base_axe['passes']}")

    rounds: list[dict] = []
    stopped_reason = "max_rounds_reached"
    final_html = current_html

    for r in range(1, MAX_ROUNDS + 1):
        reviews = REVIEWS_FOR(r)
        log("-" * 72)
        log(f"ROUND {r}: reviews={reviews.name}")
        if not reviews.exists():
            log(f"  no reviews for round {r}; stopping")
            stopped_reason = "no_more_reviews"
            break

        # 1. Judge -> manifest (LLM-safe fixes go to Claude Opus 4.8).
        patches, rejected, deferred = judge.build_manifest(current_path, reviews, use_llm=True)

        # 2. Applicator -> patched HTML (all-or-nothing).
        try:
            patched_html, applied = applicator.apply_patches(current_html, patches)
        except applicator.PatchError as e:
            log(f"  applicator rolled back: {e}; stopping")
            rounds.append({"round": r, "status": "applicator_rollback", "error": str(e)})
            stopped_reason = "applicator_rollback"
            break

        # 3. Preservation gate (pre-round input vs patched output).
        gate_res = gate.run_gate(current_html, patched_html)

        # 4. Rescore.
        axe = axe_score(patched_html)

        entry = {
            "round": r, "reviews": reviews.name,
            "patches_applied": len(applied), "rejected": len(rejected),
            "score": axe["score"], "violations": axe["violations"], "passes": axe["passes"],
            "gate_passed": gate_res["passed"],
            "gate_failed_checks": gate_res["failed_checks"],
        }
        log(f"  patches applied={len(applied)}  rejected={len(rejected)}  "
            f"score={axe['score']}%  violations={axe['violations']}  passes={axe['passes']}  "
            f"gate={'PASS' if gate_res['passed'] else 'FAIL'}")

        # Gate failure: round does not count as progress; revert and stop.
        if not gate_res["passed"]:
            entry["status"] = "gate_failed_reverted"
            rounds.append(entry)
            log(f"  ✗ gate failed {gate_res['failed_checks']} — reverting round {r}, stopping")
            stopped_reason = "gate_failed"
            break

        # Round accepted.
        ROUND_HTML(r).write_text(patched_html)
        current_html, current_path, final_html = patched_html, ROUND_HTML(r), patched_html
        entry["status"] = "accepted"
        rounds.append(entry)

        # 5. Stop condition.
        converged = (axe["score"] >= SCORE_THRESHOLD
                     and hard_gates_pass(gate_res, axe)
                     and len(applied) == 0)
        if converged:
            log(f"  ✓ converged: score {axe['score']}% >= {SCORE_THRESHOLD}%, "
                f"hard gates pass, no remaining fixes")
            stopped_reason = "converged"
            break

    FINAL_HTML.write_text(final_html)
    final_axe = axe_score(final_html)
    summary = {
        "baseline": base_axe,
        "rounds": rounds,
        "rounds_run": len([r for r in rounds if r.get("status") == "accepted"]),
        "stopped_reason": stopped_reason,
        "final": final_axe,
        "final_html": str(FINAL_HTML),
    }
    SUMMARY.write_text(json.dumps(summary, indent=2))

    log("=" * 72)
    log("LOOP COMPLETE")
    log(f"  stopped: {stopped_reason}")
    log(f"  progression: baseline {base_axe['passes']} passes -> "
        + " -> ".join(f"r{e['round']} {e['passes']}p/{e['patches_applied']}fix"
                      for e in rounds if e.get("status") == "accepted"))
    log(f"  final: score {final_axe['score']}%  violations {final_axe['violations']}  "
        f"passes {final_axe['passes']}")
    log(f"  final HTML: {FINAL_HTML}")
    log(f"  summary:    {SUMMARY}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
