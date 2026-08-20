# ────────────────────────────────────────────────────────────────────────────
# trellis2-worker.Dockerfile — GPU sculptor worker (Phase 2, TRELLIS.2-4B)
#
# The one image in this project that is NOT CPU-portable. TRELLIS.2 depends on
# four compiled CUDA extensions (flash-attn, CuMesh, FlexGEMM, o-voxel) with no
# CPU kernels, so this builds against the CUDA 12.4 devel image and will only run
# on an NVIDIA host with the Container Toolkit installed.
#
# Deploy it on a GPU host (24 GB VRAM or better) and point the pipeline at it:
#   P2P_SCULPTOR_BACKEND=remote
#   P2P_SCULPTOR_REMOTE_URL=http://<gpu-host>:8100
#
# The TRELLIS.2 source is not on PyPI, so it is cloned at build time. Point
# TRELLIS2_REPO at a fork to build the adapted checkout instead of upstream.
#
# Build (expect 30-60 min — the extensions compile from source):
#   docker build -f infra/docker/trellis2-worker.Dockerfile \
#       -t p2p-trellis2-worker --build-arg TORCH_CUDA_ARCH_LIST="8.6" .
#
# TORCH_CUDA_ARCH_LIST must match the deployment GPU or the kernels will not
# load: 8.0 = A100, 8.6 = A10G/RTX 30xx, 8.9 = L4/RTX 40xx, 9.0 = H100.
# ────────────────────────────────────────────────────────────────────────────

FROM --platform=linux/amd64 nvidia/cuda:12.4.1-devel-ubuntu22.04 AS trellis2-worker

LABEL description="p2p-mesh Phase 2 — TRELLIS.2 GPU sculptor worker"

ARG TRELLIS2_REPO=https://github.com/microsoft/TRELLIS.2.git
ARG TRELLIS2_REF=main
ARG TORCH_CUDA_ARCH_LIST="8.0;8.6;8.9;9.0"

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CUDA_HOME=/usr/local/cuda \
    TORCH_CUDA_ARCH_LIST=${TORCH_CUDA_ARCH_LIST} \
    TRELLIS2_REPO_PATH=/opt/TRELLIS.2 \
    TRELLIS2_MODEL_PATH=/models/trellis2 \
    HF_HOME=/models/hf_cache \
    PYTHONPATH=/app:/app/pythonsrc \
    OPENCV_IO_ENABLE_OPENEXR=1 \
    PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

# ── System dependencies ───────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.10 python3.10-dev python3-pip \
        git ninja-build build-essential cmake \
        libgl1 libglib2.0-0 libjpeg-dev \
    && ln -sf /usr/bin/python3.10 /usr/local/bin/python \
    && ln -sf /usr/bin/python3.10 /usr/local/bin/python3 \
    && pip install --no-cache-dir --upgrade pip setuptools wheel \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# ── PyTorch (pinned to the CUDA 12.4 build upstream tests against) ────────────
RUN pip install --no-cache-dir torch==2.6.0 torchvision==0.21.0 \
        --index-url https://download.pytorch.org/whl/cu124

# ── TRELLIS.2 Python dependencies (setup.sh --basic) ──────────────────────────
# gradio, tensorboard, lpips and the training extras are deliberately omitted:
# this worker only ever runs inference, and none of that path imports them.
RUN pip install --no-cache-dir \
        imageio imageio-ffmpeg tqdm easydict opencv-python-headless ninja \
        trimesh transformers pandas zstandard kornia timm safetensors \
        huggingface_hub einops omegaconf scipy \
    && pip install --no-cache-dir \
        git+https://github.com/EasternJournalist/utils3d.git@9a4eb15e4021b67b12c460c7057d642626897ec8

# ── Attention backend ─────────────────────────────────────────────────────────
RUN pip install --no-cache-dir flash-attn==2.7.3 --no-build-isolation

# ── TRELLIS.2 source ──────────────────────────────────────────────────────────
# --recursive: o-voxel vendors Eigen as a submodule and will not build without it.
RUN git clone --recursive -b ${TRELLIS2_REF} ${TRELLIS2_REPO} /opt/TRELLIS.2

# ── Compiled CUDA extensions ──────────────────────────────────────────────────
# One RUN each: these are the slowest layers in the build and caching them
# separately means a change to one does not recompile the others.
RUN git clone --recursive https://github.com/JeffreyXiang/CuMesh.git /tmp/CuMesh \
    && pip install --no-cache-dir /tmp/CuMesh --no-build-isolation \
    && rm -rf /tmp/CuMesh

RUN git clone --recursive https://github.com/JeffreyXiang/FlexGEMM.git /tmp/FlexGEMM \
    && pip install --no-cache-dir /tmp/FlexGEMM --no-build-isolation \
    && rm -rf /tmp/FlexGEMM

RUN pip install --no-cache-dir /opt/TRELLIS.2/o-voxel --no-build-isolation

# ── Worker service ────────────────────────────────────────────────────────────
RUN pip install --no-cache-dir fastapi "uvicorn[standard]" python-multipart

WORKDIR /app
COPY pythonsrc/sculptors/ ./pythonsrc/sculptors/
COPY services/ ./services/

RUN mkdir -p /models/trellis2 /models/hf_cache

EXPOSE 8100

# Weights are pulled on first boot into /models/trellis2 (mount a volume to keep
# them) unless the volume is already populated.
CMD ["uvicorn", "services.trellis2_worker.app:app", \
     "--host", "0.0.0.0", "--port", "8100", \
     "--timeout-keep-alive", "900"]
