.PHONY: help lint format test validate clean dev-backend dev-frontend docker-build docker-up docker-down

help:
	@echo "Available commands:"
	@echo "  make lint            - Lint Python and TypeScript code"
	@echo "  make format          - Auto-format Python and TypeScript code"
	@echo "  make test            - Run Python tests"
	@echo "  make validate        - Syntax-check the Modal deployment entrypoints"
	@echo "  make clean           - Remove build artifacts"
	@echo "  make dev-backend     - Run the API locally with uvicorn --reload (:8000)"
	@echo "  make dev-frontend    - Run the frontend dev server locally (:5173)"
	@echo "  make docker-build    - Build the backend + frontend Docker images"
	@echo "  make docker-up       - Run the full self-hosted stack via Docker Compose"
	@echo "  make docker-down     - Stop the Docker Compose stack"

lint:
	ruff check src/ api/ tests/ modal/
	cd frontend && npm run lint

format:
	black src/ api/ tests/ modal/
	cd frontend && npm run format

test:
	pytest tests/ -v

validate:
	python -m py_compile src/modal_api.py modal/modal_alttext_adapter.py modal/modal_olmo_wcag.py modal/modal_olmocr_final.py

clean:
	rm -rf build/ dist/ *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
	rm -rf .ruff_cache

dev-backend:
	cd api && uvicorn main:app --reload --host 0.0.0.0 --port 8000

dev-frontend:
	cd frontend && npm run dev

docker-build:
	docker compose build

docker-up:
	docker compose up --build

docker-down:
	docker compose down
