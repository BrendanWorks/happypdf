"""
Portable path resolution for happypdf.

Centralizes all path logic so the project works on any machine without
editing files or setting up symlinks. Uses environment variables and
relative paths from __file__.
"""

import os
import sys
from pathlib import Path


# ── Project structure ──────────────────────────────────────────────────────

def get_project_root() -> Path:
    """Get the happypdf project root (repo root, not src/)."""
    # This file is in happypdf/src/path_resolver.py
    # So parent.parent gets us to happypdf/
    return Path(__file__).resolve().parent.parent


def get_src_dir() -> Path:
    """Get the src/ directory."""
    return get_project_root() / "src"


def get_api_dir() -> Path:
    """Get the api/ directory (snapshots, index, etc)."""
    return get_project_root() / "api"


# ── Dependencies ───────────────────────────────────────────────────────────

def get_axe_core_path() -> Path:
    """
    Resolve path to axe-core/axe.min.js.

    Order of precedence:
    1. AXE_CORE_PATH environment variable (for overrides)
    2. Bundled in repo: happypdf/node_modules/axe-core/axe.min.js
    3. System node_modules: /node_modules/axe-core/axe.min.js
    4. User's home: ~/node_modules/axe-core/axe.min.js

    Raises:
        FileNotFoundError: if no axe-core installation found
    """

    # 1. Environment override
    if env_path := os.environ.get("AXE_CORE_PATH"):
        path = Path(env_path)
        if path.exists():
            return path
        raise FileNotFoundError(
            f"AXE_CORE_PATH environment variable points to non-existent file: {path}"
        )

    # 2. Bundled in repo
    repo_axe = get_project_root() / "node_modules" / "axe-core" / "axe.min.js"
    if repo_axe.exists():
        return repo_axe

    # 3. System node_modules (for Docker/CI)
    system_axe = Path("/node_modules/axe-core/axe.min.js")
    if system_axe.exists():
        return system_axe

    # 4. Home directory
    home_axe = Path.home() / "node_modules" / "axe-core" / "axe.min.js"
    if home_axe.exists():
        return home_axe

    # ✗ Not found
    raise FileNotFoundError(
        f"axe-core not found. Please install:\n"
        f"  npm install --legacy-peer-deps axe-core\n"
        f"  (or set AXE_CORE_PATH environment variable)\n\n"
        f"Searched:\n"
        f"  1. AXE_CORE_PATH env var\n"
        f"  2. {repo_axe}\n"
        f"  3. {system_axe}\n"
        f"  4. {home_axe}"
    )


def validate_paths() -> None:
    """
    Validate that all required paths exist.

    Call this at Modal startup to fail fast with clear instructions
    if anything is missing.

    Raises:
        FileNotFoundError: if any required path is missing
    """
    checks = [
        ("Project root", get_project_root()),
        ("src/ directory", get_src_dir()),
        ("api/ directory", get_api_dir()),
        ("axe-core", get_axe_core_path()),
    ]

    for name, path in checks:
        if not path.exists():
            raise FileNotFoundError(
                f"[Path validation failed] {name} not found: {path}\n"
                f"Please refer to SETUP.md for project structure."
            )

    print(f"✓ All required paths validated")
    print(f"  Project root: {get_project_root()}")
    print(f"  axe-core: {get_axe_core_path()}")


# ── Export for Modal ───────────────────────────────────────────────────────

# These are the main exports used by Modal config and pipeline code
REPO = get_project_root()
SRC = get_src_dir()
AXE_LOCAL = get_axe_core_path()
