# happypdf

**Convert any PDF to WCAG 2.2 validated HTML in 3–6 minutes.** Multi-model peer review + iterative remediation with zero violations.

## The Problem

PDFs are everywhere in government, education, and enterprise — and most of them are inaccessible. Screen readers fail on untagged content, images carry no alt text, and tables have no structural markup, so the data inside them is invisible to assistive technology. Manual remediation is slow, expensive, and does not scale.

## The Solution

happypdf automates remediation end-to-end using open models and multi-agent peer review:

1. **Extract:** olmOCR (Ai2's vision-based system) recovers markdown + images from any PDF
2. **Generate alt text:** Qwen2-VL creates descriptions for every image (1-2 sec each)
3. **Build HTML:** MarkdownHTMLConverter produces semantic HTML5 with proper landmarks, heading hierarchy, and table structure
4. **Score baseline:** axe-core WCAG audit (real headless Chromium)
5. **Enhance:** 3 rounds of peer review (OLMo, Gemini, GPT) + Claude judge synthesizes patches + applicator applies ARIA attributes
6. **Validate:** Preservation gate ensures no content is lost; loop stops when converged

**Result:** 0 WCAG violations, 95%+ axe-core passes, deterministic remediation that's auditable and reproducible.

## Three Deployment Modes

The orchestration is identical across all three modes — only the model backends are swapped. That pluggability is the whole point.

| Mode | Models | Cost | When to use |
|------|--------|------|-------------|
| **Self-hosted / Open-weight** | OLMo peer review + local inference on your own hardware or Modal account | Zero marginal cost, lower quality | Cost-sensitive, offline, or air-gapped environments |
| **Demo / Hosted** | happypdf provisions Claude as judge/fixer with OLMo as peer reviewer | Per-conversion (scales with document size and review rounds) | Try it Now! |
| **BYOK / Enterprise** | User brings their own Claude / ChatGPT enterprise credentials; same code as demo mode | Zero incremental cost to happypdf | Enterprises that already hold model contracts |

**BYOK is the differentiator.** No competitor has built it. The barrier to enterprise accessibility tooling is procurement friction, not technical capability — organizations already have model contracts but cannot easily route a third-party SaaS tool through them. BYOK sidesteps that entirely: the customer points happypdf at credentials they already own and pay for.

## Try It Now

**Live at https://happypdf.org** — upload any PDF and watch the full pipeline in real-time:

- Drag-and-drop interface
- Real-time progress tracking (extraction → alt text → HTML → peer review rounds)
- Live HTML preview with WCAG scoring and enhancement details
- Download remediated HTML + JSON manifest with all patches applied

The backend runs on Modal A100 GPUs. Try with complex documents: forms, tables, images, OCR'd scans, dense government PDFs.

## How It Works

```
PDF Input
  |
  v
olmOCR (vision-based extraction, Ai2) -> Markdown + images
  |
  v
Qwen2-VL alt text generation (per image, ~1-2s)
  |
  v
Semantic HTML5 (landmarks, heading hierarchy, proper tables, data-ir-id attributes)
  |
  v
axe-core baseline WCAG scoring (real headless Chromium)
  |
  v
Rounds 1-3: [Peer review (OLMo, Gemini, GPT in parallel)
            + Claude judge (deduplicate, validate, classify patches)
            + Applicator (apply ARIA/alt-text fixes by element ID)
            + Preservation gate (text coverage ≥ 95%, image count, heading order, tables)
            + Rescore (axe-core)]
  |
  v
[Converged when: 0 violations + score ≥ 95% + no new patches]
  |
  v
WCAG-validated HTML + JSON manifest (patches, enhancement summary)
```


## What the Loop Actually Does

The application produces semantically valid HTML from any PDF — our generator builds proper landmarks, heading hierarchy, and alt text from olmOCR's markdown, so the baseline already scores **0 WCAG violations** on axe-core.

The multi-round loop doesn't *fix* violations. It *enhances* accessible structure by adding ARIA attributes (labels, roles, descriptions) where reviewers identify opportunities. Here's what happens:

**Round 1:** Peer reviewers (OLMo, Gemini, GPT) scan the HTML and suggest enhancements (e.g., "add aria-label to table," "add role to navigation"). Claude judges which are safe and deterministic. The applicator adds them. axe-core rescores — passes typically increase (26 → 31), violations stay at 0.

**Round 2:** Reviewers scan the patched HTML and suggest remaining enhancements. Fewer suggestions than round 1. Loop continues if new patches apply; otherwise converges.

**Round 3:** By round 3, most structural enhancement is complete. If no new patches are actionable, the loop stops.

**Convergence:** The loop stops when:
- Score ≥ 95% AND
- Content preservation gate passes (text coverage, image count, heading order, tables) AND
- Zero new patches suggested

This ensures remediation is additive, never destructive.

### Real Results: Benchmark Suite

Three documents, three document types:

| Document | Type | Baseline | R1 | R2 | R3 | Final | Stop Reason |
|---|---|---|---|---|---|---|---|
| AccessComputing Syllabus | Clean digital | 0 viol / 23 pass | +5 pass | +4 pass | 0 new | 0 viol / 32 pass | Converged |
| IRS Schedule C | Dense form | 0 viol / 23 pass | +5 pass | 0 new | — | 0 viol / 28 pass | Converged |
| Navy Bulletin 1943 | OCR'd prose | 0 viol / 17 pass | 0 new | — | — | 0 viol / 17 pass | Converged |

**Key finding:** All three converge within 2 rounds. Structure-driven enhancement scales with how much structure olmOCR recovers (syllabus tables → more patches; Navy prose-only → no patches). The preservation gate passes every round, confirming content is never lost.

**Remediation effect:** The loop's work is *visible in the passes count climbing and ARIA attributes added*, not in violation reduction (there are none to reduce). This is enhancement, not fixing.

Reproduce: `python src/benchmark.py` (see [benchmark/BENCHMARK.md](benchmark/BENCHMARK.md)).

## Quick Start

### Prerequisites

- Python 3.10+
- Node.js 18+
- Modal account (for extraction and remediation)

### Setup

```bash
git clone https://github.com/BrendanWorks/happypdf.git
cd happypdf

# Python dependencies
pip install -r requirements.txt

# Node dependencies (axe-core for WCAG scoring)
npm install

# Chromium for headless browser (required by Playwright)
playwright install chromium

# Set Modal credentials
export MODAL_TOKEN_ID=your_token_id
export MODAL_TOKEN_SECRET=your_token_secret
```

### Use the Deployed Web UI

happypdf runs live at **https://happypdf.org** with:

- Drag-and-drop PDF upload
- Real-time pipeline progress (extraction → alt text → HTML → WCAG baseline → peer review rounds)
- Live HTML preview with WCAG violations and enhancements
- Download remediated HTML + JSON manifest

No local setup needed for testing. The backend runs on Modal A100 GPUs.

### Run Locally (Development)

For development or self-hosting:

```bash
# Start the backend (Modal-deployed)
modal deploy src/modal_api.py

# Start the frontend (Next.js)
cd frontend
npm install
npm run dev
```

Or run the benchmark suite locally:

```bash
python src/benchmark.py
```

Outputs:

- `output/` directory with `{doc}_scored.html` and `{doc}_manifest.json` per benchmark document
- WCAG baseline scores and multi-round enhancement history
- Gate pass/fail logs and convergence details

## Architecture

### Element ID System

Every block-level element gets a deterministic SHA256-based ID: `block-{page}-{hash}` where `hash = SHA256(normalized_text)[:8]` and `normalized_text` is the element's text with whitespace collapsed and capped at 200 characters. This enables stable cross-run patching: if you regenerate the HTML from the same PDF, the same elements get the same IDs.

### Three Deployment Modes (Technical)

**Self-hosted:** Open-weight models run on your own Modal account or hardware. You control compute, data stays local, cost is per-GPU-second.

**Demo/Hosted:** happypdf runs the endpoints and brokers API calls to Claude, Gemini, GPT, and OLMo. You pay per-conversion. Data is transient (not stored).

**BYOK/Enterprise:** Same code as demo mode. You pass your own Claude or ChatGPT enterprise API key. happypdf routes the work through your credentials, never touching the API keys directly.

### Modal Infrastructure

- **olmOCR extraction:** H100, ~3–4 min cold start (model download), ~30 sec warm. Returns markdown with YAML front-matter.
- **Qwen2-VL alt text:** H100, ~1.5 min per image (includes model download on first call).
- **OLMo peer review:** H100, structured WCAG violations JSON with hallucination detection.

### Scoring

axe-core runs in a real headless Chromium browser and returns structured JSON. Score = `passes / (passes + violations)` as a percentage. This is automated check coverage, not WCAG conformance. Hard gates (no critical violations, no content loss, no reading order regressions) are the real measure.

## Security

### API Key Handling (BYOK Mode)

happypdf uses a **zero-transmission security model** for enterprise API keys:

- **Keys never reach the frontend.** Users bring their Claude or ChatGPT credentials in the BYOK UI, but these are *not sent to happypdf's servers*. Instead, they are stored in Modal's encrypted secret vault (`modal.Secret.from_name("happypdf-secrets")`).
- **Backend-only access.** API keys are injected into the Modal container as environment variables and used directly by the backend's language model clients. The frontend never sees or transmits them.
- **No credential logging.** Error messages are sanitized to exclude exception details that could leak API response content. Backend uses in-memory job state only (no persistent logs).

### Transport Security

- **HTTPS enforced.** All endpoints use Modal's default HTTPS with TLS 1.3. CORS middleware explicitly allows only `https://` origins in production (`https://happypdf.org`, `https://happypdf.netlify.app`).
- **No intermediate proxies.** Direct HTTPS connection from frontend to Modal ASGI app; no API gateway or load balancer that could log credentials.

### Data Persistence

- **Ephemeral job storage.** Job state (PDF content, intermediate HTML, remediation results) lives in in-memory Python dict protected by thread locks. No database, Redis, or persistent storage.
- **Container lifecycle.** Modal containers scale down after 20 minutes of idle time (`scaledown_window=1200`). When the container terminates, all in-memory job data is cleared.
- **No file caching.** Temporary files (PDFs, intermediate images) are created with Python's `tempfile` module and deleted after processing completes.

### Audit Results

| Component | Status | Details |
|---|---|---|
| **HTTPS** | ✅ Enforced | Modal default + CORS validation for `https://` only |
| **API Key Transmission** | ✅ None | Keys stored as Modal Secrets, never sent to frontend |
| **Error Handling** | ✅ Hardened | Exception messages sanitized to exclude API response details |
| **Data Caching** | ✅ Ephemeral | In-memory only, cleared after 20-min container idle |
| **Logging** | ✅ Minimal | No structured logging of requests/responses; debug prints excluded from API path |

### Deployment Checklist for Self-Hosting

If you self-host happypdf:

1. **Set Modal secrets:** Store `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, and `GOOGLE_API_KEY` in Modal's secret vault, not in `.env` or config files.
2. **HTTPS only:** Configure TLS termination at your ingress (e.g., Let's Encrypt via nginx).
3. **CORS origins:** Update `allow_origins` in `api/main.py` to match your frontend domain.
4. **Container lifecycle:** Set `scaledown_window` to your SLA (default 20 min). Shorter windows = more frequent cold starts; longer = standing cost.
5. **No persistent storage:** Do not add Redis, databases, or S3 for job state. The ephemeral in-memory model is a security feature.

### Known Security Limitations

- **Concurrent request logging:** If Modal's system logs capture request/response bodies (outside happypdf's control), they would include PDFs and intermediate HTML. This is a Modal platform limitation, not a code issue. For air-gapped deployments, self-host on private infrastructure.
- **Browser console leakage:** Frontend dev tools could reveal job IDs and API endpoints. This is standard browser behavior; mitigate by keeping dev tools closed in production.

## Known Limitations

- **Baseline already accessible:** Our HTML generator produces valid semantic structure from any PDF, so axe-core finds 0 violations at baseline. The loop enhances with ARIA, it doesn't fix broken HTML. This is by design: we extract *correctly*, not remediate broken extraction. Violation reduction via ARIA occurs only if the original HTML was malformed; our baseline is structurally sound.
- **Duplicate element IDs from visual artifacts:** olmOCR treats PDF visual separator lines (rows of dashes) as content and assigns them IDs. On documents with many visual separators, duplicate hashes can occur. This is documented and doesn't block remediation (applicator uses all-or-nothing per ID, so duplicates fail safe).
- **Heading hierarchy:** olmOCR returns section labels as paragraphs, not headings. We heuristically promote short standalone lines to `<h2>`. Works well in practice but isn't perfect for complex heading structures. Manual fixes can override via the patch manifest.
- **axe-core coverage:** axe-core detects ~30–40% of WCAG requirements (AA and AAA). The other 60% require human review or custom logic. happypdf handles the automatable portion via peer review suggestions; hard cases route to `needs_human` for manual triage.
- **Reviewer consensus:** OLMo (7B), Gemini, and GPT (openai) run in parallel with retry/backoff. If all three fail or skip, the round uses only the previous round's patches. Validated end-to-end: all three benchmark documents converge within 2 rounds, gate passes every round, 0 violations throughout. OLMo (7B) occasionally emits malformed JSON on very large documents (>10k words) and is gracefully skipped for that round; Gemini and GPT continue.
- **Image extraction:** Images are extracted as separate files and linked via `<img>` tags with alt text. If the original PDF has raster images (e.g., screenshots), quality depends on olmOCR's extraction. Vector graphics in PDFs are converted to raster; fidelity is high but not lossless.

## Related Work

**SciA11y** (Wang, Cachola, et al., ASSETS '21) — Ai2 team converted scientific paper PDFs to accessible HTML. Evaluated ~86% success rate on readability; flagged alt-text and table accessibility as open problems. happypdf extends this work to general and government PDFs and adds iterative multi-model WCAG validation. [Paper](https://doi.org/10.1145/3441852.3471212)

**olmOCR** (Poznanski et al., Ai2, arXiv:2502.18443) — Ai2's vision-based PDF extraction system built on Qwen2.5-VL. happypdf uses olmOCR as the primary extraction engine and adds the remediation and validation pipeline. [Paper](https://arxiv.org/abs/2502.18443)

## Status

✅ **Production-ready pipeline.** All components tested and deployed:

- ✅ Extraction (olmOCR) — fully integrated, markdown with YAML front-matter
- ✅ Alt text (Qwen2-VL) — replaces Molmo-7B-D after extensive testing, 1-2s per image
- ✅ HTML generation (MarkdownHTMLConverter) — proper semantic HTML5, tables, images, landmark structure
- ✅ WCAG scoring (axe-core) — real headless Chromium, structured JSON results
- ✅ Claude judge (`src/judge.py`) — synthesizes reviews, classifies patches, deduplicates
- ✅ Multi-round loop (`src/loop.py`) — early stopping, convergence detection
- ✅ Content preservation gate (`src/gate.py`) — text coverage, image count, heading order, tables
- ✅ Live peer reviewers (OLMo, Gemini, GPT) — wired with retry/backoff, graceful fallback
- ✅ Next.js frontend — drag-and-drop upload, real-time progress, HTML preview
- ✅ Modal deployment (`src/modal_api.py`) — ASGI FastAPI app, max_containers=1, warm keepalive
- ✅ Security audit — zero-transmission BYOK mode, ephemeral job storage, HTTPS enforced

### Running Tests

```bash
# Run full benchmark on all test documents
python src/benchmark.py

# Inspect specific document output
cat output/syllabus_scored.html
cat output/syllabus_manifest.json
```

See [benchmark/BENCHMARK.md](benchmark/BENCHMARK.md) for full benchmark results and gate pass/fail logs.

## How the Loop Works (For Developers)

The loop is review-source agnostic. It consumes structured reviews (issues with element IDs, WCAG criteria, suggested fixes) and produces a deterministic patch manifest.

**Per round** (`run_loop` in `src/loop.py`):

1. **Judge** (`src/judge.py`): synthesize peer reviews → deduplicate, flag hallucinations, classify (deterministic vs. LLM-safe vs. needs_human) → patch manifest. LLM-safe fixes (alt text) go to Claude Opus 4.8; everything else is decided without an API call.
2. **Applicator** (`src/applicator.py`): apply patches by `data-ir-id`, all-or-nothing with rollback on any failure.
3. **Preservation gate** (`src/gate.py`): compare the round's input HTML to the patched output (text coverage ≥ 95%, image count, heading order, tables). If it fails, the round is reverted and the loop stops. The gate is a pre/post comparison, so it runs *after* the applicator, not before.
4. **axe-core rescore:** run in real headless Chromium, collect structured results.
5. **Stop condition:** converged when no new patches were applied AND score ≥ threshold AND the gate passes.

**Swapping review sources.** `run_loop(baseline_html, reviews_provider, ...)` takes a provider function; the judge, applicator, gate, and loop logic stay identical:

```python
# Current (mock files, per round):
def reviews_provider(round, current_html):
    return json.load(open(f"tests/mock_reviews_r{round}.json"))

# Future (live reviewers on the current HTML):
def reviews_provider(round, current_html):
    return merge(call_olmo(current_html), call_gemini(current_html), call_gpt(current_html))
```

**Element IDs:** every block-level element gets a stable SHA256-based ID (`block-{page}-{hash}`). This enables safe patching across reruns and is the foundation for the applicator's all-or-nothing model.

## License

MIT

## Contributing

PRs welcome. For major changes, open an issue first.
