#!/usr/bin/env python3
"""Capture a REAL end-to-end pipeline run per benchmark PDF for the demo snapshots.

Mirrors api/main.py's _live worker step-for-step — same functions, same order,
same hosted defaults — so the captured record is exactly what a live hosted job
produces, including the PointCheck coverage checks, the independent alt-text
judge, and the visual fidelity gate. Every value in one snapshot comes from ONE
run; core stats and report blocks are never mixed across runs.

Unlike _live (which degrades report blocks to "unavailable" markers rather than
fail a user's job), a capture ABORTS if any block comes back degraded: a demo
snapshot must never bake in an error state. Rerun on failure.

Writes benchmark/<name>_live_{baseline,final}.html and <name>_live_summary.json
(build_snapshots.py's inputs) with the four report blocks in the summary.
Follow with: python api/build_snapshots.py

Run: python scripts/capture_live_snapshots.py [name ...]   (default: all three)
"""

import json
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "benchmark"
sys.path.insert(0, str(ROOT / "src"))

import build_syllabus_slice as bss  # noqa: E402
import fidelity_gate as fg  # noqa: E402
import reviewers  # noqa: E402
from loop import axe_score, run_loop  # noqa: E402
from pointcheck_scorer import pointcheck_score  # noqa: E402

# (snapshot id, benchmark PDF, doctype) — ids/doctypes match build_snapshots.DOCS
DOCS = [
    ("syllabus", "syllabus_NOTaccessible.pdf", "Clean digital PDF"),
    ("irs_schedule_c", "irs_schedule_c.pdf", "Dense tax form"),
    ("navy_bulletin", "navy_bulletin.pdf", "OCR'd historical scan"),
]


def _pointcheck_or_die(html: str, which: str) -> dict:
    block = pointcheck_score(html)
    if block.get("error"):
        raise RuntimeError(f"pointcheck ({which}) degraded: {block['error']}")
    return block


def capture(name: str, pdf_file: str, doctype: str) -> dict:
    print(f"\n=== {name} ({doctype}) [LIVE CAPTURE] ===", flush=True)
    pdf_bytes = (BENCH / pdf_file).read_bytes()
    t0 = time.time()

    # Fidelity gate's PDF-side inventory needs only the raw PDF — start it now
    # so the GPU cold start overlaps extraction, exactly as _live does.
    with ThreadPoolExecutor(max_workers=1) as fidelity_pool:
        fidelity_future = fidelity_pool.submit(fg.analyze_pdf_pages, pdf_bytes)

        with tempfile.NamedTemporaryFile("wb", suffix=".pdf", delete=False) as f:
            f.write(pdf_bytes)
            pdf_path = Path(f.name)

        # Image extraction + alt text run concurrently with olmOCR extraction.
        def _images_and_alt():
            images = bss.extract_images(pdf_path)
            return images, (bss.generate_alt_text(images) if images else {})

        with ThreadPoolExecutor(max_workers=1) as pool:
            alt_future = pool.submit(_images_and_alt)
            markdown = bss.strip_front_matter(bss.run_olmocr(pdf_bytes, pdf_file))
            images, alt_map = alt_future.result()
        pdf_path.unlink(missing_ok=True)
        print(f"  extracted: {len(markdown)} chars markdown, {len(images)} images", flush=True)

        # Independent alt-text judge, started before the loop as in _live.
        with ThreadPoolExecutor(max_workers=1) as judge_pool:
            judge_future = (
                judge_pool.submit(bss.judge_alt_text_map, images, alt_map) if images else None
            )

            title = bss.extract_title_from_markdown(markdown)
            baseline_html = bss.HtmlBuilder(markdown, images, alt_map, title=title).build()
            baseline_axe = axe_score(baseline_html)
            pointcheck_baseline = _pointcheck_or_die(baseline_html, "baseline")

            summary = run_loop(
                baseline_html,
                reviewers.make_live_provider(),
                label=name,
                use_llm=True,
                baseline_axe=baseline_axe,
            )
            final_html = summary.pop("final_html")

            # A demo snapshot must reflect the full reviewer panel; a run
            # where any reviewer was down (e.g. 401 on a missing token) is
            # degraded even though the loop tolerates it.
            unhealthy = {
                r: h.get("status")
                for r, h in summary.get("reviewer_health", {}).items()
                if h.get("status") != "success"
            }
            if unhealthy:
                raise RuntimeError(f"reviewer(s) degraded: {unhealthy} — fix and rerun")

            alt_text_review = None
            if judge_future is not None:
                alt_text_review = judge_future.result(timeout=240)
                if not alt_text_review or alt_text_review.get("status") == "unavailable":
                    raise RuntimeError("alt-text judge degraded — rerun the capture")

        fidelity = fg.compare_with_html(fidelity_future.result(timeout=300), final_html)
        if fidelity.get("status") != "ok":
            raise RuntimeError(f"fidelity gate degraded ({fidelity.get('status')}) — rerun")

    pointcheck = _pointcheck_or_die(final_html, "final")

    summary.update(
        name=name,
        doctype=doctype,
        total_seconds=round(time.time() - t0, 2),
        pointcheck_baseline=pointcheck_baseline,
        pointcheck=pointcheck,
        alt_text_review=alt_text_review,
        fidelity=fidelity,
    )
    (BENCH / f"{name}_live_baseline.html").write_text(baseline_html)
    (BENCH / f"{name}_live_final.html").write_text(final_html)
    (BENCH / f"{name}_live_summary.json").write_text(json.dumps(summary, indent=2))

    judged = (alt_text_review or {}).get("images_judged", 0)
    flagged = len((alt_text_review or {}).get("flagged_low_quality", []))
    print(
        f"  done in {summary['total_seconds']}s: "
        f"{summary['baseline']['passes']}->{summary['final']['passes']} passes, "
        f"pointcheck {len(pointcheck['findings'])} findings, "
        f"alt judge {judged} judged/{flagged} flagged, "
        f"fidelity {len(fidelity['findings'])} findings",
        flush=True,
    )
    return summary


def main() -> int:
    reviewers.load_env()
    want = sys.argv[1:] or [d[0] for d in DOCS]
    unknown = set(want) - {d[0] for d in DOCS}
    if unknown:
        print(f"unknown doc(s): {sorted(unknown)}; valid: {[d[0] for d in DOCS]}")
        return 1
    for name, pdf_file, doctype in DOCS:
        if name in want:
            capture(name, pdf_file, doctype)
    print("\nAll captures complete. Now run: python api/build_snapshots.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
