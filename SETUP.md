# HappyPDF Local Setup Guide

This document explains the project structure and how to set up happypdf for local development or deployment.

## Project Structure

```
happypdf/
├── src/                           # Core pipeline code
│   ├── path_resolver.py           # Portable path resolution (imports this!)
│   ├── modal_api.py               # Modal FastAPI endpoint
│   ├── loop.py                    # Multi-round remediation loop
│   ├── build_syllabus_slice.py    # Pipeline orchestrator
│   ├── report_generator.py        # HTML report generation
│   ├── judge.py                   # LLM-based patch evaluation
│   ├── applicator.py              # Safe patch application
│   ├── gate.py                    # Preservation gate validation
│   ├── reviewers.py               # Multi-model reviewer integration
│   └── ...                        # Other pipeline modules
│
├── api/                           # Backend job management
│   ├── main.py                    # FastAPI endpoints (manifest, report, etc)
│   └── snapshots/                 # Pre-computed demo snapshots
│       ├── syllabus.json
│       ├── irs_schedule_c.json
│       └── navy_bulletin.json
│
├── frontend/                      # React/Next.js web UI
│   ├── src/
│   │   └── App.tsx
│   └── package.json
│
├── benchmark/                     # Test PDFs (for local testing)
│   └── syllabus_NOTaccessible.pdf
│
├── output/                        # Generated outputs (HTML, JSON, cache)
│   ├── syllabus_scored.html
│   ├── syllabus_final.html
│   └── ...
│
├── videos/                        # Demo GIFs and videos
│   ├── happypdf-demo.gif
│   ├── happypdf-demo.mp4
│   └── pipeline-demo.gif
│
├── node_modules/                  # Dependencies (created by npm install)
│   └── axe-core/
│       └── axe.min.js
│
└── README.md
```

## Prerequisites

- **Python 3.10+**
- **Node.js 18+**
- **pip** and **npm**
- **Playwright** (browser automation for axe-core)

## Local Setup

### 1. Clone the Repository

```bash
git clone https://github.com/BrendanWorks/happypdf.git
cd happypdf
```

### 2. Install Python Dependencies

```bash
# Create a virtual environment (recommended)
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers (needed for axe-core)
python -m playwright install chromium
```

### 3. Install Node Dependencies (axe-core)

```bash
# Install axe-core in the project root
npm install --legacy-peer-deps axe-core

# Verify axe-core is accessible
ls node_modules/axe-core/axe.min.js
```

### 4. Set Up Frontend (Optional, for local dev)

```bash
cd frontend
npm install
npm run dev  # Runs on http://localhost:5173
```

## Path Resolution

All hardcoded paths have been removed. The project uses **portable path resolution** via `src/path_resolver.py`:

### Supported Environments

1. **Local development** (macOS/Linux/Windows)
   - Paths resolved relative to `__file__` using `Path(__file__).resolve().parent`
   - axe-core found via: `node_modules/axe-core/axe.min.js` (repo root)

2. **Docker/Container**
   - Paths work from any mount point
   - axe-core can be mounted or installed in `/node_modules/axe-core/axe.min.js`

3. **Environment overrides** (for CI/CD)
   - Set `AXE_CORE_PATH=/path/to/axe.min.js` to override axe-core location
   - All other paths auto-resolve from `__file__` location

### How It Works

When Python imports `src/modal_api.py`, `build_syllabus_slice.py`, or `loop.py`:

```python
from path_resolver import REPO, AXE_LOCAL, validate_paths
validate_paths()  # Fails immediately if paths don't exist
```

This ensures:
- ✅ No hardcoded user paths
- ✅ Works after any git clone
- ✅ Works on any machine (Mac, Linux, Windows, Docker)
- ✅ Fails fast with clear error messages if setup is incomplete

## Running Locally

### Run the Remediation Pipeline (Standalone)

```bash
# Requires baseline HTML in output/syllabus_scored.html
python src/loop.py
```

### Deploy to Modal (Production)

```bash
# Requires Modal account and MODAL_TOKEN_ID / MODAL_TOKEN_SECRET
modal deploy src/modal_api.py
```

### Run Frontend Dev Server

```bash
cd frontend
npm run dev
```

Then open http://localhost:5173

## Environment Variables

Optional overrides (all have sensible defaults):

```bash
# Override axe-core location (default: node_modules/axe-core/axe.min.js)
export AXE_CORE_PATH=/custom/path/to/axe.min.js

# Modal deployment (if not in ~/.config/modal)
export MODAL_TOKEN_ID=your_token_id
export MODAL_TOKEN_SECRET=your_token_secret

# API keys for live PDF processing
export ANTHROPIC_API_KEY=sk-ant-...
export OPENAI_API_KEY=sk-...
export GOOGLE_API_KEY=...
```

## Troubleshooting

### Error: "axe-core not found"

**Solution:**

```bash
# Install axe-core in repo root
npm install --legacy-peer-deps axe-core
```

Or manually set it:

```bash
export AXE_CORE_PATH=/path/to/your/axe.min.js
```

### Error: "Project root not found"

This shouldn't happen if you're running from within the cloned repo. But if it does:

```bash
# Ensure you're in the happypdf/ directory
pwd
# Should show: /path/to/happypdf

# Verify src/path_resolver.py exists
ls src/path_resolver.py
```

### Modal Deploy Fails

Verify Modal setup:

```bash
# Check Modal credentials
modal profile

# Should show your token
```

If not configured:

```bash
modal token new
# Follow the prompts
```

## Docker Setup (Optional)

If you prefer containerized deployment:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install Node (for axe-core)
RUN apt-get update && apt-get install -y nodejs npm

# Copy project
COPY happypdf .

# Install Python deps
RUN pip install -r requirements.txt
RUN python -m playwright install chromium

# Install axe-core
RUN npm install --legacy-peer-deps axe-core

# Run pipeline or Modal app
CMD ["python", "src/loop.py"]
# OR: modal deploy src/modal_api.py
```

## Verification Checklist

After setup, verify everything works:

- [ ] `python -c "from src.path_resolver import validate_paths; validate_paths()"` runs without error
- [ ] `ls node_modules/axe-core/axe.min.js` shows the file exists
- [ ] `python src/loop.py` runs (if you have a baseline PDF)
- [ ] `modal deploy src/modal_api.py` succeeds (if you have Modal credentials)

## Next Steps

- Read [README.md](./README.md) for project overview
- Check `src/modal_api.py` for API endpoint documentation
- Review `src/loop.py` for the multi-round remediation loop
- See `CLAUDE.md` in the parent directory for deployment procedures

## Questions?

If paths aren't resolving, check:

1. **Am I in the right directory?** `pwd` should show `.../happypdf`
2. **Do dependencies exist?** `ls node_modules/axe-core/axe.min.js` should succeed
3. **Is Python on the path?** `python --version` should show 3.10+
4. **Are imports correct?** `python -c "import sys; print(sys.path)"` should include `src/`

For more help, see the troubleshooting section above.
