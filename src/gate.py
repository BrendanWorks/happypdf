#!/usr/bin/env python3
"""
Content-preservation gate: verify a remediation round did not damage the document.

Remediation should make HTML *more* accessible without losing or corrupting
content. This gate compares the original (pre-round) HTML to the patched HTML
and fails the round if any preservation check is violated. A failing round does
NOT count as progress — the caller logs it and bails before the next round.

Checks
------
  text_coverage   : patched visible-text word count >= 95% of original
  image_count     : number of <img> must not decrease
  heading_order   : patched heading levels must not skip (e.g. h1 -> h3 is invalid)
  table_structure : if the original had tables, the patched HTML must still have them

Pure Python + lxml. No LLM calls.

Run
---
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
OUT_LOG = ROOT / "output" / "preservation_gate.json"

TEXT_COVERAGE_MIN = 0.95


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
    """Heading levels in document order, e.g. [1, 2, 2, 3]."""
    nodes = doc.xpath("//h1 | //h2 | //h3 | //h4 | //h5 | //h6")
    return [int(n.tag[1]) for n in nodes]


def _count(doc, tag: str) -> int:
    return len(doc.xpath(f"//{tag}"))


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------
def check_text_coverage(orig, patched) -> dict:
    o, p = _visible_word_count(orig), _visible_word_count(patched)
    coverage = (p / o) if o else 1.0
    return {
        "name": "text_coverage", "passed": coverage >= TEXT_COVERAGE_MIN,
        "original_words": o, "patched_words": p,
        "coverage": round(coverage, 4), "threshold": TEXT_COVERAGE_MIN,
    }


def check_image_count(orig, patched) -> dict:
    o, p = _count(orig, "img"), _count(patched, "img")
    return {"name": "image_count", "passed": p >= o, "original": o, "patched": p}


def check_heading_order(orig, patched) -> dict:
    levels = _heading_levels(patched)
    skips, prev = [], None
    for lvl in levels:
        if prev is not None and lvl > prev + 1:
            skips.append({"from": prev, "to": lvl})
        prev = lvl
    return {"name": "heading_order", "passed": not skips,
            "sequence": levels, "skips": skips}


def check_table_structure(orig, patched) -> dict:
    o, p = _count(orig, "table"), _count(patched, "table")
    # Only a constraint if the original had tables.
    return {"name": "table_structure", "passed": (p >= o) if o else True,
            "original": o, "patched": p}


CHECKS = (check_text_coverage, check_image_count, check_heading_order, check_table_structure)


def run_gate(original_html: str, patched_html: str) -> dict:
    orig = html.document_fromstring(original_html)
    patched = html.document_fromstring(patched_html)
    results = [c(orig, patched) for c in CHECKS]
    passed = all(r["passed"] for r in results)
    return {"passed": passed, "checks": results,
            "failed_checks": [r["name"] for r in results if not r["passed"]]}


def main() -> int:
    ap = argparse.ArgumentParser(description="Content-preservation gate for a remediation round.")
    ap.add_argument("--original", type=Path, default=DEFAULT_ORIGINAL)
    ap.add_argument("--patched", type=Path, default=DEFAULT_PATCHED)
    args = ap.parse_args()

    log("=" * 70)
    log(f"Preservation gate  original={args.original.name}  patched={args.patched.name}")
    if not args.original.exists() or not args.patched.exists():
        log("FATAL: missing original or patched HTML")
        return 1

    result = run_gate(args.original.read_text(), args.patched.read_text())
    OUT_LOG.parent.mkdir(parents=True, exist_ok=True)
    OUT_LOG.write_text(json.dumps(result, indent=2))

    for c in result["checks"]:
        mark = "✓" if c["passed"] else "✗"
        log(f"  {mark} {c['name']}: " + ", ".join(
            f"{k}={v}" for k, v in c.items() if k not in ("name", "passed")))
    log("=" * 70)
    if result["passed"]:
        log("GATE PASSED — round preserved content; safe to continue")
        return 0
    log(f"GATE FAILED — {result['failed_checks']} — round does NOT count as progress")
    return 3


if __name__ == "__main__":
    sys.exit(main())
