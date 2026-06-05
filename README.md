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
| **3 — Engineer** | `engineer.py` | ✅ Complete | Automated mesh repair using pymeshfix (MeshFix algorithm, Attene 2010) with trimesh fallback, uniform scaling, and gravity-aligned orientation. |
| **3.5 — Slicer** | `slicer.py` | ✅ Complete | `CuraSlicer` subprocess wrapper invoking CuraEngine 4.x with bundled printer definition files. Converts `.obj` to `.gcode`. |
| **4 — Operator** | `operator_phase.py` | ✅ Complete | `OctoPrintOperator` REST client. Auto-connects printer, uploads `.gcode`, and starts the print job. |

---

## 🚀 Quick Start

> **Note:** For deep-dives into individual docker phases, volume management, and GPU overrides, refer to the [Docker Usage Guide](README-docker.md).

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

#### Option A: macOS (Apple Silicon)
Run Phase 1 natively to utilize MPS, and run Phases 2-5 inside Docker to use reliable Linux binaries.

```bash
# Setup native environment for Phase 1
conda activate p2p-mesh
pip install -r requirements.txt

# Step 1: Run Phase 1 Natively (MPS accelerated, ~30s)
./run_phase1_native.sh "a ceramic vase"

# Step 2: Run Phases 2-5 in Docker
docker compose run --rm pipeline-runner \
    python pythonsrc/pipeline.py "a ceramic vase" \
    --skip-visualizer --blueprint /app/inputs/blueprint.png \
    --print --start-print
```

#### Option B: Ubuntu / Windows (NVIDIA GPU)
Run the entire pipeline seamlessly inside Docker with NVIDIA GPU acceleration.

```bash
# Run the full pipeline in a single step with GPU pass-through
docker compose -f docker-compose.yml -f docker-compose.gpu.yml \
    run --rm pipeline-runner \
    python pythonsrc/pipeline.py "a ceramic vase" \
    --print --start-print
```
*(Requires NVIDIA Container Toolkit installed on the host).*

#### Option C: CPU-Only (Any Platform)
If you don't have a supported GPU, you can run the entire pipeline inside Docker using only CPU. Be aware that Phase 1 (FLUX) will take **~80+ minutes** on CPU.

```bash
docker compose run --rm pipeline-runner \
    python pythonsrc/pipeline.py "a ceramic vase" \
    --print --start-print
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

- [x] **Phase 1: Visualizer** — Text-to-image blueprinting (FLUX.2-klein-4B, MPS acceleration)
- [x] **Phase 2: Sculptor** — Neural 3D reconstruction & Taubin smoothing (TripoSR)
- [x] **Phase 3: Engineer** — Automated mesh repair, scaling & orientation (pymeshfix)
- [x] **Phase 3.5: Slicer** — CuraEngine G-code generation with bundled printer profiles
- [x] **Phase 4: Operator** — OctoPrint upload, pre-flight printer safety checks & job control
- [x] **Dockerization** — Containerize the full pipeline for cloud deployment (Ubuntu 22.04 target, CuraEngine via apt)
- [ ] **Phase 5: Monitor** — Real-time print telemetry and failure detection
- [ ] **Web UI** — Minimal FastAPI + frontend for non-CLI usage
- [ ] **Multi-printer profile registry** — Plugin-style printer profile management
- [ ] **Physical printer validation** — Real hardware end-to-end test (USB serial connection)

---

## 📄 License

This project is licensed under the [Apache 2.0 License](https://www.apache.org/licenses/LICENSE-2.0).
