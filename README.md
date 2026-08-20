# Prompt2Print: Mesh Engine (p2p-mesh)

![Build Status](https://img.shields.io/badge/Build-passing-brightgreen)
![Status](https://img.shields.io/badge/Status-Proof_of_Concept_COMPLETE-brightgreen)
![Platform](https://img.shields.io/badge/Platform-macOS_Silicon|Fedora|Windows-gray)
![License](https://img.shields.io/badge/License-Apache_2.0-green)

**p2p-mesh** is the generative engine for the Prompt2Print platform — a fully local, end-to-end pipeline that converts a natural language prompt into a physical 3D print with zero cloud round-trips.

The system takes a user description and generates a clay-render blueprint image. It then reconstructs the blueprint into a 3D geometry mesh using neural implicit surface extraction, repairs and scales the mesh for the intended print bed, and slices it into machine instructions (G-code). Finally, it dispatches the print job directly to a local 3D printer and continuously monitors telemetry to detect print failures.

This project is built for developers and makers who want a fully local AI-to-physical-object pipeline. It combines state-of-the-art vision models, robust mesh processing, and real-time printer integrations into a single asynchronous orchestration service with a modern web UI.

---

## Architecture Overview

| Component         | Location          | Technology        | Purpose                          |
|-------------------|-------------------|-------------------|----------------------------------|
| Visualizer        | `pythonsrc/`      | FLUX.2-klein-4B   | Text → blueprint image           |
| Sculptor          | `pythonsrc/sculptors/` | TRELLIS.2-4B | Image → 3D mesh                  |
| Sculptor worker   | `services/trellis2_worker/` | FastAPI + CUDA | Serves TRELLIS.2 to GPU-less hosts |
| Engineer          | `pythonsrc/`      | manifold3d/trimesh | Mesh repair + scaling            |
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

## Disabling Telemetry

It is important to avoid sending usage or prompt telemetry to your AI provider while using this project, therefore you must disable telemetry in the client or account settings for each provider you use. The exact labels vary slightly by product version, but the general flow is the same: open the provider settings, find the privacy or diagnostics section, and turn off any option that says "Send usage data", "Share prompts", "Improve the model", "Usage telemetry", "Diagnostic data", or similar.

### Copilot
1. Open the Copilot or VS Code settings panel.
2. Search for terms such as "telemetry", "diagnostics", "send usage data", or "improve Copilot".
3. Disable any option related to sending usage data or product improvement.
4. If you are using an organization-managed tenant, also check your admin or enterprise privacy settings because the tenant policy can override the local client setting.
5. Restart the client if a setting change does not take effect immediately.

### Gemini
1. Open the Gemini app or web interface and go to Settings or Privacy.
2. Look for sections named "Data usage", "Model improvement", "Help improve Gemini", or "Telemetry".
3. Turn off any toggle that allows your prompts or usage data to be used for training or diagnostics.
4. If you use a Google Workspace or managed account, confirm that the account-level privacy policy does not enable data sharing by default.

### OpenAI
1. Open your OpenAI account settings or the client application settings.
2. Navigate to Privacy, Data Controls, or Settings.
3. Disable any setting related to sharing chat data, usage telemetry, or model improvement.
4. If you use ChatGPT Team/Enterprise, check the workspace or organization privacy settings as well, because those can override individual preferences.

### Claude
1. Open the Claude app or web interface and go to Settings or Privacy.
2. Find the section for data usage, telemetry, or model improvement.
3. Turn off any option that allows your interactions to be used for training, diagnostics, or product improvement.
4. If you are signed in through an organization, review the workspace or enterprise privacy controls as well.

### Antigravity
1. Open the Antigravity client or account dashboard.
2. Go to Preferences, Privacy, or Telemetry settings.
3. Disable any toggle or checkbox for usage reporting, diagnostics, or anonymous telemetry.
4. Save the settings and restart the application if needed.

### OpenRouter
1. Sign in to OpenRouter and open your account or settings page.
2. Look for privacy, telemetry, or data-sharing controls.
3. Disable any option related to usage analytics, diagnostic data, or model-improvement sharing.
4. If you use the OpenRouter API directly, also review any SDK or client configuration that may send telemetry by default and disable it there if available.

> Tip: If you do not see a telemetry toggle in the UI, the safest approach is to use a local-only client configuration, avoid any optional data-sharing consent prompts, and review the provider's privacy policy for the latest wording.

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

Manually set up the environment:

```bash
# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Upgrade pip
pip install --upgrade pip

# Install dependencies (on Linux)
pip install -r requirements-linux.txt

# Or install dependencies (on macOS)
pip install -r requirements-mac.txt
```

Then build Docker images and configure environment variables:

```bash
# Build Docker images (one-time)
# The base image must be built first before building other services:
docker compose -f infra/docker-compose.yml build p2p-base
docker compose -f infra/docker-compose.yml build

# Alternatively, use the automated Makefile convenience target:
make build


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

The system collects real-time telemetry from active printers, including hotend temperatures, bed temperatures, Z-axis height, current G-code line, and progress percentage. This data is stored in a local SQLite database and streamed via WebSocket to the frontend. The telemetry stream also dynamically injects high-resolution synthetic temperature samples between full state updates for smoother UI monitoring. Note that OctoPrint lacks `gcode_line` reporting in its standard telemetry events.

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
- [x] **Phase 2: Sculptor** — Neural 3D reconstruction (TRELLIS.2-4B, shape-only O-Voxel path), in-process on CUDA or via a GPU worker
- [x] **Phase 3: Engineer** — Automated mesh repair, scaling & orientation (manifold3d)
- [x] **Phase 3.5: Slicer** — CuraEngine G-code generation with bundled printer profiles
- [x] **Phase 4: Operator** — OctoPrint upload, pre-flight printer safety checks & job control
- [x] **Dockerization** — Full pipeline containerization (Ubuntu 22.04, CuraEngine via apt)
- [x] **API Layer** — FastAPI async job server with SQLite-backed job queue, UUID tracking, dynamic printer metadata endpoints, and status/download endpoints
- [x] **Klipper/Moonraker integration** — WebSocket client for real-time state subscription; Moonraker REST operator to replace/extend OctoPrint operator
- [x] **Telemetry schema v1** — Structured failure-event data model (Z-height, temp deviation, extrusion delta, G-code line, timestamp) defined before UI work begins
- [x] **Telemetry collector** — Background WebSocket consumer writing structured telemetry to SQLite; per-job event log
- [x] **Phase 5: Monitor** — Real-time failure detection using collected telemetry signatures; alert + optional pause-on-anomaly via Klipper pause API
- [x] **Web UI** — React SPA (Vite) served by FastAPI; job submission, phase progress, preview of blueprint and mesh, print status, and dynamic layouts supporting multiple firmware targets

---

### 🔨 In Progress — MVP Expansion

- [ ] **Bambu Labs adapter** — MQTT-based operator for Bambu X1/P1 series (proprietary protocol); currently stubbed out in backend with placeholder UI
- [ ] **Klipper UI** — Complete dedicated telemetry and control dashboard for Klipper (currently using generic service placeholder)
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
- [ ] **Textured output** — GLB export with baked PBR materials, which TRELLIS.2 already produces and the shape-only path discards. Blocked on a permissively licensed rasterizer: upstream's `to_glb()` needs one, and nvdiffrast's licence is non-commercial (see `THIRD-PARTY-NOTICES.md`)
- [ ] **User accounts + multi-tenant** — Auth layer (OAuth2/JWT), per-user job history, telemetry namespacing for B2B SaaS deployment

---

## License

This project is licensed under the [Apache 2.0 License](https://www.apache.org/licenses/LICENSE-2.0).

Third-party components, model weights and the obligations they carry are tracked in
[`THIRD-PARTY-NOTICES.md`](THIRD-PARTY-NOTICES.md). Two of those obligations are
worth stating here, because they constrain what a deployment may do:

**Built with DINOv3.** Phase 2's image conditioning uses DINOv3
(`facebook/dinov3-vitl16-pretrain-lvd1689m`), © Meta Platforms, Inc., licensed
under the [DINOv3 License](https://ai.meta.com/resources/models-and-libraries/dinov3-license/).
Commercial use is permitted; attribution is mandatory, the Acceptable Use Policy
and trade-control terms apply, and **the weights must not be baked into a
distributed image** — that would turn a use into a redistribution.

**Two upstream defaults are deliberately not used.** TRELLIS.2's documented
install line asks for `nvdiffrast` and `nvdiffrec` (NVIDIA Source Code License,
non-commercial); the shape-only path never rasterizes, and neither package is
installed. Its checkpoint configures background removal as `briaai/RMBG-2.0`
(CC BY-NC 4.0); `pythonsrc/sculptors/background.py` substitutes MIT BiRefNet
weights before the pipeline loads. Both substitutions are enforced by
[`tests/test_licensing_guards.py`](tests/test_licensing_guards.py) — read it before
changing either.
