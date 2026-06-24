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
| **Demo / Hosted** | happypdf provisions Claude as judge/fixer with OLMo as peer reviewer | Per-conversion (scales with document size and review rounds) | Try it Now! |
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

The vertical slice (steps 1-5) is complete and working. The multi-round remediation loop (rounds 1-3) is implemented and validated across three document types — see below.

## What the Loop Actually Does

The vertical slice produces semantically valid HTML from any PDF — our generator builds proper landmarks, heading hierarchy, and alt text from olmOCR's markdown, so the baseline already scores **0 WCAG violations** on axe-core.

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

- **Baseline already accessible:** Our HTML generator produces valid semantic structure from any PDF, so axe-core finds 0 violations at baseline. The loop enhances with ARIA, it doesn't fix broken HTML. If you need to measure violation-reduction, you'd need a deliberately-broken baseline or a different source (e.g., OCR without structure recovery).
- **Duplicate element IDs from visual artifacts:** olmOCR treats PDF visual separator lines (rows of dashes) as content. They get IDs. If many are present, you'll see duplicates. Documented and non-blocking for the vertical slice.
- **Heading hierarchy:** olmOCR returns section labels as paragraphs, not headings. Short standalone lines are heuristically promoted to `<h2>`. This works well in practice but isn't perfect.
- **axe-core coverage:** axe-core detects ~30–40% of WCAG requirements. The other 60% require human review or custom logic. The loop handles the automatable portion; hard cases route to `needs_human`.
- **Live reviewers are wired and validated** (`src/reviewers.py`): OLMo (Modal), Gemini (google-genai), and GPT (openai) run in parallel with retry/backoff and graceful per-reviewer skip. Validated end-to-end on all three benchmark docs — all converge, gate passes every round, 0 violations throughout (see `benchmark/BENCHMARK_LIVE.md`). Note: OLMo (7B) sometimes emits malformed JSON on large documents and is skipped for that round; the loop continues with the other reviewers.

## Related Work

**SciA11y** (Wang, Cachola, et al., ASSETS '21) — Ai2 team converted scientific paper PDFs to accessible HTML. Evaluated ~86% success rate on readability; flagged alt-text and table accessibility as open problems. happypdf extends this work to general and government PDFs and adds iterative multi-model WCAG validation. [Paper](https://doi.org/10.1145/3441852.3471212)

**olmOCR** (Poznanski et al., Ai2, arXiv:2502.18443) — Ai2's vision-based PDF extraction system built on Qwen2.5-VL. happypdf uses olmOCR as the primary extraction engine and adds the remediation and validation pipeline. [Paper](https://arxiv.org/abs/2502.18443)

## Development

1. ~~Claude judge + patch manifest~~ — done (`src/judge.py`)
2. ~~Multi-round loop with early stopping~~ — done (`src/loop.py`)
3. ~~Content preservation gate~~ — done (`src/gate.py`)
4. ~~Benchmark across document types~~ — done (`src/benchmark.py`, [benchmark/BENCHMARK.md](benchmark/BENCHMARK.md))
5. Wire live OLMo/Gemini/GPT reviewers (replaces mock reviews; needs API credentials)
6. Next.js frontend (drag-and-drop, visual review)
7. Pre-cached demo mode

### Running Tests

```bash
# Run the vertical slice on the benchmark PDF
python src/build_syllabus_slice.py

# Inspect output
cat output/syllabus_axe_baseline.json
```

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
