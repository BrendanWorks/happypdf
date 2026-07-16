"""
Tests for the fidelity gate (PointCheck Phase 3) — the GPU-free parts.

Covers parse_fidelity_response, html_inventory, PDF page rendering, and the
loss-only comparison rules including the calibration decisions:
  - off-by-one image differences are below the VLM noise floor
  - hallucinated single-page tables need cross-page agreement
  - scanned documents suppress count comparisons entirely (navy_bulletin
    calibration: the model counts figures INSIDE a page scan while the HTML
    counts extracted rasters — different units)

The Modal vision function is validated by the calibration run documented in
docs/POINTCHECK_INTEGRATION.md Phase 3 and the staging e2e.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "modal"))
sys.path.insert(0, str(ROOT / "src"))

import fidelity_gate as fg  # noqa: E402
from modal_alttext_judge import parse_fidelity_response  # noqa: E402

# ---------------------------------------------------------------------------
# parse_fidelity_response
# ---------------------------------------------------------------------------


def test_parse_fidelity_well_formed():
    out = parse_fidelity_response("IMAGES: 3\nTABLES: 1\nCHART: yes\nTEXT: no")
    assert out == {"images": 3, "tables": 1, "has_chart": True, "text_heavy": False}


def test_parse_fidelity_spelled_out_zero():
    out = parse_fidelity_response("IMAGES: none\nTABLES: 0\nCHART: no\nTEXT: yes")
    assert out["images"] == 0 and out["tables"] == 0


def test_parse_fidelity_garbage_gives_unknowns():
    out = parse_fidelity_response("This page shows a lovely sunset.")
    assert out == {"images": None, "tables": None, "has_chart": None, "text_heavy": None}


def test_parse_fidelity_caps_absurd_counts():
    assert parse_fidelity_response("IMAGES: 90000")["images"] == 50


# ---------------------------------------------------------------------------
# html_inventory + rendering
# ---------------------------------------------------------------------------


def test_html_inventory_counts():
    html = """<html><body><main>
      <img src="a.png" alt="a"><img src="b.png" alt="b">
      <table><tr><td>x</td></tr></table>
      <p>Hello world</p></main></body></html>"""
    inv = fg.html_inventory(html)
    assert inv["images"] == 2
    assert inv["tables"] == 1
    assert inv["text_chars"] > 0


def test_render_pdf_pages_benchmark():
    pdf = (ROOT / "benchmark" / "syllabus_NOTaccessible.pdf").read_bytes()
    pages = fg.render_pdf_pages(pdf)
    assert len(pages) == 1
    assert pages[0]["page_number"] == 1
    assert pages[0]["text_chars"] > 100  # digital PDF has a text layer
    assert len(pages[0]["image_b64"]) > 1000


def test_render_pdf_pages_respects_cap():
    pdf = (ROOT / "benchmark" / "navy_bulletin.pdf").read_bytes()
    pages = fg.render_pdf_pages(pdf, max_pages=3)
    assert len(pages) == 3


# ---------------------------------------------------------------------------
# Comparison rules
# ---------------------------------------------------------------------------

HTML_ONE_IMG = '<html><body><img src="a.png" alt="a"><p>text here</p></body></html>'
HTML_EMPTY = "<html><body><p>text only document body</p></body></html>"


def _page(n, images=0, tables=0, chart=False, text=True, chars=1000, success=True):
    return {
        "page_number": n, "images": images, "tables": tables,
        "has_chart": chart, "text_heavy": text, "text_chars": chars,
        "success": success,
    }


def _result(pages):
    return {"pages": pages, "pages_total": len(pages), "pages_analyzed": len(pages)}


def test_clean_digital_doc_no_findings():
    block = fg.compare_with_html(_result([_page(1, images=1, tables=1)]),
                                 '<html><body><img alt="a"><table><tr><td>1</td></tr></table>'
                                 '<table><tr><td>2</td></tr></table></body></html>')
    assert block["status"] == "ok"
    assert block["findings"] == []


def test_missing_images_flagged():
    block = fg.compare_with_html(_result([_page(1, images=3)]), HTML_EMPTY)
    assert [f["type"] for f in block["findings"]] == ["possible_missing_images"]


def test_off_by_one_image_is_noise():
    block = fg.compare_with_html(_result([_page(1, images=2)]), HTML_ONE_IMG)
    assert block["findings"] == []


def test_missing_tables_needs_cross_page_agreement():
    # 1 of 3 pages claims a table — hallucination-shaped, must stay quiet.
    pages = [_page(1, tables=1), _page(2), _page(3)]
    assert fg.compare_with_html(_result(pages), HTML_EMPTY)["findings"] == []
    # 2 of 3 pages agree — flag it.
    pages = [_page(1, tables=1), _page(2, tables=1), _page(3)]
    types = [f["type"] for f in fg.compare_with_html(_result(pages), HTML_EMPTY)["findings"]]
    assert types == ["possible_missing_tables"]


def test_scanned_page_flagged_and_counts_suppressed():
    # Navy-bulletin shape: text-heavy pages with no text layer, and a huge
    # apparent image-count mismatch that must be suppressed.
    pages = [
        _page(1, images=5, chars=0),
        _page(2, images=5, chars=0),
        _page(3, images=5, chars=2000),
    ]
    block = fg.compare_with_html(_result(pages), HTML_ONE_IMG)
    types = [f["type"] for f in block["findings"]]
    assert types == ["text_rendered_as_image"]
    assert "[1, 2]" in block["findings"][0]["description"]


def test_unavailable_when_no_pdf_result():
    block = fg.compare_with_html(None, HTML_ONE_IMG)
    assert block["status"] == "unavailable"
    assert block["findings"] == []


def test_unavailable_when_all_pages_failed():
    pages = [_page(1, success=False)]
    block = fg.compare_with_html(_result(pages), HTML_ONE_IMG)
    assert block["status"] == "unavailable"
    assert block["findings"] == []
