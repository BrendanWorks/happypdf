# The Preservation Gate: What It Checks and What It Guarantees

## The Problem It Solves

Accessibility remediation transforms a document with automated tools. The risk is silent content loss: a patch that drops a paragraph, an enhancement that swallows a table row. Scores and violation counts don't catch that; a document can score *better* after losing content.

happypdf's **preservation gate** guards against this: every review round's output is compared against the original converted document, and a round that damages content is discarded rather than shipped.

## The Actual Contract

The gate runs after each remediation round and compares the patched HTML against the **original baseline HTML** (always the original, never the previous round, so per-round tolerances cannot compound). Implemented in [`src/gate.py`](../src/gate.py):

| Check | Rule | Why this rule |
|---|---|---|
| `text_coverage` | Patched visible-text word count ≥ **95%** of the original | HTML normalization legitimately drops a little whitespace/artifact text; losing a real paragraph, list, or table blows well past 5% |
| `image_count` | Must never decrease | Every `<img>` from the conversion must survive |
| `table_structure` | Table count must never decrease | Same, for `<table>` elements |
| `heading_order` | No **new** heading-level skips (e.g. h1→h3) introduced by patches | A skip breaks the screen-reader outline; pre-existing skips in the source aren't blamed on the round |

A round that fails **any** check is discarded; its patches are thrown away, the loop stops, and the output is the last version that passed. Every check's before→after numbers are recorded in the round's `gate_checks` (visible in the job manifest and API responses), e.g.:

```json
{"name": "text_coverage", "passed": true,
 "detail": "314 -> 314 words (100.0%); threshold 95%"}
```

## What This Guarantees

- **No round can trade content for score.** A patch set that loses text, images, or tables is rejected even if it would improve the axe result.
- **Tolerances don't compound.** Because every round is measured against the original, three rounds can't each shave 5%.
- **The evidence is in every job.** The per-round `gate_checks` ship in the manifest, real numbers from the run, not a claim.

## What This Does *Not* Guarantee

- ❌ **Extraction fidelity.** The gate compares HTML before and after *remediation*. It does not verify the PDF→markdown OCR step, if olmOCR misreads or misses text on the page, the gate never sees it. OCR quality is a property of the input and the extraction model.
- ❌ **Exact word-for-word identity.** The text check is a ≥95% coverage threshold against the original, not a hash or character-level comparison.
- ❌ Text *correctness*, alt-text *quality*, or WCAG *conformance*; those are the jobs of the reviewers, the judge, axe-core, and ultimately human review (axe-core covers roughly 30–40% of WCAG).

The gate is a **safety net against remediation-induced loss**, not a mathematical proof of end-to-end integrity. Treat it as "automation can't quietly make the document worse," not as a compliance certificate.

## How It Fits the Loop

1. Each round's reviewer findings become a deterministic patch manifest, applied to elements by stable `data-ir-id`.
2. The patched HTML is gated against the original baseline (checks above).
3. axe-core rescores; a round that *increases* violations is also rejected (regression guard).
4. Only rounds that pass both gates count as progress.

See any live job's manifest (`GET /api/jobs/{id}/manifest`) for the real per-round gate numbers.
