#!/usr/bin/env python3
"""Adversarial edge-case tests for the content-preservation gate.

Run: python tests/test_gate_edges.py   (exit 0 = all pass)
Each case mutates a known-good baseline and asserts the gate verdict.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import gate  # noqa: E402

BASE = (ROOT / "output" / "syllabus_scored.html").read_text()

DOC = """<!DOCTYPE html><html lang="en"><body><main>
<h1 data-ir-id="a">Title</h1>
<h2 data-ir-id="b">Section</h2>
<p data-ir-id="c">{p1}</p>
<table data-ir-id="t"><tr><th>H</th></tr><tr><td>1</td></tr></table>
<img data-ir-id="i" src="x.png" alt="a logo">
</main></body></html>"""

GOOD = DOC.format(p1="one two three four five six seven eight nine ten")


def check(name, original, patched, expect_pass, expect_failed=None):
    res = gate.run_gate(original, patched)
    ok = res["passed"] == expect_pass
    if expect_failed is not None:
        ok = ok and (expect_failed in res["failed_checks"])
    status = "PASS" if ok else "FAIL"
    print(f"  [{status}] {name}: passed={res['passed']} failed={res['failed_checks']}")
    return ok


def main() -> int:
    results = []

    # 1. Identity — patched == original → gate passes.
    results.append(check("identity passes", GOOD, GOOD, True))

    # 2. Empty patched document → text_coverage fails.
    empty = "<!DOCTYPE html><html><body><main></main></body></html>"
    results.append(check("empty patched fails coverage", GOOD, empty, False, "text_coverage"))

    # 3. Text loss below 95% (drop most words) → text_coverage fails.
    thin = DOC.format(p1="one")
    results.append(check("text loss fails coverage", GOOD, thin, False, "text_coverage"))

    # 4. Deleted table → table_structure fails.
    no_table = GOOD.replace('<table data-ir-id="t"><tr><th>H</th></tr><tr><td>1</td></tr></table>', "")
    results.append(check("deleted table fails", GOOD, no_table, False, "table_structure"))

    # 5. Removed image → image_count fails.
    no_img = GOOD.replace('<img data-ir-id="i" src="x.png" alt="a logo">', "")
    results.append(check("removed image fails", GOOD, no_img, False, "image_count"))

    # 6. Heading skip h1->h3 → heading_order fails.
    skip = GOOD.replace('<h2 data-ir-id="b">Section</h2>', '<h3 data-ir-id="b">Section</h3>')
    results.append(check("h1->h3 skip fails", GOOD, skip, False, "heading_order"))

    # 7. Added images (none -> some) is allowed (count must not *decrease*).
    more_img = GOOD.replace("</main>", '<img data-ir-id="i2" src="y.png" alt="b"></main>')
    results.append(check("added image passes", GOOD, more_img, True))

    # 8. Pure ARIA annotation (the real remediation) preserves everything.
    annotated = GOOD.replace('<table data-ir-id="t">', '<table data-ir-id="t" aria-label="Data">')
    results.append(check("aria annotation passes", GOOD, annotated, True))

    print(f"\n{sum(results)}/{len(results)} edge cases passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
