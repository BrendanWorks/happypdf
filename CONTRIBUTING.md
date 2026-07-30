# Contributing to happypdf

Thanks for your interest! Here's how to get started.

## Development Setup

**Option A, locally:**
1. Clone the repo
2. Follow the setup instructions in [`docs/SETUP.md`](docs/SETUP.md)
3. `make dev-backend` and `make dev-frontend` (in separate terminals) to run both halves with live reload
4. Run `make lint` and `make test` to verify everything works

**Option B, Docker:**
1. `cp .env.example .env` and fill in your Modal + provider credentials
2. `make docker-up` (or `docker compose up --build`): runs the full stack in containers
3. See the [Run Locally with Docker](README.md#run-locally-with-docker) section in the README for what this does and doesn't cover

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
