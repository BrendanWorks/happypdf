"""
Deploy the happypdf demo API to Modal as a public ASGI app (live PDF uploads).

Design notes (why this isn't just `asgi_app()(lambda: app)`):
  - The API runs the 2-6 min pipeline in a background thread and keeps job state
    in memory. To make that survive Modal's serverless model we pin to a single
    container (max_containers=1) and keep it warm long enough that polls hit the
    same container and the thread isn't scaled down mid-job (scaledown_window).
  - The pipeline shells out to a real headless Chromium for axe-core, so the
    image bundles Playwright + Chromium + axe.min.js.
  - The reviewer/judge API keys come from the `happypdf-secrets` Modal Secret;
    AXE_CORE_PATH points the gate at the bundled axe-core.
  - Live conversions are rate-limited to HAPPYPDF_DAILY_LIMIT/day (Modal Dict).

Deploy:  modal deploy src/modal_api.py
"""

from pathlib import Path

import modal

REPO = Path(__file__).resolve().parent.parent
AXE_LOCAL = "/Users/brendanworks/node_modules/axe-core/axe.min.js"

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "fastapi==0.138.0",
        "uvicorn[standard]==0.49.0",
        "python-multipart==0.0.32",
        "anthropic==0.111.0",
        "openai==1.109.1",
        "google-genai==1.75.0",
        "httpx==0.28.1",
        "PyMuPDF==1.27.2.3",
        "lxml==6.1.1",
        "beautifulsoup4==4.14.3",
        "playwright==1.60.0",
        "modal",
    )
    .run_commands("playwright install --with-deps chromium")
    .add_local_file(AXE_LOCAL, "/root/axe.min.js")
    .add_local_dir(str(REPO / "src"), "/root/happypdf/src")
    .add_local_dir(str(REPO / "api"), "/root/happypdf/api")
)

app = modal.App("happypdf-api")


@app.function(
    image=image,
    secrets=[modal.Secret.from_name("happypdf-secrets")],
    min_containers=0,        # scale to zero when idle — no standing cost
    max_containers=1,        # single container => consistent in-memory job state
    scaledown_window=1200,   # stay warm 20 min so a 5 min job + polls survive
    timeout=3600,
)
@modal.concurrent(max_inputs=20)  # serve polls concurrently with a running job
@modal.asgi_app()
def fastapi_app():
    import os
    import sys

    sys.path.insert(0, "/root/happypdf/api")
    sys.path.insert(0, "/root/happypdf/src")
    os.environ.setdefault("AXE_CORE_PATH", "/root/axe.min.js")
    os.environ.setdefault("HAPPYPDF_ON_MODAL", "1")
    # TEST: Force OpenAI provider for this deployment (remove to auto-select)
    os.environ.setdefault("HAPPYPDF_ALT_TEXT_PROVIDER", "openai")

    from main import app as fastapi  # api/main.py
    return fastapi
