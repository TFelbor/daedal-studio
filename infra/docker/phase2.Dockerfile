# ────────────────────────────────────────────────────────────────────────────
# phase2.Dockerfile — Sculptor client (TRELLIS.2 image → 3D)
#
# Phase 2 runs TRELLIS.2-4B, which needs an NVIDIA GPU with ~24 GB of VRAM and
# four compiled CUDA extensions. That does not fit this project's linux/amd64
# CPU image family, so the model is NOT in here. This image is the *client*: it
# posts the blueprint to a GPU worker and post-processes the mesh that comes back.
#
#   worker image:  infra/docker/trellis2-worker.Dockerfile  (CUDA, GPU host)
#   worker code:   services/trellis2_worker/
#
# Point it at a worker and it runs anywhere:
#   DS_SCULPTOR_BACKEND=remote
#   DS_SCULPTOR_REMOTE_URL=http://<gpu-host>:8100
#
# On a host that *does* have an NVIDIA GPU and the extensions installed, set
# DS_SCULPTOR_BACKEND=trellis2 and TRELLIS2_REPO_PATH to run in-process
# instead — or just use the worker image, which already has all of it.
#
# Build (standalone):
#   docker build -f infra/docker/phase2.Dockerfile -t ds-phase2-sculptor .
# ────────────────────────────────────────────────────────────────────────────

FROM ds-base:latest AS phase2-sculptor

LABEL description="ds-mvp Phase 2 — Sculptor (TRELLIS.2 client)"

# ── Configuration ─────────────────────────────────────────────────────────────
# `auto` resolves to `remote` when a worker URL is set. With neither a worker nor
# a CUDA GPU the backend fails at startup with an actionable message rather than
# producing a mesh from something that is not the model you asked for.
ENV DS_SCULPTOR_BACKEND=auto \
    TRELLIS2_MODEL_PATH=/models/trellis2 \
    HF_HOME=/models/hf_cache

# ── System dependencies for mesh processing ───────────────────────────────────
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libgmp-dev \
        libmpfr-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# ── Python dependencies ───────────────────────────────────────────────────────
# No torch: the client never runs a network. It uploads an image, receives
# geometry and does trimesh work on the CPU. Keeping torch out is what makes this
# image small enough to be worth having separately from the worker.
RUN pip install --no-cache-dir \
        "trimesh>=4.0.0" \
        "manifold3d>=3.0.0" \
        "Pillow>=10.0.0" \
        "numpy>=1.24.0" \
        "scipy>=1.11.0" \
        "requests>=2.31.0" \
        "fast-simplification>=0.1.6" \
        "fonttools>=4.50"

# ── Entry point ───────────────────────────────────────────────────────────────
ENTRYPOINT ["/usr/local/bin/ds-entrypoint", "python", "pythonsrc/sculptor.py"]
CMD ["--help"]
