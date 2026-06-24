#!/usr/bin/env python3
"""
Content-preservation gate: verify a remediation round did not damage the document.

Remediation should make HTML *more* accessible without losing or corrupting
content. This gate compares the original (pre-round) HTML to the patched HTML
and fails the round if any preservation check is violated. A failing round does
NOT count as progress — the caller logs it and bails before the next round.

Checks (every check reports before -> after numbers, not just pass/fail):
  text_coverage   : patched visible-text word count >= TEXT_COVERAGE_THRESHOLD of original
  image_count     : number of <img> must not decrease
  heading_order   : patched heading levels must not skip more than HEADING_SKIP_TOLERANCE
  table_structure : if the original had tables, the patched HTML must still have >= as many

Pure Python + lxml. No LLM calls. Writes output/gate_detailed.json for audit.

Run:
  python src/gate.py                                  # scored.html vs patched.html
  python src/gate.py --original A.html --patched B.html
Exit code: 0 = passed, 3 = gate failed, 1 = bad input.
"""

import argparse
import copy
import json
import sys
from datetime import datetime
from pathlib import Path

from lxml import html

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ORIGINAL = ROOT / "output" / "syllabus_scored.html"
DEFAULT_PATCHED = ROOT / "output" / "syllabus_patched.html"
OUT_DETAIL = ROOT / "output" / "gate_detailed.json"

# --- Thresholds (documented) ------------------------------------------------
# TEXT_COVERAGE_THRESHOLD: patched visible text must retain >= 95% of original
# words. Rationale: extraction + HTML generation legitimately drop a little
# trailing whitespace and visual-artifact text, so a few percent of slack avoids
# false positives. But losing a whole paragraph, list, or table is well over 5%
# of a typical page, so real content loss is caught. 0.90 would let an entire
# short section silently vanish; 0.99 would false-positive on benign whitespace
# normalization.
TEXT_COVERAGE_THRESHOLD = 0.95
# HEADING_SKIP_TOLERANCE: max allowed jump between consecutive heading levels.
# 1 permits h1->h2 (valid nesting) but fails h1->h3, which skips a level and
# breaks the screen-reader outline. 2 would permit h1->h3 (the exact defect we
# guard against); 0 would forbid any nesting at all.
HEADING_SKIP_TOLERANCE = 1


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------------------------------------------------------------------------
# Measurements
# ---------------------------------------------------------------------------
def _visible_word_count(doc) -> int:
    """Words of human-visible text — excludes <script>/<style> noise."""
    body = doc.find(".//body")
    root = copy.deepcopy(body if body is not None else doc)
    for bad in root.xpath(".//script | .//style"):
        bad.getparent().remove(bad)
    return len(root.text_content().split())


def _heading_levels(doc) -> list[int]:
    return [int(n.tag[1]) for n in doc.xpath("//h1 | //h2 | //h3 | //h4 | //h5 | //h6")]


def _count(doc, tag: str) -> int:
    return len(doc.xpath(f"//{tag}"))


def _table_shapes(doc) -> list[dict]:
    """Per-table row/cell counts, for describing structural change."""
    shapes = []
    for t in doc.xpath("//table"):
        shapes.append({"rows": len(t.xpath(".//tr")), "cells": len(t.xpath(".//td | .//th"))})
    return shapes


# ---------------------------------------------------------------------------
# Checks — each returns before/after numbers and a human-readable detail line
# ---------------------------------------------------------------------------
def check_text_coverage(orig, patched) -> dict:
    o, p = _visible_word_count(orig), _visible_word_count(patched)
    coverage = (p / o) if o else (1.0 if p == 0 else 1.0)
    # An empty original with surviving content is fine; an empty *patched* is not.
    passed = coverage >= TEXT_COVERAGE_THRESHOLD and (p > 0 or o == 0)
    return {
        "name": "text_coverage", "passed": passed,
        "original_words": o, "patched_words": p,
        "coverage": round(coverage, 4), "threshold": TEXT_COVERAGE_THRESHOLD,
        "detail": f"{o} -> {p} words ({coverage:.1%}); threshold {TEXT_COVERAGE_THRESHOLD:.0%}",
    }


def check_image_count(orig, patched) -> dict:
    o, p = _count(orig, "img"), _count(patched, "img")
    return {"name": "image_count", "passed": p >= o, "original": o, "patched": p,
            "detail": f"{o} -> {p} images (must not decrease)"}


def check_heading_order(orig, patched) -> dict:
    before, after = _heading_levels(orig), _heading_levels(patched)
    skips, prev = [], None
    for lvl in after:
        if prev is not None and (lvl - prev) > HEADING_SKIP_TOLERANCE:
            skips.append({"from": prev, "to": lvl})
        prev = lvl
    return {"name": "heading_order", "passed": not skips,
            "original_sequence": before, "patched_sequence": after,
            "tolerance": HEADING_SKIP_TOLERANCE, "skips": skips,
            "detail": f"before {before} -> after {after}; skips {skips or 'none'}"}


def check_table_structure(orig, patched) -> dict:
    o, p = _count(orig, "table"), _count(patched, "table")
    passed = (p >= o) if o else True
    return {"name": "table_structure", "passed": passed, "original": o, "patched": p,
            "original_shapes": _table_shapes(orig), "patched_shapes": _table_shapes(patched),
            "detail": f"{o} -> {p} tables" + ("" if passed else " (TABLE LOST)")}


CHECKS = (check_text_coverage, check_image_count, check_heading_order, check_table_structure)


def run_gate(original_html: str, patched_html: str, *, write_detail: bool = False) -> dict:
    orig = html.document_fromstring(original_html)
    patched = html.document_fromstring(patched_html)
    results = [c(orig, patched) for c in CHECKS]
    passed = all(r["passed"] for r in results)
    detail = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "passed": passed, "checks": results,
        "failed_checks": [r["name"] for r in results if not r["passed"]],
        "thresholds": {"text_coverage": TEXT_COVERAGE_THRESHOLD,
                       "heading_skip_tolerance": HEADING_SKIP_TOLERANCE},
    }
    if write_detail:
        OUT_DETAIL.parent.mkdir(parents=True, exist_ok=True)
        OUT_DETAIL.write_text(json.dumps(detail, indent=2))
    # Keep the lightweight keys the loop already relies on.
    return {"passed": passed, "checks": results, "failed_checks": detail["failed_checks"]}


def main() -> int:
    ap = argparse.ArgumentParser(description="Content-preservation gate for a remediation round.")
    ap.add_argument("--original", type=Path, default=DEFAULT_ORIGINAL)
    ap.add_argument("--patched", type=Path, default=DEFAULT_PATCHED)
    args = ap.parse_args()

    log("=" * 72)
    log(f"Preservation gate  original={args.original.name}  patched={args.patched.name}")
    if not args.original.exists() or not args.patched.exists():
        log("FATAL: missing original or patched HTML")
        return 1

    result = run_gate(args.original.read_text(), args.patched.read_text(), write_detail=True)
    for c in result["checks"]:
        log(f"  {'✓' if c['passed'] else '✗'} {c['name']}: {c['detail']}. "
            f"{'PASS' if c['passed'] else 'FAIL'}")
    log("=" * 72)
    if result["passed"]:
        log(f"GATE PASSED — round preserved content (detail: {OUT_DETAIL})")
        return 0
    log(f"GATE FAILED — {result['failed_checks']} — round does NOT count as progress")
    return 3


if __name__ == "__main__":
    sys.exit(main())
