#!/usr/bin/env python3
"""
happypdf API — async job service in front of the remediation pipeline.

Two job kinds:
  - replay : the 3 benchmark docs return REAL pre-computed results (api/snapshots/*),
             stepped through the pipeline stages so the UI animates. Instant, free.
  - live   : an uploaded PDF runs the real pipeline (olmOCR -> alt text -> HTML ->
             axe -> live-reviewer loop). Minutes, real GPU/API cost.

Run (loads .env for ANTHROPIC/GOOGLE/OPENAI keys used by the live path):
  uvicorn api.main:app --reload --port 8000
or:
  python api/main.py
"""

import json
import os
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
SNAPSHOTS = ROOT / "api" / "snapshots"
import sys
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(ROOT / "api"))

# Pipeline stages the UI walks through (ids match the frontend).
STAGES = [
    {"id": "uploading", "label": "Upload"},
    {"id": "extracting", "label": "olmOCR extraction"},
    {"id": "alt_text", "label": "Alt text generation"},
    {"id": "html", "label": "Semantic HTML"},
    {"id": "axe_baseline", "label": "axe-core baseline"},
    {"id": "round1", "label": "Peer review · Round 1"},
    {"id": "round2", "label": "Peer review · Round 2"},
    {"id": "round3", "label": "Peer review · Round 3"},
    {"id": "done", "label": "Output ready"},
]

app = FastAPI(title="happypdf API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173", "http://localhost:5174", "http://127.0.0.1:5173",
        "https://happypdf.netlify.app",
    ],
    # Netlify deploy previews / branch deploys: https://<hash>--happypdf.netlify.app
    allow_origin_regex=r"https://([a-z0-9-]+--)?happypdf\.netlify\.app",
    allow_methods=["*"], allow_headers=["*"],
)

# Daily rate limit for the paid live path. Backed by a Modal Dict on Modal (shared
# across container restarts), or an in-process counter locally.
DAILY_LIMIT = int(os.environ.get("HAPPYPDF_DAILY_LIMIT", "10"))
_local_counts: dict[str, int] = {}


def _rate_check() -> tuple[bool, int]:
    """Returns (allowed, count_after). Increments only when allowed."""
    today = datetime.now().strftime("%Y-%m-%d")
    if os.environ.get("HAPPYPDF_ON_MODAL"):
        import modal
        counts = modal.Dict.from_name("happypdf-counts", create_if_missing=True)
        c = counts.get(today, 0)
        if c >= DAILY_LIMIT:
            return False, c
        counts[today] = c + 1
        return True, c + 1
    c = _local_counts.get(today, 0)
    if c >= DAILY_LIMIT:
        return False, c
    _local_counts[today] = c + 1
    return True, c + 1

# In-memory job store (local dev). job_id -> dict.
JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()


def _new_job(kind: str, name: str) -> str:
    jid = uuid.uuid4().hex[:12]
    with JOBS_LOCK:
        JOBS[jid] = {
            "id": jid, "kind": kind, "name": name, "status": "running",
            "stage": "uploading", "stages": STAGES, "baseline": None,
            "rounds": [], "final": None, "enhancements": [], "final_html": None,
            "error": None, "source": None, "started": time.time(),
        }
    return jid


def _set(jid: str, **kw) -> None:
    with JOBS_LOCK:
        JOBS[jid].update(kw)


def _load_snapshot(name: str) -> dict:
    f = SNAPSHOTS / f"{name}.json"
    if not f.exists():
        raise HTTPException(404, f"unknown demo: {name}")
    return json.loads(f.read_text())


# ---------------------------------------------------------------------------
# Replay worker — steps a real snapshot through the stages with realistic pacing
# ---------------------------------------------------------------------------
def _replay(jid: str, name: str) -> None:
    try:
        snap = _load_snapshot(name)
        _set(jid, source=snap["source"])
        pace = {"uploading": 0.4, "extracting": 1.1, "alt_text": 0.9,
                "html": 0.7, "axe_baseline": 0.8}
        for sid in ("uploading", "extracting", "alt_text", "html", "axe_baseline"):
            _set(jid, stage=sid)
            time.sleep(pace[sid])
        _set(jid, baseline=snap["baseline"])

        revealed = []
        for rnd in snap["rounds"]:
            _set(jid, stage=f"round{rnd['round']}")
            time.sleep(0.9)
            revealed.append(rnd)
            _set(jid, rounds=list(revealed))
        _set(jid, stage="done", final=snap["final"],
             enhancements=snap["enhancements"], final_html=snap["final_html"],
             stopped_reason=snap["stopped_reason"], total_seconds=snap["total_seconds"],
             status="done")
    except Exception as e:  # pragma: no cover
        _set(jid, status="error", error=str(e))


# ---------------------------------------------------------------------------
# Live worker — runs the real pipeline on an uploaded PDF
# ---------------------------------------------------------------------------
def _live(jid: str, pdf_bytes: bytes, filename: str) -> None:
    import tempfile
    import build_syllabus_slice as bss
    import reviewers
    from loop import run_loop, axe_score
    reviewers.load_env()
    try:
        _set(jid, source="live pipeline (olmOCR + Qwen2-VL + live reviewers + Claude judge)")
        _set(jid, stage="extracting")
        markdown = bss.strip_front_matter(bss.run_olmocr(pdf_bytes, filename))

        _set(jid, stage="alt_text")
        with tempfile.NamedTemporaryFile("wb", suffix=".pdf", delete=False) as f:
            f.write(pdf_bytes)
            pdf_path = Path(f.name)
        images = bss.extract_images(pdf_path)
        alt_map = bss.generate_alt_text(images) if images else {}
        pdf_path.unlink(missing_ok=True)

        _set(jid, stage="html")
        baseline_html = bss.HtmlBuilder(markdown, images, alt_map).build()

        _set(jid, stage="axe_baseline")
        _set(jid, baseline=axe_score(baseline_html))

        def on_round(entry, _patched):
            _set(jid, stage=f"round{entry['round']}")
            with JOBS_LOCK:
                JOBS[jid]["rounds"].append({
                    "round": entry["round"], "patches_applied": entry["patches_applied"],
                    "passes": entry["passes"], "score": entry["score"],
                    "violations": entry["violations"], "gate_passed": entry["gate_passed"],
                    "gate_checks": entry.get("gate_checks", []),
                })

        summary = run_loop(baseline_html, reviewers.live_provider,
                           label=filename, use_llm=True, on_round=on_round)
        final_html = summary["final_html"]
        from build_snapshots import enhancements
        _set(jid, stage="done", final=summary["final"], final_html=final_html,
             enhancements=enhancements(baseline_html, final_html),
             stopped_reason=summary["stopped_reason"], status="done")
    except Exception as e:
        _set(jid, status="error", error=f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get("/api/health")
def health():
    return {"status": "ok", "jobs": len(JOBS)}


@app.get("/api/demos")
def demos():
    idx = SNAPSHOTS / "index.json"
    return json.loads(idx.read_text()) if idx.exists() else []


@app.post("/api/jobs/demo/{name}")
def start_demo(name: str):
    _load_snapshot(name)  # 404 if unknown
    jid = _new_job("replay", name)
    threading.Thread(target=_replay, args=(jid, name), daemon=True).start()
    return {"job_id": jid}


@app.post("/api/jobs/live")
async def start_live(file: UploadFile = File(...)):
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(400, "please upload a .pdf")
    allowed, count = _rate_check()
    if not allowed:
        raise HTTPException(
            429,
            f"Daily live-conversion limit reached ({DAILY_LIMIT}/day). "
            f"Try the instant replay demos, or self-host for unlimited runs.",
        )
    data = await file.read()
    jid = _new_job("live", file.filename)
    threading.Thread(target=_live, args=(jid, data, file.filename), daemon=True).start()
    return {"job_id": jid}


@app.get("/api/jobs/{jid}")
def job_status(jid: str):
    with JOBS_LOCK:
        job = JOBS.get(jid)
        if not job:
            raise HTTPException(404, "no such job")
        out = {k: v for k, v in job.items() if k != "final_html"}
    out["stage_index"] = next((i for i, s in enumerate(STAGES) if s["id"] == out["stage"]), 0)
    out["has_html"] = job.get("final_html") is not None
    return out


@app.get("/api/jobs/{jid}/html", response_class=HTMLResponse)
def job_html(jid: str):
    with JOBS_LOCK:
        job = JOBS.get(jid)
    if not job or not job.get("final_html"):
        raise HTTPException(404, "no html yet")
    return HTMLResponse(job["final_html"])


if __name__ == "__main__":
    import uvicorn
    sys.path.insert(0, str(ROOT / "api"))
    uvicorn.run(app, host="127.0.0.1", port=8000)
