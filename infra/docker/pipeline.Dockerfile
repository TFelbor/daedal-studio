# ────────────────────────────────────────────────────────────────────────────
# pipeline.Dockerfile — Pipeline runner (orchestrator, chains phases 1–5)
#
# This is the "all-in-one" runner image. It does NOT use FROM <phase> because
# Docker doesn't support merging multiple FROM stages into one without copying
# files. Instead, it installs ALL phase dependencies in a single image.
#
# Design rationale:
#   - Individual phase images (phase1–5) are optimised for independent rebuilds
#     and targeted testing of one phase at a time.
#   - The pipeline image provides a single container that can run the full chain
#     (pipeline.py), removing the need for inter-container communication.
#   - When you replace a phase (e.g. swap TripoSR), rebuild phase2.Dockerfile
#     and this pipeline.Dockerfile; the others stay untouched.
#
# Build (standalone):
#   docker build -f infra/docker/pipeline.Dockerfile -t p2p-mesh-pipeline .
# ────────────────────────────────────────────────────────────────────────────

FROM p2p-base:latest AS pipeline-runner

LABEL description="p2p-mesh Pipeline Runner — all phases (1–5) in one container"

# ── Model paths ───────────────────────────────────────────────────────────────
ENV FLUX_MODEL_PATH=/models/flux \
    TRIPOSR_MODEL_PATH=/models/triposr \
    HF_HOME=/models/hf_cache \
    TRANSFORMERS_CACHE=/models/hf_cache \
    CURA_ENGINE_PATH=CuraEngine

# ── System dependencies ───────────────────────────────────────────────────────
# Merge of phase1-5 system deps.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        software-properties-common \
        libgmp-dev \
        libmpfr-dev \
        libgomp1 \
        git \
    && add-apt-repository universe -y \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        cura-engine \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# ── Python dependencies — installed in dependency order ──────────────────────
# 1. PyTorch (CPU) — 2.7+ required for torch.float8_e8m0fnu (used by transformers 5.x)
RUN pip install --no-cache-dir \
        torch==2.7.1 \
        torchvision==0.22.1 \
        torchaudio==2.7.1 \
        --index-url https://download.pytorch.org/whl/cpu

# 2. Phase 1 deps (FLUX / diffusers)
# FLUX.2-klein-4B requires Flux2KleinPipeline which is only in diffusers git HEAD.
# DiffusionPipeline.from_pretrained auto-detects and uses the correct pipeline class.
RUN pip install --no-cache-dir \
        "git+https://github.com/huggingface/diffusers.git" \
        "transformers>=4.45.0" \
        "accelerate>=0.33.0" \
        "safetensors>=0.4.0" \
        "sentencepiece>=0.2.0" \
        "protobuf>=3.20.0" \
        "huggingface_hub>=0.24.0" \
        "hf_transfer>=0.1.6"

# 3. Phase 2 deps (TripoSR)
RUN pip install --no-cache-dir \
        "einops>=0.8.0" \
        "omegaconf>=2.3.0" \
        "rembg>=2.0.50" \
        "onnxruntime>=1.15.0"

# System build deps for torchmcubes C extension
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential git ninja-build \
    && rm -rf /var/lib/apt/lists/*

# Install torchmcubes from source (not on PyPI as a wheel)
RUN pip install git+https://github.com/tatsy/torchmcubes.git

RUN pip install --no-cache-dir PyMCubes

# 4. Phase 3 deps (pymeshfix / trimesh)
RUN pip install --no-cache-dir \
        "trimesh[all]>=4.0.0" \
        "pymeshfix>=0.16.0" \
        "fast-simplification>=0.1.6" \
        "scipy>=1.11.0"

# 5. Phase 5 deps (requests / OctoPrint client)
RUN pip install --no-cache-dir \
        "requests>=2.31.0" \
        "numpy>=1.24.0" \
        "Pillow>=10.0.0" \
        "matplotlib>=3.7.0"

# ── Entrypoint script ────────────────────────────────────────────────────────
# Bootstraps config.py from config.template.py on first run (config.py is
# gitignored and not present on a clean image build).
COPY pythonsrc/ ./pythonsrc/
COPY infra/docker/entrypoint.sh /usr/local/bin/p2p-entrypoint
RUN chmod +x /usr/local/bin/p2p-entrypoint

# ── Entry point ───────────────────────────────────────────────────────────────
# The entrypoint script bootstraps config.py, then exec's its arguments.
# Users pass the full command: python pythonsrc/pipeline.py "prompt" --flags
#
# Examples:
#   docker compose run --rm pipeline-runner \
#       python pythonsrc/pipeline.py "a vase" --print --start-print
#   docker run --rm p2p-mesh-pipeline \
#       python pythonsrc/pipeline.py "a vase" --print --start-print
ENTRYPOINT ["/usr/local/bin/p2p-entrypoint"]
CMD ["python", "pythonsrc/pipeline.py", "--help"]
