# Deployment & Local Setup

This guide covers running the happypdf vertical slice on your own machine. The pipeline calls GPU functions that are already deployed on Modal, so you need a Modal account but no local GPU.

## Prerequisites

- Python 3.11+
- Node.js 18+ (for the `axe-core` npm package)
- A [Modal](https://modal.com) account with the `olmocr` and `pdfaccess-alttext` apps deployed

## 1. Modal Credentials

The orchestrator authenticates to Modal through environment variables. Create a token in the Modal dashboard (Settings -> API Tokens) and export it:

```bash
export MODAL_TOKEN_ID=ak-xxxxxxxxxxxxxxxx
export MODAL_TOKEN_SECRET=as-xxxxxxxxxxxxxxxx
```

Alternatively, run `modal token new` once to write credentials to `~/.modal.toml` (which is gitignored — never commit it).

The GPU functions must be deployed under your account:

```bash
modal deploy modal/modal_olmocr_final.py     # deploys app "olmocr"
modal deploy modal/modal_alttext_adapter.py  # deploys app "pdfaccess-alttext"
```

These are the same reference implementations kept in `modal/`. The orchestrator looks them up by name with `modal.Function.from_name(...)`, so they must exist as **deployed** (not ephemeral `modal run`) apps.

## 2. Install Dependencies

```bash
pip install -r requirements.txt
npm install
playwright install chromium
```

- `pip install -r requirements.txt` installs PyMuPDF, Playwright, and the Modal client (pinned to tested versions).
- `npm install` pulls `axe-core` into `node_modules/`.
- `playwright install chromium` downloads the headless browser axe-core runs inside.

## 3. Run the Vertical Slice

```bash
python src/build_syllabus_slice.py
```

What happens:

1. Loads `benchmark/syllabus_NOTaccessible.pdf`.
2. Calls the deployed olmOCR function -> markdown (cached to `output/syllabus_olmocr.md`).
3. Extracts embedded images with PyMuPDF -> `output/syllabus_images/`.
4. Calls the deployed Qwen2-VL function for alt text (cached to `output/syllabus_alt.json`).
5. Builds semantic HTML5.
6. Runs axe-core in headless Chromium.
7. Writes results to `output/`.

Pass `--no-cache` to force fresh olmOCR and alt-text calls:

```bash
python src/build_syllabus_slice.py --no-cache
```

## 4. Interpreting the Output

| File | What it tells you |
|------|-------------------|
| `output/syllabus_scored.html` | The remediated HTML. The comment block at the top shows the axe score, severity breakdown, violation rules, and any duplicate-ID artifacts. |
| `output/syllabus_axe_baseline.json` | The raw, verbatim axe-core result (`violations`, `passes`, `incomplete`, `testEngine`). Use this for programmatic checks. |
| stdout logs | Timestamped per-stage timing plus the final `score / violations / passes / images` summary. |

A score of 100% on this benchmark means the *output* HTML has zero axe violations — the success case, since the *input* PDF is deliberately inaccessible. Remember that axe covers only part of WCAG; see [ARCHITECTURE.md](ARCHITECTURE.md#score-vs-hard-gates).

## Troubleshooting

- **Modal timeout / function not found.** Confirm the apps are deployed under your account: `modal app list` should show `olmocr` and `pdfaccess-alttext` in the `deployed` state. An app left in `stopped` state was run ephemerally with `modal run` and cannot be looked up by name — redeploy it with `modal deploy`.
- **Long first run.** The first call pays olmOCR's cold start (~3-4 min to start the vLLM server on a cold H100) plus Qwen2-VL cold start (~1-1.5 min). Subsequent runs use the disk cache and finish in seconds. Use `--no-cache` only when you actually need fresh extraction.
- **`axe-core not found`.** The orchestrator looks for `node_modules/axe-core/axe.min.js` at the repo root first, then a shared parent install. Run `npm install` in the repo root if it is missing.
- **Playwright headless issues.** If Chromium fails to launch, re-run `playwright install chromium`. On Linux you may also need `playwright install-deps`.
- **GPU memory / OOM on Modal.** The deployed functions are sized for a single document at a time. Do not fan out concurrent calls against a single GPU container; batch sequentially.
