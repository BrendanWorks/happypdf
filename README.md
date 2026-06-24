# happypdf

Convert inaccessible PDFs to WCAG-validated HTML using AI2's open model stack.

## The Problem

PDFs are everywhere in government, education, and enterprise — and most of them are inaccessible. Screen readers fail on untagged content, images carry no alt text, and tables have no structural markup, so the data inside them is invisible to assistive technology. Manual remediation is slow, expensive, and does not scale to the volume of documents organizations actually publish. happypdf automates the work using multi-agent iterative remediation: open vision models extract the content, a model generates alt text, and an accessibility engine scores the result so it can be fixed and re-scored until it passes.

## Three Deployment Modes

The orchestration is identical across all three modes — only the model backends are swapped. That pluggability is the whole point.

| Mode | Models | Cost | When to use |
|------|--------|------|-------------|
| **Self-hosted / Open-weight** | OLMo, Llama, Mistral, olmOCR run on your own Modal account or hardware | Zero marginal cost, lower quality | Cost-sensitive, offline, or air-gapped environments |
| **Demo / Hosted** | happypdf provisions Claude as judge/fixer with Gemini / GPT / Mistral / OLMo as peer reviewers | Per-conversion (scales with document size and review rounds) | Best quality; used for the portfolio demo |
| **BYOK / Enterprise** | User brings their own Claude / ChatGPT enterprise credentials; same code as demo mode | Zero incremental cost to happypdf | Enterprises that already hold model contracts |

**BYOK is the differentiator.** No competitor has built it. The barrier to enterprise accessibility tooling is procurement friction, not technical capability — organizations already have model contracts but cannot easily route a third-party SaaS tool through them. BYOK sidesteps that entirely: the customer points happypdf at credentials they already own and pay for.

## How It Works

```
PDF Input
  |
  v
olmOCR (Ai2, vision-based extraction) -> Markdown
  |
  v
Image extraction + Qwen2-VL alt text generation
  |
  v
Semantic HTML5 generation (landmarks, heading hierarchy, data-ir-id attributes)
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

This vertical slice ships steps 1-5. Rounds 1-3 (iterative remediation) are in development.

## Quick Start

```bash
# Clone and setup
git clone https://github.com/BrendanWorks/happypdf.git
cd happypdf

# Install dependencies
pip install -r requirements.txt
npm install
playwright install chromium

# Run the vertical slice (requires Modal credentials)
export MODAL_TOKEN_ID=your_token_id
export MODAL_TOKEN_SECRET=your_token_secret
python src/build_syllabus_slice.py

# Outputs
# - output/syllabus_scored.html
# - output/syllabus_axe_baseline.json
```

The orchestrator caches olmOCR markdown and alt text in `output/`, so re-runs are near-instant and do not re-spend GPU time. Pass `--no-cache` to force a fresh extraction.

## Related Work

> **SciA11y** (Wang, Cachola, et al., ASSETS '21) — the Ai2 team converted scientific-paper PDFs to accessible HTML, reporting ~86% success on readability and flagging alt text and table accessibility as open problems. happypdf extends this work to general and government PDFs and adds iterative multi-model WCAG validation.
> Paper: https://doi.org/10.1145/3441852.3471212

> **olmOCR** (Poznanski et al., Ai2, 2025) — Ai2's vision-based PDF extraction system. happypdf uses olmOCR as the primary extraction engine and adds the remediation layer on top.
> Paper: https://arxiv.org/abs/2502.18443

## Architecture & Codebase

```
src/build_syllabus_slice.py
  - Orchestrator: PDF -> olmOCR -> alt text -> HTML -> axe-core
  - Caches olmOCR markdown and alt text so iteration is fast
  - Logs timing and violations to stdout

modal/
  - Reference implementations (already deployed on Modal)
  - modal_olmocr_final.py:   PDF extraction (olmOCR via the official CLI)
  - modal_alttext_adapter.py: Qwen2-VL alt text generation
  - modal_olmo_wcag.py:       OLMo WCAG peer review

benchmark/
  - syllabus_NOTaccessible.pdf: the inaccessible source document used for the demo
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the technical deep-dive and [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for setup and troubleshooting.

## Known Limitations

- **Vertical slice only:** Rounds 2-3 (iterative remediation) are not yet implemented.
- **Duplicate element IDs** from visual artifacts (e.g., rows of dashes that hash to the same value) are documented in the output but not yet filtered.
- **Heading hierarchy** relies on olmOCR's markdown output; short standalone section labels are promoted to `<h2>` heuristically, and a top-level `<h1>` is synthesized if olmOCR emits none.
- **axe-core covers roughly 30-40% of WCAG requirements.** The hard gates — critical violations, content loss, and reading order — are the real measure of success, not the axe pass rate alone.

## For Developers

```
Next:  Claude judge + patch manifest (enables rounds 2-3)
Then:  Multi-round loop with early stopping
Then:  Next.js frontend for drag-and-drop + visual review
Then:  Pre-cached demo mode for portfolio
```

## Citation & License

Built on Ai2's olmOCR and OLMo models. Licensed under MIT.
