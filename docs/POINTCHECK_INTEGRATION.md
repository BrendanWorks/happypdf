# PointCheck Integration — Design Doc (not yet implemented)

Status: **Proposed / future work.** No code from this doc has been implemented. This exists to capture the research and phased recommendation so it isn't lost.

## Context / Motivation

happypdf scores its generated HTML using axe-core alone (`src/loop.py`'s `AxeScorer`), and this project's own architecture doc already admits the gap: [`docs/ARCHITECTURE.md`](ARCHITECTURE.md) states axe-core "covers roughly 30-40% of WCAG success criteria — it cannot judge reading order, content loss during extraction, or whether alt text is actually correct."

[PointCheck](https://pointcheck.org) ([github.com/BrendanWorks/PointCheck](https://github.com/BrendanWorks/PointCheck)), a separate project by the same author, was built specifically to catch what DOM-only scanners miss. Its own validation data (`wcag_tool_comparison.csv`) shows real cases — W3C's "Before" accessibility test page, the AU and Mars test pages — where axe reports 0 violations but PointCheck correctly flags JS-only links, 200%-zoom text clipping, and visually-insufficient focus rings.

This doc captures whether that tech is portable into happypdf's very different pipeline (a static generated HTML file, not a live URL) and what a phased integration would look like.

## Current state: happypdf's scoring contract

`AxeScorer.score(html)` (`src/loop.py:63-111`) loads HTML into a reused headless-Chromium Playwright instance (sync API), injects axe-core 4.12.1, and returns:

```python
{"score": float, "violations": int, "passes": int, "critical_serious": int}
```

Called ~4x per document (baseline + up to `MAX_ROUNDS=3` remediation rounds). A regression guard (`loop.py:296-305`) reverts any round that increases `violations`. Convergence requires score ≥95% AND `hard_gates_pass()` AND zero new patches applied (`loop.py:314-317`).

## PointCheck's architecture

PointCheck's checks (`backend/app/wcag_checks/*.py`) follow a layered pattern via `BaseWCAGTest.run(self, page, task) -> AsyncGenerator` (`base.py:76-79`) — they take a live **async** Playwright `Page`, not a URL or raw HTML string:

- **Layer 1 (JS/DOM, no GPU)** — every check has one. `_molmo_analyze()` (`base.py:113-130`) returns `""` and degrades gracefully when `analyzer=None`, so Layer-1-only execution is an already-supported mode in the existing code, not something that needs to be built.
- **Layer 2 (MolmoWeb-8B screenshot QA)** — single-shot visual questions layered on top of Layer 1.
- **Layer 3 (agent loop)** — only `keyboard_nav.py` and `form_errors.py`; multi-step interactive clicking that needs a real live page, not applicable to a static converted document.

Two checks stand out as directly additive to axe:
- `page_structure.py`'s `STRUCTURE_JS` catches filename-pattern alt text (`img_042.png` set as the alt attribute), vague link text ("click here"), and non-decorative empty-alt images via size/link heuristics — none of which axe's ruleset covers.
- `color_blindness.py`'s DOM-tree alpha-composite walk (`getEffectiveBg()`) fixes exactly the class of false-pass bug happypdf's own docs flag: axe can report a contrast check as passing when the actual rendered color comes from stacked semi-transparent layers.

## Recommended phasing

**Phase 1 — port Layer-1-only checks, `analyzer=None`, zero GPU cost.**
Port `page_structure.py`'s `STRUCTURE_JS`, `color_blindness.py`'s contrast walk, and `keyboard_nav.py`'s static JS scan (`KEYBOARD_STATIC_JS` — skip the Layer 3 agent-loop import entirely). All three reuse the Chromium page `AxeScorer` already keeps open per job.

Mechanically: `AxeScorer` uses sync Playwright; PointCheck's checks are async. Bridge with a small `asyncio.run()` wrapper around just the Layer-1 JS-eval calls — don't migrate all of `AxeScorer` to async, which would be a larger, riskier touch to `_run_loop_inner`'s control flow for no benefit at this phase. This bridge is safe here specifically: the caller of `AxeScorer`/`run_loop`, `_live()`, runs on a plain `threading.Thread` (`api/main.py:597-599`), not inside FastAPI's event loop, so there's no "asyncio.run() cannot be called from a running event loop" conflict to worry about.

**Phase 2 — pilot Layer 2 (single-shot MolmoWeb-8B QA) selectively, not blanket.**
Layer 2 questions are one screenshot + one Molmo call (~30-50s per `MOLMO_TIMEOUT`), materially cheaper than the full dual-model Focus Visibility flow. Try `page_structure.py`'s heading-hierarchy question against a handful of happypdf's existing `benchmark/` docs before committing GPU budget to it.

**Phase 3 — defer Focus Visibility.**
`focus_indicator.py` (MolmoWeb-8B + Molmo-7B-D, ~20GB VRAM combined) risks contention with happypdf's Modal container, which already loads olmOCR-2 + alt-text Qwen2-VL and makes 3 external LLM calls per round. If pursued later, run it as a **separate Modal GPU function** (matching the existing pattern in `src/build_syllabus_slice.py` for olmOCR/alt-text as separate functions) called once post-convergence, not per round — avoids multiplying PointCheck's own documented 60-90s cold start by up to 4x. Converted PDFs also have simpler, deterministic tab order compared to live interactive sites, so the payoff here is genuinely lower priority than Phase 1/2.

**Skip:** `form_errors.py` (PDF-to-HTML conversions essentially never produce `<form>` elements) and `zoom_test.py`'s Layer 2/3 (low value for single-column converted documents; its Layer 1 CDP check is cheap enough to fold into Phase 1 as a bonus if convenient, but not a priority).

## Integration point

Add a sibling module (e.g. `src/pointcheck_scorer.py`) called alongside `scorer.score(patched)` in `_run_loop_inner` (`loop.py:263`), returning a separate `{"pointcheck": {...}}` block. Do **not** fold results into axe's `violations`/`critical_serious` keys — the regression guard (`loop.py:296-305`) and convergence check (`loop.py:314`) key off those directly, and `judge.py`/`applicator.py` don't yet have patch strategies for PointCheck-specific findings (e.g. structural heading-order issues). Report PointCheck findings as a non-blocking coverage section first; only promote specific categories into the hard-gate logic once matching patch strategies exist.

## Risk assessment

- **Prod-safety: low.** The async/sync bridge is safe (see Phase 1 above), and any implementation goes through this project's standing backend deploy gate — local syntax/type check → staging deploy → full `regression_suite.py` — before touching prod.
- **Technical/correctness: low.** The JS itself is a verbatim copy (PointCheck's own comment reads "unchanged from PointCheck v1 — reproduced in full for self-containment"), not new logic — just relocated, and isolated to a non-blocking sibling report.
- **Output quality: moderate — the main real risk.** PointCheck's checks were validated against live websites (W3C's test page, GDS, AU, Mars), not PDF-derived single-flow documents. Some findings (e.g. "missing skip navigation," `landmark-one-main`) may be irrelevant noise on happypdf's document shape, which has no page chrome to begin with. Mitigate by running against happypdf's own `benchmark/` docs and pruning/tuning anything that fires spuriously before it's customer-facing.
- **Maintenance: low but real long-term.** This would be a fork, not a shared dependency — the JS lives in two repos and can drift over time.

## Licensing

PointCheck has no `LICENSE` file (all-rights-reserved by default). Since both projects share the same author, this isn't a legal blocker — just add an attribution/license header on any ported module for cleanliness.

## Payoff (if Phase 1 is built)

More issues actually caught, for free — no added latency or cost, since it rides on the browser page already open for axe scoring. Closes part of the real gap between "validated" (meaning axe-validated, ~30-40% of WCAG) and what customers likely assume the claim means. The visible score won't change immediately, since Phase 1 findings are reported as a separate non-blocking section rather than folded into the pass/fail gate — that's deliberate, to avoid false convergence regressions, but worth knowing if the goal is "raise the number" rather than "catch more real problems."

## Verification (for whenever Phase 1 is actually implemented)

Run the ported checks against happypdf's existing `benchmark/` documents and confirm:
1. No false positives against docs that already score 100% on axe.
2. Genuine new findings on docs with known issues (cross-check against PointCheck's own `wcag_tool_comparison.csv` categories).
3. The axe-regression guard and 95% convergence threshold still behave correctly with the new sibling `pointcheck` block present but not feeding into `violations`/`critical_serious`.

Per this project's standing deploy rule, any backend change goes through `modal deploy --env staging` + `regression_suite.py` before prod.
