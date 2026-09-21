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
#
# lxml (BSD-3-Clause) is named explicitly because trimesh's 3MF exporter imports it
# at call time — Phase 3 writes `engineered_mesh.3mf` on every run, and a transitive
# copy that arrives with something else is one a later pin can remove without any
# manifest saying so.
#
# fontTools (MIT) is named for lxml's reason exactly: `pythonsrc/organizer/lettering.py`
# reads glyph contours out of the vendored font with it, so Phase 2 cannot compile a
# lettered spec without it — and it arrives transitively with matplotlib, which is a
# dependency a later pin could drop with no manifest saying so. Pure Python, downloads
# nothing at runtime. See THIRD-PARTY-NOTICES.md § 2.
RUN pip install --no-cache-dir \
        "numpy>=1.24.0" \
        "scipy>=1.11.0" \
        "trimesh[easy]>=4.0.0" \
        "manifold3d>=3.0.0" \
        "fast-simplification>=0.1.6" \
        "lxml>=5.0.0" \
        "fonttools>=4.50" \
        "Pillow>=10.0.0" \
        "matplotlib>=3.7.0"

# ── Entry point ───────────────────────────────────────────────────────────────
ENTRYPOINT ["/usr/local/bin/ds-entrypoint", "python", "pythonsrc/engineer.py"]
CMD ["--help"]
