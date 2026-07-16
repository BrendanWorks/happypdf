"""
Visual fidelity gate — PointCheck Phase 3 (see docs/POINTCHECK_INTEGRATION.md).

Answers the question no output-side check can: did content survive the
PDF -> HTML conversion? The pipeline's preservation gate (src/gate.py)
compares extracted-vs-patched, so anything olmOCR dropped BEFORE the HTML
existed is invisible to it.

Design (v1 = content inventory, not position comparison):
  PDF side   — each page is rendered to PNG and inventoried by Molmo-7B-D
               ("alttext-judge" Modal app, judge_page_fidelity): image count,
               table count, chart presence, text presence. Vision is needed
               here because the PDF is unstructured.
  HTML side  — counted structurally from the DOM (no vision, no GPU): the
               produced document is ours and fully machine-readable.
  Compare    — LOSS-ONLY findings with tolerances (see _compare): we flag
               "the PDF appears to have N tables, the output has fewer",
               never surpluses. VLM counting is imperfect; tolerances are
               calibrated against the benchmark corpus (see the design doc's
               Phase 3 verification and tests/test_fidelity_gate.py).

Report-only: results land in the job record's `fidelity` block and never
touch axe scores, gates, or convergence. Failure must never fail a job —
callers wrap in try/except, and this module degrades per-page.
"""

from __future__ import annotations

import base64
from datetime import datetime

import modal

FIDELITY_APP, FIDELITY_FN = "alttext-judge", "judge_page_fidelity"

# Pages beyond this are skipped (noted in the block) to bound GPU time.
MAX_PAGES = 10
# Render DPI: a US-letter page at 110dpi is ~935px wide — right at the judge's
# 896px input cap, so no detail is wasted on pixels the model never sees.
RENDER_DPI = 110

# A page whose embedded text layer has fewer characters than this, but which
# the vision model says is text-heavy, is likely a scanned page (text rendered
# as an image) — the worst accessibility failure mode.
SCANNED_TEXT_CHARS_THRESHOLD = 50


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------------------------------------------------------------------------
# PDF side
# ---------------------------------------------------------------------------

def render_pdf_pages(pdf_bytes: bytes, max_pages: int = MAX_PAGES) -> list[dict]:
    """Render pages to PNG for the vision inventory.

    Returns [{"page_number", "image_b64", "text_chars"}]; text_chars comes
    from the PDF's embedded text layer and powers scanned-page detection.
    """
    import fitz

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pages = []
    for i in range(min(doc.page_count, max_pages)):
        page = doc[i]
        pix = page.get_pixmap(dpi=RENDER_DPI)
        pages.append(
            {
                "page_number": i + 1,
                "image_b64": base64.b64encode(pix.tobytes("png")).decode(),
                "text_chars": len("".join(page.get_text().split())),
            }
        )
    total = doc.page_count
    doc.close()
    log(f"fidelity: rendered {len(pages)}/{total} page(s) at {RENDER_DPI}dpi")
    return pages


def analyze_pdf_pages(pdf_bytes: bytes) -> dict | None:
    """PDF-side inventory: render pages, run the vision battery remotely.

    Safe to start as soon as the upload is validated — it does not depend on
    extraction or the review loop, so its GPU cold start can overlap both.
    Returns {"pages": [...merged render+vision...], "pages_total": int,
    "pages_analyzed": int} or None if the PDF has no readable pages.
    """
    import fitz

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pages_total = doc.page_count
    doc.close()

    rendered = render_pdf_pages(pdf_bytes)
    if not rendered:
        return None

    log(f"fidelity: calling Modal {FIDELITY_APP}/{FIDELITY_FN} for {len(rendered)} page(s)...")
    fn = modal.Function.from_name(FIDELITY_APP, FIDELITY_FN)
    vision = fn.remote([{"page_number": p["page_number"], "image_b64": p["image_b64"]} for p in rendered])

    by_page = {v["page_number"]: v for v in vision}
    pages = []
    for p in rendered:
        v = by_page.get(p["page_number"], {})
        pages.append(
            {
                "page_number": p["page_number"],
                "text_chars": p["text_chars"],
                "images": v.get("images"),
                "tables": v.get("tables"),
                "has_chart": v.get("has_chart"),
                "text_heavy": v.get("text_heavy"),
                "success": v.get("success", False),
            }
        )
    return {"pages": pages, "pages_total": pages_total, "pages_analyzed": len(pages)}


# ---------------------------------------------------------------------------
# HTML side (structural — no vision)
# ---------------------------------------------------------------------------

def html_inventory(html_str: str) -> dict:
    """Count content-bearing elements in the produced document."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html_str, "html.parser")
    return {
        "images": len(soup.find_all("img")),
        "tables": len(soup.find_all("table")),
        "text_chars": len("".join(soup.get_text().split())),
    }


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------

def _compare(pdf_result: dict, html_inv: dict) -> list[dict]:
    """Loss-only findings with tolerances.

    Rules (calibrated against the benchmark corpus — see tests):
      - images: flag only when the PDF-side count exceeds the HTML's by >=2,
        OR the PDF clearly has images and the HTML has none. VLM counts
        wobble by one (headers, rules, and watermarks get miscounted), so a
        difference of exactly 1 is below the noise floor.
      - tables: flag only when the PDF-side count exceeds the HTML's AND at
        least half the analyzed pages agreed a table exists. Form-shaped
        documents (e.g. IRS forms) look table-like to a VLM; requiring
        cross-page agreement keeps single-page hallucinated tables quiet.
      - scanned text: any page the model calls text-heavy whose embedded
        text layer is near-empty (< SCANNED_TEXT_CHARS_THRESHOLD chars).
      - scanned documents SUPPRESS the count comparisons: on a scanned page
        the vision model counts photos INSIDE the page scan while the HTML
        counts extracted raster objects — different units (calibration:
        navy_bulletin measured ~23 visual figures vs 11 page-scan rasters,
        both "correct"). The scanned-text finding, which is the more accurate
        and more severe signal, carries the message instead.
    """
    findings: list[dict] = []
    pages = [p for p in pdf_result["pages"] if p["success"]]
    if not pages:
        return findings

    scanned = [
        p["page_number"]
        for p in pages
        if p["text_heavy"] and p["text_chars"] < SCANNED_TEXT_CHARS_THRESHOLD
    ]
    if scanned:
        findings.append(
            {
                "type": "text_rendered_as_image",
                "severity": "critical",
                "description": (
                    f"Page(s) {scanned} appear to contain substantial text but have almost "
                    "no machine-readable text layer — likely scanned pages. Verify the "
                    "extracted content for these pages carefully."
                ),
            }
        )
        # Count basis is unreliable for scan-composed documents — stop here.
        return findings

    pdf_images = sum(p["images"] for p in pages if p["images"] is not None)
    pdf_tables = sum(p["tables"] for p in pages if p["tables"] is not None)
    pages_with_tables = sum(1 for p in pages if (p["tables"] or 0) > 0)

    if (pdf_images >= 2 and html_inv["images"] == 0) or (
        pdf_images - html_inv["images"] >= 2
    ):
        findings.append(
            {
                "type": "possible_missing_images",
                "severity": "serious",
                "description": (
                    f"The original PDF appears to contain ~{pdf_images} image(s)/figure(s) "
                    f"across {len(pages)} analyzed page(s); the converted document has "
                    f"{html_inv['images']}. Some figures may have been dropped during extraction."
                ),
            }
        )

    if pdf_tables > html_inv["tables"] and pages_with_tables * 2 >= len(pages):
        findings.append(
            {
                "type": "possible_missing_tables",
                "severity": "serious",
                "description": (
                    f"The original PDF appears to contain ~{pdf_tables} table(s); the "
                    f"converted document has {html_inv['tables']}. Tables may have been "
                    "flattened to plain text during extraction."
                ),
            }
        )

    return findings


def compare_with_html(pdf_result: dict | None, final_html: str) -> dict:
    """Combine the (possibly None/partial) PDF inventory with the HTML's.

    Pure local computation — instant, so it runs post-convergence without
    adding wall-clock time; the GPU half (analyze_pdf_pages) runs earlier.
    """
    if not pdf_result:
        return {"status": "unavailable", "findings": []}

    html_inv = html_inventory(final_html)
    findings = _compare(pdf_result, html_inv)
    analyzed = [p for p in pdf_result["pages"] if p["success"]]
    return {
        "status": "ok" if analyzed else "unavailable",
        "method": (
            "Molmo-7B-D content inventory of each original PDF page, compared "
            "against the converted document's structure (loss-only, calibrated "
            "tolerances)"
        ),
        "pages_total": pdf_result["pages_total"],
        "pages_analyzed": len(analyzed),
        "pdf_inventory": {
            "images": sum(p["images"] for p in analyzed if p["images"] is not None),
            "tables": sum(p["tables"] for p in analyzed if p["tables"] is not None),
            "pages_with_charts": sum(1 for p in analyzed if p["has_chart"]),
        },
        "html_inventory": html_inv,
        "findings": findings,
        "per_page": pdf_result["pages"],
    }
