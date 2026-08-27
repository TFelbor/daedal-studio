# ────────────────────────────────────────────────────────────────────────────
# phase3.Dockerfile — Engineer (manifold3d + trimesh, mesh repair & scale)
#
# Inherits the base layer and adds:
#   - manifold3d (Apache-2.0 guaranteed-manifold kernel; replaced GPL pymeshfix)
#   - trimesh with its runtime extras (`[easy]`; see the note below on `[all]`)
#   - numpy, scipy (required for hollowing / voxel operations)
#   - fast-simplification (optional but recommended for decimation)
#
# No GPU needed — all mesh processing is CPU-bound.
#
# Build (standalone):
#   docker build -f infra/docker/phase3.Dockerfile -t ds-phase3-engineer .
# ────────────────────────────────────────────────────────────────────────────

FROM ds-base:latest AS phase3-engineer

LABEL description="ds-mvp Phase 3 — Engineer (mesh repair + scale)"

# ── System dependencies ───────────────────────────────────────────────────────
# manifold3d ships manylinux wheels; these libs remain for trimesh's runtime extras.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libgmp-dev \
        libmpfr-dev \
        libgomp1 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# ── Python dependencies ───────────────────────────────────────────────────────
# trimesh's `[easy]` extra, not `[all]`. `[all]` includes trimesh's own `test-more`
# extra, which installs **pymeshlab (GPL-3.0)** and **triangle (LGPL-3.0)** into a
# production image — a GPL library importable in the same interpreter, which is the
# exact rule `pymeshfix`'s removal established. Found by the first run of the committed
# licence audit (`licenses/report.json`); nothing in this project imports either.
# `[easy]` keeps the runtime extras (rtree, embreex, shapely, …) and drops trimesh's
# test and viewer dependencies. Do not restore `[all]`.
RUN pip install --no-cache-dir \
        "numpy>=1.24.0" \
        "scipy>=1.11.0" \
        "trimesh[easy]>=4.0.0" \
        "manifold3d>=3.0.0" \
        "fast-simplification>=0.1.6" \
        "Pillow>=10.0.0" \
        "matplotlib>=3.7.0"

# ── Entry point ───────────────────────────────────────────────────────────────
ENTRYPOINT ["/usr/local/bin/ds-entrypoint", "python", "pythonsrc/engineer.py"]
CMD ["--help"]
