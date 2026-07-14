#!/usr/bin/env python3
"""
Live peer reviewers: OLMo (Modal), Gemini (Google), GPT (OpenAI).

Each reviewer reads the *current* HTML (which carries data-ir-id attributes) and
returns accessibility issues citing those ids, in the standard schema the judge
consumes:
    {issue_id, wcag_criterion, element_id, issue, impact, confidence,
     suggested_fix, fix_type, hallucinated}

`get_live_reviews(html, round_num)` calls reviewers in parallel (profile-dependent)
and returns a dict keyed by reviewer name — {"olmo": [...], "gemini": [...], ...} —
which is exactly the shape the mock files use, so it drops straight into the
loop's `reviews_provider`. (The spec sketched a flat list; the per-reviewer dict
is required for the judge's agreement/confidence logic.)

Profiles:
- "default" (env: REVIEWER_PROFILE=default or unset): calls OLMo, Gemini, GPT in parallel
- "olmo-only" (env: REVIEWER_PROFILE=olmo-only): calls only OLMo (single-model review)

Resilience: each reviewer is retried once with exponential backoff; a reviewer
that still fails is logged and skipped (the round continues with the others).
If ALL reviewers fail, get_live_reviews raises AllReviewersFailed so the caller
can abort the round.

Credentials are read from the environment (load .env first). OLMo uses Modal
auth (~/.modal.toml); Gemini needs GOOGLE_API_KEY; GPT needs OPENAI_API_KEY.
"""

import asyncio
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

GEMINI_MODEL = "gemini-2.5-flash"
GPT_MODEL = "gpt-4o-mini"
OLMO_URL = os.environ.get(
    "OLMO_REVIEWER_URL",
    "https://brendanworks--olmo-wcag-reviewer-api.modal.run",
)

# Per-reviewer context budgets. OLMo has a 4k-token context (8k chars ≈ 2k tokens
# leaves room for the prompt); Gemini 2.5 Flash and GPT-4o-mini have 100k+ token
# windows, so they get the whole document (bounded to keep cost sane).
OLMO_MAX_HTML_CHARS = 8000
MAX_HTML_CHARS = 60000
RETRIES = 1  # one retry after the first failure
BACKOFF_BASE = 2.0  # seconds: 2, 4, ...

REVIEW_INSTRUCTION = (
    "You are a WCAG 2.2 accessibility reviewer. You are given an HTML fragment in "
    "which every block-level element has a stable `data-ir-id` attribute. Identify "
    "accessibility issues that can be fixed by adding or correcting ARIA attributes "
    "(aria-label, role, aria-describedby) or alt text. For each issue, cite the exact "
    "`data-ir-id` value of the element it applies to — never invent an id that is not "
    "present in the HTML. Prefer concrete, deterministic fixes and put the literal "
    'attribute and value in suggested_fix, e.g. \'Add aria-label="Class schedule" to '
    "the table.'\n\n"
    "Respond with ONLY a JSON object of the form:\n"
    '{"violations": [{"issue_id": "string", "wcag_criterion": "1.3.1", '
    '"element_id": "block-1-...", "issue": "short description", '
    '"impact": "critical|serious|moderate|minor", "confidence": 0.0-1.0, '
    '"suggested_fix": "concrete fix", "fix_type": "deterministic|llm_safe|needs_human", '
    '"hallucinated": false}]}'
)


class AllReviewersFailed(Exception):
    pass


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [reviewers] {msg}", flush=True)


def load_env() -> None:
    """Minimal .env loader (no dependency) — only sets vars that are unset."""
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------
def _extract_json(text: str) -> dict | list:
    text = (text or "").strip()
    if text.startswith("```"):  # strip markdown code fences
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Salvage the first complete JSON value, ignoring trailing junk
        # (small models often emit "Extra data" after a valid object).
        m = re.search(r"[\{\[]", text)
        if m:
            return json.JSONDecoder().raw_decode(text[m.start() :])[0]
        raise


def _normalize(raw, reviewer: str, valid_ids: set[str]) -> list[dict]:
    """Coerce any reviewer output into the standard issue schema, keeping only
    issues that target a data-ir-id actually present in the HTML."""
    if isinstance(raw, dict):
        items = raw.get("violations") or raw.get("issues") or []
    elif isinstance(raw, list):
        items = raw
    else:
        items = []
    out = []
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            continue
        eid = it.get("element_id") or it.get("elementId") or it.get("id")
        if not eid or eid not in valid_ids:
            continue  # drop issues that cite an unknown/missing id
        fix_type = it.get("fix_type") or "deterministic"
        if it.get("requires_human_review") or it.get("requires_long_desc"):
            fix_type = "needs_human"
        out.append(
            {
                "issue_id": it.get("issue_id") or f"{reviewer}-{i}",
                "wcag_criterion": str(it.get("wcag_criterion") or it.get("criterion") or "1.3.1"),
                "element_id": eid,
                "issue": it.get("issue") or it.get("description") or "",
                "impact": it.get("impact") or "moderate",
                "confidence": float(it.get("confidence", 0.75) or 0.75),
                "suggested_fix": it.get("suggested_fix") or it.get("fix") or "",
                "fix_type": fix_type,
                "hallucinated": bool(it.get("hallucinated", False)),
            }
        )
    return out


def _valid_ids(html: str) -> set[str]:
    return set(re.findall(r'data-ir-id="([^"]+)"', html))


def _strip_data_uris(html: str) -> str:
    """Replace base64 data-URI image payloads with a placeholder before review.

    The output HTML embeds every image as a data: URI so it is self-contained;
    a single embedded image can be hundreds of KB of base64. Sending that to
    reviewers wastes the entire context window on noise the models cannot read.
    The <img> element, its data-ir-id, and its alt text (what reviewers actually
    assess) are preserved."""
    return re.sub(r'src="data:[^"]*"', 'src="embedded-image"', html)


def _clip(html: str, limit: int = MAX_HTML_CHARS) -> str:
    return html if len(html) <= limit else html[:limit]


# ---------------------------------------------------------------------------
# Individual reviewers (raw call -> text); normalization happens in the gather
# ---------------------------------------------------------------------------
async def _call_gemini(html: str, api_key: str | None = None) -> str:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key or os.environ["GOOGLE_API_KEY"])
    resp = await client.aio.models.generate_content(
        model=GEMINI_MODEL,
        contents=f"HTML to review:\n{_clip(html)}",
        config=types.GenerateContentConfig(
            system_instruction=REVIEW_INSTRUCTION,
            response_mime_type="application/json",
        ),
    )
    return resp.text


async def _call_gpt(html: str, api_key: str | None = None) -> str:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=api_key or os.environ["OPENAI_API_KEY"])
    resp = await client.chat.completions.create(
        model=GPT_MODEL,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": REVIEW_INSTRUCTION},
            {"role": "user", "content": f"HTML to review:\n{_clip(html)}"},
        ],
    )
    return resp.choices[0].message.content


async def _call_olmo(html: str, api_key: str | None = None) -> str:
    # Use a synchronous client in a worker thread: a per-round asyncio.run() closes
    # its loop before httpx's async client finishes TLS teardown, which spews
    # "Event loop is closed" noise. A sync client sidesteps that entirely while
    # still running in parallel with the other reviewers via the thread executor.
    import httpx

    # The OLMo Modal endpoint requires a shared bearer token when the server has
    # OLMO_REVIEWER_TOKEN set (see modal/modal_olmo_wcag.py). Self-hosted open
    # deployments may leave it unset on both sides.
    token = os.environ.get("OLMO_REVIEWER_TOKEN", "")
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    def _sync() -> str:
        with httpx.Client(timeout=300, follow_redirects=True) as client:
            r = client.post(
                f"{OLMO_URL}/review",
                headers=headers,
                json={
                    "html_chunk": _clip(html, OLMO_MAX_HTML_CHARS),
                    "system_prompt": REVIEW_INSTRUCTION,
                    "max_tokens": 1024,
                },
            )
            r.raise_for_status()
            data = r.json()
            if not data.get("success"):
                raise RuntimeError(data.get("error", "OLMo review failed"))
            raw_output = data.get("raw_output", "")
            # Verify it looks like JSON, not plain text prose
            if raw_output and not raw_output.strip().startswith(("{", "[")):
                # OLMo is returning plain text instead of JSON - likely not following the instruction
                raise RuntimeError(f"OLMo returned non-JSON text: {raw_output[:100]}")
            return raw_output

    return await asyncio.to_thread(_sync)


REVIEWERS = {"olmo": _call_olmo, "gemini": _call_gemini, "gpt": _call_gpt}


def _available(name: str, openai_api_key: str | None = None) -> bool:
    if name == "gemini":
        return bool(os.environ.get("GOOGLE_API_KEY"))
    if name == "gpt":
        return bool(openai_api_key or os.environ.get("OPENAI_API_KEY"))
    return True  # olmo uses Modal auth


def _get_profile_reviewers(profile: str) -> dict[str, callable]:
    """Return the set of reviewers for a given profile.

    Args:
        profile: "default" for multi-model (OLMo + Gemini + GPT) or "olmo-only"
                 for single-model (OLMo only). Default if unset or invalid: "default".

    Returns:
        Dict of {reviewer_name: callable} for this profile.
    """
    profile = (profile or "default").lower().strip()
    if profile == "olmo-only":
        return {"olmo": REVIEWERS["olmo"]}
    # default: all reviewers
    return REVIEWERS


async def _run_one(name: str, fn, html: str, valid_ids: set[str]) -> tuple[str, list[dict] | None]:
    """Call one reviewer with one retry; return (name, issues) or (name, None) on failure."""
    for attempt in range(RETRIES + 1):
        t0 = time.time()
        try:
            raw = await fn(html)
            issues = _normalize(_extract_json(raw), name, valid_ids)
            log(f"{name}: {len(issues)} issue(s) in {time.time() - t0:.1f}s")
            return name, issues
        except Exception as e:
            dt = time.time() - t0
            # Log exception type but truncate message to avoid leaking credentials
            error_summary = f"{type(e).__name__}"
            if str(e) and len(str(e)) < 200:
                error_summary += f": {str(e)[:150]}"

            # Always log full exception for diagnostic purposes (OLMo debugging)
            if name == "olmo":
                import traceback

                log(f"{name}: FAILED in {dt:.1f}s ({error_summary})")
                log(f"{name}: Full traceback: {traceback.format_exc()[:500]}")

            if attempt < RETRIES:
                wait = BACKOFF_BASE ** (attempt + 1)
                log(f"{name}: FAILED in {dt:.1f}s ({error_summary}); retrying in {wait:.0f}s")
                await asyncio.sleep(wait)
            else:
                log(f"{name}: FAILED in {dt:.1f}s ({error_summary}); skipping")
                return name, None


async def get_live_reviews(
    html: str,
    round_num: int,
    profile: str = "default",
    openai_api_key: str | None = None,
) -> tuple[dict[str, list[dict]], dict[str, dict]]:
    """Call reviewers in parallel based on profile; return ({reviewer: [issues]}, {reviewer: health_info}).

    Args:
        html: HTML fragment to review
        round_num: review round number (for logging)
        profile: "default" (OLMo+Gemini+GPT) or "olmo-only" (OLMo only)
        openai_api_key: optional BYOK OpenAI key for the GPT reviewer. Passed
            explicitly (never via environment mutation) so concurrent jobs with
            different credentials cannot leak keys to each other.

    Reviewers without credentials are skipped with a warning. Raises
    AllReviewersFailed if no reviewer produced a result."""
    load_env()
    # valid_ids is computed on the full HTML; reviewers see a data-URI-stripped
    # copy so their context budget goes to real content, not base64 payloads.
    valid_ids = _valid_ids(html)
    review_html = _strip_data_uris(html)
    profile_reviewers = _get_profile_reviewers(profile)
    active = {n: f for n, f in profile_reviewers.items() if _available(n, openai_api_key)}
    skipped = [n for n in profile_reviewers if n not in active]
    if skipped:
        log(f"round {round_num}: skipping (no credentials): {', '.join(skipped)}")
    log(
        f"round {round_num}: calling {', '.join(active)} in parallel (profile={profile}) "
        f"({len(valid_ids)} addressable elements)"
    )

    def _bound(fn, name: str):
        if name == "gpt" and openai_api_key:
            return lambda h: fn(h, api_key=openai_api_key)
        return fn

    results = await asyncio.gather(
        *[_run_one(n, _bound(f, n), review_html, valid_ids) for n, f in active.items()]
    )

    reviews, health, failures = {}, {}, 0
    for name, issues in results:
        if issues is None:
            failures += 1
            health[name] = {"status": "failed", "round": round_num}
        else:
            reviews[name] = issues
            health[name] = {"status": "success", "round": round_num}
    # Return health even if all reviewers failed — caller needs this for telemetry
    if active and failures == len(active):
        log(
            f"round {round_num}: all {failures} reviewer(s) failed; returning health telemetry before raising"
        )
        # Create an exception with health attached so it can be extracted
        exc = AllReviewersFailed(f"all {failures} reviewer(s) failed in round {round_num}")
        exc.health = health  # Attach health data to exception
        raise exc
    return reviews, health


def make_live_provider(profile: str | None = None, openai_api_key: str | None = None):
    """Build a reviews_provider(round, html) bound to explicit credentials.

    This is the BYOK entry point: the caller passes per-job credentials here
    instead of mutating os.environ, so concurrent jobs can never observe each
    other's keys. Falls back to the REVIEWER_PROFILE env var / hosted default
    keys for anything not supplied."""
    resolved_profile = profile or os.environ.get("REVIEWER_PROFILE", "default")

    def provider(round_num: int, html: str) -> tuple[dict[str, list[dict]], dict[str, dict]]:
        return asyncio.run(
            get_live_reviews(
                html, round_num, profile=resolved_profile, openai_api_key=openai_api_key
            )
        )

    return provider


def live_provider(round_num: int, html: str) -> tuple[dict[str, list[dict]], dict[str, dict]]:
    """Synchronous adapter matching the loop's reviews_provider(round, html).
    Returns (reviews, health_info).

    Reads REVIEWER_PROFILE env var for profile selection ("default" or "olmo-only").
    """
    profile = os.environ.get("REVIEWER_PROFILE", "default")
    return asyncio.run(get_live_reviews(html, round_num, profile=profile))
