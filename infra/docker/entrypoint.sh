#!/bin/bash
# ────────────────────────────────────────────────────────────────────────────
# docker/entrypoint.sh — Container startup script for ds-mvp pipeline.
#
# Responsibilities:
#   1. Bootstrap config.py from config.template.py if it doesn't exist.
#      (config.py is gitignored and won't be present on a clean clone.)
#   2. Pass all arguments through to the specified command.
#
# This script is the ENTRYPOINT for the pipeline-runner image.
# Individual phase images use CMD directly and don't need this script.
# ────────────────────────────────────────────────────────────────────────────

set -euo pipefail

CONFIG_PY="/app/pythonsrc/config.py"
CONFIG_TEMPLATE="/app/pythonsrc/config.template.py"

# ── Bootstrap config.py ───────────────────────────────────────────────────────
if [ ! -f "$CONFIG_PY" ]; then
    echo "[entrypoint] config.py not found — copying from config.template.py"
    cp "$CONFIG_TEMPLATE" "$CONFIG_PY"
    echo "[entrypoint] config.py created. Values are read from environment variables."
else
    echo "[entrypoint] config.py already exists — using existing file."
fi

# ── Validate required env vars ────────────────────────────────────────────────
# Warn (but do not exit) if OCTOPRINT_API_KEY is unset — it's only needed
# for Phase 5 (--print flag). Phases 1–4 work without it.
if [ -z "${OCTOPRINT_API_KEY:-}" ]; then
    echo "[entrypoint] WARNING: OCTOPRINT_API_KEY is not set."
    echo "             Phase 5 (--print) will fail unless --octoprint-key is passed as a CLI arg."
fi

# ── Execute the provided command ──────────────────────────────────────────────
exec "$@"
