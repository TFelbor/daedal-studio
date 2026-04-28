# Prompt2Print: Mesh Engine (p2p-mesh)

![Status](https://img.shields.io/badge/Status-Proof_of_Concept-orange)
![Platform](https://img.shields.io/badge/Platform-macOS_Silicon-gray)
![License](https://img.shields.io/badge/License-Apache_2.0-green)

**p2p-mesh** is the generative engine for the Prompt2Print platform. It is responsible for the "Toymaker" workflow: converting natural language prompts into 3D-printable meshes through a vertically integrated local pipeline.

> **Current State:** Phase 3.5 (Slicer) + Phase 4 (Operator) — Operational.
> The pipeline now supports fully automated end-to-end printing: text prompt → image → mesh → G-code → OctoPrint.

## 🏗 Architecture

This Proof of Concept (PoC) is built for **Local Inference** to ensure data privacy and zero marginal cost for the user.

| Phase | Module | Description |
|-------|--------|-------------|
| **1 — Visualizer** | `visualizer.py` | `Flux.2-Klein-4B` (bfloat16 quantised) generates high-fidelity clay renders from a text prompt |
| **2 — Sculptor** | `sculptor.py` | TripoSR reconstructs renders into 3D geometry with Taubin smoothing and optional quadric decimation (graceful fallback if `fast-simplification` is absent) |
| **3 — Engineer** | *(inside `sculptor.py`)* | Automated mesh repair, uniform scaling, gravity-aligned orientation, and optional voxel hollowing |
| **3.5 — Slicer** | `slicer.py` | `CuraSlicer` subprocess wrapper: converts the engineered `.obj` → print-ready `.gcode` via CuraEngine. Bundled printer profiles for Ender 3 and Anycubic Mega |
| **4 — Operator** | `operator_phase.py` | `OctoPrintOperator` REST client: uploads `.gcode`, validates printer state pre-flight (Operational / not-printing / no-error), and starts the job |

**Hardware Acceleration:** Metal Performance Shaders (MPS) with automatic CPU-fallback for unsupported ops on Apple Silicon (`PYTORCH_ENABLE_MPS_FALLBACK=1` applied before the first `torch` import).

## 💻 Tested Environment

* **Machine:** MacBook Air M4
* **Memory:** 32 GB Unified Memory
* **Python:** 3.10 (Conda / Miniforge)

## 🚀 Quick Start

### 1. Prerequisites

```bash
# Activate environment
conda activate p2p-mesh

# Install core dependencies (now includes fast-simplification)
pip install -r requirements.txt

# M4 EXCEPTION: Build geometry kernel from source
pip install git+https://github.com/tatsy/torchmcubes.git

# Install CuraEngine (required for Phase 3.5 slicing)
brew install curaengine   # macOS
# apt install cura-engine # Debian / Ubuntu
```

### 2. Run the Full Pipeline (end-to-end)

```bash
# Generate mesh only (Phases 1 → 2 → 3)
python pythonsrc/pipeline.py "a miniature chess knight" --target-mm 80 --hollow

# Full pipeline: generate → slice → upload → print (Phases 1 → 2 → 3 → 3.5 → 4)
python pythonsrc/pipeline.py "a ceramic vase" \
    --print \
    --octoprint-url http://octopi.local \
    --octoprint-key MY_API_KEY \
    --start-print \
    --profile pythonsrc/profiles/ender3.json
```

### 3. Run Individual Phases

```bash
# Phase 1 — Visualizer
python pythonsrc/visualizer.py

# Phase 2 + 3 — Sculptor / Engineer
python pythonsrc/sculptor.py

# Phase 3.5 — Slicer (standalone)
python pythonsrc/slicer.py \
    --input  outputs/engineered_mesh.obj \
    --output outputs/engineered_mesh.gcode \
    --profile pythonsrc/profiles/ender3.json

# Phase 4 — Operator (standalone)
python pythonsrc/operator_phase.py \
    --file outputs/engineered_mesh.gcode \
    --url  http://octopi.local \
    --key  MY_API_KEY \
    --start --watch
```

### 4. Skip Phases (resume from checkpoint)

```bash
# Skip Visualizer — reuse an existing blueprint image
python pythonsrc/pipeline.py --skip-visualizer --blueprint inputs/blueprint.png --print ...

# Skip Sculptor — reuse an existing mesh
python pythonsrc/pipeline.py --skip-sculptor --mesh outputs/test_mesh.obj --print ...
```

## 🖨 Printer Profiles

Bundled profiles live in `pythonsrc/profiles/`:

| File | Printer | Build Volume | Notes |
|------|---------|-------------|-------|
| `ender3.json` | Creality Ender 3 | 220 × 220 × 250 mm | 0.2 mm layers, 15 % grid infill |
| `anycubic_mega.json` | Anycubic Mega | 210 × 210 × 205 mm | 0.2 mm layers, 15 % grid infill |

Pass any custom profile with `--profile path/to/profile.json`. The JSON schema mirrors the flat key-value format accepted by CuraEngine's `-j` flag.

## 🛣️ Roadmap

* [x] **Phase 1: Visualizer** — Text-to-Image Blueprinting
* [x] **Phase 2: Sculptor** — Neural 3D Reconstruction & Smoothing
* [x] **Phase 3: Engineer** — Automated Mesh Repair, Scaling & Hollowing
* [x] **Phase 3.5: Slicer** — CuraEngine G-code generation with bundled printer profiles
* [x] **Phase 4: Operator** — OctoPrint upload, pre-flight printer safety checks & job monitoring
* [ ] **Phase 5: Monitor** — Real-time print telemetry & failure detection

## 📄 License

This project is licensed under the Apache 2.0 License.
