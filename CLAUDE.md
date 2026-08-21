# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Prompt2Print (p2p-mesh) is a pipeline that converts a natural language prompt into a physical 3D print. It chains: text→blueprint image (FLUX), image→3D mesh (TRELLIS.2-4B), mesh repair+scaling (trimesh/manifold3d), slicing (CuraEngine), and printer dispatch (OctoPrint/Klipper). A FastAPI server orchestrates jobs and serves a React SPA. Phases 1 and 3–5 run in Docker (linux/amd64) or natively on macOS with MPS acceleration for Phase 1.

**Phase 2 is the exception to "fully local".** TRELLIS.2-4B needs an NVIDIA GPU with ~24 GB of VRAM and four compiled CUDA extensions with no CPU kernels, so it cannot run in this project's amd64 CPU images or on Apple Silicon. It runs in-process on a CUDA host, in a GPU worker the rest of the pipeline reaches over HTTP, or on Pixazo's hosted endpoint (€0,32 per generation — the only option on a Mac). See **Sculptor** below.

**Phase 1 is unaffected by any of that.** `visualizer.get_device()` still picks `mps` on Apple Silicon and `infra/scripts/run_phase1_native.sh` / `make phase1-native` / `make start-native` are the MPS-native path. Phase 2's backend choice is independent of it.

## Build & Run Commands

```bash
# Python tests (default: skip slow/integration markers)
pytest tests/ -v
pytest tests/ -m "slow and real_printer"     # requires real/simulated printer
pytest tests/ -m "slow and full_pipeline"    # requires FLUX + a CUDA GPU or sculptor worker

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

# Phase 2 GPU worker — run this on a CUDA host, not the dev machine
docker compose -f infra/docker-compose.yml --profile gpu-worker up trellis2-worker
curl -s http://<gpu-host>:8100/health | python -m json.tool   # check before submitting jobs

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

Execution strategies are auto-detected by `platform_utils.py`. These decide **Phase 1's**
placement only:
- `mps_native` — macOS with Apple Silicon (Phase 1 native, Phases 3-5 in Docker)
- `nvidia_docker` — NVIDIA GPU available in Docker
- `cpu_docker` — CPU-only Docker fallback

Phase 2's placement is a *separate* decision made by `sculptors.resolve_backend_name`, because
`platform_utils` knows nothing about the worker URL that makes a GPU-less host viable.

Skip flags (`--skip-visualizer`, `--skip-sculptor`) allow resuming from intermediate artifacts.

Between Phase 3 and Phase 4 the pipeline runs the **printability gate** (`pythonsrc/printability.py`).
It is deliberately *not* a numbered phase: the `.status` protocol, the WebSocket phase updates and
the UI progress bar all key off phases 1–5, so renumbering would change what every historical
`.status` file means. It emits `[P2P] ─── PRINTABILITY ... ───` banners instead, writes
`data/outputs/{job_id}/printability.json`, and persists score/verdict/features/report onto the
job's telemetry row. Scoring is **advisory** — a low score never blocks a print unless
`--min-printability SCORE` is passed, and a crash in the scorer is logged and skipped rather than
failing the job.

### Sculptor — Phase 2 (pythonsrc/sculptors/)

Image→3D reconstruction with **TRELLIS.2-4B**. `pythonsrc/sculptor.py` is a thin facade over
the package, kept so `from sculptor import create_sculptor`, the Phase 2 container entrypoint
and the CLI all have one stable name.

Three backends run the *same* model; which one runs is a deployment detail, not a difference in
output — except for the coordinate frame, which is why each declares its own `up_axis`:

- **`trellis2`** — in-process. Requires CUDA, ~24 GB VRAM, and `$TRELLIS2_REPO_PATH` pointing at
  a TRELLIS.2 checkout (upstream is not pip-installable).
- **`remote`** — posts the blueprint to a self-hosted GPU worker (`services/trellis2_worker/`)
  and gets raw geometry back.
- **`pixazo`** — calls Pixazo's hosted `trellis-2-image-to-3d` endpoint. The only backend that
  works on an Apple Silicon Mac, and the only one that costs money.

`create_sculptor()` / `resolve_backend_name()` resolve `auto` as: `remote` if
`$P2P_SCULPTOR_REMOTE_URL` is set (an explicit configuration outranks a local GPU that may be
busy with Phase 1), else `trellis2` if CUDA is visible, else `pixazo` if `$PIXAZO_API_KEY` is
set, else **raise**. The paid endpoint is last on purpose — hardware already paid for must never
be passed over for one that bills — and selecting it logs the price, so a run that starts
spending money says so. There is deliberately no CPU fallback: silently producing a mesh from
something other than the model you asked for is worse than failing, and there is nothing to fall
back *to*.

- **Shape-only path.** `Trellis2Backend` drives the pipeline stages itself
  (`get_cond` → `sample_sparse_structure` → `sample_shape_slat[_cascade]` → `decode_shape_slat`)
  rather than calling `pipeline.run()`, which would also sample a texture latent. An FDM printer
  consumes geometry alone, so this saves roughly 40% of GPU time, keeps the texture DiT and
  decoder from being downloaded at all (`SHAPE_ONLY_MODELS` narrows `model_names_to_load`), and
  — see Licensing — never touches a rasterizer.
- **TRELLIS.2 is already Z-up**, unlike TripoSR. Its orbit cameras use `[0,0,1]` as up and
  `o_voxel.postprocess.to_glb` swaps Y/Z on the way out precisely because glTF is Y-up and the
  model's frame is not. So `up_axis = "z"` and no rotation is applied. Getting this wrong is
  silent: the print simply comes out lying on its side.
- **Smoothing defaults to 0.** Sharp features are the reason to run this model; Taubin smoothing
  subdivides and rounds exactly the edges O-Voxel recovers. `default_smooth_iterations` is a
  per-backend value, and `--smooth N` opts back in.
- **Decimation happens twice, on purpose.** `cumesh` simplifies on the GPU to
  `gpu_simplify_target` (200k) before the mesh is ever materialised as NumPy — a 1024³
  reconstruction is millions of faces, and CPU-decimating that costs minutes — then the shared
  CPU pass takes it to `--faces`.
- **Post-processing is shared and lives client-side** (`SculptorBackend.postprocess`):
  Z-up rotation, largest-component pruning, optional smoothing, decimation, export. The worker
  returns *raw* geometry so there is exactly one implementation regardless of where inference
  ran, and so GPU seconds are not billed for CPU work. The frame comes back in the
  `X-P2P-Up-Axis` header, which is what makes that split safe rather than an assumption.
- **`generation_params()` is the backend's own business.** Each backend reports its knobs so the
  pipeline never has to know which ones a given backend has. `remote` renames the wire field
  `seed` to `mesh_seed` on the way out: it shares a telemetry column with local runs, and one
  field under two names is a column nobody can query.
- **Background removal is upstream's step on our weights.** `preprocess_image` cuts the subject
  out and premultiplies it the way the model was trained, so Phase 2 no longer uses
  `rembg`/u2net — that was a TripoSR grey-composite trick for shape-from-shading and it would
  fight this model's own preprocessing. But the checkpoint configures the step as
  `BiRefNet(model_name="briaai/RMBG-2.0")`, and **BRIA RMBG-2.0 is CC BY-NC 4.0** — the class is
  MIT, the weights are not. `pythonsrc/sculptors/background.py` substitutes MIT BiRefNet
  (`ZhengPeng7/BiRefNet`) via `permissive_rembg()`, held open **across**
  `Pipeline.from_pretrained` because upstream builds the matte model eagerly and a swap
  afterwards would already have downloaded the encumbered weights.
  `assert_permissive_matte()` then checks the outcome rather than the mechanism, so an upstream
  reshuffle fails the load instead of silently reverting. Covers `trellis2` *and* `remote` — the
  worker runs this same code. Does **not** cover `pixazo`: that is someone else's deployment,
  and therefore a contract question, not a code one.
- **New CLI/API knobs**: `--sculptor-backend`, `--pipeline-type`
  (`512`|`1024`|`1024_cascade`|`1536_cascade`), `--mesh-seed`, `--smooth`. `--mesh-seed` is
  *not* `--seed`: one reproduces the blueprint, the other the reconstruction, and a single value
  for both would make it impossible to re-sculpt one image two ways. `POST /jobs` accepts
  `pipeline_type` and `mesh_seed`.

### Hosted sculptor (pythonsrc/sculptors/pixazo.py)

`POST {gateway}/trellis-2-image-to-3d/v1/trellis-2-image-to-3d-request`, then poll
`GET {gateway}/v2/requests/status/{request_id}` until `COMPLETED` and download `output.media_url[0]`.
Auth is `Ocp-Apim-Subscription-Key`, not a bearer token.

- **`up_axis = "y"`, unlike every other backend.** The endpoint returns **GLB**, and glTF is
  Y-up — upstream's `to_glb()` swaps Y/Z on the way out precisely because the model's own frame
  is Z-up. trimesh does not undo that, so `postprocess`'s rotation is load-bearing here in a way
  it is not for `trellis2`. Getting it wrong is silent: the part prints lying on its side.
  Overridable per instance via `$P2P_PIXAZO_UP_AXIS` so settling the question empirically does
  not need a redeploy.
- **`image_url` takes a URL, not an upload.** There is no documented upload endpoint, so
  `_resolve_image_url` inlines the blueprint as a `data:` URI by default — zero infrastructure —
  and uses `$P2P_PIXAZO_IMAGE_BASE_URL` when a public bucket or tunnel is available instead.
- **`pipeline_type` → `resolution` is lossy.** The hosted API has no cascade sampler, so
  `1024_cascade` and `1024` both send `resolution=1024`. `generation_params()` records *both* the
  requested pipeline type and the resolution sent, because a collapsed cascade is not the same
  experiment as a native run and nothing after the fact could tell them apart.
- **The charge is booked the moment the gateway accepts the request**
  (`last_generation_cost_eur`), not when a mesh arrives. An accepted generation may be billed
  even if polling times out or the download fails, so booking on delivery would understate
  spend. The failure path persists the cost *and* the `request_id` — the manual-recovery
  handle — to telemetry even when Phase 2 fails, so cost per usable mesh stays computable
  from `phase2_failed` in `generation_params`.
- Unset knobs are **omitted** from the payload rather than sent as null, so the endpoint applies
  its own documented defaults.

### Sculptor worker (services/trellis2_worker/)

FastAPI service holding one backend resident on a GPU. `GET /health` (no auth — a readiness
probe requiring a secret is one nobody runs) reports the loaded model and free VRAM;
`POST /sculpt` takes a multipart image plus optional `backend`/`pipeline_type`/`seed` and returns
mesh bytes with `X-P2P-Up-Axis`, `X-P2P-Model`, `X-P2P-Model-Version`, `X-P2P-Mesh-Format`.

- Requests are **serialised** under one lock: the GPU cannot serve two 4B-parameter
  reconstructions, and `pipeline_type`/`seed` overrides are applied to the *shared instance* and
  restored in a `finally`. A leaked override would silently change every later job's geometry,
  long after the request that set it.
- A request naming a different backend is **refused (409)**, not served by the loaded one — the
  telemetry row would otherwise name a model that never ran.
- A preload failure is logged, not fatal: the worker then answers `/health` with the reason,
  which beats a container that exits on startup.
- Built by `infra/docker/trellis2-worker.Dockerfile` (CUDA 12.4 devel). `TORCH_CUDA_ARCH_LIST`
  must match the deployment GPU or the compiled kernels will not load.

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
  `generation_model_version`, `generation_backend` (see below), `generation_params`,
  `generation_cost_eur`, `generation_duration_s`, `mesh_features`, `printability_score`,
  `printability_verdict`, `printability_report`. All optional, so pre-existing rows stay valid, and
  `db.init_schema()` adds the columns to older databases via `ALTER TABLE`. These exist because
  they cannot be backfilled: after a print finishes, nothing else records which model made the
  mesh or what the call cost. Write them with `db.update_job_generation()` and
  `db.update_job_printability()` — both skip `None` arguments, so cost arriving after the model
  name does not erase it.
- **`generation_cost_eur` is euro, not dollars** (renamed from `generation_cost_usd`;
  `db._PRINT_JOB_RENAMED_COLUMNS` migrates existing databases with `ALTER TABLE RENAME COLUMN`
  *before* the additive pass, so recorded values move rather than being stranded beside a fresh
  empty column). Every hosted endpoint this project has priced bills in EUR, and a figure stored
  in one currency under the name of another cannot be summed later.
- **`generation_backend` has four values, not two**: `local`, `remote_worker`, `hosted_api`,
  `unknown`. `hosted_api` is the only one that sets a cost. `remote_worker` is a self-hosted GPU worker: nothing is billed per call, so
  `generation_cost_eur` stays None while `generation_duration_s` legitimately includes upload and
  queueing. Folding it into `local` makes both numbers unreadable; folding it into `hosted_api`
  implies a cost that does not exist.
- **Swapping the image-to-3D model** (e.g. TRELLIS.2 self-hosted → TRELLIS.2 on fal.ai): set
  `MODEL_NAME`, `MODEL_VERSION`, `BACKEND` and `last_generation_cost_eur` on the sculptor object,
  and report its knobs from `generation_params()`. `pipeline._record_generation()` reads all of it
  off the instance after Phase 2, so a pay-per-generation backend needs no pipeline change to get
  its cost and latency recorded per job.
- **DB** (`db.py`): SQLite wrapper with thread-safe locking; `check_same_thread=False` for use across asyncio tasks.
- **One database, and where it lives.** The telemetry database is
  **`~/.p2p-mesh/telemetry.db` on the host** — always, in every execution mode. Containers
  reach that same file through the `~/.p2p-mesh:/root/.p2p-mesh` bind mount: `HOME` is
  `/root` in the image, so `get_default_db_path()` resolves to the mounted host file
  rather than to anything container-local. The Fernet key for the encrypted config store
  (`.config_key`) sits in that same directory, so one database means one key.

  **Do not set `TELEMETRY_DB_PATH`** in `.env`, in compose, or in a shell that will run
  the server. Leaving it unset is what keeps every process on one file. The only
  legitimate use is pointing a throwaway environment somewhere else — which is exactly
  what `tests/conftest.py` does, redirecting it to a temp directory in `pytest_configure`
  so the suite cannot touch real data.

  This is written down because it went wrong. `.env` used to set
  `TELEMETRY_DB_PATH=/app/telemetry/telemetry.db` and compose mounted a **named volume**
  `p2p-telemetry` there. A named volume is invisible from the host, so container runs
  wrote job rows into a database nobody could see while their artifacts landed in the
  bind-mounted `data/outputs/` — 27 job directories with no matching rows anywhere a
  developer would look. Native runs meanwhile used the default path, so the two modes
  had separate histories and separate encrypted config stores. There is deliberately no
  telemetry volume in compose now, and `infra/scripts/patch_env.py`, which rewrote that
  variable back into `.env` on every run, has been deleted.

  `tests/test_single_database.py` is the regression guard: it fails if compose or
  `.env.template` starts pinning the variable again, or if a telemetry volume reappears.
- **`job_event` has no foreign key onto `print_job`**, so deleting a job leaves its
  events behind. `feedback_funnel()` and `count_job_events()` therefore join `print_job`,
  and `count_orphaned_job_events()` reports the debris. Without the join the pilot's
  headline response rate is computed over jobs that no longer exist — on one real
  database that read as a confident 40% when the honest answer was "no data".
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
`THIRD-PARTY-NOTICES.md`. Four rules keep that grant coherent — the first three have already
been violated once, so treat them as load-bearing rather than aspirational:

- **Never import a GPL/AGPL library in-process** — nor a "source-available, non-commercial" one. `pymeshfix` was removed for exactly this:
  it wraps MeshFix (Attene/IMATI-GE-CNR), whose terms additionally require a negotiated
  contract for commercial use. `Engineer.repair_mesh` now composes trimesh (MIT) for surface
  closing with `manifold3d` (Apache-2.0) for the manifoldness guarantee and boolean union.
- **CuraEngine and OctoPrint are AGPL-3.0 and must stay at arm's length** — CLI subprocess and
  HTTP/socket respectively, never linked or embedded. All FOSS slicers are AGPL/GPL, so
  subprocess isolation is the design, not a workaround. Both are shipped unmodified; the
  written source offer lives in `THIRD-PARTY-NOTICES.md`.
- **Model weights carry licences independent of the library that loads them — and independent of
  the class name.** `rembg` is MIT but its *default* model became BRIA RMBG-2.0, which requires a
  paid commercial agreement; that is why `rembg` was pinned to `2.0.69` **and** `u2net` named
  explicitly while TripoSR was Phase 2. `rembg` is gone, but the same weights came back by a
  second route: `microsoft/TRELLIS.2-4B`'s own `pipeline.json` reads
  `"rembg_model": {"name": "BiRefNet", "args": {"model_name": "briaai/RMBG-2.0"}}`. **An
  explicitly named repo is no protection when the repo someone else named is the encumbered
  one** — read the id, not the class. Phase 2 overrides it (see Sculptor above);
  `tests/test_licensing_guards.py` holds the line. Two rules follow: **do not reintroduce
  `rembg`**, and **do not remove the matte substitution** on the theory that upstream names its
  model explicitly. The remaining live instance of `trust_remote_code=True` is our own MIT
  BiRefNet load — MIT, but still remote code execution; pin a revision with
  `$P2P_BIREFNET_MODEL_ID` (`repo@sha`) before any untrusted deployment.
- **DINOv3 is unavoidable and that is fine — but it carries obligations.**
  `image_cond_model` is `facebook/dinov3-vitl16-pretrain-lvd1689m`, feeding `get_cond`, so it is
  on the shape path and cannot be structurally avoided the way the rasterizer and the matte
  weights can. The **DINOv3 License permits commercial use**; what it requires is attribution
  ("Built with DINOv3", carried in the UI footer, `README.md` and `THIRD-PARTY-NOTICES.md`),
  compliance with its Acceptable Use Policy and trade-control terms, propagation of the licence
  if the weights or a derivative are ever *redistributed*, and acknowledgement in publications.
  The repo is gated, so whoever accepted the terms with the project's `HF_TOKEN` is the licensee.
  **Do not bake DINOv3 weights into a distributed image** — that turns a use into a
  redistribution.
- **Never install nvdiffrast or nvdiffrec.** Upstream TRELLIS.2's documented install line asks
  for both, and both are under the **NVIDIA Source Code License — non-commercial research only**.
  They are the same class of hazard as `pymeshfix`, and harder to spot because GitHub reports the
  licence as `Other` rather than as copyleft. Phase 2 avoids them structurally, not by
  remembering: the shape-only path never calls `o_voxel.postprocess.to_glb()` (the only thing on
  the image→3D path that rasterizes), `trellis2/pipelines/__init__.py` resolves submodules lazily
  so the texturing pipeline and renderers are never imported, and the worker image simply does not
  install them. If a future feature needs textured output, the rasterizer must come from a
  permissive backend (PyTorch3D, BSD-3-Clause) — never from nvdiffrast.

When adding or bumping a dependency, check the package licence *and* any weights it downloads
at runtime, then update `THIRD-PARTY-NOTICES.md`.

## Important Constraints

- The `PYTORCH_ENABLE_MPS_FALLBACK=1` env var must be set **before** any `import torch` — this is why `pipeline.py` sets it at the very top before other imports. It is a Phase 1 concern only now; Phase 2 is CUDA-only and never runs on MPS.
- `Trellis2Backend.__init__` likewise sets `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` and `OPENCV_IO_ENABLE_OPENEXR=1` before the extensions load, matching upstream's own entry points
- `pythonsrc/config.py` is gitignored and must be created from `config.template.py` for native (non-Docker) runs
- `data/` directories including logs, inputs, outputs are all runtime-only and gitignored
- Phase 1 (FLUX) on Docker/CPU takes ~84 minutes; native macOS MPS is ~30 seconds — the MPS-native path is the primary dev workflow on Mac
- Docker images are `linux/amd64` only; on Apple Silicon, Docker Desktop emulates via Rosetta 2. The one exception is `trellis2-worker.Dockerfile`, which is built against a CUDA devel image and only runs on an NVIDIA host
- Phase 2 has **no CPU path at all**. On a machine without an NVIDIA GPU and without `$P2P_SCULPTOR_REMOTE_URL`, `create_sculptor()` raises rather than falling back — there is nothing to fall back to, and a mesh from an unnamed model is worse than an error. Set up the worker (`services/trellis2_worker/README.md`) or use `--skip-sculptor --mesh <path>` to work on Phases 3–5