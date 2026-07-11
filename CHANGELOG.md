# Changelog

This project doesn't use formal semantic versioning yet — entries are grouped by date. See [GitHub Releases](https://github.com/BrendanWorks/happypdf/releases) for downloadable demo assets (currently [v1.0](https://github.com/BrendanWorks/happypdf/releases/tag/v1.0)).

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
