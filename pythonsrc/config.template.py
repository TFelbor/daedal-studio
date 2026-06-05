"""
config.template.py — Copy this file to config.py and fill in your values.
config.py is gitignored and must never be committed.

Setup:
    cp pythonsrc/config.template.py pythonsrc/config.py
    # Then edit config.py with your actual values.

Docker / Environment Variable Usage:
    All values can be overridden via environment variables (set in .env or
    via docker run -e / docker compose environment:). Environment variables
    are always checked first before any hardcoded fallbacks.

Priority order (high → low):
    1. Environment variable   (CURA_ENGINE_PATH, OCTOPRINT_URL, etc.)
    2. config.py override     (only when running outside Docker)
    3. Auto-detection logic   (shutil.which, app bundle paths)
    4. Hardcoded fallback
"""
import os
import shutil
from pathlib import Path

# ── CuraEngine binary path ────────────────────────────────────────────────
# Auto-detection order:
#   1. CURA_ENGINE_PATH environment variable  ← Docker always sets this
#   2. 'CuraEngine' on system PATH (apt install on Ubuntu)
#   3. 'curaengine' on system PATH (lowercase variant some distros use)
#   4. UltiMaker Cura macOS app bundle (common install location on macOS)
#   5. Explicit fallback — set this in config.py if auto-detection fails
def _detect_cura_engine() -> str:
    # 1. Env var — highest priority, always wins (set in .env / docker run -e)
    if env_path := os.environ.get("CURA_ENGINE_PATH"):
        return env_path
    # 2. 'CuraEngine' on PATH (apt package on Ubuntu, capital C)
    if shutil.which("CuraEngine"):
        return "CuraEngine"
    # 3. 'curaengine' on PATH (lowercase variant used on some distros)
    if shutil.which("curaengine"):
        return "curaengine"
    # 4. UltiMaker Cura macOS app bundle (local dev on macOS)
    bundle_path = (
        "/Applications/UltiMaker Cura.app/Contents/Frameworks/CuraEngine"
    )
    if Path(bundle_path).exists():
        return bundle_path
    # 5. Final fallback — caller will see a clear error from slicer.py
    return "CuraEngine"

CURA_ENGINE_PATH: str = _detect_cura_engine()

# ── OctoPrint connection ──────────────────────────────────────────────────
# Override with environment variable OCTOPRINT_URL.
# In Docker: set to http://host.docker.internal:5001 (macOS/Windows host)
#            or your printer's LAN IP on Linux.
OCTOPRINT_DEFAULT_URL: str = os.environ.get(
    "OCTOPRINT_URL", "http://localhost:5001"
)

# ── OctoPrint API Key ─────────────────────────────────────────────────────
# NEVER hardcode your API key here in config.template.py.
# Set it in config.py (gitignored) or via environment variable OCTOPRINT_API_KEY.
# In Docker: set OCTOPRINT_API_KEY in your .env file.
OCTOPRINT_API_KEY: str = os.environ.get("OCTOPRINT_API_KEY", "")
# In config.py, replace the line above with:
# OCTOPRINT_API_KEY: str = "your-actual-key-here"

# ── AI Model Paths ─────────────────────────────────────────────────────────
# Paths to model weight directories. Override via environment variables.
# In Docker: these map to named volumes mounted at /models/flux and /models/triposr.
FLUX_MODEL_PATH: str = os.environ.get(
    "FLUX_MODEL_PATH",
    str(Path(__file__).parent / "models" / "flux"),
)

TRIPOSR_MODEL_PATH: str = os.environ.get(
    "TRIPOSR_MODEL_PATH",
    str(Path(__file__).parent / "models" / "TripoSR"),
)

# ── Canonical I/O Directories ──────────────────────────────────────────────
# Always relative to repo root (/app in Docker)
# Override via environment variables for custom deployments
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUTS_DIR  = os.environ.get("P2P_INPUTS_DIR",  os.path.join(BASE_DIR, "inputs"))
OUTPUTS_DIR = os.environ.get("P2P_OUTPUTS_DIR", os.path.join(BASE_DIR, "outputs"))
