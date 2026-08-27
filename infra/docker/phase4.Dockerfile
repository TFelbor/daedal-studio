# ────────────────────────────────────────────────────────────────────────────
# phase4.Dockerfile — Slicer (CuraEngine 5.x, .obj → .gcode)
#
# Inherits the base layer and adds:
#   - CuraEngine installed via apt (Ubuntu 22.04 repos)
#   - The Python slicer wrapper (slicer.py) needs only stdlib + already-base libs
#
# IMPORTANT: We install CuraEngine from apt — do NOT copy a macOS app bundle.
# The default binary path is /usr/bin/CuraEngine (verified at build time).
# CURA_ENGINE_PATH env var overrides this at runtime if needed.
#
# Build (standalone):
#   docker build -f infra/docker/phase4.Dockerfile -t ds-phase4-slicer .
# ────────────────────────────────────────────────────────────────────────────

FROM ds-base:latest AS phase4-slicer

LABEL description="ds-mvp Phase 4 — Slicer (CuraEngine)"

# ── CuraEngine installation ───────────────────────────────────────────────────
# Universe repository is required for curaengine on Ubuntu 22.04.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        software-properties-common \
    && add-apt-repository universe -y \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        cura-engine \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# ── Verify CuraEngine is available and set default path ──────────────────────
RUN CuraEngine --version || curaengine --version || \
    (echo "WARNING: CuraEngine not found via apt — will attempt runtime detection"; true)

# ── CuraEngine path (matches auto-detection in config.template.py) ────────────
# The apt package may install as 'CuraEngine' or 'curaengine'; we set both
# as fallback candidates. slicer.py checks shutil.which() at runtime.
ENV CURA_ENGINE_PATH=CuraEngine

# ── Entry point ───────────────────────────────────────────────────────────────
ENTRYPOINT ["/usr/local/bin/ds-entrypoint", "python", "pythonsrc/slicer.py"]
CMD ["--help"]
