# happypdf Benchmark — LIVE reviewers across document types

Full pipeline per document: cached olmOCR markdown → semantic HTML → multi-round loop (judge → applicator → preservation gate → axe rescore). Reviews are live OLMo (Modal) + Gemini (google-genai) + GPT (openai), called in parallel.

**Note on violations:** the HTML generator emits clean semantic HTML5, so every document starts at **0 axe violations**. The loop's measurable effect is the **passes** count climbing as ARIA is added — and only where there is structure to enhance. The cross-document signal is therefore structure-driven remediation, not violation-fixing.

| Document | Type | Baseline (viol / passes) | Round 1 (patches → passes) | Round 2 | Round 3 | Final passes | Stop | Time (s) |
|---|---|---|---|---|---|---|---|---|
| syllabus | clean, already accessible | 0 / 23 | 3 → 28p | 0 → 28p | — | 28 | converged | 117.5 |
| irs_schedule_c | dense tax form | 0 / 23 | 1 → 28p | 1 → 28p | 0 → 28p | 28 | converged | 145.04 |
| navy_bulletin | OCR'd historical scan, prose | 0 / 17 | 1 → 21p | 1 → 22p | 0 → 22p | 22 | converged | 383.93 |

All documents end with **0 violations** and a content-preservation gate that **passed every round** (no text loss, no dropped tables/images, no heading skips). Convergence = score ≥ 95% AND hard gates pass AND a round produced no new patches.
