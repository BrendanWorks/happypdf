# olmOCR-2 (v2) staging deployment log

Record of the olmOCR v1 → olmOCR-2-7B-1025-FP8 extraction upgrade. Staging only
production (`olmocr`) is untouched by this work.

## GPU & resource notes

Modal is **serverless**: a deployed app reserves **no GPU while idle** and scales
to zero. GPU is provisioned per-invocation, so running `olmocr` (v1) and
`olmocr-v2` side by side costs nothing at rest and cannot starve each other. The
"pause other apps to free a GPU" step from the task brief does not apply to this
platform; there is nothing to free. Confirmed below: every deployed app is at
`Tasks: 0`.

The olmOCR-2 **FP8** weights need ~16–18 GB VRAM and fit on the H100 the function
already requests (`gpu="H100"`), so no GPU-type change was needed.

## Before (captured prior to deploying olmocr-v2)

`modal app list`: all apps idle (`Tasks: 0`), including production `olmocr`
(`ap-wDsDrIAcF2NsBUkuK63yVb`, deployed 2026-06-19). No `olmocr-v2` app existed yet.

`modal volume list`:

```
molmo-cache       2026-05-21   brendanworks
molmo-hf-cache    2026-05-18   brendanworks
molmo2-er-cache   2026-05-06   brendanworks
```

(No olmocr volume: the extraction image downloads the model at runtime; nothing
persistent to migrate.)

## Change

- New file `modal/modal_olmocr_v2.py`, Modal app **`olmocr-v2`**.
- Pins `olmocr>=0.4.0` (production installs it unpinned).
- Passes explicit `--model allenai/olmOCR-2-7B-1025-FP8`. Production passes no
  `--model` and therefore uses the olmocr CLI default `allenai/olmOCR-7B-0725-FP8`
  (olmOCR **v1**): the implicit default this upgrade replaces.
- Production app `olmocr` and the pipeline's `Function.from_name("olmocr", ...)`
  lookup are unchanged.

## After

**Deploy:** `modal deploy modal/modal_olmocr_v2.py` → app **`olmocr-v2`** created
(`ap-euFEoPhyz37yNvawmR9e0O`), image build 225s. `modal app list` afterward shows
both apps `deployed` and `Tasks: 0`:

```
ap-wDsDrIAcF2NsBUkuK63yVb   olmocr      deployed   0   2026-06-19   (production, v1: unchanged)
ap-euFEoPhyz37yNvawmR9e0O   olmocr-v2   deployed   0   2026-07-12   (staging, olmOCR-2-FP8: new)
```

**Comparison run** (`python scripts/compare_olmocr_v1_v2.py`, IRS Schedule C):

- Health check passed (both functions resolved).
- Staging v2 reported model `allenai/olmOCR-2-7B-1025-FP8` ✓ (259s cold H100).
- Production v1 reported no model, i.e. the implicit CLI default, confirming prod
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
**checkbox fidelity**: it renders proper `☐` glyphs consistently on every page
(24 vs 11), where v1 degrades to ASCII `[ ]` on later pages. v1's extra ~2.2k
chars are dotted-leader/dash filler, not additional content. The larger olmOCR-2
table/math gains would show on documents with dense numeric tables or equations,
which this form's field layout doesn't heavily exercise.

**Recommendation.** The primary value delivered is the **correctness/robustness
fix** (explicit model pin, no silent drift on the olmocr default) plus cleaner
checkbox output, not a dramatic accuracy jump on this particular PDF. Safe to
promote when ready; consider one more comparison on a math/table-dense document
(e.g. an academic paper) before cutover if a bigger quality delta is expected.

Raw outputs and the machine-generated report are under `output/` (gitignored):
`irs_schedule_c_v1_olmocr.md`, `irs_schedule_c_v2_olmocr2.md`,
`olmocr_v1_v2_comparison_*.log`. Re-score them for free (no GPU) with:
`python scripts/compare_olmocr_v1_v2.py --score-files output/irs_schedule_c_v1_olmocr.md output/irs_schedule_c_v2_olmocr2.md`

**Production impact: none.** The pipeline still resolves `Function.from_name("olmocr", ...)`;
`olmocr-v2` is not referenced by any production code path.

## Second comparison, somatosensory.pdf (neuroscience text)

Run to exercise a science document (prose + one table + figures). v2 reported
`allenai/olmOCR-2-7B-1025-FP8` (204s); v1 the implicit default (192s).

| metric | v1 (prod) | v2 (staging) | Δ |
|---|---|---|---|
| chars | 7218 | 7118 | −100 |
| tables | 1 | 1 | 0 |
| table_rows | 3 | 3 | 0 |
| images referenced | 6 | 6 | 0 |
| math_markers | 0 | 0 | 0 |

**This one favors v1, not v2.** No equations in the doc (so the expected
olmOCR-2 math advantage wasn't exercised), and inspection of the markdown shows
two accessibility-relevant regressions in v2:

1. **Italic emphasis dropped.** v1 preserves `<i>…</i>` on introduced terms
   (*first pain*, *cutaneous pricking pain*, *second/deep pain*, *intrafusal /
   extrafusal fibers*); v2 renders them as plain text. Consistent across every
   emphasized term, looks systematic, not random.
2. **Thinner figure alt text.** For the skin-receptor diagram, v1's alt text
   lists 7 receptor types plus the glabrous-vs-hairy-skin distinction; v2's
   lists 5 and omits the skin-type distinction.

Both captured the same prose, table, and 6 figure references; no text content
loss either way.

**Caveat.** Single run, single doc; olmOCR is a VLM with stochastic decoding, so
the alt-text wording difference could be run-to-run variance. The italics drop is
more likely a real formatting behavior change between model versions (it's
uniform across the document). Worth a re-run and a check against a genuinely
equation-heavy paper before concluding.

## Third comparison. Pascal2606.30772v1.pdf (14-page algebraic geometry paper)

The equation-dense test recommended above: a math paper (Pascal constructions,
Burkhardt quartic, projective four-space) full of inline and display LaTeX. v2
reported `allenai/olmOCR-2-7B-1025-FP8` (202s); v1 the implicit default (200s).

| metric | v1 (prod) | v2 (staging) | Δ |
|---|---|---|---|
| chars | 30441 | 30407 | −34 |
| lines | 747 | 726 | −21 |
| tables | 1 | 1 | 0 |
| table_rows | 4 | 4 | 0 |
| math_markers | 686 | 686 | **0** |

**Essentially equivalent, and this is the fair math test.** Both emit the same
686 LaTeX math markers, and reading the equations confirms both extract the math
**accurately**: same variables, same display environments, same structure.
Whole-document counts of the small stylistic differences are all noise-level:
italic `*…*` spans 22 vs 21, QED symbols identical, spaced `=` in math 204 vs 201.
A few local differences exist (e.g. `k = 5` vs `k=5`, `\begin{array}{ll}` with `&`
alignment vs `{l}` inline, one `*Proof.*` vs `Proof.`) but they do not accumulate
into a systematic quality gap in either direction.

Notably, this **weakens the somatosensory "v2 drops emphasis" hypothesis**: here
the two are at parity on italics (22 vs 21), so that earlier difference is better
explained by run-to-run VLM variance than a systematic v2 regression.

## Overall read across all three documents

| Document | Type | Result |
|---|---|---|
| IRS Schedule C | dense tax form | wash; v2 slightly cleaner checkboxes (24 vs 11 glyphs) |
| somatosensory | neuroscience prose + figures | leaned v1 (richer alt text, more emphasis) — but small sample |
| Pascal 2606.30772 | equation-dense math paper | equivalent; math accurate in both, differences noise-level |

Across a form, a prose+figure doc, and a genuinely math-heavy paper, **olmOCR-2
does not show a measurable quality advantage over v1 on happypdf's inputs**, and
the math case, where it was most expected to win, came out a dead heat. The
differences seen are at the level of VLM run-to-run variance.

The dependable, non-stochastic value of this change is therefore the
**correctness/robustness fix**: pinning `olmocr>=0.4.0` and an explicit
`--model`, so extraction no longer rides the olmocr CLI's shifting default, not
an output-quality upgrade. That is still worth shipping. **Recommendation:**
promote when convenient for the robustness win, but don't expect an accuracy jump;
there's no quality reason to rush the cutover, and v1 stays deployed as a
zero-cost fallback.

Re-score any saved outputs for free (no GPU), e.g.:
`python scripts/compare_olmocr_v1_v2.py --score-files output/Pascal2606.30772v1_v1_olmocr.md output/Pascal2606.30772v1_v2_olmocr2.md`
