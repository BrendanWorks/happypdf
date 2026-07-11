# Contributing to happypdf

Thanks for your interest! Here's how to get started.

## Development Setup

1. Clone the repo
2. Follow the setup instructions in [`docs/SETUP.md`](docs/SETUP.md)
3. Run `make lint` and `make test` to verify everything works

## Making Changes

1. Create a branch: `git checkout -b feature/your-feature-name`
2. Make your changes
3. Run linting and tests:
   ```bash
   make lint
   make test
   ```
4. Fix any errors and commit
5. Push and open a PR

## Code Style

- Python: Black + ruff (run `make format` to auto-fix)
- TypeScript/React: ESLint + Prettier (`cd frontend && npm run format`)
- All PRs must pass CI checks before merging (see `.github/workflows/`)

## Questions?

Open an issue or check [`docs/`](docs/) for more details.
