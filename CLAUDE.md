# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Prompt2Print (p2p-mesh) is a fully-local pipeline that converts a natural language prompt into a physical 3D print. It chains: text→blueprint image (FLUX), image→3D mesh (TripoSR), mesh repair+scaling (trimesh/manifold3d), slicing (CuraEngine), and printer dispatch (OctoPrint/Klipper). A FastAPI server orchestrates jobs and serves a React SPA. All pipeline phases can run in Docker (linux/amd64) or natively on macOS with MPS acceleration for Phase 1.

## Build & Run Commands

```bash
# Python tests (default: skip slow/integration markers)
pytest tests/ -v
pytest tests/ -m "slow and real_printer"     # requires real/simulated printer
pytest tests/ -m "slow and full_pipeline"    # requires FLUX + TripoSR GPU

# Single test file
pytest tests/test_db.py -v

# Frontend
cd web && npm run dev      # Vite dev server with API proxy to localhost:8000
cd web && npm run build    # TypeScript check + Vite production build
cd web && npm run lint     # ESLint

# Docker (from repo root)
docker compose -f infra/docker-compose.yml build              # build all images
docker compose -f infra/docker-compose.yml up api-server      # start API server + UI
docker compose -f infra/docker-compose.yml -f infra/docker-compose.gpu.yml up api-server  # with GPU
docker compose -f infra/docker-compose.yml run --rm pipeline-runner python pythonsrc/pipeline.py "a vase" --print --start-print

# Makefile shortcuts
make build                     # docker compose build
make up                        # start API server
make test                      # pytest tests/ -v
make phase1-native PROMPT="..."  # run Phase 1 natively on macOS MPS

# Setup (first time)
cp .env.template .env          # edit with HF_TOKEN, OCTOPRINT_API_KEY, etc.
cp pythonsrc/config.template.py pythonsrc/config.py  # if running natively (not Docker)
```

## Architecture

### Pipeline (pythonsrc/pipeline.py)

The core pipeline runs 5 phases sequentially. Phase banners (`[P2P] ═══ PHASE N START/PASS/FAIL ...`) are parsed by the server to emit WebSocket progress updates. The pipeline writes a `.status` file per job to `data/logs/{job_id}.status`.

Execution strategies are auto-detected by `platform_utils.py`:
- `mps_native` — macOS with Apple Silicon (Phase 1 native, Phases 2-5 in Docker)
- `nvidia_docker` — NVIDIA GPU available in Docker
- `cpu_docker` — CPU-only Docker fallback

Skip flags (`--skip-visualizer`, `--skip-sculptor`) allow resuming from intermediate artifacts.

Between Phase 3 and Phase 4 the pipeline runs the **printability gate** (`pythonsrc/printability.py`).
It is deliberately *not* a numbered phase: the `.status` protocol, the WebSocket phase updates and
the UI progress bar all key off phases 1–5, so renumbering would change what every historical
`.status` file means. It emits `[P2P] ─── PRINTABILITY ... ───` banners instead, writes
`data/outputs/{job_id}/printability.json`, and persists score/verdict/features/report onto the
job's telemetry row. Scoring is **advisory** — a low score never blocks a print unless
`--min-printability SCORE` is passed, and a crash in the scorer is logged and skipped rather than
failing the job.

### Server (server/app.py)

FastAPI application with:
- **REST API**: CRUD for jobs (`/jobs`), config management (`/config`), printer simulators (`/simulators/*`), health check, and `GET /jobs/{job_id}/printability` (full report, falling back to the per-job `printability.json` artifact for older jobs). `GET /jobs/{job_id}` also carries `printability_score` / `printability_verdict`.
- **Capture and feedback endpoints**: `GET /jobs/{id}/provenance` returns the whole capture record
  (blueprint, mesh, slice, target, engagement, outcome) — kept off `GET /jobs/{id}`, which the UI
  polls on a timer. `GET /feedback/pending` lists prints awaiting a human verdict;
  `POST /jobs/{id}/outcome` records one; `POST /jobs/{id}/outcome/prompt-shown` and
  `.../dismiss` record that someone was asked and that they declined; `GET /feedback/stats`
  reports the response rate. The outcome endpoint takes an optional signed token from the outset
  so email or webhook delivery is a config change rather than a refactor.
- `GET /jobs/{id}/download` logs a `download` event and increments `download_count` before
  streaming — the response is lazy and may be abandoned mid-flight.
- **WebSocket**: `/ws/jobs/{job_id}` streams phase progress, telemetry batches, and job completion — managed by `JobBroadcaster`
- **Job lifecycle**: POST `/jobs` creates a DB record and launches pipeline subprocess asynchronously; polls `[P2P]` banners from stdout for phase tracking
- **SPA serving**: catch-all route serves `web/dist/` — the React app must be pre-built before server start
- **Config store** (`config_store.py`): Fernet-encrypted key-value store in SQLite (`app_config` table); encryption key at `.config_key` in repo root
- **SimulatorManager** (`simulator_manager.py`): manages a real dockerized OctoPrint on port 5001 (`docker compose -f infra/docker-compose.yml --profile simulator up -d octoprint-simulator`), found by compose label or name. Its virtual printer plugin is enabled in `data/octoprint/octoprint/config.yaml`, so the full dispatch path runs without hardware. `start_moonraker()`/`stop_moonraker()` are deprecated stubs that always report not-running — there is no Moonraker simulator, and `tests/mocks/` no longer contains mock servers.

### Data Flow

1. User submits job via UI → POST `/jobs` → `PrintJob` inserted in SQLite telemetry DB
2. Pipeline subprocess launched → stdout parsed for `[P2P]` phase banners → WebSocket broadcasts
3. If `--print` flag set: Phase 4 slices mesh to G-code, Phase 5 uploads to printer via `PrinterFactory`
4. After Phase 5 starts printing: a telemetry collector (Moonraker WebSocket or OctoPrint SockJS) plus an `AnomalyDetector` stream samples into SQLite; whichever process claims the job first is the sole writer
5. Frontend receives live phase updates, telemetry, and job outcomes via WebSocket

### Telemetry (pythonsrc/telemetry/)

- **Schema** (`schema.py`): Four dataclasses — `PrintJob`, `TelemetrySample`, `FailureEvent`,
  `JobEvent` — with JSON serialization
- **The capture principle**: every column below exists because the value has exactly one moment
  at which it is knowable. A seed drawn and thrown away cannot be recovered; a profile read at
  query time is whatever the file says today, not what the job printed with; "the printer
  finished" is not "the part survived". When adding a signal, ask when it stops being
  recoverable — that is when it must be written.
- **Blueprint provenance (Phase 1)**: `blueprint_model`, `blueprint_model_version`,
  `blueprint_seed`, `blueprint_prompt_engineered`, `blueprint_params`, `blueprint_sha256`,
  `blueprint_duration_s`. Kept under a `blueprint_` prefix rather than merged into
  `generation_*`, which other code reads as the *sculptor's* provenance.
  `blueprint_prompt_engineered` is not `prompt`: `blueprint_spec.engineer_prompt()` appends a
  clay-render suffix the user never sees, and changing that wrapper would otherwise be invisible
  in the dataset. Write with `db.update_job_blueprint()`.
- **Seeds**: `Visualizer.generate_blueprint` returns a `BlueprintResult`, not a `Path`, and takes
  an optional `seed`. Drawn from `SystemRandom` when omitted — **never** the wall clock, which
  gave every job started in the same second an identical image. `blueprint_spec.py` holds the
  seed and prompt logic torch-free so the pipeline, server and tests can use it without the
  Phase 1 stack.
- **Mesh lineage**: `raw_mesh_sha256` / `raw_mesh_features` and `repaired_mesh_sha256` /
  `repaired_mesh_features` bracket Phase 3, making repair's effect measurable. `mesh_features`
  keeps its existing meaning — the printed mesh. Written by `pipeline._record_mesh_lineage()`
  via `printability.extract_features(mesh, thickness=False)` on the raw mesh; the voxel wall
  thickness pass is skipped there because it is expensive and meaningless before scaling.
- **Slice results**: `slice_status` (`success`/`failed`/`skipped`), `slice_error`,
  `slice_duration_s`, `estimated_print_time_s`, `filament_used_mm`/`_mm3`/`_g`,
  `support_filament_mm3`, `layer_count`, `slice_stats`. Recorded on failure too — a dataset of
  only successful slices cannot predict which meshes fail. See `gcode_stats.py` below.
- **Target process and material**: `material_type`, `material_brand`, `material_colour`,
  `nozzle_diameter_mm`, `process_params`. `process_params` is a snapshot of the resolved printer
  profile frozen at job creation, and `GET /jobs/{id}` reads `layer_height_mm` from it. Reading
  the profile file at response time instead means editing a profile retroactively rewrites what
  finished jobs claim to have used.
- **Engagement** (`job_event` table + `JobEvent`): `download`, `regenerate`,
  `outcome_prompt_shown`, `outcome_prompt_dismissed`, `outcome_reported`. One table rather than a
  column per signal, so the pilot's response-rate query needs no migration. `download_count` and
  `parent_job_id` are denormalised onto `print_job` for the common query.
- **Generation provenance + pre-print quality on `PrintJob`**: `generation_model`,
  `generation_model_version`, `generation_backend` (`local` / `hosted_api`), `generation_params`,
  `generation_cost_usd`, `generation_duration_s`, `mesh_features`, `printability_score`,
  `printability_verdict`, `printability_report`. All optional, so pre-existing rows stay valid, and
  `db.init_schema()` adds the columns to older databases via `ALTER TABLE`. These exist because
  they cannot be backfilled: after a print finishes, nothing else records which model made the
  mesh or what the call cost. Write them with `db.update_job_generation()` and
  `db.update_job_printability()` — both skip `None` arguments, so cost arriving after the model
  name does not erase it.
- **Swapping the image-to-3D model** (e.g. TripoSR → TRELLIS.2 on fal.ai): set `MODEL_NAME`,
  `MODEL_VERSION`, `BACKEND` and `last_generation_cost_usd` on the sculptor object.
  `pipeline._record_generation()` reads them off it after Phase 2, so a pay-per-generation backend
  needs no pipeline change to get its cost and latency recorded per job.
- **DB** (`db.py`): SQLite wrapper with thread-safe locking; `check_same_thread=False` for use across asyncio tasks. Path default: `~/.p2p-mesh/telemetry.db` or `TELEMETRY_DB_PATH` env var
- **Collectors**: `MoonrakerCollector` (JSON-RPC over WebSocket to Klipper) and `OctoPrintCollector` (SockJS WebSocket to OctoPrint) write samples to the DB as a background asyncio task, and relay them to the API server via `internal_telemetry.send_internal_telemetry` (`P2P_API_URL`) for WebSocket fan-out. OctoPrint's socket will not accept the API key directly: the collector exchanges it for a session token via `POST /api/login {"passive": true}` and authenticates as `<user>:<session>`. Sending `_api:<api_key>` instead is answered with `reauthRequired` and no telemetry ever arrives.
- **Single writer** (`collector_claim.py`): the API server, `pipeline.py` and `run_operator.py` can all construct a collector for the same job. Each claims a row in `telemetry_collector_claim` at the moment its first sample arrives; non-holders stand down instead of duplicating every row. Claims are released on `stop()` and can be taken over after 120s without a heartbeat.
- **Print outcome is a product feature, not a column** (`outcome`, `outcome_source`,
  `outcome_reported_at`). `outcome_source` is `machine` or `user`, and **only `user` is ground
  truth**. A pipeline that exits 0 after dispatching a print, and an OctoPrint `PrintDone` event,
  both mean the G-code file ran to the end — neither knows whether the part adhered, warped or
  came off the bed. Both therefore write `awaiting_verdict`, not `success`.
  `db.update_job_outcome_verdict()` enforces the precedence rule centrally: **a machine write
  never overwrites a human one**, because printer events arrive late and would otherwise replace
  a real observation with a meaningless one. Genuine machine-observed failures
  (`PrintFailed`, `Error`, `PrintCancelled`) are still recorded directly.
- **Asking the question** (`web/src/components/OutcomeFeedback.tsx`, `/feedback/*`): a persistent
  app-shell banner listing prints awaiting a verdict, each answerable in one tap. It lives in the
  shell rather than on a page because the person who can answer has usually navigated away.
  `outcome_prompt_shown` is logged when a card *renders* (server-deduplicated), so the response
  rate's denominator is people asked, not jobs queued. **A skip is recorded**
  (`outcome_prompt_dismissed`) — whether pilot users report at all is the thing being measured,
  so declining must be distinguishable from never being asked. `GET /feedback/stats` counts over
  prompted *jobs*, not raw events; dividing total reports by total prompts lets an unprompted
  verdict push the rate above 1.
- **Detector** (`detector.py`): Five rules, all evaluated per sample over a 20-sample history — thermal runaway (`hotend_target > 150°C` and actual more than 25°C below target for 5 consecutive samples), clog (progress > 5% and `gcode_line` unchanged across 10 samples while printing), layer shift (Z drops more than 0.5mm between samples), adhesion (`z < 1.0mm` and progress < 10% when state goes printing → error/cancelled), and extrusion issue (`extrusion_factor_pct <= 10` for 5 consecutive samples). Each type fires at most once per job. Rules that read progress need an operator; rules that read `gcode_line` or `extrusion_factor_pct` are Klipper-only, since `OctoPrintCollector` leaves those fields None. Start one per collector via `attach_detector()` — a collector's `sample_queue` is otherwise never consumed.

### Slice statistics (pythonsrc/gcode_stats.py)

**CuraEngine's CLI does not populate its own G-code header.** A real artifact in this repo reads
`;TIME:6666` (correct) alongside `;Filament used: 0m` (wrong — the print extrudes 2.4m) and
`;MINX:2.14748e+06` (the int32 sentinel, never overwritten). Reading the header would record
"0 m of filament" for every job, so `parse_gcode_file()` derives the numbers from the E axis in
one streaming pass instead, using the header only for `;TIME:` and as a fallback.

- Extrusion mode is tracked (`M82` absolute vs `M83` relative): the same `E` word means a
  position under one and a delta under the other, and misreading it inflates totals by orders of
  magnitude. `G92 E` moves the datum without extruding; negative deltas are retractions.
- Each delta is attributed to the current `;TYPE:` section, which is where the support figure
  comes from — no Cura version puts it in the header.
- Mass needs a material: `MATERIAL_DENSITY_G_CM3` covers the types the UI offers, and an unknown
  material yields `None` rather than a guess.
- `header_bbox_is_populated()` detects the sentinel by MIN exceeding MAX, not by magnitude.
- Tested against synthetic fixtures, so the suite needs no CuraEngine.

### Printability (pythonsrc/printability.py)

Deterministic, pre-print geometry scoring — the quality gate the Engineer never had.

- **`ProcessProfile`**: every threshold (nozzle, min wall, overhang angle, bed contact, build
  volume) lives here, so supporting resin is a new profile rather than new check code.
  `ProcessProfile.from_printer_profile()` derives limits from `pythonsrc/profiles/*.json`;
  nozzle diameter is absent from the bundled profiles and defaults to 0.4mm.
- **`evaluate_printability(mesh, profile, job_id, was_hollowed)`** returns a `PrintabilityReport`
  with 11 `CheckResult`s, a weighted 0–100 score, a verdict (`ready` / `risky` / `unprintable`)
  and a `features` snapshot. Checks: watertight, winding, non-manifold edges, degenerate faces,
  floating components, escape hole, min wall thickness, overhang area, bed contact, build-volume
  fit, self-intersections.
- **Wall thickness** is measured by voxelising and taking a distance transform (medial axis ×2),
  *not* by ray casting: `trimesh.proximity.thickness` requires `rtree`, which is not installed, and
  adding it would put a binary dependency in every image. The measurement is quantised, so each
  report states its own ±1-voxel tolerance and the check warns rather than fails inside it. Grid
  size is capped by `MAX_THICKNESS_VOXELS`; bulky meshes get a coarser pitch.
- **`self_intersections` is live**, backed by `manifold3d` (Apache-2.0, now a hard dependency).
  Construction of a `Manifold` is the topological test — rejection means the surface does not bound
  a solid, which is `fail` and critical. Interpenetration is then measured by unioning the
  decomposed components and comparing volume against the sum of the parts; a shortfall above float
  noise is `warn`, since `Engineer.repair_mesh` unions them anyway. If `manifold3d` is somehow
  absent the check reports `not_checked` and is excluded from the score denominator, so it neither
  rewards nor penalises.
- Escape-hole detection finds components whose bounding box nests inside another's, which is
  exactly what `Engineer.hollow_mesh`'s voxel erosion produces: a sealed cavity. It is fatal only
  when the mesh was actually hollowed.

### Printer Operators (pythonsrc/operators/)

Abstract base class `BasePrinterOperator` defines: `connect()`, `upload_file()`, `start_print()`, `cancel_print()`, `pause_print()`, `resume_print()`, `get_printer_state()`. Shared code (`pipeline.py`, `run_operator.py`) must call these with the base signature only — `OctoPrintOperator.upload_file` accepts an extra `start_print` kwarg that no other operator has, and passing it raises `TypeError` on Klipper and Bambu (`tests/test_operator_contract.py` guards this). `PrinterFactory` accepts `moonraker` as an alias for `klipper`, because the UI and config store persist the former while profiles use the latter. `PrinterFactory.create(firmware, base_url, api_key)` returns the appropriate implementation. Profiles at `pythonsrc/profiles/*.json` specify `firmware`, `base_url`, and optionally `api_key`.

### Docker Infrastructure

All images are pinned to `linux/amd64` (CuraEngine is only available as amd64 apt package). Phase Dockerfiles are layered on `base.Dockerfile`. The `pipeline-runner` image bundles all phases and mounts `pythonsrc/` as a volume for live development. Named volumes (`p2p-models-flux`, etc.) persist model weights across rebuilds.

### Frontend (web/)

React 19 + Vite 8 + TypeScript 6. Dependencies: `react-router-dom` (routing), `recharts` (telemetry charts), `three` + `@types/three` (3D mesh viewer). Vite dev server proxies `/jobs` and `/health` to `localhost:8000`. Production build goes to `web/dist/` which is copied into the API server Docker image.

## Configuration

System config (`.env` template at `.env.template`) is loaded by Docker Compose. Runtime config (accessible via `/config` API) is stored encrypted in the telemetry SQLite database (`app_config` table). The encryption key file `.config_key` is gitignored and auto-generated on first use.

Key pipeline paths: `data/inputs/` (blueprint), `data/outputs/{job_id}/` (per-job mesh, G-code and a blueprint snapshot — runs without `--job-id` still use flat `data/outputs/`), `data/logs/` (per-job logs and status files). Server artifact endpoints resolve the per-job path first and fall back to the flat layout for pre-existing rows. These are gitignored runtime directories.

## Licensing Constraints

The project ships under Apache-2.0 (`LICENSE`), and every dependency is tracked in
`THIRD-PARTY-NOTICES.md`. Three rules keep that grant coherent — all three have already been
violated once, so treat them as load-bearing rather than aspirational:

- **Never import a GPL/AGPL library in-process.** `pymeshfix` was removed for exactly this:
  it wraps MeshFix (Attene/IMATI-GE-CNR), whose terms additionally require a negotiated
  contract for commercial use. `Engineer.repair_mesh` now composes trimesh (MIT) for surface
  closing with `manifold3d` (Apache-2.0) for the manifoldness guarantee and boolean union.
- **CuraEngine and OctoPrint are AGPL-3.0 and must stay at arm's length** — CLI subprocess and
  HTTP/socket respectively, never linked or embedded. All FOSS slicers are AGPL/GPL, so
  subprocess isolation is the design, not a workaround. Both are shipped unmodified; the
  written source offer lives in `THIRD-PARTY-NOTICES.md`.
- **Model weights carry licences independent of the library that loads them.** `rembg` is MIT
  but its *default* model became BRIA RMBG-2.0, which requires a paid commercial agreement.
  Hence `rembg==2.0.69` is pinned **and** `sculptor.REMBG_MODEL` names `u2net` (Apache-2.0)
  explicitly. Both controls are required — a version pin alone does not survive a bump.

When adding or bumping a dependency, check the package licence *and* any weights it downloads
at runtime, then update `THIRD-PARTY-NOTICES.md`.

## Important Constraints

- The `PYTORCH_ENABLE_MPS_FALLBACK=1` env var must be set **before** any `import torch` — this is why `pipeline.py` sets it at the very top before other imports
- `pythonsrc/config.py` is gitignored and must be created from `config.template.py` for native (non-Docker) runs
- `data/` directories including logs, inputs, outputs are all runtime-only and gitignored
- Phase 1 (FLUX) on Docker/CPU takes ~84 minutes; native macOS MPS is ~30 seconds — the MPS-native path is the primary dev workflow on Mac
- Docker images are `linux/amd64` only; on Apple Silicon, Docker Desktop emulates via Rosetta 2