# ────────────────────────────────────────────────────────────────────────────
# phase2.Dockerfile — Sculptor (TripoSR, 2D → 3D reconstruction)
#
# Inherits the base layer and adds:
#   - PyTorch (CPU by default; GPU via compose override)
#   - trimesh, PIL, einops, omegaconf (TripoSR deps)
#   - rembg (background removal used in pre-processing)
#   - torchmcubes (Marching Cubes, required by TripoSR mesh extraction)
#   - fast-simplification (mesh decimation)
#
# Model weights are NOT baked in — stored in a named volume at
# /models/triposr and expected to be pre-populated or downloaded on first run.
#
# Build (standalone):
#   docker build -f infra/docker/phase2.Dockerfile -t p2p-phase2-sculptor .
# ────────────────────────────────────────────────────────────────────────────

FROM p2p-base:latest AS phase2-sculptor

LABEL description="p2p-mesh Phase 2 — Sculptor (TripoSR 2D→3D)"

# ── Model paths ───────────────────────────────────────────────────────────────
ENV TRIPOSR_MODEL_PATH=/models/triposr \
    HF_HOME=/models/hf_cache \
    TRANSFORMERS_CACHE=/models/hf_cache

# ── System dependencies for mesh processing ───────────────────────────────────
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libgmp-dev \
        libmpfr-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# ── Python dependencies ───────────────────────────────────────────────────────
RUN pip install --no-cache-dir \
        torch==2.5.1 \
        torchvision==0.20.1 \
        torchaudio==2.5.1 \
        --index-url https://download.pytorch.org/whl/cpu

RUN pip install --no-cache-dir \
        "transformers<4.45.0" \
        "einops>=0.8.0" \
        "omegaconf>=2.3.0" \
        "trimesh>=4.0.0" \
        "Pillow>=10.0.0" \
        "numpy>=1.24.0" \
        "rembg>=2.0.50" \
        "onnxruntime>=1.15.0" \
        "fast-simplification>=0.1.6" \
        "huggingface_hub>=0.24.0" \
        "safetensors>=0.4.0" \
        "scipy>=1.11.0"

# ── torchmcubes: build from source (no pre-built wheel for linux/cpu) ─────────
# This is a C++/CUDA extension required by TripoSR's mesh extraction.
# System build deps for torchmcubes C extension
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential git ninja-build \
    && rm -rf /var/lib/apt/lists/*

# Install torchmcubes from source (not on PyPI as a wheel)
RUN pip install git+https://github.com/tatsy/torchmcubes.git

RUN pip install --no-cache-dir PyMCubes

# ── Entry point ───────────────────────────────────────────────────────────────
ENTRYPOINT ["/usr/local/bin/p2p-entrypoint", "python", "pythonsrc/sculptor.py"]
CMD ["--help"]
