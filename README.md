# happypdf

Convert inaccessible PDFs into **WCAG 2.2-validated** semantic HTML5 with multi-model review and iterative accessibility enhancement.

**Live Demo:** [https://happypdf.org](https://happypdf.org)

happypdf turns inaccessible PDFs into clean, semantic HTML5. It uses vision-based OCR for extraction, generates high-quality alt text, builds proper structure (landmarks, headings, tables), scores the result with axe-core in a real Chromium browser, and runs a multi-round review loop that safely enhances accessibility **without losing original content**.

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
- [Security](#security)
- [Known Limitations](#known-limitations)
- [Related Work](#related-work)
- [Contributing & License](#contributing--license)

## Why This Exists

PDFs remain ubiquitous in government, education, healthcare, and enterprise workflows. Many are unusable with assistive technology due to missing tags, alt text, headings, landmarks, or table structure.

Manual remediation is effective but slow, expensive, and difficult to scale. happypdf automates what can be automated, keeps every change fully auditable, and uses strict preservation checks so remediation is always additive.

## What happypdf Does

happypdf processes PDFs through a reproducible pipeline:

1. **Extract content** using olmOCR (Ai2's vision-based PDF extraction system, powered by Qwen2-VL).
2. **Generate context-aware alt text** by re-prompting Qwen2-VL on each extracted image, preserving page layout context.
3. **Build semantic HTML5** with landmarks, headings, tables, images, and stable element IDs.
4. **Score accessibility** using axe-core in a real headless Chromium browser.
5. **Review & enhance** via multi-model peer reviewers + judge model.
6. **Apply safe patches** (ARIA labels, roles, descriptions, etc.).
7. **Validate preservation** — text, images, headings, and tables are never lost.

The result is remediated, WCAG-scored HTML plus a detailed, human-readable manifest of every enhancement.

## The Secret Sauce: True BYOK Enterprise Support

Most accessibility tools force a binary choice: pay per conversion or build it yourself. happypdf offers a better path.

**Bring Your Own Keys (BYOK)** lets you use your existing Claude, ChatGPT Enterprise, or Gemini credentials. If your organization already has approved AI contracts, happypdf routes remediation through them at **no additional licensing cost**.

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

The same orchestration layer works across all modes — only the model backends change.

| Mode | Models | Cost Model | Best For |
| :--- | :--- | :--- | :--- |
| **Self-hosted / open-weight** | OLMo + local/Modal inference | Compute only | Offline, air-gapped, cost-sensitive |
| **Hosted Demo** | happypdf-provisioned (Claude judge + reviewers) | Per conversion | Quick testing |
| **BYOK / Enterprise** | Your Claude, OpenAI, or Gemini keys | Your existing contracts | Organizations with approved AI access |

## Why This Project?

This work extends Ai2's **SciA11y** research (Wang, Cachola, et al., ASSETS '21), which achieved ~86% fidelity but highlighted three key gaps: automated alt text, table accessibility, and iterative WCAG validation. happypdf addresses all three:

- **Alt text** — Qwen2-VL generates context-aware descriptions.
- **Tables** — Robust recovery of proper `<table>`, `<th>`, etc. structure.
- **Iterative validation** — Multi-round peer review + preservation gates ensure enhancements are safe and additive.

## How the Pipeline Works

<img width="784" height="1168" alt="image" src="https://github.com/user-attachments/assets/52bec40c-efab-4191-9bc3-1264b908f537" />



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

All documents converge quickly with zero content loss.

**Core Benchmarks**

| Document              | Type            | Baseline       | Round 1     | Round 2   | Final          | Reviewers              | Stop reason |
|-----------------------|-----------------|----------------|-------------|-----------|----------------|------------------------|-------------|
| AccessComputing Syllabus | Clean digital | 0 viol / 23 pass | +5 pass   | +4 pass  | 0 viol / 32 pass | OLMo ✅, Gemini ✅, GPT ✅ | Converged |
| IRS Schedule C        | Dense form     | 0 viol / 23 pass | +5 pass   | 0 new    | 0 viol / 28 pass | OLMo ✅, Gemini ✅, GPT ✅ | Converged |
| Navy Bulletin 1943    | OCR'd prose    | 0 viol / 17 pass | 0 new     | -        | 0 viol / 17 pass | OLMo ✅, Gemini ✅, GPT ✅ | Converged |

**Extended Test Suite (7 Additional Documents)**

| Document | Type | Size | Pages | Baseline | Final | Rounds | Notes |
|----------|------|------|-------|----------|-------|--------|-------|
| Chapter 6: Assessment | Academic | 4.2M | 13 | 26 pass | 26 pass | 1 | Image-heavy extraction |
| Blood Pressure Instructions | Medical | 163K | 1 | 26 pass | 26 pass | 1 | Device manual, visuals |
| Creating a One Pager | Business | 1.3M | 5 | 26 pass | 31 pass | 2 | Mixed text & graphics |
| Dry Lab Protocol | Scientific | 1.3M | 3 | 20 pass | 20 pass | 1 | Text-heavy instructions |
| Example Document | Sample | 343K | 3 | 27 pass | 32 pass | 2 | Generic test document |
| Invoice Sample | Financial | 146K | 1 | 23 pass | 28 pass | 3 | Structured form, dense |
| Somatosensory | Scientific | 132K | 2 | 24 pass | 24 pass | 0 | Neural system reference |

**Comprehensive Test Suite (10 PDFs)** — Full details and raw files in [`benchmark/`](benchmark/).

**Key Metrics (10 PDFs):**
- Average rounds to convergence: **1.6**
- Baseline violations: **0-1 across all documents**
- Reviewer success rate: **100%** on tested review rounds
- Total ARIA enhancements: 21+ across the suite
- Total test coverage: **86 KB to 4.4 MB** | **1–13 pages**

## Project Status & Roadmap

**✅ Production Ready** — Fully deployed with working BYOK, benchmarks, and security controls.

**Upcoming:**
- Full audit-trail JSON manifest export
- JAWS / NVDA screen reader validation
- Optional persistent storage (e.g. Supabase)
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

# Set up Modal credentials
export MODAL_TOKEN_ID=your_token_id
export MODAL_TOKEN_SECRET=your_token_secret
```

### Run Locally

```bash
modal deploy src/modal_api.py

cd frontend
npm install
npm run dev
```

Run benchmarks: `python src/benchmark.py`

## Architecture Highlights

- **Stable Element IDs** (`block-{page}-{hash}`) for safe, repeatable patching.
- **Review-source agnostic** design — easily swap reviewers.
- **Security-first BYOK** — Keys never touch the browser.

## Security

### BYOK API key handling
happypdf is designed so enterprise API keys do not pass through the browser or get written to application logs.
- Keys are stored in Modal's encrypted secret vault.
- Keys are injected into backend containers as environment variables.
- The frontend never receives provider credentials.
- Error messages are sanitized to avoid leaking API responses or credentials.
- Job state is stored in memory, not in a database.

### Transport security
- Production endpoints use HTTPS.
- CORS is restricted to approved `https://` origins.
- The frontend connects directly to the Modal ASGI app.

### Data persistence
- PDF content, intermediate HTML, and remediation results live in in-memory job state.
- No database, Redis, or persistent storage is required for jobs.
- Temporary files are created with Python's `tempfile` module and deleted after processing.
- Modal containers scale down after idle periods, clearing in-memory state.

### Self-hosting checklist
For self-hosted deployments:
1. Store `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, and `GOOGLE_API_KEY` in Modal Secrets or your own secret manager.
2. Enforce HTTPS at the ingress layer.
3. Restrict CORS origins to your production frontend domains.
4. Choose a container scale-down window that matches your security and latency needs.
5. Avoid persistent job storage unless your organization explicitly requires it.

## Known Limitations
- **axe-core is not full WCAG conformance.** Automated tools can only test part of WCAG. happypdf reports axe-core results and routes uncertain cases to human review.
- **Baseline output is often already valid.** Because the HTML generator creates semantic structure up front, the review loop often improves passes and structure rather than reducing violations.
- **Heading detection is heuristic.** Some section labels from OCR are promoted to headings, but complex document structures may still need manual review.
- **Duplicate IDs can occur on repeated visual artifacts.** Repeated separator lines or similar artifacts can produce identical hashes. The applicator fails safe when patches are ambiguous.
- **OCR quality affects output quality.** Scanned pages, low-resolution images, and complex vector graphics can reduce extraction quality.
- **Reviewer output can fail.** If a reviewer emits malformed JSON or times out, that reviewer is skipped for the round and the loop continues with available reviews.

## Related Work
- **SciA11y**: Ai2 research on converting scientific paper PDFs to accessible HTML. happypdf extends this research to general documents with iterative validation. [Paper](https://doi.org/10.1145/3441852.3471212)
- **olmOCR**: Primary extraction engine. [Paper](https://arxiv.org/abs/2502.18443)

## Contributing & License

Pull requests are welcome. For major changes, please open an issue first.

**License:** MIT
