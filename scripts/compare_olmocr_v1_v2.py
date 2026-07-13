#!/usr/bin/env python3
"""
Compare olmOCR v1 (production, app "olmocr") vs olmOCR-2 (staging, app "olmocr-v2")
on a table-heavy benchmark PDF, and log a quality comparison for review.

What it does:
  1. HEALTH CHECK — resolves both Modal functions and aborts if the staging
     endpoint isn't deployed/reachable. We never call the production endpoint
     unless staging is confirmed live (no point comparing against nothing).
  2. Runs IRS Schedule C (dense tax form with tables) through v2, then v1.
  3. Computes structure/math/text heuristics on each output.
  4. Writes raw markdown + a comparison report to output/ (gitignored, transient).

What it deliberately does NOT do:
  - It does not touch anything under benchmark/ (inputs, *_final.html, *_summary.json).
  - It does not modify production, promote v2, or change any committed report.

Usage:
    python scripts/compare_olmocr_v1_v2.py
    python scripts/compare_olmocr_v1_v2.py --pdf benchmark/navy_bulletin.pdf
"""

import argparse
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import modal

REPO = Path(__file__).resolve().parent.parent
DEFAULT_PDF = REPO / "benchmark" / "irs_schedule_c.pdf"
OUTPUT_DIR = REPO / "output"  # gitignored, transient — safe scratch space

V1_APP, V1_FN = "olmocr", "process_pdf"  # production (implicit default model = v1)
V2_APP, V2_FN = "olmocr-v2", "process_pdf"  # staging (pinned olmOCR-2-7B-1025-FP8)
EXPECTED_V2_MODEL = "allenai/olmOCR-2-7B-1025-FP8"

# A single cold H100 extraction realistically takes a few minutes. Treat anything
# past this as "staging is unhealthy/too slow" and surface it loudly.
SLOW_THRESHOLD_SEC = 600


def log(report: list[str], line: str = "") -> None:
    """Append to the in-memory report and echo to stdout so the run is watchable."""
    print(line)
    report.append(line)


def resolve(app: str, fn: str):
    """Resolve a deployed Modal function handle, or return None if it isn't there."""
    try:
        return modal.Function.from_name(app, fn)
    except Exception as e:  # noqa: BLE001 — we want to catch any resolution failure
        print(f"  ✗ could not resolve {app}/{fn}: {type(e).__name__}: {e}")
        return None


def health_check(report: list[str]) -> tuple:
    """Verify the staging endpoint exists before we spend money on a comparison.

    Returns (v2_fn, v1_fn); exits the process if either isn't reachable.
    """
    log(report, "── HEALTH CHECK ─────────────────────────────────────────────")
    v2 = resolve(V2_APP, V2_FN)
    if v2 is None:
        log(report, f"ABORT: staging app '{V2_APP}' is not deployed/reachable.")
        log(report, "Deploy it first:  modal deploy modal/modal_olmocr_v2.py")
        _flush(report)
        sys.exit(2)
    log(report, f"  ✓ staging   {V2_APP}/{V2_FN} resolved")

    v1 = resolve(V1_APP, V1_FN)
    if v1 is None:
        log(report, f"ABORT: production app '{V1_APP}' is not deployed/reachable.")
        _flush(report)
        sys.exit(2)
    log(report, f"  ✓ production {V1_APP}/{V1_FN} resolved")
    log(report, "")
    return v2, v1


def analyze(markdown: str) -> dict:
    """Cheap, deterministic heuristics for table structure / math / text volume.

    NOTE: olmOCR emits tables as HTML <table> blocks, not GFM pipe-tables, so
    table structure is measured from HTML tags. GFM pipe rows are also counted in
    case a future model/version switches format.
    """
    lines = markdown.splitlines()
    # HTML tables (olmOCR's actual format)
    html_tables = len(re.findall(r"<table[ >]", markdown, re.IGNORECASE))
    html_rows = len(re.findall(r"<tr[ >]", markdown, re.IGNORECASE))
    # GFM pipe tables (fallback, in case output format changes)
    pipe_rows = sum(1 for ln in lines if ln.count("|") >= 2)
    # Math markers: $...$ / $$ / \( \) / \[ \]
    math_markers = len(re.findall(r"\$\$?|\\\(|\\\)|\\\[|\\\]", markdown))
    headings = [ln for ln in lines if ln.lstrip().startswith("#")]
    # Checkbox glyph fidelity: proper ☐/☑ vs ASCII "[ ]" fallback
    checkbox_glyphs = len(re.findall(r"[☐☑✓✗]", markdown))
    return {
        "chars": len(markdown),
        "lines": len(lines),
        "headings": len(headings),
        "tables": html_tables,
        "table_rows": html_rows,
        "pipe_rows": pipe_rows,
        "checkbox_glyphs": checkbox_glyphs,
        "math_markers": math_markers,
    }


def run_endpoint(name: str, fn, pdf_bytes: bytes, filename: str, report: list[str]) -> dict | None:
    log(report, f"── {name} ──────────────────────────────────────────────────")
    t0 = time.time()
    try:
        result = fn.remote(pdf_bytes, filename)
    except Exception as e:  # noqa: BLE001
        elapsed = time.time() - t0
        log(report, f"  ✗ FAILED after {elapsed:.0f}s: {type(e).__name__}: {e}")
        log(report, "")
        return None
    elapsed = time.time() - t0
    slow = " ⚠️ SLOW" if elapsed > SLOW_THRESHOLD_SEC else ""
    log(report, f"  ✓ completed in {elapsed:.0f}s{slow}")
    log(report, f"    model reported: {result.get('model', '(none — v1 implicit default)')}")
    log(report, f"    pages: {result.get('page_count')}")
    result["_elapsed"] = elapsed
    return result


def _flush(report: list[str]) -> Path:
    OUTPUT_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = OUTPUT_DIR / f"olmocr_v1_v2_comparison_{ts}.log"
    path.write_text("\n".join(report) + "\n")
    print(f"\n📄 Comparison report written to: {path}")
    return path


def emit_metrics(report: list[str], m1: dict | None, m2: dict) -> None:
    """Render the v1/v2 metrics table into the report."""
    metrics = [
        "chars",
        "lines",
        "headings",
        "tables",
        "table_rows",
        "checkbox_glyphs",
        "math_markers",
    ]
    log(report, f"  {'metric':<16}{'v1 (prod)':>12}{'v2 (staging)':>14}{'Δ':>8}")
    for k in metrics:
        v2v = m2[k]
        v1v = m1[k] if m1 else 0
        log(report, f"  {k:<16}{v1v:>12}{v2v:>14}{v2v - v1v:>+8}")
    log(report, "")
    log(report, "  tables/table_rows: HTML <table>/<tr> structure recovered (olmOCR emits")
    log(report, "  HTML tables, not pipe tables). checkbox_glyphs: proper ☐/☑ vs ASCII '[ ]'")
    log(report, "  fallback. math_markers: LaTeX-style math. Numbers guide review — always")
    log(report, "  eyeball the saved .md files for structural accuracy before promoting v2.")


def score_files(path1: str, path2: str) -> None:
    """Offline mode: recompute metrics from two saved .md files (no Modal calls)."""
    report: list[str] = []
    p1, p2 = Path(path1), Path(path2)
    log(report, "── OFFLINE RE-SCORE (no Modal calls) ───────────────────────")
    log(report, f"  v1 file: {p1}")
    log(report, f"  v2 file: {p2}")
    log(report, "")
    m1 = analyze(p1.read_text()) if p1.exists() else None
    m2 = analyze(p2.read_text())
    emit_metrics(report, m1, m2)
    _flush(report)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--pdf", default=str(DEFAULT_PDF), help="PDF to compare (default: IRS Schedule C)"
    )
    ap.add_argument(
        "--score-files",
        nargs=2,
        metavar=("V1_MD", "V2_MD"),
        help="Offline: recompute metrics from two saved .md files, no Modal calls",
    )
    args = ap.parse_args()

    if args.score_files:
        score_files(*args.score_files)
        return

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        print(f"❌ PDF not found: {pdf_path}")
        sys.exit(1)

    report: list[str] = []
    log(report, "=" * 62)
    log(report, "olmOCR v1 (prod) vs olmOCR-2 (staging) comparison")
    log(report, f"timestamp: {datetime.now().isoformat(timespec='seconds')}")
    log(report, f"pdf:       {pdf_path.name} ({pdf_path.stat().st_size:,} bytes)")
    log(report, "=" * 62)
    log(report, "")

    v2, v1 = health_check(report)

    pdf_bytes = pdf_path.read_bytes()

    # Staging first: if it's broken, we abort before spending on production.
    r2 = run_endpoint("olmOCR-2 STAGING (olmocr-v2)", v2, pdf_bytes, pdf_path.name, report)
    if r2 is None:
        log(report, "ABORT: staging extraction failed — not proceeding to production comparison.")
        _flush(report)
        sys.exit(3)
    if r2.get("model") != EXPECTED_V2_MODEL:
        log(
            report,
            f"  ⚠️ staging returned model {r2.get('model')!r}, expected {EXPECTED_V2_MODEL!r}",
        )

    r1 = run_endpoint("olmOCR v1 PROD (olmocr)", v1, pdf_bytes, pdf_path.name, report)
    if r1 is None:
        log(report, "NOTE: production extraction failed; staging output still saved below.")

    # Save raw markdown for manual inspection (output/ only).
    OUTPUT_DIR.mkdir(exist_ok=True)
    stem = pdf_path.stem
    (OUTPUT_DIR / f"{stem}_v2_olmocr2.md").write_text(r2["markdown"])
    if r1:
        (OUTPUT_DIR / f"{stem}_v1_olmocr.md").write_text(r1["markdown"])

    # Metrics table
    log(report, "")
    log(report, "── QUALITY COMPARISON ──────────────────────────────────────")
    m2 = analyze(r2["markdown"])
    m1 = analyze(r1["markdown"]) if r1 else None
    emit_metrics(report, m1, m2)
    log(report, "")
    if r1:
        log(report, f"  timing: v1 {r1['_elapsed']:.0f}s vs v2 {r2['_elapsed']:.0f}s")
    log(report, "")
    log(report, "Saved outputs:")
    log(report, f"  {OUTPUT_DIR / f'{stem}_v2_olmocr2.md'}")
    if r1:
        log(report, f"  {OUTPUT_DIR / f'{stem}_v1_olmocr.md'}")

    _flush(report)


if __name__ == "__main__":
    main()
