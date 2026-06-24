#!/usr/bin/env python3
"""
Multi-round remediation loop — the vertical slice's iteration driver.

The core is `run_loop(baseline_html, reviews_provider, ...)`, which is review-source
agnostic: it asks a provider for each round's reviews. `src/loop.py` runs it with a
file-based provider (tests/mock_reviews_rN.json); `src/benchmark.py` runs the same
loop with reviews synthesized per document. Swapping in live OLMo/Gemini/GPT
reviewers is just another provider — the loop, gate, applicator, and stop logic
do not change.

Per round:
  1. Provider supplies the round's reviews (dict) or None to stop.
  2. Judge -> patch manifest (LLM-safe fixes go to Claude Opus 4.8 when use_llm).
  3. Applicator applies the manifest deterministically -> patched HTML.
  4. Preservation gate compares the round's input to the patched output. Fail =>
     the round is discarded (no progress) and the loop stops.
  5. axe-core rescores. Converged when score >= threshold AND hard gates pass AND
     the round produced no new patches.

Note: the gate is a pre/post comparison, so it runs after the applicator each
round (against that round's input), not at the very top.

Run:
  python src/loop.py            # needs ANTHROPIC_API_KEY for the LLM-safe fix
"""

import json
import sys
import tempfile
import time
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


def run_loop(baseline_html: str, reviews_provider, *, label: str = "doc",
             use_llm: bool = True, max_rounds: int = MAX_ROUNDS,
             threshold: float = SCORE_THRESHOLD, on_round=None) -> dict:
    """Drive the remediation loop. `reviews_provider(round, current_html)` returns
    a reviews dict for the round, or None to stop. `on_round(entry, patched_html)`
    is an optional progress hook called after each accepted round. Returns a
    summary dict."""
    base_axe = axe_score(baseline_html)
    log(f"[{label}] baseline: score {base_axe['score']}%  violations "
        f"{base_axe['violations']}  passes {base_axe['passes']}")

    current = baseline_html
    final = baseline_html
    rounds: list[dict] = []
    stopped = "max_rounds_reached"
    prev_violations = base_axe["violations"]

    for r in range(1, max_rounds + 1):
        t0 = time.time()
        try:
            reviews = reviews_provider(r, current)
        except Exception as e:
            rounds.append({"round": r, "status": "reviewers_failed", "error": str(e),
                           "seconds": round(time.time() - t0, 2)})
            stopped = "reviewers_failed"
            log(f"[{label}] round {r}: reviewers failed ({e}); stopping")
            break
        if reviews is None:
            stopped = "no_more_reviews"
            break

        with tempfile.TemporaryDirectory() as d:
            html_path = Path(d) / "current.html"
            reviews_path = Path(d) / "reviews.json"
            html_path.write_text(current)
            reviews_path.write_text(json.dumps(reviews))
            patches, rejected, deferred, audit = judge.build_manifest(html_path, reviews_path, use_llm=use_llm)

        try:
            patched, applied = applicator.apply_patches(current, patches)
        except applicator.PatchError as e:
            rounds.append({"round": r, "status": "applicator_rollback", "error": str(e),
                           "seconds": round(time.time() - t0, 2)})
            stopped = "applicator_rollback"
            log(f"[{label}] round {r}: applicator rolled back ({e}); stopping")
            break

        gate_res = gate.run_gate(current, patched)
        axe = axe_score(patched)
        entry = {
            "round": r, "patches_applied": len(applied), "rejected": len(rejected),
            "score": axe["score"], "violations": axe["violations"], "passes": axe["passes"],
            "gate_passed": gate_res["passed"], "gate_failed_checks": gate_res["failed_checks"],
            "gate_checks": [{"name": c["name"], "passed": c["passed"], "detail": c["detail"]}
                            for c in gate_res["checks"]],
            "judge_audit": audit,
            "seconds": round(time.time() - t0, 2),
        }
        log(f"[{label}] round {r}: patches={len(applied)} rejected={len(rejected)} "
            f"score={axe['score']}% viol={axe['violations']} passes={axe['passes']} "
            f"gate={'PASS' if gate_res['passed'] else 'FAIL'} ({entry['seconds']}s)")

        if not gate_res["passed"]:
            entry["status"] = "gate_failed_reverted"
            rounds.append(entry)
            stopped = "gate_failed"
            log(f"[{label}] round {r}: gate failed {gate_res['failed_checks']} — reverting, stopping")
            break

        # Axe-regression guard: never accept a round that makes accessibility worse.
        if axe["violations"] > prev_violations:
            entry["status"] = "axe_regression_reverted"
            entry["regression"] = f"{prev_violations} -> {axe['violations']} violations"
            rounds.append(entry)
            stopped = "axe_regression"
            log(f"[{label}] round {r}: axe regression ({entry['regression']}) — reverting, stopping")
            break

        current, final = patched, patched
        prev_violations = axe["violations"]
        entry["status"] = "accepted"
        rounds.append(entry)
        if on_round:
            on_round(entry, patched)

        if (axe["score"] >= threshold and hard_gates_pass(gate_res, axe) and len(applied) == 0):
            stopped = "converged"
            log(f"[{label}] round {r}: converged (no remaining fixes)")
            break

    return {"label": label, "baseline": base_axe, "rounds": rounds,
            "rounds_accepted": len([r for r in rounds if r.get("status") == "accepted"]),
            "stopped_reason": stopped, "final": axe_score(final), "final_html": final}


# ---------------------------------------------------------------------------
# CLI: run on the syllabus with file-based mock reviews
# ---------------------------------------------------------------------------
def _file_provider(r: int, _current_html: str):
    p = ROOT / "tests" / f"mock_reviews_r{r}.json"
    return json.loads(p.read_text()) if p.exists() else None


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Run the remediation loop on the syllabus baseline.")
    ap.add_argument("--live", action="store_true",
                    help="use live OLMo/Gemini/GPT reviewers instead of mock files")
    ap.add_argument("--baseline", type=Path, default=BASELINE)
    args = ap.parse_args()

    log("=" * 72)
    if not args.baseline.exists():
        log(f"FATAL: baseline not found: {args.baseline}")
        return 1

    if args.live:
        import reviewers
        reviewers.load_env()  # ensure ANTHROPIC/GOOGLE/OPENAI keys are present for judge + reviewers
        provider, mode = reviewers.live_provider, "live reviewers"
    else:
        provider, mode = _file_provider, "file-based mock reviews"
    log(f"Remediation loop starting (syllabus, {mode})")

    summary = run_loop(args.baseline.read_text(), provider, label="syllabus", use_llm=True)
    FINAL_HTML.write_text(summary.pop("final_html"))
    SUMMARY.write_text(json.dumps({**summary, "final_html": str(FINAL_HTML)}, indent=2))

    accepted = [e for e in summary["rounds"] if e.get("status") == "accepted"]
    log("=" * 72)
    log(f"LOOP COMPLETE  stopped={summary['stopped_reason']}")
    log("  progression: baseline {}p -> ".format(summary["baseline"]["passes"])
        + " -> ".join(f"r{e['round']} {e['passes']}p/{e['patches_applied']}fix" for e in accepted))
    log(f"  final: score {summary['final']['score']}%  passes {summary['final']['passes']}")
    log(f"  final HTML: {FINAL_HTML}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
