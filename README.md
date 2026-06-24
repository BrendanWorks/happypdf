# happypdf

Convert inaccessible PDFs to WCAG-validated HTML using Ai2's open model stack.

## The Problem

PDFs are everywhere in government, education, and enterprise — and most of them are inaccessible. Screen readers fail on untagged content, images carry no alt text, and tables have no structural markup, so the data inside them is invisible to assistive technology. Manual remediation is slow, expensive, and does not scale to the volume of documents organizations actually publish.

happypdf automates the work using multi-agent iterative remediation: open vision models extract the content, a model generates alt text, and an accessibility engine scores the result so it can be fixed and re-scored until it passes.

## Three Deployment Modes

The orchestration is identical across all three modes — only the model backends are swapped. That pluggability is the whole point.

| Mode | Models | Cost | When to use |
|------|--------|------|-------------|
| **Self-hosted / Open-weight** | OLMo peer review + local inference on your own hardware or Modal account | Zero marginal cost, lower quality | Cost-sensitive, offline, or air-gapped environments |
| **Demo / Hosted** | happypdf provisions Claude as judge/fixer with OLMo as peer reviewers | Per-conversion (scales with document size and review rounds) | Best quality |
| **BYOK / Enterprise** | User brings their own Claude / ChatGPT enterprise credentials; same code as demo mode | Zero incremental cost to happypdf | Enterprises that already hold model contracts |

**BYOK is the differentiator.** No competitor has built it. The barrier to enterprise accessibility tooling is procurement friction, not technical capability — organizations already have model contracts but cannot easily route a third-party SaaS tool through them. BYOK sidesteps that entirely: the customer points happypdf at credentials they already own and pay for.

## How It Works

```
PDF Input
  |
  v
olmOCR (vision-based extraction, Ai2) -> Markdown
  |
  v
Image extraction + Qwen2-VL alt text generation
  |
  v
Semantic HTML5 (landmarks, heading hierarchy, data-ir-id attributes)
  |
  v
axe-core baseline WCAG scoring
  |
  v
[Rounds 1-3: Peer review + Claude judge + patch + rescore]   [TODO]
  |
  v
WCAG-validated HTML + review manifest
```

The vertical slice (steps 1-5) is complete and working. Iterative remediation (rounds 1-3) is in development.

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

### Run the Vertical Slice

```bash
python src/build_syllabus_slice.py
```

Outputs:

- `output/syllabus_scored.html` — semantic HTML with audit block at top
- `output/syllabus_axe_baseline.json` — raw axe-core WCAG results

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

## Known Limitations

- **Vertical slice only:** Rounds 2-3 (iterative remediation) not yet implemented.
- **Duplicate element IDs:** Visual artifacts (e.g., rows of dashes in PDFs) are treated as content. They get IDs. If there are many, you'll see duplicates. This is documented and non-blocking for the vertical slice.
- **Heading hierarchy:** olmOCR returns section labels as paragraphs, not headings. Short standalone lines are heuristically promoted to `<h2>`. This works well in practice but isn't perfect.
- **axe-core coverage:** axe-core detects ~30–40% of WCAG requirements. The other 60% require human review or custom logic.

## Related Work

**SciA11y** (Wang, Cachola, et al., ASSETS '21) — Ai2 team converted scientific paper PDFs to accessible HTML. Evaluated ~86% success rate on readability; flagged alt-text and table accessibility as open problems. happypdf extends this work to general and government PDFs and adds iterative multi-model WCAG validation. [Paper](https://doi.org/10.1145/3441852.3471212)

**olmOCR** (Poznanski et al., Ai2, arXiv:2502.18443) — Ai2's vision-based PDF extraction system built on Qwen2.5-VL. happypdf uses olmOCR as the primary extraction engine and adds the remediation and validation pipeline. [Paper](https://arxiv.org/abs/2502.18443)

## Development

### Next Steps (Priority Order)

1. Implement Claude judge + patch manifest (enables rounds 2-3)
2. Wire multi-round loop with early stopping
3. Content preservation gate (text coverage, image count, reading order)
4. Next.js frontend (drag-and-drop, visual review)
5. Pre-cached demo mode

### Running Tests

```bash
# Run the vertical slice on the benchmark PDF
python src/build_syllabus_slice.py

# Inspect output
cat output/syllabus_axe_baseline.json
```

## License

MIT

## Contributing

PRs welcome. For major changes, open an issue first.
