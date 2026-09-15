# Daedal Studio — Docker Usage Guide

This guide explains how to build, run, and troubleshoot the **ds-mvp pipeline** using Docker. This document is written for system operators, DevOps engineers, and developers running the system locally.

---

## 1. Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Docker Engine | 24.x or later | Core container runtime |
| Docker Compose plugin | v2.20 or later | Must be `docker compose` (not `docker-compose`) |
| NVIDIA Container Toolkit | Latest | Optional. Required for GPU pass-through on Ubuntu/Windows |
| Disk space | ≥ 30 GB | Models (FLUX weights) and images. Add ~20 GB on the GPU host for TRELLIS.2-4B |
| RAM | ≥ 16 GB | Minimum 8 GB for CPU-only runs |

---

## 2. Service Overview

The system is decomposed into highly modular services, allowing independent builds and scaling:

| Service          | Image / Dockerfile          | Port  | Purpose                          |
|------------------|-----------------------------|-------|----------------------------------|
| pipeline-runner  | `infra/docker/pipeline.Dockerfile` | —     | Runs all 5 pipeline phases       |
| phase1-visualizer| `infra/docker/phase1.Dockerfile`   | —     | FLUX text-to-image (standalone)  |
| phase2-sculptor  | `infra/docker/phase2.Dockerfile`   | —     | TRELLIS.2 client (posts to the GPU worker) |
| trellis2-worker  | `infra/docker/trellis2-worker.Dockerfile` | `gpu-worker` | TRELLIS.2-4B in-process (NVIDIA host only) |
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
| ds-models-flux      | `/models/flux`       | FLUX.2-klein-4B weights (~16 GB)            |
| ds-models-trellis2  | `/models/trellis2`   | TRELLIS.2-4B weights (GPU worker only)      |
| ds-models-hf-cache  | `/models/hf_cache`   | HuggingFace hub cache                       |
| ds-inputs           | `/app/inputs`        | Blueprint images (pipeline input)           |
| ds-outputs          | `/app/outputs`       | Meshes, G-code (pipeline output)            |

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
| `TRELLIS2_MODEL_PATH` | `/models/trellis2` | No | Path to cached TRELLIS.2 weights |
| `DS_SCULPTOR_BACKEND` | `auto` | No | `auto` \| `trellis2` \| `remote` |
| `DS_SCULPTOR_REMOTE_URL` | — | For `remote` | GPU worker root URL, e.g. `http://gpu-host:8100` |
| `DS_SCULPTOR_REMOTE_KEY` | — | No | Bearer token, if the worker sets `DS_WORKER_API_KEY` |
| `TRELLIS2_PIPELINE_TYPE` | `1024_cascade` | No | `512` \| `1024` \| `1024_cascade` \| `1536_cascade` |
| `PYTORCH_ENABLE_MPS_FALLBACK` | `1` | No | CPU fallback for macOS MPS operations |
| `HF_HOME` | `/models/hf_cache` | No | Cache path for huggingface-hub |
| `TRANSFORMERS_CACHE` | `/models/hf_cache` | No | Alias for HF_HOME |
| `DS_DATABASE_URL` | — | **Yes** | PostgreSQL URL of the telemetry database (Supabase session pooler or direct connection). Every process uses this one URL |
| `DS_API_BIND` | `127.0.0.1` | No | Host address the API server is published on — see §7. `0.0.0.0` exposes it to the network |
| `DS_API_TOKEN` | generated | No | The shared secret every route but `GET /health` is checked against — see §7. Blank generates one at `~/.ds-mvp/.api_token` on first start |
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
    -v ds-models-flux:/models/flux \
    -v ds-models-hf-cache:/models/hf_cache \
    -v ds-inputs:/app/inputs \
    -e HF_TOKEN=your_token \
    ds-phase1-visualizer:latest \
    --prompt "a ceramic vase" --output /app/inputs/blueprint.png --steps 4
```

### Phase 2 — Sculptor

Two containers, on two machines. TRELLIS.2-4B needs an NVIDIA GPU with ~24 GB of
VRAM and four compiled CUDA extensions with no CPU kernels, so the model lives in
the worker image and the client posts to it.

**On the GPU host** — start the worker (weights download on first boot):
```bash
docker compose -f infra/docker-compose.yml --profile gpu-worker up trellis2-worker

# Confirm it is ready before submitting jobs; a failed preload shows up here
# rather than as a failed Phase 2 four minutes in.
curl -s http://localhost:8100/health | python -m json.tool
```

**On the pipeline host** — point the client at it:
```bash
docker run --rm \
    -v ds-inputs:/app/inputs \
    -v ds-outputs:/app/outputs \
    -e DS_SCULPTOR_BACKEND=remote \
    -e DS_SCULPTOR_REMOTE_URL=http://gpu-host:8100 \
    ds-phase2-sculptor:latest \
    --blueprint /app/inputs/blueprint.png --output /app/outputs/raw_mesh.obj
```

If the pipeline host *is* the GPU host, the shape is the same — run the worker and
point the client at `http://localhost:8100`. The client and the worker stay separate
containers even then, because the CPU images deliberately carry no torch and no CUDA
extensions; that separation is what keeps them portable and what keeps the
non-commercially-licensed renderer packages out of them entirely (see
[`THIRD-PARTY-NOTICES.md`](../THIRD-PARTY-NOTICES.md)).

### Phase 3 — Engineer
```bash
docker run --rm \
    -v ds-outputs:/app/outputs \
    ds-phase3-engineer:latest \
    /app/outputs/raw_mesh.obj /app/outputs/engineered_mesh.obj 50.0
```

### Phase 4 — Slicer
```bash
docker run --rm \
    -v ds-outputs:/app/outputs \
    ds-phase4-slicer:latest \
    --input /app/outputs/engineered_mesh.obj --output /app/outputs/engineered_mesh.gcode
```

### Phase 5 — Operator
```bash
docker run --rm \
    -v ds-outputs:/app/outputs \
    -e OCTOPRINT_URL=http://host.docker.internal:5001 \
    -e OCTOPRINT_API_KEY=your_key \
    ds-phase5-operator:latest \
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
Once healthy, navigate to `http://localhost:8000` to access the Daedal Studio UI.

### The token

**Every route but `GET /health` and the built SPA needs a shared secret.** That
includes `GET /jobs/{id}/download`, the WebSocket upgrades and
`POST /jobs/{id}/internal-telemetry`. Without it they answer `401`.

There is one token for the whole server — no per-user accounts, and none planned
before Phase 5. Set it yourself, or let the server make one:

```bash
# Choose one:
openssl rand -hex 32                        # put the result in .env as DS_API_TOKEN=…

# Or leave DS_API_TOKEN blank and let the server generate it on first start:
make api-token                              # prints the token this machine uses
```

A generated token is written to `~/.ds-mvp/.api_token`, mode `0600` — beside the
config store's Fernet key, in the directory both containers already mount, so a
compose run and `make start-native` resolve the same secret. The **path** is in the
startup log; the value never is.

The web UI asks for it once and keeps it in `localStorage`; Settings § 04 Developer
can reveal, replace or forget it. For anything else, send it as a bearer header:

```bash
curl -H "Authorization: Bearer $(make -s api-token)" http://localhost:8000/jobs
curl http://localhost:8000/health                       # the one route that needs no token
```

**Rotating it** means changing `DS_API_TOKEN` in `.env` (or the file) and restarting
the server; every browser is then asked for the new one. Revocation is rotation for
everybody — that is what one shared secret costs.

The pipeline container and the dispatch operator are handed the token by the server
when it launches them, so nothing needs configuring for a job to report its telemetry.

### Where it is reachable from

**The machine running it, and nowhere else, by default.** The published port is bound
to loopback (`127.0.0.1:8000:8000`), so `http://127.0.0.1:8000` — equivalently
`http://localhost:8000` — works on that host and no other machine on the network can
open it.

The token and the bind address do different jobs and you want both. `POST /jobs`
spends EUR 0,32 on a hosted generation, `POST /jobs/{id}/print-dispatch` heats a
nozzle for hours, and `PUT /config` rewrites the printer credentials the server then
ships to whatever address it is given. Authentication decides who may do those
things; the bind address decides who may try.

Binding the *published* port changes nothing about what the server can reach
outbound: a printer on the LAN, OctoPrint on another host and Supabase are all
connections the server opens itself, and they work exactly as before.

To expose it on purpose, set one variable in `.env` and recreate the container:

```bash
echo 'DS_API_BIND=0.0.0.0' >> .env          # or a single LAN address, e.g. 192.168.1.50
docker compose -f infra/docker-compose.yml up -d --force-recreate api-server
docker compose -f infra/docker-compose.yml config | grep 8000   # confirm the published address
```

The same variable sets uvicorn's `--host` for `make start-native`, which binds the
host interface directly. An SSH tunnel (`ssh -L 8000:127.0.0.1:8000 user@host`) is
still the quieter option, and the token is not TLS: on an untrusted network, put the
server behind something that terminates HTTPS.

Note that `--host 0.0.0.0` on the `command:` line inside the container is *not* this
setting and must stay as it is. Docker publishes a port by connecting to the
container's own address, so a loopback bind in there makes the published port dead
whatever `DS_API_BIND` says.

> Restarting the api-server also stops the OctoPrint simulator (its shutdown hook);
> start it again afterwards.

---

## 8. Skip-Phase Flags Reference

You can pass these flags to the `pipeline-runner` or `pipeline.py` script to bypass completed phases.

| Flag | Example | Description |
|------|---------|-------------|
| `--skip-visualizer` | `--skip-visualizer --blueprint /app/inputs/img.png` | Skips Phase 1; requires a provided image. |
| `--skip-sculptor` | `--skip-sculptor --mesh /app/outputs/mesh.obj` | Skips Phase 2; requires a provided mesh. The way to work on Phases 3-5 without a GPU. |
| `--sculptor-backend` | `--sculptor-backend remote` | Where Phase 2 runs: `auto`, `trellis2` or `remote`. |
| `--pipeline-type` | `--pipeline-type 1536_cascade` | TRELLIS.2 voxel resolution. Higher is finer and slower. |
| `--mesh-seed` | `--mesh-seed 7` | Reconstruction seed. Distinct from `--seed`, which is Phase 1's. |
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
docker volume ls | grep ds-

# Inspect volume location on host
docker volume inspect ds-telemetry

# WARNING: Destructive operations
# Force models to re-download by deleting the volume
docker volume rm ds-models-flux
```

---

## 12. Telemetry Database

All print telemetry, failure events, job rows and the encrypted config store live in
**PostgreSQL on Supabase**, named by `DS_DATABASE_URL` in `.env`. The api-server and the
pipeline container both receive that URL from compose; nothing is stored in a volume.
The only host-side state is the config store's Fernet key at `~/.ds-mvp/.config_key`,
bind-mounted into both containers.

Query it from the host with any PostgreSQL client, or with the trace tool:
```bash
python -m pythonsrc.telemetry.trace --list
python -m pythonsrc.telemetry.trace <job_id>
```

Backups are Supabase's (daily on every plan; point-in-time recovery as an add-on). The
schema is created by the server on startup and is also committed as
`supabase/migrations/*_telemetry_schema.sql` — see `supabase/README.md`.

## 13. What `data/` holds, and what is safe to delete

`data/` is gitignored runtime state. Nothing in it is an input to a build and nothing in
it is backed up; the telemetry row, not the directory, is the record of a job.

| Path | Holds | Safe to delete |
|------|-------|----------------|
| `data/inputs/{job_id}/blueprint.png` | Phase 1's render for one job, plus its `.provenance.json` sidecar | Yes, once the job has finished — the outputs directory keeps a snapshot |
| `data/inputs/blueprint.png` | The shared blueprint a skip-Phase-1 run reuses | Only if you are not about to run with `SKIP_VISUALIZER` |
| `data/outputs/{job_id}/` | That job's mesh, G-code, 3MF, `printability.json`, and for a spec job `spec.json` and `dimension_report.json` | Yes, and it is the only copy — the row records hashes, not files |
| `data/outputs/dev-{job_id}/` | The same, for a run that stood a bundled fixture in for Phase 1 or Phase 2 | Yes; nothing in it came from a model |
| `data/outputs/*.{obj,stl,3mf,gcode}` | The flat layout, written by a run with no `--job-id` | Yes; `POST /jobs` sweeps these anyway |
| `data/logs/{job_id}.log`, `.status` | The pipeline's stdout and its phase records | Yes, once the job is settled |
| `data/octoprint/` | The simulator's own configuration and uploads, including the API key it boots with | **No** — deleting it re-keys the simulator |

A directory holding only `blueprint.png` is a job **parked at the approval gate**,
waiting for a person; deleting it discards the image they are being asked to approve.

### Finding a job's artifacts

```bash
make outputs             # every job directory, newest first, and what each one holds
make outputs LIMIT=10
python -m pythonsrc.outputs --json
```

This reads only the filesystem, so it works with no database configured and no
virtualenv — which matters, because the directories nobody can account for are usually
the ones left by a run that died before it wrote a telemetry row.
`python -m pythonsrc.telemetry.trace --list` is the database-side sibling: it knows the
prompt and the outcome, and nothing about what is on disk.

### Pruning

```bash
make clean-outputs                    # remove empty job directories
make clean-outputs DAYS=30 DRY_RUN=1  # ...also list what is older than 30 days
make clean-outputs DAYS=30            # ...and remove it
```

The default removes only empty directories — a run creates one at its first write, so an
empty one is a run that died before producing anything, and removing it cannot lose
anything. `DAYS=N` additionally removes job directories not written to in N days: that
deletes real meshes and G-code, so it is opt-in, it prints every path first, and a job
parked at the approval gate is exempt from it.

---

## 14. Troubleshooting

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

### `401 Not authenticated` from every route, or the UI asks for a token
**Cause:** Every route but `GET /health` is authenticated (§7), and this browser or
this `curl` is not sending the shared secret. After an upgrade from a build that had
no authentication, this is expected once: an old `.env` has no `DS_API_TOKEN`, so the
server generated one.
**Fix:** `make api-token` prints the token; paste it into the box the UI shows, or
send it as `Authorization: Bearer …`. If `make api-token` says there is none yet, the
server has not started since the change — start it once and it writes one.

### The UI loads but every panel is empty and the log shows 401s
**Cause:** The token stored in the browser is not the one the server is checking —
usually `DS_API_TOKEN` was changed in `.env`, or a native run and a compose run
resolved different files.
**Fix:** Settings → 04 Developer → **Replace**, with the value `make api-token`
prints. `load_native_env.sh` lifts `DS_API_TOKEN` out of `.env`, so both ways of
starting the server agree as long as the value is in there.

### `DS_DATABASE_URL is not set`
**Cause:** The telemetry database URL is missing from `.env` (or, for `make start-native`, not exported).
**Fix:** Copy the Supabase connection string (Project Settings → Database, session pooler) into `DS_DATABASE_URL` in `.env`. Compose passes it to both containers; `load_native_env.sh` lifts it into a native run.

### `GET /health` reports `database.healthy: false`
**Cause:** Supabase is unreachable from this machine, the URL is wrong, or the project is paused.
**Fix:** `problems` names the cause. The server keeps running and re-checks every `DS_DB_HEALTH_INTERVAL_S` seconds; nothing is recorded until it clears.

### `OctoPrint telemetry not collecting: Socket.IO version mismatch`
**Cause:** OctoPrint's Socket.IO server version does not match the `python-socketio` client version expected.
**Fix:** Check OctoPrint plugin logs and verify the Socket.IO compatibility protocol.

### `Moonraker WebSocket disconnects immediately`
**Cause:** The Klipper printer is not in a "ready" state or is disconnected from Moonraker.
**Fix:** Verify Klipper state through Fluidd/Mainsail before running jobs.
