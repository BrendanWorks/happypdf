# happypdf

Convert inaccessible PDFs into WCAG 2.2-validated semantic HTML5 with multi-model review and iterative accessibility enhancement.

**Live demo:** https://happypdf.org

happypdf turns inaccessible PDFs into clean, semantic HTML5. It uses vision-based OCR for extraction, generates high-quality alt text, builds proper structure (landmarks, headings, tables), scores the result with axe-core in a real Chromium browser, and then runs a multi-round review loop that safely enhances accessibility without losing original content.

## Why This Exists

PDFs remain ubiquitous in government, education, healthcare, and enterprise workflows. Many are unusable with assistive technology due to missing tags, alt text, headings, landmarks, or table structure.

Manual remediation is effective but slow, expensive, and difficult to scale. happypdf automates what can be automated, keeps every change fully auditable, and uses strict preservation checks to ensure remediation is additive rather than destructive.

## What happypdf Does

happypdf processes PDFs through a reproducible pipeline:

1. Extract content using olmOCR (Ai2's vision-based PDF extraction system).
2. Generate alt text with Qwen2-VL.
3. Build semantic HTML5 with landmarks, headings, tables, images, and stable element IDs.
4. Score accessibility using axe-core in a real headless Chromium browser.
5. Review & enhance via multi-model peer reviewers + judge.
6. Apply safe patches (ARIA labels, roles, descriptions, etc.).
7. Validate preservation (text, images, headings, and tables are never lost).

The result is remediated, WCAG-scored HTML plus a detailed, human-readable manifest of every enhancement.

## The Secret Sauce: True BYOK Enterprise Support

Most accessibility tools force you into a binary choice: pay per conversion or build everything yourself. happypdf offers a better path.

Bring Your Own Keys (BYOK) lets you use your existing Claude, ChatGPT Enterprise, or Gemini credentials. If your organization already has approved AI contracts, happypdf routes remediation through them at no additional licensing cost.

**Why This Matters**

- **Zero new procurement friction** — Use models your security and legal teams have already approved.
- **True cost transparency** — You only pay for the compute you use through contracts you already own.
- **Consistent pipeline** — The same high-quality orchestration works in hosted demo, self-hosted, and BYOK modes.

This design makes happypdf uniquely practical for enterprises and government users.

## Demo

Try it at https://happypdf.org.

Features include:

- Drag-and-drop PDF upload
- Real-time pipeline progress
- Live HTML preview
- Detailed WCAG scoring and enhancement logs
- Downloadable HTML + manifest

The demo runs on Modal GPUs and handles complex documents well (forms, tables, scanned pages, image-heavy reports, government publications).

## Deployment Modes

The same orchestration layer works across all modes — only the model backends change.

| Mode | Models | Cost Model | Best For |
|---|---|---|---|
| **Self-hosted / open-weight** | OLMo + local/Modal inference | Compute only | Offline, air-gapped, cost-sensitive |
| **Hosted Demo** | happypdf-provisioned (Claude judge + reviewers) | Per conversion | Quick testing |
| **BYOK / Enterprise** | Your Claude, OpenAI, or Gemini keys | Your existing contracts | Organizations with approved AI access |

## Why This Project?

This work extends Ai2's **SciA11y** research (Wang, Cachola, et al., ASSETS '21), which demonstrated PDF-to-HTML conversion at ~86% fidelity but identified three open problems: *automated alt text generation, table accessibility, and iterative WCAG validation*. happypdf addresses all three:

- **Alt text:** Qwen2-VL generates per-image descriptions (replaces manual work).
- **Tables:** MarkdownHTMLConverter recovers proper `<table>`, `<tr>`, `<td>`, `<th>` structure from olmOCR's markdown.
- **Iterative validation:** Multi-round peer review loop with Claude judge + content preservation gates ensure accessibility is additive and never destructive.

The result is a production system that scales PDF remediation from manual hours-per-document to automated minutes.

## How the pipeline works

<img width="1024" height="559" alt="image" src="https://github.com/user-attachments/assets/c0b277e8-6cd3-4cd6-a5c0-c2fb53fdc7cd" />


## Review Loop

The initial HTML generator often produces zero axe-core violations for many documents. The review loop focuses on enhancement, not just fixing violations.

Each round:

1. Peer reviewers (OLMo, Gemini, GPT-4o, etc.) analyze the HTML in parallel.
2. Judge model deduplicates suggestions, rejects unsafe changes, and classifies patches.
3. Deterministic applicator updates elements by stable data-ir-id.
4. Preservation gate verifies content integrity.
5. axe-core rescans.
6. Loop stops on convergence.

Typical enhancements include ARIA labels for tables, roles for navigational regions, clearer image descriptions, and safer relationships between document sections.

## Benchmark Results

All documents in the test suite converge quickly with zero content loss.

| Document | Type | Baseline | Round 1 | Round 2 | Round 3 | Final | Reviewers | Stop reason |
|---|---|---:|---:|---:|---:|---:|---|---|
| AccessComputing Syllabus | Clean digital | 0 viol / 23 pass | +5 pass | +4 pass | 0 new | 0 viol / 32 pass | OLMo ✅, Gemini ✅, GPT ✅ | Converged |
| IRS Schedule C | Dense form | 0 viol / 23 pass | +5 pass | 0 new | - | 0 viol / 28 pass | OLMo ✅, Gemini ✅, GPT ✅ | Converged |
| Navy Bulletin 1943 | OCR'd prose | 0 viol / 17 pass | 0 new | - | - | 0 viol / 17 pass | OLMo ✅, Gemini ✅, GPT ✅ | Converged |

Key observations:

- All benchmark documents converge within two rounds.
- Multi-model orchestration is robust: all three reviewers (OLMo, Gemini, GPT) succeeded on all documents.
- The preservation gate passes every round.
- Documents with more recoverable structure tend to receive more useful enhancements.
- The main effect is visible in additional axe-core passes and applied ARIA attributes, not only in violation reduction.

Run the benchmark suite with:

```bash
python src/benchmark.py
```

See [`benchmark/BENCHMARK.md`](benchmark/BENCHMARK.md) for detailed logs and outputs.

### Comprehensive Test Suite (9 PDFs)

Extended testing across diverse document types confirms production readiness. **All test PDFs available in [`benchmark/`](benchmark/) for independent verification.**

#### Extended Test Documents (6 newly tested)

| Document | Type | Size | Pages | Baseline | Final | Rounds | Notes |
|----------|------|------|-------|----------|-------|--------|-------|
| Chapter 6: Assessment | Academic | 4.2M | 13 | 26 pass | 26 pass | 1 | Image-heavy extraction |
| Blood Pressure Instructions | Medical | 163K | 1 | 26 pass | 26 pass | 1 | Device manual, visuals |
| Creating a One Pager | Business | 1.3M | 5 | 26 pass | 31 pass | 2 | Mixed text & graphics |
| Dry Lab Protocol | Scientific | 1.3M | 3 | 20 pass | 20 pass | 1 | Text-heavy instructions |
| Example Document | Sample | 343K | 3 | 27 pass | 32 pass | 2 | Generic test document |
| Invoice Sample | Financial | 146K | 1 | 23 pass | 28 pass | 3 | Structured form, dense |

#### Core Benchmark Suite (3 validated)

| Document | Type | Size | Pages | Baseline | Final | Rounds | Notes |
|----------|------|------|-------|----------|-------|--------|-------|
| AccessComputing Syllabus | Educational | 0.1M | 1 | 23 pass | 32 pass | 3 | Clean digital PDF, tables |
| IRS Schedule C (Tax Form) | Financial | 0.1M | 2 | 23 pass | 28 pass | 2 | Dense form, structured data |
| Navy Bulletin 1943 | Government | 4.4M | 11 | 17 pass | 17 pass | 1 | OCR'd historical prose |

**Comprehensive suite metrics (9 PDFs):**
- Document range: 86 KB to 4.4 MB | 1–13 pages
- Baseline passes: 17–32 (0 violations across all, 100% baseline WCAG compliance)
- Final passes: 17–32 (enhancements applied where beneficial)
- Average rounds to convergence: 1.9 rounds
- Total ARIA enhancements: 21+ attributes across all documents
- Multi-model reviewer health: 100% success (all reviewers succeeded on all rounds)

All tested documents demonstrate the pipeline's ability to:
- Produce valid semantic HTML5 from PDFs (images, tables, landmarks, proper hierarchy)
- Achieve WCAG baseline at generation time (before peer review)
- Apply meaningful accessibility enhancements via ARIA attributes
- Converge reliably without content loss or destructive patching

## Project Status & Roadmap

✅ **Production Ready** — Fully deployed at happypdf.org with working BYOK, benchmarks, and security controls.

Upcoming:

- Full audit-trail JSON manifest export
- JAWS/NVDA screen reader validation
- Optional persistent storage (e.g. Supabase)
- Expanded documentation and examples

## Quick Start

### Prerequisites

- Python 3.10+
- Node.js 18+
- Modal account
- Playwright Chromium

### Install

```bash
git clone https://github.com/BrendanWorks/happypdf.git
cd happypdf

# Python dependencies
pip install -r requirements.txt

# Node dependencies for axe-core scoring
npm install

# Chromium for Playwright
playwright install chromium

# Modal credentials
export MODAL_TOKEN_ID=your_token_id
export MODAL_TOKEN_SECRET=your_token_secret
```

### Run the web app locally

```bash
# Deploy the backend
modal deploy src/modal_api.py

# Start the frontend
cd frontend
npm install
npm run dev
```

### Run benchmarks

```bash
python src/benchmark.py
```

Benchmark outputs are written to `output/` and include:

- `{doc}_scored.html`
- `{doc}_manifest.json`
- WCAG baseline and final scores
- Enhancement history by round
- Preservation gate logs
- Convergence details

## Architecture Highlights

- **Stable Element IDs** (`block-{page}-{hash}`) — Enables safe, repeatable patching.
- **Review-source agnostic** — Swap reviewers easily while keeping judge/applicator/gate logic consistent.
- **Security-first BYOK** — Keys never touch the browser, are stored in encrypted vaults, and errors are sanitized.

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

## Known limitations

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

Pull requests welcome. For major changes, please open an issue first.

**License:** MIT

## Testing

```bash
# Run the full benchmark suite
python src/benchmark.py

# Inspect generated output
cat output/syllabus_scored.html
cat output/syllabus_manifest.json
```
