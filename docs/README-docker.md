# Prompt2Print — Docker Usage Guide

This guide explains how to build and run the **p2p-mesh pipeline** using Docker.
The pipeline is split into six services (one per phase), allowing any single
phase to be rebuilt or swapped without touching the others.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Project Structure](#2-project-structure)
3. [Quickstart (Compose)](#3-quickstart-compose)
4. [Skip Phases — Reuse Existing Outputs](#4-skip-phases--reuse-existing-outputs)
5. [GPU Override (NVIDIA)](#5-gpu-override-nvidia)
6. [Raw `docker run` (No Compose)](#6-raw-docker-run-no-compose)
7. [Running Individual Phase Images](#7-running-individual-phase-images)
8. [Volume Reference](#8-volume-reference)
9. [Environment Variable Reference](#9-environment-variable-reference)
10. [Rebuilding a Single Phase](#10-rebuilding-a-single-phase)
11. [Troubleshooting](#11-troubleshooting)

---

## 1. Prerequisites

| Requirement | Version |
|-------------|---------|
| Docker Engine | 24.x or later |
| Docker Compose plugin | v2.20 or later (`docker compose` not `docker-compose`) |
| NVIDIA Container Toolkit | *(GPU only)* Latest |
| Disk space | ≥ 30 GB (FLUX + TripoSR weights) |
| RAM | ≥ 16 GB recommended (≥ 8 GB minimum for CPU-only run) |

---

## ⚠️ Apple Silicon Mac: Run Phase 1 Outside Docker

Docker on macOS runs inside a Linux VM and cannot access the Apple
Silicon GPU (MPS). Running Phase 1 (FLUX image generation) inside
Docker on Mac will use CPU and take approximately 84 minutes.

The recommended workflow on Mac:

# Step 1 — Run Phase 1 natively (MPS accelerated, ~30 seconds)
./run_phase1_native.sh "a ceramic vase"

# Step 2 — Run Phases 2-5 in Docker (~5 minutes)
docker compose run --rm pipeline-runner \
    python pythonsrc/pipeline.py "a ceramic vase" \
    --skip-visualizer --blueprint /app/inputs/blueprint.png \
    --print --start-print --verbose

On a Linux server with an NVIDIA GPU, the full pipeline can run
inside Docker using the GPU override:
docker compose -f docker-compose.yml -f docker-compose.gpu.yml \
    run --rm pipeline-runner \
    python pythonsrc/pipeline.py "a ceramic vase" \
    --print --start-print --verbose

---

## 2. Project Structure

```
p2p-mesh/
├── docker/
│   ├── base.Dockerfile          ← shared Python 3.10 + system libs layer
│   ├── phase1.Dockerfile        ← FLUX.2-klein-4B (text-to-image)
│   ├── phase2.Dockerfile        ← TripoSR (2D → 3D reconstruction)
│   ├── phase3.Dockerfile        ← pymeshfix + trimesh (repair + scale)
│   ├── phase4.Dockerfile        ← CuraEngine apt install (.obj → .gcode)
│   ├── phase5.Dockerfile        ← requests only (OctoPrint REST client)
│   ├── pipeline.Dockerfile      ← all-in-one runner (chains phases 1–5)
│   └── entrypoint.sh            ← bootstraps config.py from template
├── docker-compose.yml           ← primary dev interface
├── docker-compose.gpu.yml       ← NVIDIA GPU override (compose merge)
├── .env.template                ← copy to .env and fill in your values
└── README-docker.md             ← this file
```

**Build order for standalone phase images:**

```
base → phase1, phase2, phase3, phase4, phase5 (independent)
base → pipeline (all deps merged)
```

---

## 3. Quickstart (Compose)

### Step 1 — Configure environment

```bash
cp .env.template .env
# Open .env and set OCTOPRINT_API_KEY and OCTOPRINT_URL
```

### Step 2 — Build the base image first

The individual phase images all `FROM p2p-base:latest`. Build it once:

```bash
docker build -f docker/base.Dockerfile -t p2p-base:latest .
```

### Step 3 — Build all service images

```bash
docker compose build
```

### Step 4 — Run the full pipeline

```bash
docker compose run --rm pipeline-runner \
    python pythonsrc/pipeline.py "a ceramic vase" \
    --print --start-print --verbose
```

> **macOS / Windows note:** OctoPrint on the host machine is accessed via
> `host.docker.internal`. This is pre-configured in `docker-compose.yml`.
> Linux users: set `OCTOPRINT_URL=http://YOUR_HOST_IP:5001` in `.env`.

---

## 4. Skip Phases — Reuse Existing Outputs

Use skip flags to fast-iterate on a specific phase without re-running expensive upstream steps (e.g. model inference).

### Skip Phase 1 — reuse an existing blueprint image

```bash
docker compose run --rm pipeline-runner \
    python pythonsrc/pipeline.py "prompt" \
    --skip-visualizer --blueprint /app/inputs/blueprint.png \
    --print --start-print
```

### Skip Phases 1 and 2 — start from an existing mesh

```bash
docker compose run --rm pipeline-runner \
    python pythonsrc/pipeline.py \
    --skip-visualizer --skip-sculptor \
    --mesh /app/outputs/raw_mesh.obj \
    --print --start-print --verbose
```

### Mesh-only run (no printing — stop after Phase 3)

```bash
docker compose run --rm pipeline-runner \
    python pythonsrc/pipeline.py "a sphere" \
    --skip-visualizer --mesh /app/outputs/raw_mesh.obj
```

---

## 5. GPU Override (NVIDIA)

The default compose file runs everything on CPU. To enable NVIDIA GPU
acceleration for Phases 1 (FLUX) and 2 (TripoSR):

### Requirements

- NVIDIA GPU driver installed on the host
- [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html) installed:

  ```bash
  # Ubuntu
  sudo apt-get install -y nvidia-container-toolkit
  sudo systemctl restart docker
  ```

### Run with GPU

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml \
    run --rm pipeline-runner \
    python pythonsrc/pipeline.py "a sphere" --print --start-print
```

The GPU override file sets `runtime: nvidia` and `CUDA_VISIBLE_DEVICES=0`
only on the GPU-heavy phases (1, 2, and pipeline-runner). Phases 3–5
are unaffected and always run on CPU.

---

## 6. Raw `docker run` (No Compose)

Use this pattern for CI environments or when you don't want to use Compose.

```bash
docker run --rm \
    -v p2p-models-flux:/models/flux \
    -v p2p-models-triposr:/models/triposr \
    -v p2p-inputs:/app/inputs \
    -v p2p-outputs:/app/outputs \
    -e OCTOPRINT_URL=http://host.docker.internal:5001 \
    -e OCTOPRINT_API_KEY=YOUR_KEY \
    p2p-mesh-pipeline \
    python pythonsrc/pipeline.py "a vase" --print --start-print
```

> **macOS / Windows:** use `host.docker.internal` instead of `localhost`
> when OctoPrint is running on the host machine.

> **Linux:** use `--add-host=host.docker.internal:host-gateway` if you
> need host connectivity, or use your host's LAN IP directly.

---

## 7. Running Individual Phase Images

Each phase has its own image that can be invoked independently.
Build and run a single phase for development and testing:

### Phase 1 — Visualizer (text-to-image)

```bash
# Build standalone phase image
docker build -f docker/base.Dockerfile -t p2p-base:latest .
docker build -f docker/phase1.Dockerfile -t p2p-phase1-visualizer:latest .

# Run
docker run --rm \
    -v p2p-models-flux:/models/flux \
    -v p2p-inputs:/app/inputs \
    -e FLUX_MODEL_PATH=/models/flux \
    p2p-phase1-visualizer:latest \
    --prompt "a ceramic vase" \
    --output /app/inputs/blueprint.png \
    --steps 4
```

### Phase 2 — Sculptor (2D → 3D)

```bash
docker build -f docker/phase2.Dockerfile -t p2p-phase2-sculptor:latest .

docker run --rm \
    -v p2p-models-triposr:/models/triposr \
    -v p2p-inputs:/app/inputs \
    -v p2p-outputs:/app/outputs \
    -e TRIPOSR_MODEL_PATH=/models/triposr \
    p2p-phase2-sculptor:latest \
    --blueprint /app/inputs/blueprint.png \
    --output /app/outputs/raw_mesh.obj
```

### Phase 3 — Engineer (mesh repair + scale)

```bash
docker build -f docker/phase3.Dockerfile -t p2p-phase3-engineer:latest .

docker run --rm \
    -v p2p-outputs:/app/outputs \
    p2p-phase3-engineer:latest \
    /app/outputs/raw_mesh.obj \
    /app/outputs/engineered_mesh.obj \
    50.0 --verbose
```

### Phase 4 — Slicer (CuraEngine)

```bash
docker build -f docker/phase4.Dockerfile -t p2p-phase4-slicer:latest .

docker run --rm \
    -v p2p-outputs:/app/outputs \
    p2p-phase4-slicer:latest \
    --input /app/outputs/engineered_mesh.obj \
    --output /app/outputs/engineered_mesh.gcode
```

### Phase 5 — Operator (OctoPrint)

```bash
docker build -f docker/phase5.Dockerfile -t p2p-phase5-operator:latest .

docker run --rm \
    -v p2p-outputs:/app/outputs \
    -e OCTOPRINT_URL=http://host.docker.internal:5001 \
    -e OCTOPRINT_API_KEY=YOUR_KEY \
    p2p-phase5-operator:latest \
    --file /app/outputs/engineered_mesh.gcode \
    --url http://host.docker.internal:5001 \
    --key YOUR_KEY \
    --start --watch
```

---

## 8. Volume Reference

| Volume Name | Mount Point | Contents |
|-------------|------------|---------|
| `p2p-models-flux` | `/models/flux` | FLUX.2-klein-4B weights (downloaded on first run) |
| `p2p-models-triposr` | `/models/triposr` | TripoSR weights |
| `p2p-models-hf-cache` | `/models/hf_cache` | HuggingFace hub cache (tokenisers, configs) |
| `p2p-inputs` | `/app/inputs` | Blueprint images (input to pipeline) |
| `p2p-outputs` | `/app/outputs` | Meshes, G-code (output from pipeline) |

### Managing volumes

```bash
# List all p2p volumes
docker volume ls | grep p2p

# Inspect a volume (find its mountpoint on the host)
docker volume inspect p2p-models-flux

# Delete model weights to force a fresh download
docker volume rm p2p-models-flux

# Delete all p2p volumes (destructive — removes all outputs too)
docker volume rm p2p-models-flux p2p-models-triposr p2p-inputs p2p-outputs
```

### Swapping a model

To swap TripoSR for a new 3D reconstruction model:

1. Edit `docker/phase2.Dockerfile` — update the pip installs and model path.
2. Delete the old volume: `docker volume rm p2p-models-triposr`
3. Rebuild: `docker build -f docker/phase2.Dockerfile -t p2p-phase2-sculptor:latest .`
4. The pipeline-runner image also needs rebuilding if you changed phase2's Python deps.

---

## 9. Environment Variable Reference

Set these in your `.env` file (copied from `.env.template`).
All values can also be passed via `docker run -e VAR=value`.

| Variable | Default | Description |
|----------|---------|-------------|
| `OCTOPRINT_URL` | `http://host.docker.internal:5001` | OctoPrint base URL |
| `OCTOPRINT_API_KEY` | *(empty)* | **Required** for Phase 5 (printing) |
| `CURA_ENGINE_PATH` | `CuraEngine` | CuraEngine binary name or full path |
| `FLUX_MODEL_PATH` | `/models/flux` | FLUX model weights directory |
| `TRIPOSR_MODEL_PATH` | `/models/triposr` | TripoSR weights directory |
| `PYTORCH_ENABLE_MPS_FALLBACK` | `1` | CPU fallback for unsupported MPS ops |
| `HF_HOME` | `/models/hf_cache` | HuggingFace Hub cache directory |
| `TRANSFORMERS_CACHE` | `/models/hf_cache` | Alias for `HF_HOME` |

---

## 10. Rebuilding a Single Phase

One of the core design goals is **swap-ability**: changing one phase should not require touching any other.

### Rebuild only Phase 3 (engineer)

```bash
# Rebuild the individual phase image
docker compose build phase3-engineer

# Or rebuild standalone
docker build -f docker/phase3.Dockerfile -t p2p-phase3-engineer:latest .
```

### Rebuild the pipeline runner after changing phase deps

```bash
docker compose build pipeline-runner

# Or standalone
docker build -f docker/pipeline.Dockerfile -t p2p-mesh-pipeline:latest .
```

### Rebuild base (affects all phases)

```bash
docker build -f docker/base.Dockerfile -t p2p-base:latest .
# Then rebuild all phases
docker compose build
```

---

## 11. Troubleshooting

### `ModuleNotFoundError: No module named 'config'`

**Cause:** `config.py` is gitignored and the container startup script failed.

**Fix:** The entrypoint script should have created it automatically from `config.template.py`. If it didn't:

```bash
# Manually copy inside the container
docker compose run --rm pipeline-runner \
    cp pythonsrc/config.template.py pythonsrc/config.py
```

Or mount a pre-filled `config.py`:

```bash
-v /path/to/your/config.py:/app/pythonsrc/config.py:ro
```

### `CuraEngine not found`

**Cause:** The `curaengine` apt package failed to install, or the path is wrong.

**Fix:**

1. Verify the package installed: `docker compose run --rm phase4-slicer which CuraEngine`
2. If missing, try the lowercase variant: `CURA_ENGINE_PATH=curaengine`
3. Check `apt-get install curaengine` output in the build log.

### `Connection refused — cannot reach OctoPrint`

**Cause:** OctoPrint is running on the host but the container can't reach it.

**Fix (macOS/Windows):** Use `http://host.docker.internal:5001` in `OCTOPRINT_URL`.

**Fix (Linux):** Add `--add-host=host.docker.internal:host-gateway` to your
`docker run` command, or use your host's LAN IP directly.

### `403 Forbidden` from OctoPrint

**Cause:** `OCTOPRINT_API_KEY` is wrong or not set.

**Fix:** Check OctoPrint → Settings → API → Global API Key and update `.env`.

### Out of disk space during model download

FLUX weights are ~16 GB. Ensure the Docker volume storage location has
at least 30 GB free. Check with:

```bash
docker system df
docker volume inspect p2p-models-flux
```

### GPU not detected inside container

**Cause:** NVIDIA Container Toolkit not installed or Docker daemon not restarted.

**Fix:**

```bash
# Verify toolkit is installed
nvidia-ctk --version

# Restart Docker daemon
sudo systemctl restart docker

# Test GPU visibility
docker run --rm --runtime=nvidia nvidia/cuda:12.0-base nvidia-smi
```
