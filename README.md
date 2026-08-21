# Prompt2Print: Mesh Engine (p2p-mesh)

![Status](https://img.shields.io/badge/Status-Proof_of_Concept_COMPLETE-brightgreen)
![Platform](https://img.shields.io/badge/Platform-macOS_Silicon|Fedora|Windows-gray)
![License](https://img.shields.io/badge/License-Apache_2.0-green)

**p2p-mesh** is the generative engine for the Prompt2Print platform — an end-to-end pipeline that converts a natural language prompt into a physical 3D print.

The system takes a user description and generates a clay-render blueprint image. It then reconstructs the blueprint into a 3D geometry mesh, repairs and scales the mesh for the intended print bed, scores it for printability, and slices it into machine instructions (G-code). Finally, it dispatches the print job to a local 3D printer and continuously monitors telemetry to detect print failures.

**Phases 1 and 3–5 run on your own hardware.** Phase 2 (image→3D) is the exception: TRELLIS.2-4B needs an NVIDIA GPU with ~24 GB of VRAM and compiled CUDA extensions that have no CPU kernels. It runs in-process on a CUDA host, on a self-hosted GPU worker the rest of the pipeline reaches over HTTP, or on Pixazo's hosted endpoint (€0,32 per generation — the only option on an Apple Silicon Mac). See **Sculptor** in [`CLAUDE.md`](CLAUDE.md).

---

## Architecture Overview

| Component         | Location          | Technology        | Purpose                          |
|-------------------|-------------------|-------------------|----------------------------------|
| Visualizer        | `pythonsrc/`      | FLUX.2-klein-4B   | Text → blueprint image           |
| Sculptor          | `pythonsrc/sculptors/` | TRELLIS.2-4B | Image → 3D mesh                  |
| Sculptor worker   | `services/trellis2_worker/` | FastAPI + CUDA | Serves TRELLIS.2 to GPU-less hosts |
| Engineer          | `pythonsrc/`      | manifold3d/trimesh | Mesh repair + scaling            |
| Printability      | `pythonsrc/printability.py` | trimesh/manifold3d | Pre-print geometry scoring + verdict |
| Slicer            | `pythonsrc/`      | CuraEngine        | Mesh → G-code                    |
| Operators         | `pythonsrc/operators/` | REST/HTTP/MQTT | Printer control (OctoPrint/Klipper/Bambu stub) |
| Telemetry         | `pythonsrc/telemetry/` | SQLite/WebSocket/SockJS | Printer state streaming + failure detection |
| Job API           | `server/`         | FastAPI/uvicorn   | Async job orchestration          |
| Web UI            | `web/`            | React/Vite/TS     | Browser-based user interface     |

---

## Repository Structure

```text
p2p-mesh/
├── docs/           # Architecture decisions, operator guides, and protocol notes
├── infra/          # Docker Compose files, Dockerfiles, and deployment scripts
├── pythonsrc/      # Core pipeline: phases 1–5, printability, operators, telemetry
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
- `PIXAZO_API_KEY` for Phase 2 on a machine without an NVIDIA GPU (billed per generation)
- OctoPrint (optional, for OctoPrint printer integration; its bundled virtual-printer plugin is the current simulator)

---

## Quick Start

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

### 4. Test without hardware
From the **Settings** page (`/setup`), start the dockerized OctoPrint simulator. Its virtual-printer plugin is enabled in `data/octoprint/octoprint/config.yaml`, so the full dispatch path — upload, select, start, telemetry, failure detection — runs without a physical machine. There is no Moonraker simulator.

### 5. Drive a printer directly (optional)
The OctoPrint operator has its own CLI, useful for isolating a dispatch problem from the rest of the pipeline:

```bash
python -m pythonsrc.operators.octoprint_operator --file <path> [--url URL] [--key KEY] \
    [--location local|sdcard] [--start] [--watch] [--status] [--dry-run]
```

`--dry-run` validates connectivity without uploading; `--watch` follows the print and reports progress; `--status` only reports current printer state.

---

## Printer Support Matrix

| Firmware              | REST control                             | Telemetry                  | Failure detection                          | Status                                  |
|-----------------------|------------------------------------------|----------------------------|--------------------------------------------|-----------------------------------------|
| OctoPrint             | ✅ Upload, select, start, pause, cancel  | ✅ SockJS                  | ⚠️ Temperature + Z only                    | Supported                               |
| Klipper / Moonraker   | ✅ Full                                  | ✅ JSON-RPC over WebSocket | ⚠️ Field mapping needs repair              | Supported, unverified on hardware       |
| Bambu Lab             | 🔬 Stub — every method raises            | ❌ Not yet                 | ❌ Not yet                                 | Phase 1 requirement (see Roadmap)       |

Two caveats worth stating plainly. **Nothing in this table has been exercised against a physical printer yet** — the OctoPrint virtual-printer plugin is the current stand-in, and real-hardware bring-up is the open Phase 0 item below. And the rules that read `gcode_line` or `extrusion_factor_pct` are Klipper-only, because `OctoPrintCollector` leaves those fields unset.

---

## Telemetry & Failure Detection

The system collects real-time telemetry from active printers — hotend and bed temperatures, Z height, current G-code line, progress and extrusion factor — into a local SQLite database, and streams it to the frontend over WebSocket. When several processes could collect for the same job, the first whose sample lands claims the job and the others stand down, so no row is written twice.

`AnomalyDetector` (`pythonsrc/telemetry/detector.py`) evaluates five rules per sample over a 20-sample history, each firing at most once per job:

1. **Thermal runaway** — hotend target above 150 °C while the actual temperature stays more than 25 °C below it for 5 consecutive samples (a heater or thermistor fault, not overheating).
2. **Clog** — progress past 5% while `gcode_line` does not advance across 10 samples. *Klipper only.*
3. **Layer shift** — Z drops more than 0.5 mm between samples.
4. **Bed adhesion** — Z below 1.0 mm and progress under 10% when the printer goes from printing to error or cancelled.
5. **Extrusion issue** — extrusion factor at or below 10% for 5 consecutive samples. *Klipper only.*

These thresholds are untuned heuristics: they have never been checked against a real failure sequence, which is why re-tuning them against observed data is a Phase 2 item below.

---

## Running Tests

```bash
pytest tests/                                # default: skips anything marked slow
pytest tests/ -m "slow and real_printer"     # needs a real or simulated printer
pytest tests/ -m "slow and full_pipeline"    # needs FLUX + a CUDA GPU or sculptor worker
```

The suite refuses to touch the real telemetry database or spend money: `tests/conftest.py`
redirects `TELEMETRY_DB_PATH` to a temporary directory and sets `P2P_DISABLE_PAID_BACKENDS`
before collection, and the Pixazo backend refuses to construct when that flag is set.
`make test` runs the same suite.

---

## Roadmap

**Target: MVP launch by 31 December 2026**, then a defensible 3D-printing-native product
through 2027. The phases and dates below come from the internal MVP-to-Moat roadmap
(18 August 2026); the status of each item is what the code does today, not what was planned.

Two things are never cut, because they *are* the product: **printability scoring as a
first-class pre-print step**, and the **telemetry capture schema**. A signal has exactly one
moment at which it is knowable — a seed drawn and thrown away cannot be recovered, and "the
printer finished" is not "the part survived" — so everything else sequences around them.

**Compute strategy: rent inference, don't run it.** Phase 2 is the only cost centre. Hosted
generation stays the default through build, beta and probably launch — no idle cost, no GPU
orchestration to build. Self-hosting only becomes cheaper north of roughly 3–5k generations
per month, so actual usage should pull us there rather than a preemptive migration. University
GPU access is reserved for *fine-tuning* (Bet 1), not production serving.

---

### ✅ Phase 0 — Foundation (18–31 August 2026)

- [x] **Phase 1: Visualizer** — text→blueprint (FLUX.2-klein-4B), MPS-native on Apple Silicon (~30 s) or Docker/CPU (~84 min)
- [x] **Phase 2: Sculptor** — TRELLIS.2-4B replaces TripoSR, shape-only O-Voxel path. Three interchangeable backends: in-process CUDA, self-hosted GPU worker, and Pixazo's hosted endpoint (€0,32/generation — the only path on a Mac)
- [x] **Phase 3: Engineer** — mesh repair and scaling on trimesh + manifold3d
- [x] **Phase 4: Slicer** — CuraEngine G-code generation, statistics derived from the E axis rather than Cura's unreliable header
- [x] **Phase 5: Operator** — OctoPrint and Moonraker upload, pre-flight checks, job control
- [x] **Printability gate** *(pulled forward from Phase 1)* — 11 deterministic checks, weighted 0–100 score, `ready`/`risky`/`unprintable` verdict, per-job `printability.json`, persisted to telemetry and served over REST. Advisory by default; `--min-printability` makes it blocking
- [x] **Telemetry capture schema** — blueprint and generation provenance, mesh lineage bracketing repair, slice results (recorded on failure too), engagement events, cost in EUR, single-writer collector arbitration
- [x] **Print-outcome feedback loop** *(pulled forward from Phase 2)* — a verdict prompt in the app shell, `/feedback/*` endpoints, and the rule that a machine write never overwrites a human one
- [x] **Licence compliance** — GPL `pymeshfix` replaced by manifold3d; non-commercial BRIA matte weights substituted with MIT BiRefNet; `nvdiffrast`/`nvdiffrec` structurally excluded; DINOv3 attributed. Enforced by `tests/test_licensing_guards.py`
- [x] **Web UI** — React SPA served by FastAPI: submission, live phase progress, blueprint and mesh preview, G-code preview, telemetry charts, printability report
- [ ] **Real-hardware bring-up** — the whole dispatch path has only ever run against the OctoPrint virtual printer. **This is the open Phase 0 item and the first real integration risk.** Printers arrive at the end of August
- [x] **Bambu decision** — answered: the accessible fleet is Bambu Lab (A1 Mini, A1, X2), which makes `BambuOperator` a hard Phase 1 requirement rather than an optional adapter
- [ ] **University GPU access requests** (KTH + Trento) — filed early only because approval lag is long; the hardware is not needed until Bet 1 in Q1 2027

---

### 🔨 Phase 1 — MVP Core Build (1–30 September 2026)

- [ ] **Bambu MQTT operator** — protocol already documented in [`docs/bambu_protocol.md`](docs/bambu_protocol.md); every method currently raises `NotImplementedError`
- [ ] **Show printability before the user commits to print** — the report is computed and served, but the UI submits jobs with printing already enabled, so the score currently arrives *after* dispatch. This is a launch-gate requirement, not a nicety
- [ ] **Mesh orientation and hollowing correctness** — `orient_for_print` re-orients away from the Z-up frame Phase 2 establishes, and `hollow_mesh` loses millimetre scale. Both fail silently: the part simply prints on its side or at the wrong size
- [ ] **Printer profile → slicer settings** — CuraEngine ignores any profile that is not a `.def.json`, so layer height, temperatures and infill from `pythonsrc/profiles/*.json` never reach it and every machine slices as a default Ender 3
- [ ] **Minimal auth** — a user model, sessions, and `PrintJob` rows tied to a user. No endpoint is authenticated today
- [ ] **Mock-data pipeline toggle** — run the full pipeline from a canned blueprint and mesh, for development on a machine that cannot reach a GPU and should not be billed
- [ ] **Single-colour 3MF export** alongside `.gcode` — *first thing to cut if the phase slips*
- [ ] **LLM prompt expansion** ahead of the existing clay-render template injection — *second thing to cut; the static template is a reasonable fallback*

---

### 📋 Phase 2 — Launch Hardening + Closed Beta (1–31 October 2026)

- [ ] **Benchmark suite** — a fixed 30–50 prompt set (primitives, household objects, mechanical parts, figurines) run weekly, tracking watertight rate, mean printability score, latency and € per generation. Cheap to build: the telemetry schema already captures every input it needs
- [ ] **Closed beta on our own printers**, running continuously — this is where the labelled print-outcome dataset actually starts accumulating
- [ ] **Bounded job queue** — replace fire-and-forget task dispatch, which today has no concurrency limit and no backpressure, with a bounded queue before concurrent traffic reaches it
- [ ] **Continuous integration** — nothing currently runs the licence, cost or database-safety guards automatically; they execute only when a developer remembers
- [ ] **Re-tune `AnomalyDetector` against observed failures** — the thermal rule presently matches every normal heat-up ramp, and the clog rule cannot fire on either firmware. Repair precedes tuning
- [ ] **Printer setup / connection-test wizard** — firmware detection, profile selection, a connection test that works for every firmware, first-print walkthrough
- [ ] **Decision: no billing at launch.** Ship free or waitlisted; payments come after retention is validated, not before

---

### 🚀 Phase 3 — Public Launch (1 November – 20 December 2026)

- [ ] Recompute hosted-versus-self-hosted economics against real beta volume — a waitlisted launch will likely stay well under the crossover
- [ ] Final benchmark pass; load-test the job queue
- [ ] Terms of service and privacy policy with an explicit consent flow for "we use your print outcomes to improve the model" — the disclosure has to be right from day one rather than retrofitted onto data already collected
- [ ] **Launch**, with buffer before 31 December for the inevitable first-week fires

**Launch gate — all four must hold before Phase 3 starts:**

- ≥ 90% of generated meshes watertight without manual intervention
- printability score shown to 100% of users before they can download or slice
- a published, benchmarked end-to-end latency figure
- at least one full print-outcome loop closed on real hardware (generate → print → verdict recorded)

---

### 🔭 Phase 4 — Moat-building (Q1–Q2 2027)

Three bets, in dependency order — each needs the previous one's data or infrastructure:

1. **Bet 2 groundwork first.** With a few months of labelled (mesh features → predicted score →
   actual outcome) rows, train a gradient-boosted tree — not a deep model — to check whether the
   deterministic printability score actually predicts reality, and to start flagging risky
   generations. Needs data, not a training GPU.
2. **Bet 1 — print-aware conditioning.** Fine-tune with target-process conditioning (FDM/SLA/SLS
   wall thickness, overhang limits) on our own outcome data. This is what the university GPU
   access is for, and it is genuine research: budget a full quarter.
3. **Bet 3 — multi-part assembly / auto-split.** Longest horizon, lowest confidence; sequenced last.

Alongside the bets: an SLA/resin printability profile (`ProcessProfile` is already parameterised,
so this is a new profile rather than new check code), deeper Bambu Studio / OrcaSlicer
integration, multi-colour 3MF mapping, and a labelled failure-event export for supervised
failure prediction.

---

### 🌱 Phase 5 — Scale (2027+)

- Move to self-hosted or reserved GPU infrastructure once volume crosses the crossover threshold
- Hire the first dedicated ML engineer once Bet 1/2 results justify it
- **Textured output** — TRELLIS.2 already produces it and the shape-only path discards it. Blocked on a permissively licensed rasterizer: upstream's `to_glb()` needs one and nvdiffrast is non-commercial (see [`THIRD-PARTY-NOTICES.md`](THIRD-PARTY-NOTICES.md))
- **User accounts + multi-tenant** — per-user job history and telemetry namespacing for B2B deployment
- **Multi-printer profile registry** — community-importable, plugin-style profile management
- **Slicer abstraction layer** — pluggable backend (CuraEngine, PrusaSlicer CLI, OrcaSlicer CLI) selectable per profile
- **Local agent (Rust)** — native bridge for mDNS printer discovery and direct G-code streaming, without requiring a desktop app

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
