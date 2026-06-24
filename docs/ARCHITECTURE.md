# Architecture

happypdf turns an inaccessible PDF into WCAG-validated HTML through a linear extraction-and-scoring pipeline, with a remediation loop layered on top (in development). This document explains the moving parts of the shipping vertical slice and the design decisions behind them.

## Pipeline Overview

```
PDF -> olmOCR (markdown) -> PyMuPDF (images) -> Qwen2-VL (alt text)
    -> semantic HTML5 -> axe-core score -> scored HTML + raw axe JSON
```

The orchestrator is `src/build_syllabus_slice.py`. It is deliberately a single, readable file: each pipeline stage is a function, every stage logs a timestamped line to stdout, and the two expensive GPU calls (olmOCR and Qwen2-VL) are cached to disk so HTML and scoring iteration is free.

## Element ID System

Every generated element carries a `data-ir-id` ("intermediate representation id") attribute. IDs are **deterministic**: they are the first 8 hex characters of a SHA-256 hash of the element's normalized text content, prefixed with the page number — e.g. `block-1-cd967709`.

```python
key = " ".join(text[:200].split())          # normalize whitespace, cap length
ident = f"block-{page}-{sha256(key)[:8]}"
```

Determinism is the point. When the remediation loop (rounds 2-3) rewrites an element to fix a violation, the patch needs to target a stable handle that survives across runs. Re-running extraction on the same PDF yields the same IDs, so a patch manifest can say "replace the contents of `block-1-844ada8f`" and have it mean the same element every time.

The tradeoff: two elements with identical normalized text hash to the same ID. This happens with visual artifacts such as rows of dashes used as separators. The builder detects collisions (`dup_ids`) and records them in the output's comment block rather than silently emitting invalid duplicate IDs. Filtering these artifacts upstream is a known TODO.

## Three Deployment Modes (and Why the Code Doesn't Change)

The three modes described in the README — self-hosted, hosted demo, and BYOK — are **not three codebases**. They are the same orchestration with different model backends bound at the seams:

- **Extraction** is always olmOCR. It runs on your Modal account in every mode.
- **Alt text** is Qwen2-VL today; it can be swapped for any vision model behind the same `generate_alt_text(image_b64, context) -> {alt_text, ...}` contract.
- **Peer review / judge** (rounds 2-3) is where the modes diverge: OLMo for self-hosted, Claude + a panel for hosted, and customer-supplied credentials for BYOK. All speak the same review/patch contract, so the loop code is identical.

Because the seams are plain function contracts, "switching modes" is configuration, not a rewrite. That is what makes BYOK cheap to offer.

## Modal Infrastructure

The GPU work runs as deployed Modal functions, called from the local orchestrator via `modal.Function.from_name(app, fn).remote(...)`:

| App | Function | GPU | Role |
|-----|----------|-----|------|
| `olmocr` | `process_pdf(pdf_bytes, filename)` | H100 | Runs the official olmOCR CLI (vLLM + Qwen2.5-VL), returns markdown |
| `pdfaccess-alttext` | `generate_alt_text(image_b64, context)` | H100 | Qwen2-VL alt text generation |
| `olmo-wcag-reviewer` | OLMo peer review | A100/H100 | WCAG peer review (rounds 2-3, reference impl in `modal/`) |

Reference implementations live in `modal/`. They are already deployed; the directory is kept for transparency and redeployment, not imported by the orchestrator.

Cold-start cost is dominated by olmOCR (~3-4 minutes to bring up the vLLM server on a cold H100). Qwen2-VL alt text is ~1-1.5 minutes cold. This is exactly why the orchestrator caches their outputs.

## axe-core Integration

Scoring runs the real [axe-core](https://github.com/dequelabs/axe-core) engine inside a real headless Chromium via Playwright — not a reimplementation or a mock:

1. The generated HTML is written to `output/` and loaded with `file://` navigation.
2. `axe.min.js` is injected into the loaded page with `page.evaluate(axe_src)`.
3. `axe.run()` executes and returns structured JSON (`violations`, `passes`, `incomplete`, `testEngine`, etc.).

> **Note on a common bug:** axe must be injected *after* the page has loaded, using `page.evaluate(...)`. Injecting via `add_init_script` after `goto` does nothing — init scripts only run on the next navigation, so axe is never present on the page actually being audited. The orchestrator uses the evaluate-after-load approach.

The raw axe JSON is written verbatim to `output/syllabus_axe_baseline.json`. A summary (score, severity counts, violation rules) is computed and embedded as an HTML comment block at the top of `output/syllabus_scored.html`.

### Score vs. Hard Gates

The reported score is simply `passes / (passes + violations)`. It is a useful signal, not a verdict. axe-core covers roughly 30-40% of WCAG success criteria — it cannot judge reading order, content loss during extraction, or whether alt text is actually *correct*. The real acceptance bar for a remediated document is the hard gates: zero critical violations, no content dropped relative to the source, and a sensible reading order. Those gates are enforced by the remediation loop, not by axe alone.

## Known Bugs and Workarounds

- **Quote escaping in `alt` attributes.** Qwen2-VL frequently returns alt text containing literal double quotes (e.g. `logo for "Accessible University"`). Because `alt="..."` is double-quoted, an unescaped quote truncates the attribute mid-sentence and leaks the remainder into bogus attributes — and axe still "passes" because *an* alt attribute exists. The builder uses attribute-safe escaping (`&` `<` `>` `"` -> entities) for all dynamic attribute values. Element *text* uses the lighter `&<>`-only escaping.
- **Duplicate `data-ir-id` values.** See the Element ID System section. Collisions are detected and documented in the output comment block; upstream artifact filtering is a TODO.
- **Heading promotion heuristic.** olmOCR sometimes emits section labels (e.g. "Course Objectives") as plain paragraphs rather than markdown headings. The builder synthesizes an `<h1>` from the first content line when no heading exists, and short standalone labels are candidates for `<h2>` promotion. This is heuristic and can occasionally mis-tag a line; it is a tradeoff for stronger document structure when the extractor under-tags.
