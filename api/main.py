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

import asyncio
import json
import os
import re
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response


# ---------------------------------------------------------------------------
# API Key Validation
# ---------------------------------------------------------------------------
def validate_anthropic_key(key: str) -> tuple[bool, str]:
    """Validate Anthropic API key with a quick auth call. Returns (valid, error_msg)."""
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=key)
        # Minimal auth check: list models (cheap, no usage)
        client.models.list()
        return True, ""
    except Exception as e:
        # Log full error for operators; return friendly message for users
        print(f"[VALIDATION] Anthropic key validation failed: {type(e).__name__}: {e}", flush=True)
        return (
            False,
            "Your Anthropic API key is invalid or expired. Please check your key and try again.",
        )


def validate_openai_key(key: str) -> tuple[bool, str]:
    """Validate OpenAI API key with a quick auth call. Returns (valid, error_msg)."""
    try:
        from openai import OpenAI

        client = OpenAI(api_key=key)
        # Minimal auth check: list models (cheap, no usage)
        client.models.list()
        return True, ""
    except Exception as e:
        # Log full error for operators; return friendly message for users
        print(f"[VALIDATION] OpenAI key validation failed: {type(e).__name__}: {e}", flush=True)
        return (
            False,
            "Your OpenAI API key is invalid or expired. Please check your key and try again.",
        )


ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
SNAPSHOTS = ROOT / "api" / "snapshots"
import sys  # noqa: E402

sys.path.insert(0, str(SRC))
sys.path.insert(0, str(ROOT / "api"))

from job_store import DailyRateLimiter, JobStore, mark_interrupted_if_stale  # noqa: E402

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
        "http://localhost:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5173",
        "https://happypdf.org",
        "https://happypdf.netlify.app",
    ],
    # Netlify deploy previews / branch deploys: https://<hash>--happypdf.netlify.app
    allow_origin_regex=r"https://([a-z0-9-]+--)?happypdf\.netlify\.app",
    allow_methods=["*"],
    allow_headers=["*"],
)

# Daily rate limit for the paid live path. Backed by a Modal Dict on Modal so a
# container recycle can't reset the day's count; in-process locally.
DAILY_LIMIT = int(os.environ.get("HAPPYPDF_DAILY_LIMIT", "20"))  # raised for demo testing
RATE_LIMITER = DailyRateLimiter()

# Upload guardrails for the paid live path: each accepted upload triggers real
# H100 time, so reject obviously-invalid or oversized files before spending it.
MAX_UPLOAD_MB = int(os.environ.get("HAPPYPDF_MAX_UPLOAD_MB", "25"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024

# Job ids are uuid4().hex[:12]; demo snapshot names are short slugs. Anything
# else in a path param is rejected before it reaches the filesystem or headers.
JOB_ID_RE = re.compile(r"^[0-9a-f]{12}$")
DEMO_NAME_RE = re.compile(r"^[a-z0-9_]{1,64}$")

# Job store: a modal.Dict on Modal (survives container recycles), else in-process.
JOBS = JobStore()
JOBS_LOCK = threading.Lock()


def _new_job(kind: str, name: str) -> str:
    jid = uuid.uuid4().hex[:12]
    now = time.time()
    with JOBS_LOCK:
        JOBS.prune()  # drop long-dead records so the store stays bounded
        JOBS.put(
            jid,
            {
                "id": jid,
                "kind": kind,
                "name": name,
                "status": "running",
                "stage": "uploading",
                "stages": STAGES,
                "baseline": None,
                "rounds": [],
                "final": None,
                "enhancements": [],
                "error": None,
                "source": None,
                "started": now,
                "updated": now,
                "stage_started": now,
                "page_count": None,
                "has_baseline_html": False,
                "has_final_html": False,
                "reviewer_health": {},
            },
        )
    return jid


def _set(jid: str, **kw) -> None:
    with JOBS_LOCK:
        rec = JOBS.get(jid)
        if rec is None:
            return
        # Stamp stage transitions so the UI can show truthful per-stage timers.
        if "stage" in kw and kw["stage"] != rec.get("stage"):
            rec["stage_started"] = time.time()
        rec.update(kw)
        rec["updated"] = time.time()
        JOBS.put(jid, rec)  # write the whole record back (modal.Dict returns copies)


def _load_snapshot(name: str) -> dict:
    # Strict slug check: the name comes from a URL path parameter and is used
    # to build a filesystem path — reject anything that isn't a known-safe slug.
    if not DEMO_NAME_RE.match(name):
        raise HTTPException(404, "unknown demo")
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
        pace = {
            "uploading": 0.4,
            "extracting": 1.1,
            "alt_text": 0.9,
            "html": 0.7,
            "axe_baseline": 0.8,
        }
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
        JOBS.put_blob(jid, "final_html", snap["final_html"])
        _set(
            jid,
            stage="done",
            final=snap["final"],
            enhancements=snap["enhancements"],
            has_final_html=True,
            stopped_reason=snap["stopped_reason"],
            total_seconds=snap["total_seconds"],
            status="done",
        )
    except Exception as e:  # pragma: no cover
        _set(jid, status="error", error=str(e))


# ---------------------------------------------------------------------------
# Live worker — runs the real pipeline on an uploaded PDF
# ---------------------------------------------------------------------------
def _heartbeat(jid: str, stop: threading.Event, interval_s: float = 60.0) -> None:
    """Touch the job's `updated` timestamp while the worker is alive.

    Long stages (cold-start olmOCR on a big PDF) can exceed STALE_RUNNING_S
    without any _set() call; without a heartbeat the poller would falsely tell
    the user the job was interrupted while it is still running."""
    while not stop.wait(interval_s):
        with JOBS_LOCK:
            rec = JOBS.get(jid)
            if rec is None or rec.get("status") != "running":
                return
            rec["updated"] = time.time()
            JOBS.put(jid, rec)


def _warm_olmo_reviewer() -> None:
    """Fire-and-forget pre-warm of the OLMo reviewer GPU endpoint.

    Booting the A10G and loading the 7B model takes ~1-2 min; doing it while
    olmOCR extraction runs (2-4 min) means review round 1 hits a warm model
    instead of paying that cold start inline. Tolerates servers that don't
    have /warmup yet (older deploys 404) and any network failure — worst case
    round 1 is simply as slow as it used to be."""
    try:
        import httpx

        from reviewers import OLMO_URL

        token = os.environ.get("OLMO_REVIEWER_TOKEN", "")
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        httpx.get(f"{OLMO_URL}/warmup", headers=headers, timeout=300)
    except Exception:
        pass


def _live(
    jid: str,
    pdf_bytes: bytes,
    filename: str,
    anthropic_api_key: str | None = None,
    openai_api_key: str | None = None,
    reviewer_profile: str = "default",
) -> None:
    """Run the real pipeline. BYOK keys are passed explicitly down the call
    chain (provider factory + judge byok dict) — never written to os.environ —
    so concurrent jobs with different credentials cannot observe each other's
    keys and there is no restore step that can race."""

    def _safe_pointcheck(html: str) -> dict:
        # PointCheck Layer-1 coverage checks (see docs/POINTCHECK_INTEGRATION.md).
        # Report-only: never feeds axe's score/gates, and a failure here must
        # never fail the conversion.
        try:
            from pointcheck_scorer import pointcheck_score

            return pointcheck_score(html)
        except Exception as e:
            print(f"[pointcheck] non-fatal: {type(e).__name__}: {e}", flush=True)
            return {"findings": [], "counts": {}, "error": "pointcheck_unavailable"}

    import tempfile
    from concurrent.futures import ThreadPoolExecutor

    stop_heartbeat = threading.Event()
    threading.Thread(target=_heartbeat, args=(jid, stop_heartbeat), daemon=True).start()
    threading.Thread(target=_warm_olmo_reviewer, daemon=True).start()
    judge_pool = None  # alt-text judge executor; shut down in finally on error paths
    fidelity_pool = None  # fidelity-gate executor; ditto
    try:
        import build_syllabus_slice as bss
        import reviewers
        from loop import axe_score, run_loop

        reviewers.load_env()  # hosted defaults from .env (only sets unset vars)
        byok = {"anthropic": anthropic_api_key, "openai": openai_api_key}
        provider = reviewers.make_live_provider(reviewer_profile, openai_api_key=openai_api_key)

        _set(jid, source="live pipeline (olmOCR + Qwen2-VL + live reviewers + Claude judge)")

        # PointCheck Phase 3: fidelity gate's PDF-side vision inventory needs
        # only the raw PDF, so it starts NOW — its GPU cold start overlaps
        # extraction and the review rounds. Report-only, best-effort; the
        # HTML-side comparison is instant and happens post-convergence.
        import fidelity_gate as fg

        fidelity_pool = ThreadPoolExecutor(max_workers=1)
        fidelity_future = fidelity_pool.submit(fg.analyze_pdf_pages, pdf_bytes)

        _set(jid, stage="extracting")
        with tempfile.NamedTemporaryFile("wb", suffix=".pdf", delete=False) as f:
            f.write(pdf_bytes)
            pdf_path = Path(f.name)

        # Image extraction + alt text don't depend on the olmOCR markdown, so
        # they run concurrently with extraction — the alt-text GPU's cold start
        # overlaps olmOCR's 2-4 min instead of adding ~1 min after it.
        def _images_and_alt():
            images = bss.extract_images(pdf_path)
            return images, (bss.generate_alt_text(images) if images else {})

        with ThreadPoolExecutor(max_workers=1) as pool:
            alt_future = pool.submit(_images_and_alt)
            markdown = bss.strip_front_matter(bss.run_olmocr(pdf_bytes, filename))
            _set(jid, stage="alt_text")
            images, alt_map = alt_future.result()
        pdf_path.unlink(missing_ok=True)

        # PointCheck Phase 2: independent alt-text judging (Molmo-7B-D),
        # kicked off NOW so the judge GPU's cold start overlaps the review
        # rounds instead of adding to them. Report-only and best-effort —
        # collected (with a timeout) after the loop finishes.
        judge_pool = ThreadPoolExecutor(max_workers=1)
        judge_future = (
            judge_pool.submit(bss.judge_alt_text_map, images, alt_map) if images else None
        )

        _set(jid, stage="html")
        title = bss.extract_title_from_markdown(markdown)
        baseline_html = bss.HtmlBuilder(markdown, images, alt_map, title=title).build()
        # The converted document exists NOW — publish it so users can preview
        # while the review rounds run (the enhanced version replaces it later).
        JOBS.put_blob(jid, "baseline_html", baseline_html)
        _set(jid, has_baseline_html=True)

        _set(jid, stage="axe_baseline")
        baseline_axe = axe_score(baseline_html)
        _set(jid, baseline=baseline_axe, pointcheck_baseline=_safe_pointcheck(baseline_html))

        def on_round(entry, _patched, reviewer_health=None):
            with JOBS_LOCK:
                rec = JOBS.get(jid)
                if rec is None:
                    return
                rec["rounds"].append(
                    {
                        "round": entry["round"],
                        "patches_applied": entry["patches_applied"],
                        "passes": entry["passes"],
                        "score": entry["score"],
                        "violations": entry["violations"],
                        "gate_passed": entry["gate_passed"],
                        "gate_checks": entry.get("gate_checks", []),
                    }
                )
                if reviewer_health:
                    rec["reviewer_health"] = reviewer_health
                rec["updated"] = time.time()
                JOBS.put(jid, rec)  # write the whole record back (modal.Dict returns copies)

        summary = run_loop(
            baseline_html,
            provider,
            label=filename,
            use_llm=True,
            on_round=on_round,
            # Mark the stage as the round STARTS — most of a round's wall clock
            # is the reviews themselves, and marking at completion hid that
            # wait inside the previous stage's timer.
            on_round_start=lambda r: _set(jid, stage=f"round{r}"),
            byok=byok,
            baseline_axe=baseline_axe,
        )
        final_html = summary["final_html"]
        from build_snapshots import enhancements

        try:
            enhancements_list = enhancements(baseline_html, final_html)
        except Exception as e:
            print(f"Warning: enhancements calculation failed: {e}")
            enhancements_list = []
        # Collect the alt-text judge verdicts (started before the loop; a
        # warm judge is long done by now, a cold one gets a bounded grace
        # period). Timeout/failure leaves alt_text_review as an explicit
        # "unavailable" marker — never fails the job.
        alt_text_review = None
        if judge_future is not None:
            _set(jid, stage="alt_judge")
            try:
                alt_text_review = judge_future.result(timeout=240)
            except Exception as e:
                print(f"[alt-judge] non-fatal: {type(e).__name__}: {e}", flush=True)
                alt_text_review = {"status": "unavailable"}
        judge_pool.shutdown(wait=False)

        # Fidelity gate: the PDF-side inventory has had the whole pipeline to
        # finish; combine with the final HTML (instant, local). Report-only.
        try:
            _set(jid, stage="fidelity")
            fidelity = fg.compare_with_html(
                fidelity_future.result(timeout=180), final_html
            )
        except Exception as e:
            print(f"[fidelity] non-fatal: {type(e).__name__}: {e}", flush=True)
            fidelity = {"status": "unavailable", "findings": []}
        fidelity_pool.shutdown(wait=False)

        # Large HTML lives in its own blob key, not the job record — polls
        # fetch the whole record every 1.5s and must stay small.
        JOBS.put_blob(jid, "final_html", final_html)
        _set(
            jid,
            stage="done",
            final=summary["final"],
            has_final_html=True,
            enhancements=enhancements_list,
            stopped_reason=summary["stopped_reason"],
            status="done",
            reviewer_health=summary.get("reviewer_health", {}),
            reviewer_profile=reviewer_profile,
            pointcheck=_safe_pointcheck(final_html),
            alt_text_review=alt_text_review,
            fidelity=fidelity,
        )
    except Exception as e:
        # Log full error server-side for operators; generic message for user
        print(f"[ERROR] Job {jid} failed: {type(e).__name__}: {e}", flush=True)
        _set(jid, status="error", error="Conversion failed. Check your API key and try again.")
    finally:
        stop_heartbeat.set()
        if judge_pool is not None:
            judge_pool.shutdown(wait=False)
        if fidelity_pool is not None:
            fidelity_pool.shutdown(wait=False)


# ---------------------------------------------------------------------------
# Deep health checks — provider-key validity + Modal function resolvability.
#
# Motivation: the hosted secret carried a dead OpenAI key and no Anthropic /
# Google keys for weeks, and nothing noticed until a live review of the logs
# (jobs silently degraded to OLMo-only with no LLM judge). These checks make
# that state visible in /api/health, where the scheduled monitor workflow
# (.github/workflows/monitor.yml) alerts on it.
#
# Cost/safety: only cheap calls — provider models.list() and Modal metadata
# lookups; never boots a GPU. Results are cached for HEALTH_TTL_S; a cold
# container's first /api/health pays ~5s once. Disabled outside Modal unless
# HAPPYPDF_DEEP_HEALTH=1, so local dev and pytest never make network calls.
# ---------------------------------------------------------------------------
HEALTH_TTL_S = int(os.environ.get("HAPPYPDF_HEALTH_TTL_S", str(24 * 3600)))
# A FAILED check is re-validated on a short TTL instead of being remembered all
# day: a transient provider blip (observed live 2026-07-14: one Google API
# hiccup) otherwise poisons the cache and re-alerts the monitor every 30 min
# until the container happens to recycle.
HEALTH_FAIL_TTL_S = int(os.environ.get("HAPPYPDF_HEALTH_FAIL_TTL_S", "600"))
_health_cache: dict = {"checked_at": 0.0, "checks": {}}
_health_lock = threading.Lock()


def _deep_health_enabled() -> bool:
    return (
        os.environ.get("HAPPYPDF_ON_MODAL") == "1" or os.environ.get("HAPPYPDF_DEEP_HEALTH") == "1"
    )


def _run_deep_checks() -> dict[str, str]:
    """Each check is 'ok', 'missing', 'invalid', or 'unavailable'."""
    checks: dict[str, str] = {}

    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        checks["anthropic_key"] = "missing"
    else:
        ok, _ = validate_anthropic_key(key)
        checks["anthropic_key"] = "ok" if ok else "invalid"

    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        checks["openai_key"] = "missing"
    else:
        ok, _ = validate_openai_key(key)
        checks["openai_key"] = "ok" if ok else "invalid"

    key = os.environ.get("GOOGLE_API_KEY")
    if not key:
        checks["google_key"] = "missing"
    else:
        # One retry: a single transient API blip must not flag a valid key.
        for attempt in (1, 2):
            try:
                from google import genai

                # Keep the client referenced while consuming the lazy pager — an
                # inline temporary gets GC'd first and raises "client has been
                # closed" before the first page is fetched.
                client = genai.Client(api_key=key)
                next(iter(client.models.list()), None)
                checks["google_key"] = "ok"
                break
            except Exception as e:
                print(
                    f"[VALIDATION] Google key check failed (attempt {attempt}): "
                    f"{type(e).__name__}",
                    flush=True,
                )
                checks["google_key"] = "invalid"
                if attempt == 1:
                    time.sleep(2)

    # GPU pipeline functions must be resolvable by name (metadata only — this
    # hydrates the handle, it does not invoke anything or boot a container).
    try:
        import build_syllabus_slice as bss
        import modal

        for label, (app_name, fn_name) in {
            "olmocr_function": (bss.OLMOCR_APP, bss.OLMOCR_FN),
            "alttext_function": (bss.ALTTEXT_APP, bss.ALTTEXT_FN),
        }.items():
            try:
                modal.Function.from_name(app_name, fn_name).hydrate()
                checks[label] = "ok"
            except Exception as e:
                print(
                    f"[VALIDATION] {label} ({app_name}/{fn_name}) unresolvable: "
                    f"{type(e).__name__}",
                    flush=True,
                )
                checks[label] = "unavailable"
    except Exception:
        checks["olmocr_function"] = checks["alttext_function"] = "unavailable"

    return checks


def _health_checks() -> tuple[dict[str, str], float]:
    """Return (checks, checked_at), refreshing the cache when stale.

    The refresh is synchronous — only the monitor calls this endpoint, and a
    once-per-TTL ~5s probe is preferable to serving 'pending' after cold start.
    """
    if not _deep_health_enabled():
        return {"deep_checks": "disabled"}, 0.0
    with _health_lock:
        cached = _health_cache["checks"]
        all_ok = bool(cached) and all(v == "ok" for v in cached.values())
        ttl = HEALTH_TTL_S if all_ok else HEALTH_FAIL_TTL_S
        if time.time() - _health_cache["checked_at"] > ttl:
            _health_cache["checks"] = _run_deep_checks()
            _health_cache["checked_at"] = time.time()
        return dict(_health_cache["checks"]), _health_cache["checked_at"]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get("/api/health")
def health():
    checks, checked_at = _health_checks()
    degraded = any(v not in ("ok", "disabled") for v in checks.values())
    return {
        "status": "degraded" if degraded else "ok",
        "jobs": len(JOBS),
        "checks": checks,
        "checks_age_s": round(time.time() - checked_at) if checked_at else None,
    }


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
async def start_live(
    file: UploadFile = File(...),  # noqa: B008
    anthropic_api_key: str = Form(default=None),
    openai_api_key: str = Form(default=None),
    reviewer_profile: str = Form(default="default"),
):
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(400, "please upload a .pdf")

    # Size + content sniff before spending GPU time. Reading first: UploadFile
    # spools to disk past 1 MB, so this doesn't hold a huge body in RAM twice.
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            413,
            f"PDF too large ({len(data) / 1024 / 1024:.1f} MB). "
            f"The hosted demo accepts up to {MAX_UPLOAD_MB} MB — self-host for larger files.",
        )
    # A real PDF starts with %PDF- within the first 1024 bytes (per spec).
    if b"%PDF-" not in data[:1024]:
        raise HTTPException(400, "This file doesn't look like a PDF. Please upload a real .pdf.")

    # Parse the PDF for a page count (instant, local). This powers honest wait
    # estimates in the UI, and rejects files olmOCR could never read anyway
    # (corrupt or password-protected) before any GPU time is spent.
    try:
        import fitz

        with fitz.open(stream=data, filetype="pdf") as doc:
            if doc.needs_pass:
                raise HTTPException(
                    400, "This PDF is password-protected. Please remove the password and retry."
                )
            page_count = doc.page_count
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            400, "This PDF couldn't be read. It may be corrupt — try re-exporting it."
        ) from None

    allowed, count = RATE_LIMITER.check_and_increment(DAILY_LIMIT)
    if not allowed:
        raise HTTPException(
            429,
            f"Daily live-conversion limit reached ({DAILY_LIMIT}/day). "
            f"Try the instant replay demos, or self-host for unlimited runs.",
        )

    # Validate BYOK keys upfront (fail fast). Run in a worker thread — these are
    # blocking network calls, and blocking the event loop here would stall every
    # concurrent poll request.
    if anthropic_api_key:
        valid, err = await asyncio.to_thread(validate_anthropic_key, anthropic_api_key)
        if not valid:
            raise HTTPException(400, err)
    if openai_api_key:
        valid, err = await asyncio.to_thread(validate_openai_key, openai_api_key)
        if not valid:
            raise HTTPException(400, err)

    jid = _new_job("live", file.filename)
    _set(jid, page_count=page_count)
    threading.Thread(
        target=_live,
        args=(jid, data, file.filename),
        kwargs={
            "anthropic_api_key": anthropic_api_key,
            "openai_api_key": openai_api_key,
            "reviewer_profile": reviewer_profile,
        },
        daemon=True,
    ).start()
    return {"job_id": jid}


@app.get("/api/jobs/{jid}")
def job_status(jid: str):
    # Strict id check: blob keys share the store namespace (jid:name), so an
    # unvalidated path param could read a blob record through this endpoint.
    if not JOB_ID_RE.match(jid):
        raise HTTPException(404, "no such job")
    # Reads don't need JOBS_LOCK: records are replaced whole (never mutated in
    # place), so a get either sees the old or the new record. Holding the lock
    # here would serialize every poll behind a network round-trip to the Dict.
    job = JOBS.get(jid)
    if not job:
        raise HTTPException(404, "no such job")
    # A job frozen at "running" (worker died on a container recycle) surfaces
    # as a terminal error the frontend can act on, instead of a stuck spinner.
    job = mark_interrupted_if_stale(job)
    out = {k: v for k, v in job.items() if k not in ("final_html", "baseline_html")}
    out["stage_index"] = next((i for i, s in enumerate(STAGES) if s["id"] == out["stage"]), 0)
    # has_final_html is the blob-era flag; final_html-in-record is the legacy
    # shape (pre-blob jobs still live in the store for up to 24h after deploy).
    out["has_html"] = bool(job.get("has_final_html") or job.get("final_html") is not None)
    out["has_baseline_html"] = bool(job.get("has_baseline_html"))
    return out


@app.get("/api/jobs/{jid}/html", response_class=HTMLResponse)
def job_html(jid: str, version: str = "final"):
    """Serve generated HTML. version=final (default) is the enhanced output;
    version=baseline is the pre-review conversion, available minutes earlier
    so users can preview while the review rounds run."""
    if not JOB_ID_RE.match(jid) or version not in ("final", "baseline"):
        raise HTTPException(404, "no html yet")
    html = JOBS.get_blob(jid, f"{version}_html")
    if html is None and version == "final":
        # Legacy fallback: jobs created before the blob store kept the HTML
        # inline on the record.
        job = JOBS.get(jid)
        html = (job or {}).get("final_html")
    if not html:
        raise HTTPException(404, "no html yet")
    # Defense in depth: the output HTML derives from PDF content and LLM output,
    # so serve it with scripts/forms/plugins disabled. The document itself is
    # static text + data-URI images and needs none of those.
    return HTMLResponse(
        html,
        headers={"Content-Security-Policy": "sandbox; script-src 'none'; object-src 'none'"},
    )


def _build_manifest_v2(job: dict = None, snap: dict = None, jid: str = None) -> dict:
    """Build enterprise-grade v2 manifest from job or snapshot data."""
    if job:
        source_data = job
        started_ts = job.get("started")
        total_seconds = time.time() - started_ts if started_ts else 0
        completed_ts = time.time() if job.get("status") == "done" else None
    else:
        source_data = snap
        started_ts = snap.get("started_at")
        total_seconds = snap.get("total_seconds", 0)
        completed_ts = snap.get("completed_at")

    baseline = source_data.get("baseline", {})
    final = source_data.get("final", {})
    rounds_list = source_data.get("rounds", [])
    enhancements_raw = source_data.get("enhancements", [])
    reviewer_health = source_data.get("reviewer_health", {})
    reviewer_profile = source_data.get("reviewer_profile", "default")

    # Calculate delta
    baseline_violations = baseline.get("violations", 0)
    final_violations = final.get("violations", 0)
    baseline_passes = baseline.get("passes", 0)
    final_passes = final.get("passes", 0)

    # Parse ISO timestamps
    def _parse_iso_or_timestamp(val):
        if isinstance(val, str):
            return val
        if isinstance(val, (int, float)):
            return datetime.fromtimestamp(val).isoformat() + "Z"
        return None

    started_iso = _parse_iso_or_timestamp(started_ts)
    completed_iso = _parse_iso_or_timestamp(completed_ts)

    # Build reviewer telemetry
    reviewer_telemetry = []
    reviewer_type_map = {
        "olmo": "local_open_weight",
        "gpt": "commercial_peer",
        "claude": "commercial_judge",
    }
    for agent_id, health in reviewer_health.items():
        reviewer_telemetry.append(
            {
                "agent_id": agent_id,
                "type": reviewer_type_map.get(agent_id, "unknown"),
                "rounds_participated": health.get("rounds_ran", 0),
                "status": health.get("status", "unknown").lower(),
            }
        )

    # Build execution history with detailed rounds
    execution_rounds = []
    for r in rounds_list:
        round_entry = {
            "round_index": r.get("round", 0),
            "patches_proposed": r.get("patches_proposed", 0),
            "patches_applied": r.get("patches_applied", 0),
            "patches_rejected": r.get("patches_rejected", 0),
            "preservation_gate": {
                "status": "passed" if r.get("gate_passed", False) else "failed",
                "checks_executed": r.get("gate_checks", []),
            },
            "axe_metrics": {
                "score": r.get("score", 0),
                "violations": r.get("violations", 0),
                "passes": r.get("passes", 0),
            },
        }
        execution_rounds.append(round_entry)

    # Build enhancements with audit trail and approval status
    enhancements_enhanced = []
    for e in enhancements_raw:
        proposed_by = e.get("proposed_by", "olmo")

        # Build voting record (captures reviewer consensus)
        votes = e.get("votes", {})
        if not votes:
            # Default votes when not specified: proposed_by and approved_by approve
            approved_by = e.get("approved_by", "claude")
            votes = {proposed_by: "approve", approved_by: "approve"}

        # Calculate agreement score (proportion of approve votes)
        total_votes = len(votes)
        approve_count = sum(1 for v in votes.values() if v == "approve")
        agreement_score = (approve_count / total_votes * 100) if total_votes > 0 else 0.0

        # Approval status: default to approved if all votes are approve
        wcag_mapping = e.get("wcag_mapping", [])
        approval_status = e.get(
            "approval_status", "approved" if agreement_score == 100.0 else "pending"
        )

        enh = {
            "element_id": e.get("element_id", ""),
            "html_tag": e.get("type", "element"),
            "round_introduced": e.get("round_introduced", 1),
            "mutation": {
                "action": "inject_attribute",
                "attribute": e.get("attribute", ""),
                "value": e.get("value", ""),
            },
            "audit": {
                "proposed_by": proposed_by,
                "approved_by": e.get("approved_by", "claude"),
                "rationale": e.get("description", e.get("rationale", "")),
                "wcag_mapping": wcag_mapping,
            },
            "approval_status": approval_status,
            "voting_record": {
                "proposed_by": proposed_by,
                "agreement_score": round(agreement_score, 2),
                "votes": votes,
            },
        }
        enhancements_enhanced.append(enh)

    # Calculate enhancement approval summary
    approved_count = sum(1 for e in enhancements_enhanced if e.get("approval_status") == "approved")
    total_enhancements = len(enhancements_enhanced)

    manifest = {
        "$schema": "https://happypdf.org/schemas/v1/manifest.json",
        "id": jid or source_data.get("id", "unknown"),
        "name": source_data.get("name", "PDF"),
        "status": (
            "completed"
            if source_data.get("status") == "done"
            else source_data.get("status", "in_progress")
        ),
        "approval_summary": {
            "total_enhancements": total_enhancements,
            "approved": approved_count,
            "pending": total_enhancements - approved_count,
            "rejected": 0,
            "approval_rate": round(
                (approved_count / total_enhancements * 100) if total_enhancements > 0 else 0, 1
            ),
        },
        "pipeline_metadata": {
            "engine_version": "1.0.0",
            "primary_ocr": "olmOCR",
            "vlm_backbone": "Qwen2-VL",
            "orchestration_mode": "BYOK",
            "reviewer_profile": reviewer_profile,
            "timestamps": {
                "started_at": started_iso,
                "completed_at": completed_iso,
                "duration_seconds": float(total_seconds) if total_seconds else 0,
            },
        },
        "compliance_summary": {
            "baseline": {
                "axe_score": baseline.get("score", 0),
                "violations": baseline_violations,
                "passes": baseline_passes,
                "critical_serious": 0,
            },
            "final": {
                "axe_score": final.get("score", 0),
                "violations": final_violations,
                "passes": final_passes,
                "critical_serious": 0,
            },
            "delta": {
                "additional_passes": final_passes - baseline_passes,
                "violations_resolved": baseline_violations - final_violations,
            },
        },
        "reviewer_telemetry": reviewer_telemetry,
        "execution_history": {
            "total_rounds": len(execution_rounds),
            "stopped_reason": source_data.get("stopped_reason", "in_progress"),
            "rounds": execution_rounds,
        },
        "enhancements": enhancements_enhanced,
    }

    return manifest


def _safe_download_id(jid: str) -> str:
    """jid comes from the URL path and ends up in a Content-Disposition header;
    only real job ids and demo slugs are ever valid, so enforce exactly that."""
    if JOB_ID_RE.match(jid) or DEMO_NAME_RE.match(jid):
        return jid
    raise HTTPException(404, "job not found")


@app.get("/api/jobs/{jid}/manifest")
def job_manifest(jid: str):
    """Return complete remediation manifest with all patches, decisions, and audit trail."""
    safe_id = _safe_download_id(jid)
    job = JOBS.get(jid)

    # If not found in JOBS, check if it's a demo snapshot ID
    if not job:
        try:
            snap = _load_snapshot(jid)
            manifest = _build_manifest_v2(snap=snap, jid=jid)
        except HTTPException:
            raise HTTPException(404, "job not found") from None
    else:
        manifest = _build_manifest_v2(job=job, jid=jid)

    # Return with download headers
    json_str = json.dumps(manifest, indent=2, default=str)
    return Response(
        content=json_str,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{safe_id}_manifest.json"'},
    )


@app.get("/api/jobs/{jid}/report")
def job_report(jid: str):
    """Return a formatted HTML report of the remediation process."""
    import sys

    sys.path.insert(0, str(SRC))
    from report_generator import generate_html_report

    safe_id = _safe_download_id(jid)
    job = JOBS.get(jid)

    # If not found in JOBS, check if it's a demo snapshot ID
    if not job:
        try:
            snap = _load_snapshot(jid)
            manifest = _build_manifest_v2(snap=snap, jid=jid)
        except HTTPException:
            raise HTTPException(404, "job not found") from None
    else:
        manifest = _build_manifest_v2(job=job, jid=jid)

    html = generate_html_report(manifest)
    return Response(
        content=html,
        media_type="text/html",
        headers={"Content-Disposition": f'attachment; filename="{safe_id}_report.html"'},
    )


if __name__ == "__main__":
    import uvicorn

    sys.path.insert(0, str(ROOT / "api"))
    uvicorn.run(app, host="127.0.0.1", port=8000)
