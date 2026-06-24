# happypdf Benchmark — remediation loop across document types

Full pipeline per document: cached olmOCR markdown → semantic HTML → multi-round loop (judge → applicator → preservation gate → axe rescore). Reviews are synthesized per document from its real elements.

**Note on violations:** the HTML generator emits clean semantic HTML5, so every document starts at **0 axe violations**. The loop's measurable effect is the **passes** count climbing as ARIA is added — and only where there is structure to enhance. The cross-document signal is therefore structure-driven remediation, not violation-fixing.

| Document | Type | Baseline (viol / passes) | Round 1 (patches → passes) | Round 2 | Round 3 | Final passes | Stop | Time (s) |
|---|---|---|---|---|---|---|---|---|
| syllabus | clean, already accessible | 0 / 23 | 2 → 28p | 1 → 32p | 0 → 32p | 32 | converged | 3.97 |
| irs_schedule_c | dense tax form | 0 / 23 | 1 → 28p | 0 → 28p | — | 28 | converged | 2.92 |
| navy_bulletin | OCR'd historical scan, prose | 0 / 17 | 0 → 17p | — | — | 17 | converged | 2.05 |

All documents end with **0 violations** and a content-preservation gate that **passed every round** (no text loss, no dropped tables/images, no heading skips). Convergence = score ≥ 95% AND hard gates pass AND a round produced no new patches.
