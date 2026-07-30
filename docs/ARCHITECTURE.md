# Architecture

happypdf turns an inaccessible PDF into WCAG-validated HTML through a linear extraction-and-scoring pipeline, with a remediation loop layered on top. This document explains the moving parts of the shipping vertical slice, the design decisions behind them, and the trade-offs we made.

**Design Philosophy:** happypdf prioritizes **auditability, safety, and rigor** over raw speed. Every choice is grounded in the constraint that accessibility remediation must be *additive*, never losing content, never making silent changes, always showing its work.

## Pipeline Overview

```
PDF -> olmOCR (markdown) -> PyMuPDF (images) -> Qwen2-VL (alt text)
    -> semantic HTML5 -> axe-core score -> scored HTML + raw axe JSON
```

The orchestrator is `src/build_syllabus_slice.py`. It is deliberately a single, readable file: each pipeline stage is a function, every stage logs a timestamped line to stdout, and the two expensive GPU calls (olmOCR and Qwen2-VL) are cached to disk so HTML and scoring iteration is free.

## Element ID System

Every generated element carries a `data-ir-id` ("intermediate representation id") attribute. IDs are **deterministic**: they are the first 8 hex characters of a SHA-256 hash of the element's normalized text content, prefixed with the page number, e.g. `block-1-cd967709`.

```python
key = " ".join(text[:200].split())          # normalize whitespace, cap length
ident = f"block-{page}-{sha256(key)[:8]}"
```

Determinism is the point. When the remediation loop (rounds 2-3) rewrites an element to fix a violation, the patch needs to target a stable handle that survives across runs. Re-running extraction on the same PDF yields the same IDs, so a patch manifest can say "replace the contents of `block-1-844ada8f`" and have it mean the same element every time.

The tradeoff: two elements with identical normalized text hash to the same ID. This happens with visual artifacts such as rows of dashes used as separators. The builder detects collisions (`dup_ids`) and records them in the output's comment block rather than silently emitting invalid duplicate IDs. Filtering these artifacts upstream is a known TODO.

## Deployment Modes (and Why the Code Doesn't Change)

All deployment modes use the same codebase. **Credential selection and reviewer profiling are environment-variable seams.**

- **Extraction** is always olmOCR. It runs on your Modal account in every mode.
- **Alt text** is Qwen2-VL today; it can be swapped for any vision model behind the same `generate_alt_text(image_b64, context) -> {alt_text, ...}` contract.
- **Peer review / judge** (review rounds) uses `reviewers.make_live_provider(profile, ...)`:
  - `REVIEWER_PROFILE=default` (or unset): OLMo + Gemini + GPT-4o mini in parallel (default).
  - `REVIEWER_PROFILE=olmo-only`: OLMo only (single-model review).
  - Hosted credentials come from the environment (`.env`, Modal secrets). **BYOK keys are passed explicitly down the call chain per job**, never written to the process environment, so concurrent jobs with different credentials cannot observe each other's keys (changed in v1.2.1).

**Why this matters:** Adding OLMo-only mode required only 50 lines of code (a profile selector + filter logic) because the loop, judge, applicator, and gate don't know or care how many reviewers there are. The same code paths work whether it's three models or one. This is the payoff of "review-source agnostic" design; new modes are cheap to add.

## Modal Infrastructure

The GPU work runs as deployed Modal functions, called from the local orchestrator via `modal.Function.from_name(app, fn).remote(...)`:

| App | Function | GPU | Role |
|-----|----------|-----|------|
| `olmocr-v2` | `process_pdf(pdf_bytes, filename)` | H100 | Runs the official olmOCR-2 CLI (vLLM + Qwen2.5-VL backbone), returns markdown; weights baked into the image, one extraction per container (`olmocr` remains as the v1 fallback app) |
| `pdfaccess-alttext` | `generate_alt_text(image_b64, context)` | H100 | Qwen2-VL alt text generation |
| `olmo-wcag-reviewer` | OLMo peer review (bearer-token auth) | A10G | WCAG peer review across rounds; pre-warmed at job start via `/warmup` |

Reference implementations live in `modal/`. They are already deployed; the directory is kept for transparency and redeployment, not imported by the orchestrator.

Cold-start cost is dominated by olmOCR (~2.5-4 minutes to boot vLLM from image-local weights on a cold H100). Qwen2-VL alt text is ~1-1.5 minutes cold, but runs concurrently with extraction so its cold start is hidden. The CLI orchestrator additionally caches both outputs to disk so HTML/scoring iteration is free.

## axe-core Integration

Scoring runs the real [axe-core](https://github.com/dequelabs/axe-core) engine inside a real headless Chromium via Playwright, not a reimplementation or a mock:

1. The generated HTML is written to `output/` and loaded with `file://` navigation.
2. `axe.min.js` is injected into the loaded page with `page.evaluate(axe_src)`.
3. `axe.run()` executes and returns structured JSON (`violations`, `passes`, `incomplete`, `testEngine`, etc.).

> **Note on a common bug:** axe must be injected *after* the page has loaded, using `page.evaluate(...)`. Injecting via `add_init_script` after `goto` does nothing, init scripts only run on the next navigation, so axe is never present on the page actually being audited. The orchestrator uses the evaluate-after-load approach.

The raw axe JSON is written verbatim to `output/syllabus_axe_baseline.json`. A summary (score, severity counts, violation rules) is computed and embedded as an HTML comment block at the top of `output/syllabus_scored.html`.

### Score vs. Hard Gates

The reported score is simply `passes / (passes + violations)`. It is a useful signal, not a verdict. axe-core covers roughly 30-40% of WCAG success criteria; it cannot judge reading order, content loss during extraction, or whether alt text is actually *correct*. The real acceptance bar for a remediated document is the hard gates: zero critical violations, no content dropped relative to the source, and a sensible reading order. Those gates are enforced by the remediation loop, not by axe alone.

## Trade-offs in Pipeline Design

### Speed vs. Auditability: Why Deterministic IDs?

A simpler approach would be to generate new UUIDs for each element on each run. But then the patch manifest wouldn't be reproducible, "replace element X" would mean different things across runs, making the audit trail unverifiable.

We chose deterministic hashing over UUIDs specifically to make the remediation process auditable. When you can say "here's the exact element we changed, here's the hash of its content," the audit trail becomes precise and independently reproducible, not just a log.

The trade-off: collision handling. Two elements with identical normalized text hash to the same ID (e.g., repeated separator lines). We detect and document collisions rather than silently emitting duplicates. Upstream filtering would eliminate the collisions but add complexity; we chose to be transparent about it instead.

### Accuracy vs. Computation: Why Multi-Model Review?

A single LLM could generate patches directly. It's faster and simpler.

But single models have blindspots:
- Claude excels at ARIA patterns and structured fixes.
- Gemini is strong at semantic descriptions and image analysis.
- OLMo/Qwen reason well about document structure.

Each model catches different classes of errors. By running three reviewers in parallel and having a judge deduplicate and filter unsafe patches, we improve resilience to model-specific failures. On the Cosmic Story Mat benchmark (25 embedded images), OLMo timed out on the first attempt; the loop correctly continued with Gemini + GPT, re-tried OLMo, and converged successfully.

The trade-off: this approach is slower per-round (3 parallel calls + judge) than one-shot prompting. We made that trade because accessibility remediation is not a latency-critical workload; a few extra seconds per document is acceptable if it means fewer hallucinated ARIA roles or missed edge cases.

### Completeness vs. Complexity: Why Real Chromium for Axe?

We inject axe-core into a real headless Chromium instance rather than parsing HTML rules locally. This means:
- Real DOM rendering, real CSS cascade, real computed styles.
- axe-core can detect actual accessibility bugs, not just structural ones.
- We get structured JSON output from the real engine.

The trade-off: This requires Playwright + Chromium + a running Playwright process. It's heavier than static HTML analysis. But the result is authoritative, if axe-core says there are 0 violations, that judgment is credible because it came from the actual accessibility audit engine that organizations use.

## Known Bugs and Workarounds

- **Quote escaping in `alt` attributes.** Qwen2-VL frequently returns alt text containing literal double quotes (e.g. `logo for "Accessible University"`). Because `alt="..."` is double-quoted, an unescaped quote truncates the attribute mid-sentence and leaks the remainder into bogus attributes, and axe still "passes" because *an* alt attribute exists. The builder uses attribute-safe escaping (`&` `<` `>` `"` -> entities) for all dynamic attribute values. Element *text* uses the lighter `&<>`-only escaping.
- **Duplicate `data-ir-id` values.** See the Element ID System section. Collisions are detected and documented in the output comment block; upstream artifact filtering is a TODO.
- **Heading promotion heuristic.** olmOCR sometimes emits section labels (e.g. "Course Objectives") as plain paragraphs rather than markdown headings. The builder synthesizes an `<h1>` from the first content line when no heading exists, and short standalone labels are candidates for `<h2>` promotion. This is heuristic and can occasionally mis-tag a line; it is a tradeoff for stronger document structure when the extractor under-tags.
