"""
Tests for src/pointcheck_scorer.py — PointCheck Layer-1 ports.

Verification criteria from docs/POINTCHECK_INTEGRATION.md (Phase 1):
  1. No false positives on clean, document-shaped HTML (including the
     web-noise prunes: skip links, <nav> landmark, 24px touch targets).
  2. Genuine findings fire on HTML with known planted issues that axe-core's
     ruleset misses (filename alt text, vague links, javascript: links,
     positive tabindex, alpha-composited contrast failures).

These launch a real headless Chromium per call (same as loop.axe_score),
so they are integration tests, not pure unit tests.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pointcheck_scorer import pointcheck_score  # noqa: E402

# A document with planted issues that axe-core does NOT flag.
KNOWN_BAD_HTML = """<!DOCTYPE html>
<html lang="en">
<head><title>Quarterly Report 2026</title></head>
<body>
<main>
  <h1>Quarterly Report</h1>

  <!-- filename-style alt text: axe passes (alt exists), PointCheck flags -->
  <img src="chart.png" alt="img_042.png" width="300" height="200">

  <!-- vague link text -->
  <p>For details see <a href="/appendix">click here</a>.</p>

  <!-- javascript: href -->
  <p><a href="javascript:void(0)">Open the appendix</a></p>

  <!-- positive tabindex -->
  <p><a href="/section2" tabindex="3">Section two of the report</a></p>

  <!-- duplicate IDs -->
  <p id="note">First note</p>
  <p id="note">Second note</p>

  <!-- click handler on a non-interactive element, not keyboard reachable -->
  <div onclick="expand()">Expand the revenue table</div>

  <!-- alpha-composited contrast failure: the DIV's rgba(0,0,0,0.85) over the
       white body renders a near-black background; #333 text on it is ~1.2:1.
       A checker reading backgroundColor naively can miss the composite. -->
  <div style="background-color: rgba(0,0,0,0.85); padding: 10px;">
    <p style="color: #333333;">Fine print rendered on a composited dark background</p>
  </div>
</main>
</body>
</html>"""

# Shaped like happypdf output: lang, descriptive title, single h1, one <main>,
# descriptive alt and link text, unique IDs, default styling. Deliberately has
# NO skip link, NO <nav>, and >=5 ordinary inline links — the web-noise cases
# that must be pruned, not reported, on a converted document.
CLEAN_DOCUMENT_HTML = """<!DOCTYPE html>
<html lang="en">
<head><title>Course Syllabus — Biology 101</title></head>
<body>
<main>
  <h1>Course Syllabus</h1>
  <h2>Reading list</h2>
  <p>See the <a href="/textbook">required textbook chapter list</a> and the
     <a href="/schedule">weekly lecture schedule</a> before the first class.</p>
  <ul>
    <li><a href="/lab-safety">Lab safety requirements</a></li>
    <li><a href="/office-hours">Instructor office hours</a></li>
    <li><a href="/grading">Grading rubric and policies</a></li>
  </ul>
  <h2>Figures</h2>
  <img src="cell.png" alt="Diagram of a plant cell with labeled organelles" width="300" height="200">
  <table>
    <tr><th>Week</th><th>Topic</th></tr>
    <tr><td>1</td><td>Cell structure</td></tr>
  </table>
</main>
</body>
</html>"""


def test_known_bad_document_findings():
    result = pointcheck_score(KNOWN_BAD_HTML)
    criteria = {f["criterion"] for f in result["findings"]}

    assert "1.1.1" in criteria, "filename-style alt text should be flagged"
    assert "2.4.4" in criteria, "vague 'click here' link should be flagged"
    assert "2.1.1" in criteria, "javascript: link / mouse-only handler should be flagged"
    assert "2.4.3" in criteria, "positive tabindex should be flagged"
    assert "4.1.1" in criteria, "duplicate IDs should be flagged"
    assert "1.4.3" in criteria, "alpha-composited contrast failure should be flagged"

    # counts must agree with findings
    assert sum(result["counts"].values()) == len(result["findings"])


def test_clean_document_has_no_findings():
    result = pointcheck_score(CLEAN_DOCUMENT_HTML)
    assert result["findings"] == [], (
        "clean document-shaped HTML should produce zero findings, got: "
        + "; ".join(f"{f['criterion']} {f['description']}" for f in result["findings"])
    )
    # The web-noise cases (no skip link on a doc with links; inline links
    # smaller than 24px) must have fired in JS and been pruned in Python.
    assert result["pruned_as_document_noise"] >= 1
    # Contrast walk actually sampled elements (the check ran, found nothing).
    assert result["contrast_elements_checked"] > 0


def test_result_shape():
    result = pointcheck_score(CLEAN_DOCUMENT_HTML)
    assert set(result["counts"].keys()) == {"critical", "serious", "moderate", "minor"}
    for f in pointcheck_score(KNOWN_BAD_HTML)["findings"]:
        assert {"check", "criterion", "severity", "description", "examples", "fix"} <= set(f)
