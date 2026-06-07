# ────────────────────────────────────────────────────────────────────────────
# phase3.Dockerfile — Engineer (pymeshfix + trimesh, mesh repair & scale)
#
# Inherits the base layer and adds:
#   - pymeshfix (MeshFix algorithm — Attene 2010)
#   - trimesh with full optional deps
#   - numpy, scipy (required for hollowing / voxel operations)
#   - fast-simplification (optional but recommended for decimation)
#
# No GPU needed — all mesh processing is CPU-bound.
#
# Build (standalone):
#   docker build -f docker/phase3.Dockerfile -t p2p-phase3-engineer .
# ────────────────────────────────────────────────────────────────────────────

FROM p2p-base:latest AS phase3-engineer

LABEL description="p2p-mesh Phase 3 — Engineer (mesh repair + scale)"

# ── System dependencies ───────────────────────────────────────────────────────
# VTK and pymeshfix may need additional system libs for their C++ bindings.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libgmp-dev \
        libmpfr-dev \
        libgomp1 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# ── Python dependencies ───────────────────────────────────────────────────────
RUN pip install --no-cache-dir \
        "numpy>=1.24.0" \
        "scipy>=1.11.0" \
        "trimesh[all]>=4.0.0" \
        "pymeshfix>=0.16.0" \
        "fast-simplification>=0.1.6" \
        "Pillow>=10.0.0" \
        "matplotlib>=3.7.0"

# ── Entry point ───────────────────────────────────────────────────────────────
ENTRYPOINT ["/usr/local/bin/p2p-entrypoint", "python", "pythonsrc/engineer.py"]
CMD ["--help"]
