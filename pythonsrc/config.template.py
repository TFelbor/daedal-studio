"""
config.template.py — Copy this file to config.py and fill in your values.
config.py is gitignored and must never be committed.

Setup:
    cp pythonsrc/config.template.py pythonsrc/config.py
    # Then edit config.py with your actual values.
"""
import os
import shutil
from pathlib import Path

# ── CuraEngine binary path ────────────────────────────────────────────────
# Auto-detection order:
#   1. CURA_ENGINE_PATH environment variable
#   2. 'curaengine' on system PATH (Homebrew install)
#   3. UltiMaker Cura macOS app bundle (common install location)
#   4. Explicit fallback path — set this if auto-detection fails
def _detect_cura_engine() -> str:
    if env_path := os.environ.get("CURA_ENGINE_PATH"):
        return env_path
    if shutil.which("curaengine"):
        return "curaengine"
    bundle_path = (
        "/Applications/UltiMaker Cura.app/Contents/Frameworks/CuraEngine"
    )
    if Path(bundle_path).exists():
        return bundle_path
    # Set this manually if none of the above work:
    return "CuraEngine"

CURA_ENGINE_PATH: str = _detect_cura_engine()

# ── OctoPrint connection ──────────────────────────────────────────────────
# Override with environment variable OCTOPRINT_URL if needed.
OCTOPRINT_DEFAULT_URL: str = os.environ.get(
    "OCTOPRINT_URL", "http://localhost:5001"
)

# ── OctoPrint API Key ─────────────────────────────────────────────────────
# NEVER hardcode your API key here in config.template.py.
# Set it in config.py (gitignored) or via environment variable.
OCTOPRINT_API_KEY: str = os.environ.get("OCTOPRINT_API_KEY", "")
# In config.py, replace the line above with:
# OCTOPRINT_API_KEY: str = "your-actual-key-here"
