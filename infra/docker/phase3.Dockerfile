# ────────────────────────────────────────────────────────────────────────────
# phase3.Dockerfile — Engineer (manifold3d + trimesh, mesh repair & scale)
#
# Inherits the base layer and adds:
#   - manifold3d (Apache-2.0 guaranteed-manifold kernel; replaced GPL pymeshfix)
#   - trimesh with full optional deps
#   - numpy, scipy (required for hollowing / voxel operations)
#   - fast-simplification (optional but recommended for decimation)
#
# No GPU needed — all mesh processing is CPU-bound.
#
# Build (standalone):
#   docker build -f infra/docker/phase3.Dockerfile -t p2p-phase3-engineer .
# ────────────────────────────────────────────────────────────────────────────

FROM p2p-base:latest AS phase3-engineer

LABEL description="p2p-mesh Phase 3 — Engineer (mesh repair + scale)"

# ── System dependencies ───────────────────────────────────────────────────────
# manifold3d ships manylinux wheels; these libs remain for trimesh's optional extras.
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
        "manifold3d>=3.0.0" \
        "fast-simplification>=0.1.6" \
        "Pillow>=10.0.0" \
        "matplotlib>=3.7.0"

# ── Entry point ───────────────────────────────────────────────────────────────
ENTRYPOINT ["/usr/local/bin/p2p-entrypoint", "python", "pythonsrc/engineer.py"]
CMD ["--help"]
