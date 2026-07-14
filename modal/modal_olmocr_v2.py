"""
olmOCR v2 STAGING deployment — DO NOT point production at this yet.

This is a staging duplicate of modal_olmocr_final.py used to validate the
olmOCR-2-7B-1025-FP8 model before cutting production over to it.

What differs from production (modal_olmocr_final.py, Modal app "olmocr"):
  1. App name is "olmocr-v2" (production stays "olmocr", untouched).
  2. olmocr is pinned to >=0.4.0 (the release line that ships olmOCR-2).
     Production installs olmocr UNPINNED.
  3. The extraction command passes an EXPLICIT model:
         --model allenai/olmOCR-2-7B-1025-FP8
     Production passes no --model, so it silently uses the olmocr CLI default,
     which is allenai/olmOCR-7B-0725-FP8 (olmOCR *v1*). That implicit default
     is exactly what this upgrade replaces.

olmOCR-2 improves table structure and math handling over v1. The FP8 weights
need ~16-18 GB VRAM and fit comfortably on the H100 this function requests.

Deploy (staging only — creates/updates the "olmocr-v2" app, leaves "olmocr" alone):
    modal deploy modal/modal_olmocr_v2.py

Smoke test one PDF from the CLI:
    modal run modal/modal_olmocr_v2.py --pdf-file benchmark/irs_schedule_c.pdf

Call from code:
    modal.Function.from_name("olmocr-v2", "process_pdf")

REVERT: nothing in production references "olmocr-v2". To retire it entirely,
`modal app stop olmocr-v2`. Production is unaffected either way.
"""

import logging
import subprocess
import tempfile
from pathlib import Path

import modal

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# The model this staging app is validating. Kept as a module constant so the
# test/comparison script can import it and assert the deployment matches.
MODEL_ID = "allenai/olmOCR-2-7B-1025-FP8"

# ============================================================================
# Modal Image Definition - mirrors the proven production image, with olmocr
# bumped to the >=0.4.0 line that ships olmOCR-2.
# ============================================================================

image = (
    modal.Image.debian_slim(python_version="3.11")
    # System packages (from official Dockerfile, excluding unavailable fonts)
    .apt_install(
        "poppler-utils",
        "fonts-crosextra-caladea",
        "fonts-crosextra-carlito",
        "gsfonts",
        "lcdf-typetools",
        "git",
        "git-lfs",
    )
    # Python GPU stack - install PyTorch with CUDA wheels
    .run_commands(
        "pip install torch>=2.7.0 -f https://download.pytorch.org/whl/cu128/torch_stable.html",
        "pip install vllm==0.11.2 transformers==4.57.3",
        # v2: pin olmocr to the release line that ships olmOCR-2 (was unpinned in prod)
        "pip install 'olmocr>=0.4.0'",
        # Fix: FastAPI 0.137+ refactored route includes to use lazy routers, breaking
        # prometheus_fastapi_instrumentator (tracked at github.com/trallnag/prometheus-fastapi-instrumentator/issues/370)
        # Pin FastAPI to < 0.137 to avoid the incompatibility
        "pip install 'fastapi<0.137'",
    )
    # Bake the model weights into the image at BUILD time. Downloading ~16 GB
    # from HuggingFace on every cold start made vLLM miss its server-ready
    # timeout whenever HF was slow (observed live 2026-07-13: repeated cold
    # downloads degraded until every extraction failed with "vllm server did
    # not become ready"). With weights in the image, containers never touch
    # HF at runtime and cold start is just the vLLM model load.
    .run_commands(
        'python -c "from huggingface_hub import snapshot_download; '
        f"snapshot_download('{MODEL_ID}')\""
    )
)

app = modal.App("olmocr-v2", image=image)

# ============================================================================
# Main Function - Processes PDF using official olmocr CLI, pinned to olmOCR-2
# ============================================================================


@app.function(
    gpu="H100",
    timeout=3600,
    memory=40960,
    # One extraction per container. Each call boots its own vLLM server via the
    # olmocr CLI; a SECOND call on a reused warm container can hang forever on
    # leftover GPU state from the previous vLLM's unclean shutdown (observed
    # live 2026-07-13: back-to-back conversions froze the second job at
    # "extracting" with zero output). Fresh container per call = clean boot.
    # Traffic is sparse enough that calls were effectively always cold anyway.
    single_use_containers=True,
)
def process_pdf(pdf_bytes: bytes, filename: str = "document.pdf") -> dict:
    """
    Process PDF through the official olmocr CLI, pinned to olmOCR-2-7B-1025-FP8.

    Identical to the production function except for the explicit --model flag.

    Args:
        pdf_bytes: Raw PDF file bytes
        filename: Original filename (for reference)

    Returns:
        {
            "markdown": str,   # Full markdown output with YAML front matter
            "status": "success",
            "page_count": int, # Estimated from markdown separators
            "filename": str,
            "bytes": int,      # Input PDF size
            "model": str,      # Which model produced this output (for comparison)
        }
    """

    logger.info(f"[olmocr-v2] Processing {filename} ({len(pdf_bytes):,} bytes) with {MODEL_ID}")

    # Create temp workspace
    workspace = Path(tempfile.mkdtemp(prefix="olmocr_v2_"))
    logger.info(f"[olmocr-v2] Workspace: {workspace}")

    input_pdf = workspace / "input.pdf"
    markdown_dir = workspace / "markdown"

    try:
        # Write PDF
        logger.info("[olmocr-v2] Writing input PDF")
        input_pdf.write_bytes(pdf_bytes)

        # Run official olmocr CLI with an EXPLICIT model (the v2 change).
        cmd = [
            "olmocr",
            str(workspace),
            "--model",
            MODEL_ID,
            "--markdown",
            "--pdfs",
            str(input_pdf),
            "--max_server_ready_timeout",
            "600",  # headroom for vLLM model load; weights are local (baked into image)
        ]
        logger.info("[olmocr-v2] EXACT COMMAND LINE:")
        for i, arg in enumerate(cmd):
            logger.info(f"[olmocr-v2] arg[{i}] = {arg!r}")
        logger.info(f"[olmocr-v2] Running: {' '.join(cmd)}")

        env = {
            **dict(subprocess.os.environ),
            "CUDA_VISIBLE_DEVICES": "0",
        }

        # Stream the CLI's output live instead of capturing it. With captured
        # output a hung run is completely silent — observed live 2026-07-13: a
        # stuck extraction produced zero logs for 30+ minutes and could only be
        # diagnosed by killing the container. Streaming makes progress (model
        # download, vLLM startup, per-page work) visible in `modal app logs`.
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
        )
        output_lines: list[str] = []
        assert proc.stdout is not None
        for line in proc.stdout:
            print(f"[olmocr-v2] {line.rstrip()}", flush=True)
            output_lines.append(line)
        returncode = proc.wait(timeout=60)  # streams ended; exit is imminent
        output = "".join(output_lines)

        logger.info(f"[olmocr-v2] Exit code: {returncode}")

        if returncode != 0:
            error_msg = f"olmocr failed (exit {returncode})"
            if output:
                error_msg += f"\n{output[-1000:]}"
            raise RuntimeError(error_msg)

        # Find markdown output file (olmocr may nest files in subdirectories)
        if not markdown_dir.exists():
            raise RuntimeError(f"No markdown output directory: {markdown_dir}")

        # First try direct children
        md_files = sorted(markdown_dir.glob("*.md"))
        # If not found, search recursively (olmocr may create subdirs)
        if not md_files:
            md_files = sorted(markdown_dir.glob("**/*.md"))

        if not md_files:
            available = list(markdown_dir.rglob("*"))
            raise RuntimeError(
                f"No .md files found in {markdown_dir}. Found: {[f.name for f in available[:10]]}"
            )

        output_file = md_files[0]
        logger.info(
            f"[olmocr-v2] Output: {output_file.name} ({output_file.stat().st_size:,} bytes)"
        )

        # Read markdown
        markdown = output_file.read_text()

        # Estimate page count from markdown YAML separators
        page_count = 1 + markdown.count("\n---\n")

        logger.info(f"[olmocr-v2] Generated {len(markdown):,} characters, ~{page_count} pages")

        return {
            "markdown": markdown,
            "status": "success",
            "page_count": page_count,
            "filename": filename,
            "bytes": len(pdf_bytes),
            "model": MODEL_ID,
        }

    except Exception as e:
        logger.error(f"[olmocr-v2] Error: {e}", exc_info=True)
        raise

    finally:
        # Cleanup
        import shutil

        shutil.rmtree(workspace, ignore_errors=True)


# ============================================================================
# CLI Interface
# ============================================================================


@app.local_entrypoint()
def main(pdf_file: str):
    """
    Smoke-test the olmocr-v2 Modal function.

    Usage:
        modal run modal/modal_olmocr_v2.py --pdf-file benchmark/irs_schedule_c.pdf
    """

    pdf_path = Path(pdf_file)
    if not pdf_path.exists():
        print(f"❌ PDF not found: {pdf_file}")
        return

    print("=" * 90)
    print(f"olmOCR v2 Modal Test — {MODEL_ID}")
    print("=" * 90)
    print(f"PDF: {pdf_path.name}")
    print(f"Size: {pdf_path.stat().st_size:,} bytes\n")

    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()

    print("🚀 Processing on Modal H100 (olmocr-v2)...")

    result = process_pdf.remote(pdf_bytes, pdf_path.name)

    print("\n" + "=" * 90)
    print("✅ SUCCESS")
    print("=" * 90)
    print(f"Model: {result.get('model')}")
    print(f"Pages: {result['page_count']}")
    print(f"Markdown: {len(result['markdown']):,} characters")

    print("\n" + "=" * 90)
    print("FIRST 1500 CHARACTERS")
    print("=" * 90)
    print(result["markdown"][:1500])

    if len(result["markdown"]) > 1500:
        print("\n[... truncated ...]")
