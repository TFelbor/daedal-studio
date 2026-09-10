# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## ds-mvp — Claude Code guide

The pipeline's contract with this repository. `docs/PIPELINE.md` explains how an issue
becomes a pull request; this section is what an agent must know before it changes a
file. Everything below it in this document is the system as built — read that too,
and read the part that covers what you are touching.

### Build and test

- **Install:**
  `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements-mac.txt`
  (`requirements-linux.txt` on Linux; CI installs `torch` from PyTorch's CPU index
  first, then `requirements-base.txt`), then
  `cp pythonsrc/config.template.py pythonsrc/config.py`, `cp .env.template .env`,
  `mkdir -p data/inputs data/outputs data/logs`, `npm --prefix web ci`.
- **Test:** `pytest tests/` — must pass before opening a PR. `pytest.ini` deselects the
  `slow` markers, so this is the selection CI runs. It needs a PostgreSQL: either
  Docker running, in which case `tests/conftest.py` starts a throwaway
  `postgres:17-alpine`, or `DS_TEST_DATABASE_URL` pointing at a database the suite may
  administer. Frontend: `npm --prefix web run build`, which is `tsc -b && vite build`
  and therefore the type check as well.
- **Lint:** `npm --prefix web run lint` (ESLint). It currently **fails on 27
  pre-existing errors** unrelated to any new change, and CI runs it
  `continue-on-error`. Do not treat a red lint as a reason to stop; do leave it no
  redder than you found it.
  <!-- TODO: no Python linter or formatter is configured — no ruff, flake8, black or
  pyproject at the root. Pick one, add it to requirements-base.txt and to ci.yml, and
  replace this note with the command. -->
  <!-- TODO: no coverage measurement exists anywhere — pytest.ini, requirements-base.txt,
  the Makefile and ci.yml all lack it (issue #82). The only figure available is what
  `pytest tests/ --collect-only` reports, and it is a count of tests, not of covered
  lines. A number written into this file instead had rotted from 949 to 2 493 without
  anything noticing, which is the argument for measuring rather than quoting. Add
  pytest-cov and a floor before anyone states a percentage. -->

### Layout

- `pythonsrc/` — the five-phase pipeline (`pipeline.py`), the parametric organizer
  engine (`organizer/`), sculptor backends (`sculptors/`), printer operators
  (`operators/`), telemetry (`telemetry/`), printability, IP screening, licence policy.
- `server/` — FastAPI app (`app.py`), WebSocket broadcaster, encrypted config store,
  OctoPrint simulator manager. Serves the built SPA.
- `web/` — React 19 + Vite + TypeScript SPA. `npm run build` writes `web/dist/`, which
  the API server image copies and serves.
- `services/trellis2_worker/` — the GPU sculptor worker; runs only on a CUDA host.
- `supabase/migrations/` — the telemetry DDL, **generated** from
  `python -m pythonsrc.telemetry.db --ddl`. `infra/` — Dockerfiles, compose, CI helpers.
- `tests/` — the suite; `pytest tests/ --collect-only` is the only honest count.
  `docs/` — PRD, roadmap, `PIPELINE.md`,
  `deferred-legal-tasks.md`, `RUNBOOK-spec-job.md` (one spec job by hand, from
  `POST /jobs` to the telemetry row — the steps the default selection cannot reach
  because they need a real slicer, a printer and a database).
  `licenses/` — the committed dependency tree.

### Conventions

- One task = one PR, referencing the issue; acceptance criteria copied into the PR body
  as a checklist.
- Tests for every behaviour change.
- Never modify files containing `LEGAL-DEFERRED` unless the issue explicitly says so.
  (No file carries the marker today. When one does, it is legal work parked
  deliberately — see `docs/deferred-legal-tasks.md` — and moving it is a legal
  decision, not a code one.)
- Never add dependencies without stating why in the PR. A dependency here is also a
  licence decision: read **Licensing Constraints** below before adding one, check the
  weights any package downloads at runtime as well as the package, and update
  `THIRD-PARTY-NOTICES.md`. `tests/test_licensing_guards.py` is a required part of the
  suite, not an optional one.
- **`.claude/skills/` is mostly ignored and partly tracked, by name.** The two
  directories listed in `.gitignore` are vendored third-party skills that
  `claude-implement` loads; everything else there is a developer's own. Adding one
  is a licence decision — it is redistribution, so it needs the upstream `LICENSE`
  in the directory and an entry in `THIRD-PARTY-NOTICES.md` § 2 — and it needs
  `Skill` on the workflow's `--allowedTools`, without which the skill is silently
  inert. `tests/test_vendored_skills.py` binds all four of those facts together
  and is the only thing that does. Do **not** convert these to the action's
  `plugins` input: a plugin cannot be pinned to a ref and would resolve to a third
  party's default branch on every run. Adding one is also **not free and not
  neutral**: a description is injected into every run whether it fires or not, and
  a skill written for another stack does not merely waste that — it instructs the
  implementer to hand-author generated migrations, write `CLAUDE.md`, or install a
  test framework nobody asked for. Three vendored skills were removed for exactly
  that, one of them for advice that would have denied the server every write; the
  reasons are in `THIRD-PARTY-NOTICES.md` § 2 so they do not get rediscovered. See
  `docs/PIPELINE.md` § Skills are vendored, not installed.
- Never touch these unless the issue explicitly says so:
  - **Credentials and secrets** — `server/config_store.py` (the Fernet-encrypted store),
    `.env.template`, `pythonsrc/operators/` (printer API keys),
    `supabase/README.md`'s security posture. There is no end-user authentication in
    this repository yet; these are the paths that hold secrets, and they are what
    "auth" means here. In CI, **`CLAUDE_CODE_OAUTH_TOKEN` is the only auth secret**
    and every `.github/workflows/claude-*.yml` uses it; `ANTHROPIC_API_KEY` does not
    exist here and must not be named in a workflow, because the action renders an
    unset secret as an empty credential rather than as no credential. See
    `docs/PIPELINE.md` § Secrets.
  - **Anything that spends money** — `pythonsrc/sculptors/pixazo.py` is the only code
    that incurs a charge (EUR 0,32 per generation) and `generation_cost_eur` is where
    it is booked. There is no payments or billing code in this repository yet; when
    there is, list it here.
  - **Migrations** — `supabase/migrations/` and `pythonsrc/telemetry/db.py`. The
    migration file is generated from the code, and `tests/test_supabase_migration.py`
    fails when they disagree; never hand-edit the SQL.
- Units are metric, currency is EUR — in code, in the UI and in prose.

### Definition of done

Tests pass, lint passes, checklist complete, no out-of-scope changes.

---

## Project Overview

**Direction (committed 2026-08-31): Daedal Studio builds custom-fit tabletop/TCG organizers
from a prompt — parametric geometry compiled from a structured spec, not generative mesh
reconstruction.** The product PRD is `docs/PRD_daedal_tcg_organizers.md`; the plan in force is
`docs/ds-mvp-roadmap.md` §§0.1–7A; the reasoning is `docs/pivot-brief-tcg-organizers.md`. The
governing rule: *the LLM interprets words; it never produces geometry.* Phases 1–2 below
(FLUX → TRELLIS.2) are **benched, not deleted** — they leave the critical path and become the
branch behind decorative personalization (PRD F13/F14). Everything from Phase 3 onward (repair,
printability gate, slicing, dispatch gate, telemetry) is unchanged and is what the parametric
path plugs into via the `--skip-visualizer --skip-sculptor --mesh <path>` seam. The parametric engine has its first pieces (2026-09-03): the spec schema
(`pythonsrc/organizer/spec.py`) and two archetypes — the deck box
(`archetypes/deck_box.py`) and, since 2026-09-10, the card divider
(`archetypes/card_divider.py`) — entered through `pipeline.py --spec` —
see **Organizer — the parametric path** below. Phase 3 asserts a spec run's geometry
instead of repairing it and measures every designed feature back to ±0,05 mm, and
`POST /jobs` accepts a spec (2026-09-03). The dimension KB, LLM extraction and the UI's
spec panel wiring do not exist yet; do not treat generative-path tuning as roadmap work.

**The UI has been moved onto the pivot's vocabulary ahead of the engine** (2026-09-02). The
five phases now read **Composer · Compiler · Printability · Slicer · Operator** in the app,
`web/src/pipeline.ts` is the single source for those names and blurbs, and the composer
carries an archetype strip, a Fits Check and a spec panel. Phases 1–3 therefore *describe*
the parametric pipeline while the backend still runs FLUX → TRELLIS.2 → repair; the comment
at the top of `pipeline.ts` says so, and nothing in the telemetry columns changed
(`blueprint_model` and `generation_model` still record what actually ran). The new panels are
**shells with explicit empty states**, never placeholder numbers: `organizer/spec.ts` holds
the types and `specFromJob` is the one seam to wire when the engine lands, and
`NO_SPEC_REASON` is the single sentence every one of them shows meanwhile. A fits badge with
no measurement behind it is the exact failure the Fits Check exists to prevent, and a
screenshot of one outlives any caveat.

The rest of this file documents the system as built. It chains: text→blueprint image (FLUX), image→3D mesh (TRELLIS.2-4B), mesh repair+scaling (trimesh/manifold3d), slicing (CuraEngine), and printer dispatch (OctoPrint/Klipper). A FastAPI server orchestrates jobs and serves a React SPA. Phases 1 and 3–5 run in Docker (linux/amd64) or natively on macOS with MPS acceleration for Phase 1.

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

# CI (.github/workflows/ci.yml) runs the same two commands on every push and PR:
#   pytest tests/test_licensing_guards.py   # named separately — a licence break is not
#   pytest tests/                           #   an ordinary failure
# plus `npm run build` (which is `tsc -b`, so it is the type check too) in web/.
# It installs CPU torch wheels, copies `config.template.py` into place — which is also
# what keeps that template from rotting — and puts `infra/ci/curaengine_stub.sh` on PATH
# as `CuraEngine`, because `CuraSlicer` refuses to construct without the binary even in
# tests that stub the call. A stub, not the real engine: `apt-get install cura-engine`
# broke when `ubuntu-latest` moved to 24.04 (the package is in universe on 22.04 and
# again from 25.10, but noble has no candidate), and nothing in the default selection
# executes it — verified, since the suite passes with a stub that exits 70 if invoked.
# `npm run lint` runs non-blocking: it has 27 pre-existing errors, and a gate that is
# red the day it lands teaches everyone to ignore the red.

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

The core pipeline runs 5 phases sequentially. Phase banners (`[DS] ═══ PHASE N START/PASS/FAIL ...`) are parsed by the server to emit WebSocket progress updates. The pipeline writes a `.status` file per job to `data/logs/{job_id}.status`.

**The banners are a contract between two processes that share no code**, and it is the
most fragile one in the project. `_phase_start`/`_phase_pass`/`_phase_fail` print them;
`server.app.PHASE_BANNER_RE` recognises them. Reword a banner, drop the trailing `═══`
or renumber a phase and the pipeline still runs to completion, still exits 0 and still
writes every artifact — while the UI sits at "phase 01 pending" for the whole run.
Invisible in a diff, total at runtime. `tests/test_phase_banners.py` binds the two
halves: it generates banners with the real emitters and parses them with the real
parser, so neither side carries a copy of the other's format. The regex and
`PHASE_NAMES` are module-level in `server/app.py` (they were locals inside
`_stream_output`) for exactly that reason — a test retyping the regex would agree with
itself forever.

Execution strategies are auto-detected by `platform_utils.py`. These decide **Phase 1's**
placement only:
- `mps_native` — macOS with Apple Silicon (Phase 1 native, Phases 3-5 in Docker)
- `nvidia_docker` — NVIDIA GPU available in Docker
- `cpu_docker` — CPU-only Docker fallback

Phase 2's placement is a *separate* decision made by `sculptors.resolve_backend_name`, because
`platform_utils` knows nothing about the worker URL that makes a GPU-less host viable.

Skip flags (`--skip-visualizer`, `--skip-sculptor`) allow resuming from intermediate artifacts.

**How big the part comes out is a request, and it used to be a constant.** Phase 3
scales the mesh, and `--target-mm` (default 50.0) has existed since it was written —
but nothing forwarded it. `POST /jobs` had no size field at all, so *every* job
submitted through the web app printed at 50 mm regardless of the prompt: "small
pikachu figurine" and "giant pikachu statue" came out identical. `JobRequest.target_mm`
now carries it, `_pipeline_args` forwards it, and **omitting it forwards nothing** so
the pipeline's own default stays the only default — a copy of 50.0 in the server would
drift the first time either moved.

**A mesh can arrive with its dimensions already final, and Phase 3 used to resize it
anyway.** `Engineer.process` repaired, oriented and then scaled **unconditionally**,
with `target_mm` defaulting to 50.0. That is right for Phase 2 output, which has no
dimensions of its own — a reconstruction comes out in an arbitrary scale. It is data
loss for a mesh compiled from a parametric spec, where every dimension *is* the
deliverable: such a part left Phase 3 with its height set to 50 mm and everything
else dragged along by the same factor. Reachable today with no new code, via the
documented `--skip-visualizer --skip-sculptor --mesh box.stl` path — which is
deliberately *not* a fixture run, so its outputs land in the real namespace. And
undetectable downstream: the mesh is still watertight, `printability` still scores
it, CuraEngine still slices it, the printer still prints it, and nothing in the log,
the report or the telemetry row mentions that a dimension moved. The only symptom is
a part that does not fit, found by a person hours later. `target_mm=None`
(`--no-scale`) now means "these dimensions are final" and skips the scale;
**`None` also overrides `self.target_dimensions`**, because an instance-level
default must not silently resize a mesh whose caller has said otherwise.
`--hollow` with `--no-scale` is **refused**, not served: hollowing voxelises at a
`wall_thickness` pitch and needs the re-scale below, so honouring both is
impossible and each remedy is wrong in a different direction — re-scaling discards
the authored dimensions, skipping it ships the wrong size with its base under the
plate. A part needing both an internal cavity and exact dimensions must model the
cavity. `last_report` gains **`scale_applied`**, written unconditionally and kept
separate from `scale_axis`, because three outcomes are three facts: a scale ran, a
scale was asked for and there was no extent to apply it to (`"none"`), or the caller
declared the mesh final (`"preserved"`). Folding the last into `"none"` would make
"we honoured your dimensions" indistinguishable from "your mesh was degenerate".

**`--scale-axis` decides which extent the size describes, and it defaults to
`height`.** `scale_to_dimensions` sized the **longest bounding-box edge**, which is
defensible for a machine and wrong for a person: a figurine with its arms out is wider
than it is tall, so a request for 50 mm produced a part 50 mm across and 38 mm high —
smaller than asked in the one dimension the requester was picturing. Height is the Z
extent, and that is true *only after* `orient_for_print`, which translates onto Z = 0
without rotating; `apply_scale` is origin-based, so scaling after orienting preserves
both the seating and the X/Y centring. **This is a behaviour change for existing
callers** — a wide, short model asked for 50 mm is now 50 mm tall and much wider, which
can newly exceed `build_volume_mm`. `longest` remains reachable by name.

**A size written in the prompt is offered, never applied** (`pythonsrc/size_hint.py`,
`POST /prompt/size-hint`). "a 10cm tall vase" already answers the question the composer
is asking, and the parser reads it — in millimetres, converting imperial at the boundary
— along with the axis the phrasing implies ("tall" vs "wide"). But it only ever
*prefills*: applying it would make `prompt` and `requested_size_mm` disagree about who
decided, which is the same fabrication as a fixture mesh sitting in the real namespace.
A bare number is never a size — a count, a year and `d20` all contain digits — so a unit
is required. `strip_size_phrase` drops the matched phrase once the number is a
parameter, because saying it twice makes FLUX draw a scale reference (a hand, a coin)
and Phase 2 then has two subjects for `_largest_component` to choose between. Vague size
words ("small", "miniature") are deliberately **left in place**: those are style, not
measurement, and editing them out would change what the person asked for.

**`hollow` re-scales, and it must be told the axis.** `hollow_mesh` voxelises at a
sub-`wall_thickness` pitch, so the shell comes back slightly larger than the target with its
base below Z = 0, and `process` re-scales and re-seats afterwards. That second
`scale_to_dimensions` call takes `scale_axis` explicitly — left to the default it would
size a `longest` request by *height*, so the part would be scaled by one convention and
then silently re-scaled by another. The `achieved_extent_mm` in `last_report` is measured
after this, on the exported mesh, which is why it is the honest figure rather than the
one the first scale produced.

**Height mode bounds one axis and not the other two.** A wide model asked for a tall
height can come out past the bed. It is deliberately **not** shrunk — a part quietly
scaled to something other than what was asked for is the bug this whole change set
removes — so Phase 3 prints an `--- OVERSIZE ---` line naming the axes, and
`build_volume_fit` (critical, weight 2.0) fails it in the printability report.

**`printability.size_feasibility` inverts the wall check.** The min-wall check runs
*after* scaling, so "your walls are too thin" arrives once the size is fixed and the one
remedy — print it bigger — was never named. It reuses `_thickness_pitch` and
`_wall_status` rather than copying them, because the pitch *is* the tolerance and a
predictor with its own formula would quote a confidence interval the real check does not
have. Wall thickness is exactly linear in the scale factor; the *measurement* is
quantised, and the pitch's dominant term flips from absolute (`min_wall/4`) to
proportional (`max_extent/256`) as the part grows — so a suggested size is confirmed by
re-measuring there and never reported as measured. Hollowing voxelises at an absolute
pitch, so the prediction does not hold for it and is not offered.

**Filament colour reaches the blueprint and nothing else.** When the requester named a
colour, `engineer_prompt` renders the preview in it — the running view shows the
blueprint first, and a grey preview of a part someone ordered in red is a small lie told
at the most visible moment. It changes the blueprint only: `_strip_appearance` discards
appearance for every backend and CuraEngine has no use for a material. `material_colour`
is unvalidated free text from the composer, and it ends up in the string sent to the
model, which makes it a **second prompt channel** — one that any screen inspecting only
`prompt` would never see. `blueprint_spec.normalise_colour` therefore drops anything that
is not plausibly a colour name rather than sanitising it into something else. Note that
a very dark or saturated colour works against the matte's need for a separable subject
and the clay shading Phase 2 reads shape from; that trade has not been measured on real
renders yet.

**This checkpoint takes no negative prompt.** `FLUX.2-klein-4B` is distilled, so
upstream's classifier-free-guidance branch (gated on `not is_distilled`) never runs and
the `guidance_scale` recorded in `blueprint_params` for every job is inert. Every
constraint in the wrapper is therefore phrased as something to *draw* — "a single object
centred in frame, no hands, no props" is the positive form of forbidding a scale cue.

**A skipped phase installs a real asset, and the output directory says so.** When Phase 1
or Phase 2 is skipped with nothing real to work from, the pipeline copies in
`pythonsrc/assets/dev_reference/{blueprint.png,raw_mesh.obj}` — actual outputs of job
`ec076d7e`. It used to fabricate them: a flat blue rectangle and a 50mm
`trimesh.creation.box`. The cube is watertight, convex and single-component, so
`repair_mesh` had nothing to remove, `_largest_component` nothing to choose between, and
the printability gate scored geometry no reconstruction produces; the reference mesh
arrives with 138 non-manifold edges across 95 components, which is what those paths were
written for. Such a run writes to **`data/outputs/dev-{job_id}`** — a mesh built from a
fixture must not sit in the real namespace looking like one a model made.
`resolve_job_artifact` searches both, so the endpoints still serve it.
`_will_use_reference_assets` is the predicate, and it is deliberately narrower than "a
phase was skipped": the primary Mac workflow always passes `--skip-visualizer` because
Phase 1 just ran natively, and `--skip-sculptor --mesh real.obj` supplies its own. Only a
*substitution* earns the prefix.

**The blueprint is per job.** `data/inputs/blueprint.png` was one filename every run
wrote in place — the native Mac process, the pipeline container, all of them. Phase 1
takes ~30s natively and minutes in Docker, so two jobs started in that window raced for
it, and the loser sculpted, sliced and printed the winner's image while recording its
own prompt and seed against it. Nothing downstream could notice: the file exists, it is
a real render, and its hash is whatever landed last. The result is a mislabelled row in
the one dataset this project exists to collect, and on a per-generation sculptor backend
it is money spent reconstructing the wrong picture. The per-job snapshot into
`data/outputs/{job_id}/blueprint.png` does not fix it — that copies whichever image won.
`pipeline._blueprint_path` is the decision: `--blueprint` wins, else
`data/inputs/{job_id}/blueprint.png` when there is a `--job-id`, else the flat path for
manual CLI use. The sidecar shares the directory, which is the other half — `read_sidecar`
rejects a sidecar whose hash does not match the image beside it, so a race used to cost
the *winner* its provenance too. The server sends the native Phase 1 there via
`$DS_BLUEPRINT_OUTPUT` (`run_phase1_native.sh`) and hands the container the same path.
Two deliberate exceptions: the **skip-Phase-1 configuration keeps the shared path**,
because it exists to reuse an image already sitting there and generates nothing to race
for; and `POST /jobs` **no longer deletes** `data/inputs/blueprint.png` in its
stale-artifact sweep, which was the same race from the other side — creating one job
removed the blueprint a concurrent one was still reading, and deleted the very input a
skip-Phase-1 run was about to use.

**Both phases skipped is the commonest dev configuration, and it used to get no
blueprint at all.** `SKIP_VISUALIZER` + `SKIP_SCULPTOR` in the config store is how the
UI runs Phases 3-5 on a machine with no GPU, and the install condition read `if not
blueprint_path.exists() and not args.skip_sculptor` — withholding the image whenever
Phase 2 was skipped too, on the reasoning that a skipped Phase 2 has nothing to hand it
to. Phase 2 is not the blueprint's only consumer: it is the first thing the running view
shows and its hash is the job's only Phase 1 provenance. Those runs exited 0 with a
`dev-` directory holding `raw_mesh.obj` alone, an empty blueprint stage, NULL for every
`blueprint_*` column, and nothing in the log saying so.
`_should_install_reference_blueprint` is the decision now: skipped Phase 1, nothing at
the path, **and no `--mesh`**. That last clause is the honest exception — a run that
supplied its own geometry is not a fixture run, its outputs land in the real namespace,
and inventing a blueprint there would stamp a fabricated input's hash as this job's
provenance. That case logs a warning instead, because an unexplained empty first stage
reads as a broken pipeline.

**The fixture flag is carried out to the UI, not only to the dataset.**
`GET /jobs/{id}` returns `used_reference_assets`, and the running view shows a
`Fixture inputs` badge and re-captions the blueprint and mesh stages. Without it the
page captions a bundled image "Blueprint drawn from the prompt" — the same lie the
`dev-` prefix exists to prevent, told to the person instead of to the query. `_blueprint_is_stand_in` recognises the reference
blueprint by hash and the legacy flat rectangles by pixels — that guard is the only thing
stopping a per-generation backend from being billed to reconstruct a fixture, and the old
files persist on the shared blueprint path.

**Phase 5 does not follow Phase 4 for a UI job.** `POST /jobs` from the web app sends
`print: false, start_print: false`, so the pipeline stops after the slicer and the job
waits for a person to confirm the printer — see **Dispatch gate** below. `--print
--start-print` still dispatch immediately, which is what the CLI and any automation
use: there is nobody to ask there.

Between Phase 3 and Phase 4 the pipeline runs the **printability gate** (`pythonsrc/printability.py`).
It is deliberately *not* a numbered phase: the `.status` protocol, the WebSocket phase updates and
the UI progress bar all key off phases 1–5, so renumbering would change what every historical
`.status` file means. It emits `[DS] ─── PRINTABILITY ... ───` banners instead, writes
`data/outputs/{job_id}/printability.json`, and persists score/verdict/features/report onto the
job's telemetry row. Scoring is **advisory** — a low score never blocks a print unless
`--min-printability SCORE` is passed, and a crash in the scorer is logged and skipped rather than
failing the job (but it is *recorded* — see the error envelope under **Printability**).

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
`$DS_SCULPTOR_REMOTE_URL` is set (an explicit configuration outranks a local GPU that may be
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
- **Appearance is discarded for every backend** (`SculptorBackend._strip_appearance`,
  the first step of `postprocess`). Nothing after Phase 2 reads a material and CuraEngine
  could not use one, but appearance travels: Pixazo returns `metallicFactor: 1.0` and two
  texture images, which renders as polished chrome anywhere the mesh is opened. Held in the
  shared path rather than per backend so a worker that starts returning textures cannot
  reintroduce it. `pixazo._recache_clean_glb` then rewrites the cached GLB without it — the
  raw purchased bytes are still cached first, because that is the copy that survives a crash
  in parsing, but what is left on disk afterwards is geometry only.
- **GLB vertices are welded before anything reads topology** (`pixazo._download_mesh`).
  glTF cannot share a vertex between faces that disagree on a normal or a UV, so exporters
  split them: a real mesh arrived with 143,783 vertices for 196,733 faces, 47,541 of them
  duplicates lying on top of each other. Positions said closed surface, the index buffer said
  confetti. `merge_vertices(merge_tex=True, merge_norm=True)` — the flags are what make it a
  *positional* weld; without them trimesh honours the very attributes that caused the split.
- **`_largest_component` ranks by face count, not bounding box.** Ranking by extent loses the
  model to any scrap that happens to be elongated. Combined with the unwelded seams above,
  one job bought a 196,733-face mesh and printed a 577-face sliver. Components come off the
  face-adjacency graph rather than `mesh.split()`, which materialises every fragment — 6,195
  of them on that mesh, enough to exhaust memory.
- **Post-processing is shared and lives client-side** (`SculptorBackend.postprocess`):
  Z-up rotation, largest-component pruning, optional smoothing, decimation, export. The worker
  returns *raw* geometry so there is exactly one implementation regardless of where inference
  ran, and so GPU seconds are not billed for CPU work. The frame comes back in the
  `X-DS-Up-Axis` header, which is what makes that split safe rather than an assumption.
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
- **The face budget is 100,000** (`DEFAULT_TARGET_FACES`), not 5,000. Derived from what
  the printer can express: a 50mm model has roughly 5,000mm² of surface, so 100k faces
  puts the average edge near 0.3mm — already under the 0.4mm nozzle and 0.2mm layer. At
  5,000 the edges were ~1.4mm, three and a half nozzle widths, and TRELLIS.2's 195k-face
  output arrived visibly faceted. Repair costs ~6s at this budget against Phase 2's 220s.
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
  Overridable per instance via `$DS_PIXAZO_UP_AXIS` so settling the question empirically does
  not need a redeploy.
- **`image_url` takes a URL, not an upload.** There is no documented upload endpoint, so
  `_resolve_image_url` inlines the blueprint as a `data:` URI by default — zero infrastructure —
  and uses `$DS_PIXAZO_IMAGE_BASE_URL` when a public bucket or tunnel is available instead.
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
mesh bytes with `X-DS-Up-Axis`, `X-DS-Model`, `X-DS-Model-Version`, `X-DS-Mesh-Format`.

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

### Organizer — the parametric path (pythonsrc/organizer/)

The pivot's engine: a **spec schema** and **two archetypes**, entered through
`pipeline.py --spec PATH`. *The LLM interprets words; it never produces
geometry* — and the spec is the boundary that rule describes. Everything left of it may
be probabilistic; everything right of it is deterministic, and the same spec compiles to
the same STL byte for byte (`tests/test_deck_box.py` and `tests/test_card_divider.py`
pin that).

- **`spec.py` is stdlib-only, on purpose.** Frozen dataclasses (`OrganizerSpec`,
  `Compartment`, `CardStack`, `Lid`, `Divider`, `Constraints`, `Process`), millimetres
  rounded to 1 µm on construction so `from_dict(to_dict(s)) == s` holds exactly,
  `from_dict`
  refusing unknown keys, and one `SpecError` listing *every* problem with its dotted
  path. `canonical_json` / `spec_hash` / `spec_diff` make one spec one string, one
  hash, and two specs a path-by-path diff (F8). `pythonsrc.organizer` exports the schema
  and nothing else, so the api-server image — no trimesh, no manifold3d — can import it
  when the request model grows a spec field. Do not add pydantic here; it is not in the
  pipeline image.
- **An archetype's parameters are a *section* on the spec, and an absent section is
  omitted from the canonical form.** `Lid` and `Divider` are `Optional[...] = None` and
  named in `_OPTIONAL_SECTIONS`, which is what `to_dict` drops when they are None.
  `dataclasses.asdict` would have written `"divider":null` into every deck box spec ever
  stored — moving every one of their hashes for a field they do not mention, and moving
  them all again for the next archetype's section. `from_dict` defaults each to None, so
  the round trip is unaffected and the fixed hash vector in `tests/test_organizer_spec.py`
  did not move. `RawSpec` in `web/src/api/client.ts` declares both sections optional for
  the same reason. The alternative — a `SCHEMA_VERSION` bump — refuses every existing
  spec file for an additive field.
  The parameters live on the spec rather than as archetype constants because F8 iterates
  a design by spec *diff*: "make the tab wider" has to be `divider.tab_width_mm`.
- **`constraints.max_external_mm` is never the limit an archetype compares against.**
  `Constraints.fit_margin_mm` (default **2,0 mm**) comes off every axis first, via
  `effective_max_external_mm()` — the one place the subtraction happens, so two
  archetypes cannot disagree about what the limit is, and `archetypes/common.py`'s
  `external_overshoots` is the one place it is applied. A box internal is measured
  off one copy, copies of the same game vary ±1–2 mm and no public database exists
  (`docs/dimension-kb-research.md` §7); the audited insert standard makes the 2 mm
  reduction mandatory because an insert that presses outward splits the cardboard
  corners. The remedy names the arithmetic (`exceeds 74.6 mm (max_external 76.6 −
  2 margin)`), because two millimetres nobody typed must be explained where they
  refuse something. **`fit_margin_mm: 0` is for a person who measured the box they
  are filling** and restores the old comparison *and* the old sentence — the
  parenthetical is omitted when no subtraction happened. This moved every spec
  hash once: a scalar with a default is written into the canonical form like
  `process.wall_mm`, and the alternative, a `SCHEMA_VERSION` bump, refuses every
  existing spec file for an additive field.
- **Each archetype refuses the other's section by name.** `deck_box` refuses a
  `divider`, `card_divider` refuses a `lid`. Ignoring a section prints a different part
  than the one asked for, silently, which is the same failure as ignoring an unsupported
  field.
- **`archetypes/common.py` holds what is not about one shape.** The
  exactly-one-compartment rule (`single_compartment_problem`), the plane-count assertion
  (`expect_planes`) and the view-row builder (`view_row`), each taking its own wording as
  an argument so the sentence a person reads stays the archetype's. It was extracted when
  the second archetype landed — that is the moment a habit becomes an API — and not into
  `compiler.py` (the kernel bridge and the measurers) or `archetypes/__init__.py` (which
  imports the archetype modules, so a helper there is a circular import).
- **`dimensions.py` is a seed, not the KB.** The standard card footprint, the single and
  double sleeved envelopes and the three design pitches (0.305 / 0.60 / 0.70 mm per
  card), each with its source from `docs/dimension-kb-research.md`. Only `standard` is
  offered: the Japanese size has no sourced sleeve envelope and an invented one is
  exactly the fabricated number the schema exists to refuse. The M2 KB replaces this
  file; `resolve_stack`'s `basis` string is what the UI's fits line shows.
- **`card_divider` is one flat plate with a label tab, and the second archetype is what
  proves the API is an API** (issue #65, 2026-09-10). The plate is the sleeved envelope
  exactly — **no margin**, because no divider margin is sourced anywhere and the one
  candidate (`cavity_clearance_mm`, 1,5 mm) would make the plate as wide as this
  project's own deck box cavity, a fit that jams. Seven measured features
  (`plate_width/height_mm`, `thickness_mm`, `tab_width/height/offset_mm`,
  `total_height_mm`), all seven on the mesh — unlike the deck box, which designs a stack
  height no geometry carries. One part, so the gate is told `expected_components=1` and
  scores it 100 / `ready` (the deck box's `min_wall_thickness` warn does not appear: a
  1,4 mm plate reads over the floor at the ~0,4 mm pitch a 102 mm part gets).
  `CardStack.count` does not enter the geometry — a divider labels a group of any size —
  and the fits line says so rather than the archetype refusing a count.
  `thickness_mm` defaults to 1,4 mm, the middle of the 1,2–1,6 mm band the audited
  insert document gives (roadmap §0.5 — **one practitioner's practice, not a standard**);
  the tab's 20 × 10 mm are **design defaults with no source**, and `to_view` says
  "unsourced" on the row rather than presenting them as measured.
  **It is built as one extruded outline, not two boxes unioned.** Boxes were tried
  first: a `left` or `right` tab has a side face coplanar with the plate's, the kernel
  keeps vertices from that intersection, and the mesh came back carrying a Y plane at
  `plate_height − overlap` that no design dimension accounts for and `measure` could not
  tell from a real one. `manifold3d.CrossSection(...).extrude(t)` has exactly the
  design's planes — same kernel, no new dependency, and the primitive roadmap §0.5
  already names for the chamfer work. `measure` reads X **per region** for the same
  reason: the plate's two planes off its bottom edge, the tab's off the vertices above
  the plate's top plane, and `tab_offset_mm` as the difference — which is also the only
  way `left` and `right` are distinguishable (both give three X planes) and the only way
  the offset survives `orient_for_print`'s re-centring.
- **Archetype rules live in the archetype.** A lip thinner than `min_feature_mm`, a
  second compartment, magnets, a lid taller than the cavity — `deck_box.validate`
  refuses each with the remedy named. A tab as wide as its plate, a missing `divider`
  section, a sub-`min_feature_mm` tab — `card_divider.validate` likewise. Ignoring an
  unsupported field prints a different box than the one asked for, silently.
- **Every designed feature is measured back off the mesh** (`deck_box.measure`, the
  shape of text-to-cad's measure/align checkers): the plate is split into body and lid,
  their distinct axis-aligned planes are read, and each feature is a difference of
  planes. It runs on the compiled mesh *and on Phase 3's output*, which is what makes the
  ±0.05 mm assertion honest — it measures what the slicer receives. A plane count that
  does not match the design is itself the finding (`MeasureError`).
- **`--spec` is the `--skip-visualizer --skip-sculptor --mesh --no-scale` seam with a
  compile step in front.** The three flags are implied (`_apply_spec_mode`) — the run
  that forgets `--no-scale` prints a 50 mm deck box. `--mesh` and `--hollow` are refused.
  The compile runs inside the **real Phase 2 banners**, so the UI's "Compiler" moves
  truthfully and the banner contract is untouched. A spec run substitutes nothing:
  `_will_use_reference_assets` and `_should_install_reference_blueprint` both return
  False, so it lands in `data/outputs/{job_id}` and gets no invented blueprint, and a
  `--blueprint` it is handed is dropped with a warning (the mps_native strategy
  hardcodes one; reading the shared path would record another job's render as this
  job's provenance). The job directory holds `compiled_mesh.stl`, `spec.json`
  (canonical), `compile_features.json` and, after Phase 3, `dimension_report.json`.
- **Phase 3 asserts a spec run; it never repairs it** (`_repair_mode_for`,
  `Engineer.process(repair_mode="assert")`). A compiled mesh is watertight by
  construction, so a defect is a compiler bug, and repairing it hides the bug — the
  voxel escalation rebuilds the surface at a pitch that discards the dimensions the spec
  fixed, while `scale_applied: false` says they were honoured. `assert_manifold` checks
  what repair would fix (watertight, boundary and non-manifold edge counts, winding and
  positive volume, kernel acceptance) and raises `MeshAssertionError` naming every
  finding; nothing is exported. `repair_method="asserted"` is the fourth value of that
  key. Assert mode requires `target_mm=None`; `--mesh` stays on the repair path, because a
  mesh of one's own made no promise about its topology.
- **Then the dimensions are asserted** (`_assert_spec_dimensions`): the spec Phase 2
  recorded is reloaded from `spec.json`, the engineered mesh is measured with the
  archetype's `measure()`, and every feature in `MEASURED_FEATURES` is compared at
  `DEFAULT_TOLERANCE_MM` (0,05 mm). `dimension_report.json` is written **before** the
  verdict so a failure is inspectable; one `[DS] Dimensions: 19/19 …` line and a `✗` per
  miss are printed; the report rides on the row as `repair_report["dimension_check"]`
  (the `achieved_extent_mm` precedent — no new column); and a miss is a `MeasureError`,
  which is a failed Phase 3. A spec run that ships a wrong dimension has failed, however
  watertight it is. `tests/test_organizer_dimensional_accuracy.py` sweeps 405 specs
  across the deck box's envelope and 324 across the divider's (sleevings × tab positions
  × thicknesses × tab sizes) on the exported, reloaded STL, plus a corner set through
  the assert path for each, and runs as its own CI step. Per-archetype `parametrize`
  blocks, because the *generic* sweep across every archetype is issue #85 and still open.
- **The compiler is the generation model.** `generation_model = "organizer/deck_box"` or
  `"organizer/card_divider"`,
  `generation_model_version = "1"`, `generation_backend = "local"`, the spec hash and
  features in `generation_params`. No new column — this is exactly what those columns
  record. `blueprint_*` stay NULL, correctly. `size_source="spec"` is written by
  `POST /jobs` when the request carries a spec (below).
- **The gate is told the part count**, read off `len(compile_result.parts)` so no
  archetype knowledge lives in `pipeline.py`. `evaluate_printability(expected_components=)`:
  a body and a lid are two grounded bodies as designed, and used to score every deck
  box "risky" for a possible unintended split; a divider is one. A mismatch still warns;
  a floating body
  still fails. The remaining warn on a deck box is `min_wall_thickness`: the measurement
  pitch grows with the plate's width, so a 1.4 mm lip reads as "within tolerance of the
  minimum", and the verdict stays `risky` because that check is critical. That is the
  check's known quantisation, not a thin lip. A divider scores 100 / `ready`.
- **`POST /jobs` accepts a spec** (`JobRequest.spec`). Validated on the model with the
  stdlib-only schema — `pythonsrc.organizer` imports nothing heavy for exactly this — so
  a bad spec is a 422 listing every problem and no row is written; the archetype's own
  rules need the kernel and arrive as a failed Phase 2. A spec beside `target_mm`,
  `scale_axis` or `size_source` is refused: the spec decides every dimension. The
  handler writes the spec canonically to `data/inputs/{job_id}/spec.json`, sets
  `request.spec_path` to the container path (the `blueprint_path` precedent) and
  forwards `--spec`; `_phase_skips` makes a spec request skip both generative phases —
  no native Phase 1, no blueprint gate — and neither `_pipeline_args` nor the mps_native
  command hands it `--skip-visualizer --blueprint <shared>`. The row records
  `size_source="spec"` with `requested_size_mm` and `requested_scale_axis` NULL.
- **The spec comes back on `GET /jobs/{id}`, off the row** (`job_spec_summary`,
  2026-09-09): `spec` (canonical), `spec_hash`, `archetype`, `archetype_version` and
  `dimension_check`, all NULL for a prompt job. **The row is authoritative, not the
  file.** `JobRequest._spec_is_valid` now returns `OrganizerSpec.from_dict(v).to_dict()`,
  so the canonical spec is what lands in `request_params` *and* what
  `data/inputs/{job_id}/spec.json` is written from — they cannot disagree, the row
  survives a cleared `data/outputs/`, and a request that omitted `process` no longer
  stores a spec with a hole where the wall thickness is. It is also the copy the
  handler already has: one dict lookup and one sha256, measured at **+0,02 ms on a
  7,15 ms request** (`tests/_bench_poll.py`), which matters because this endpoint is
  polled once a second. `spec_hash` prefers `generation_params["spec_sha256"]` — the
  hash of the spec the compiler actually received — and falls back to hashing the
  row's, which is the only answer available before Phase 2. The output directory is
  read **only** when the row says "spec job" and carries no spec.
  `GET /jobs/{id}/spec` is the un-polled sibling (`/provenance` precedent), adding
  `compile_features.json` and `dimension_report.json`; `SPEC_ARTIFACTS` is where
  `view.json` joins when the annotated preview lands.
- **The UI's only fit verdict is the measured one.** `specFromJob` projects the four
  fields onto `web/src/organizer/spec.ts`'s display shape, and every row in it is a
  field of the spec itself — no stack height, no internal depth. Those are `derive()`'s
  and the dimension KB's, and a second copy of that arithmetic in TypeScript is a
  number on screen that nothing computed. The Fits Check renders
  `measuredFit(dimension_check)` — Phase 3's report, in its own words ("Dimensions
  verified", not "Fits", which would claim a stack was measured against a cavity) —
  and `measuredFit` is the *only* constructor of a `FitsResult`, which
  `tests/test_job_spec_endpoint.py` pins. Three absences, three sentences:
  `NO_SPEC_REASON` (a generative job), `UNCOMPOSED_SPEC_REASON` (the composer, which
  still cannot build a spec) and `UNMEASURED_FIT_REASON` (a spec Phase 3 has not
  measured).
- **`ARCHETYPES` in `web/src/organizer/spec.ts` is exactly `spec.ARCHETYPES`**, and
  `tests/test_archetype_registry.py` binds the three lists — the schema's, the
  registry's keys and the `id`s in the TSX (read as text; there is no test runner in
  `web/`). It offered `dice_tray`, `box_insert` and `dividers` until the divider landed
  and none of the three existed: a strip cell for a shape the compiler would refuse is
  the same fabrication as a fits badge with no measurement behind it. A cell appears the
  day the compiler does. That test also asserts every registry module exposes the whole
  archetype API, which is what "adding an archetype is a module and a line" means.
- **Not built, and where it is:** composing a spec in the UI — every job the app can
  submit is still a prompt job, so `NO_SPEC_REASON` is what its own panels show — the
  annotated mm preview (`archetypes.view_for` is written; nothing serves it), the
  *generic* envelope sweep across every archetype (#85 — there are two, each with its
  own `parametrize`), the token tray and box-insert archetypes, LLM extraction and the
  KB (M2). `python -m pythonsrc.organizer example|compile|measure [--report]` is the
  developer loop; `example` takes the archetype positionally or as `--archetype`.
- **No spec job has yet reached the real slicer, a printer or the telemetry database.**
  Everything above is verified to Phase 3 plus printability against a CuraEngine
  **stub** — `infra/ci/curaengine_stub.sh` exits 70 if anything really invokes it — so
  the brim decision over two grounded bodies, `slice_status`/`layer_count`/the filament
  figures (all derived from an E axis that only exists once something sliced) and the
  dispatch gate against the OctoPrint simulator are unexercised. The harness for that
  run is `tests/test_spec_job_end_to_end.py` (`slow`, `real_printer`: it needs Docker,
  the built `ds-mvp-pipeline` image, the CuraEngine *inside* it and a simulator on
  5001, and skips naming whichever is missing) and `docs/RUNBOOK-spec-job.md` is the
  same run by hand, with `tests/test_runbook_spec_job.py` holding every command,
  service, endpoint, column and filename it names against the source. Roadmap §0.3
  Phase 1 carries the box, and it stays `[~]` until a real row's `trace` output exists.

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
- **`POST /jobs/{id}/events/preview-reached` is the activation metric's numerator**, and
  `GET /feedback/stats` carries the rate beside the response rate. "≥ 60 % of prompt
  submitters reach a preview" (PRD §7, roadmap §6A) had a denominator all along — `prompt`
  is required on `POST /jobs`, so a job row *is* one prompt submission — and nothing
  recorded that a person ever saw the geometry they asked for. One event kind
  (`preview_reached`), no migration, and the same shape and server-side dedup as
  `outcome_prompt_shown`: **once per job**, so a reload, a switch between the mesh and
  toolpath tabs or a second visit next week cannot each count again. Deduplicated on the
  server and not only in the client because a reloaded page has a fresh memory of what it
  has already sent, and the running view is the surface people refresh.
  `TelemetryDB.activation_funnel()` counts `COUNT(DISTINCT job_id)` against the job count,
  which is the same "over jobs, not raw events" rule `feedback_funnel` was fixed to
  follow — either guard alone would let the ratio exceed 1. **`dev` jobs are excluded from
  both halves**, for the reason `dev` is excluded from `answered`: a cube printed to verify
  a pipeline change is not a pilot user. The key is `jobs_submitted`, not
  `prompts_submitted`, because `prompts_shown` beside it counts *outcome* prompts.
  **It is fired from the stage, not from a phase banner** (`NewJob.tsx`): an artifact
  appearing on disk is a fact about the pipeline, and this metric is about someone looking,
  so the condition is that the mesh or the toolpath is the *rendered* tab **and** has
  something behind it — `MeshViewer` draws a waiting animation until Phase 3 lands, and
  counting that would report activation for a job whose preview never arrived. `meshReady`
  and `sliceReady` are one definition each for that reason, read by the stage advance, the
  event and the stage itself. The `≥ 30 % export` half of the same metric needed no new
  instrument: `download` plus `?preview=1` already separates keeping a result from looking
  at one.
- `GET /jobs/{id}/download` logs a `download` event and increments `download_count` before
  streaming — the response is lazy and may be abandoned mid-flight. `?preview=1` serves the
  same bytes and records nothing: the toolpath viewer polls this endpoint to *render* the
  G-code, and without the flag `download_count` was a component-mount counter, not the
  "a person chose to keep this" signal it is documented as.
  **`?format=gcode|stl|3mf` chooses which of the job's three files** (`DOWNLOAD_FORMATS`);
  `gcode` is the default, so every caller written before the parameter — the viewer, the
  dispatch gate, a bookmark — is unchanged. One endpoint with a parameter rather than three
  endpoints, because the event and `download_count` mean "a person kept this result" and
  that fact does not subdivide by extension; the format rides in the event `detail`
  instead, which is what makes "did anyone use the 3MF" a query. An unrecognised format is
  a **400 naming the three that work, decided before the job is looked up** — a 404 sends
  someone looking for a missing file when the spelling is what is wrong — and a *known*
  format with no file (a job engineered before the 3MF existed) is still a 404.
  `GET /jobs/{id}/mesh` stays as it is: it serves the `.obj` inline for the viewer, which
  is not a handoff. `tests/test_download_formats.py` binds the three sides that must
  agree — the formats the endpoint serves, the ones `DownloadFormats.tsx` offers, and the
  suffixes `Engineer.EXPORT_SUFFIXES` writes.
  **A servable format that is not swept mis-attributes a file.** `resolve_job_artifact`
  falls back to the flat `data/outputs/` layout for a *finished* job with no file of its
  own, and the `is_per_job` guard in `download_job_output` refuses that fallback only for
  a job that never completed. What protects the completed ones is `POST /jobs` deleting
  the flat files — so the sweep list is `server.stale_flat_artifacts`, read out of
  `DOWNLOAD_FORMATS` rather than spelled out a second time. Adding `?format=3mf` to one
  list and not the other left a CLI run's flat `engineered_mesh.3mf` surviving every
  later job, and answered a 200 with it for any finished job whose own export was
  missing or recorded in `export_errors`. `tests/test_job_artifacts.py` binds the two
  lists and exercises the flat fallback in every format.
- **WebSocket**: `/ws/jobs/{job_id}` streams phase progress, telemetry batches, and job completion — managed by `JobBroadcaster`
- **Job lifecycle**: POST `/jobs` creates a DB record and launches pipeline subprocess asynchronously; polls `[DS]` banners from stdout for phase tracking
- **Logging** (`server/logging_config.py`, called at import): the app had no handler,
  level or format, so under uvicorn it inherited a root logger uvicorn never configures
  and every `logger.info` was discarded. One stdout handler, severity in colour when the
  output is a terminal (`$DS_LOG_COLOR`, `$NO_COLOR`), level from `$DS_LOG_LEVEL`.
  A `log_requests` middleware logs one line per request with its duration, severity
  following the status code, and demotes polled endpoints (`/health`, `/config`,
  `/feedback/pending`, `/system/printer/status`, `GET /jobs/{id}`) to DEBUG.
  **Uvicorn's access log is switched off** because it logged every request a second
  time, at INFO, cancelling that demotion out; `$DS_UVICORN_ACCESS_LOG=1` restores it.
- **SPA serving**: catch-all route serves `web/dist/` — the React app must be pre-built before server start
- **Every request-controlled path join goes through `contained_path`.** Nothing between
  the socket and a handler collapses dot segments: uvicorn percent-decodes the request
  target straight into `scope["path"]`, and Starlette's `{...:path}` converter matches
  `/` and `..` alike — so `GET /%2e%2e/%2e%2e/%2e%2e/etc/passwd` reached `serve_spa` as
  `../../../etc/passwd`, `os.path.join` walked out of `web/dist`, and `FileResponse`
  streamed the file. There is **no end-user authentication in this server**, and the
  api-server process is the one with `~/.ds-mvp/.config_key` bind-mounted, so that was
  an unauthenticated read of the Fernet key for the store holding printer API keys —
  and of `.env` and `pythonsrc/config.py` beside it. `contained_path(base, *parts)`
  joins and then requires `is_relative_to(base)` **after `resolve()`**: a lexical check
  passes a path whose every component is innocent and whose symlink target is not, and
  an *absolute* part needs no `..` at all (`Path("web/dist") / "/etc/passwd"` is
  `/etc/passwd`, and `//x` reaches a `:path` group as `/x`). Four joins use it —
  `serve_spa`, `resolve_job_artifact` (both `job_id`, which arrives as `..` from
  `/jobs/%2e%2e/blueprint`, and `filename`), `resolve_job_profile`, and the two
  `repo_root / job.profile_name` profile reads, where `profile` is free text from
  `POST /jobs` that is `json.load`ed and handed to `run_operator.py`. A refused SPA
  path falls through to `index.html` rather than 403-ing, because client-side routing
  means an unmatched path is the normal case for a deep link.
  `tests/test_static_path_traversal.py` holds the line, and it sends every traversal
  **percent-encoded**: `httpx` normalises a literal `../` away client-side, so a test
  written the obvious way passes against the vulnerable code.
- **A printer profile may only be a file in `pythonsrc/profiles`** — `PROFILES_DIR`,
  `resolve_profile_path`, `profile_path_or_default`. `profile` is free text on
  `POST /jobs`, and `create_job` reads the file it names twice:
  `resolve_printer_target` pulls `firmware` / `base_url` / `api_key` out of it, and
  `_profile_snapshot` `json.load`s it and stores the **whole parsed dict** as
  `process_params`, which `GET /jobs/{id}/provenance` serves back verbatim. Since
  `Path(repo_root) / "/any/file.json"` is `/any/file.json`, that was an
  unauthenticated read of any JSON file the server can open, written into the dataset
  and handed back — no traversal needed. **`DEFAULT_PROFILE` is the same value, not a
  more trusted one**: it is set through `PUT /config` and `web/src/pages/NewJob.tsx`
  forwards it as `request.profile`, so it takes one boundary, at all nine join sites.
  Confining to the checkout would have stopped the absolute read and left every JSON
  file under it an accepted profile — `web/package.json`, `licenses/*.json`,
  `tsconfig.json` — which is an in-repo existence oracle and lets `run_operator.py` be
  handed `package.json` as a printer. Three consequences, each deliberate:
  **only an *escaping* path is a 422**; a profile that merely does not exist stays a
  202 and disables printing, which is what `"default"` and `"test"` do and what
  `tests/test_server.py` pins — and the distinction falls out of `contained_path`,
  which returns a path for a contained file that does not exist and None only for an
  escape. The refusal sits **beside the IP screen**, before `job_id` is minted and
  before the artifact-cleanup loop, for the reason given there. And
  `profile_path_or_default` falls back to the bundled Ender 3 at the sites that are
  not request boundaries, because honouring an escaping path meant reading a printer
  address and API key out of a file the caller chose.
  **Behaviour change:** an absolute or out-of-repo profile path no longer resolves
  anywhere. `printer_status._ceiling` used to end
  `open(candidate if candidate.exists() else profile_ref)` — deliberate absolute-path
  support, and the same arbitrary read reachable through
  `GET /system/printer/status`; that fallback is gone. `PrinterSetup`'s datalist was
  already entirely `pythonsrc/profiles/*.json`.
  **Still open, and worse than either:** `PUT /config` has no authentication, so a
  caller can repoint `OCTOPRINT_URL` at their own host and have the server ship it
  `OCTOPRINT_API_KEY`. That is a bigger hole than any profile read and wants its own
  issue.
- **Config store** (`config_store.py`): Fernet-encrypted key-value store in the telemetry database (`app_config` table); the key stays on the host at `$DS_CONFIG_KEY_PATH`, default `~/.ds-mvp/.config_key`
- **SimulatorManager** (`simulator_manager.py`): manages a real dockerized OctoPrint on port 5001 (`docker compose -f infra/docker-compose.yml --profile simulator up -d octoprint-simulator`), found by compose label or name. Its virtual printer plugin is enabled in `data/octoprint/octoprint/config.yaml`, so the full dispatch path runs without hardware. `start_moonraker()`/`stop_moonraker()` are deprecated stubs that always report not-running — there is no Moonraker simulator, and `tests/mocks/` no longer contains mock servers.

### Data Flow

1. User submits job via UI → POST `/jobs` → `PrintJob` inserted in the telemetry database (PostgreSQL on Supabase)
2. Pipeline subprocess launched → stdout parsed for `[DS]` phase banners → WebSocket broadcasts
3. If `--print` flag set: Phase 4 slices mesh to G-code, Phase 5 uploads to printer via `PrinterFactory`
4. After Phase 5 starts printing: a telemetry collector (Moonraker WebSocket or OctoPrint SockJS) plus an `AnomalyDetector` stream samples into the database; whichever process claims the job first is the sole writer
5. Frontend receives live phase updates, telemetry, and job outcomes via WebSocket

### Telemetry (pythonsrc/telemetry/)

- **Schema** (`schema.py`): Four dataclasses — `PrintJob`, `TelemetrySample`, `FailureEvent`,
  `JobEvent` — with JSON serialization
- **The capture principle**: every column below exists because the value has exactly one moment
  at which it is knowable. A seed drawn and thrown away cannot be recovered; a profile read at
  query time is whatever the file says today, not what the job printed with; "the printer
  finished" is not "the part survived". When adding a signal, ask when it stops being
  recoverable — that is when it must be written.
- **Seeing the capture path** (`pythonsrc/telemetry/trace.py`):
  `python -m pythonsrc.telemetry.trace <job_id|prefix>` renders one job's row as the nine
  writes that filled it, in write order, each annotated with the `TelemetryDB` method and
  call site that performs it, and each column marked written / placeholder / expected-null.
  `--list` indexes recent jobs with a coverage count, `--latest` takes the newest, `--json`
  emits a per-stage coverage map, `--db` takes a PostgreSQL URL (default
  `$DS_DATABASE_URL`). The session is opened `READ ONLY` server-side: an inspection tool
  holding a writable handle is one `commit` away from being a writer.
  `STAGES` in that module is the map, and `tests/test_telemetry_trace.py` asserts it against
  the live schema — the union of its columns must equal `print_job`'s exactly, in both
  directions, with each column claimed by one stage. **Adding a capture column means adding
  it to `STAGES`**, or the suite fails; that guard is the only reason the map is still true
  a month after it was written. It had in fact been failing: `git_sha`,
  `used_reference_assets`, `dispatched_printer_url`, `repair_report` and
  `print_duration_s` were all added without stage entries, so the guard was red and
  every later column would have been blamed on whoever noticed. The map now carries
  `run_context`, `dispatch` and `print_duration` stages — each naming its own writer,
  because a stage names exactly one `TelemetryDB` method and `print_duration_s` is
  written by the collector rather than by the outcome verdict. `traced_db`'s "complete"
  job writes all of them, so an empty stage in that fixture means a hole in the tool
  rather than a hole in the fixture.
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
- **The blueprint sidecar carries Phase 1 provenance across the process boundary.** The
  primary Mac workflow runs the visualizer as its own native process and the pipeline with
  `--skip-visualizer`, which used to record only the image hash — seed, prompt, model all
  NULL for every job on that path. `write_sidecar()`/`read_sidecar()` in `blueprint_spec.py`
  serialize the `BlueprintResult` next to the PNG; the sidecar stores the image's own sha256
  and a mismatch reads as *no sidecar*, because a stale sidecar attributing an old seed
  to a new image is worse than none. That guard is now belt-and-braces rather than the
  only line of defence: a job renders into `data/inputs/{job_id}/`, so the sidecar has
  the directory to itself (see **The blueprint is per job** below). The pipeline reads it
  back on the skip path; do not "simplify" this into recording only the hash again.
- **Requested size**: `requested_size_mm`, `size_source`, `requested_scale_axis`,
  written at insert time by `POST /jobs`. `requested_size_mm` is **NULL when nobody
  chose** rather than 50.0 — the applied value is already recoverable from
  `repair_report["target_mm"]`, and a stored default is indistinguishable from a user
  who typed the default. `size_source` is `default` | `user` | `prompt_hint` | `spec`
  and is *always* written, because "the default applied" is itself the fact; the client
  may claim `user` or `prompt_hint` for a size it sent, but never `default` or `spec`,
  which the server derives — `spec` from the presence of `JobRequest.spec`, with the
  size and axis NULL because the spec fixed every dimension. `requested_scale_axis` is the **promise made to the requester** — the
  axis the control was labelled with — while `repair_report["scale_axis"]` is the axis
  Phase 3 actually applied. Two columns precisely so they can disagree: a control
  labelled "Height" that produced a longest-edge part is a bug this pairing makes
  visible, and `repair_report` is an unschematised blob that cannot be queried for it.
  `scale_axis` is written into `last_report` unconditionally — including as `"none"`
  when there was no extent to scale — because an absent key in a JSON blob cannot be
  told apart from a pre-change row.
- **Run context**: `git_sha` and `used_reference_assets`, written by
  `pipeline._record_run_context()` before any phase runs. The fixture flag used to exist only
  in the output directory's `dev-` prefix — nothing queryable — which made fixture runs the
  largest training-set contamination risk. False is written as 0, not skipped: "verified real"
  must stay distinguishable from "predates the column". `git_sha` resolves via
  `pythonsrc/telemetry/run_context.py` ($DS_GIT_SHA beats `git rev-parse`; the server stamps
  it into the container env, which carries no .git).
- **Dispatch provenance**: `dispatched_printer_url`, written at the moment of dispatch by the
  gate endpoint, the pipeline's Phase 5 and `run_operator.py` — deliberately the *pre*-Docker-
  rewrite URL, since `host.docker.internal` is a container artifact. This is the only thing
  that distinguishes simulator telemetry (localhost:5001) from real hardware; `printer_id` is
  a constant and profiles are resolved on read.
- **Mesh lineage**: `raw_mesh_sha256` / `raw_mesh_features` and `repaired_mesh_sha256` /
  `repaired_mesh_features` bracket Phase 3, making repair's effect measurable. `mesh_features`
  keeps its existing meaning — the printed mesh. Written by `pipeline._record_mesh_lineage()`
  via `printability.extract_features(mesh, thickness=False)` on the raw mesh; the voxel wall
  thickness pass is skipped there because it is expensive and meaningless before scaling.
  `repair_report` (from `Engineer.last_report`) rides along: which repair path ran
  (manifold / trimesh_fallback / voxel_remesh), rounds, faces dropped, and the scale factor —
  previously log-only, which made "did voxel remeshing hurt outcomes" unanswerable.
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
  `outcome_prompt_shown`, `outcome_prompt_dismissed`, `outcome_reported`, `preview_reached`.
  One table rather than a
  column per signal, so the pilot's response-rate query needs no migration — and the
  activation metric's instrument was in fact one line in `JOB_EVENT_KINDS` (see
  `preview-reached` under **Server**). `download_count` and
  `parent_job_id` are denormalised onto `print_job` for the common query.
  Adding a kind needs no DDL (`job_event.kind` is TEXT, deliberately not a CHECK
  constraint — `JobEvent.__post_init__` is the validation, in one place) and no
  `telemetry/trace.py` change either, since that map covers `print_job`'s columns.
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
- **DB** (`db.py`): PostgreSQL via `psycopg` 3, one shared `psycopg_pool` per process
  per URL. A `TelemetryDB` is cheap to construct — the server does it per request — and
  borrows a pooled connection for exactly one operation; `close()` is a no-op kept for
  the callers that pair it with construction. Prepared statements are off so the same
  code works behind Supabase's transaction pooler; connections are validated on checkout
  so one Supabase closed while idle is replaced rather than handed out.
- **One database, and where it lives.** The telemetry database is **PostgreSQL on
  Supabase** (project `lxdtmktcaaypdqeuheoq`), reached by every process — the API
  server, the pipeline container, the native Mac pipeline, `run_operator.py` — through
  one variable, **`DS_DATABASE_URL`**, set in `.env`. Compose passes it to `api-server`
  and `pipeline-runner`, the server forwards it into the pipeline container (rewriting a
  loopback host to `host.docker.internal` for a local PostgreSQL in development), and
  `load_native_env.sh` lifts it into `make start-native`. **An unset URL is a
  configuration error** (`DatabaseConfigError`, naming the variable), never a silent
  default: the previous storage had one, and it split native runs and container runs
  across two databases without anything saying so. The Fernet key for the encrypted
  config store stays on the host at `~/.ds-mvp/.config_key`, which is what the
  `~/.ds-mvp:/root/.ds-mvp` bind mount is still for.

  **Why it moved.** It was one SQLite file, `~/.ds-mvp/telemetry.db`, bind-mounted into
  the containers — and it corrupted once: `telemetry_sample`'s b-tree ended up with pages
  referenced twice, 346 rows were unreadable, and `.recover` salvaged none of them.
  `synchronous` was FULL and there was no hot journal, so it was not a crash mid-write;
  on macOS the containers run in a Linux VM, so the host process and the pipeline
  container were two machines sharing a file over VirtioFS, which SQLite does not
  support for concurrent writers. Everything built around the file afterwards —
  integrity check at startup, rotating snapshots, an off-disk mirror, "WAL deliberately
  off" — compensated for the storage. A network PostgreSQL removes the failure class
  (real concurrent writers, real transactions, backups that are Supabase's), so all of
  that machinery is gone, and with it `TELEMETRY_DB_PATH`, `POST /system/database/backup`
  and the `DS_DB_BACKUP_*` variables. Existing rows were **not** migrated: the product
  had not launched and a fresh schema was cheaper than a conversion nobody needed.

  **Schema.** `schema_statements()` in `db.py` is the single source. `init_schema()` runs
  it (idempotent, under an advisory lock so two processes starting together queue rather
  than race the catalogue) and then adds any column in `_PRINT_JOB_EXTRA_COLUMNS` an
  existing table lacks — the one migration this module performs. `supabase/migrations/
  *_telemetry_schema.sql` is *rendered* from the same function
  (`python -m pythonsrc.telemetry.db --ddl`) and `tests/test_supabase_migration.py`
  fails when the file and the code disagree. JSON payloads are `JSONB` (a malformed blob
  is refused at write time, not tolerated at read time), timestamps `TIMESTAMPTZ` (read
  back UTC-aware; `_str_to_dt` still accepts ISO text), reals `DOUBLE PRECISION`.
  **Row-level security is enabled on every table with no policies**: Supabase exposes
  `public` through PostgREST to its `anon`/`authenticated` roles, and RLS with no policy
  is what stops them reading the dataset; the server connects as the tables' owner and is
  unaffected.

  **Health, not integrity.** `TelemetryDB.health_check()` answers "does it respond and
  are the tables there" — a missing table is reported as `missing table: <name>` so
  `server.check_database_health` can tell "run `init_schema`" from "the network is down",
  and does the former itself. It runs at startup and every `$DS_DB_HEALTH_INTERVAL_S`
  seconds (default 60, 0 disables); `GET /health` reports the *cached* verdict with a
  `checked_at`, because the endpoint is polled and a dead database would otherwise hold
  every poll for the pool timeout (`$DS_DATABASE_TIMEOUT_S`, default 10). A server whose
  database is unreachable at startup still comes up, degraded, and the periodic check
  creates the schema when the connection returns; a server with **no URL** does not
  start. `tests/test_db_health.py` and `tests/test_db_connection.py` hold this.

  **Tests run against PostgreSQL too.** `tests/conftest.py` points `DS_DATABASE_URL` at
  a schema it creates before collection and drops afterwards, on the database named by
  `DS_TEST_DATABASE_URL` (CI: a `postgres` service container) or, when that is unset, on
  a throwaway `postgres:17-alpine` container it starts with the Docker CLI
  (`tests/testing_postgres.py`). Every test that needs its own database takes the
  `isolated_db` / `isolated_db_url` / `isolated_db_env` fixtures — a schema per test,
  carried in the URL as `options=-csearch_path=…` so `TelemetryDB` needs no test knob.
  The SQLite-era `:memory:` and temp-file idioms are gone. `tests/test_single_database.py`
  is the regression guard: it fails if the retired `TELEMETRY_DB_PATH` is read anywhere,
  if compose stops handing a writer the URL, or if a telemetry volume reappears.
- **Foreign keys are enforced** — declared constraints, named
  (`job_event_job_id_fkey`, …), always on. In the SQLite era they were declared and
  decorative (`PRAGMA foreign_keys` defaults to OFF), which is the actual root cause of
  the orphaned-events incident. A sample, job event or failure event for a nonexistent
  job is refused at write time (`IntegrityError`, re-exported from `db.py`).
  `feedback_funnel()` and `count_job_events()` keep their `print_job` joins and
  `count_orphaned_job_events()` stays, because a database can still acquire orphans by
  other routes. Tests that need a legacy orphan drop the named constraint for one insert
  and re-add it `NOT VALID`.
- **Collectors**: `MoonrakerCollector` (JSON-RPC over WebSocket to Klipper) and `OctoPrintCollector` (SockJS WebSocket to OctoPrint) write samples to the DB as a background asyncio task, and relay them to the API server via `internal_telemetry.send_internal_telemetry` (`DS_API_URL`) for WebSocket fan-out. OctoPrint's socket will not accept the API key directly: the collector exchanges it for a session token via `POST /api/login {"passive": true}` and authenticates as `<user>:<session>`. Sending `_api:<api_key>` instead is answered with `reauthRequired` and no telemetry ever arrives.
- **The server-side collector attaches when Phase 5 starts, not at job creation**
  (`_attach_job_telemetry`, fired by `_run_pipeline`'s `on_phase` hook when the Phase 5
  banner arrives). Attached at creation it wrote ~1 idle-printer sample per second under
  the job for the entire pipeline — hours of a machine printing nothing, shaped exactly
  like print telemetry. `OctoPrintCollector` also takes a `gcode_filename` and ignores
  printer events naming any other file: the socket reports every print on the machine,
  and a Benchy someone started from the OctoPrint UI used to settle our job's outcome.
  Its `_on_event` respects the single-writer claim, records `print_paused`/`print_resumed`/
  `printer_terminal` job events (the terminal detail carries the firmware's own `reason`),
  writes the printer-reported duration to `print_duration_s` (deliberately outside the
  outcome-precedence guard — it is a measurement, not a verdict), and fills the sample's
  `gcode_line` with `progress.filepos` — the same byte-offset semantics Moonraker uses,
  which is also what lets the clog rule fire on OctoPrint at all.
- **Single writer** (`collector_claim.py`): the API server, `pipeline.py` and `run_operator.py` can all construct a collector for the same job. Each claims a row in `telemetry_collector_claim` at the moment its first sample arrives; non-holders stand down instead of duplicating every row. Claims are released on `stop()` and can be taken over after 120s without a heartbeat.
  **Every claim write is a compare-and-swap**, guarded on the `(owner, heartbeat_at)`
  the SELECT read, with `rowcount` as the verdict. `try_claim_collector` reads, decides,
  then writes, and the writes used to be bare `WHERE job_id = ?` — so two collectors
  that both saw the same stale claim both updated it and both were told they had won.
  That is the exact double-writer the table exists to prevent, reachable only after a
  collector has already crashed, which is when the telemetry matters most. A heartbeat
  is guarded too: it must *confirm* ownership, not assert it, or it silently takes back
  a claim a rival won in the window. Losing the swap returns False, so the loser
  declines at `insert_sample` rather than merely logging.
  **Arbitration being unavailable is not the same as the database being broken.** Only
  `no such table` takes the fail-open branch — that is an older database with no claim
  table and therefore no rival collector, and the sample can still be written. Every
  other error means nothing can be written by anyone, and failing open there told the
  collector it had *won* a claim it never took: it went on to `insert_sample`, died
  there instead, and `_run_loop`'s blanket handler logged the result as `OctoPrint
  connection error` — the one thing that was not wrong. An unreachable database now
  logs one ERROR naming itself and the collector declines, and both DB writes in
  `octoprint_collector` (`_on_current`, `_on_event`) are guarded so a storage fault
  cannot masquerade as a dropped socket and tear down a working websocket once per
  sample. Repeat failures are demoted to DEBUG until one succeeds, because telemetry
  arrives about once a second.
- **Two outcomes describe the dataset, not the part.** `VALID_OUTCOMES` in
  `schema.py` now also carries `dev` and `declined`, and `NON_EVIDENCE_OUTCOMES` names
  everything a success-rate query must filter out. `dev` is a developer's test run —
  the third verdict button, gated behind `import.meta.env.DEV` so it is dropped from
  the production bundle rather than merely hidden — and exists so that verifying a
  pipeline change by printing a cube does not land in the column the pilot is measured
  from. `declined` records that someone was asked twice and does not want to be asked
  again; it is deliberately **not** `unknown`, because `job_status_from_outcome` maps
  `unknown` back to `running` and a settled job written that way would claim to be
  mid-pipeline forever.
- **`VALID_FAILURE_TYPES` is shared between the detector and the human form.** The
  first five values are the `AnomalyDetector`'s own rule names, reused by the UI's
  dropdown on purpose: when the detector fires and a person agrees, both rows must use
  the same word or "how often is the detector right" is not a query. `other` is the
  escape hatch and means nothing without `notes`. `OutcomeRequest` validates the field
  on the *request model*, not in the handler — validating later wrote the verdict and
  then refused the request, leaving the row marked `failure` behind a 422.
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
  verdict push the rate above 1. **`declined` and `dev` verdicts are responses, not answers**:
  `feedback_funnel()` excludes them from `answered` (via the verdict in the event detail) and
  reports `declined` separately — "don't ask me again" used to inflate the exact number the
  pilot is measured by. The dashboard buckets them the same way: `GET /jobs` stats has `dev`
  and `declined` keys, and neither counts as `failed`.
- **Detector** (`detector.py`): Five rules, all evaluated per sample over a 20-sample history — thermal runaway (`hotend_target > 150°C`, actual more than 25°C below target for 5 consecutive samples, **and the gap not closing** — a cold hotend climbing to 210°C satisfies the first two conditions exactly, and used to be reported as a fault seconds after dispatch), clog (progress > 5% and `gcode_line` unchanged across 10 samples while printing), layer shift (Z drops more than 0.5mm between samples, **while printing** — end-of-print parking and homing drop Z legitimately and used to be written up on healthy jobs), adhesion (`z < 1.0mm` and progress < 10% when state goes printing → **error, deliberately not cancelled**: a person cancelling a print is not machine-observed evidence about the part; if it really was adhesion, the human's own verdict says so), and extrusion issue (`extrusion_factor_pct <= 10` for 5 consecutive samples, while printing). Each type fires at most once per job (per process — the set is in-memory). Rules that read progress need an operator; `extrusion_factor_pct` is still Klipper-only, but `gcode_line` is now filled on OctoPrint too (file position), so the clog rule can fire on both firmwares. Start one per collector via `attach_detector()` — a collector's `sample_queue` is otherwise never consumed.

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

### Mesh repair — Phase 3 (pythonsrc/engineer.py)

`repair_mesh` composes trimesh (MIT, closes the surface) with manifold3d
(Apache-2.0, guarantees the result). The trimesh half used to have a hole in it:
**nothing in the chain could remove a non-manifold edge.** `fix_normals` and
`fix_winding` reorder faces, `fill_holes` adds them, `merge_vertices` welds
coincident ones — none of them can delete a third face hanging off an edge. A mesh
that arrived with non-manifold edges therefore left "repair" with the same count,
the kernel answered `Error.NotManifold`, and the unrepaired surface was shipped.
Downstream that reads as repair failing outright at every face count: the slicer
gets a mesh with no consistent inside and printability scores it unprintable.

- **Closing is a loop, not a sequence** (`MAX_CLOSE_ROUNDS`). Dropping a
  non-manifold fin opens a hole where it was attached; filling a hole, or
  stitching a boundary loop, can fuse two faces onto one edge and create a fresh
  non-manifold seam. Running each step once leaves whichever defect the other one
  created. Real meshes converge in one to three rounds.
- **Which two faces to keep on an over-shared edge decides whether repair fixes
  the mesh or destroys it.** Faces are ranked by how many of their *own* three
  edges are cleanly manifold — a face embedded in the surface scores 3, a fin
  hanging off it scores 0 or 1 — with area only as a tie-break. Ranking by area
  is the intuitive choice and it is wrong: isosurface fins are usually *larger*
  than the face beneath them, so area keeps the fin and deletes the surface.
  Measured on an 80k-face sphere with 200 fins: area dropped 440 faces and left
  322 boundary edges no later round could close, forcing a volumetric rebuild
  that lost all detail; connectivity dropped 198 and closed in one round.
- **`fill_holes` only fans over triangle and quad loops.** Anything larger needs
  `trimesh.repair.stitch`, which returns loose faces for the caller to graft on
  (`_graft` re-welds after). A boundary that neither closes nor stitches is where
  the loop gives up and logs why.
- **Winding is fixed once, at the end, and only when needed.** `fix_winding`
  walks the face-adjacency graph in Python and measures ~10s on an 80k-face mesh;
  the loop grafts patches whose winding is arbitrary, so a pass before it is a
  pass that has to be repeated. `is_winding_consistent` is a vectorised
  comparison, so a mesh that arrives consistent — the normal case off an
  isosurface — pays for the check and needs only `fix_inversion`, a sign test on
  its volume. Removing the redundant pass took an 82k-face repair from 20s to
  0.5s and a 328k-face one from 63s to 2s.
- **Edge counting folds vertex pairs into one int64 key** rather than calling
  `np.unique(axis=0)`, which sorts rows through an object-dtype view: 0.014s
  against 0.216s on an 80k-face mesh, once per round.
- **A kernel rejection escalates to a volumetric remesh** rather than shipping
  the reject. A filled voxel grid has an unambiguous inside, so marching cubes
  over it cannot produce a boundary or a non-manifold edge. It is the last resort
  and it says so in the log: detail below the pitch
  (`VOXEL_REMESH_RESOLUTION`, a divisor of the longest extent so it is
  scale-invariant — repair runs before scaling) is gone. The result is
  deliberately **not** decimated back to the input budget: quadric decimation of
  a marching-cubes surface at those ratios (measured: 100k faces to 2.4k)
  reintroduces hundreds of non-manifold edges, trading the defect the remesh
  exists to remove for a smaller file. CuraEngine is untroubled by six figures.
- **`analyze_mesh` reports `boundary_edges` and `nonmanifold_edges`.**
  "Not watertight" does not say which repair is needed — a boundary edge is a
  hole to fill, a non-manifold edge is a face to remove, and different code fixes
  each. `process` logs the pair either side of repair, so a repair that did
  nothing is visible in the log rather than three phases later.
- **`hollow_mesh` maps its shell back out of voxel space.**
  `VoxelGrid.marching_cubes` is `ops.matrix_to_marching_cubes(matrix=self.matrix)`:
  it meshes the occupancy array at a spacing of one and **ignores the grid's own
  transform**, so the surface comes back in index space — one unit per voxel, origin
  at the grid corner. Hollowing runs *after* scaling and orienting, so returning that
  unmapped turned a 50mm sphere into a 43mm one with its base 0.5mm under the plate
  and its centre 21mm off in X and Y, on every `--hollow` job, and nothing downstream
  could notice: the shell is watertight, it slices and it prints. `process` then
  re-scales and re-seats, because voxelising at a pitch this fine leaves the
  isosurface up to a voxel outside the input's surface — and only the *scaled* axis
  comes out exact. The other two carry up to one pitch of dilation: a voxel grid
  does not respect its object's symmetry unless the object happens to align with
  it, and the isotropic result the old 1.2mm pitch gave for a sphere was
  coincidence, not a property. The same omission in `_voxel_remesh` is harmless
  only because repair runs before scale and orientation.
- **The shell is measured, not eroded, and it is never one voxel thick**
  (`HOLLOW_VOXELS_PER_WALL = 2`). Eroding the filled grid one layer with the default
  6-connected structure makes the shell exactly one voxel thick, and a one-voxel
  layer following a curved surface is a diagonal staircase whose voxels touch only
  at edges and corners. `marching_cubes` meshes *face* adjacency, so it returned one
  closed surface per face-connected run: a 50mm sphere hollowed at the default wall
  came back as **378 disconnected chips**, 314 of them floating clear of the plate —
  watertight, sliceable confetti, and the reason `floating_components` (critical)
  failed rather than the escape-hole check anyone would have predicted. The interior
  is now a Euclidean distance transform thresholded at the wall, which makes the
  wall a length in millimetres instead of "one voxel, whatever that is", and the
  grid is deliberately finer than the wall. `HOLLOW_MAX_VOXELS` (2M, matching
  `printability.MAX_THICKNESS_VOXELS` — the two measure the same walls) coarsens the
  pitch on a large part, and a coarsened pitch **thickens** the wall rather than
  thinning it, because a sub-two-voxel shell is the fragmenting one. That is
  reported, not silent: `last_report` carries `wall_thickness_achieved_mm` beside
  the requested figure.
- **Hollowing vents what it seals.** Meshing a closed shell yields two surfaces, an
  outer and an inner, and the inner one is a sealed cavity that
  `printability.escape_hole` rates **fatal** — precisely because the Engineer
  created it — so every `--hollow` job was unprintable by construction. Each cavity
  is now breached to the outside along the shortest path out of it, starting from
  its **lowest** voxel: lowest because a drain belongs under the part, shortest
  (via the distance transform's feature indices, which name the nearest exterior
  voxel) because a channel bounded by the wall thickness cannot bore through the
  body on its way out. Aiming down from a cavity's *centroid* instead is wrong on
  anything non-convex — the mean of a torus's lowest ring is the middle of the hole,
  where there is no wall to breach and nothing gets vented. Three things follow, and
  each is recorded in `last_report` rather than logged and lost:
  **cavities too small to hold their own vent are filled**, not vented (below that
  size hollowing removes less material than the vent does, so the pocket is all
  defect and no saving — a real reconstruction had 37 cavities, 36 of them that
  small); **a vent that would sever the shell is abandoned**, one cavity at a time,
  because a 2.4mm channel out of a pocket inside a thin appendage takes the
  appendage with it and the gate would then report floating components on a part
  nobody asked for; and **the result is verified, not assumed** — the empty space is
  labelled and each cavity checked against the outside, because "should have
  breached" is how a sealed cavity reaches a printer. `vent=False` /
  `--no-escape-hole` reproduces the sealed shell, and the gate correctly fails it;
  that exists because a sealed shell is a real shape, not because it is a reasonable
  default.
- **Repair is not bit-exact even on a clean mesh**: `_to_manifold` hands vertices
  to the kernel as float32, so coordinates round-trip through single precision.
  Sub-micron on a 50mm part, but not zero.
- **Phase 3 writes three files, and the third one carries the unit**
  (`Engineer.export_mesh`, `EXPORT_SUFFIXES`). The `.obj` is the path the caller
  named and what `GET /jobs/{id}/mesh` renders; the `.stl` is CuraEngine's input;
  the **`.3mf` is the handoff** (PRD F9), because a printer this project cannot
  dispatch to is reached by opening a file in its own slicer, and 3MF is the only
  one of the three that records `unit="millimeter"`. An STL is a bag of triangles
  with no unit, so the receiving program guesses — and for a part compiled from a
  spec, where every dimension *is* the deliverable, that guess is the whole risk.
  Single-colour, deliberately: `_strip_appearance` discards appearance for every
  sculptor backend, so a colour written here would be one this pipeline invented.
  **Only the 3MF may fail quietly** (`OPTIONAL_EXPORT_SUFFIXES`): `last_report`
  gains `exports` (the filenames the job actually has) and `export_errors`, and the
  precedent is the printability gate — the STL is on disk and sliceable, and
  refusing to print a part because a handoff copy failed trades a working print for
  a missing convenience. The other two propagate, and the `.stl` is the one that is
  easy to get wrong: tolerating its loss does not save a print, it moves the failure
  to Phase 4 — which slices `final_mesh_path.with_suffix(".stl")` and books the
  `FileNotFoundError` as `slice_status="failed"` for a mesh CuraEngine never
  received. That is a fabricated row in the one column that answers which meshes
  fail to slice, with the cause three stages back in an unschematised blob. `lxml`
  is what trimesh's 3MF exporter imports **at
  call time**, which is why "3MF export is one line" held only inside the Docker
  images, where it arrived transitively; it is declared in `requirements-base.txt`
  and in both images that run Phase 3 now.

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
  exactly what hollowing produces if it does not vent: a sealed cavity. It is fatal only
  when the mesh was actually hollowed. `Engineer.hollow_mesh` now drills the hole (see
  **Hollowing vents what it seals** above), so a failure here is a cavity venting could
  not reach rather than the by-construction verdict every `--hollow` job used to get.
- **A crash in the scorer is recorded, not swallowed.** Scoring never fails a job, which used to
  mean a scorer exception left no trace at all: no artifact, no telemetry, and a UI that could not
  tell "nothing measured this mesh" from "the measurement broke". Both rendered as the same empty
  panel, and an empty quality panel reads as a clean one.
  `pipeline._record_printability_failure()` now writes an **error envelope** —
  `{job_id, evaluated_at, status: "error", error, error_type}` — to `printability.json` and to
  `printability_report`, leaving `printability_score`/`printability_verdict` NULL because there is
  no score and inventing one (0 for safety, 100 for convenience) would be a fabricated measurement.
  It is written only when no report exists, so a failure *after* a good score cannot overwrite it.
  `GET /jobs/{id}/printability` passes the envelope through; the UI distinguishes it from a report
  by the absence of `checks` (`isPrintabilityReport`).

### Orientation and adhesion (Phase 3 → Phase 4)

- **`Engineer.orient_for_print` does not rotate.** It used to take the axis with the
  *smallest* extent to be the flat one and rotate that onto Z, so anything that stands
  up — the thinnest axis of a figurine is left-to-right — was laid on its side on every
  job. Its docstring claimed the opposite of the code. The rotation was also
  unnecessary: Phase 2 already knows which way is up from the backend's `up_axis`, and a
  bounding box cannot recover that. It now centres in X/Y and sits the part on Z=0.
  Choosing a better *print* orientation is a real optimisation, but it is a search over
  candidate rotations scored against the process profile, not an argmin over three
  numbers.
- **Adhesion follows the measurement** (`pipeline._adhesion_args`). The profiles ask
  for a skirt, which primes the nozzle and touches nothing. When `bed_contact` does not
  pass, Phase 4 is given `-s adhesion_type=brim -s brim_line_count=N`. A brim rather
  than modelled base geometry: it peels off, and it does not print a part other than the
  one that was asked for. **The knob is `brim_line_count`, not `brim_width`** —
  `brim_width` is a Cura *frontend* setting that the UI divides by the line width before
  calling the engine, so the override this used to pass had no effect whatsoever
  (measured on CuraEngine 4.13: `brim_line_count=5` → 119 adhesion moves, `=20` → 907,
  `brim_width=2` → exactly the default). N is derived from `BRIM_WIDTH_MM` and the
  process profile's nozzle, so 8mm is 20 lines at 0.4mm and 10 at 0.8mm.
- **`fdmprinter`'s own default adhesion is `brim`, 20 lines.** Until the profile
  translation below existed, that default was what every job got, whatever the profile
  said and whatever `bed_contact` measured. A part with an adequate footprint now gets
  the skirt its profile asks for, so the brim means something when it appears.

### Slicer — Phase 4 (pythonsrc/slicer.py)

Subprocess wrapper around the CuraEngine CLI (AGPL — see Licensing). Four things about
the command line it builds are load-bearing, and each of them was once wrong:

- **A printer profile is translated into `-s` overrides.** `pythonsrc/profiles/*.json`
  carry `layer_height`, `machine_width`, `material_print_temperature`,
  `infill_sparse_density` and a dozen more, named exactly as CuraEngine names them —
  and none of it used to reach the engine. `_resolve_definitions` accepted a profile
  only when the filename ended in `.def.json`; anything else fell through to the
  bundled Ender 3 definition, silently. Selecting the Anycubic Mega therefore sliced
  for an Ender 3 at 210/60 °C on a 220×220 bed instead of 200/55 on 210×210, while
  `printability` scored the mesh against the profile's nozzle and layer height and
  `process_params` recorded settings the print never used. Verified in the pipeline
  image: the same box now yields `M104 S200` / `M140 S55` under one profile and
  `M104 S210` / `M140 S60` under the other, where the two G-code files used to be
  byte-identical.
- **Setting names are validated against `fdmprinter.def.json`** (`known_cura_settings`),
  because CuraEngine accepts `-s anything=1` without complaint — an unknown key is not
  an error, it is a setting that never applies and never says so. That is not
  hypothetical: `ender3_base.def.json` set the bed size as
  `machine_buildvolume_width`, which is not a setting, so the engine kept slicing for
  its 100×100 mm default. Connection keys (`firmware`, `base_url`, `api_key`) are
  dropped in silence; anything else unrecognised is warned about.
- **Every `-s` is emitted before `-l`.** CuraEngine applies a setting to whatever
  object is current and `-l` makes the loaded mesh current, so a setting after it lands
  in per-mesh scope where slicing does not read it. Measured: `-s adhesion_type=none`
  after `-l` left all 906 adhesion moves in the G-code; the same argument before `-l`
  removed every one. The adhesion override had been sitting in that dead position since
  it was written. `extra_args` follow the profile's own settings, so a later `-s` wins
  on any key both name.
- Booleans are rendered `true`/`false` (`format_setting_value`): `str(True)` is
  `"True"`, which CuraEngine parses as neither, so `retraction_enable` would have
  arrived disabled.

### Printer readiness (`printer_status`)

`GET /system/printer/status` answers two different questions and they must not be
conflated: `configured` means a target is set, `running` means **we asked it and it
answered**. It used to return `running: True` for any profile file that existed,
without opening a connection — so a profile pointing at a switched-off printer read as
ready, the pipeline view opened, and the failure surfaced four phases later at dispatch,
after Phase 2 had already been billed on the hosted sculptor. `POST /jobs` now refuses
on `running`, not just `configured`, and the probe delegates to `test_connection` rather
than reimplementing reachability — two probes that can disagree about one printer is how
a "ready" badge ends up beside a dead machine.

`SimulatorManager._get_container` had the same class of bug independently: compose
derives its project name from the directory it is invoked in, so the same service
accumulates container records under several project names
(`ds-mvp-octoprint-simulator-1`, `infra-octoprint-simulator-1`, …).
Listing them and taking `[0]` reported "stopped" while a working simulator answered on
port 5001. A **running** container now wins over a stopped one regardless of which
project created it, and "stopped" stays distinguishable from "absent".

A 401/403 from a printer is reported as *reached and refused*, naming the credential to
check — not as a connection failure. Surfacing OctoPrint's stock Flask 403 body
("You don't have the permission to access the requested resource") sent people looking
at their network for a wrong API key.

**`localhost` means something different on each side of the container boundary, and
only the outbound connection may be translated** (`server.container_reachable_url`).
`http://localhost:5001` is what a person types into Printer Setup, what their browser
opens, and what `dispatched_printer_url` records — it is the only thing distinguishing
a simulator print from real hardware, so the config store keeps it verbatim. From
inside the api-server container it is also the api-server. `pipeline.py` and
`run_operator.py` have made that translation since they were written, guarded on
`/.dockerenv`; the server had not, on the assumption it ran natively — but
`docker compose up api-server` is the documented way to start it, and there every
probe answered "Connection failed: All connection attempts failed" while the simulator
sat Operational on 5001, with the badge reading Offline and `POST /jobs` refusing on
`running`.

**The compose network is tried before `host.docker.internal`, because the host gateway
is not always a route.** `api-server` was missing the `extra_hosts: host-gateway`
mapping `pipeline-runner` carries, so the name did not resolve at all — but adding it
is not sufficient: on Fedora, firewalld drops traffic from a docker bridge to the host
by default, so the gateway resolves and the connection then times out. The simulator is
a container this server already manages, and container-to-container over the shared
compose network needs neither the host nor its firewall.
`SimulatorManager.internal_url()` returns that address — the compose *service* name and
the port the simulator listens on **inside** its namespace (80), not the 5001 it is
published as — and declines with None when the two containers share no network, rather
than handing back a name that fails five seconds later at connect. The host-gateway
rewrite remains the fallback for anything that is not the simulator.

**The dispatch gate hands the operator both addresses.** `run_operator.py` runs in the
api-server container and cannot derive the compose route from a loopback URL, so
`OCTOPRINT_URL` carries the route and `$DS_DISPATCH_URL` the configured address that
route stands in for — `dispatched_printer_url` must name the printer a person chose,
not the container artifact standing in for it. The gate also passes `OCTOPRINT_URL` at
all now: `resolve_printer_target` makes the config store authoritative for `base_url`,
and the operator's own fallback is the *profile's* dev default, so a real printer
configured in Settings was dispatched to localhost:5001 while the gate displayed the
right machine.

**`data/octoprint` is mounted read-only into `api-server`** so
`simulator_manager.octoprint_api_key()` can read the key the simulator boots with.
Without it that returns None, Settings' "use simulator" button sets the URL and
silently no key (`applyOctoprintSimulator` skips the write when the key is absent), and
every call to a perfectly healthy simulator comes back 403.

**Restarting the api-server stops the simulator.** `stop_octoprint()` is wired to the
server's shutdown hook, so `docker compose up -d --force-recreate api-server` takes the
simulator down with it and it must be started again afterwards. The simulator's
`config.yaml` now carries `serial: {autoconnect: true, port: VIRTUAL, baudrate: 115200}`
so it comes back Operational on its own rather than needing someone to reconnect the
virtual printer in the OctoPrint UI each time.

That hook is also why `tests/conftest.py` cuts the shared `simulator_manager` off from
the real Docker daemon in `pytest_configure`, alongside the database redirect and for
the same reason: every test entering a `TestClient` context manager fires shutdown, so
`pytest tests/` stopped the developer's running simulator mid-session with nothing in
the output saying so. It injects a factory raising the manager's own
`SimulatorAvailabilityError` — which `_client_or_none()` already treats as "cannot
tell", making `stop_octoprint` a no-op — rather than patching the method, because the
suite must be unable to reach a daemon at all, not merely decline to use one.

**The same hook stashes `data/inputs/blueprint.png` for the session.** Three tests
(`test_blueprint_gate.py` twice, `test_ip_screen.py` once) write to that exact path —
`_snapshot_blueprint` and `create_job` derive it from `server/app.py`'s own location,
so there is no path to redirect and no honest way to test the real resolution order
without it — and then `unlink()` it. That is the file a skip-Phase-1 run exists to
reuse, and the file `POST /jobs` was deliberately changed to *stop* deleting. It is
moved aside in `pytest_configure` and moved back in `pytest_unconfigure`, with
`shutil.move` rather than `os.rename`: the stash is a tempdir, routinely on another
filesystem, where `os.rename` fails EXDEV — silently, since the guard swallows OSError,
leaving the tests to delete the real file exactly as before.

Moving it aside is also what makes those tests pass on a tree where a container wrote
that PNG: the bind mounts run as root, so it comes back `root:root 0644` and the
developer's own interpreter cannot open it for writing. Renaming needs write permission
on the *directory*, not the file. When container-written artifacts pile up more widely,
`docker run --rm -v "$PWD/data:/d" -v "$HOME/.ds-mvp:/h" alpine chown -R 1000:1000 /d /h`
fixes them without sudo.

### Dispatch gate — Phase 5 waits on a person

A print is the only step that heats a nozzle for hours, spends filament and cannot be undone,
and it used to start on its own: the pipeline was launched with `--print --start-print`, so the
first time anyone saw which machine a part was going to was in the past tense.

- **The state is derived, not stored** (`server.dispatch_state`). `dispatched` when a
  `dispatch_confirmed` job event exists or the outcome is `awaiting_verdict`;
  `awaiting_confirmation` when the pipeline finished (`outcome == "success"`), the slice
  succeeded and the G-code artifact is on disk; `not_ready` otherwise. No new outcome value and
  no migration: the outcome column says what the *software* did, and "a person has not decided
  yet" is a decision record, which is what `job_event` is for. Requiring `outcome == "success"`
  is deliberate — a pipeline still running may have been launched with `--print` and would
  dispatch itself.
- **`POST /jobs/{id}/print-dispatch` requires `confirmed: true`.** Nothing else in the system
  stops a print, so the flag *is* the gate and there is no unconfirmed code path left — the rail's
  old "Print" button (which posted an empty body from `JobControlPanel`) is gone. The body also
  carries the target **as it was displayed** (`profile`, `base_url`); when those no longer match
  what the server resolves, the answer is **409**, because confirming a printer you are no longer
  looking at is not confirming. The printer is then re-probed via `printer_status()` and a dead
  one is 409'd *before* the operator subprocess runs.
- **`dispatch_target` is resolved on read, not frozen at creation** — the point of showing it is
  that it reflects a profile someone changed in Settings five minutes ago.
- On confirmation the endpoint records the event, sets `awaiting_verdict` (dispatched is not
  printed — see Telemetry), appends a phase-5 `running` record with `_append_phase_status` so the
  rail moves, and **follows the operator to its exit** rather than firing and forgetting: a
  non-zero exit writes phase 5 `error` and records `failure`, so a dispatch that never started
  does not leave a row asking a person about a part that does not exist.
- **`GET /jobs?status=awaiting_dispatch`** is what makes the step survive a page reload: such a
  job is finished as far as the pipeline is concerned, so it is absent from the running list, and
  the pending decision used to vanish on refresh. The dashboard marks the row `To send`
  (`awaiting_dispatch` per row) rather than `Success`, and `NewJob` re-attaches on mount — but
  **only to the job that tab was watching** (`sessionStorage['ds.watchedJob']`, re-checked
  against `dispatch_state`), not to whatever the filter returns newest. "Sliced and not sent"
  has no time limit, so one job nobody ever confirmed would otherwise own the landing page
  for good. Everything else is reached from the dashboard.

### IP screening and the blueprint gate

This project **manufactures and hands over a physical object**. If that object
reproduces a protected character the analysis is direct infringement: the DSA hosting
shelters cover hosting third-party content, not making goods, and the
private/non-commercial-use exception (Art. 20(1)(a) Community Design Regulation) covers
a person printing at home for themselves — expressly not a paid service printing on
their behalf. Four layers, cheapest and most certain first, each independently
shippable.

**Tier 0 — the notice** (`web/src/components/PromptNotice.tsx`). One line, shared by all
three composers so the landing page, the inline "New job" field and the zoomed field
cannot tell people different things. It states two facts and both must stay true: you
must hold the rights, and the prompt and image are kept with the job. The retention half
is checked against reality — `print_job.prompt`, `blueprint_prompt_engineered`,
`blueprint_sha256`, `data/outputs/{job_id}/blueprint.png` — because a notice claiming
less than is kept is worse than none. Styled `hint`, never `notice`: the latter is the
error treatment, and a neutral statement in the failure colour is the same class of
mistake as captioning a fixture blueprint as drawn. **ToS and the notice-and-action
procedure are deliberately not code** — see `docs/deferred-legal-tasks.md`.

**Tier 1 — the prompt screen** (`pythonsrc/ip_screen.py`, blocklist in
`pythonsrc/data/ip_blocklist.json`). Two settings, because one is wrong either way: a
screen that only warns protects nobody, and one that refuses everything it
half-recognises refuses paying pilot users for asking about fan art. A curated name is
**blocked** — refused before `job_id` is minted, which is also **before the artifact
cleanup loop** that unconditionally deletes the shared `data/inputs/blueprint.png`; a
refusal after that point destroys the previous job's output to reject a job that never
existed. A weak signal is **flagged**, recorded as an `ip_screen_flagged` job event and
shown at the blueprint gate. There is deliberately no `ip_screen_blocked` event: a block
happens before `insert_job`, foreign keys are enforced, and an event for a nonexistent
row cannot be written — blocks go to the activity feed. **Normalise, then compare**: a
raw string comparison was already defeated once in this repo by a `repo@sha` pin, so
accents, spacing, hyphens and case are folded and a bounded edit distance covers typos.
**`material_colour` is screened too** — it is free text the blueprint wrapper
interpolates into the prompt, so a screen reading `prompt` alone leaves the colour box
as a second, unwatched prompt channel.

**Tier 2 — the image screen** (`pythonsrc/ip_screen_image.py`). Prompt filtering leaks:
"a chunky yellow lightning-mouse figurine, anime style" names nothing on the blocklist
and still renders something recognisable. So the render itself is scored, **before Phase
2 is billed for reconstructing it**.

- **No reference images are stored anywhere in this repo.** The comparison is
  image-against-*text*: the curated terms are embedded as strings. Caching reference
  crops would improve recall and would mean shipping the material the screen exists to
  keep out. `tests/test_ip_screen_image.py` asserts every candidate is a `str` and that
  the package ships no image assets.
- **Control labels are not optional.** A comparison over protected terms alone has no
  way to say "this is just a vase" — every image matches whichever term is least wrong.
- **`openai/clip-vit-*` is on the deny list, and its repo tag says MIT.** The model
  card's own out-of-scope section reads *"Any deployed use case of the model — whether
  commercial or not — is currently out of scope."* This is the RMBG-2.0 lesson one layer
  deeper: read the licence, not the tag. The default is
  `google/siglip-base-patch16-224` — Apache-2.0, no out-of-scope clause, native in the
  pinned `transformers` so **no new dependency and no `trust_remote_code`**. SigLIP 2 is
  permissive too and was deferred on a correctness report, not a licence one
  (`huggingface/transformers` #43994).
- **Sigmoid, not softmax.** SigLIP is trained with a sigmoid loss, so each candidate is
  an independent probability. A softmax would make the verdict depend on how many terms
  the blocklist happens to contain.
- **Advisory by default.** The threshold is uncalibrated against real renders and a
  false positive that fails Phase 1 has no appeal, so the default is to flag for the
  human gate; `$DS_IP_IMAGE_ENFORCEMENT=enforce` refuses instead.
- **Screened before the image is written** (`ip_screen_image.save_screened`). The path a
  blueprint goes to is the *shared* `data/inputs/blueprint.png` — Phase 2's input and
  the fallback the artifact endpoints serve for any job — so a refused render saved "to
  look at later" becomes some other job's input.
- **Never imported by `server/app.py`.** `infra/docker/server.Dockerfile` installs no
  torch, transformers or numpy on a `python:3.10-slim` base; an import there takes the
  api-server image down at start-up. `tests/test_licensing_guards.py` holds that line.
  The heavy imports are inside `_load_model` for the same reason, and because
  `PYTORCH_ENABLE_MPS_FALLBACK=1` must be set before any `import torch`.
- Cost, in order of magnitude: one ViT-B/16 forward pass (~17 GFLOPs), text embeddings
  computed once and cached, ~800MB added to the pipeline image, **no per-call fee**. It
  runs before Phase 2, so every block avoids a EUR 0,32 generation.

**Tier 3 — the blueprint gate.** **Phase 2 does not start until a person has looked at
the blueprint.** Half the value is legal — an automated screen cannot be the last word
on resemblance, and this is the only recovery path for a Tier 2 false positive. The other
half is the product: the pipeline discards appearance and prints in one colour at a
0.4mm nozzle, so what arrives is a silhouette. Someone picturing something else should
find out from an image in thirty seconds rather than from a part four minutes and
EUR 0,32 later.

- **Derived state plus a `job_event`**, exactly like the dispatch gate:
  `server.blueprint_gate_state` returns `approved` / `rejected` / `awaiting_approval` /
  `not_ready`. No new outcome value and no migration — the outcome column says what the
  *software* did, and "a person has not decided yet" is a decision record.
- **Two subprocess invocations joined by a database row**, which is what makes the wait
  durable. `_run_pipeline` holds the `JobRequest` in memory only, so a gate that parked
  by awaiting would lose the job on a server restart. `--stop-after-phase N` creates the
  seam the docker strategies lacked (they run all five phases in one `docker compose
  run`); `print_job.request_params` carries the submitted request across, because
  `pipeline_type` and `mesh_seed` both change the geometry and exist nowhere else until
  Phase 2 has already run.
- **Gated exactly when Phase 1 runs in this invocation** (`gated = not skip_viz and not
  request.print`). That coupling is what terminates the loop: `_continue_pipeline`
  re-enters with `skip_visualizer=True`, so the continuation is not gated. `--print` opts
  out — the CLI and automation pass it and there is nobody to ask.
- **The continuation reads the snapshot, not the shared input.** This was wrong first
  time and it defeated the whole gate: `_pipeline_args` hardcoded
  `--blueprint /app/data/inputs/blueprint.png`, so between parking and approving, a
  second `POST /jobs` could delete that file and write its own render there — and the
  approved job would reconstruct *the other job's* image while the sidecar beside it
  stamped that job's seed, prompt and model onto this row. `JobRequest.blueprint_path`
  had been declared and forwarded nowhere since forever; it is now honoured, and the
  resumed request names `/app/data/outputs/{job_id}/blueprint.png`.
- **`awaiting_approval` requires a `blueprint_gate_parked` event and an unsettled
  outcome.** Deriving it from "a per-job blueprint exists" was wrong for the same class
  of reason: `pipeline.py` snapshots a blueprint into the per-job directory on *every*
  run with a `--job-id`, so an ungated run — anything with `SKIP_VISUALIZER` or
  `print: true` — reported itself as awaiting approval seconds in, the UI drew the gate
  over a pipeline already in Phase 2, and approving it started a **second** pipeline for
  the same job: two hosted reconstructions billed, two containers writing one output
  directory. A settled row is checked too, mirroring `dispatch_state`'s insistence on
  `outcome == "success"`.
- **A gated run that cannot park fails rather than continuing.** Falling through would
  let Phase 2 spend money on an image nobody approved, which is the one outcome the gate
  exists to prevent.
- **A rejection settles the row** as `cancelled`. `job_status_from_outcome` maps
  `unknown` to running, so a declined job left unknown would sit in the running list
  forever and `NewJob` would re-attach to it on every page load — the landing composer
  would become unreachable. For the same reason a *parked* job is excluded from
  `status=running`: it is waiting, not running, and it has its own filter.
- **`update_job_start_time` is first-write-wins.** A job can be launched more than once
  against one row — the gate resumes it, the dispatch gate runs the operator — and a
  later invocation overwriting `started_at` destroys the only record of when the job
  began, along with every duration computed from it. The continuation appends to the log
  rather than truncating it, for the same reason.
- **A directory holding only a blueprint snapshot does not claim the plain namespace.**
  `_job_outputs_dir` prefers an existing `data/outputs/{job_id}`, and the gate creates
  exactly that before Phase 2 runs — so a continuation that then substituted a fixture
  mesh would have written it into the real namespace, which is the one thing the `dev-`
  prefix exists to prevent.
- **The blueprint is snapshotted before parking** (`_snapshot_blueprint`). `POST /jobs`
  deletes the shared `data/inputs/blueprint.png` on every submission, so a parked job
  would otherwise have the image it is asking about destroyed by the next job — and
  `resolve_job_artifact`'s fallback is that same path, so the gate would show a
  *different* job's blueprint. That is also why `resolve_job_artifact` grew
  `per_job_only`. The provenance sidecar is copied with it, or the continuation's
  skip-visualizer path records NULL for seed, prompt and model.
- **The approval is bound to the image's hash.** The client sends the sha256 it
  displayed; a mismatch is a **409**, because approving an image you are no longer
  looking at is not approving. Approving twice is also 409 — two clicks must not buy two
  reconstructions.
- **A parked job keeps `outcome = "unknown"`.** Writing "success" would make
  `dispatch_state` report a job with no mesh and no G-code as ready to print.
  `GET /jobs?status=awaiting_blueprint_approval` is what makes the pending decision
  survive a page reload; an unknown filter is still a 400.
- `_append_phase_status` now writes the phase's *name* (`_PHASE_STATUS_NAMES`) rather
  than the number as a string, so a record appended by the server and one written by
  `pipeline._write_status` agree about what a phase is called. `operator` is kept for
  Phase 5, which `tests/test_dispatch_gate.py` pins.
- Gate banners use the printability form (`--- NAME ---`), never
  `=== PHASE n ===`, which the server's regex turns into a progress update.

### Printer Operators (pythonsrc/operators/)

Abstract base class `BasePrinterOperator` defines: `connect()`, `upload_file()`, `start_print()`, `cancel_print()`, `pause_print()`, `resume_print()`, `get_printer_state()`. Shared code (`pipeline.py`, `run_operator.py`) must call these with the base signature only — `OctoPrintOperator.upload_file` accepts an extra `start_print` kwarg that no other operator has, and passing it raises `TypeError` on Klipper and Bambu (`tests/test_operator_contract.py` guards this). `PrinterFactory` accepts `moonraker` as an alias for `klipper`, because the UI and config store persist the former while profiles use the latter. `PrinterFactory.create(firmware, base_url, api_key)` returns the appropriate implementation. Profiles at `pythonsrc/profiles/*.json` specify `firmware`, `base_url`, and optionally `api_key`.

### Docker Infrastructure

All images are pinned to `linux/amd64` (CuraEngine is only available as amd64 apt package). Phase Dockerfiles are layered on `base.Dockerfile`. The `pipeline-runner` image bundles all phases and mounts `pythonsrc/` as a volume for live development. Named volumes (`ds-models-flux`, etc.) persist model weights across rebuilds.

### Frontend (web/)

React 19 + Vite 8 + TypeScript 6. Dependencies: `react-router-dom` (routing), `recharts` (telemetry charts), `three` + `@types/three` (3D mesh viewer). Vite dev server proxies `/jobs` and `/health` to `localhost:8000`. Production build goes to `web/dist/` which is copied into the API server Docker image.

**There are two grounds now, and every colour is a token in both.** The palette is the
marketing site's — teal `#43a38d` on `#2f3030` — and `[data-theme='light']` is a complete
second sheet, not a filter. `theme.ts` owns the switch: an explicit stored choice always
wins, and `prefers-color-scheme` is followed only while nothing is stored, because someone
who has flipped the toggle must not be overruled at sunset. Three rules follow.

- **The ink ladder is named by role, not by alpha** (`--ink-strong` … `--ink-ghost`, plus
  `--ink-trace` below them). It was `--ink-80`/`--ink-58`/…; a name carrying a number is
  wrong in one of the two themes the moment the second one exists, because the light sheet
  expresses the ladder as *solid greys* rather than alphas. That is not a stylistic
  preference: faded ink separates from a dark ground as the alpha drops and converges on a
  light one, and the spec's light ladder measured **2.0:1** at the faint end — 51 elements
  below AA, the whole footer among them. Both ladders are now solved for contrast against
  the *stricter* of their two grounds (`--void` in light, `--ground` in dark, and they are
  opposite because the void is darker in one and lighter in the other).
- **`--accent` is a fill; `--accent-ink` is type.** #43a38d as text on the light ground is
  2.21:1. Anything that sets a colour on a glyph uses `--accent-ink`, which is the same hue
  walked down to 4.5:1 in light and nudged up to it in dark; borders, backgrounds and
  registration marks keep `--accent`. The design system's own guidance says this — use a deep
  ramp step for accent text, never the accent.
- **The bottom two ladder steps are the orientation tier and are deliberately below AA.**
  `--ink-faint` and `--ink-ghost` carry 10px uppercase tracked block labels ("PIPELINE",
  "05 PHASES") at ~3.3–3.6:1 and are meant to recede; pushing them to 4.5 collapses them into
  `--ink-mute` and flattens the hierarchy the whole board is built on. **Nothing that is a
  sentence may use them** — prose goes on `--ink-mute` or above. The honest fix for the
  residual is fewer 10px labels, not a flatter ramp.

**A drawn surface must be told when the ground moves.** Canvas and WebGL resolve colours
once, at the frame they draw, so `var(--ink)` cannot reach them. `theme.ts` exports
`onThemeChange`, `inkAt(alpha)` and `accentAt(alpha)` for that, and `hooks/useTheme.ts`
exposes the theme as React state for an effect dependency. `GCodeViewer` re-colours **in
place** via the preview's setters rather than rebuilding — a rebuild tears down the WebGL
context, re-downloads the G-code and snaps the camera back to the top — and `MeshViewer`
holds refs to its scene and material for the same reason.

Four layout rules are load-bearing enough to name, because breaking them is invisible in a
diff and obvious on screen:

- **`--gutter` and `--rail` are the page's symmetry lines** (`global.css`). Every full-width
  edge — nav, footer, `.sheet`, the split cells, the job header, the stage, the rail, the
  verdict banner, the dispatch gate — uses `var(--gutter)`, so the logo, the hero and the
  credits stand on one line. They previously ranged 40–56px per scene, which read as a wobble
  down the left side of the product. `--rail` is the one side-column width (was 380/400/400).
- **`.surface` is a flex column and page roots take `flex: 1`.** A page must own the height
  between the nav and the footer; `NewJob`'s split stopped at 620px, so its closing rule landed
  mid-page with a band of bare grid beneath it. The idle split spends the extra height *above*
  the composer (`.composeGroup { margin-top: auto }`) so the field and the printer plate sit on
  the same closing rule.
- **A framed field expresses focus once** (`.field-frame`). The frame *is* the input, so the
  textarea's own `:focus-visible` ring — 2px of accent, 2px inside the frame — is suppressed and
  the frame carries the state: accent at line strength, the ground opens, the registration marks
  close in. Two nested orange rectangles around the biggest object on the page read as an alarm.
- **Prompt fields do not resize and do not accept unbounded text.** `MAX_PROMPT_CHARS`
  (`components/promptLimits.ts`) caps both fields with a counter that only appears near the
  ceiling; `resize` is `none` and `PromptZoom` replaces the handle — the same text on a centred
  plate, page dimmed shallowly. A resize grip asks the writer to do layout, and its uncapped
  drag could push the submit button off screen.

The running view's stage follows the pipeline: it advances to the mesh when Phase 3 completes
and to the **toolpath as soon as the slice exists**, and the printability report is rendered
under the mesh stage (`PrintabilityCard` with `pending` for the window where the mesh is done
and the score is not). The G-code preview used to be duplicated in a 240px slot in the rail,
which is not where a 200-layer toolpath is read.

**`NewJob` shows one of two pages, and `jobId` decides which — so nothing may set it
without a way to unset it.** The running view was a one-way door: `setJobId(null)` was
called nowhere, so a tab that attached to a job could not reach the landing composer
again, and "New job" opens the inline composer *beside* the running job rather than
going back. `leaveJob` is the way back — it closes the socket, forgets the watched job
and leaves the job itself alone. The other half of the same bug was on the server:
`GET /jobs` answered an unrecognised `status` filter with the *unfiltered* list, newest
first, so a browser one deploy ahead of the server was handed a finished job by
`status=awaiting_dispatch` and dropped into the running view on every load. Unknown
filters are now a 400 (`JOB_LIST_STATUSES`), and the client checks the row it got back
rather than the fact that a row came back.

**A WebSocket closed while still `CONNECTING` is aborted, not closed** — the spec says
to fail the connection, so the browser resets the TCP socket mid-handshake and the Vite
proxy logs `ws proxy error: read ECONNRESET` twice. StrictMode discards the first socket
of every effect, so this fired on every dev page load and read like a dead backend.
`api/ws.ts`'s `closeSocket` waits for the upgrade before closing; use it instead of
`ws.close()` in effect cleanups.

## Configuration

System config (`.env` template at `.env.template`) is loaded by Docker Compose; `DS_DATABASE_URL` in it is the one required value. Runtime config (accessible via `/config` API) is stored encrypted in the telemetry database (`app_config` table, PostgreSQL on Supabase). The Fernet key file lives at `~/.ds-mvp/.config_key` (`$DS_CONFIG_KEY_PATH`), is gitignored and auto-generated on first use.

**The API is published on loopback, and one variable moves it.** `ports: -
"8000:8000"` offered an unauthenticated `POST /jobs` (EUR 0,32 a hosted
generation), `POST /jobs/{id}/print-dispatch` (heats a nozzle) and `PUT /config`
(rewrites printer credentials) to everything that could route to the host — the
LAN, a guest network, a shared VPN. The mapping is
`${DS_API_BIND:-127.0.0.1}:8000:8000` and `make start-native` passes the same
variable to uvicorn's `--host`, so the container and the native run agree and
neither is open by default; `load_native_env.sh` lifts it across because a `.env`
that opens the API deliberately must not be inert natively. **uvicorn's `--host
0.0.0.0` inside the container and in `server.Dockerfile` is not this setting and
must stay** — Docker publishes a port by connecting to the container's own
address, so a loopback bind in there makes the published port dead. The bind
address is one token whose deletion is invisible in a diff and total at runtime,
which is what `tests/test_api_bind_address.py` is for. This is a vector removed,
not authentication: there is still none, and `PUT /config` remains the hole
described under **Server** above.

Key pipeline paths: `data/inputs/{job_id}/` (blueprint and its provenance sidecar; runs without `--job-id` use flat `data/inputs/`), `data/outputs/{job_id}/` (per-job mesh, G-code and a blueprint snapshot — runs without `--job-id` still use flat `data/outputs/`), `data/logs/` (per-job logs and status files). Server artifact endpoints resolve the per-job path first and fall back to the flat layout for pre-existing rows. These are gitignored runtime directories.

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
  `$DS_BIREFNET_MODEL_ID` (`repo@sha`) before any untrusted deployment.
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

- **An extra can carry a licence the specifier does not mention.** `trimesh[all]`
  includes trimesh's own `test-more` extra, so `pipeline.Dockerfile` and
  `phase3.Dockerfile` installed **pymeshlab (GPL-3.0)** and **triangle (LGPL-3.0)** into
  production images from the day Phase 3 was written — a GPL extension module importable
  in the same interpreter, which is exactly what `pymeshfix`'s removal ruled out, reached
  by a route no manifest read would catch. Both images now use `trimesh[easy]`, which
  keeps the runtime extras (rtree, embreex, shapely) and drops the test and viewer sets.
  **Do not restore `[all]`**; `licence_policy.EXTRAS_THAT_PULL_COPYLEFT` and a guard over
  every install manifest hold the line. Note that `[easy]` does install `rtree`, so
  `printability`'s comment about it being absent describes the intent — measure by
  voxelising, do not depend on `rtree` — rather than the image.

**The dependency tree is committed, because the audit was reading the wrong list.**
`requirements-base.txt` and `web/package.json` name roughly a hundred packages; the
resolved tree is several thousand across four ecosystems, and **both components that
have broken this grant arrived transitively** — `pymeshfix` under something that looked
like a mesh utility, `briaai/RMBG-2.0` as another model's configured default. Neither
was in a manifest. `.github/workflows/licence-data.yml` therefore regenerates
`licenses/` on every merge and commits it: `pip-licenses` run **inside the built
images** (the requirements files are not what ships — `pipeline.Dockerfile` installs
`diffusers` from git HEAD and `server.Dockerfile` pins nothing at all),
`license-checker` over the web app's production tree, and `syft` SBOMs, which are the
only thing that can see `cura-engine` arriving as an AGPL-3.0 apt package.
`licenses/report.json` is the scored index — read it first.

- **The rules live in `pythonsrc/licence_policy.py`, not in the scanner.**
  `tests/test_licensing_guards.py` imports the same `FORBIDDEN_RENDERER_PACKAGES` and
  `AGPL_IN_PROCESS_PACKAGES`; a report with its own copy is a report that disagrees with
  the guards the first time either is edited. `classify()` reads a licence *string*
  (LGPL before GPL, or every LGPL package is a § 13 problem; `"or later"` is a version
  floor, not an SPDX choice) and `verdict()` adds the question the text turns on —
  `in_process`. Same name, opposite answers: `octoprint` as a pip distribution is a
  denial, `octoprint` in an image SBOM is the server we speak HTTP to.
- **A wheel in an image is in-process only when our code runs in that image.**
  `licence_report.py` overrides `python`-typed SBOM rows to in-process, which is right for
  `ds-mvp-pipeline`, `ds-api-server` and the registry images those are *built on* — a
  wheel in `python:3.10-slim` is one the api-server imports. It was wrong for the one
  scanned image that is a **peer service**: `octoprint/octoprint` holds OctoPrint's own
  AGPL plugins, and scoring them as linked made `licence-data` red on **every merge to
  `main`** with six standing denials against a tree nothing here imports — burying the one
  signal the gate exists to carry. `ARM_LENGTH_IMAGE_SBOMS` names the exception (keyed by
  SBOM stem, `base-` prefix ignored) and its flags aggregate under a `service` layer, the
  way the OS layer already did. Adding a name there is a licensing decision: justify it in
  `THIRD-PARTY-NOTICES.md` first.
- **Expected findings are recorded, not rediscovered.** `ARM_LENGTH_COMPONENTS` and
  `REVIEWED_WEAK_COPYLEFT` carry their reason, and OS-layer copyleft is aggregated into
  one row per image with a **count** — every Debian base carries dozens of GPL packages,
  and one row each means the same forty findings every week with the new one hidden among
  them. The count moving is the signal.
- **Missing data reads as `incomplete`, never `allow`.** CI cannot build the TRELLIS.2
  worker image (four CUDA extensions, compiled against a GPU architecture no runner has),
  so `licenses/python-worker.json` is produced by hand on a CUDA host — the command is in
  `licenses/README.md`. That is also the one tree where `nvdiffrast` would appear, so
  refresh it after touching `infra/docker/trellis2-worker.Dockerfile`.
- **`docs/audits/YYYY-MM-DD-licence.md` is how a recurring audit gets deltas** instead of
  re-deriving the same list weekly. The block between the `generated:` markers is
  rewritten from `report.json`; everything outside it is preserved, because judgement is
  the half no scanner produces. The `digest` fence excludes the timestamp and the commit,
  so an unchanged run is *visibly* unchanged.

**`ARCHITECTURE.md` is the phase-by-phase map** — model, pinned version, HF repo id,
hardware path, and the numbers that have actually been measured. It exists because the
alternative is inferring the stack from a requirements file, and it says `not measured`
rather than estimating, so an "expected gain" is never computed against an invented
baseline. `tests/test_licence_data.py` fails if a model declared in the code is missing
from that map.

When adding or bumping a dependency, check the package licence *and* any weights it downloads
at runtime, then update `THIRD-PARTY-NOTICES.md`.

## Important Constraints

- The `PYTORCH_ENABLE_MPS_FALLBACK=1` env var must be set **before** any `import torch` — this is why `pipeline.py` sets it at the very top before other imports. It is a Phase 1 concern only now; Phase 2 is CUDA-only and never runs on MPS.
- `Trellis2Backend.__init__` likewise sets `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` and `OPENCV_IO_ENABLE_OPENEXR=1` before the extensions load, matching upstream's own entry points
- `pythonsrc/config.py` is gitignored and must be created from `config.template.py` for native (non-Docker) runs
- `data/` directories including logs, inputs, outputs are all runtime-only and gitignored
- Phase 1 (FLUX) on Docker/CPU takes ~84 minutes; native macOS MPS is ~30 seconds — the MPS-native path is the primary dev workflow on Mac
- Docker images are `linux/amd64` only; on Apple Silicon, Docker Desktop emulates via Rosetta 2. The one exception is `trellis2-worker.Dockerfile`, which is built against a CUDA devel image and only runs on an NVIDIA host
- Phase 2 has **no CPU path at all**. On a machine without an NVIDIA GPU and without `$DS_SCULPTOR_REMOTE_URL`, `create_sculptor()` raises rather than falling back — there is nothing to fall back to, and a mesh from an unnamed model is worse than an error. Set up the worker (`services/trellis2_worker/README.md`) or use `--skip-sculptor --mesh <path>` to work on Phases 3–5