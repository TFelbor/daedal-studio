# Daedal Studio — archived

![Status](https://img.shields.io/badge/Status-Archived_(Nov_2026)-lightgrey)
![License](https://img.shields.io/badge/License-Apache_2.0-green)

**Daedal Studio closed in November 2026. This repository is its complete, working
codebase, published as an archive under the Apache License 2.0.** It is not
maintained: issues and pull requests are closed, and nothing here is a service you can
sign up for.

Daedal designed custom-fit 3D-printed organizers for trading card and board games —
deck boxes sized to *your* sleeves and card count, token trays, card dividers and
board-game box inserts — and drove them through printability checks, slicing and a
human-confirmed printer dispatch. It was built by **Tytus Felbor**, **Alberto García
de la Torre** and **Brandon Perrone** between February and October 2026, starting life
as *Prompt2Print*, a text-to-3D tool, and pivoting on 31 August 2026 to parametric
organizers under one rule:

> **The language model interprets words. It never produces geometry.**

Why it closed, what we decided and avoided, and what we would do differently is
written up in a five-part series: **https://substack.com/@tytusfelbor**.

## What is worth taking from here

| If you want… | Look at |
|---|---|
| A parametric CSG engine with per-feature dimensional assertions | `pythonsrc/organizer/` — spec → `manifold3d` geometry for four archetypes, every designed feature measured back to ±0,05 mm in CI (405 variants) |
| Sourced card, sleeve and game-box dimensions | `pythonsrc/organizer/dimensions.py`, `pythonsrc/data/game_boxes.v1.json` (provenance on every value), `docs/dimension-kb-research.md` |
| Driving CuraEngine from Python without the silent failures | `pythonsrc/slicer.py` and `docs/SYSTEM-AS-BUILT.md` § Slicer — five command-line facts, each once wrong |
| An AI agent pipeline that turns GitHub issues into reviewed PRs | `docs/PIPELINE.md`, `.github/workflows/claude-*.yml`, `CLAUDE.md` — and the trust boundary that keeps it honest |
| Licence policy enforced as tests | `pythonsrc/licence_policy.py`, `tests/test_licensing_guards.py`, the committed tree in `licenses/`, `docs/deferred-legal-tasks.md` |
| Why every design decision is what it is | `docs/SYSTEM-AS-BUILT.md`, indexed at the foot of `CLAUDE.md` |

By the numbers: 469 commits on `main`, 129 merged pull requests (30 of them opened and
implemented by the Claude agent pipeline, every merge a human decision), ≈ 2 165 test
functions (≈ 5 000 cases with parametrisation), 76,6 % line coverage, more lines of
test code than product code.

## Try the engine in two minutes (CPU only)

The organizer engine needs no GPU, database or printer:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-mac.txt   # or requirements-linux.txt
python -m pythonsrc.organizer example deck_box > deck.json
python -m pythonsrc.organizer compile deck.json --out deck.stl
python -m pythonsrc.organizer measure deck.json deck.stl   # 26/26 features within ±0,05 mm
```

Edit `deck.json` (card count, sleeve, `fit_intent`) and compile again. The full
pipeline — server, web app, slicer, printer simulator, telemetry — is documented in the
original README below and needs Docker and PostgreSQL.

## What is not here

- **Model weights.** The benched generative branch (FLUX.2-klein-4B → TRELLIS.2-4B)
  downloads them at runtime under their own licences; see `THIRD-PARTY-NOTICES.md`.
- **Internal business documents** — strategy reviews, roadmap, PRD, pricing and partner
  correspondence. References to them in the code say so.
- **Credentials.** The Claude workflows need a `CLAUDE_CODE_OAUTH_TOKEN` this repository
  does not have, and GitHub Actions is disabled on the archive.

## Licence

Apache License 2.0 — see [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE). Third-party
components keep their own licences; [`THIRD-PARTY-NOTICES.md`](THIRD-PARTY-NOTICES.md)
lists them, including the two AGPL-3.0 tools (CuraEngine, OctoPrint) this code only
ever calls as a separate process or over HTTP.

---

# Original README (as the project left it, October 2026)


**ds-mvp** is the engine for the Daedal Studio platform: **custom-fit tabletop & TCG
organizers from a prompt** — deck boxes sized to *your* sleeves and card count, token
trays sized to *your* dice, box inserts sized to *your* game — printed on your machine
or ours, dimensionally exact by construction.

The governing rule, from the PRD:

> **The language model interprets words. It never produces geometry.**

An LLM is allowed to decide that "double-sleeved Commander deck" means *100 cards ×
0,72 mm per sleeved card*. It is never allowed to decide how thick the wall next to
those cards is. That is arithmetic, done by tested code: a structured spec, compiled by
a parametric archetype library into watertight geometry, validated by a printability
gate, sliced with the target printer's real profile, and dispatched only after a person
confirms the target. Prompt → preview is sub-second geometry plus one LLM call
(~€0,002), not a GPU pipeline.

**Two paths through one pipeline:**

- **The product path (being built now):** prompt → spec extraction → parametric compile
  → Phases 3–5 (validate → gate → slice → dispatch). The PRD and roadmap were internal
  planning documents and are not published with this archive.
- **The generative branch (benched):** prompt → blueprint image (FLUX.2-klein-4B) →
  image → 3D mesh (TRELLIS.2-4B) → Phases 3–5. Fully built, off the critical path, and
  returning later as the engine behind decorative personalization (PRD F13/F14).
  Phase 2 needs an NVIDIA GPU (~24 GB VRAM), a self-hosted GPU worker, or Pixazo's
  hosted endpoint (€0,32 per generation — the only option on an Apple Silicon Mac).

Everything from Phase 3 onward — mesh validation, the printability gate, CuraEngine
slicing with real profile translation, the dispatch gate, telemetry capture and failure
detection — is shared by both paths and is the half competitors skip. The parametric
path enters through a seam that already exists:
`--skip-visualizer --skip-sculptor --mesh <path> --no-scale`.

**Start with [`ARCHITECTURE.md`](ARCHITECTURE.md)** for the phase-by-phase map: what
runs each phase, the pinned version, the hardware it needs, and what it has been
measured to cost. The resolved dependency tree for every image is committed under
[`licenses/`](licenses/README.md) and regenerated by CI. Why each design decision is
what it is lives in [`docs/SYSTEM-AS-BUILT.md`](docs/SYSTEM-AS-BUILT.md), indexed from
[`CLAUDE.md`](CLAUDE.md).

---

## Architecture Overview

| Component         | Location          | Technology        | Path | Purpose                          |
|-------------------|-------------------|-------------------|------|----------------------------------|
| Composer (spec + archetypes + dimension KB) | `pythonsrc/organizer/` *(in build)* | LLM extraction + manifold3d CSG | product | Prompt → structured spec → exact geometry |
| Engineer          | `pythonsrc/`      | manifold3d/trimesh | shared | Mesh validation, repair (generative only), seating |
| Printability      | `pythonsrc/printability.py` | trimesh/manifold3d | shared | Pre-print geometry scoring + verdict |
| Slicer            | `pythonsrc/`      | CuraEngine        | shared | Mesh → G-code with real profile translation |
| Operators         | `pythonsrc/operators/` | REST/HTTP/MQTT | shared | Printer control (OctoPrint/Klipper/Bambu stub) |
| Telemetry         | `pythonsrc/telemetry/` | PostgreSQL (Supabase)/WebSocket/SockJS | shared | Printer state streaming + failure detection |
| Job API           | `server/`         | FastAPI/uvicorn   | shared | Async job orchestration, human gates |
| Web UI            | `web/`            | React/Vite/TS     | shared | Job submission, previews, printer control |
| Visualizer        | `pythonsrc/`      | FLUX.2-klein-4B   | benched | Text → blueprint image |
| Sculptor          | `pythonsrc/sculptors/` | TRELLIS.2-4B | benched | Image → 3D mesh |
| Sculptor worker   | `services/trellis2_worker/` | FastAPI + CUDA | benched | Serves TRELLIS.2 to GPU-less hosts |

---

## Repository Structure

```text
ds-mvp/
├── docs/           # PRD, roadmap, pivot brief, audits, operator guides, protocol notes
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
- OctoPrint (optional, for OctoPrint printer integration; its bundled virtual-printer
  plugin is the current simulator)
- **Generative branch only:** `HF_TOKEN` (Hugging Face) for FLUX weight download; an
  NVIDIA GPU + Container Toolkit, or `PIXAZO_API_KEY` for hosted Phase 2 (billed per
  generation). The parametric path needs none of these.

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
docker compose -f infra/docker-compose.yml build ds-base
docker compose -f infra/docker-compose.yml build

# Alternatively, use the automated Makefile convenience target:
make build


# Copy and edit environment/config files
cp .env.template .env    # edit with printer settings (HF_TOKEN only for the generative branch)
```


### 2. Start the Server + Web UI
```bash
# Build frontend first (one-time, or after UI changes)
cd web && npm install && npm run build && cd ..

# Start API server (serves web UI on http://localhost:8000)
docker compose -f infra/docker-compose.yml up api-server
```
Open **http://localhost:8000** — the web UI handles job submission, live phase tracking, previews, and printer control.

### 3. Run the pipeline

From an organizer spec (the parametric path — see `pythonsrc/organizer/`):

```bash
python -m pythonsrc.organizer example deck_box > data/inputs/deck.json
docker compose -f infra/docker-compose.yml run --rm pipeline-runner python pythonsrc/pipeline.py --spec /app/data/inputs/deck.json --print --start-print
```

`--spec` compiles the spec as Phase 2, then Phase 3 **asserts** the mesh is a solid and
measures every designed feature back off the engineered mesh to ±0,05 mm — it never
repairs or scales it, and a miss fails the run with `dimension_report.json` beside the
mesh. `POST /jobs` accepts the same spec as `"spec"` and records `size_source="spec"`.

On a mesh of your own whose dimensions are final:

```bash
docker compose -f infra/docker-compose.yml run --rm pipeline-runner python pythonsrc/pipeline.py "deck box" --skip-visualizer --skip-sculptor --mesh /app/data/inputs/box.stl --no-scale --print --start-print
```

`--no-scale` means "these dimensions are final" — Phase 3 repairs and seats the mesh
but never resizes it.

Or run the generative branch from a prompt:

```bash
# macOS Apple Silicon (Phase 1 native, rest in Docker)
make phase1-native PROMPT="a ceramic vase"

# Docker (any platform)
docker compose -f infra/docker-compose.yml run --rm pipeline-runner python pythonsrc/pipeline.py "a ceramic vase" --print --start-print
```

### 4. Test without hardware
From the **Settings** page (`/setup`), start the dockerized OctoPrint simulator. Its virtual-printer plugin is enabled in `data/octoprint/octoprint/config.yaml`, so the full dispatch path — upload, select, start, telemetry, failure detection — runs without a physical machine. There is no Moonraker simulator (building one is a roadmap item).

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
| OctoPrint             | ✅ Upload, select, start, pause, cancel  | ✅ SockJS                  | ⚠️ Temperature + Z + clog (file position)  | Supported                               |
| Klipper / Moonraker   | ✅ Full                                  | ✅ JSON-RPC over WebSocket | ⚠️ Field mapping needs repair              | Supported, unverified — no test target yet (Alberto, Trento) |
| Bambu Lab             | 🔬 Stub — `connect()` handshakes, all six actions raise | ❌ Not yet | ❌ Not yet                                 | M1 requirement — KTH machine (Tytus); protocol in [`docs/bambu_protocol.md`](docs/bambu_protocol.md) |

Two caveats worth stating plainly. **Nothing in this table has been exercised against a
physical printer yet** — the OctoPrint virtual-printer plugin is the current stand-in,
and real-hardware bring-up starts when the KTH Bambu and the Trento printer arrive. And
the `extrusion_factor_pct` rule is still Klipper-only.

---

## Telemetry & Failure Detection

The system collects real-time telemetry from active printers — hotend and bed temperatures, Z height, current G-code line, progress and extrusion factor — into the telemetry database (PostgreSQL on Supabase, `DS_DATABASE_URL`), and streams it to the frontend over WebSocket. When several processes could collect for the same job, the first whose sample lands claims the job and the others stand down, so no row is written twice.

`AnomalyDetector` (`pythonsrc/telemetry/detector.py`) evaluates five rules per sample over a 20-sample history, each firing at most once per job:

1. **Thermal runaway** — hotend target above 150 °C while the actual temperature stays more than 25 °C below it for 5 consecutive samples (a heater or thermistor fault, not overheating).
2. **Clog** — progress past 5% while `gcode_line` does not advance across 10 samples.
3. **Layer shift** — Z drops more than 0.5 mm between samples, while printing.
4. **Bed adhesion** — Z below 1.0 mm and progress under 10% when the printer goes from printing to error.
5. **Extrusion issue** — extrusion factor at or below 10% for 5 consecutive samples. *Klipper only.*

These thresholds are untuned heuristics: they have never been checked against a real failure sequence, which is why re-tuning them against observed data is a roadmap item.

On the product path this telemetry closes a loop no competitor has: **spec → print →
fit verdict**. "Printed successfully" and "fits as intended" are different questions,
and the outcome-feedback funnel asks the second.

---

## Running Tests

### What the suite needs before it will run

Three things beyond the Python packages, and the suite stops with a message naming the
missing one rather than failing halfway:

- **The local config and the runtime directories.** `pythonsrc/config.py` is gitignored —
  it holds machine-specific paths — and `pipeline.py`, `slicer.py` and `engineer.py`
  import from it at module scope, so a fresh checkout cannot even collect without it.
  `data/` is gitignored too.

  ```bash
  cp pythonsrc/config.template.py pythonsrc/config.py
  mkdir -p data/inputs data/outputs data/logs
  ```

- **A PostgreSQL the suite may administer.** The telemetry database is PostgreSQL
  (Supabase) in every deployed mode, so the tests run against PostgreSQL too — a SQLite
  stand-in would pass while the production driver, types and SQL went untested. Either
  set `DS_TEST_DATABASE_URL` to a database the suite may create and drop schemas in, or
  have Docker running and `tests/conftest.py` will start a throwaway `postgres:17-alpine`
  on a random loopback port and remove it at the end (`DS_TEST_POSTGRES_IMAGE` overrides
  the image). Isolation is a schema per test, carried in the URL as
  `options=-csearch_path=…`, so `TelemetryDB` needs no test-only knob. See
  [`tests/testing_postgres.py`](tests/testing_postgres.py).

- **A `CuraEngine` on `PATH`.** `CuraSlicer.__init__` refuses to construct without the
  binary, including in the tests that stub the call — but nothing in the default
  selection actually executes it, so a stand-in is enough. CI installs
  [`infra/ci/curaengine_stub.sh`](infra/ci/curaengine_stub.sh) under that name, which
  exits 70 if it is ever really invoked rather than faking a successful slice.

### The commands

```bash
pytest tests/                                   # the default selection — what CI runs
pytest tests/test_db.py                         # one file
pytest tests/test_db.py::test_insert_retrieve_job   # one test
pytest tests/ -m "slow and real_printer"        # needs a real printer or the OctoPrint simulator
pytest tests/ -m "slow and full_pipeline"       # needs FLUX weights plus a CUDA GPU or a reachable sculptor worker
make test                                       # pytest tests/ -v
make test-slow                                  # pytest tests/ -v -m "slow and real_printer"
```

`pytest.ini` carries `-m "not slow"` in its `addopts`, so **`pytest tests/` is already the
selection CI runs** — it deselects everything that needs weights, a GPU or a printer. That
is the command that must pass before a PR opens; the two marker-selected runs above are
opt-in and need hardware this repository cannot assume. Six markers are declared:
`integration` (a running FastAPI server, no printer), `slow` (over 30 seconds),
`real_printer`, `full_pipeline`, and two that select nothing on the command line and are
not meant to. `dimensional_sweep` labels one case of one archetype's declared dimensional
envelope so `tests/conftest.py` can tally the run per archetype; see **What CI runs**
below. `prompt_jobs_benched` opts a module out of the suite-wide `ALLOW_PROMPT_JOBS`
default: `POST /jobs` refuses a job carrying no spec, because the shipping path is the
parametric organizer and the generative one is benched, but most of this suite predates
that and posts a prompt job as the generic way to reach the pipeline.
`tests/conftest.py::_generative_path_open` opens the capability for those modules, and
the marker is how `tests/test_prompt_jobs_benched.py` declines it and sees the refusal
production sees.

The `slow and real_printer` selection is the only place the **real** slicer and a printer
are exercised; the default selection runs against a CuraEngine stub.
`tests/test_spec_job_end_to_end.py` takes one parametric spec from `POST /jobs` through
CuraEngine and the dispatch gate to a telemetry row, and skips — naming which of Docker,
the built pipeline image, the slicer inside it or the OctoPrint simulator is absent —
rather than failing. [`docs/RUNBOOK-spec-job.md`](docs/RUNBOOK-spec-job.md) is the same
run by hand, for when you need to watch it.

### The frontend

```bash
npm --prefix web ci
npm --prefix web run build   # tsc -b && vite build — the type check as well as the bundle
npm --prefix web run lint    # ESLint
```

There is no JavaScript test runner in this repository: `npm run build` is the check,
because it is `tsc -b` first and the API server image serves `web/dist/`, so a build that
only breaks in production is a server that starts and then 404s the whole app. `npm run
lint` currently **fails on 27 pre-existing errors** unrelated to any new change, which is
why CI runs it `continue-on-error` — a gate that is red the day it lands teaches everyone
to ignore the red. Do not treat a red lint as a reason to stop; do leave it no redder than
you found it.

### What CI runs

[`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs three Python steps on every
push and pull request, then the frontend build:

```bash
pytest tests/test_licensing_guards.py tests/test_licence_data.py                          # licence guards
pytest tests/test_organizer_dimensional_accuracy.py tests/test_deck_box.py tests/test_engineer_assert.py tests/test_archetype_registry.py  # dimensional accuracy (PRD N1)
pytest tests/                                                                             # the whole default selection
```

The first two are subsets of the third, named separately so they are legible from the job
list without opening a log. A licence violation is the one class of defect that cannot be
fixed after a release, and the ±0,05 mm dimensional claim is the product's promise.

The dimensional step sweeps **every registered archetype** over the envelope its own
module declares (`envelope()` in each `pythonsrc/organizer/archetypes/*.py`) and ends
with one line per archetype:

```
-------------------------- dimensional sweep (PRD N1) --------------------------
card_divider: 324/324
deck_box: 495/495
token_tray: 160/160
```

A missing line is the failure that matters and the one a total would hide: an archetype
added without an envelope compiles, is offered in the composer and reaches a printer
while no mesh it produced has ever been measured. `tests/test_archetype_registry.py`
joins the step because it refuses that module at the same moment as one missing
`measure`.

### What the suite refuses to touch

`tests/conftest.py` does its work in `pytest_configure` — the last hook before collection —
because several modules construct a `TelemetryDB` at *import* time, which no fixture can
get in front of. Five things are put out of reach for the run:

- **The real telemetry database.** `DS_DATABASE_URL` is rewritten to a schema this run
  created and will drop. Two test modules run `DELETE FROM print_job`, and the SQLite-era
  suite once destroyed 312 real job rows exactly that way.
- **Money.** `DS_DISABLE_PAID_BACKENDS=1` is set and `PIXAZO_API_KEY` removed from the
  environment; the hosted Phase 2 backend refuses to construct under that flag, and it
  survives into the pipeline container, which a monkeypatch could not.
- **The Fernet key.** `DS_CONFIG_KEY_PATH` moves to a temporary directory — the real key
  decrypts `HF_TOKEN` and `OCTOPRINT_API_KEY`.
- **The Docker daemon, via the shared `SimulatorManager`.** The server's shutdown hook
  stops the OctoPrint simulator, and every test entering a `TestClient` context fires it,
  so a full run used to stop a developer's simulator mid-session.
- **`data/inputs/blueprint.png`.** A live artifact three tests write to and delete; it is
  moved aside before collection and moved back afterwards.

A run killed hard enough to skip that teardown leaves the throwaway database behind:
`docker rm -f $(docker ps -aq -f name=ds-mvp-test-pg-)` clears it.

---

## Roadmap

**The plan of record was the internal roadmap** (§0.1
onward, not published): progress stages Phase 0–5, labelled with the PRD's milestones M0–M3. **Beta
launch = Phase 4 (M3)**: the pipeline is not "ready" until direct-to-printer handoff works —
Bambu (KTH) and OctoPrint/Moonraker (Trento) — alongside spec extraction, the archetype
library, the dimension KB, the annotated mobile preview, and the test-fit coupon.

Three things are never cut, because they *are* the product: the **spec schema + the
archetype library with its manifold and dimensional CI**, **printability scoring as a
first-class pre-print step**, and the **telemetry capture schema** with the fit-verdict
feedback loop. Everything else sequences around them.

Progress at a glance, as it stood when the project closed (mirrored from roadmap §0.3):

### ✅ Phase 0 — Foundation (18–31 August 2026)

- [x] Five-phase pipeline, prompt → physical print (FLUX → TRELLIS.2 → repair → CuraEngine → dispatch) — now the benched generative branch
- [x] Printability gate — 11 deterministic checks, weighted score, verdict, per-job report
- [x] Telemetry capture schema — provenance, mesh lineage, slice results, engagement, single-writer collectors
- [x] Outcome-feedback funnel — machine never overwrites human; `dev`/`declined` bucketed out
- [x] Dispatch gate + blueprint gate — durable human-in-the-loop pauses that survive restarts
- [x] OctoPrint operator verified against the dockerized virtual printer
- [x] Licence discipline — policy-as-code guards, committed dependency tree, CI regeneration
- [x] Database self-defence — integrity checks, rotating verified snapshots, off-disk mirror
- [x] Web UI — submission, live phases, previews, telemetry, printability report
- [x] Rename to Daedal Studio — banners, env vars, worker headers moved in one commit
- [x] `--no-scale`: Phase 3 honours spec-final dimensions (PR #40 — scaling half of N1)
- [ ] Real-hardware bring-up — first print on a physical machine (Bambu @ KTH, printer @ Trento); printers arrived ~2 Sep
- [x] ~~University GPU access requests filed~~ — dropped 3 Sep: the Trento request was rejected (28 Aug) and it is moot after the pivot

### ✅ Phase 1 — Capability spike (PRD M0 · 1–14 September 2026)

- [x] Kernel decision recorded — `manifold3d` now, `build123d`/OCCT when fillets earn the review (`ARCHITECTURE.md`)
- [x] Spec schema — `pythonsrc/organizer/spec.py`, JSON-serialisable, diffable (PR #46, 2026-09-03)
- [x] First archetype: deck box, spec → mesh → Phases 3–5 via the `--spec` seam (authored in Claude Code against `manifold3d`, source frozen) — `pipeline.py --spec`, kernel `manifold3d` (PR #46, 2026-09-03)
- [x] Repair-assertion path: assert watertight + per-feature dimensions on spec meshes, `size_source="spec"` — `Engineer.process(repair_mode="assert")`, `dimension_report.json` after Phase 3, `JobRequest.spec` (PR #47, 2026-09-03)
- [x] Dimensional-accuracy CI — spec → exported-mesh error per critical feature — `tests/test_organizer_dimensional_accuracy.py`, 405-spec envelope on the exported STL at ±0,05 mm per feature (`DEFAULT_TOLERANCE_MM`) + Phase 3 assert path, its own CI step (PR #47, 2026-09-03)
- [x] `feat/ui-redesign-pivot` merged into `main` — PR #48, 2026-09-04. The four boxes above were ticked on `main` before the code was there; they are now true of `main`
- [x] One spec job end to end (`POST /jobs` → CuraEngine → OctoPrint simulator → telemetry row) — **run by hand on the Mac 2026-09-10 (#110), job `b6af18fa-2ba6-4e16-9c84-6151d5f79ebd`**, and `pytest tests/test_spec_job_end_to_end.py -m "slow and real_printer"` passes 8/8 on that machine. The row: `size_source="spec"`, `generation_model="organizer/deck_box"` v1 `local` with no `generation_cost_eur`, every `blueprint_*` NULL, `repair_report` `repair_method="asserted"` / `scale_applied=false` / `scale_axis="preserved"` with `dimension_check.within_tolerance=true`, `printability_verdict="ready"` at 100,0, `slice_status="success"` with 472 layers and 8,73 m of filament off the E axis, and `dispatched_printer_url="http://localhost:5001"` after a person confirmed the gate. Phase 3 measured 19/19 designed features to within 0,000005 mm of the spec against `DEFAULT_TOLERANCE_MM` of 0,05. Outcome recorded `dev`, which is what that verdict is for — a verification print must not sit in the pilot's success-rate denominator. **Five defects only the real run could find**, each fixed with a regression test in the same PR: the server forwarded a printer profile by *name* where `pipeline.py` resolves a *path*, so Phase 4 died on every job (`Printer definition not found: ender3.json`); `run_operator.py` never put the repository root on `sys.path`, so every confirmed dispatch raised `ModuleNotFoundError: No module named 'pythonsrc'` inside the api-server image; `environment: ${DS_DATABASE_URL:-}` shadowed the `env_file` carrying it, because compose reads its interpolation `.env` from `infra/` and not from the repository root; `api-server` had no `env_file` at all; and a bare `~/.ds-mvp` bind mount resolved to the api-server container's own `/root` when it launched the pipeline (`mounts denied`), now `${HOST_HOME:-~}`. The last three are `make up`-only, which is why neither the suite nor the `mps_native` path had ever seen them. `docs/RUNBOOK-spec-job.md` is the same run by hand and `tests/test_runbook_spec_job.py` re-derives every command, service, endpoint, column and filename it names from the source

### 📋 Phase 2 — Internal alpha (PRD M1 · 15 September – 10 October 2026)

- [x] Token tray + card divider archetypes — **both done**. Card divider (PR #104, 2026-09-10): `pythonsrc/organizer/archetypes/card_divider.py`, a `Divider` spec section, one extruded outline, seven measured features, its own 324-spec envelope sweep, `expected_components=1`, gate 100 / `ready`. What it also settled: `archetypes/common.py` for the rules that are not about one shape, an absent optional section omitted from the canonical form so an added archetype moves no existing `spec_hash`, and the UI's archetype strip corrected to the archetypes the engine actually has. Token tray (issue #84, 2026-09-13): `pythonsrc/organizer/archetypes/token_tray.py`, one open body, a regular grid of square-cornered pockets with `process.wall_mm` dividers, a `Tray` spec section carrying `columns` alone (the rows follow from the compartment count), `ARCHETYPE_WALL_MM["token_tray"] = 1.6` — the top of the audited 1,2–1,6 mm band, thinner than the deck box's 2,4 mm, which is its lid's arithmetic. What it settled, and what makes it the composition wedge rather than a third shape: **`Compartment.contents` is a `CardStack | Pocket` union and `compartments` is finally plural**, told apart by the keys it carries rather than by a `kind` discriminator, which would have moved every stored `spec_hash`; **a pocket's millimetres are typed, not resolved** — `docs/dimension-kb-research.md` §4 sources die *sizes* without sourcing the clearance around one, so a 16 mm d6 preset would be a sourced number plus an invented one and `Pocket.source` carries provenance instead; and **`archetypes.required_measurements` now prefers a module's `measured_features(spec)`**, because a tray's feature list grows with its grid (30 for a 2 × 3, 37 for a 4 × 2) and a fixed tuple would have reported *within tolerance* with every pocket unchecked. 160-case envelope (grids × pocket sizes × walls × floors) on the exported, reloaded STL at ±0,05 mm, plus Phase 3's assert path; `expected_components=1`, gate 100 / `ready`. **Not** in v1: ragged grids, per-pocket heights, finger cutouts and rounded corners — the first two belong to the box-insert archetype, the last two to their own issues
- [x] Fit-offset determinism ~~(printer profile as a recorded compile input)~~ — **decided 2026-09-17 (owner): offsets stay in the spec, option (b), NOT a compile input**, and the code half landed 2026-09-22 (issue #89). `ProcessProfile` carries the fit fields as the source the composer pre-fills from — `spec_hash` does not change meaning, `generation_params` grew no second hash input, and the same-spec-same-STL-bytes invariant stands unchanged, because **no spec class gained a field**: the profile supplies *values* for `lid.clearance_mm`, `process.cavity_clearance_mm` and `process.stack_slack_mm`, which existed already. What it settled, and most of it is about where a number is allowed to be: **the sourced table is its own stdlib-only module** (`pythonsrc/fit_offsets.py`) because the api-server image installs no numpy, trimesh or scipy and therefore cannot import `printability` — so the composer's pre-fill and the printability scorer read four profile keys through one reader rather than two that can disagree, which is `_profile_build_volume`'s rule applied again; **the pre-fill happens at `POST /organizer/resolve`**, the option the decision preferred, so `spec.py` took no change at all and this issue never joined the organizer queue (#152, #153, #155, #157 all edit it); **the compiler cannot reach an offset**, asserted by grep over `pythonsrc/organizer/` rather than left as a convention, so (a) is unreachable and not merely unimplemented; **a cavity clearance is an *offset* and the other two are absolute**, because `fit_intent` already decides the cavity and a profile stating it outright would silently overrule the one word a person actually chooses; **blank in the composer means the printer's figure, not the schema's** — the only field group in that form where it does — which needs no has-this-been-touched flag and re-resolves itself when the intent moves; and **`stack_slack_mm` is uniform across every bundled profile on purpose**, because what it absorbs is sleeve variation rather than the machine (§2 keeps a 120-vs-130 µm disagreement on one line of Dragon Shield alone) — it is a field so the Phase 4 coupon loop has somewhere to put a measured figure, and the docstring says it carries none today. Two classes, `tuned` (Bambu P1S) and `desktop` (Ender 3, Anycubic Mega S, Klipper test), each profile naming its class and `tests/test_fit_offsets.py` binding the name to the sourced row. **The bands are sourced and the placement inside them is not, and the file says so in those words**: §5's 0,2–0,4 mm friction lip and §3's 1,5–2 / 4–6 mm clearances are citations, §6's ±0,1 mm tuned and ±0,5 % / ±0,5 mm desktop accuracies are citations, and the mapping of the second onto the first is this project's reasoning. The `desktop` cavity allowance is the one number with two sources behind it — +0,5 mm is §6's floor, and added to the intents it lands snug at 2,0 and easy at 4,5 mm, both inside §3's own bands. **The finding worth keeping is a negative one**: no figure in a 0,2–0,4 mm friction band survives §6's ±0,5 mm desktop floor, so a lid designed to any clearance in it can print interference-fit on a machine at the bottom of its sourced accuracy. That gap is not closable by choosing a better default, which is precisely what the Phase 4 coupon and the calibration loop exist to measure — this table is the prior they start from, not the answer they replace. Under (b) nothing else in a finished row says which machine's figures were on screen, so `generation_params.fit_profile` records the profile, the version and what it *offered* (never what the spec chose — the spec is that record), which is what makes cohort 1's fit reports joinable at all. **The tripwire that reopens this** is closed-beta evidence that users routinely print one design across several printers and expect each to fit; watch for it in cohort 1
- [x] Manifold CI sweep across every archetype's parameter envelope — 2026-09-15 (PR #137, issue #85). Each archetype module declares its own `envelope()`; one parametrize drives 979 specs (495 deck boxes, 324 dividers, 160 trays) and the CI step ends with one line per archetype. A module registered without an envelope fails by name — the sweep is what makes an archetype an archetype
- [x] 3MF export (+ `lxml` in `requirements-base.txt`, STL/3MF download endpoint) — 2026-09-09. Phase 3 writes `engineered_mesh.3mf` beside the `.stl` on every run (`Engineer.export_mesh`; a spec run's 3MF measures the same as its STL to ±0,05 mm), `GET /jobs/{id}/download?format=gcode|stl|3mf` serves all three with the format on the `download` event, and the finished-job view offers them. **Bambu Studio acceptance is still untested** — nobody has opened a produced 3MF in it
- [x] Dispatch path generalised beyond OctoPrint — operator monitor loop, per-firmware credentials through the gate — 2026-09-16 (PR #146, issue #74). One state vocabulary across three firmwares, the monitor loop reads every one of them and picks its collector, and an operator says which firmware it is rather than being guessed at by `isinstance`
- [x] Spec submit wired in the UI — archetype strip + spec panel → `POST /jobs` — 2026-09-12 (PR #127, issue #76)
- [x] Chamfer + vertical-fillet primitives in `compiler.py` — 2026-09-13 (PR #132): `rounded_rect_prism(w, d, h, r, chamfer_mm=…)` and `base_chamfer(section, h, c)`, shared by every archetype, no new dependency and no OCCT review (§0.5). The deck box carries them by default — chamfer 0,6 mm, external round 1,0 mm, internal 0, all three **design defaults, unsourced** and labelled so on the view row, with the lip's and the lid cavity's radii *derived* from the external one so the closure's clearance is exact around a corner too. `MEASURED_FEATURES` 19 → 26, every one within 0,05 mm across the 405-spec envelope, a 48-case edge corner and Phase 3's assert path. Two findings worth keeping: the chamfer must be **built with** its wall from the design's own `CrossSection` — every boolean formulation leaves zero-area triangles along the seam that float64 tolerates and the float32 STL export does not — and `plane_set` over a vertex column cannot measure a rounded box, so `compiler.face_planes` reads faces instead. `deck_box.ARCHETYPE_VERSION` → 2, its first bump; every spec hash moved a fourth time, and a spec stating all three at zero compiles to the pre-#80 bytes exactly
- [x] `Process.fit_intent` (`snug` | `easy`) driving cavity clearance — 2026-09-10: `snug` is the default and today's 1,5 mm, `easy` is 4,0 mm, both the low end of `docs/dimension-kb-research.md` §3's bands and both in `FIT_INTENT_CLEARANCE_MM` alone. The clearance is resolved on construction, so an explicit `cavity_clearance_mm` still wins and the canonical form always carries the millimetres the geometry was built from; every spec hash moved a second time and no mesh did. An `easy` deck box compiles — a loose box is a valid request — and is refused only when the wider cavity is what pushes it past a stated `max_external_mm`, with both remedies named; a `snug` overshoot stays a `fits_check` verdict, which is what the UI can show
- [x] Justify or retire `Process.wall_mm = 2.8` — 2026-09-11: the floor is the machine's (`spec.wall_floor_mm` = 3 × the profile's `machine_nozzle_size`, so 1,2 mm at 0,4 and 1,8 mm at 0,6 rather than a constant that is only right on one printer) and the default is the archetype's (`spec.ARCHETYPE_WALL_MM`). The deck box's 2,4 mm is `Lid.wall_mm` + `Lid.clearance_mm` + `Process.min_feature_mm` — the thinnest body wall that still leaves its own lift-off lid a valid lip, so anything less is a default `validate` refuses; the card divider has no wall at all (`USES_PROCESS_WALL_MM = False`) and the floor skips it. The wall is resolved on construction like the clearance, so the canonical form states what the geometry has; every spec hash moved a third time, and a spec that *states* 2,8 mm compiles to the byte it always did. Refused in Phase 2, not Phase 3, because Phase 3 runs after the job directory already describes the part
- [x] `constraints.max_external_mm` gains the −2 mm safety buffer (research §7, BIT's leave-3/3/2 rule) — 2026-09-10: `Constraints.fit_margin_mm`, default 2,0 mm, subtracted on every axis by `effective_max_external_mm()` — the one place either archetype gets its limit from. The remedy names the arithmetic (`exceeds 74.6 mm (max_external 76.6 − 2 margin)`) so the two millimetres nobody typed are explained where they refuse something; `fit_margin_mm: 0` is for a person who measured the box they are filling and restores the old comparison and the old sentence exactly. The canonical form gains a key, so every spec hash moved — once, deliberately, rather than a `SCHEMA_VERSION` bump that would refuse every existing spec file for an additive field

### 📱 Phase 3 — Closed preview, friendly-user alpha (PRD M2 · 11–31 October 2026)

- [ ] LLM spec extraction — **two arms on one model-agnostic extractor** (§0.7, 2026-09-22): `claude-sonnet-5` structured outputs (plan of record) and TypeSafe Jev candidate-selection (code finds every number in the prompt, the model only *selects*; it cannot emit a millimetre). Whichever clears N5 ships. Every extracted field renders as "read from your words" with its span and is **confirmed by the person before `POST /jobs`** — the author of record is the person, never the model. Optional for the alpha; the form-driven configurator is the fallback, §5A cut #3. The Jev arm on the request path is issue #181, **blocked** on the harness below and on #182; `ip_screen` runs first and is never overruled; model pinned to `jev-1.13.0`; kill-switched and fail-open. **Parked until mid-October 2026 (§0.7)**
- [ ] Held-out prompt set + field-accuracy harness (≥90 % per required field **per language** gates the extractor) — issue #178. Two arms over the same ≥ 60 prompts (EN/IT/DE/PL/SV, typos, injected instructions, number words); **offline only** — keys stay on the Mac, CI runs recorded fixtures. The verdict is **a person reading the table**, recorded here with the table's path and date; no test asserts the threshold, because it is a product call per language. The question-set JSON is authored by a person with the TypeSafe skill and attached to the issue before the `claude` label goes on. **Parked until mid-October 2026; #178 closed as a placeholder, reopen then**
- [ ] **IP screen speaks the beta's languages** — DE / PL / IT purpose cues and contents nouns, so "Deckbox für Pokémon-Karten" flags as functional instead of refusing the primary persona (verified 2026-09-22: DE, PL and IT `block` today; SV passes by a fuzzy accident). Code only, no model; the § L6 line does not move; legal-pair review — issue #179, **parked until mid-October 2026 (closed placeholder)**
- [ ] **Game-box KB aliases + deterministic name → entry seam** — `POST /organizer/box-hint`, whole-word + difflib over name/publisher/aliases, suggestion only; the picker stays the sole writer of `spec.box`, and siblings that differ by a numeral or an edition are never auto-resolved. The model-backed disambiguator behind the same seam is tripwired in §0.7, not scheduled — issue #180, **parked until mid-October 2026 (closed placeholder)**
- [ ] **TypeSafe vendor onboarding bundle** — MCA / DPA / Privacy read and archived under `docs/audits/vendor-terms/`, notices rows, deferred-legal § L7, licensing guard, key-handling decision (`TYPESAFE_API_KEY` env-only, never `CONFIG_KEYS`). **Human-only, legal pair; no tier label, so the pipeline never fires on it.** Must land before or with #181 — issue #182, **parked with the rest until mid-October 2026 (closed placeholder)**
- [ ] Dimension KB v1 — curated JSON (research done: `docs/dimension-kb-research.md`)
- [ ] Clarify loop — ≤3 chip questions, reusing the blueprint-gate pause pattern
- [ ] Mobile-first pass — split layouts become stacks; retire waiting-state theatre + figurine copy
- [ ] Installable PWA — manifest, service worker, home-screen install, web push, camera capture for the fit photo
- [x] mm-annotated preview — spec-driven — 2026-09-17 (issue #88). The 80-unit normalisation is gone: scene units are millimetres and the camera is framed from the bounding box, so a figure in mm over the mesh is true. Every archetype declares `callouts(spec)` — one axis-aligned dimension line per designed feature, anchored to planes `measure()` reads it off, tiered so 720 px shows the cavity and the closure and drops the externals. Phase 2 writes the whole document to `view.json` (the api-server image has no kernel, so a view derived on demand cannot be derived at all) and `GET /jobs/{id}/spec` serves it. A callout's `feature` **must** be one `required_measurements` promises, which is the anti-fabrication rule in one line; the viewer reconciles the served mesh against the document's frame and draws nothing when they disagree. A prompt job is annotated with nothing and told nothing
- [ ] Spec-diff iteration ("make the lid deeper") on existing lineage columns
- [x] `preview_reached` job event (activation metric) — 2026-09-10 (PR #106). One event kind, no migration: `POST /jobs/{id}/events/preview-reached`, written once per job by the running view when the mesh or the toolpath is the *rendered* tab and has something behind it, deduplicated server-side the way `outcome_prompt_shown` is. `GET /feedback/stats` reports `jobs_submitted` / `previews_reached` / `activation_rate` over jobs via `TelemetryDB.activation_funnel()`, `dev` jobs excluded from both halves. The ≥30 % export half was already instrumented (`download` + `?preview=1`)
- [ ] N3 measured end to end on a real phone (≤20 s); the per-job `docker compose run` replaced if it blows the budget
- [x] IP screen re-scoped for functional articles — "deck box for Pokémon cards" must pass before any external user sees the app — 2026-09-10 (PR #116, issue #79), part (a). `ip_screen._classify_usage` reads *how* a curated name is used, for strong hits only: a depiction cue near it blocks, a purpose cue before it flags, and with neither the category decides (a `character` is the prompt's subject, a `franchise`/`brand` its contents). The missing TCG franchises (Magic: The Gathering, Yu-Gi-Oh!, Lorcana, One Piece, Flesh and Blood, Digimon, Star Wars Unlimited) joined the list **for the flag**, so consistency comes from the rule rather than from omission; `ip_screen_flagged` carries the `usage`. The position is recorded as a product decision pending counsel in `docs/deferred-legal-tasks.md` § L6. **Part (b) — screening F13's embossing field — landed 2026-09-17 (PR #162, issue #156)**: the free-text fields are screened as separate channels and the embossing one is not a functional-article context, which unblocks F13
- [ ] Friendly-user alpha — 5–10 known users, form-driven deck box, we print and send a photo, scripted usability sessions
- [ ] Finger cutouts + non-structural lightweighting cutouts on tray archetypes — dual-purpose (cards pushed up from below, filament cut); makes the mass `gcode_stats` already computes actionable
- [x] ~~Decide: multi-compartment box-insert archetype before launch, or board gamers post-launch?~~ **Decided 2026-09-05: board gamers are a December launch segment.** The three boxes below are what that decision costs (§0.5)
- [x] **Multi-compartment box-insert archetype** — **done 2026-09-18 (issue #152)**. `pythonsrc/organizer/archetypes/box_insert.py`: one enclosure holding several *differently shaped* fitted regions — a card well, a token pocket, a dice well — in one manifold body, compiled to fit the interior of a publisher's box. This is where the composition wedge PRD §1 claims and PRD F5's `box-insert grid` become true of the code rather than of the schema. What it settled: **one archetype with a heterogeneous compartment list, not a container nesting the existing three** — a nested spec changes the *shape* of `compartments`, which is a schema change rather than a new optional section and would move every stored `spec_hash`, and what an insert borrows is already shared (`resolve_stack`, `rounded_rect_prism`/`base_chamfer`, `external_overshoots`, `SweepCase`); **no new content type**, so a dice well is a typed `Pocket` and every existing hash stands still — pinned literally by `EXAMPLE_SPEC_HASHES`, captured on `main` before `insert` was written, because a new optional section is the only additive-safe change this schema has; **`insert.rows` is the whole layout grammar and nobody types a position** (`Tray.columns`' rule in the other direction), with slack in a narrower row shared equally across that row's X walls, so `process.wall_mm` is the minimum wall rather than the exact one and each row's is a measured feature; **per-compartment depth is the floor rising, not the rim falling**, which is what the tray deferred; **a card stack lies flat** (a sleeved card stands 92 mm and these interiors run 70–75 mm); **the interior is a limit, not a target** — `max_external_mm` needed no change, and the **undershoot** is now printed on the fits line because an insert that rattles is what #153 exists for. A ragged layout cannot be read off a plane count, so it is the first archetype to measure **region by region**: `compiler.face_planes_within`, five features per compartment including `c{i}_x_mm`/`c{i}_y_mm`, and a `MEASURE_NEEDS_SPEC = True` hook on the registry so the design supplies the region and the mesh supplies the numbers. 192-case envelope sweep on the exported, reloaded STL at ±0,05 mm plus Phase 3's assert path; `expected_components=1`, gate `ready`; the composer's strip offers it with a compartment-list editor. **Not** in v1: filling the interior, cards on edge, a compartment spanning two rows, rounded well corners and finger cutouts — issue #152
- [ ] **Locking tabs / anti-slide geometry** — mandatory per §0.5 for transport; in scope now that inserts are, and pointless before the archetype above — issue #153
- [x] **Game-box internals: seed the KB with the launch set** — 2026-09-21 (issue #154): `pythonsrc/data/game_boxes.v1.json` and `pythonsrc/organizer/box_kb.py`, with **provenance per value** (basis, source, capture date and the units it was captured in, one set per axis) and a load-time refusal for any value with no source. **Three entries, and three is the finding**: every number is transcribed from a row of `docs/dimension-kb-research.md` that already names where it came from — Wingspan off §7's BGG measurement thread, plus the two commercial card cases of §3 — and the rows refused are recorded in the data file rather than left as omissions (the Cloudflare-gated Printables listing §8 says to re-verify, and every BGG box-dimension row, which is external and in inches). `folk` is not an accepted basis and a `derived` interior must name the subtraction behind it, which is the issue’s "do not infer an interior from an exterior without saying so in the data" as a loader rule. `spec.box` is a new **optional section**, so no stored `spec_hash` moved; it resolves `constraints.max_external_mm` on construction, refuses a spec that disagrees with the entry it names, and still loads one recorded against a KB version this build does not carry — a job that ran is a record, and the job page must not go down with a correction. `compile_spec` puts the entry and the version on `generation_params`. **`fit_margin_mm` comes off a curated interior exactly as off a typed one**: a curated number is still one copy of one box. The degraded mode is the composer’s opening state, not a failure — "a box nobody has measured, I’ll type the interior" — and `interiorNote` labels every row as sourced or typed, per axis. **No BGG client**, asserted against the whole tree by `tests/test_game_box_kb.py`
- [ ] **Stackable enclosure for a collection that outgrew its box** — decided 2026-09-17 (§0.5). The insert archetype above organises the *inside* of the publisher's box; this is for the collection that no longer fits one at all (Catan + Seafarers + Cities & Knights + the 5–6 player extension is the reference case). Same compiler, constraint inverted: no fixed outer envelope, a stack of trays plus a shell sized from the contents, and transport held by the locking tabs above rather than by a publisher's lid — issue #155
- [x] **Embossing-field IP screen — part (b) of the #79 re-scope** — 2026-09-17 (PR #162, issue #156). `ip_screen.py` screened `prompt` and `material_colour` joined into one string; the free-text fields are now screened as separate `CHANNELS`, each on its own tokens, and `ScreenVerdict.channel` says which one matched — joined, the box's own purpose text lent the emboss field its grammar and demoted a refusal to a flag. `DEPICTION_ONLY_CHANNELS` holds the embossing field: the functional-article rule does not reach it, because nothing raised on a face holds anything, so a strong hit is refused whatever surrounds it while an ambiguous word ('joker', 'frozen') still only flags. `JobRequest.embossing_text` is screened before `job_id` is minted and before the spec is written to disk, and compiles to nothing yet by design — the geometry is #157, which this unblocks. The position is recorded as a product decision pending counsel in `docs/deferred-legal-tasks.md` § L6
- [ ] **Decorative tier v1 — parametric emboss/deboss on a face (F13)** — promoted 2026-09-17 (§0.5) from Phase 5 "(Could)". Extruded text or a monogram boolean-unioned onto, or subtracted from, a chosen face: deterministic, no model in the loop, ~€0 and seconds. Blocked on the IP screen above. Image relief (FLUX render or user image → heightmap → displacement) and F14 sculptural lids stay post-v1 — issue #157

### 🧪 Phase 4 — Closed beta on our own printers (1–30 November 2026)

- [ ] Hosted environment — API + web + database on one VM, TLS, access gate, admin surface locked down, no Docker socket in the public build
- [ ] Bounded job queue + rate limits replacing fire-and-forget dispatch
- [x] ~~Printer-reachability decision for a hosted server — 3MF download / Bambu Cloud / local agent / phone-as-LAN-bridge~~ **Decided 2026-09-10 (§0.6, issue #95): B + A for this beta (3MF download, self-host on LAN for zero-click), C for the December launch ("Daedal Link" local helper), D in Q1 2027 (native app as LAN bridge). Not E.**
- [ ] ToS (warranty, indemnity, right to refuse, data-use consent) + privacy policy live before the first external tester
- [ ] Closed beta cohort 1 — external users prompt, we print on KTH/Trento, photo + fit verdict back; every participant interviewed
- [ ] Bambu operator for real — KTH machine in Developer Mode; port text-to-cad's MIT `bambu-labs` FTPS/MQTT logic (Tytus) — moved from Phase 2 on 4 Sep: the beta prints on our own machine via Bambu Studio by hand
- [ ] Moonraker test target — headless Klipper + virtual MCU (Alberto) — moved from Phase 2 on 4 Sep
- [ ] Test-fit coupon — 10-minute tolerance validator through the dispatch gate
- [ ] Fit verdict in `VALID_OUTCOMES` + outcome UI ("fits as intended" ≠ "printed")
- [ ] Coupon → tolerance calibration loop — verdicts update per-printer/material fit offsets
- [ ] Fit-verdict loop closed at least once on real hardware
- [ ] Handoff verified on real hardware: Bambu **and** OctoPrint, end to end
- [ ] Patent decision on the calibration loop — prior-art search + counsel **before** anything public discloses it
- [ ] Sentry + `AnomalyDetector` re-tuned on real print telemetry

### 🚀 Phase 5 — Public launch (December 2026 · target 20 Dec, hard stop 31 Dec)

- [ ] Minimal accounts — magic-link auth, spec as the saved object, ownership checks on job routes (F11)
- [ ] Load-test the job queue and LLM rate limits
- [ ] EU AI Act transparency review; GDPR data-subject path (retention window, export/delete, LLM processor terms)
- [ ] Mobile web QA on real iOS + Android devices — viewer, install flow, push, camera
- [ ] Pre-launch checklist verified; cybersecurity review
- [ ] **"Daedal Link" local helper (route C, §0.6)** — signed-in desktop/Pi agent, outbound WebSocket to the hosted server; C(i) hands the sliced 3MF to Bambu Connect via `bambu-connect://import-file` (no Developer Mode, one Send click), C(ii) drives MQTT/FTPS over the LAN (Developer Mode, zero clicks, telemetry). Engine is `BambuOperator` (#73). **If cut, B is the launch route and the copy says "Download and print".**
- [ ] Public launch — parametric TCG organizers, STL/3MF export, OctoPrint handoff, Bambu handoff where verified
- [x] ~~(Could) F13 lid embossing — only after the embossing-field IP screen exists~~ **Moved to Phase 3 on 2026-09-17 (§0.5), and raised from Could to Should.** Customisation is a market-value requirement rather than a premium add-on; the screen it waits on moved with it

### 🔭 Phase 6 — Post-launch: moat & scale (Q1–Q2 2027 →)

- [ ] Fit-outcome dataset → does the printability/fit score predict reality (Bet 2 groundwork, no GPU needed)
- [ ] Native apps — iOS App Store + Google Play as a Capacitor wrapper of the PWA; phone-as-LAN-bridge to the printer; store economics reviewed first
- [ ] Generative personalization premium tier — text emboss and image relief on the parametric kernel first; sculptural lids (F14) as the niche add-on
- [ ] Print-aware conditioning research (Bet 1) — only if the F14 tier is pursued
- [ ] KB depth: game-box internals **beyond the launch set** (the seed moved to Phase 3 with the Dec-2026 board-gamer decision, §0.5), archetypes prioritized by prompt volume; adjacent categories (dice trays, desk organizers) before phone cases
- [ ] Self-host / scale economics recomputed on real beta volume
- [ ] **Tripwired typed-judgment uses from §0.7, none scheduled** — the model-backed box disambiguator behind #180's seam (KB ≥ ~30 entries with edition pairs *and* the deterministic path below 90 % on the box field); an offline IP-screen eval harness that finds cue gaps a person then adds in code (never a decider, never block → allow); fit-verdict pre-fill from free text (only once a reply channel exists and volume exceeds what one operator taps through); a prompt guard inside a live extractor (thresholds from the N5 set, never a refusal). Each reopens as its own issue with the same human-oversight list as §0.7

---

## What we retain

Every job stores the following, and none of it is recoverable after the fact if it is
not captured at the moment it happens — which is why it is captured:

- **Your prompt, verbatim** (`print_job.prompt`); on the generative branch also the
  engineered variant actually sent to the image model
  (`blueprint_prompt_engineered`). On the product path the saved object is the
  **spec** — regenerable and tweakable, which is what makes iteration free.
- **The blueprint image** (generative branch), in the job's own output directory, plus
  its SHA-256.
- **The mesh** before and after repair, as hashes and geometry feature snapshots.
- **The slice result**, including failures, and the printer the G-code was sent to.
- **Your verdict on the print**, if you give one, and the fact that you were asked.

Prompts are stored permanently at present. A retention window is a decision still to
be made — see `docs/deferred-legal-tasks.md`.

**Original designs only.** You must hold the rights to whatever you describe. Prompts
naming protected characters or brands are refused, and a job can be refused or
cancelled at any stage. (A deck box *for* your Pokémon cards is a functional article,
not a reproduction of a character — re-scoping the screen for that distinction is a
roadmap item.)

## License

This project is licensed under the [Apache 2.0 License](https://www.apache.org/licenses/LICENSE-2.0).

Third-party components, model weights and the obligations they carry are tracked in
[`THIRD-PARTY-NOTICES.md`](THIRD-PARTY-NOTICES.md). Two of those obligations are
worth stating here, because they constrain what a deployment may do:

**Built with DINOv3.** The benched generative branch's image conditioning uses DINOv3
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
