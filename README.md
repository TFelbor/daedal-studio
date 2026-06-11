# Prompt2Print: Mesh Engine (p2p-mesh)

![Build Status](https://img.shields.io/badge/Build-passing-brightgreen)
![Status](https://img.shields.io/badge/Status-Proof_of_Concept_COMPLETE-brightgreen)
![Platform](https://img.shields.io/badge/Platform-macOS_Silicon|Ubuntu|Windows-gray)
![License](https://img.shields.io/badge/License-Apache_2.0-green)

**p2p-mesh** is the generative engine for the Prompt2Print platform — a fully local, end-to-end pipeline that converts a natural language prompt into a physical 3D print with zero cloud round-trips.

The system takes a user description and generates a clay-render blueprint image. It then reconstructs the blueprint into a 3D geometry mesh using neural implicit surface extraction, repairs and scales the mesh for the intended print bed, and slices it into machine instructions (G-code). Finally, it dispatches the print job directly to a local 3D printer and continuously monitors telemetry to detect print failures.

This project is built for developers and makers who want a fully local AI-to-physical-object pipeline. It combines state-of-the-art vision models, robust mesh processing, and real-time printer integrations into a single asynchronous orchestration service with a modern web UI.

---

## Architecture Overview

| Component         | Location          | Technology        | Purpose                          |
|-------------------|-------------------|-------------------|----------------------------------|
| Visualizer        | `pythonsrc/`      | FLUX.2-klein-4B   | Text → blueprint image           |
| Sculptor          | `pythonsrc/`      | TripoSR           | Image → 3D mesh                  |
| Engineer          | `pythonsrc/`      | pymeshfix/trimesh | Mesh repair + scaling            |
| Slicer            | `pythonsrc/`      | CuraEngine        | Mesh → G-code                    |
| Operators         | `pythonsrc/operators/` | REST/HTTP      | Printer control (OctoPrint/Klipper/Bambu stub) |
| Telemetry         | `pythonsrc/telemetry/` | SQLite/WS/SIO  | Printer state streaming + failure detection |
| Job API           | `server/`         | FastAPI/uvicorn   | Async job orchestration          |
| Web UI            | `web/`            | React/Vite/TS     | Browser-based user interface     |

---

## Repository Structure

```text
p2p-mesh/
├── docs/           # Architecture decisions, operator guides, and protocol notes
├── infra/          # Docker Compose files, Dockerfiles, and deployment scripts
├── pythonsrc/      # Core pipeline: phases 1–4, printer operators, and telemetry
├── server/         # FastAPI async job orchestrator server
├── tests/          # pytest test suite (unit, mocked integration, slow tests)
└── web/            # React/Vite frontend source code
```

---

## Prerequisites

- Docker Engine 24.x+ and Docker Compose v2.20+
- For macOS Apple Silicon: conda/venv with Python 3.10, `requirements.txt` installed
- For NVIDIA GPU: NVIDIA Container Toolkit
- `HF_TOKEN` (Hugging Face) for FLUX weight download
- OctoPrint (optional, for OctoPrint printer integration)
- Klipper simulation (optional, see `docs/klipper_simulation.md`)

---

## Quick Start

#### CLI OctoPrint Operator
```bash
python -m pythonsrc.operators.octoprint_operator --file <local_path> [--location <remote_dir>] [--select] [--start]
```
- `--file`: Local file to upload.
- `--location` (default `local`): Remote directory on printer.
- `--select`: After upload, select file for printing.
- `--start`: Start print immediately after selection.

#### Failure Events Endpoint
```bash
GET /jobs/{job_id}/failure   # retrieve manual failure reports
POST /jobs/{job_id}/failure  # report failure from UI
```
Returns list of `FailureEvent` objects with snapshot of recent telemetry.

#### Fernet Key Regeneration
If encrypted config key in `.config_key` is corrupted, server logs warning and generates fresh key automatically, avoiding startup crash.

#### Moonraker Mock Port
Moonraker mock accepts optional `--port` argument (default `7125`). Use `docker compose up moonraker-mock` or run manually:
```bash
python tests/mocks/moonraker_mock.py --port 7126
```


### 1. Setup
```bash
# Clone and install dependencies
pip install -r requirements.txt

# Build Docker images (one-time)
docker compose -f infra/docker-compose.yml build

# Copy and edit environment/config files
cp .env.template .env    # edit with HF_TOKEN and printer settings
```

### 2. Start the Server + Web UI
```bash
# Build frontend first (one-time, or after UI changes)
cd web && npm install && npm run build && cd ..

# Start API server (serves web UI on http://localhost:8000)
docker compose -f infra/docker-compose.yml up api-server
```
Open **http://localhost:8000** — the web UI handles job submission, live phase tracking, blueprint/mesh preview, and printer control.

### 3. Submit a Print Job
From the web UI: enter a prompt like "a low poly planter box" and click **Generate & Print**. The pipeline runs automatically with the best execution strategy for your hardware (MPS on Apple Silicon, NVIDIA Docker if available, CPU Docker fallback).

Alternatively, run from CLI:
```bash
# macOS Apple Silicon (Phase 1 native, rest in Docker)
make phase1-native PROMPT="a ceramic vase"

# Docker (any platform)
docker compose -f infra/docker-compose.yml run --rm pipeline-runner python pythonsrc/pipeline.py "a ceramic vase" --print --start-print
```

### 4. Test with Simulators
From the **Settings** page (`/setup`), start the Moonraker or OctoPrint simulator to test printer communication without physical hardware. The simulators stream mock telemetry data and respond to print commands.

---

## Printer Support Matrix

| Firmware    | REST Control | Telemetry         | Failure Detection | Status     |
|-------------|--------------|-------------------|-------------------|------------|
| OctoPrint   | ✅ Full      | ✅ Socket.IO      | ✅ (temp + Z)     | Supported  |
| Klipper     | ✅ Full      | ✅ WebSocket/RPC  | ✅ Full           | Supported  |
| Bambu Lab   | 🔬 Stub      | ❌ Not yet        | ❌ Not yet        | In progress|

---

## Telemetry & Failure Detection

The system collects real-time telemetry from active printers, including hotend temperatures, bed temperatures, Z-axis height, current G-code line, and progress percentage. This data is stored in a local SQLite database and streamed via WebSocket to the frontend. Note that OctoPrint lacks `gcode_line` reporting in its standard telemetry events.

The system automatically detects failure conditions and triggers events based on four primary rules:
1. `DetectTemperatureDrop`: Flags if the hotend temperature drops below 150°C during active printing.
2. `DetectThermalRunaway`: Flags if the hotend temperature exceeds 280°C to prevent hardware damage.
3. `DetectZHeightAnomaly`: Flags unexpected drops in Z-height, indicating a potential catastrophic layer shift or bed adhesion failure.
4. `DetectStalledPrint`: Flags if a print remains in the same state without progressing for over 5 minutes.

---

## Running Tests

```bash
pytest tests/
pytest tests/ -m "slow and real_printer"
pytest tests/ -m "slow and full_pipeline"
```

---

## Roadmap

### ✅ Completed — Proof of Concept & MVP Foundation

- [x] **Phase 1: Visualizer** — Text-to-image blueprinting (FLUX.2-klein-4B, MPS acceleration)
- [x] **Phase 2: Sculptor** — Neural 3D reconstruction & Taubin smoothing (TripoSR)
- [x] **Phase 3: Engineer** — Automated mesh repair, scaling & orientation (pymeshfix)
- [x] **Phase 3.5: Slicer** — CuraEngine G-code generation with bundled printer profiles
- [x] **Phase 4: Operator** — OctoPrint upload, pre-flight printer safety checks & job control
- [x] **Dockerization** — Full pipeline containerization (Ubuntu 22.04, CuraEngine via apt)
- [x] **API Layer** — FastAPI async job server with SQLite-backed job queue, UUID tracking, and status/download endpoints
- [x] **Klipper/Moonraker integration** — WebSocket client for real-time state subscription; Moonraker REST operator to replace/extend OctoPrint operator
- [x] **Telemetry schema v1** — Structured failure-event data model (Z-height, temp deviation, extrusion delta, G-code line, timestamp) defined before UI work begins
- [x] **Telemetry collector** — Background WebSocket consumer writing structured telemetry to SQLite; per-job event log
- [x] **Phase 5: Monitor** — Real-time failure detection using collected telemetry signatures; alert + optional pause-on-anomaly via Klipper pause API
- [x] **Web UI** — React SPA (Vite) served by FastAPI; job submission, phase progress, preview of blueprint and mesh, print status

---

### 🔨 In Progress — MVP Expansion

- [ ] **Bambu Labs adapter** — MQTT-based operator for Bambu X1/P1 series (proprietary protocol); currently stubbed out
- [ ] **Printer setup wizard** — Onboarding flow: printer firmware detection, profile selection, connection test, first-print walkthrough

---

### 📋 Planned — MVP

- [ ] **Multi-printer profile registry** — Plugin-style profile management supporting Klipper, OctoPrint, and static printer definitions; community-importable
- [ ] **Slicer abstraction layer** — Pluggable slicer backend (CuraEngine, PrusaSlicer CLI, OrcaSlicer CLI) selectable per printer profile

---

### 🔭 Future

- [ ] **Local agent (Rust)** — Lightweight native bridge for mDNS printer discovery and direct G-code streaming; complements web UI without requiring full desktop app
- [ ] **Physical printer validation** — End-to-end hardware test suite across Ender 3, Bambu X1C, and Prusa MK4
- [ ] **Dataset pipeline** — Labeled failure-event export tooling; basis for supervised failure-prediction model
- [ ] **Model quality gate** — Automated TripoSR output scoring (mesh validity, printability heuristics) before job proceeds to slicing
- [ ] **User accounts + multi-tenant** — Auth layer (OAuth2/JWT), per-user job history, telemetry namespacing for B2B SaaS deployment

---

## License

This project is licensed under the [Apache 2.0 License](https://www.apache.org/licenses/LICENSE-2.0).
