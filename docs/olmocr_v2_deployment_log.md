# olmOCR-2 (v2) staging deployment log

Record of the olmOCR v1 → olmOCR-2-7B-1025-FP8 extraction upgrade. Staging only —
production (`olmocr`) is untouched by this work.

## GPU & resource notes

Modal is **serverless**: a deployed app reserves **no GPU while idle** and scales
to zero. GPU is provisioned per-invocation, so running `olmocr` (v1) and
`olmocr-v2` side by side costs nothing at rest and cannot starve each other. The
"pause other apps to free a GPU" step from the task brief does not apply to this
platform — there is nothing to free. Confirmed below: every deployed app is at
`Tasks: 0`.

The olmOCR-2 **FP8** weights need ~16–18 GB VRAM and fit on the H100 the function
already requests (`gpu="H100"`), so no GPU-type change was needed.

## Before (captured prior to deploying olmocr-v2)

`modal app list` — all apps idle (`Tasks: 0`), including production `olmocr`
(`ap-wDsDrIAcF2NsBUkuK63yVb`, deployed 2026-06-19). No `olmocr-v2` app existed yet.

`modal volume list`:

```
molmo-cache       2026-05-21   brendanworks
molmo-hf-cache    2026-05-18   brendanworks
molmo2-er-cache   2026-05-06   brendanworks
```

(No olmocr volume — the extraction image downloads the model at runtime; nothing
persistent to migrate.)

## Change

- New file `modal/modal_olmocr_v2.py`, Modal app **`olmocr-v2`**.
- Pins `olmocr>=0.4.0` (production installs it unpinned).
- Passes explicit `--model allenai/olmOCR-2-7B-1025-FP8`. Production passes no
  `--model` and therefore uses the olmocr CLI default `allenai/olmOCR-7B-0725-FP8`
  (olmOCR **v1**) — the implicit default this upgrade replaces.
- Production app `olmocr` and the pipeline's `Function.from_name("olmocr", ...)`
  lookup are unchanged.

## After

**Deploy:** `modal deploy modal/modal_olmocr_v2.py` → app **`olmocr-v2`** created
(`ap-euFEoPhyz37yNvawmR9e0O`), image build 225s. `modal app list` afterward shows
both apps `deployed` and `Tasks: 0`:

```
ap-wDsDrIAcF2NsBUkuK63yVb   olmocr      deployed   0   2026-06-19   (production, v1 — unchanged)
ap-euFEoPhyz37yNvawmR9e0O   olmocr-v2   deployed   0   2026-07-12   (staging, olmOCR-2-FP8 — new)
```

**Comparison run** (`python scripts/compare_olmocr_v1_v2.py`, IRS Schedule C):

- Health check passed (both functions resolved).
- Staging v2 reported model `allenai/olmOCR-2-7B-1025-FP8` ✓ (259s cold H100).
- Production v1 reported no model — i.e. the implicit CLI default, confirming prod
  runs olmOCR **v1** as suspected (248s cold H100).

Metrics (HTML `<table>`/`<tr>` counted; olmOCR emits HTML tables, not pipe tables):

| metric | v1 (prod) | v2 (staging) | Δ |
|---|---|---|---|
| chars | 10077 | 7870 | −2207 |
| headings | 0 | 0 | 0 |
| tables | 2 | 2 | 0 |
| table_rows | 35 | 35 | 0 |
| checkbox_glyphs | 11 | 24 | **+13** |
| math_markers | 0 | 0 | 0 |

**Reading of results.** On this form the two are structurally **equivalent**:
identical HTML table reconstruction (2 tables, 35 rows), all Parts I–V and every
line field captured by both, no content loss either way. v2's measurable win is
**checkbox fidelity** — it renders proper `☐` glyphs consistently on every page
(24 vs 11), where v1 degrades to ASCII `[ ]` on later pages. v1's extra ~2.2k
chars are dotted-leader/dash filler, not additional content. The larger olmOCR-2
table/math gains would show on documents with dense numeric tables or equations,
which this form's field layout doesn't heavily exercise.

**Recommendation.** The primary value delivered is the **correctness/robustness
fix** (explicit model pin, no silent drift on the olmocr default) plus cleaner
checkbox output — not a dramatic accuracy jump on this particular PDF. Safe to
promote when ready; consider one more comparison on a math/table-dense document
(e.g. an academic paper) before cutover if a bigger quality delta is expected.

Raw outputs and the machine-generated report are under `output/` (gitignored):
`irs_schedule_c_v1_olmocr.md`, `irs_schedule_c_v2_olmocr2.md`,
`olmocr_v1_v2_comparison_*.log`. Re-score them for free (no GPU) with:
`python scripts/compare_olmocr_v1_v2.py --score-files output/irs_schedule_c_v1_olmocr.md output/irs_schedule_c_v2_olmocr2.md`

**Production impact: none.** The pipeline still resolves `Function.from_name("olmocr", ...)`;
`olmocr-v2` is not referenced by any production code path.
