.PHONY: help lint format test validate clean

help:
	@echo "Available commands:"
	@echo "  make lint       - Lint Python and TypeScript code"
	@echo "  make format     - Auto-format Python and TypeScript code"
	@echo "  make test       - Run Python tests"
	@echo "  make validate   - Syntax-check the Modal deployment entrypoints"
	@echo "  make clean      - Remove build artifacts"

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
