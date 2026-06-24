"""
olmOCR Modal endpoint - Official implementation

Following allenai/olmocr GitHub repository:
- Uses ollmOCR-2-7B-1025-FP8 (latest model from allenai HuggingFace)
- Pins exact versions: vllm==0.11.2, transformers==4.57.3, torch>=2.7.0
- Calls official olmocr CLI tool
- Returns markdown output with YAML front matter (primary_language, is_rotation_valid, etc.)

To run:
    modal run modal_olmocr_final.py --pdf-file path/to/pdf.pdf

To deploy for external use:
    modal deploy modal_olmocr_final.py
    # Then call via modal.Function("ollmocr_final", "process_pdf")
"""

import json
import logging
import subprocess
import tempfile
from pathlib import Path

import modal

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ============================================================================
# Modal Image Definition - Based on Official Dockerfile
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
        "pip install olmocr",
        # Fix: FastAPI 0.137+ refactored route includes to use lazy routers, breaking
        # prometheus_fastapi_instrumentator (tracked at github.com/trallnag/prometheus-fastapi-instrumentator/issues/370)
        # Pin FastAPI to < 0.137 to avoid the incompatibility
        "pip install 'fastapi<0.137'",
    )
)

app = modal.App("olmocr", image=image)

# ============================================================================
# Main Function - Processes PDF using official olmocr CLI
# ============================================================================

@app.function(
    gpu="H100",
    timeout=3600,
    memory=40960,
)
def process_pdf(pdf_bytes: bytes, filename: str = "document.pdf") -> dict:
    """
    Process PDF through official olmOCR CLI.

    This function:
    1. Writes PDF to temp file
    2. Runs: olmocr <workspace> --markdown --pdfs <pdf>
    3. Extracts markdown output
    4. Returns structured result

    Args:
        pdf_bytes: Raw PDF file bytes
        filename: Original filename (for reference)

    Returns:
        {
            "markdown": str,  # Full markdown output with YAML front matter
            "status": "success",
            "page_count": int,  # Estimated from markdown separators
            "filename": str,
            "bytes": int,  # Input PDF size
        }
    """

    logger.info(f"[olmocr] Processing {filename} ({len(pdf_bytes):,} bytes)")

    # Create temp workspace
    workspace = Path(tempfile.mkdtemp(prefix="olmocr_"))
    logger.info(f"[olmocr] Workspace: {workspace}")

    input_pdf = workspace / "input.pdf"
    markdown_dir = workspace / "markdown"

    try:
        # Write PDF
        logger.info(f"[olmocr] Writing input PDF")
        input_pdf.write_bytes(pdf_bytes)

        # Run official olmocr CLI
        # Increase timeout for vLLM server startup on cold H100 (can take 30-90 seconds)
        cmd = [
            "olmocr",
            str(workspace),
            "--markdown",
            "--pdfs",
            str(input_pdf),
            "--max_server_ready_timeout",
            "300",  # 5 minutes for vLLM server to become ready
        ]
        # Log the exact command with all arguments
        logger.info(f"[olmocr] EXACT COMMAND LINE:")
        for i, arg in enumerate(cmd):
            logger.info(f"[olmocr] arg[{i}] = {arg!r}")
        logger.info(f"[olmocr] Running: {' '.join(cmd)}")

        env = {
            **dict(subprocess.os.environ),
            "CUDA_VISIBLE_DEVICES": "0",
        }

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=3600,
            env=env,
        )

        logger.info(f"[olmocr] Exit code: {result.returncode}")

        # Log FULL output for debugging (not truncated)
        if result.stdout:
            logger.info(f"[olmocr stdout - FULL OUTPUT]\n{result.stdout}")
        if result.stderr:
            logger.warning(f"[olmocr stderr - FULL OUTPUT]\n{result.stderr}")

        if result.returncode != 0:
            error_msg = f"olmocr failed (exit {result.returncode})"
            if result.stderr:
                error_msg += f"\n{result.stderr[:1000]}"
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
            raise RuntimeError(f"No .md files found in {markdown_dir}. Found: {[f.name for f in available[:10]]}")

        output_file = md_files[0]
        logger.info(f"[olmocr] Output: {output_file.name} ({output_file.stat().st_size:,} bytes)")

        # Read markdown
        markdown = output_file.read_text()

        # Estimate page count from markdown YAML separators
        page_count = 1 + markdown.count("\n---\n")

        logger.info(f"[olmocr] Generated {len(markdown):,} characters, ~{page_count} pages")

        return {
            "markdown": markdown,
            "status": "success",
            "page_count": page_count,
            "filename": filename,
            "bytes": len(pdf_bytes),
        }

    except Exception as e:
        logger.error(f"[olmocr] Error: {e}", exc_info=True)
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
    Test the olmocr Modal function.

    Usage:
        modal run modal_olmocr_final.py --pdf-file comparison_test/f1040sc.pdf
    """

    pdf_path = Path(pdf_file)
    if not pdf_path.exists():
        print(f"❌ PDF not found: {pdf_file}")
        return

    print("=" * 90)
    print("olmOCR Modal Test")
    print("=" * 90)
    print(f"PDF: {pdf_path.name}")
    print(f"Size: {pdf_path.stat().st_size:,} bytes\n")

    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()

    print("🚀 Processing on Modal H100...")

    result = process_pdf.remote(pdf_bytes, pdf_path.name)

    print("\n" + "=" * 90)
    print("✅ SUCCESS")
    print("=" * 90)
    print(f"Pages: {result['page_count']}")
    print(f"Markdown: {len(result['markdown']):,} characters")

    print("\n" + "=" * 90)
    print("FIRST 1500 CHARACTERS")
    print("=" * 90)
    print(result["markdown"][:1500])

    if len(result["markdown"]) > 1500:
        print("\n[... truncated ...]")

    # Save output
    output_path = Path(f"olmocr_{Path(pdf_file).stem}.md")
    output_path.write_text(result["markdown"])
    print(f"\n✅ Full output: {output_path}")
