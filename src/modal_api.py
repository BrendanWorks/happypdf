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

Deploy:
  prod:    modal deploy src/modal_api.py
  staging: HAPPYPDF_APP_NAME=happypdf-api-staging modal deploy src/modal_api.py
           (staging gets its own job/rate Dicts so it never touches prod state)
"""

import os

import modal

# path_resolver + validate_paths run only at DEPLOY time (locally), where they
# resolve the real paths used to build the image below. Inside the Modal container
# this module is imported to serve the ASGI app, but path_resolver is mounted under
# /root/happypdf/src (only added to sys.path inside fastapi_app, not at load time)
# and its local paths don't exist there — the image is already built, so REPO and
# AXE_LOCAL are just unused placeholders. Guarding this prevents a container crash
# loop (ModuleNotFoundError: path_resolver) on deploy.
try:
    from path_resolver import AXE_LOCAL, REPO, validate_paths
except ModuleNotFoundError:
    from pathlib import Path

    REPO = Path("/root/happypdf")
    AXE_LOCAL = "/root/axe.min.js"
else:
    validate_paths()  # deploy-time: fail fast if a required local path is missing

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
        "modal==1.4.3",  # match requirements.txt — an unpinned client can drift
    )
    .run_commands("playwright install --with-deps chromium")
    .add_local_file(AXE_LOCAL, "/root/axe.min.js")
    .add_local_dir(str(REPO / "src"), "/root/happypdf/src")
    .add_local_dir(str(REPO / "api"), "/root/happypdf/api")
)

# Deploy-time override for a staging copy of the app. Staging must never share
# prod's persistent Dicts, so the store names are derived from the app name.
APP_NAME = os.environ.get("HAPPYPDF_APP_NAME", "happypdf-api")
IS_PROD = APP_NAME == "happypdf-api"
JOBS_DICT = "happypdf-jobs" if IS_PROD else f"{APP_NAME}-jobs"
RATE_DICT = "happypdf-rate-limit" if IS_PROD else f"{APP_NAME}-rate-limit"

app = modal.App(APP_NAME)


@app.function(
    image=image,
    secrets=[
        modal.Secret.from_name("happypdf-secrets"),
        # Bearer token shared with the OLMo reviewer endpoint (see
        # modal/modal_olmo_wcag.py). Create once:
        #   modal secret create olmo-reviewer-auth OLMO_REVIEWER_TOKEN=$(openssl rand -hex 32)
        modal.Secret.from_name("olmo-reviewer-auth"),
    ],
    min_containers=0,  # scale to zero when idle — no standing cost
    max_containers=1,  # single container => consistent in-memory job state
    scaledown_window=1200,  # stay warm 20 min so a 5 min job + polls survive
    timeout=3600,
    env={"HAPPYPDF_JOBS_DICT": JOBS_DICT, "HAPPYPDF_RATE_DICT": RATE_DICT},
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
    # Alt text provider: auto-select (Claude if both keys, OpenAI if only)
    # Can be overridden via HAPPYPDF_ALT_TEXT_PROVIDER env var for testing

    from main import app as fastapi  # api/main.py

    return fastapi
