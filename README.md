# Prompt2Print: Mesh Engine (p2p-mesh)

![Status](https://img.shields.io/badge/Status-Proof_of_Concept-orange)
![Platform](https://img.shields.io/badge/Platform-macOS_Silicon-gray)
![License](https://img.shields.io/badge/License-Apache_2.0-green)


**p2p-mesh** is the generative engine for the Prompt2Print platform. It is responsible for the "Toymaker" workflow: converting natural language prompts into 3D-printable meshes through a vertically integrated local pipeline.

> **Current State:** Phase 3 (Engineer) - Operational.
> The module now supports automated mesh repair, scaling, orientation, and hollowing.

## 🏗 Architecture

This Proof of Concept (PoC) is built for **Local Inference** to ensure data privacy and zero marginal cost for the user.

* **Phase 1 (Visualizer):** `Flux.2-Klein-4B` (Quantized `bfloat16`) generates high-fidelity clay renders.
* **Phase 2 (Sculptor):** TripoSR (Large Reconstruction Model) transforms renders into 3D geometry.
* **Post-Processing:** Trimesh-based Taubin smoothing and voxel sub-division for print-ready topology.
* **Hardware Acceleration:** Metal Performance Shaders (MPS) with custom CPU-fallback patches for M4 compatibility.

## 💻 Tested Environment

* **Machine:** MacBook Air M4
* **Memory:** 32GB Unified Memory (M4 Unified Architecture)
* **Python:** 3.10 (Conda/Miniforge)

## 🚀 Quick Start

### 1. Prerequisites

Install core dependencies and build the geometry kernel from source to satisfy the M4's C++ requirements.

```bash
# Activate environment
conda activate p2p-mesh

# Install Core Dependencies
pip install -r requirements.txt

# M4 EXCEPTION: Build geometry kernel from source
pip install git+https://github.com/tatsy/torchmcubes.git

```

### 2. Generate the Pipeline

The workflow is split into two modules to maintain a "Connected Factory" logic.

```bash
# Step 1: Generate the 3D-readable concept
python pythonsrc/visualizer.py

# Step 2: Sculpt the 3D mesh from the concept
python pythonsrc/sculptor.py

```

## 🛣️ Roadmap

* [x] **Phase 1: Visualizer** (Text-to-Image Blueprinting)
* [x] **Phase 2: Sculptor** (Neural 3D Reconstruction & Smoothing)
* [x] **Phase 3: Engineer** (Automated Mesh Repair & Scaling)
* [ ] **Phase 4: Operator** (G-Code Slicing & Direct Printer Export)

## 📄 License

This project is licensed under the Apache 2.0 License.
