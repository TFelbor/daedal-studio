# Prompt2Print: Mesh Engine (p2p-mesh)

![Status](https://img.shields.io/badge/Status-Proof_of_Concept_COMPLETE-brightgreen)
![Platform](https://img.shields.io/badge/Platform-macOS_Silicon|Ubuntu|Windows-gray)
![License](https://img.shields.io/badge/License-Apache_2.0-green)

**p2p-mesh** is the generative engine for the Prompt2Print platform — a fully local, end-to-end pipeline that converts a natural language prompt into a physical 3D print with zero cloud round-trips. The user types a description; the system generates a blueprint image, reconstructs it as a 3D mesh, repairs and scales the mesh for the print bed, slices it into machine instructions, and dispatches the job to an OctoPrint printer server.

---

## 🏗 Architecture

All five pipeline phases are implemented, operational, and **fully Dockerized**.

| Phase | Module | Status | Description |
|-------|--------|--------|-------------|
| **1 — Visualizer** | `visualizer.py` | ✅ Complete | `FLUX.2-klein-4B` (bfloat16) generates a 1024×1024 clay-render blueprint from a text prompt. |
| **2 — Sculptor** | `sculptor.py` | ✅ Complete | TripoSR reconstructs the blueprint into 3D geometry via neural implicit surface extraction, followed by Taubin smoothing and quadric decimation to a configurable face target. |
| **3 — Engineer** | `engineer.py`       | ✅ Complete | Decimates polygon count, computes robust bounding boxes, rescales to precise target sizes, and provides experimental hollowing algorithms to reduce material usage. |
| **4 — Operator** | `operators/octoprint_operator.py` | ✅ Complete | `OctoPrintOperator` REST client. Auto-connects printer, uploads `.gcode`, and starts the print job. |
| **5 — Slicer**   | `slicer.py`         | ✅ Complete | Wraps `CuraEngine` subprocess for headless G-code generation. |

---

## 🚀 Quick Start

> **Note:** For deep-dives into individual docker phases, volume management, and GPU overrides, refer to the [Docker Usage Guide](docs/README-docker.md).

### 1. Config Setup

We use `.env` to manage configurations for both native execution and Docker.

```bash
# Create your local config from the safe-to-commit template
cp .env.template .env

# Edit .env and configure:
#   - OCTOPRINT_URL (e.g. http://host.docker.internal:5001)
#   - OCTOPRINT_API_KEY
#   - HF_TOKEN (Hugging Face token for FLUX weights)
```

### 2. Execution Workflows

How you run the pipeline depends on your hardware. **CuraEngine and PyMeshFix behave best in a Linux environment**, which is why Docker is the standard. However, **Docker on macOS cannot access Apple Silicon GPUs (MPS)**, creating a necessary hardware boundary.

#### Option A: macOS (Apple Silicon) — Recommended

Run Phase 1 natively to utilize MPS, and run Phases 2-5 inside Docker to use reliable Linux binaries.

```bash
# Setup native environment for Phase 1
conda activate p2p-mesh
pip install -r requirements.txt

# Step 1: Run Phase 1 Natively (MPS accelerated, ~30s)
make phase1-native PROMPT="a ceramic vase"
# Or directly:
bash infra/scripts/run_phase1_native.sh "a ceramic vase"

# Step 2: Run Phases 2-5 in Docker
docker compose -f infra/docker-compose.yml run --rm pipeline-runner \
    python pythonsrc/pipeline.py "a ceramic vase" \
    --skip-visualizer --blueprint /app/inputs/blueprint.png \
    --print --start-print
```

#### Option B: Ubuntu / Windows (NVIDIA GPU)

Run the entire pipeline seamlessly inside Docker with NVIDIA GPU acceleration.

```bash
# Run the full pipeline in a single step with GPU pass-through
docker compose -f infra/docker-compose.yml -f infra/docker-compose.gpu.yml \
    run --rm pipeline-runner \
    python pythonsrc/pipeline.py "a ceramic vase" \
    --print --start-print
```
*(Requires NVIDIA Container Toolkit installed on the host).*

#### Option C: CPU-Only (Any Platform)

If you don't have a supported GPU, you can run the entire pipeline inside Docker using only CPU. Be aware that Phase 1 (FLUX) will take **~80+ minutes** on CPU.

```bash
docker compose -f infra/docker-compose.yml run --rm pipeline-runner \
    python pythonsrc/pipeline.py "a ceramic vase" \
    --print --start-print
```

### 3. Makefile Shortcuts

A `Makefile` is provided at the project root for convenience:

```bash
make build          # Build all Docker images
make up             # Start the API server
make down           # Stop all services
make logs           # Tail API server logs
make test           # Run the test suite
make health         # Check API server health (requires running server)
make phase1-native PROMPT="a ceramic vase"   # Run Phase 1 on Mac (MPS)
make pipeline-mac  PROMPT="a ceramic vase"   # Full pipeline on Mac
make pipeline-gpu  PROMPT="a ceramic vase"   # Full pipeline with NVIDIA GPU
```

---

## 🖨 Printer Profiles

Bundled profiles live in `pythonsrc/profiles/`:

| File | Printer | Build Volume | Notes |
|------|---------|-------------|-------|
| `ender3.json` | Creality Ender 3 | 220 × 220 × 250 mm | 0.2 mm layers, 15% grid infill |
| `anycubic_mega.json` | Anycubic Mega | 210 × 210 × 205 mm | 0.2 mm layers, 15% grid infill |

CuraEngine uses the bundled `fdmprinter.def.json` (base) + `ender3_base.def.json` (machine) definition pair. Pass a custom `.def.json` via `--profile` to override.

---

## 🛣️ Roadmap

### ✅ Completed — Proof of Concept

- [x] **Phase 1: Visualizer** — Text-to-image blueprinting (FLUX.2-klein-4B, MPS acceleration)
- [x] **Phase 2: Sculptor** — Neural 3D reconstruction & Taubin smoothing (TripoSR)
- [x] **Phase 3: Engineer** — Automated mesh repair, scaling & orientation (pymeshfix)
- [x] **Phase 3.5: Slicer** — CuraEngine G-code generation with bundled printer profiles
- [x] **Phase 4: Operator** — OctoPrint upload, pre-flight printer safety checks & job control
- [x] **Dockerization** — Full pipeline containerization (Ubuntu 22.04, CuraEngine via apt)

---

### 🔨 In Progress — MVP Foundation

- [ ] **API Layer** — FastAPI async job server with SQLite-backed job queue, UUID tracking, and status/download endpoints
- [ ] **Klipper/Moonraker integration** — WebSocket client for real-time state subscription; Moonraker REST operator to replace/extend OctoPrint operator
- [ ] **Telemetry schema v1** — Structured failure-event data model (Z-height, temp deviation, extrusion delta, G-code line, timestamp) defined before UI work begins
- [ ] **Telemetry collector** — Background WebSocket consumer writing structured telemetry to SQLite; per-job event log

---

### 📋 Planned — MVP

- [ ] **Web UI** — React SPA (Vite) served by FastAPI; job submission, phase progress, preview of blueprint and mesh, print status
- [ ] **Printer setup wizard** — Onboarding flow: printer firmware detection, profile selection, connection test, first-print walkthrough
- [ ] **Multi-printer profile registry** — Plugin-style profile management supporting Klipper, OctoPrint, and static printer definitions; community-importable
- [ ] **Slicer abstraction layer** — Pluggable slicer backend (CuraEngine, PrusaSlicer CLI, OrcaSlicer CLI) selectable per printer profile
- [ ] **Bambu Labs adapter** — MQTT-based operator for Bambu X1/P1 series (proprietary protocol); highest-volume new printer segment
- [ ] **Phase 5: Monitor** — Real-time failure detection using collected telemetry signatures; alert + optional pause-on-anomaly via Klipper pause API

---

### 🔭 Future

- [ ] **Local agent (Rust)** — Lightweight native bridge for mDNS printer discovery and direct G-code streaming; complements web UI without requiring full desktop app
- [ ] **Physical printer validation** — End-to-end hardware test suite across Ender 3, Bambu X1C, and Prusa MK4
- [ ] **Dataset pipeline** — Labeled failure-event export tooling; basis for supervised failure-prediction model
- [ ] **Model quality gate** — Automated TripoSR output scoring (mesh validity, printability heuristics) before job proceeds to slicing
- [ ] **User accounts + multi-tenant** — Auth layer (OAuth2/JWT), per-user job history, telemetry namespacing for B2B SaaS deployment

---

## 📄 License

This project is licensed under the [Apache 2.0 License](https://www.apache.org/licenses/LICENSE-2.0).
