# ────────────────────────────────────────────────────────────────────────────
# base.Dockerfile — Shared foundation for all p2p-mesh phase images.
#
# Provides:
#   - Ubuntu 22.04 LTS
#   - Python 3.10 (deadsnakes PPA)
#   - Headless OpenGL / display libs required by OpenCV and trimesh
#   - pip + setuptools + wheel
#   - WORKDIR /app with pythonsrc copied in
#
# Usage (standalone build):
#   docker build -f docker/base.Dockerfile -t p2p-base .
# ────────────────────────────────────────────────────────────────────────────

FROM --platform=linux/amd64 ubuntu:22.04

LABEL maintainer="Prompt2Print" \
      description="p2p-mesh base image — Python 3.10 + headless system libs"

# ── Environment ──────────────────────────────────────────────────────────────
# DEBIAN_FRONTEND: prevent apt from blocking on interactive prompts
# PYTHONUNBUFFERED: stream Python stdout/stderr directly to docker logs
# PYTHONDONTWRITEBYTECODE: skip .pyc generation inside containers
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/pythonsrc \
    PYTORCH_ENABLE_MPS_FALLBACK=1

# ── System dependencies ───────────────────────────────────────────────────────
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        software-properties-common \
        gnupg \
        curl \
        wget \
        ca-certificates \
        git \
        build-essential \
        # Headless display / OpenGL required by OpenCV and trimesh
        libgl1 \
        libglib2.0-0 \
        libsm6 \
        libxrender1 \
        libxext6 \
        # Extra mesh / scientific libs
        libgomp1 \
        libffi-dev \
        libssl-dev \
    && add-apt-repository ppa:deadsnakes/ppa -y \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        python3.10 \
        python3.10-dev \
        python3.10-distutils \
        python3-pip \
    && ln -sf /usr/bin/python3.10 /usr/local/bin/python3 \
    && ln -sf /usr/bin/python3.10 /usr/local/bin/python \
    && curl -sS https://bootstrap.pypa.io/get-pip.py | python3.10 \
    && pip install --upgrade pip setuptools wheel \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# ── Working directory ─────────────────────────────────────────────────────────
WORKDIR /app

# ── Copy Python source ────────────────────────────────────────────────────────
# Copy the full pythonsrc tree (includes tsr/, profiles/, config.template.py)
COPY pythonsrc/ ./pythonsrc/
COPY requirements.txt ./requirements.txt

# ── Entrypoint script ───────────────────────────────────────────────────────────────
COPY docker/entrypoint.sh /usr/local/bin/p2p-entrypoint
RUN chmod +x /usr/local/bin/p2p-entrypoint

# ── Create I/O directories ────────────────────────────────────────────────────
RUN mkdir -p /app/inputs /app/outputs /models/flux /models/triposr

# ── Default command ────────────────────────────────────────────────────────────
CMD ["python", "--version"]
