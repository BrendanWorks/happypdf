# PointCheck Integration — Design Doc

Status: **Phase 1 implemented (July 16 2026)**; **Phase 2 implemented, STAGING ONLY (July 16 2026)** — prod promotion pending the maintenance window (`modal deploy src/modal_api.py`, then one prod e2e; the `alttext-judge` Modal app is already deployed and is only referenced by the new API code). Phase 2 notes: `modal/modal_alttext_judge.py` (Molmo-7B-D 4-bit on A10G, weights baked, `transformers==5.14.1` pinned) + `judge_alt_text_map()` in `build_syllabus_slice.py` + concurrent collection in `_live` (report-only `alt_text_review` block). Generation uses a MANUAL greedy decode loop with Molmo's legacy tuple cache — transformers' `generate()` is incompatible with this model's remote code (modern versions pre-inject a DynamicCache; Molmo's forward does `past_key_values[0][0].size(-2)` → `'list' object has no attribute 'size'`). Flag threshold calibrated at score ≤2 (the judge is strict: good alt scored 3, filename/wrong alt scored 1 on the Accessible University logo smoke test). Phases 3+ remain proposed. Implementation note: the checks run via `pointcheck_score(html)` — a one-shot sync-Playwright run mirroring `loop.axe_score()` — called post-baseline and post-loop in `_live` rather than inside `_run_loop_inner`; the JS strings were copied verbatim, so no async bridge was needed at all. Validation: 3 new pytest cases (planted issues fire; clean document-shaped HTML is silent; web-noise prunes verified), zero false positives against all three `api/snapshots/` final_htmls (each 100% on axe), and a staging + prod e2e conversion with both blocks present and the pipeline unaffected.

Revised July 15 2026: merged the original check-porting plan with a capability-track review. The original doc asked "which PointCheck checks port onto happypdf's output HTML?" — this revision also answers the broader question, "where does PointCheck's visual inspection make happypdf better for users?" The two produce different GPU priorities. File/line claims in *Current state* and Phase 1 were re-verified against both codebases during the revision.

## Context / Motivation

happypdf scores its generated HTML using axe-core alone (`src/loop.py`'s `AxeScorer`), and this project's own architecture doc already admits the gap: [`docs/ARCHITECTURE.md`](ARCHITECTURE.md) states axe-core "covers roughly 30-40% of WCAG success criteria — it cannot judge reading order, content loss during extraction, or whether alt text is actually correct."

[PointCheck](https://pointcheck.org) ([github.com/BrendanWorks/PointCheck](https://github.com/BrendanWorks/PointCheck)), a separate project by the same author, was built specifically to catch what DOM-only scanners miss. Its own validation data (`wcag_tool_comparison.csv`) shows real cases — W3C's "Before" accessibility test page, the AU and Mars test pages — where axe reports 0 violations but PointCheck correctly flags JS-only links, 200%-zoom text clipping, and visually-insufficient focus rings.

Note where the ARCHITECTURE.md gap actually lives: **reading order, content loss, and alt-text correctness are conversion-fidelity problems, not output-scanning problems.** No check that inspects only the generated HTML can address them — they require looking at the original PDF too, or at the images themselves. That observation drives the two-track structure below.

## Current state: happypdf's scoring contract

`AxeScorer.score(html)` (`src/loop.py:63-111`) loads HTML into a reused headless-Chromium Playwright instance (sync API), injects axe-core 4.12.1, and returns:

```python
{"score": float, "violations": int, "passes": int, "critical_serious": int}
```

Called ~4x per document (baseline + up to `MAX_ROUNDS=3` remediation rounds). A regression guard (`loop.py:296-305`) reverts any round that increases `violations`. Convergence requires score ≥95% AND `hard_gates_pass()` AND zero new patches applied (`loop.py:314-317`).

Also relevant: the text reviewers never see images at all — `_strip_data_uris()` (`src/reviewers.py:152`) removes them before review, and the preservation gate (`src/gate.py`) compares extracted-vs-patched structure, so nothing in the current pipeline can detect content that olmOCR dropped or scrambled *before* the HTML existed.

## PointCheck's architecture

PointCheck's checks (`backend/app/wcag_checks/*.py`) follow a layered pattern via `BaseWCAGTest.run(self, page, task) -> AsyncGenerator` (`base.py:76-79`) — they take a live **async** Playwright `Page`, not a URL or raw HTML string:

- **Layer 1 (JS/DOM, no GPU)** — every check has one. `_molmo_analyze()` (`base.py:113-130`) returns `""` and degrades gracefully when `analyzer=None`, so Layer-1-only execution is an already-supported mode in the existing code, not something that needs to be built.
- **Layer 2 (MolmoWeb-8B screenshot QA)** — single-shot visual questions layered on top of Layer 1.
- **Layer 3 (agent loop)** — only `keyboard_nav.py` and `form_errors.py`; multi-step interactive clicking that needs a real live page, not applicable to a static converted document.

Two checks stand out as directly additive to axe:
- `page_structure.py`'s `STRUCTURE_JS` catches filename-pattern alt text (`img_042.png` set as the alt attribute), vague link text ("click here"), and non-decorative empty-alt images via size/link heuristics — none of which axe's ruleset covers.
- `color_blindness.py`'s DOM-tree alpha-composite walk (`getEffectiveBg()`) fixes exactly the class of false-pass bug happypdf's own docs flag: axe can report a contrast check as passing when the actual rendered color comes from stacked semi-transparent layers.

Beyond the checks, PointCheck has two transferable **capabilities** that are not checks at all:
- `MolmoQAAnalyzer` (`backend/app/models/molmo2.py`) — Molmo-7B-D-0924 in 4-bit NF4 (~4 GB VRAM), a general screenshot/image QA model, including the hard-won Transformers 5.x compat patches (ROPE default key, lenient processor init, DynamicCache patch, read-only-property setters).
- The LLM-as-judge eval pattern from PointCheck's `regression_suite.py` — an independent model grading another model's output.

## Two tracks

**Track A — port checks onto the generated HTML** (the original plan). Improves scanning coverage of the thing happypdf already controls and already validates. Cheap, low-risk, incremental.

**Track B — apply vision QA to the conversion problem itself.** Judges alt-text quality with an independent vision model, and compares rendered output against the original PDF pages. This is the only track that touches the three admitted gaps (reading order, content loss, alt-text correctness), and it is where GPU budget should go first.

## Recommended phasing (merged)

**Phase 1 (Track A) — port Layer-1-only checks, `analyzer=None`, zero GPU cost.**
Port `page_structure.py`'s `STRUCTURE_JS`, `color_blindness.py`'s contrast walk, and `keyboard_nav.py`'s static JS scan (`KEYBOARD_STATIC_JS` — skip the Layer 3 agent-loop import entirely). All three reuse the Chromium page `AxeScorer` already keeps open per job.

Mechanically: `AxeScorer` uses sync Playwright; PointCheck's checks are async. Bridge with a small `asyncio.run()` wrapper around just the Layer-1 JS-eval calls — don't migrate all of `AxeScorer` to async, which would be a larger, riskier touch to `_run_loop_inner`'s control flow for no benefit at this phase. This bridge is safe here specifically: the caller of `AxeScorer`/`run_loop`, `_live()`, runs on a plain `threading.Thread` (`api/main.py:597-599`), not inside FastAPI's event loop, so there's no "asyncio.run() cannot be called from a running event loop" conflict to worry about.

**Phase 2 (Track B) — independent alt-text judging with Molmo-7B-D.**
Today Qwen2-VL generates alt text (`src/build_syllabus_slice.py` step 4) and nothing verifies it — the reviewers can't see images. Add a judge step: for each generated alt text, show Molmo-7B-D the image plus the text and ask for a 1–5 adequacy score with a one-line critique, and an independent opinion on `requires_long_desc` (charts/data graphics need long descriptions far more often than photos). Low scores get flagged in the manifest for human attention (non-blocking at first; optionally trigger one regeneration retry later).

Why this is the first GPU spend rather than the original Phase 2 (heading-hierarchy screenshot QA): it is per-image rather than per-page-per-round, the model is the cheap one (~4 GB 4-bit → A10G or smaller), the judge is a *different* model than the generator so it's a real check rather than self-grading, and it directly addresses an admitted gap ("whether alt text is actually correct") instead of re-inspecting structure the gate already validates.

Implementation notes:
- New Modal function (own app or function, scale-to-zero), matching the existing pattern of separate functions for olmOCR/alt-text. Do **not** co-locate with the extraction container.
- Lift `MolmoQAAnalyzer` from PointCheck including all compat patches; pin `transformers` and bake weights into the image at build time, exactly as `modal/modal_olmocr_v2.py` already does — Molmo's Transformers compatibility is fragile and the patches exist for a reason.
- Cache the model at container/module level so batch jobs reuse the warm container (PointCheck commit `95ae1b4` is the reference implementation of this pattern; it took a scan from 155 s to 19 s).

**Phase 3 (Track B) — visual fidelity gate: rendered output vs original PDF pages.**
Render each original PDF page to an image (pdf2image/pypdfium2) and screenshot the corresponding region of the produced HTML (the Chromium instance is already there). Ask Molmo-7B-D a fixed question battery about each side — "How many figures/tables appear on this page?", "Is there a chart, and what does it show?", "What are the first and last sentences?", "Does this figure contain substantial readable text?" — and turn disagreements into findings: *"Page 3 of the original contains a bar chart that does not appear in the output."*

This is the differentiator: it upgrades the preservation claim from "structural counts matched" to "an independent vision model compared the output against the original document, page by page." It also catches text-rendered-as-image (the scanned-PDF failure mode, which today passes silently as an image with alt text) and gross reading-order scrambles in multi-column sources. Run once post-convergence, not per round. Findings are a non-blocking report section first, same discipline as Phase 1; page-to-region alignment between a paginated PDF and a single-flow HTML document is approximate, so start with per-page content-inventory questions (counts, presence) rather than exact-position comparisons.

**Phase 4 — deferred.**
- *Heading-hierarchy screenshot QA* (the original Phase 2): largely subsumed by the Phase 3 question battery; revisit only if fidelity-gate findings show structure-specific misses.
- *Focus Visibility* (`focus_indicator.py`, MolmoWeb-8B + Molmo-7B-D, ~20 GB combined): unchanged deferral reasoning — converted documents have simple, deterministic tab order; if ever pursued, run as a separate Modal GPU function once post-convergence, not per round.
- *Pointing-annotated findings*: MolmoWeb-8B's `point_to()` can localize a finding on the page image and embed a crop in the manifest (PointCheck's `screenshot_b64`-per-finding pattern). High polish value, but it needs the 16 GB model — do it last, and only if report impact justifies the bigger GPU.

**Skip (unchanged):** `form_errors.py` (PDF-to-HTML conversions essentially never produce `<form>` elements) and `zoom_test.py`'s Layer 2/3 (low value for single-column converted documents; its Layer 1 CDP check is cheap enough to fold into Phase 1 as a bonus if convenient, but not a priority).

## Integration points

- **Phase 1:** sibling module (e.g. `src/pointcheck_scorer.py`) called alongside `scorer.score(patched)` in `_run_loop_inner` (`loop.py:263`), returning a separate `{"pointcheck": {...}}` block. Do **not** fold results into axe's `violations`/`critical_serious` keys — the regression guard (`loop.py:296-305`) and convergence check (`loop.py:314`) key off those directly, and `judge.py`/`applicator.py` don't yet have patch strategies for PointCheck-specific findings. Report findings as a non-blocking coverage section first; only promote specific categories into the hard-gate logic once matching patch strategies exist.
- **Phase 2:** a judge call after `generate_alt_text()` in `src/build_syllabus_slice.py`; results land as new manifest fields per image (`alt_judge_score`, `alt_judge_critique`, `alt_judge_long_desc_opinion`).
- **Phase 3:** post-convergence step in `_run_loop_inner` (or in the job runner after `run_loop` returns), emitting a `{"fidelity": {...}}` block in the report.

## Risk assessment

- **Prod-safety: low.** The async/sync bridge is safe (see Phase 1), and any implementation goes through this project's standing backend deploy gate — local syntax/type check → staging deploy → full `regression_suite.py` — before touching prod.
- **Technical/correctness (Track A): low.** The JS is a verbatim copy, not new logic — just relocated, and isolated to a non-blocking sibling report.
- **Output quality (Track A): moderate — the main real risk for ported checks.** PointCheck's checks were validated against live websites (W3C's test page, GDS, AU, Mars), not PDF-derived single-flow documents. Some findings (e.g. "missing skip navigation") may be irrelevant noise on happypdf's document shape. Mitigate by running against `benchmark/` docs and pruning anything that fires spuriously before it's customer-facing. Note this risk applies to Track A only — Track B's judge and fidelity gate are designed around the conversion problem rather than adapted from web scanning.
- **Output quality (Track B): moderate, different failure mode.** A miscalibrated judge nags users about acceptable alt text; a naive fidelity battery false-alarms on pagination differences. Both need calibration runs against `benchmark/` docs with known-good and known-bad examples before being shown to users, and both must launch as non-blocking report sections.
- **Model fragility (Track B): known and manageable.** Molmo on recent Transformers requires the compat patches in PointCheck's `molmo2.py`; pin versions and bake weights into the image (same discipline as olmOCR-2).
- **Maintenance: low but real long-term.** Track A is a fork, not a shared dependency — the JS lives in two repos and can drift. Track B lifts `MolmoQAAnalyzer` once; same caveat.

## Licensing

PointCheck has no `LICENSE` file (all-rights-reserved by default). Since both projects share the same author, this isn't a legal blocker — just add an attribution/license header on any ported module for cleanliness. Independent quick win: add a LICENSE to the PointCheck repo itself.

## Payoff

- **Phase 1:** more issues actually caught, for free — no added latency or cost, since it rides on the browser page already open for axe scoring. The visible score won't change (findings are a separate non-blocking section, deliberately, to avoid false convergence regressions).
- **Phase 2:** the single most important accessibility artifact happypdf produces — alt text — gets independently verified instead of trusted. Manifest gains a per-image quality signal users can act on.
- **Phase 3:** the preservation claim becomes visual and page-by-page, closing the "reading order / content loss" gap axe and the structural gate cannot touch. This is the feature that most changes what a customer can trust the tool to have done.

## Verification

Per phase, against `benchmark/` documents, before anything is customer-facing:

**Phase 1:**
1. No false positives against docs that already score 100% on axe.
2. Genuine new findings on docs with known issues (cross-check against PointCheck's `wcag_tool_comparison.csv` categories).
3. The axe-regression guard and 95% convergence threshold still behave correctly with the new sibling `pointcheck` block present but not feeding into `violations`/`critical_serious`.

**Phase 2:**
1. Judge scores correlate with human judgment on a hand-labeled sample of benchmark images (good alt ≥4, filename/vacuous alt ≤2).
2. `requires_long_desc` opinion flags charts/graphs and not photos.
3. No pipeline failure when the judge function is unavailable (non-fatal, same pattern as PointCheck's narrative fallback).

**Phase 3:**
1. A known-bad fixture (a PDF with a deliberately dropped figure) MUST produce a fidelity finding — the ground-truth-document pattern from PointCheck's regression suite.
2. Clean benchmark docs produce zero fidelity findings across two consecutive runs (variance check).
3. Multi-column benchmark doc: reading-order questions produce consistent answers.

Per this project's standing deploy rule, any backend change goes through `modal deploy --env staging` + `regression_suite.py` before prod.
