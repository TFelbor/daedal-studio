# Prompt2Print — Docker Usage Guide

This guide explains how to build, run, and troubleshoot the **p2p-mesh pipeline** using Docker. This document is written for system operators, DevOps engineers, and developers running the system locally.

---

## 1. Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Docker Engine | 24.x or later | Core container runtime |
| Docker Compose plugin | v2.20 or later | Must be `docker compose` (not `docker-compose`) |
| NVIDIA Container Toolkit | Latest | Optional. Required for GPU pass-through on Ubuntu/Windows |
| Disk space | ≥ 30 GB | Models (FLUX + TripoSR weights) and images |
| RAM | ≥ 16 GB | Minimum 8 GB for CPU-only runs |

---

## 2. Service Overview

The system is decomposed into highly modular services, allowing independent builds and scaling:

| Service          | Image / Dockerfile          | Port  | Purpose                          |
|------------------|-----------------------------|-------|----------------------------------|
| pipeline-runner  | `infra/docker/pipeline.Dockerfile` | —     | Runs all 5 pipeline phases       |
| phase1-visualizer| `infra/docker/phase1.Dockerfile`   | —     | FLUX text-to-image (standalone)  |
| phase2-sculptor  | `infra/docker/phase2.Dockerfile`   | —     | TripoSR reconstruction           |
| phase3-engineer  | `infra/docker/phase3.Dockerfile`   | —     | Mesh repair + scaling            |
| phase4-slicer    | `infra/docker/phase4.Dockerfile`   | —     | CuraEngine slicing               |
| phase5-operator  | `infra/docker/phase5.Dockerfile`   | —     | OctoPrint/Klipper job dispatch   |
| api-server       | `infra/docker/server.Dockerfile`   | 8000  | FastAPI job orchestrator + UI    |
| web (build)      | `infra/docker/web.Dockerfile`      | —     | Builds React SPA into api-server |

---

## 3. Volume Reference

Persistent storage ensures weights don't re-download and outputs aren't lost across restarts.

| Volume Name          | Mount Point          | Contents                                    |
|----------------------|----------------------|---------------------------------------------|
| p2p-models-flux      | `/models/flux`       | FLUX.2-klein-4B weights (~16 GB)            |
| p2p-models-triposr   | `/models/triposr`    | TripoSR weights                             |
| p2p-models-hf-cache  | `/models/hf_cache`   | HuggingFace hub cache                       |
| p2p-inputs           | `/app/inputs`        | Blueprint images (pipeline input)           |
| p2p-outputs          | `/app/outputs`       | Meshes, G-code (pipeline output)            |
| p2p-telemetry        | `/app/telemetry`     | SQLite telemetry DB (job history, samples)  |

---

## 4. Environment Variable Reference

These variables configure the `.env` file at the repository root.

| Variable | Default Value | Required? | Description |
|----------|---------------|-----------|-------------|
| `HF_TOKEN` | `""` | Yes | HuggingFace token for FLUX weights download |
| `OCTOPRINT_URL` | `http://host.docker.internal:5001` | Yes | OctoPrint API endpoint |
| `OCTOPRINT_API_KEY` | `""` | Yes | OctoPrint application key |
| `CURA_ENGINE_PATH` | `CuraEngine` | No | Path to binary inside the container |
| `FLUX_MODEL_PATH` | `/models/flux` | No | Path to cached FLUX weights |
| `TRIPOSR_MODEL_PATH` | `/models/triposr` | No | Path to cached TripoSR weights |
| `PYTORCH_ENABLE_MPS_FALLBACK` | `1` | No | CPU fallback for macOS MPS operations |
| `HF_HOME` | `/models/hf_cache` | No | Cache path for huggingface-hub |
| `TRANSFORMERS_CACHE` | `/models/hf_cache` | No | Alias for HF_HOME |
| `TELEMETRY_DB_PATH` | `/app/telemetry/telemetry.db` | No | Path to the SQLite DB storing telemetry |
| `PAUSE_ON_FAILURE` | `false` | No | Automatically pause printer on anomaly |

---

## 5. Quickstart (Compose)

Build and run the full stack (API server + React frontend) rapidly:

```bash
cp .env.template .env
# Edit .env and configure HF_TOKEN, OCTOPRINT_API_KEY
docker compose -f infra/docker-compose.yml build
docker compose -f infra/docker-compose.yml up api-server
```
*Note for macOS users:* The FLUX text-to-image generator (Phase 1) runs on CPU in Docker and will be slow (~84 mins). It is highly recommended to run Phase 1 natively on macOS (MPS) and only run Phase 2-5 or the API server in Docker.

---

## 6. Running Individual Phase Images

Each phase is individually addressable for testing and isolated runs.

### Phase 1 — Visualizer
```bash
docker run --rm \
    -v p2p-models-flux:/models/flux \
    -v p2p-models-hf-cache:/models/hf_cache \
    -v p2p-inputs:/app/inputs \
    -e HF_TOKEN=your_token \
    p2p-phase1-visualizer:latest \
    --prompt "a ceramic vase" --output /app/inputs/blueprint.png --steps 4
```

### Phase 2 — Sculptor
```bash
docker run --rm \
    -v p2p-models-triposr:/models/triposr \
    -v p2p-inputs:/app/inputs \
    -v p2p-outputs:/app/outputs \
    p2p-phase2-sculptor:latest \
    --blueprint /app/inputs/blueprint.png --output /app/outputs/raw_mesh.obj
```

### Phase 3 — Engineer
```bash
docker run --rm \
    -v p2p-outputs:/app/outputs \
    p2p-phase3-engineer:latest \
    /app/outputs/raw_mesh.obj /app/outputs/engineered_mesh.obj 50.0
```

### Phase 4 — Slicer
```bash
docker run --rm \
    -v p2p-outputs:/app/outputs \
    p2p-phase4-slicer:latest \
    --input /app/outputs/engineered_mesh.obj --output /app/outputs/engineered_mesh.gcode
```

### Phase 5 — Operator
```bash
docker run --rm \
    -v p2p-outputs:/app/outputs \
    -e OCTOPRINT_URL=http://host.docker.internal:5001 \
    -e OCTOPRINT_API_KEY=your_key \
    p2p-phase5-operator:latest \
    --file /app/outputs/engineered_mesh.gcode --start --watch
```

---

## 7. Running the API Server

The API server hosts the FastAPI application and serves the React UI.

```bash
# Start the API server in detached mode
docker compose -f infra/docker-compose.yml up -d api-server

# Verify health
curl http://localhost:8000/health
```
Once healthy, navigate to `http://localhost:8000` to access the Prompt2Print UI.

---

## 8. Skip-Phase Flags Reference

You can pass these flags to the `pipeline-runner` or `pipeline.py` script to bypass completed phases.

| Flag | Example | Description |
|------|---------|-------------|
| `--skip-visualizer` | `--skip-visualizer --blueprint /app/inputs/img.png` | Skips Phase 1; requires a provided image. |
| `--skip-sculptor` | `--skip-sculptor --mesh /app/outputs/mesh.obj` | Skips Phase 2; requires a provided mesh. |
| `--skip-engineer` | `--skip-engineer` | Skips Phase 3 repairs and scaling. |
| `--skip-slicer` | `--skip-slicer` | Skips Phase 4 G-code slicing. |
| `--print` / `--start-print` | `--print --start-print` | Opts in to Phase 5 execution (dispatch). |

---

## 9. GPU Override (NVIDIA)

To leverage an NVIDIA GPU on Ubuntu/Windows, stack the GPU compose file on top of the base compose file:

```bash
docker compose -f infra/docker-compose.yml -f infra/docker-compose.gpu.yml up api-server
```
This passes `runtime: nvidia` down to the relevant containers. Ensure the host has the NVIDIA Container Toolkit installed.

---

## 10. Rebuilding a Single Phase

Phase separation enables fast rebuilds. If you edit Phase 3 code, only rebuild its container:

```bash
docker compose -f infra/docker-compose.yml build phase3-engineer
```
The other phases will remain cached. Note that changes to `infra/docker/base.Dockerfile` will require a full rebuild of all phases.

---

## 11. Volume Management

Manage your named volumes using the Docker CLI:

```bash
# List all volumes
docker volume ls | grep p2p

# Inspect volume location on host
docker volume inspect p2p-telemetry

# WARNING: Destructive operations
# Force models to re-download by deleting the volume
docker volume rm p2p-models-flux
```

---

## 12. Telemetry Database

The system records all print telemetry, failure events, and job status in a SQLite database at `/app/telemetry/telemetry.db` (mapped to the `p2p-telemetry` volume).

Query it directly from the host:
```bash
docker compose -f infra/docker-compose.yml exec api-server sqlite3 /app/telemetry/telemetry.db \
  "SELECT job_id, outcome, started_at FROM print_job ORDER BY started_at DESC LIMIT 10;"
```

Back it up locally:
```bash
docker cp $(docker compose -f infra/docker-compose.yml ps -q api-server):/app/telemetry/telemetry.db ./telemetry_backup.db
```

---

## 13. Troubleshooting

### `ModuleNotFoundError: No module named 'config'`
**Cause:** `config.py` is gitignored and the container startup script failed to copy from the template.
**Fix:** Run `cp pythonsrc/config.template.py pythonsrc/config.py` and mount it manually, or allow the entrypoint script to run.

### `CuraEngine not found`
**Cause:** Apt package `curaengine` failed to install in Phase 4.
**Fix:** Verify with `docker compose run --rm phase4-slicer which CuraEngine`. Set `CURA_ENGINE_PATH=curaengine` (lowercase) if needed.

### `Connection refused — cannot reach OctoPrint`
**Cause:** Docker network can't resolve the host machine.
**Fix (macOS/Windows):** Use `http://host.docker.internal:5001`.
**Fix (Linux):** Use your LAN IP or add `--add-host=host.docker.internal:host-gateway`.

### `403 Forbidden` from OctoPrint
**Cause:** Incorrect or missing `OCTOPRINT_API_KEY`.
**Fix:** Generate a new Global API Key in OctoPrint and update `.env`.

### Out of disk space during model download
**Cause:** Insufficient space for 16GB FLUX weights.
**Fix:** Use `docker system df` and clean up old images, or prune unused volumes.

### GPU not detected inside container
**Cause:** Missing NVIDIA Container Toolkit.
**Fix:** Install `nvidia-container-toolkit` on the host and run `sudo systemctl restart docker`.

### `api-server fails to start: port 8000 in use`
**Cause:** Another service is bound to port 8000 on the host machine.
**Fix:** Find the blocking process (`lsof -i :8000`), kill it, or map `api-server` to a different host port in `docker-compose.yml`.

### `Telemetry DB locked`
**Cause:** Multiple `api-server` instances attempting concurrent SQLite writes.
**Fix:** Ensure only one `api-server` container is running at a time via `docker compose down` and `docker compose up api-server`.

### `OctoPrint telemetry not collecting: Socket.IO version mismatch`
**Cause:** OctoPrint's Socket.IO server version does not match the `python-socketio` client version expected.
**Fix:** Check OctoPrint plugin logs and verify the Socket.IO compatibility protocol.

### `Moonraker WebSocket disconnects immediately`
**Cause:** The Klipper printer is not in a "ready" state or is disconnected from Moonraker.
**Fix:** Verify Klipper state through Fluidd/Mainsail before running jobs.
