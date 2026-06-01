# Prompt2Print: Mesh Engine (p2p-mesh)

![Status](https://img.shields.io/badge/Status-Proof_of_Concept_COMPLETE-brightgreen)
![Platform](https://img.shields.io/badge/Platform-macOS_Silicon_(Apple_M--series)-gray)
![License](https://img.shields.io/badge/License-Apache_2.0-green)

**p2p-mesh** is the generative engine for the Prompt2Print platform — a fully local, end-to-end pipeline that converts a natural language prompt into a physical 3D print with zero cloud round-trips. The user types a description; the system generates a blueprint image, reconstructs it as a 3D mesh, repairs and scales the mesh for the print bed, slices it into machine instructions, and dispatches the job to an OctoPrint printer server — all on a single MacBook. This PoC is built for **local inference** to ensure data privacy and zero marginal cost during development, and is the foundation for a planned cloud-hosted product.

---

## 🏗 Architecture

All five pipeline phases are implemented and operational.

| Phase | Module | Status | Description |
|-------|--------|--------|-------------|
| **1 — Visualizer** | `visualizer.py` | ✅ Complete | `FLUX.2-klein-4B` (bfloat16) generates a 1024×1024 clay-render blueprint from a text prompt using MPS acceleration on Apple Silicon. |
| **2 — Sculptor** | `sculptor.py` | ✅ Complete | TripoSR reconstructs the blueprint into 3D geometry via neural implicit surface extraction, followed by Taubin smoothing and quadric decimation to a configurable face target. |
| **3 — Engineer** | `engineer.py` | ✅ Complete | Automated mesh repair using pymeshfix (MeshFix algorithm, Attene 2010) with trimesh fallback, uniform scaling to a configurable target dimension, and gravity-aligned orientation for print-bed placement. |
| **3.5 — Slicer** | `slicer.py` | ✅ Complete | `CuraSlicer` subprocess wrapper invoking CuraEngine 5.x with bundled printer definition files. Converts the engineered `.obj` to print-ready `.gcode`. Bundled profiles for Ender 3 and Anycubic Mega. |
| **4 — Operator** | `operator_phase.py` | ✅ Complete | `OctoPrintOperator` REST client. Auto-connects virtual/physical printer, uploads `.gcode`, validates printer state via pre-flight check (Operational / not-printing / no-error), and starts the print job with optional progress watching. |

**Hardware Acceleration:** Metal Performance Shaders (MPS) with automatic CPU fallback for unsupported ops on Apple Silicon (`PYTORCH_ENABLE_MPS_FALLBACK=1` applied before the first `torch` import).

---

## 💻 Tested Environment

| Component | Version / Spec |
|-----------|---------------|
| **Machine** | MacBook Air M4 |
| **Memory** | 32 GB Unified Memory |
| **Python** | 3.10 (Conda / Miniforge) |
| **OctoPrint** | 1.11.7 (local, virtual printer for PoC validation) |
| **CuraEngine** | 5.12.1 (UltiMaker Cura macOS app bundle) |

---

## ✅ PoC Validation Results

Successful end-to-end run completed on MacBook Air M4.

| Metric | Result |
|--------|--------|
| **Prompt** | `"a smooth ceramic sphere on a flat base"` |
| **Total pipeline time** | ~5 min 45 s (cold model load on M4) |
| **Blueprint** | 1024×1024 RGB, 851 KB |
| **Raw mesh** | 5,000 faces (TripoSR + quadric decimation) |
| **Engineered mesh** | 48.87 × 50.0 × 48.35 mm, pymeshfix-repaired |
| **G-code** | 3.5 MB, 124,332 lines, 108,534 G1 move commands |
| **OctoPrint** | Accepted and executed the job on virtual printer ✓ |

---

## 🚀 Quick Start

### Prerequisites

```bash
# Activate environment
conda activate p2p-mesh

# Install core dependencies
pip install -r requirements.txt

# M4 EXCEPTION: Build geometry kernel from source
# (torchmcubes has no pre-built wheel for Apple M4)
pip install git+https://github.com/tatsy/torchmcubes.git

# CuraEngine — use the UltiMaker Cura app bundle (recommended on macOS)
# or install via Homebrew:
brew install curaengine
```

### Config Setup

`config.py` holds machine-specific paths and your OctoPrint API key. It is gitignored and must never be committed.

```bash
# Create your local config from the safe-to-commit template
cp pythonsrc/config.template.py pythonsrc/config.py

# Edit config.py:
#   - Set OCTOPRINT_API_KEY to your OctoPrint API key
#     (OctoPrint Settings → API → Global API Key)
#   - Verify CURA_ENGINE_PATH — auto-detected from the UltiMaker Cura
#     app bundle by default; override if needed
```

### Full Pipeline (end-to-end)

```bash
# Generate mesh only (Phases 1 → 2 → 3, no slicing or printing)
python pythonsrc/pipeline.py "a miniature chess knight" --target-mm 80

# Full pipeline: generate → slice → upload → print (Phases 1 → 2 → 3 → 3.5 → 4)
python pythonsrc/pipeline.py "a ceramic vase" \
    --print \
    --octoprint-url http://localhost:5001 \
    --octoprint-key YOUR_API_KEY \
    --start-print \
    --profile pythonsrc/profiles/ender3.json
```

### Individual Phase Commands

```bash
# Phase 1 — Visualizer
# Generates blueprint.png from a text prompt
python pythonsrc/visualizer.py \
    --prompt "a smooth ceramic sphere on a flat base" \
    --output inputs/blueprint.png \
    --steps 4

# Phase 2 — Sculptor
# Reconstructs 3D mesh from the blueprint image
python pythonsrc/sculptor.py \
    --blueprint inputs/blueprint.png \
    --output outputs/raw_mesh.obj \
    --faces 5000

# Phase 3 — Engineer (invoked via pipeline; no standalone CLI)
# Called automatically by pipeline.py between sculptor and slicer.

# Phase 3.5 — Slicer (standalone)
python pythonsrc/slicer.py \
    --input  outputs/engineered_mesh.obj \
    --output outputs/engineered_mesh.gcode \
    --engine "/Applications/UltiMaker Cura.app/Contents/Frameworks/CuraEngine"

# Phase 4 — Operator (standalone)
python pythonsrc/operator_phase.py \
    --file outputs/engineered_mesh.gcode \
    --url  http://localhost:5001 \
    --key  YOUR_API_KEY \
    --start \
    --watch
```

### Skip Flags (resume from checkpoint)

Use skip flags to iterate on a specific phase without re-running expensive upstream steps:

```bash
# Skip Phase 1 — reuse an existing blueprint image
python pythonsrc/pipeline.py \
    --skip-visualizer \
    --blueprint inputs/blueprint.png \
    --print \
    --octoprint-url http://localhost:5001 \
    --octoprint-key YOUR_API_KEY

# Skip Phases 1 and 2 — reuse an existing raw mesh
python pythonsrc/pipeline.py \
    --skip-visualizer \
    --skip-sculptor \
    --mesh outputs/raw_mesh.obj \
    --print \
    --octoprint-url http://localhost:5001 \
    --octoprint-key YOUR_API_KEY \
    --start-print
```

---

## 🖨 Printer Profiles

Bundled profiles live in `pythonsrc/profiles/`:

| File | Printer | Build Volume | Notes |
|------|---------|-------------|-------|
| `ender3.json` | Creality Ender 3 | 220 × 220 × 250 mm | 0.2 mm layers, 15% grid infill |
| `anycubic_mega.json` | Anycubic Mega | 210 × 210 × 205 mm | 0.2 mm layers, 15% grid infill |

CuraEngine uses the bundled `fdmprinter.def.json` (base) + `ender3_base.def.json` (machine) definition pair. Pass a custom `.def.json` via `--profile` to override. The JSON schema mirrors the definition file format accepted by CuraEngine's `-j` flag.

---

## 🛣️ Roadmap

- [x] **Phase 1: Visualizer** — Text-to-image blueprinting (FLUX.2-klein-4B, MPS acceleration)
- [x] **Phase 2: Sculptor** — Neural 3D reconstruction & Taubin smoothing (TripoSR)
- [x] **Phase 3: Engineer** — Automated mesh repair, scaling & orientation (pymeshfix)
- [x] **Phase 3.5: Slicer** — CuraEngine G-code generation with bundled printer profiles
- [x] **Phase 4: Operator** — OctoPrint upload, pre-flight printer safety checks & job control
- [ ] **Phase 5: Monitor** — Real-time print telemetry and failure detection
- [ ] **Dockerization** — Containerize the full pipeline for cloud deployment (Ubuntu 22.04 target, CuraEngine via apt)
- [ ] **Web UI** — Minimal FastAPI + frontend for non-CLI usage
- [ ] **Multi-printer profile registry** — Plugin-style printer profile management
- [ ] **Physical printer validation** — Real hardware end-to-end test (USB serial connection)

---

## 📄 License

This project is licensed under the [Apache 2.0 License](https://www.apache.org/licenses/LICENSE-2.0).
