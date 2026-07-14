# Changelog

This project doesn't use formal semantic versioning yet — entries are grouped by date. See [GitHub Releases](https://github.com/BrendanWorks/happypdf/releases) for downloadable demo assets — latest is [v1.2](https://github.com/BrendanWorks/happypdf/releases/tag/v1.2), demo videos are attached to [v1.0](https://github.com/BrendanWorks/happypdf/releases/tag/v1.0).

## v1.2.1 — 2026-07-13 — Security hardening & stability maintenance

Security (from a full code review of the API + pipeline):

- **BYOK keys no longer touch the process environment.** The old mechanism swapped user keys into `os.environ` per job and restored them afterward; with `@modal.concurrent` allowing overlapping jobs, one user's key could be used (and billed) by another user's concurrent job, and the restore could race. Keys are now passed explicitly down the call chain (`reviewers.make_live_provider(...)` → `run_loop(byok=...)` → judge → API-client constructors). No environment mutation, no restore step.
- **Fixed three HTML-injection paths** reachable from PDF content or reviewer output: the table-recovery path blanket-unescaped entities (document text like `<script>` became live markup — now allowlist-sanitized via lxml), markdown image conversion didn't escape `src`/surrounding text and had an escape-order bug that double-escaped quotes in alt text (rewritten to escape everything and reject `javascript:`/non-image `data:` URLs), and the downloadable report interpolated the uploaded filename and enhancement values unescaped (every manifest-derived field now passes `html.escape`). Job HTML is additionally served with a `Content-Security-Policy: sandbox` header.
- **The OLMo reviewer GPU endpoint now requires a bearer token** (shared via the new `olmo-reviewer-auth` Modal secret). It was previously a publicly callable A10G with its URL hardcoded in a public repo.
- **Upload guardrails:** 25 MB size cap and `%PDF-` magic-byte sniff before any GPU time is spent; the daily rate limit moved from an in-process counter (reset to zero on every container recycle, despite comments claiming otherwise) to a Modal-Dict-backed thread-safe counter. Path parameters (job id, demo name) are strictly validated before touching the filesystem or `Content-Disposition` headers, closing an encoded-slash path traversal in the demo snapshot loader.

Stability:

- BYOK key validation no longer blocks the event loop (it stalled every concurrent poll while a provider call hung); a setup failure in the live worker now marks the job as errored instead of leaving a stuck spinner; a 60s heartbeat keeps long extraction stages (cold-start olmOCR on a big PDF) from being falsely reported as interrupted by the 5-minute staleness check.
- **Preservation gate fixes:** the gate now compares every round against the *original* baseline, so the 95% text-coverage allowance can't compound across rounds (three rounds could previously lose ~14% legally); the heading-order check now fails only on skips a round *introduced* — a document whose baseline already contained h1→h3 no longer fails every round for a defect the patches didn't cause.
- Judge/applicator no longer write shared audit files at fixed paths during live jobs (concurrent jobs clobbered each other); the audit travels in the return value, and the CLI paths still write files.

Quality & performance:

- **Reviewers now see the document, not base64.** Embedded data-URI images (often hundreds of KB each) are stripped to placeholders before review, and Gemini/GPT context budgets raised from 8k chars (an OLMo constraint) to 60k — previously most of any image-heavy document was never reviewed at all.
- **The judge's alt-text rewrites now attach the actual image** to Claude/GPT-4o vision calls instead of asking the model to describe an image it couldn't see.
- One Chromium instance per job instead of a fresh launch per axe run (5+ launches saved per job); alt-text generation runs 3-wide in parallel (bounded, so a 25-image document doesn't trigger 25 GPU cold starts); the baseline is no longer axe-scored twice; job polls no longer serialize behind a global lock over network round-trips; frontend poll interval relaxed to 1.5s and blob URLs are revoked.
- Staging deploys supported: `HAPPYPDF_APP_NAME=happypdf-api-staging modal deploy src/modal_api.py` creates a parallel app with its own isolated job/rate Dicts.
- 33 new tests (67 total) covering the injection defenses, BYOK plumbing, rate limiter, gate fixes, and API guardrails.

## v1.2 — 2026-07-12 — olmOCR-2 extraction upgrade

- Upgraded PDF extraction to **olmOCR-2-7B-1025-FP8** and promoted it to production. The previous deployment ran the olmocr CLI with no `--model`, silently using the CLI default (`olmOCR-7B-0725-FP8`, i.e. olmOCR v1); the model could drift with the unpinned package. Extraction now pins `olmocr>=0.4.0` and passes an explicit `--model`, so it can no longer change out from under us.
- Staged safely: deployed olmOCR-2 as a separate Modal app (`olmocr-v2`) alongside the v1 app, validated it, then repointed production by a single constant in `src/build_syllabus_slice.py`. The v1 app stays deployed as a one-line-revert fallback.
- Validated on three documents before cutover (IRS Schedule C form, a neuroscience prose+figure paper, and a 14-page equation-dense math paper). Result: olmOCR-2 is **quality-equivalent** to v1 on these inputs — the math paper was a dead heat (identical LaTeX math extraction), the form slightly favored v2 (cleaner checkbox glyphs), the prose doc slightly favored v1. The dependable win is the correctness/pinning fix, not an accuracy jump. Full comparison in [`docs/olmocr_v2_deployment_log.md`](docs/olmocr_v2_deployment_log.md).
- Added `scripts/compare_olmocr_v1_v2.py`, a health-checked v1-vs-v2 comparison harness with an offline re-scoring mode, and a README "Extraction Model" section documenting staging/production/revert.
- Fixed a latent container crash-loop exposed on this deploy: a prior path-portability refactor imported `path_resolver` at `modal_api.py` module top level, which resolves at deploy time but not inside the Modal container (crash-loop `ModuleNotFoundError: path_resolver`). Guarded so it only runs at deploy time. Verified the live pipeline end-to-end after the fix (real PDF → olmOCR-2 extraction → 100% axe baseline).

## 2026-07-11 — Docker self-hosting, repo polish

- Added Docker self-hosting: a backend Dockerfile (orchestrator, Playwright, axe-core) and a multi-stage frontend Dockerfile, tied together with `docker-compose.yml`. Scoped honestly in the docs — this containerizes the orchestration layer, not the pipeline's GPU inference, which still runs as remote Modal calls in every deployment mode.
- Verified it for real: built and ran both containers, confirmed the frontend correctly bakes in the backend URL, then submitted an actual PDF to the Dockerized backend with real credentials and let the full pipeline run to completion (real olmOCR extraction, all three live reviewers, real Claude judge patches, 100% final axe score).
- Added a `docker-build` CI job — caught two real bugs on its first two runs: the frontend's final stage was silently fetching a different Vite version via `npx` instead of the one actually pinned, and the root `package-lock.json` had never been committed at all (caught by the exact same blanket-gitignore bug pattern as `.prettierrc.json` earlier in the day). Verified the fix against a genuine fresh clone before pushing.
- Added `SECURITY.md`, `CHANGELOG.md`, and GitHub issue/PR templates.
- Added Dependabot config (pip, both npm roots, GitHub Actions, both Dockerfiles) and repository Topics for discoverability.
- Expanded the Makefile (`dev-backend`, `dev-frontend`, `docker-build`, `docker-up`, `docker-down`) and updated `CONTRIBUTING.md` to document both the local and Docker setup paths.

## 2026-07-11 — Launch validation

- Audited every claim in the README against reality and corrected what didn't hold up: BYOK privacy copy that said keys "never touch the browser" (backwards — that's how BYOK works), a benchmark average that didn't match its own table, a "self-hosted OLMo-only mode" claimed in docs that doesn't exist in code.
- Ran the 4 benchmark documents that had zero generated evidence through the real live pipeline; all 13 documents are now backed by real committed output. Recomputed every aggregate stat from the actual data.
- Verified BYOK end-to-end with a real Anthropic key: poisoned the server's default credential in-process, confirmed the job only succeeded because the explicit override took effect, confirmed the environment was correctly restored afterward.
- Verified self-hosting setup via a genuine fresh-machine test (isolated VM, real `git clone` from GitHub, no host state) — found and fixed a missing `npm install` step in the Quick Start that broke both `pytest` and `src/benchmark.py` on a clean checkout.
- Added Google Analytics with a privacy disclosure in the Security section and non-PII custom event tracking (upload started, conversion result, BYOK usage — never filenames or key values).
- Added a real social card image for link previews (previously showed bolt.new's own promo, a leftover from the original scaffold).
- Added `LICENSE` (MIT, already claimed in the README but missing as a file), linked `CONTRIBUTING.md` from the README, added a real contact path.

## 2026-07-10 — CI/CD and repo cleanup

- Added GitHub Actions CI: ruff, black, pytest, ESLint, TypeScript typecheck, and a Modal-entrypoint syntax check.
- Fixed the CI pipeline's first real run: `path_resolver.py` needs a root-level `npm install` for axe-core that neither workflow installed, and `tests/test_gate_edges.py` wasn't actually a pytest test but matched pytest's collection glob and broke on a missing transient file — renamed it out of the glob.
- Reorganized repo structure: moved internal handoff/diagnostic docs and the architecture diagram into `docs/`, archived a superseded bolt.new scaffold export, added `docs/README.md` and `CONTRIBUTING.md`.

## 2026-06-23 to 2026-07-09 — Core pipeline and BYOK

- Built the vertical slice: PDF → olmOCR extraction → semantic HTML → axe-core scoring.
- Added the multi-round remediation loop: Claude judge for LLM-safe fixes, a content-preservation gate (text coverage, image count, heading order, table structure), and a deterministic patch applicator.
- Wired live peer reviewers (OLMo via Modal, Gemini, GPT) running in parallel each round.
- Implemented BYOK (Bring Your Own Key) support with sanitized error handling.
- Deployed the live API to Modal and wired the frontend demo to it; added Netlify static hosting with client-side snapshot replay for the free demo path.
- Added the benchmark suite across document types, manifest/report JSON+HTML downloads, and audit-trail export.
- Added `pytest` testing infrastructure and made all local file paths portable across machines.
