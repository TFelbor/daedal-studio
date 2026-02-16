# Prompt2Print: Mesh Engine (p2p-mesh)

![Status](https://img.shields.io/badge/Status-Proof_of_Concept-orange)
![Platform](https://img.shields.io/badge/Platform-macOS_Silicon-gray)
![License](https://img.shields.io/badge/License-Apache_2.0-green)

**p2p-mesh** is the generative engine for the Prompt2Print platform. It is responsible for the "Toymaker" workflow: converting natural language prompts into 3D-printable meshes.

> **Current State:** Phase 1 (Visualizer) - Operational.
> This module currently generates high-fidelity 2D isometric blueprints using a quantized Flux.2 model running locally on Apple Silicon.

## 🏗 Architecture
This Proof of Concept (PoC) is built for **Local Inference** to ensure data privacy and zero marginal cost.

* **Model:** `Flux.2-Klein-4B` (Quantized `bfloat16`)
* **Library:** Hugging Face `Diffusers` + `Accelerate`
* **Hardware Acceleration:** Metal Performance Shaders (MPS) for macOS.

## 💻 Tested Environment
This codebase is optimized for and tested on the following hardware:
* **Machine:** MacBook Air M4
* **Memory:** 32GB Unified Memory
* **OS:** macOS Sequoia (or later)
* **Python:** 3.10+

## 🚀 Quick Start

### 1. Prerequisites
Ensure you have `miniforge` installed for package management.

```bash
# Create the environment
conda create -n p2p-mesh python=3.10
conda activate p2p-mesh

# Install dependencies
pip install torch torchvision torchaudio
pip install diffusers transformers accelerate sentencepiece protobuf

```

### 2. Run the Visualizer

The visualizer generates a 2D reference image ("Blueprint") that will later be used for 3D reconstruction.

```bash
pythonsrc/visualizer.py

```

*Note: The first run will download approx. 12GB of model weights to your local cache.*

## 🛣️ Roadmap

* [x] **Phase 1: Visualizer** (Text-to-Image Blueprinting)
* [ ] **Phase 2: Sculptor** (Image-to-3D Inference via TripoSR/InstantMesh)
* [ ] **Phase 3: Engineer** (Mesh Repair & Watertightness Check)
* [ ] **Phase 4: Operator** (G-Code Slicing & Printer Export)

## 📄 License

This project is licensed under the Apache 2.0 License.
