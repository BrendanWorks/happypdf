# Containerizes the happypdf orchestrator (api/ + src/): FastAPI backend,
# Playwright/axe-core for scoring, and the reviewer/judge pipeline logic.
#
# This does NOT bundle GPU inference. olmOCR extraction and Qwen2-VL alt-text
# generation are remote calls to Modal GPU functions (modal.Function.from_name),
# and the reviewer/judge step calls Anthropic/OpenAI/Google over the network.
# Self-hosting with this image still requires a Modal account (for the GPU
# functions — see docs/SETUP.md) and reviewer API keys; it is not an
# air-gapped deployment.
FROM mcr.microsoft.com/playwright/python:v1.62.0-noble

WORKDIR /app

# axe-core is an npm package fetched at the repo root (path_resolver.py looks
# for node_modules/axe-core/axe.min.js there) — needs Node.
RUN apt-get update && apt-get install -y --no-install-recommends nodejs npm \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt package.json package-lock.json ./
RUN pip install --no-cache-dir -r requirements.txt
RUN npm install --legacy-peer-deps
RUN python -m playwright install chromium

COPY src/ ./src/
COPY api/ ./api/

EXPOSE 8000
WORKDIR /app/api
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
