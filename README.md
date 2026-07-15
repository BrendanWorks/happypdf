# happypdf

Convert inaccessible PDFs into **WCAG 2.2-validated** semantic HTML5 with multi-model review and iterative accessibility enhancement.

**Live Demo:** [https://happypdf.org](https://happypdf.org)

happypdf turns inaccessible PDFs into clean, semantic HTML5. It uses vision-based OCR for extraction, generates high-quality alt text, builds proper structure (landmarks, headings, tables), scores the result with axe-core in a real Chromium browser, and runs a multi-round review loop that safely enhances accessibility **without losing original content**.

## Demo

![happypdf demo animation](./videos/happypdf-demo.gif)

Watch happypdf transform an inaccessible PDF into WCAG 2.2 AA–validated HTML with full remediation audit trail. 

**[► Full video](https://github.com/BrendanWorks/happypdf/releases/download/v1.0/Sizzle_Video.mov)** — Available in [MP4](https://github.com/BrendanWorks/happypdf/releases/download/v1.0/happypdf-demo.mp4) (689 KB) or [MOV](https://github.com/BrendanWorks/happypdf/releases/download/v1.0/Sizzle_Video.mov) (2.8 MB)

## Table of Contents
- [Why This Exists](#why-this-exists)
- [What happypdf Does](#what-happypdf-does)
- [The Secret Sauce: True BYOK Enterprise Support](#the-secret-sauce-true-byok-enterprise-support)
- [Demo](#demo)
- [Deployment Modes](#deployment-modes)
- [Why This Project?](#why-this-project)
- [How the Pipeline Works](#how-the-pipeline-works)
- [The Enhancement & Optimization Loop](#the-enhancement--optimization-loop)
- [Benchmark Results](#benchmark-results)
- [Project Status & Roadmap](#project-status--roadmap)
- [Quick Start](#quick-start)
- [Architecture Highlights](#architecture-highlights)
- [Design Decisions](#design-decisions)
- [Security](#security)
- [Known Limitations](#known-limitations)
- [Related Work](#related-work)
- [Contributing & License](#contributing--license)

## Why This Exists

PDFs remain ubiquitous in government, education, healthcare, and enterprise workflows. Many are unusable with assistive technology due to missing tags, alt text, headings, landmarks, or table structure.

Manual remediation is effective but slow, expensive, and difficult to scale. happypdf automates what can be automated, keeps every change fully auditable, and uses strict preservation checks so remediation is always additive.

## What happypdf Does

happypdf processes PDFs through a reproducible pipeline:

1. **Extract content** using olmOCR-2 (Ai2's vision-based PDF extraction system, Qwen2.5-VL backbone).
2. **Generate context-aware alt text** with a separate Qwen2-VL model on each extracted image, prompted with surrounding page text (runs in parallel with extraction).
3. **Build semantic HTML5** with landmarks, headings, tables, images, and stable element IDs.
4. **Score accessibility** using axe-core in a real headless Chromium browser.
5. **Review & enhance** via multi-model peer reviewers + judge model.
6. **Apply safe patches** (ARIA labels, roles, descriptions, etc.).
7. **Validate preservation** — text, images, headings, and tables are never lost.

The result is remediated, WCAG-scored HTML plus a detailed, human-readable manifest of every enhancement.

## The Secret Sauce: True BYOK Enterprise Support

Most accessibility tools force a binary choice: pay per conversion or build it yourself. happypdf offers a better path.

**Bring Your Own Keys (BYOK)** lets you use your existing Claude (Anthropic) or ChatGPT (OpenAI) enterprise credentials. If your organization already has approved AI contracts, happypdf routes remediation through them at **no additional licensing cost**.

### Why This Matters
- **Zero new procurement friction** — Use models your security and legal teams have already approved.
- **True cost transparency** — Pay only for the compute you actually use.
- **Consistent pipeline** — The same high-quality orchestration works across hosted demo, self-hosted, and BYOK modes.

This makes happypdf uniquely practical for enterprises and government organizations.

## Demo

Try it at **[https://happypdf.org](https://happypdf.org)**.

**Features:**
- Drag-and-drop PDF upload
- Real-time pipeline progress
- Live HTML preview
- Detailed WCAG scoring and enhancement logs
- Downloadable HTML + manifest

The demo runs on Modal GPUs and excels with complex documents: forms, tables, scanned pages, image-heavy reports, and government publications.

## Deployment Modes

There is a configurable reviewer pipeline controlled by the `REVIEWER_PROFILE` environment variable. The extraction, HTML generation, and scoring stages are always the same.

| Mode | Profile Var | Reviewers | Credentials | Cost Model | Best For |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Hosted (default)** | `default` (or unset) | OLMo + Gemini + GPT (parallel consensus) | happypdf-provisioned keys | Per conversion | Quick testing, highest quality, default experience |
| **BYOK / Enterprise** | `default` | OLMo + Gemini + GPT (same pipeline) | Your own Claude / OpenAI keys | Your existing contracts | Organizations with approved AI access |
| **OLMo-Only (single-model review)** | `olmo-only` | OLMo only (Modal) | Modal auth (+ judge keys optional) | Your Modal account | Restricted sectors, minimal external API surface, local self-hosting |

### OLMo-Only Mode

Set `REVIEWER_PROFILE=olmo-only` to run single-model review with only OLMo (no Gemini/GPT reviewers). This is useful for:
- **Government & Defense** — Minimal external API surface, full control over review compute.
- **Restricted Networks** — Reviews stay on your Modal deployment.
- **Cost-Conscious Workflows** — Single model vs. three-model consensus.

**Scope note:** this profile removes the *peer reviewers'* external calls only. Extraction and alt text are still remote Modal GPU calls in every mode, and the judge's LLM-safe fixes (alt-text rewrites) still call Claude/OpenAI when those keys are configured — with no judge keys, those fixes are routed to human review instead. It is not an air-gapped mode.

**Trade-off:** Single-model review catches fewer failure modes than multi-model consensus, so quality may drop slightly (5-10% fewer WCAG suggestions). But review inference stays within your own Modal account.

**Usage:**
```bash
# Docker
REVIEWER_PROFILE=olmo-only docker compose up --build

# Local
export REVIEWER_PROFILE=olmo-only
python src/benchmark.py --live
```

## Why This Project?

This work extends Ai2's **SciA11y** research (Wang, Cachola, et al., ASSETS '21), which achieved ~86% fidelity but highlighted three key gaps: automated alt text, table accessibility, and iterative WCAG validation. happypdf addresses all three:

- **Alt text** — Qwen2-VL generates context-aware descriptions.
- **Tables** — Robust recovery of proper `<table>`, `<th>`, etc. structure.
- **Iterative validation** — Multi-round peer review + preservation gates ensure enhancements are safe and additive.

## How the Pipeline Works

![happypdf pipeline animation](./videos/pipeline-demo.gif)

## Extraction Model: olmOCR-2

Step 1 of the pipeline — turning the PDF into markdown — runs [olmOCR](https://github.com/allenai/olmocr) on a Modal H100. **Production runs olmOCR-2-7B-1025-FP8** (promoted in v1.2 after a staged v1-vs-v2 comparison); the original v1 app stays deployed as a one-line-revert fallback.

| | Modal app | Deploy file | Model |
|---|---|---|---|
| **Production** | `olmocr-v2` | `modal/modal_olmocr_v2.py` | explicit `olmOCR-2-7B-1025-FP8`, weights baked into the image |
| **Fallback** | `olmocr` | `modal/modal_olmocr_final.py` | olmocr CLI default (v1, `olmOCR-7B-0725-FP8`) |

The production deployment pins `olmocr>=0.4.0`, passes an explicit `--model` (so extraction can't drift with the package default), bakes the ~16 GB weights into the image at build time (no runtime HuggingFace dependency), runs one extraction per container (`single_use_containers=True` — a reused warm container can hang the vLLM boot), and streams the CLI's output to Modal logs so a stuck extraction is diagnosable.

```bash
# Deploy / update production extraction
modal deploy modal/modal_olmocr_v2.py

# Smoke-test one PDF
modal run modal/modal_olmocr_v2.py --pdf-file benchmark/irs_schedule_c.pdf
```

**Revert.** The pipeline resolves extraction by app name (`OLMOCR_APP` in [`src/build_syllabus_slice.py`](src/build_syllabus_slice.py)); set it back to `"olmocr"` and redeploy the API to fall back to v1.

## The Enhancement & Optimization Loop

The initial HTML generator frequently produces **zero axe-core violations**. But automated tools can only detect what is *wrong*, not what is *right*. The review loop goes deeper: it verifies semantic correctness, optimizes structure, and ensures that generated descriptions (e.g., alt text) truly match the visual and contextual intent of each page.

**Each round:**
1. Peer reviewers (OLMo, Gemini, GPT-4o, etc.) analyze the HTML in parallel for improvement opportunities.
2. Judge model deduplicates suggestions, rejects unsafe changes, and classifies patches.
3. Deterministic applicator updates elements by stable `data-ir-id`.
4. Preservation gate verifies content integrity and no text/image loss.
5. axe-core rescans for any regressions.
6. Loop stops on convergence.

Typical enhancements include ARIA labels for tables, navigational roles, improved image descriptions, and better section relationships.

```

```

## Benchmark Results

All documents converge quickly with zero content loss. Manifest and report downloads verified for all PDFs.

**Core Benchmarks (3 Demos)**

| Document              | Type            | Size  | Pages | Baseline | Final  | Rounds |
|-----------------------|-----------------|-------|-------|----------|--------|--------|
| AccessComputing Syllabus | Clean digital | 1.2M | 8 | 100% (26 pass) | 100% (31 pass) | 2 |
| IRS Schedule C        | Dense form     | 1.1M | 7 | 100% (23 pass) | 100% (28 pass) | 3 |
| Navy Bulletin 1943    | OCR'd prose    | 876K | 6 | 100% (20 pass) | 100% (20 pass) | 1 |

**Extended Test Suite (10 Additional Documents)**

| Document | Type | Size | Pages | Baseline | Final | Rounds | Notes |
|----------|------|------|-------|----------|-------|--------|-------|
| Chapter 6: Assessment | Academic | 4.2M | 13 | 100% (26 pass) | 100% (26 pass) | 1 | Image-heavy extraction |
| Blood Pressure Instructions | Medical | 163K | 1 | 100% (26 pass) | 100% (26 pass) | 1 | Device manual, visuals |
| Creating a One Pager | Business | 1.3M | 5 | 100% (26 pass) | 100% (31 pass) | 2 | Mixed text & graphics |
| Dry Lab Protocol | Scientific | 1.3M | 3 | 100% (20 pass) | 100% (20 pass) | 1 | Text-heavy instructions |
| Example Document | Sample | 343K | 3 | 100% (27 pass) | 100% (32 pass) | 2 | Generic test document |
| Invoice Sample | Financial | 146K | 1 | 100% (23 pass) | 100% (28 pass) | 3 | Structured form, dense |
| Somatosensory | Scientific | 132K | 4 | 96.0% (24 pass) | 96.7% (29 pass) | 2 | Neural system reference; 1 baseline violation not resolved by round 2 |
| Cosmic Story Mat | Instructional | 447K | 6 | 100% (22 pass) | 100% (22 pass) | 1 | Children's literature, 25 embedded images; OLMo reviewer timed out then succeeded on retry |
| Furnace (Amana) | Technical | 11.9M | 16 | 96.3% (26 pass) | 96.8% (30 pass) | 2 | Appliance manual; loop stopped after round 2 when round 3 would have regressed the axe score |
| Hands-Only CPR Sheet | Medical | 219K | 1 | 100% (22 pass) | 100% (22 pass) | 1 | Emergency procedure; OLMo reviewer failed outright, loop continued with Gemini + GPT |

**Comprehensive Test Suite (13 PDFs Total)** — Full details and raw files in [`benchmark/`](benchmark/). All 13 rows above are backed by real generated output committed to the repo — no estimated or placeholder numbers. Document provenance and licensing notes are in [`benchmark/README.md`](benchmark/README.md) — the hosted demo offers original-PDF downloads only for the two public-domain documents.

**Key Metrics:**
- **Total PDFs tested:** 13
- **Average baseline score:** 99.4%
- **Average final score:** 99.5%
- **Average rounds to convergence:** 1.7
- **Baseline violations:** 0 violations in 11/13 documents (Somatosensory and Furnace each had 1, neither resolved by an available deterministic fix)
- **Reviewer resilience:** across 13 live runs, one reviewer failed outright once and timed-out-then-recovered once; in both cases the loop correctly continued with the remaining reviewers rather than blocking
- **Total ARIA enhancements:** 34 across the suite
- **Total test coverage:** 132 KB to 11.9 MB | 1–16 pages

## Project Status & Roadmap

**✅ Production Ready** — Fully deployed with working BYOK, benchmarks, manifest/report downloads, and security controls.

**Recently Completed (July 2026):**
- ✅ Full audit-trail JSON manifest export (with demo snapshot support)
- ✅ Formatted HTML report generation with styling
- ✅ Download package feature (JSON + HTML with proper headers)
- ✅ Comprehensive benchmark testing (13 PDFs with manifest/report verification)
- ✅ BYOK override/restore verified end-to-end with a real live job (see [Security](#security))
- ✅ Fresh-machine self-hosting test in an isolated VM, caught and fixed a missing Quick Start step
- ✅ Research-informed documentation: trade-offs in design decisions, preservation proof mathematical contract
- ✅ OLMo-only reviewer profile (`REVIEWER_PROFILE=olmo-only`) for air-gapped / government / restricted-network deployments

**Upcoming Features:**
- Visual-artifact filtering for the element ID builder (repeated separator lines etc. can hash-collide into duplicate IDs — currently detected and logged, not filtered upstream) and a second-pass classifier to reduce heading-promotion false positives; see `docs/ARCHITECTURE.md`
- Download full package ZIP (HTML output + JSON manifest + Report + Original PDF)
- CLI instance for batch processing and local runs
- Upgrade job storage from Modal Dict (current, 24h TTL) to Supabase for long-term history and batch dashboards
- JAWS / NVDA screen reader validation
- Batch processing dashboard
- Expanded documentation and examples

## Quick Start

### Prerequisites
- Python 3.10+
- Node.js 18+
- Modal account
- Playwright Chromium

### Installation
```bash
git clone https://github.com/BrendanWorks/happypdf.git
cd happypdf

# Install backend dependencies
pip install -r requirements.txt

# Install frontend dependencies
cd frontend && npm install && cd ..

# Install Chromium for Playwright
python -m playwright install chromium

# Install axe-core (path_resolver.py looks for it at the repo root)
npm install --legacy-peer-deps

# Set up Modal credentials
export MODAL_TOKEN_ID=your_token_id
export MODAL_TOKEN_SECRET=your_token_secret

# Create the OLMo reviewer auth secret (required — the API deploy references it)
modal secret create olmo-reviewer-auth OLMO_REVIEWER_TOKEN=$(openssl rand -hex 32)
```

**OLMo reviewer for self-hosts:** the code's default `OLMO_REVIEWER_URL` points at the
hosted demo's endpoint, which requires *its* bearer token — your deployment will skip the
OLMo reviewer (and continue with Gemini/GPT) unless you deploy your own and point at it:

```bash
modal deploy modal/modal_olmo_wcag.py   # deploys app "olmo-wcag-reviewer" under your account
export OLMO_REVIEWER_URL=https://<your-workspace>--olmo-wcag-reviewer-api.modal.run
```

### Run Locally

```bash
modal deploy src/modal_api.py

cd frontend
npm install
npm run dev
```

Run benchmarks: `python src/benchmark.py`

### Run Locally with Docker

```bash
cp .env.example .env   # fill in your Modal + provider credentials
docker compose up --build
```

This containerizes the orchestrator (`api/` + `src/`, with Playwright and axe-core baked in) and the built frontend — `make docker-up` does the same thing. It does **not** make the pipeline air-gapped: olmOCR extraction and Qwen2-VL alt-text generation are remote calls to Modal GPU functions, and the reviewer/judge step calls Anthropic/OpenAI/Google over the network in every deployment mode. You still need a Modal account and reviewer API keys either way — this just containerizes the orchestration layer for reproducible self-hosting, not the GPU inference itself.

## Architecture Highlights

- **Stable Element IDs** (`block-{page}-{hash}`) for safe, repeatable patching.
- **Review-source agnostic** design — easily swap reviewers.
- **Security-first BYOK** — Your key is sent once per job to call the provider on your behalf, then never persisted or reused. See [Security](#security) for the verified details.

## Design Decisions

**Why multi-model review instead of a single LLM patching the HTML directly?**
A single model call can hallucinate ARIA roles or miss edge cases. Three reviewers (OLMo, Gemini, GPT) run in parallel and vote, which catches different failure modes than any one model alone. The judge then deduplicates their findings and filters out unsafe patches before anything gets applied. This is slower than one-shot prompting, but it is more resilient to the class of errors that actually break accessibility rather than just looking wrong.

**Why deterministic patching with stable element IDs?**
If the same reviewer finding could produce different HTML on different runs, changes could not be audited or reproduced. Element content is hashed into stable IDs (`block-{page}-{hash}`), so a patch manifest can say "replace the contents of this exact element" and mean the same thing every time. That is what makes the audit trail meaningful instead of just decorative.

**Why BYOK over a pure SaaS model?**
Procurement friction is real for government and enterprise buyers. If an organization already has an approved contract with Anthropic or OpenAI, routing remediation through their own credentials removes a blocker that a per-conversion SaaS model would create. It is also why the BYOK code path was verified end-to-end with a real key rather than left as an untested feature.

## Security

### BYOK API key handling

**Default (hosted) credentials** — happypdf's own keys, used unless you supply your own:
- Stored in Modal's encrypted secret vault.
- Injected into backend containers as environment variables.
- The frontend never receives these credentials.

**BYOK (user-supplied) credentials** — when you paste your own key into the settings panel:
- The key is entered in your browser and sent once, over HTTPS, to power that single job's provider calls.
- It is passed **explicitly down the call chain** (provider factory → judge → API client constructor) for that job only — it is never written to the process environment, so concurrent jobs with different credentials can never observe each other's keys, and there is no restore step that could race. It is never persisted, logged, or reused across requests.
- Error messages are sanitized to avoid leaking API responses or credentials.
- Job state is stored in a Modal Dict keyed by job id; BYOK keys are **not** part of job state — they live only in the worker thread's call stack for the duration of the job.

**History:** v1.2 verified the earlier environment-swap mechanism end-to-end with a real key. v1.2.1 replaced that mechanism entirely with explicit key plumbing after review flagged that environment mutation could leak keys between concurrent jobs.

### Transport security
- Production endpoints use HTTPS.
- CORS is restricted to approved `https://` origins.
- The frontend connects directly to the Modal ASGI app.

### Upload & output hardening
- Live uploads are capped at 25 MB (`HAPPYPDF_MAX_UPLOAD_MB`) and content-sniffed (`%PDF-` magic bytes) before any GPU time is spent; the daily rate limit is persisted in a Modal Dict so container recycles can't reset it.
- Generated HTML derives from PDF content and LLM output, so it is defense-in-depth sanitized: table fragments pass an allowlist sanitizer, markdown image conversion escapes attributes and rejects unsafe URL schemes, and the API serves job HTML with a `Content-Security-Policy: sandbox` header. Downloadable reports HTML-escape every manifest-derived field (including the uploaded filename).
- The OLMo reviewer GPU endpoint requires a shared bearer token (`olmo-reviewer-auth` Modal secret). Without it, the endpoint would be publicly callable GPU compute. Self-hosters: `modal secret create olmo-reviewer-auth OLMO_REVIEWER_TOKEN=$(openssl rand -hex 32)` before deploying `modal/modal_olmo_wcag.py`.

### Data persistence
- Job state (progress, scores, enhancement metadata) and generated HTML live in a [Modal Dict](https://modal.com/docs/guide/dicts-and-queues) so conversions survive container restarts; records are pruned after **24 hours**.
- Uploaded PDF bytes are held in memory only for the duration of the job and are never written to the job store.
- No external database or Redis is required.
- Temporary files are created with Python's `tempfile` module and deleted after processing.

### Analytics
The hosted site (happypdf.org) uses Google Analytics (GA4) to understand traffic and usage.
- Standard GA4 data is collected: page views, device/browser info, approximate location, and first-party cookies (`_ga`, `_ga_*`).
- Custom events track pipeline usage — upload started (file size only), conversion succeeded/failed (pass count only), and BYOK used (provider name only). **No filenames, document content, or API keys are ever sent to analytics.**
- Analytics loads unconditionally on page load; there is currently no cookie-consent banner. If you're serving EU visitors and need GDPR-compliant opt-in consent, gate the GA script in `frontend/index.html` behind a consent mechanism before relying on this for compliance.
- Self-hosted deployments can remove the GA script entirely — it's a static tag in `frontend/index.html`, not wired into the pipeline.

### Self-hosting checklist
For self-hosted deployments:
1. Store `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, and `GOOGLE_API_KEY` in Modal Secrets or your own secret manager.
2. Enforce HTTPS at the ingress layer.
3. Restrict CORS origins to your production frontend domains.
4. Choose a container scale-down window that matches your security and latency needs.
5. Avoid persistent job storage unless your organization explicitly requires it.

## Limitations & Trade-offs

### Automation Has Limits

**axe-core catches ~30-40% of WCAG success criteria.** Automated tools test *syntax*, not *semantics*. A link with non-descriptive text ("click here") passes axe-core; reading order problems, incorrectly-described images, and tables with ambiguous headers don't register as violations because they require human judgment. happypdf reports what automated tools can measure and flags uncertain cases for human review. This is honest about what automation can do, and it is why the preservation gate matters more than the axe-core score alone.

**The baseline is often already valid.** The HTML generator creates semantic structure up front (landmarks, headings, tables with proper `<th>` cells, images with alt text). Many PDFs have zero baseline violations because olmOCR + deterministic HTML generation already produces passing HTML. The review loop focuses on *semantic correctness and optimization* — does an image's alt text actually describe what it shows? Is table navigation fully correct? These improvements are harder to measure (axe-core may show the same score) but matter for real assistive technology use.

**Heading detection is heuristic.** olmOCR sometimes emits section labels (e.g., "Methodology") as plain paragraphs rather than markdown headings. The builder promotes short standalone labels to `<h2>` and synthesizes an `<h1>` from the first content line when none exists. This is a trade-off: we get stronger document structure in most cases, but edge cases (a label that looks like a heading but isn't) can mis-tag. Complex documents still benefit from a human pass to verify outline accuracy.

**Handling collisions in the element ID system.** Repeated visual artifacts (rows of dashes, separator lines) can produce identical content hashes and thus duplicate `data-ir-id` values. The ID generator detects collisions and records them in the output's comment block. When the applicator encounters a patch targeting an ambiguous ID, it fails safe rather than applying it to a wrong element. A future improvement is upstream filtering of visual artifacts.

### Performance & Completeness

**Multi-model review is slower than single-model patching.** Running three reviewers (OLMo, Gemini, GPT) in parallel takes longer than one model generating patches directly. We chose ensemble review anyway because each model catches different failure modes — OLMo reasons about structure, Gemini handles semantic descriptions, GPT suggests ARIA patterns — and the judge model deduplicates and filters out unsafe patches. Single-model approaches trade speed for resilience to model-specific blindspots.

**OCR quality sets a floor.** Scanned pages, low-resolution images, and complex vector graphics reduce extraction fidelity. olmOCR is excellent but not magic; if the source PDF has unreadable text, the output won't magically make it readable. This is a constraint of the input, not the tool.

**Review models occasionally fail.** If a reviewer times out or emits malformed JSON, that reviewer is skipped for the round and the loop continues with the remaining reviewers. This is a feature (the loop doesn't block on one model's failure) and a limitation (you lose that reviewer's insights for that round). On the Cosmic Story Mat benchmark, OLMo timed out on the first attempt but succeeded on the second; the loop correctly continued with Gemini + GPT and re-tried OLMo, eventually converging with all three.

### The Preservation Gate is Your Safety Net

While automation has limits, the preservation gate is strict and always compared against the **original** document (never the previous round, so tolerances cannot compound): visible-text word coverage must stay ≥ 95%, image and table counts must never decrease, and patches must not introduce new heading-level skips. Any failing check discards the round and stops the loop, so remediation can never quietly trade content for score.

See [`docs/PRESERVATION_PROOF.md`](docs/PRESERVATION_PROOF.md) for the mathematical contract.

## Related Work
- **SciA11y**: Ai2 research on converting scientific paper PDFs to accessible HTML. happypdf extends this research to general documents with iterative validation. [Paper](https://arxiv.org/abs/2105.00076v1)
- **olmOCR**: Primary extraction engine. [Paper](https://arxiv.org/abs/2502.18443)

## Contributing & License

Pull requests are welcome — see [`CONTRIBUTING.md`](CONTRIBUTING.md) for setup, branch, and code-style conventions. For major changes, please open an issue first.

Questions or bugs: [open a GitHub issue](https://github.com/BrendanWorks/happypdf/issues).

**License:** [MIT](LICENSE)
