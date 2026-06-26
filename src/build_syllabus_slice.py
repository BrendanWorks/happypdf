#!/usr/bin/env python3
"""
AccessComputing syllabus -> scored accessible HTML, full pipeline orchestrator.

Pipeline:
    1. Load syllabus_NOTaccessible.pdf
    2. olmOCR (Modal "olmocr"/process_pdf)            -> markdown
    3. PyMuPDF                                         -> embedded images
    4. Qwen2-VL (Modal "pdfaccess-alttext")            -> alt text per image
    5. Markdown + alt text                             -> semantic HTML5
    6. axe-core via Playwright (real Chromium)         -> accessibility audit
    7. Write syllabus_scored.html (with audit summary comment block)
    8. Write syllabus_axe_baseline.json (raw axe-core output)

Run with the venv that has PyMuPDF + Playwright + modal:
    venv/bin/python build_syllabus_slice.py
"""

import base64
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import fitz  # PyMuPDF
import modal

# src/ lives under the repo root; inputs come from benchmark/, outputs go to output/.
ROOT = Path(__file__).resolve().parent.parent
INPUT_PDF = ROOT / "benchmark" / "syllabus_NOTaccessible.pdf"
OUTPUT_DIR = ROOT / "output"
OUT_HTML = OUTPUT_DIR / "syllabus_scored.html"
OUT_AXE = OUTPUT_DIR / "syllabus_axe_baseline.json"
IMG_DIR = OUTPUT_DIR / "syllabus_images"
CACHE_MD = OUTPUT_DIR / "syllabus_olmocr.md"      # cached olmOCR markdown
CACHE_ALT = OUTPUT_DIR / "syllabus_alt.json"      # cached alt-text map

# axe-core from a local npm install (repo root) or a shared parent install.
AXE_CANDIDATES = [
    ROOT / "node_modules/axe-core/axe.min.js",
    Path("/Users/brendanworks/node_modules/axe-core/axe.min.js"),
]

OLMOCR_APP, OLMOCR_FN = "olmocr", "process_pdf"
ALTTEXT_APP, ALTTEXT_FN = "pdfaccess-alttext", "generate_alt_text"


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------------------------------------------------------------------------
# Step 2: olmOCR
# ---------------------------------------------------------------------------
def run_olmocr(pdf_bytes: bytes, filename: str) -> str:
    log(f"olmOCR: calling Modal {OLMOCR_APP}/{OLMOCR_FN} ({len(pdf_bytes):,} bytes)...")
    fn = modal.Function.from_name(OLMOCR_APP, OLMOCR_FN)
    result = fn.remote(pdf_bytes, filename)
    md = result.get("markdown", "")
    log(f"olmOCR: ok, {len(md):,} chars, ~{result.get('page_count', '?')} pages")
    return md


def strip_front_matter(md: str) -> str:
    """olmOCR appends a YAML metadata block fenced by '---'. Drop metadata
    blocks (the ones carrying olmocr keys) while keeping real content."""
    blocks = re.split(r"(?m)^---\s*$", md)
    kept = []
    meta_keys = ("primary_language", "is_rotation_valid", "rotation_correction",
                 "is_table", "is_diagram", "total-input-tokens", "Page dimensions")
    for b in blocks:
        if any(k in b for k in meta_keys) and ":" in b:
            continue  # metadata block, drop it
        if b.strip():
            kept.append(b.strip())
    return "\n\n".join(kept).strip()


# ---------------------------------------------------------------------------
# Step 3: image extraction (PyMuPDF)
# ---------------------------------------------------------------------------
def extract_images(pdf_path: Path) -> list[dict]:
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(pdf_path)
    images = []
    seen_xrefs = set()
    for page_idx in range(doc.page_count):
        page = doc[page_idx]
        ctx = " ".join(page.get_text().split())[:150]
        for img in page.get_images(full=True):
            xref = img[0]
            if xref in seen_xrefs:
                continue
            seen_xrefs.add(xref)
            base = doc.extract_image(xref)
            ext = base.get("ext", "png")
            data = base["image"]
            fname = f"syllabus_img_{len(images) + 1}.{ext}"
            (IMG_DIR / fname).write_bytes(data)
            images.append({
                "filename": fname,
                "path": IMG_DIR / fname,
                "b64": base64.b64encode(data).decode("utf-8"),
                "page": page_idx + 1,
                "context": ctx,
            })
    log(f"images: extracted {len(images)} from {doc.page_count} page(s)")
    doc.close()
    return images


# ---------------------------------------------------------------------------
# Step 4: alt text (Qwen2-VL)
# ---------------------------------------------------------------------------
def generate_alt_text(images: list[dict]) -> dict[str, dict]:
    if not images:
        return {}
    log(f"alt text: calling Modal {ALTTEXT_APP}/{ALTTEXT_FN} for {len(images)} image(s)...")
    fn = modal.Function.from_name(ALTTEXT_APP, ALTTEXT_FN)
    mapping = {}
    for img in images:
        res = fn.remote(img["b64"], img["context"])
        if not res.get("success"):
            log(f"  {img['filename']}: FAILED ({res.get('error', '?')[:80]}) -> filename fallback")
            res = {"alt_text": img["filename"], "requires_long_desc": False,
                   "confidence": 0.0, "success": False}
        else:
            log(f"  {img['filename']}: \"{res['alt_text'][:70]}\" (long_desc={res['requires_long_desc']})")
        mapping[img["filename"]] = res
    return mapping


# ---------------------------------------------------------------------------
# Step 5: Markdown + alt text -> semantic HTML5
# ---------------------------------------------------------------------------
class HtmlBuilder:
    def __init__(self, markdown: str, images: list[dict], alt_map: dict[str, dict], title: str = "Document"):
        self.lines = markdown.split("\n")
        self.images = images
        self.alt_map = alt_map
        self.title = title
        self.page = 1
        self.dup_ids: set[str] = set()
        self._seen: set[str] = set()

    def _id(self, text: str) -> str:
        key = " ".join(text[:200].split())
        h = hashlib.sha256(key.encode()).hexdigest()[:8]
        ident = f"block-{self.page}-{h}"
        if ident in self._seen:
            self.dup_ids.add(ident)
        self._seen.add(ident)
        return ident

    @staticmethod
    def _esc(t: str) -> str:
        return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    @classmethod
    def _attr(cls, t: str) -> str:
        # Attribute-safe: also escape the double-quote that delimits the value.
        return cls._esc(t).replace('"', "&quot;")

    def _heading(self, line: str):
        m = re.match(r"^(#+)\s+(.+)$", line)
        return (len(m.group(1)), m.group(2)) if m else (0, line)

    def build(self) -> str:
        body, in_list, items = [], False, []

        def flush_list():
            nonlocal in_list, items
            if in_list and items:
                body.append(f'    <ul data-ir-id="{self._id("ul:" + items[0])}">')
                for it in items:
                    body.append(f'      <li data-ir-id="{self._id(it)}">{self._esc(it)}</li>')
                body.append("    </ul>")
            in_list, items = False, []

        has_h1 = any(self._heading(l.strip())[0] == 1 for l in self.lines)
        i = 0
        while i < len(self.lines):
            raw = self.lines[i].strip()
            if not raw:
                flush_list()
                i += 1
                continue

            # Synthesize an <h1> from the first content line if olmOCR emitted none.
            if not has_h1:
                flush_list()
                body.append(f'    <h1 data-ir-id="{self._id(raw)}">{self._esc(raw)}</h1>')
                has_h1 = True
                i += 1
                continue

            lvl, text = self._heading(raw)
            if lvl > 0:
                flush_list()
                lvl = min(lvl, 6)
                body.append(f'    <h{lvl} data-ir-id="{self._id(text)}">{self._esc(text)}</h{lvl}>')
                i += 1
                continue

            if raw.startswith("<table"):
                flush_list()
                start = i
                while i < len(self.lines) and "</table>" not in self.lines[i]:
                    i += 1
                i = i + 1 if i < len(self.lines) else i
                tbl = "\n".join(self.lines[start:i])
                tbl = re.sub(r"<table", f'<table data-ir-id="{self._id("table:" + tbl[:60])}"', tbl, count=1)
                body.append("    " + tbl.replace("\n", "\n    "))
                continue

            if raw.startswith(("- ", "* ", "• ")):
                in_list = True
                items.append(raw[2:].strip())
                i += 1
                continue

            flush_list()
            body.append(f'    <p data-ir-id="{self._id(raw)}">{self._esc(raw)}</p>')
            i += 1
        flush_list()

        # Inject extracted images as figures with Qwen2-VL alt text.
        # Use data-URIs so the HTML is self-contained (works offline + downloads).
        for img in self.images:
            res = self.alt_map.get(img["filename"], {})
            alt = res.get("alt_text") or img["filename"]
            fig_id = self._id("fig:" + img["filename"])
            img_id = self._id("img:" + img["filename"])
            # Guess MIME type from the b64 hint in the filename or use image/jpeg as default.
            mime = "image/png" if img["filename"].endswith(".png") else "image/jpeg"
            data_uri = f'data:{mime};base64,{img.get("b64", "")}'
            body.append(f'    <figure data-ir-id="{fig_id}">')
            body.append(f'      <img data-ir-id="{img_id}" src="{data_uri}" alt="{self._attr(alt)}">')
            if res.get("requires_long_desc"):
                cap_id = self._id("cap:" + img["filename"])
                body.append(f'      <figcaption data-ir-id="{cap_id}">'
                            f'Complex image — a full long description is required.</figcaption>')
            body.append("    </figure>")

        return self._wrap(body, self.title)

    @staticmethod
    def _wrap(body: list[str], title: str = "Document") -> str:
        head = [
            "<!DOCTYPE html>",
            '<html lang="en">',
            "<head>",
            '  <meta charset="UTF-8">',
            '  <meta name="viewport" content="width=device-width, initial-scale=1.0">',
            f"  <title>{title}</title>",
            "  <style>",
            "    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;"
            " max-width: 800px; margin: 0 auto; padding: 20px; line-height: 1.6; color: #1a1a1a; }",
            "    .skip-link { position: absolute; top: -40px; left: 0; background: #000; color: #fff;"
            " padding: 8px; text-decoration: none; }",
            "    .skip-link:focus { top: 0; }",
            "    table { border-collapse: collapse; width: 100%; margin: 1em 0; }",
            "    th, td { border: 1px solid #767676; padding: 8px; text-align: left; }",
            "    th { background: #eee; }",
            "    img { max-width: 100%; height: auto; }",
            "    figure { margin: 1.5em 0; }",
            "  </style>",
            "</head>",
            "<body>",
            '  <a href="#main-content" class="skip-link">Skip to main content</a>',
            '  <main id="main-content">',
        ]
        tail = ["  </main>", "</body>", "</html>"]
        return "\n".join(head + body + tail)


# ---------------------------------------------------------------------------
# Step 6: axe-core via Playwright (real Chromium)
# ---------------------------------------------------------------------------
def run_axe(html_file: Path) -> dict:
    from playwright.sync_api import sync_playwright

    axe_path = next((p for p in AXE_CANDIDATES if p.exists()), None)
    if axe_path is None:
        raise FileNotFoundError(f"axe-core not found in: {[str(p) for p in AXE_CANDIDATES]}")
    axe_src = axe_path.read_text()

    log(f"axe-core: launching headless Chromium ({axe_path})...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(f"file://{html_file.absolute()}")
        page.evaluate(axe_src)  # inject into the loaded page
        results = page.evaluate("async () => await axe.run()")
        browser.close()
    v, ps = len(results.get("violations", [])), len(results.get("passes", []))
    log(f"axe-core: {v} violation rule(s), {ps} pass rule(s)")
    return results


def summarize(results: dict) -> dict:
    violations = results.get("violations", [])
    sev = {"critical": 0, "serious": 0, "moderate": 0, "minor": 0}
    for v in violations:
        if v.get("impact") in sev:
            sev[v["impact"]] += 1
    n_v, n_p = len(violations), len(results.get("passes", []))
    score = round(n_p / (n_p + n_v) * 100, 1) if (n_p + n_v) else 0.0
    return {"severity": sev, "violations": n_v, "passes": n_p, "score": score,
            "rules": [{"id": v.get("id"), "impact": v.get("impact"),
                       "nodes": len(v.get("nodes", []))} for v in violations]}


def comment_block(summary: dict, dup_ids: set[str], n_imgs: int) -> str:
    s = summary
    lines = [
        "<!--",
        "  syllabus_scored.html  -  generated by build_syllabus_slice.py",
        f"  Generated: {datetime.now().isoformat(timespec='seconds')}",
        "  Pipeline: olmOCR (markdown) + PyMuPDF (images) + Qwen2-VL (alt text) + axe-core",
        "",
        "  axe-core audit summary:",
        f"    Score (passes / passes+violations): {s['score']}%",
        f"    Violations: {s['violations']}  (critical {s['severity']['critical']},"
        f" serious {s['severity']['serious']}, moderate {s['severity']['moderate']},"
        f" minor {s['severity']['minor']})",
        f"    Passes: {s['passes']}",
        f"    Images with generated alt text: {n_imgs}",
    ]
    if s["rules"]:
        lines.append("    Violation rules:")
        for r in s["rules"]:
            lines.append(f"      - {r['id']} [{r['impact']}] x{r['nodes']}")
    if dup_ids:
        lines += [
            "",
            "  KNOWN ISSUE (not blocking): duplicate data-ir-id values from visual",
            "  artifacts (e.g. dashes-only paragraphs hash to the same id):",
            "    " + ", ".join(sorted(dup_ids)),
        ]
    lines.append("-->")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
def main() -> int:
    log("=" * 70)
    log("Syllabus accessibility pipeline starting")
    if not INPUT_PDF.exists():
        log(f"FATAL: input PDF not found: {INPUT_PDF}")
        return 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    pdf_bytes = INPUT_PDF.read_bytes()
    use_cache = "--no-cache" not in sys.argv

    # Step 2 (olmOCR) - cache markdown to avoid re-spending GPU on HTML iteration.
    if use_cache and CACHE_MD.exists():
        log(f"olmOCR: using cached markdown ({CACHE_MD.name}); pass --no-cache to refresh")
        markdown = strip_front_matter(CACHE_MD.read_text())
    else:
        markdown = strip_front_matter(run_olmocr(pdf_bytes, INPUT_PDF.name))
        CACHE_MD.write_text(markdown)

    images = extract_images(INPUT_PDF)

    # Step 4 (Qwen2-VL) - cache alt-text map keyed by image filename.
    if use_cache and CACHE_ALT.exists():
        log(f"alt text: using cached map ({CACHE_ALT.name}); pass --no-cache to refresh")
        alt_map = json.loads(CACHE_ALT.read_text())
    else:
        alt_map = generate_alt_text(images)
        CACHE_ALT.write_text(json.dumps(alt_map, indent=2))

    log("HTML: building semantic HTML5...")
    builder = HtmlBuilder(markdown, images, alt_map)
    html = builder.build()

    OUT_HTML.write_text(html)  # write once so axe can load it
    results = run_axe(OUT_HTML)
    summary = summarize(results)

    # Prepend audit comment block and rewrite.
    final = comment_block(summary, builder.dup_ids, len(images)) + "\n" + html
    OUT_HTML.write_text(final)
    OUT_AXE.write_text(json.dumps(results, indent=2))

    log("=" * 70)
    log(f"DONE  score={summary['score']}%  violations={summary['violations']}"
        f"  passes={summary['passes']}  images={len(images)}")
    log(f"  HTML:    {OUT_HTML}")
    log(f"  AxeJSON: {OUT_AXE}")
    if builder.dup_ids:
        log(f"  duplicate data-ir-ids (documented, non-blocking): {sorted(builder.dup_ids)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
