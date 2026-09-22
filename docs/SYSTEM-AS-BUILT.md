# ds-mvp — the system as built

The detail behind `CLAUDE.md`. That file is the contract an agent obeys before it
changes anything and it carries an index of the sections below; this file is the
reasoning, decision by decision, for the system as it stands. Read the section that
covers what you are touching.

Moved here verbatim from `CLAUDE.md` (issue #91), which the pipeline loads into every
turn of every run: a contract belongs in every turn, a 160 KB narrative belongs a
section at a time.

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
(`pythonsrc/organizer/spec.py`) and four archetypes — the deck box
(`archetypes/deck_box.py`), since 2026-09-10 the card divider
(`archetypes/card_divider.py`), since 2026-09-13 the token tray
(`archetypes/token_tray.py`, the first whose compartments hold something other than a
card stack) and since 2026-09-18 the box insert
(`archetypes/box_insert.py`, the first whose compartments are not all the same shape) —
entered through `pipeline.py --spec` —
see **Organizer — the parametric path** below. Phase 3 asserts a spec run's geometry
instead of repairing it and measures every designed feature back to ±0,05 mm, and
`POST /jobs` accepts a spec (2026-09-03), and **since 2026-09-11 a person can compose one
in the app**: the archetype strip opens a form-driven configurator that posts to
`POST /organizer/resolve` and submits `createJob({ spec })` — see **The composer's
parametric path** under Frontend. The dimension KB and LLM extraction do not exist yet; do
not treat generative-path tuning as roadmap work.

**The UI has been moved onto the pivot's vocabulary ahead of the engine** (2026-09-02). The
five phases now read **Composer · Compiler · Printability · Slicer · Operator** in the app,
`web/src/pipeline.ts` is the single source for those names and blurbs, and the composer
carries an archetype strip, a Fits Check and a spec panel. Phases 1–3 therefore *describe*
the parametric pipeline while the backend still runs FLUX → TRELLIS.2 → repair; the comment
at the top of `pipeline.ts` says so, and nothing in the telemetry columns changed
(`blueprint_model` and `generation_model` still record what actually ran). The panels
landed as **shells with explicit empty states**, never placeholder numbers: `organizer/spec.ts`
holds the types and `specFromJob` is the one seam, and `NO_SPEC_REASON` was the single
sentence every one of them showed meanwhile. A fits badge with no measurement behind it is
the exact failure the Fits Check exists to prevent, and a screenshot of one outlives any
caveat. The spec panel is now fed for real — by `specFromJob` for a running job (#66) and
by `POST /organizer/resolve` in the composer (#76) — and **the Fits Check is still a shell,
on purpose**: the only fit verdict in this system is Phase 3's measurement of the exported
mesh, so the composer shows `UNCOMPILED_SPEC_FIT_REASON` and no tick.

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
#
# Both CI jobs run on `ubuntu-24.04-arm` (issue #125). CI is the largest single consumer
# of the Actions allowance — 729 billed minutes of September 2026's 2 448, 29,8 % — and
# an arm64 standard runner is USD 0,005 a minute against 0,006, so the allowance buys
# ~17 % more of it. Every pinned requirement resolves on linux aarch64 (80 pure-Python,
# 28 `manylinux…_aarch64`, torch from PyTorch's CPU index), `postgres:17-alpine` is
# multi-arch, and the CuraEngine stand-in is a bash script. **The Docker images are
# unaffected and stay `linux/amd64`** — `ci.yml` builds none, and `licence-data.yml`,
# which does, stays on an x64 runner for that reason. The full reasoning, including what
# would justify moving back, is in `ci.yml`'s own header.

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

**None of this runs by default any more.** `POST /jobs` refuses a job that carries no
spec (`server.app._prompt_jobs_are_benched`), because the shipping path is the parametric
organizer and the generative path is benched. A spec job cannot reach a sculptor at all —
`_apply_spec_mode` sets `skip_sculptor` — so with the bench on, no server-initiated run
constructs one. The bench exists in code rather than in a decision because the fallthrough
above is the hazard: on a host with no NVIDIA GPU and `$PIXAZO_API_KEY` set, which is every
Apple Silicon development laptop, `auto` reaches the backend that bills, at €0,32 a
generation, under terms whose output-ownership clause is unresolved
(`docs/audits/2026-09-19-external-licence.md`). Setting `ALLOW_PROMPT_JOBS=true` in the
config store reopens it with no deploy. The **CLI is not benched**: `pipeline.py --prompt`
still resolves `auto` the same way, because there the backend is chosen by whoever typed
the command.

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

The pivot's engine: a **spec schema** and **four archetypes**, entered through
`pipeline.py --spec PATH`. *The LLM interprets words; it never produces
geometry* — and the spec is the boundary that rule describes. Everything left of it may
be probabilistic; everything right of it is deterministic, and the same spec compiles to
the same STL byte for byte (`tests/test_deck_box.py`, `tests/test_card_divider.py`,
`tests/test_token_tray.py` and `tests/test_box_insert.py` pin that).

- **`spec.py` is stdlib-only, on purpose.** Frozen dataclasses (`OrganizerSpec`,
  `Compartment`, `CardStack`, `Pocket`, `Lid`, `Divider`, `Tray`, `Insert`,
  `Constraints`, `Process`), millimetres
  rounded to 1 µm on construction so `from_dict(to_dict(s)) == s` holds exactly,
  `from_dict`
  refusing unknown keys, and one `SpecError` listing *every* problem with its dotted
  path. `canonical_json` / `spec_hash` / `spec_diff` make one spec one string, one
  hash, and two specs a path-by-path diff (F8). `pythonsrc.organizer` exports the schema
  and nothing else, so the api-server image — no trimesh, no manifold3d — can import it
  when the request model grows a spec field. Do not add pydantic here; it is not in the
  pipeline image.
- **A compartment holds a card stack *or* a pocket** (issue #84, 2026-09-13).
  `Compartment.contents` is a `CardStack | Pocket` union, and that is what made
  `compartments` plural in more than name: until the token tray, every archetype held
  exactly one card stack and the list had to be one long. A `CardStack` is resolved
  against `dimensions.py`; a `Pocket` is three typed millimetres plus a free-text
  `source`, because no token or dice size is sourced anywhere (below).
  **There is no `kind` discriminator**, deliberately: adding one means a new field on
  `CardStack`, which moves the canonical form and therefore the `spec_hash` of every
  deck box and divider ever stored. The two shapes are told apart by the keys they
  carry — `count` against `width_mm`/`depth_mm`/`height_mm` — and `_from_mapping`
  refuses a mapping that looks like both or like neither, **naming both shapes**,
  because guessing one for somebody who wrote something ambiguous builds the other part
  in silence. `isCardStack` in `web/src/organizer/spec.ts` is the same narrowing on the
  browser side.
- **An archetype's parameters are a *section* on the spec, and an absent section is
  omitted from the canonical form.** `Lid`, `Divider`, `Tray` and `Insert` are
  `Optional[...] = None` and named in `_OPTIONAL_SECTIONS`, which is what `to_dict` drops
  when they are None.
  `dataclasses.asdict` would have written `"divider":null` into every deck box spec ever
  stored — moving every one of their hashes for a field they do not mention, and moving
  them all again for the next archetype's section. `from_dict` defaults each to None, so
  the round trip is unaffected and the fixed hash vector in `tests/test_organizer_spec.py`
  did not move — and did not move again when `tray` joined them, or when `insert` did
  (issue #152), which is the property that tuple exists for and what
  `test_the_third_archetypes_section_moved_no_existing_hash` and its fourth-archetype twin
  pin. The fourth one is pinned harder, and deliberately: `EXAMPLE_SPEC_HASHES` carries
  the literal `spec_hash` of all three earlier archetypes' `example()`, **captured on
  `main` before `insert` was written**, because a new optional section is the *only*
  additive-safe change this schema has and nothing mechanical stops a well-meant scalar
  on `CardStack`, `Pocket`, `Process`, `Constraints` or `Tray` — which is written into
  every canonical form there has ever been.
  `RawSpec` in `web/src/api/client.ts` declares every section optional for
  the same reason. The alternative — a `SCHEMA_VERSION` bump — refuses every existing
  spec file for an additive field.
  The parameters live on the spec rather than as archetype constants because F8 iterates
  a design by spec *diff*: "make the tab wider" has to be `divider.tab_width_mm`, and
  "make it three across" has to be `tray.columns`. `Tray` carries **`columns` alone**:
  the rows are `len(compartments) // columns`, because stating both would let a spec
  name a grid its compartment list cannot fill, and the compartment list is the half
  that says what the tray holds.
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
- **`process.fit_intent` chooses the cavity clearance, because one number was
  serving two objects.** `snug` (the default, and today's 1,5 mm) is a box you
  close; `easy` is 4,0 mm — a tray you lift cards out of. Both ends are
  `docs/dimension-kb-research.md` §3's working convention (+1,5–2 / +4–6 mm), the
  low end of each band is taken, and `FIT_INTENT_CLEARANCE_MM` is the one place
  either number appears. **The clearance is resolved on construction, never at
  compile time**: an explicit `cavity_clearance_mm` wins, omitting it takes the
  intent's figure, and either way the canonical form carries the millimetres the
  geometry is built from — deriving it later, or remembering *how* it was arrived
  at, would let two specs with one canonical form compile to two meshes. An `easy`
  deck box compiles (a loose box is a valid request) and is refused only when those
  wider millimetres are what push it past a stated `max_external_mm`, with both
  remedies named; a `snug` overshoot stays a `fits_check` verdict rather than a
  refusal, because that is what every deck box here was built with and the UI can
  show it. This moved every spec hash a second time, for `fit_margin_mm`'s reasons;
  the *mesh* a stored spec compiles to did not move, and
  `tests/test_deck_box.py` pins the example's STL in bytes.
- **`process.wall_mm` has a floor the printer sets and a default the archetype
  chooses** (issue #72, 2026-09-11). It used to default to **2,8 mm** for everything,
  which is seven perimeters at a 0,4 mm nozzle and was sourced by nobody — defensible
  for a box you carry and drop, indefensible as one constant across archetypes, and
  roughly 2× the material and print time of the audited insert band (1,2–1,6 mm,
  roadmap §0.5) over a large part. It is now two separate decisions:
  - **The floor is the machine's.** `spec.wall_floor_mm(nozzle)` is
    `WALL_FLOOR_NOZZLE_MULTIPLE` (3) × the profile's `machine_nozzle_size` — 1,2 mm at
    0,4 mm, which is the audited band's bottom, and 1,8 mm at 0,6 mm, which a constant
    1,2 could never have said. It is deliberately *not*
    `printability.min_wall_mm` (two nozzle widths): that is what the extruder can
    physically lay down, this is what a wall that carries something is built from.
  - **The default is the archetype's.** `spec.ARCHETYPE_WALL_MM` names one per
    archetype and `archetypes/__init__.py` refuses to import if the registry has an
    entry it does not. The deck box's **2,4 mm** is `Lid.wall_mm` + `Lid.clearance_mm`
    + `Process.min_feature_mm` — the thinnest body wall that still leaves this
    archetype's own lift-off lid a valid lip, so a thinner default would be one
    `validate` refuses; `tests/test_deck_box.py` binds it to the three numbers it is
    derived from. The card divider's 1,2 mm builds nothing (its one thickness is
    `divider.thickness_mm`), so the module sets `USES_PROCESS_WALL_MM = False` and the
    floor skips it rather than refusing a good plate on a big nozzle over a field it
    ignores. The token tray's **1,6 mm** is the *top* of the audited 1,2–1,6 mm band —
    four perimeters at 0,4 mm, thinner than the deck box's as issue #72 asked, and not
    thinner still because the same number is the outer wall *and* every divider between
    two pockets, and a divider carries load from both sides.
  - **The wall is resolved on construction**, in `OrganizerSpec.__post_init__` because
    only the spec knows the archetype — `cavity_clearance_mm`'s rule verbatim, and for
    its reasons: the canonical form states the wall the geometry has. An explicit
    `null` means the same as omitted.
  - **The floor is checked in `archetypes.compile_spec`, which is Phase 2**, not in
    Phase 3's `_assert_spec_dimensions` where `pipeline.py` also holds the profile.
    Phase 3 runs after Phase 2 has written `compiled_mesh.stl`, `spec.json` and
    `compile_features.json` and recorded the archetype as the job's generation model,
    so a floor enforced there refuses a part the system has already produced and
    described — and the CLI, `fits_check` and the composer preview never reach Phase 3
    at all. `pipeline._profile_nozzle_mm` reads the nozzle through
    `ProcessProfile.from_printer_profile`, so `machine_nozzle_size` has one reader on
    the pipeline side and the same value reaches CuraEngine through the validated `-s`
    overrides. **A second reader remains**: `server/app.py`'s `_profile_snapshot` takes
    the key off the profile itself, for the nozzle it stores on the job record, and
    falls back to 0,4 silently rather than through the warning
    `ProcessProfile.from_printer_profile` logs. It is a known gap, left where it was
    because the server was outside issue #72's scope; the two agree on every bundled
    profile, and they can only disagree on a profile that omits the key.
  - This moved every spec hash a third time, for `fit_margin_mm`'s reasons, and moved
    the deck box's **mesh** for the first time. **A spec that states `wall_mm: 2.8`
    compiles to the byte it always did**, which `tests/test_deck_box.py` pins next to a
    new pin for the example at its own default.
- **The three edge treatments are shape primitives in `compiler.py`, not per-archetype
  habits** (issue #80). The audited insert standard (roadmap §0.5) calls three features
  mandatory and the engine had none of them: a 45° base chamfer against warping and
  first-layer curl, external vertical corner rounds against elephant-foot flare, and
  internal vertical rounds so small parts can be scooped out of a bin. None of it needs
  the deferred OCCT review — `ARCHITECTURE.md` § The geometry kernel has the 2026-09-05
  measurement — and all of it is two functions shared by every archetype:
  `rounded_rect_prism(w, d, h, r, chamfer_mm=…)` and `base_chamfer(section, h, c)`.
  - **`base_chamfer` takes an outline and builds the prism**, rather than taking a
    finished solid and cutting into it, and that is the load-bearing detail rather than
    an API preference. Every boolean formulation — intersect the solid against a 45°
    envelope, subtract the ring between them, union a frustum onto a trimmed body —
    leaves the kernel retriangulating a tangential seam where the 45° face runs into the
    vertical wall, and emits zero-area triangles along it whose corners coincide to
    within 10⁻¹⁰ mm. They are invisible in float64: the compiled plate is watertight,
    genus 0, `Error.NoError`. Then float32 merges those corners on export and the STL
    comes back with non-manifold edges and 45 loose bodies, which is a failed Phase 3
    for every spec run. Hulling the chamfer and the wall into existence together emits
    none. For the same reason the outline is the caller's `CrossSection` and never one
    recovered with `Manifold.slice` or `.project`: both rebuild it out of triangles and
    land ~4·10⁻¹⁰ mm² off, which is enough to reproduce the near-duplicates.
  - **Every chamfer face is exactly 45°, corners included.** Eroding a polygon moves each
    edge inward along its own normal, so an eroded chord is parallel to the chord it came
    from and `c` away horizontally and below — the plane through the pair is at 45° by
    construction. Three rings hulled build it whenever the erosion keeps every edge;
    when the chamfer outgrows the corner it runs around, the general construction cuts
    one 45° half-space per edge instead (exact at any height, ~70 ms a body against 4 ms,
    re-hulled because a chain of trims leaves the same degenerate triangles).
  - **Reading the mesh back needed a new measurer.** `plane_set` over a column of
    vertex coordinates counts every arc vertex as its own plane, so a rounded box states
    dozens of X planes where the design has six. `compiler.face_planes` reads *faces*
    instead: a face square to an axis is a wall, an arc chord is 5,625° off it and a
    chamfer facet 45°, and `archetypes/common.py`'s `expect_planes` goes through it. A
    corner radius is then a plane difference in all but name — a wall runs exactly
    between its tangent points, so the `Y = 0` wall's X extent is `[r, w − r]` and `r` is
    where it starts less where the design says the wall is. A chamfer is the Z extent of
    the faces that slope, with their angle checked rather than assumed.
  - **The deck box carries them by default** and its `ARCHETYPE_VERSION` went to **2**,
    the first bump that constant has had, because a spec stored before this compiles to a
    different mesh. `process.base_chamfer_mm` 0,6 mm, `process.corner_radius_mm` 1,0 mm
    and `process.cavity_corner_radius_mm` 0 — all three **design defaults, unsourced**,
    said so on the `to_view` row as the divider's tab rows are, because the audited
    document calls the features mandatory and names no millimetre for any of them. 0,6 mm
    is three 0,2 mm layers; 1,0 mm sits under the lip inset so the closure stays
    square-cornered; the internal round is 0 because a sleeved deck lifts out whole and
    the token tray is the archetype that will turn it up. The lip's and the lid cavity's
    radii are **derived** — `max(r − lip_inset, 0)` and `max(r − lid.wall_mm, 0)` — which
    puts all three arcs on the external corner's own centre and leaves exactly
    `lid.clearance_mm` around the corner as along the side. `validate` refuses a round
    wider than the wall it is cut from (`r − (r − w)·√2` at the corner otherwise), a
    chamfer at or above `floor_mm` or `lid.top_mm` (it would reach the cavity), and an
    internal round whose `ρ·(√2 − 1)` diagonal setback eats the contents' clearance.
  - **Zero is an identity in both primitives**, which is the whole compatibility claim:
    `r = 0` with no chamfer is `Manifold.cube` vertex for vertex and `c = 0` is the plain
    prism, so a spec stating all three at zero reproduces the pre-#80 STL byte for byte
    (`tests/test_deck_box.py` pins that hash next to the example's new one). Every spec
    hash moved a fourth time, for `fit_margin_mm`'s reasons; `RawSpec` declares the three
    fields optional and the UI shows no row when they are absent, because an absent field
    there means a v1 mesh with no such feature rather than today's default.
- **Each archetype refuses the others' sections, and the wrong contents, by name.**
  `deck_box` refuses a `divider` and a `tray`, `card_divider` a `lid` and a `tray`,
  `token_tray` a `lid` and a `divider`; and the two card archetypes refuse a `Pocket`
  compartment while the tray refuses a `CardStack` one, each naming the archetype that
  *does* build it. Ignoring a section prints a different part than the one asked for,
  silently, which is the same failure as ignoring an unsupported field — and reaching
  for `contents.count` on a pocket is an `AttributeError` three frames in rather than a
  refusal anyone can act on.
- **`archetypes/common.py` holds what is not about one shape.** The
  exactly-one-compartment rule (`single_compartment_problem`), the contents-union rule
  (`card_contents_problem`), the stray-section rule (`stray_section_problem`), the
  external-limit comparison (`external_overshoots`), the plane-count assertion
  (`expect_planes`, which reads faces since the edge treatments landed — see above) and
  the view-row builder (`view_row`), each taking its own wording as
  an argument so the sentence a person reads stays the archetype's. The contents-union
  and stray-section rules arrived with the third archetype, at the point where three
  near-identical sentences in three modules is how two of them end up saying different
  things. It was extracted when
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
- **`token_tray` is one open body with a regular grid of square pockets, and the first
  compartment type that is not a card stack** (issue #84, 2026-09-13). `external_w =
  Σ widths + (cols+1)·wall`, the same on the other axis, `external_h = height + floor`;
  one cube minus one cube per grid position, compartments laid out row-major from the
  minimum X/Y corner. One part, so the gate is told `expected_components=1`.
  - **The grid is regular by rule, not by convenience:** one `width_mm` per column, one
    `depth_mm` per row, one `height_mm` overall, refused per offending compartment with
    the column or row it disagrees with. That is what makes every pocket wall a plane
    *shared across the grid* and therefore measurable — a ragged layout would put a Y
    plane at the top of one pocket and nowhere else, and `measure` reads features off
    distinct axis-aligned planes, so it could not tell a designed edge from an artefact.
    That is the failure `card_divider`'s union produced and its extruded outline fixed.
    Ragged pockets and per-pocket heights belong to the box-insert archetype, which
    needs explicit positions anyway.
  - **No token or dice presets ship with it, and that is the decision rather than an
    omission.** `docs/dimension-kb-research.md` §4 sources die *sizes* (16 mm d6, 12 mm
    d6) and a +10–15 % rule for d20/d12 only; there is no punchboard token footprint and
    no d6 pocket clearance, and a 16 mm die in a 16 mm pocket is not a pocket. A preset
    would be one sourced number plus one invented one — exactly what `dimensions.py`
    refuses by carrying no token sizes at all. So every pocket is user-given
    millimetres, `Pocket.source` carries whatever provenance the person had, and
    `to_view` prints it on the row (or says "user-given mm" when there is none) rather
    than implying a measurement. Presets join when the KB does (M2).
  - **Square corners, said out loud.** Cubes and booleans only; rounds and chamfers are
    their own roadmap item (§0.3), and `to_view` carries a `note` saying so rather than
    letting a preview imply a radius the compiler does not build.
  - **An external overshoot is a verdict, not a refusal** — the opposite of
    `deck_box._easy_fit_problems`, and for its reason inverted: there, the clearance
    that pushed the box over is a number *nobody typed*; here every millimetre was
    typed, so the honest answer is "it does not fit, by this much, on this axis" and not
    a spec the composer cannot show.
- **`box_insert` is one enclosure holding several *differently shaped* fitted regions,
  and it is where PRD §1's composition claim becomes true of the code** (issue #152,
  2026-09-18). A card well, a token pocket and a dice well in one manifold body, compiled
  to fit the interior of a publisher's box. One part, so the gate is told
  `expected_components=1`. `insert.rows` groups the compartment list into rows; with
  `w = process.wall_mm` and `f = process.floor_mm`:

  ```
  row_depth[r] = max cd in row r        row_width[r] = Σ cw in row r + (n_r + 1)·w
  external_w   = max row_width[r]       external_d   = Σ row_depth + (rows + 1)·w
  external_h   = max ch + f             row_wall[r]  = w + (external_w − row_width[r])
                                                           / (n_r + 1)
  x[r][k] = (k + 1)·row_wall[r] + Σ earlier cw in the row
  y[r]    = (r + 1)·w + Σ earlier row_depth        z_floor = external_h − ch
  ```

  - **One archetype with a heterogeneous compartment list, not a container that nests the
    existing ones.** That was the open question, and three things settled it. A nested
    spec changes the *shape* of `compartments`, which is a schema change rather than a new
    optional section, so every stored `spec_hash` would move. Every archetype it could
    nest carries a section an insert has to refuse anyway (`lid`, `divider`, `tray`). And
    what an insert actually borrows is already shared — `resolve_stack`,
    `rounded_rect_prism`/`base_chamfer`, `external_overshoots`, `stray_section_problem`,
    `SweepCase`. What is genuinely new is *layout*, which no module had.
  - **No new content type.** Card stacks, token pockets and dice wells are `CardStack`
    and `Pocket`, which is what keeps every stored hash still: a die clearance is
    unsourced (see the token tray above), so a dice well is a typed pocket like any other.
  - **`insert.rows` is the whole layout grammar and nobody types a position.** Each entry
    is how many compartments that row holds, front to back; the compartments fill them in
    order; `box_insert.validate` refuses a `rows` whose entries do not sum to the
    compartment count. That is `Tray.columns`' rule in the other direction — there, one
    number and a list that must divide by it — and both exist so a spec cannot state a
    layout its compartment list fails to fill. Positions are derived because they are not
    a decision anybody makes: given the contents, the wall and the grouping there is
    exactly one rectangular layout, and a spec carrying `x_mm` could contradict its own
    contents. A compartment that **spans two rows** is not expressible and is not built.
  - **Slack in a narrower row is shared equally across that row's X walls.** The
    alternative was one thick end wall. Equal costs nothing — the shell stays rectangular,
    no millimetre anybody typed changes, and `row{r}_wall_mm` is one measurable number per
    row rather than a wall that is 1,6 mm here and 6,4 mm there. What it *does* mean is
    that `process.wall_mm` is the **minimum** wall rather than the exact one, which
    `to_view` says on the row it appears on and `ARCHETYPE_WALL_MM`'s comment repeats.
  - **Per-compartment depth is the floor rising, not the rim falling.** Each well is cut
    from its own `z_floor` through the top, so the part is one body with several floor
    planes and one rim. That is the feature `token_tray` deferred, and `floor_mm` is the
    floor under the **deepest** compartment — the only one that number names.
  - **A card stack lies flat**: footprint `(fw + cc) × (fh + cc)`, well depth
    `n·pitch + stack_slack_mm`. A sleeved card stands 92 mm and the interiors this fills
    run 70–75 mm (`docs/dimension-kb-research.md` §7; Wingspan at 72 mm), so on edge is
    the deck box's orientation and not an insert's. A v1 decision rather than a permanent
    one — and if an orientation flag is ever wanted it goes on the `insert` section,
    **never** on `CardStack`, where a field moves every stored hash.
  - **The interior is a limit, not a target.** `constraints.max_external_mm` is already
    documented as a box interior somebody measured and `fit_margin_mm` already comes off
    it; that machinery was written for this case and took no change. So the externals are
    derived from the contents and compared against the interior, never stretched to it.
    An overshoot is a verdict (the tray's rule) naming the axis, and — new here — the
    **undershoot** is printed on the fits line too: an insert 3 mm narrower than the box
    rattles, slides under the lid and tips its contents out. Filling to the interior, and
    the locking tabs that are the other answer to it (#153), are not built. The
    undershoot is measured against the *effective* limit, or two millimetres of
    deliberate clearance would read as a fault on every part that fits perfectly.
  - **The shell is rounded and chamfered; the wells are square.**
    `process.corner_radius_mm` and `process.base_chamfer_mm` go through
    `rounded_rect_prism` as the deck box's do — the audited standard calls both mandatory
    and an insert is the part it is about — with the deck box's two refusals restated: a
    round larger than the wall it is cut from, a chamfer at or above the floor.
    `process.cavity_corner_radius_mm` is read by nobody here and `to_view`'s `note` says
    so.
- **Archetype rules live in the archetype.** A lip thinner than `min_feature_mm`, a
  second compartment, magnets, a lid taller than the cavity — `deck_box.validate`
  refuses each with the remedy named. A tab as wide as its plate, a missing `divider`
  section, a sub-`min_feature_mm` tab — `card_divider.validate` likewise. A missing
  `tray` section, a column count that does not divide the compartments, an irregular
  grid, a sub-`min_feature_mm` pocket, wall or floor — `token_tray.validate`. A missing
  `insert` section, row counts that do not sum to the compartment list, a
  sub-`min_feature_mm` compartment, wall or floor, a corner round wider than the wall, a
  chamfer that reaches the floor — `box_insert.validate`. Ignoring an
  unsupported field prints a different box than the one asked for, silently.
- **Every designed feature is measured back off the mesh** (`deck_box.measure`, the
  shape of text-to-cad's measure/align checkers): the plate is split into body and lid,
  their distinct axis-aligned planes are read, and each feature is a difference of
  planes. It runs on the compiled mesh *and on Phase 3's output*, which is what makes the
  ±0.05 mm assertion honest — it measures what the slicer receives. A plane count that
  does not match the design is itself the finding (`MeasureError`).
- **What a spec promises to measure may be a function of the spec** (issue #84). A
  module may expose `measured_features(spec)`, and `archetypes.required_measurements`
  prefers it over the fixed `MEASURED_FEATURES` tuple; the token tray is the first and
  only one, because its feature list grows with its grid — 30 names for a 2 × 3 tray, 37
  for a 4 × 2, one width/depth/height per position and one thickness per wall including
  the outer ones (`5 + 3·rows·columns + (columns + 1) + (rows + 1)`, which is why the
  two grids do not agree despite holding six and eight pockets in the same two shapes). A fixed tuple could only ever have promised the five that do not move
  (the three externals, the wall, the floor), which means a report saying *within
  tolerance* with every pocket in the grid unchecked; a divider shifted 0,5 mm leaves
  every external exactly right, and `test_a_single_pocket_out_of_position_is_caught_by_name`
  is that case. For the tray, `measure(mesh)` still takes no spec: its grid is read off
  the plane counts (`2n + 2` per axis, exactly three on Z), which is what lets it refuse a
  mesh that is not a tray instead of quietly measuring one. `MEASURED_FEATURES` stays
  required of every module and is the fallback.
- **A ragged layout cannot be read off a plane count at all, so the box insert measures
  region by region** (issue #152). `token_tray`'s docstring says why in advance: a
  compartment shallower or narrower than its neighbour "would put a Y plane at the top of
  one pocket and nowhere else", and a global read cannot tell a designed edge from an
  artefact. `compiler.face_planes_within` is the answer — `face_planes` restricted to the
  triangles whose centroid lies inside an axis-aligned box — and the split of
  responsibility is the whole of what keeps it a measurement: **the design supplies the
  region, the mesh supplies the numbers.** Each compartment contributes five features read
  inside its own region: `c{i}_width_mm`, `c{i}_depth_mm`, `c{i}_height_mm` and
  **`c{i}_x_mm`, `c{i}_y_mm`**. The positions are features because in a ragged layout
  nothing else catches a right-sized well built in the wrong place — a regular grid's
  plane count moves when a divider does and a ragged one's does not
  (`test_a_compartment_out_of_position_is_caught_by_name`).
  Three details are load-bearing:
  - The region reaches past the well by `0,4 ×` the thinnest wall, floor or well depth
    (`MEASURE_MARGIN_FRACTION`). Under 1 whole wall, or it would swallow a neighbour's
    face and report a plane count the design does not have; comfortably over the ±0,05 mm
    claim, or a wall displaced by less than the claim allows would be reported as
    *missing* rather than as *out of tolerance* — a true finding, but the wrong one.
  - The Z span stops a margin *below* the rim, because the rim overhangs into every
    compartment's region and a read that sometimes caught it would make the plane count
    depend on how the kernel triangulated an annulus.
  - The region is anchored to **the part's own minimum corner, read off the mesh**, not
    to the design's zero. Every other archetype measures differences of planes and is
    translation-invariant for free; a region is absolute and is not, and Phase 3's assert
    path XY-centres the plate it is handed. This was a real bug, caught by
    `test_phase_3_asserts_an_insert_and_hands_the_slicer_the_designed_dimensions`, and it
    holds only for as long as Phase 3 translates without rotating or scaling — the same
    contract the annotated preview's frame reconciliation rests on.

  Because that needs the spec, the registry grew a second optional hook beside
  `measured_features`: a module may declare **`MEASURE_NEEDS_SPEC = True`** and
  `archetypes.measure_spec_mesh` then calls `measure(mesh, spec)`. Additive — the other
  three keep `measure(mesh)` — and declared on the module rather than sniffed off the
  signature, because "this measurer needs the design" is a claim a reviewer should see in
  the diff. `verify_spec_mesh`, the CLI and Phase 3 all route through the dispatch and
  took no change.
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
  verdict so a failure is inspectable; one `[DS] Dimensions: 26/26 …` line and a `✗` per
  miss are printed; the report rides on the row as `repair_report["dimension_check"]`
  (the `achieved_extent_mm` precedent — no new column); and a miss is a `MeasureError`,
  which is a failed Phase 3. A spec run that ships a wrong dimension has failed, however
  watertight it is. **The feature set compared is `required_measurements(spec)`**, so a
  tray is checked at every grid position rather than at the five names that do not move.
  `tests/test_organizer_dimensional_accuracy.py` sweeps **every registered archetype**
  over the envelope its own module declares (issue #85): one `parametrize`, 979 specs —
  495 deck boxes (counts × sleevings × walls × clearances × lid engagement), 324
  dividers (sleevings × tab positions × thicknesses × tab sizes), 160 trays (grids ×
  pocket sizes × walls × floors) — on the exported, reloaded STL, plus a 90-case corner
  subset through the assert path. It runs as its own CI step and ends with one line per
  archetype (`deck_box: 495/495`).
- **The envelope is declared by the archetype, not by the test**
  (`envelope() -> tuple[SweepCase, ...]` in each module, dispatched through
  `archetypes.envelope_for`). The sweep was written for the deck box and then *copied*
  per archetype, which is a shape that fails silently: a fourth archetype could be
  registered, compiled, offered in the composer and printed while no mesh it produced
  had ever been measured, and the run would be green. `envelope_for` therefore raises
  for a module that declares none, `envelope` is on the archetype API
  `tests/test_archetype_registry.py` enforces, and the per-archetype summary line makes
  a missing archetype visible as a missing line rather than as an unchanged total.
  Being swept is what makes an archetype an archetype rather than a mesh generator.
  Each case also passes `Engineer.assert_manifold` — the production check, not a
  restatement — so watertightness, non-manifold edges and kernel acceptance are asserted
  on the float32 round trip for every spec, and the measured feature set is compared
  `==` to `required_measurements(spec)` rather than `⊆`, because a report that silently
  checked five of a tray's thirty features would say *within tolerance* and mean almost
  nothing. What stays per-archetype is the corner each contributes alone: the deck box's
  nozzle-derived wall floor (below it nothing compiles, so the coverage is a refusal
  rather than a measurement), its fit intent, and its edge treatments — 48 cases from
  absent to the ceiling of every rule, plus 12 through the assert path, rather than
  three more axes on 495, because they change the *kind* of surface rather than a length.
- **The compiler is the generation model.** `generation_model = "organizer/deck_box"`,
  `"organizer/card_divider"` or `"organizer/token_tray"`,
  `generation_model_version` = the archetype's own version — `"2"` for a deck box since
  the edge treatments landed, `"1"` for a divider and for a tray — `generation_backend =
  "local"`, the spec hash and features in `generation_params`. No new column — this is
  exactly what those columns
  record. `blueprint_*` stay NULL, correctly. `size_source="spec"` is written by
  `POST /jobs` when the request carries a spec (below).
- **The gate is told the part count**, read off `len(compile_result.parts)` so no
  archetype knowledge lives in `pipeline.py`. `evaluate_printability(expected_components=)`:
  a body and a lid are two grounded bodies as designed, and used to score every deck
  box "risky" for a possible unintended split; a divider and a tray are one. A mismatch
  still warns;
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
  `compile_features.json`, `dimension_report.json` and `view.json`.
- **`view.json` is the annotated preview's document, and Phase 2 writes it** (issue
  #88). `_compile_spec_phase` writes it from `archetypes.view_for` beside
  `compile_features.json`, because that is the only place in the system holding the
  spec, the kernel and the `CompileResult` at once — the api-server image carries no
  geometry kernel, so a view derived on demand is a view that cannot be derived. It is
  also what "a spec diff re-annotates without re-measuring" means: every millimetre on
  it is a *designed* feature, and changing the spec is the only thing that moves one.
  Two keys beyond the composer's table:
  - `frame` — `units`, `up` and the compiled plate's own `bounds_mm`.
  - `callouts` — one dimension line each, from `common.callout`. `feature` **must** be
    a name in `required_measurements(spec)`, which is the anti-fabrication contract in
    one rule: a callout naming an unmeasured feature would put a number on screen the
    dimension report has no verdict for. `value_mm` is `result.features[feature]`
    verbatim, never re-derived; `from`/`to` are axis-aligned and exactly `value_mm`
    apart, on planes `measure()` reads that feature off (`callout` refuses a line whose
    length disagrees with its label, and `tests/test_view_callouts.py` sweeps both);
    `offset` is the free space beside the line, across it rather than along it; `tier`
    is 1 for the internals a phone shows and 2 for the externals it drops.
  - **The frame is reconciled, not assumed.** The viewer compares the served mesh's
    extents with `frame.bounds_mm` at ±0,05 mm per axis and translates the callouts by
    the difference. That holds because Phase 3's assert path *translates only* —
    `orient_for_print` XY-centres and sits the part on Z = 0, and `--target-mm` is
    refused in assert mode — and `tests/test_pipeline_spec.py` asserts it rather than
    remembering it. A mismatch draws **no** callouts: a stale artifact or a rescaled
    mesh must cost the annotations, not their honesty.
  - The deck box carries all twelve; the divider and the tray carry a deliberately
    small set, and the tray annotates the **first pocket only** — a regular grid would
    otherwise put 24 lines on a 66 mm part, which is a picture nobody can read.
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
  day the compiler does, which is what `Token tray` did in issue #84 and `Box insert` in
  issue #152 — the rule those three dead cells were removed to establish, honoured twice
  now rather than merely stated. That test also asserts every registry module exposes the whole
  archetype API, which is what "adding an archetype is a module and a line" means.
- **Not built, and where it is:** ragged *grids* inside a token tray (the insert is the
  archetype that lays out a ragged layout; the tray stays regular so its plane count can
  be its grid), an insert that **fills** the interior rather than fitting inside it and
  the locking tabs that are the other answer to a rattling one (#153), cards **on edge**
  in an insert (a later flag on the `insert` section, never on `CardStack`), a compartment
  that **spans two rows**, rounded well corners and finger cutouts (their own issues; both
  the tray and the insert say so in `to_view`), the game-box interior KB (#154 — the
  interior is typed today), the stackable enclosure (#155 — the same compiler with the
  constraint inverted, which is why `box_insert.derive` is a pure function of the
  contents), token and dice presets in the dimension KB (M2 — §"No token or dice
  presets" above is why none ship now), and LLM extraction (M2).
  `python -m pythonsrc.organizer example|compile|measure [--report]` is the
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

### Game-box dimension KB (pythonsrc/organizer/box_kb.py, pythonsrc/data/game_boxes.v1.json)

The "Interior-First" input the board-gamer segment is founded on (issue #154, roadmap
§0.5): **an insert compiled against a box nobody measured is the failure mode the whole
practice is about.** `Constraints.max_external_mm` was documented from the start as *a
number somebody measured off one copy of a box*, and until this existed that number could
only be typed. The KB is where a curated one comes from.

- **It is curation, and there is no BoardGameGeek client.** BGG carries **external** box
  dimensions only, user-entered, in inches, and its API is registration-gated under a
  commercial licence (`docs/dimension-kb-research.md` §7). A BGG *forum thread* in which
  somebody reports measuring their own copy is a citation like any other and the launch
  set uses one; the API is not touched, here or anywhere in the tree, and
  `tests/test_game_box_kb.py` asserts both halves — no HTTP client in `box_kb`'s import
  graph, and no API endpoint or fetch-beside-the-hostname anywhere in the repository.
- **Provenance is per value.** Each of the three interior axes is its own `Measurement`
  with its own `basis` (`spec` | `measured` | `derived`), `source`, `captured_on` and the
  `units` it was captured in. A box whose width came off a caliper and whose height came
  off a product page is two different claims, and one `source` string on the entry would
  flatten them into one — the shape `Pocket.source` established (issue #84's finding).
  **A blank or missing source is a `BoxKBError` at import**, so the file cannot acquire an
  unsourced row by inattention. `folk` — the research document's word for a rule of thumb
  — is not an accepted basis: a rule of thumb about box walls is not a measurement of a
  box. A `derived` value must carry a `note`, because the issue's constraint is that you
  do not infer an interior from an exterior *without saying so in the data*.
- **The number in the file is the number the source stated.** An inch source is stored in
  inches and `Measurement.value_mm` converts, because a file holding 285,75 mm where the
  source says 11¼ inches cannot be diffed against the page it came from.
- **The launch set is three, and that is the point.** Small and defensible beats broad
  and unsourced: every number is transcribed from a row of `docs/dimension-kb-research.md`
  that already names where it came from — Wingspan's interior off a BGG measurement
  thread (§7), and the two commercial card cases of §3, the Ultimate Guard Boulder 100+
  and the DeckSmith Commander box. The rows **refused** are recorded in the data file's
  own comment so they are not rediscovered as omissions: the Printables 245516 listing
  §8 says to re-verify manually before shipping (Cloudflare-gated at research time, and
  nobody has), and every BGG box-dimension row, which is external and in inches.
- **The version is bound to the numbers under it.** `version` in the file is the *content*
  version (the `.v1` in the filename is the schema's); `BoxKB.content_sha256()` is a
  digest of the entries without it, and `tests/test_game_box_kb.py` pins the two together.
  Editing a measurement in place without bumping the version fails the suite — the
  `tests/test_supabase_migration.py` idiom — because a spec recording `box.kb_version`
  would otherwise name a version whose numbers are not the ones it was built from.

**`spec.box` is how a spec names one**, and it is a new *optional section* because that
is the only additive-safe change this schema has (see `_OPTIONAL_SECTIONS`): no stored
`spec_hash` moved. It is the first such section that is not an archetype's — `box` is
archetype-agnostic, a deck box built to stand inside a commercial card case being the
same claim as an insert built to fill a publisher's box, and all four archetypes accept
one.

- **The interior is resolved on construction, never at compile time.**
  `OrganizerSpec.__post_init__` fills `constraints.max_external_mm` from the entry, in
  exactly the way `Process` resolves `cavity_clearance_mm` and `wall_mm`, so the canonical
  form always states the millimetres the geometry is built from and
  `from_dict(to_dict(s))` compiles to the same mesh as `s`. A KB correction therefore
  never silently reinterprets a stored design: it produces a different spec with a
  different hash, which is a visible outcome.
- **The KB is consulted only to fill what is absent, and only ever agrees with what is
  present.** A stated limit beside a named entry must equal it to the micron or the spec
  is refused naming both — silently preferring either would print a part nobody asked
  for. A spec naming an entry or a KB version *this build does not carry* still **loads**,
  with its own millimetres: it is the record of a job that ran, and a schema that refused
  it would take the job page down the day the KB moved. Such a spec with no stated limit
  is the one case refused, because there is then nothing to build to.
- **`fit_margin_mm` comes off a curated interior exactly as off a typed one.** A curated
  number is still one copy of one box measured once, and boxes flare ±1–2 mm between
  copies of the same title. The KB buys provenance, not permission to skip the margin —
  and the reading that quietly zeroes it for "measured" entries is the one that splits
  cardboard at the corners, which is the audited document's named catastrophic failure.

**What a compiled part records.** `archetypes.compile_spec` puts `game_box_record(spec)`
on the `CompileResult`, so `features_document()` — `compile_features.json`, and
`generation_params` on the telemetry row — carries the entry id, the KB version, the
interior and the three provenance sentences. It is **absent** rather than null for a part
built to typed millimetres, which keeps every document written before the KB existed
byte-identical and stops a key implying a curated source appearing on a part that has
none. `GET /jobs/{id}` serves it from `generation_params` rather than re-resolving it, so
a later correction cannot rewrite the provenance of a finished part.

**The degraded mode is the mode this schema shipped with, and it is not a lesser state.**
Three curated boxes will never be every box that exists, so a game the KB does not carry
is the ordinary case: the composer's picker opens on *"A box nobody has measured — I'll
type the interior"*, the three millimetre fields appear, and `fit_margin_mm` comes off
them. `GET /organizer/boxes` is **fetched** rather than compiled into the client — unlike
the archetype strip and the five closed vocabularies, which are the schema's own literals
— because this is data that grows one measurement at a time, and a failed fetch degrades
to precisely that typed path.

**And the UI says which of the two it used.** `interiorNote` in
`web/src/organizer/spec.ts` is the one place the distinction is drawn, and it is drawn
**per axis**: a curated row carries the entry's own provenance sentence for that axis, a
typed row says *typed interior — no source behind this number*, and a spec naming a KB
version this build cannot resolve says so instead of claiming a source it does not have.
Two numbers that look identical in a table and are not the same kind of claim is exactly
the habit the Fits Check exists to break; a KB whose screen cannot tell them apart would
be worth nothing.

### Server (server/app.py)

FastAPI application with:
- **Authentication: one shared secret on every route but `GET /health` and the SPA**
  (`server/auth.py`). There was none at all, and the routes that answered anything
  reaching the port included the ones that spend money (`POST /jobs`, EUR 0,32 a
  hosted generation), move hardware (`POST /jobs/{id}/print-dispatch`) and stand in
  for a person (`POST /jobs/{id}/blueprint-approval`, the Tier 3 IP gate). A loopback
  bind shrank the exposure to every process on the machine; it never made the server
  safe to publish.

  `DS_API_TOKEN`, or `~/.ds-mvp/.api_token` — generated `0600` on first start, beside
  the config store's Fernet key and therefore inside the `~/.ds-mvp` mount both
  containers already have, so a native run and a compose run resolve the same secret
  without anyone copying it (`pythonsrc/api_token.py`). Only the server may generate
  one: a caller that invented its own would authenticate against a server that had
  never seen it, and would report a missing token as a wrong one.

  Five decisions worth keeping:

  - **A header, not a cookie.** A cookie rides along on a cross-site request whether
    the person meant it or not, and several routes take no body at all
    (`POST /jobs/{id}/outcome/prompt-shown`, `DELETE /jobs/{id}`) — so a `<form>` on
    any page in the browser would have authenticated as the operator. A bearer header
    cannot be sent cross-origin without a preflight, and the preflight fails because
    there is deliberately no CORS middleware. `hmac.compare_digest`; the 401 carries
    `WWW-Authenticate: Bearer`.
  - **Exempt by marker, not by list.** `@public` on the endpoint is what exempts it,
    and the middleware reads that off the route it matched — a walk to the first
    `Match.FULL`, and only for a GET, so nothing that writes is ever exempt. A list of
    paths would go stale the moment someone added a route, and it would go stale in
    the direction that leaves a route open. Two endpoints wear it: `GET /health`,
    polled by things that hold no credential, and the SPA catch-all, which serves the
    bundle a person needs *in order to* type the token — safe only because
    `contained_path` is what decides which files it will serve.
    `tests/test_api_auth.py` asserts the marked set and builds its 401 matrix from the
    router, so a new route is covered on the day it is added.
  - **Inside the request log, not outside it.** Starlette builds the stack
    inner-first, so the middleware is installed *before* `log_requests` and runs
    inside it. A 401 is exactly the line an operator needs in the log and the activity
    feed; rejecting outside the logger would make an attack the one thing that leaves
    no trace.
  - **The WebSocket takes `?token=`, refused before `accept()`.** A browser cannot put
    a header on `new WebSocket(...)`. The alternative — accept, then ask in the first
    message — leaves unauthenticated sockets open until something times them out and
    puts the check in every handler. The denial is a real HTTP 401 through ASGI's
    `websocket.http.response` extension, with a close (1008) where the server does not
    offer it. The token in a URL is survivable here only because uvicorn's access log
    is off and `log_requests` records the path alone; a test pins that nothing logs
    the query.
  - **Not a config-store key, deliberately.** `PUT /config` must not be able to rotate
    the credential that protects `PUT /config` — one bad write would lock every client
    out with no way back in through the API.

  The SPA keeps the token in `localStorage` and shows a paste-once gate without one
  (`web/src/api/auth.ts`, `components/TokenGate.tsx`); `api/http.ts` is the only place
  that attaches it, with three wrappers because a browser attaches credentials to none
  of these by itself — `apiFetch`, `withToken` for the upgrade, and
  `authedObjectUrl`/`downloadAuthed` for the `<img src>` and download anchors the
  browser requests itself. Injecting the token into `index.html` for a loopback caller
  was refused: it hands the secret to every process on the machine through the one
  route that is exempt *because* it is safe to be public, and it cannot work for a
  hosted client, which is never loopback.

  The pipeline container and the dispatch operator are handed it by `subprocess_env`
  — `docker compose run -e DS_API_TOKEN` **by name**, so it never reaches an argv that
  `ps` can read — because their collectors relay through
  `POST /jobs/{id}/internal-telemetry`, which anyone could previously have used to
  inject invented samples into a live job and into the dataset.

  What this is not: there is no per-user model (magic-link accounts are Phase 5), no
  CORS, no TLS and no `TrustedHostMiddleware`. Revocation is rotation for everybody.
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
  submitters reach a preview" (PRD §7, roadmap §6A) had a denominator all along — a job row
  is one submission, which is why the key is `jobs_submitted` and not `prompts_submitted`
  (a spec job carries no typed prompt at all; see **The prompt of a spec job** below) — and nothing
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
- **`POST /jobs/{id}/photo` is the first route that accepts bytes from a browser**, and
  it is what makes "does it fit?" answerable with something other than one word. Every
  other write this server takes is a short JSON body pydantic validates; this one is an
  arbitrary stream landing on the disk that also holds the config store's neighbours, so
  four properties are stated as data in `server/app.py` and each has a test in
  `tests/test_fit_photo_api.py`.
  - **Authenticated by writing nothing.** No `@public`, no third entry in
    `EXPECTED_PUBLIC_PATHS`. `tests/test_api_auth.py` builds its 401 matrix from the
    router, so both the POST and the GET were covered the day they existed.
  - **Capped twice.** `FIT_PHOTO_MAX_BYTES` is 10 MiB — a 12 MP phone JPEG is 3–6 MB and
    an HDR one passes 8, so 5 would refuse photographs people actually take. A declared
    `Content-Length` over it is a 413 before the body is transferred; the stream is then
    **counted again as it is consumed**, because a chunked body declares no length at all
    and uvicorn caps nothing. The second check is the one that bounds the disk, which is
    why the test sends an iterator rather than a buffer. The SPA checks the same figure
    before uploading; that check is a courtesy, the server's is the rule.
  - **Type-checked against the bytes, not the header.** `image/jpeg`, `image/png`,
    `image/webp`, and the magic prefix must agree with what the caller claimed
    (`sniff_image_type`) — otherwise a 415 naming the three. A prefix check rather than a
    decode: the api-server image has no imaging library, and handing untrusted bytes to
    one is the decompression-bomb path. It is not a validity proof — a JPEG header over
    garbage is stored — and nothing but a browser ever consumes the result. HEIC is
    refused: iOS transcodes a file-input upload to JPEG, and the residue that still
    arrives as `image/heic` cannot be rendered by two of the three desktop browsers, so
    accepting it would store evidence nobody could look at.
  - **Contained, and the server names the file.** The target is
    `data/outputs/{job_id}/fit_photo.{jpg|png|webp}` — the per-job output directory the
    api-server already has bind-mounted — joined by `fit_photo_target` through
    `contained_path`, with the suffix coming from `FIT_PHOTO_TYPES` and never from the
    client. A filename from a browser is request-controlled data and is not accepted at
    all. The row is looked up **before a byte is read**, so `/jobs/%2e%2e/photo` is a 404
    that never reaches the join. The write is staged beside the target and `os.replace`d
    into place, and a re-upload deletes a predecessor stored under a different suffix:
    one part, one picture.

  The body is the image itself rather than a multipart form. `infra/docker/server.Dockerfile`
  installs a hand-written package list **without `python-multipart`** — it is in
  `requirements-base.txt` for the GPU worker's `/sculpt` alone — and FastAPI raises at
  *import* when a route declares an `UploadFile` with no multipart parser available. A
  multipart route would therefore pass CI, where the requirements file installs it, and
  take the api-server image down in production. A raw body needs no dependency, no SBOM
  entry and no Dockerfile change.

  `GET /jobs/{id}/photo` serves it back inline, with the media type its stored suffix
  implies. It reads the row's own path and puts it through `contained_path` again —
  a value in a database is data too — and deliberately does **not** use
  `resolve_job_artifact`: that function's flat-layout and `dev-` fallbacks exist so an
  old job's G-code can still be found, and applied to a photo they would answer one job's
  request with another job's evidence. `GET /jobs/{id}` carries `has_fit_photo`, a
  boolean rather than the path, because a server-side location is not something the
  client has any use for; `/provenance` carries the path itself, for the dataset.
- **`POST /organizer/resolve` is the composer's arithmetic, and it is here because the
  dimension KB is here.** Spec in; the canonical spec, its hash, the resolved card stack
  per compartment (`dimensions.resolve_stack` — footprint, pitch, height and the `basis`
  sentence naming every source) and every `SpecError` problem with its dotted path, out.
  Nothing in the browser computes a millimetre: a stack height is a function of a table of
  sourced figures, and a second copy of that table in TypeScript drifts from the one the
  geometry is built from, which is the same failure as a fits badge with nothing behind it.
  It runs in the api-server image because `pythonsrc.organizer` and
  `pythonsrc.organizer.dimensions` import nothing outside the stdlib — the two are the
  *only* organizer imports `server/app.py` has, and `tests/test_organizer_resolve_endpoint.py`
  asserts that rather than trusting it.
  Three properties are deliberate. **It answers `schema_valid`, not `valid`**: only
  `OrganizerSpec.from_dict` ran, and the archetype's own rules — a deck box needs a lid
  section, a lip may not be thinner than `process.min_feature_mm` — import the kernel and
  are enforced when Phase 2 compiles, so a field called `valid` would claim a check nobody
  made. **It returns no fit verdict**, for the same reason and one more: `deck_box.fits_check`
  needs `manifold3d`, and the only verdict this product shows is a measurement of an
  exported mesh. **A spec the schema refuses is still a 200** — it is called on every
  keystroke, it reads nothing, writes nothing and starts nothing, and answering a
  half-composed spec with a 4xx would make typing an error in the log and in the activity
  feed. `POST /jobs` is where a bad spec is refused, and it still is.
- **A refused spec arrives as data, not only as prose.** `JobRequest._spec_is_valid` raises
  a `PydanticCustomError` whose context survives into the 422 body, so the detail entry
  carries `ctx.problems` — one `{path, message}` per problem — beside the joined `msg`.
  The dotted path was always in the sentence (`_from_mapping` prefixes every nested problem
  with it) but nothing said so, and `problem_path` in `pythonsrc/organizer/spec.py` is the
  one place that now does. The alternative was splitting the joined sentence in the browser
  on a separator no test in this repository could hold.
- **The prompt of a spec job.** `prompt` is no longer `min_length=1`, because a spec job
  has none: nobody typed words, and the geometry is a function of the spec alone. But
  `print_job.prompt` is what every list, feed line and history row titles a job with, so
  `_a_job_always_has_a_label` fills it from `spec_label(spec)` — "deck box · 100
  double-sleeved standard cards", every word a field of the spec. Derived on the server for
  the reason the *canonical* spec is what gets stored: a second copy of this sentence in
  the browser would drift from the spec it claims to describe. A line somebody types is
  kept as it is, and a request with neither a prompt nor a spec is refused exactly as
  `min_length=1` refused it.
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
  streamed the file. The api-server process is the one with `~/.ds-mvp/.config_key`
  bind-mounted, so that was a read of the Fernet key for the store holding printer API
  keys — and of `.env` and `pythonsrc/config.py` beside it, and an *unauthenticated*
  read even now, because `serve_spa` is one of the two routes that is still `@public`
  and has to be. `contained_path(base, *parts)`
  joins and then requires `is_relative_to(base)` **after `resolve()`**: a lexical check
  passes a path whose every component is innocent and whose symlink target is not, and
  an *absolute* part needs no `..` at all (`Path("web/dist") / "/etc/passwd"` is
  `/etc/passwd`, and `//x` reaches a `:path` group as `/x`). Six joins use it —
  `serve_spa`, `resolve_job_artifact` (both `job_id`, which arrives as `..` from
  `/jobs/%2e%2e/blueprint`, and `filename`), `resolve_job_profile`, the two
  `repo_root / job.profile_name` profile reads, where `profile` is free text from
  `POST /jobs` that is `json.load`ed and handed to `run_operator.py`, and the fit
  photo's two — `fit_photo_target` on the way in and `fit_photo_on_disk` on the way
  back out, which is the only join here that *writes*. A refused SPA
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
  **The bigger hole beside it** — `POST /config` had no authentication, so any caller
  could repoint `OCTOPRINT_URL` at their own host and have the server ship it
  `OCTOPRINT_API_KEY` — is closed by the host binding below. The shared secret closes
  it a second time, and the binding is still the load-bearing half: it holds against
  anyone who *does* hold the token, which one shared credential makes a real case.
- **Config store** (`config_store.py`): Fernet-encrypted key-value store in the telemetry database (`app_config` table); the key stays on the host at `$DS_CONFIG_KEY_PATH`, default `~/.ds-mvp/.config_key`
- **The protected thing in `config_store.py` is the credential surface, not the file.**
  CLAUDE.md's *never touch these unless the issue explicitly says so* list named the
  whole file. #168 added `ALLOW_PROMPT_JOBS` — non-secret, absent from
  `SUBPROCESS_ENV_KEYS`, unrelated to `DS_API_TOKEN` — and `claude-review` raised it as
  a blocking credentials finding *after* the merge, because the PR was a draft until
  the moment it landed. **#175 is the authorisation that change needed**, recorded
  retroactively for `cd73b5c`, and it settled the rule as well: what may not move
  without an issue is now named — any `secret: True` entry, `PRINTER_CREDENTIAL_HOSTS`
  and the `internal` flag `INTERNAL_CONFIG_KEYS` is derived from, `SUBPROCESS_ENV_KEYS`,
  the Fernet key path, and `DS_API_TOKEN`'s absence from `CONFIG_KEYS` — and
  `tests/test_config_store_guards.py` asserts each one, so the contract's claim fails as
  a test rather than as a paragraph nobody re-read. The narrowing is **not** "a
  non-secret key is free". What made `ALLOW_PROMPT_JOBS` worth an issue is that it
  re-opens the path that bills EUR 0,32 a generation, which is the *money* rule; a
  `secret:` flag was never going to say so, and the contract now points that key at the
  bullet that does. The **inventory** is the piece that was missing everywhere else: the
  host binding, the subprocess allowlist and the token's absence each had a test, and
  nothing at all failed when a new secret appeared or an existing one lost its flag.
- **A printer credential is bound to the host it was saved for.** `POST /config` had
  no authentication, and it writes *both halves* of an authenticated outbound request:
  the address and the key. So one request repointing `OCTOPRINT_URL` at
  `http://attacker.example/`, followed by `POST /config/test-connection`, made this
  server send `GET http://attacker.example/api/version` carrying the real
  `X-Api-Key` — a confused deputy, and one that masking the key in `GET /config` does
  nothing about, because the caller never needed to read it. `MOONRAKER_API_KEY` and
  `BAMBU_CODE` reached the same shape at dispatch. The fix is a **binding, not a
  check**: `ConfigStore.set` records `OCTOPRINT_API_KEY_HOST` /
  `MOONRAKER_API_KEY_HOST` / `BAMBU_CODE_HOST` — scheme, host and port, default port
  dropped — at the moment the *credential* is written, and
  `bound_printer_credential()` is the single place that decides whether a key may go
  out. Changing the address alone therefore moves nothing; **re-saving the key
  re-binds it**, which is a person deciding about a host they just typed. The
  binding lives in the store rather than in the endpoint because a key is also saved
  by `applyOctoprintSimulator` and by the simulator wiring, none of which goes
  through `POST /config`. Six outbound paths ask: `test_connection` (which still
  probes, keylessly, and appends the reason — a silent 401 reads as a wrong key and
  sends someone to re-type a correct one), the job detail's own printer probe,
  `subprocess_env` (`OCTOPRINT_API_KEY` is on the allowlist, which was the other way
  out), `resolve_printer_target`, the dispatch gate, which **refuses with a
  409** rather than dispatching keyless — the operator would be rejected by the
  machine and leave a job reading as dispatched — and the **operator subprocess it
  launches**, which was the one the first version of this binding missed. That one is
  worth stating in full, because two things had to be true at once for it to leak and
  neither was visible from the other's code. `subprocess_env` checked
  `OCTOPRINT_API_KEY` against `OCTOPRINT_URL`; the dispatch block then overwrote
  `env["OCTOPRINT_URL"]` with `target["base_url"]`, which on a klipper or bambu
  profile is `MOONRAKER_URL` or `BAMBU_IP`; and `run_operator.py` paired exactly those
  two variables. The gate above it asked only about the *target* firmware's
  credential — unset, therefore not withheld, therefore a pass. So an OctoPrint key
  bound to someone's own printer left for an address an unauthenticated `POST /config`
  had just named. The fix is that **the operator is told which printer in the same
  three variables the pipeline is told in** — `DS_FIRMWARE`, `DS_PRINTER_URL`,
  `DS_PRINTER_KEY`, the last of them the gate's own firmware-resolved answer — and
  `OCTOPRINT_API_KEY` is removed from that child's environment outright. The same
  edit closed the other half: `subprocess_env` starts from `os.environ`, and
  `OCTOPRINT_API_KEY` is documented in `.env.template` and loaded into every compose
  service by `env_file`, so with no key *stored* the binding had nothing to withhold
  and the inherited one was never overwritten. Withholding now **removes** rather than
  declining to set — a printer credential in a child's environment comes from the
  bound store or it does not come at all. The three `*_HOST` keys are in
  `CONFIG_KEYS` because `set()` must accept them, and in `INTERNAL_CONFIG_KEYS` so
  the HTTP surface refuses them: a writable `OCTOPRINT_API_KEY_HOST` is the same hole
  with one more request in it. `GET`/`POST /config` carry a `host_binding` block so
  Settings can say *key bound to host X* — the extra step is only fair if it is
  visible. Two consequences, both deliberate: a key saved **before** its address is
  bound to nothing and stays unsendable until re-saved, and a profile's own `api_key`
  is only ever paired with the profile's own `base_url`, never with a stored address.
  `tests/test_credential_host_binding.py` runs the whole table over all three
  credentials.
- **A stored value reaches a subprocess through one allowlist, and never through
  `os.environ`.** `POST /config` wrote the store *and* `os.environ[key]`, the startup
  hook copied the whole store into `os.environ` besides, and both launches —
  `docker compose run pipeline-runner` and `run_operator.py` — were
  `os.environ.copy()`. So every stored key was a variable in every child process this
  server spawns, set by an endpoint that had **no authentication** in front of it.
  `PYTHONPATH` was one of those keys: one request prepended an import path to the
  pipeline container, whose `data/inputs`, `data/outputs` and `data/logs` are writable
  bind mounts — one file write away from code execution, so a chain rather than a
  curiosity. `server.subprocess_env()` is the only builder now: this process's
  environment (which came from `.env` and the image) plus `SUBPROCESS_ENV_KEYS`, three
  keys each carrying the consumer that reads it. Everything else stays server-side and
  is read with `config_store.get()` — the printer set becomes
  `DS_FIRMWARE`/`DS_PRINTER_URL`/`DS_PRINTER_KEY` at the launch (which is also where
  the container's localhost rewrite happens), the `SKIP_*` flags become argv,
  `EXECUTION_STRATEGY_OVERRIDE` becomes a strategy, and `LOG_LEVEL` has no reader in
  anything this server launches. The store is read **at the launch**, not cached at
  import, because that is the one useful thing the `os.environ` write did: a key saved
  in Settings must reach the next job without a restart. `PYTHONPATH` is out of
  `CONFIG_KEYS` and off the Settings page — an import path is the image's — and
  `purge_retired_keys()` deletes the row at startup, because dropping the key without
  dropping the value leaves a setting nothing can read, edit or delete.
  `tests/test_subprocess_env.py` binds the three halves: no environ mutation, exactly
  the allowlist in both launch environments, and a value changed after startup
  reaching the next one.
- **SimulatorManager** (`simulator_manager.py`): manages a real dockerized OctoPrint on port 5001 (`docker compose -f infra/docker-compose.yml --profile simulator up -d octoprint-simulator`), found by compose label or name. Its virtual printer plugin is enabled in `data/octoprint/octoprint/config.yaml`, so the full dispatch path runs without hardware. `start_moonraker()`/`stop_moonraker()` are deprecated stubs that always report not-running — there is no Moonraker simulator, and `tests/mocks/` no longer contains mock servers.

### Web push (`server/push.py`)

**The one notification this product sends.** A print runs for hours, nobody watches it,
and when the printer says it finished the row goes to `awaiting_verdict` — where only a
person can say whether the part actually came off the bed. That question is the pilot's
central instrument (`feedback_funnel`), and until this existed it reached whoever
happened to have the page open.

**A reconciler, not a hook, and that is the load-bearing decision.** Three code paths
move a job into `awaiting_verdict`: `print_dispatch` and `_run_pipeline` in
`server/app.py`, and `OctoPrintCollector._on_event` — which runs in *whichever process
claimed the job*, which may be the pipeline container or `run_operator.py`, and which
never touches the broadcaster. Hooking the writers means three places to remember, in
two processes, one of them not this one; the fourth writer added next year would be the
one that silently sends nothing. So a task on a 30 s cadence
(`$DS_PUSH_INTERVAL_S`, `0` disables) asks the database the same question
`GET /feedback/pending` already asks, and notifies what it finds.

**`push_sent` in `job_event` is the dedup key, not a record of one.** "Has this job
been pushed" has to be a fact in the database: a flag in this process's memory would
notify a second time after a restart, which is the failure that makes people switch a
notification off for good. It is a `job_event` kind rather than a `print_job` column
for the reason that table exists — a new engagement signal should not be a migration.
The event is written **after** the sends, carrying `{sent, failed, removed}`. Writing
it first would be safer against a crash mid-send and was rejected: the event is the
only record this product keeps of a delivery, and one claiming a send that never
happened is worse than the single duplicate a crash between the two can cause. A job
with **no subscriptions** is not recorded at all — nothing was delivered, and marking
it would make the first device to subscribe miss the job it subscribed for.

**The backlog guard.** `PUSH_MAX_AGE_S` (`$DS_PUSH_MAX_AGE_S`, default one hour) is why
the first tick after this shipped did not announce every print anyone ever forgot to
answer. A job is notified only while its `completed_at` is recent; a server restarting
inside that window still delivers, a backlog from last month never does. A row with no
`completed_at` is not notified either — every writer that sets `awaiting_verdict` sets
it in the same call, so an empty one *is* the backlog.

**The subscription table is not about a job.** `push_subscription` is keyed on the push
endpoint, which is what the push service issues and what the browser re-sends on every
load, so the write is an upsert: a plain insert grows a row per visit for a device that
subscribed once. No foreign key, no job column, and deliberately **no user column** —
`server/auth.py` is one shared secret and there is no per-user model, so a notification
goes to every subscribed device and a `user_id` here would claim an identity nothing
establishes. The only garbage collection is the push service's own verdict: a **404 or
410 deletes the row** (that service saying the device is gone for good), while a 502 or
a timeout is a bad afternoon and the row stays.

**The VAPID keypair is generated on first use and never handed back.** Both halves are
`CONFIG_KEYS` marked `internal`, so `POST /config` refuses them, `GET /config` does not
list them and `/config/{key}/reveal` will not return one; `INTERNAL_CONFIG_KEYS` is now
read off that flag rather than from a second list, so a key that declares itself
internal cannot stay writable. The public half leaves through
`GET /push/vapid-public-key`, which is all a browser needs; a browser holding a
subscription made against an older key is told to make a new one by that route
answering differently. `VAPID_SUBJECT` is the one push value a person may set — RFC
8292's `sub` claim is a contact address, not a credential, and a *missing* one is
refused by every push service, which is why there is a placeholder default.

**The three routes are authenticated by writing nothing**, and here that default is
doing real work: a subscription is an address this server will POST to, so an open
`POST /push/subscriptions` would let anyone who could reach the port aim it at a host of
their choosing — the same shape as the `OCTOPRINT_URL` confused deputy above, except
there is no credential to bind, so the token is the whole answer. The endpoint is
additionally required to be an `https` URL with a host.

**The dependency.** `pywebpush` (MPL-2.0) with `py-vapid` (MPL-2.0) and `http-ece`
(MIT) — file-level weak copyleft, imported unmodified, licences read off the published
wheels rather than off an issue body, recorded in `licence_policy.REVIEWED_WEAK_COPYLEFT`
and `THIRD-PARTY-NOTICES.md` § 1. The alternative was roughly 150 lines of RFC 8291 on
the `cryptography` already in the tree; it was refused because a hand-rolled payload
encryption fails on somebody's phone and passes in CI. The send path is
`webpush_async`, on the `aiohttp` the api-server image already carries, so a tick does
not block the event loop.

**The service worker gains two handlers and no cache rules** (`web/src/sw.ts`). A push
handler reads the event payload — which the browser has already decrypted for this
subscription — and calls no route, so the worker still holds no credential and the
allowlist is untouched; `tests/test_pwa_shell.py`'s `respondWith` count is still two.
Nothing in that handler may bail out: `userVisibleOnly: true` is the only subscription
a browser grants, and a push that ends without a visible notification is one Chrome
replaces with its own message and then revokes the permission over. The tap opens
`/dashboard/<job_id>` — the SPA's route. `/jobs/<job_id>` is the API, and opening it in
the installed app opens a JSON document.

**What this needs that the deployment does not yet have: TLS.** A service worker is
only registered in a secure context, and `localhost` is the one insecure origin
browsers treat as secure. The api-server binds loopback by default (`$DS_API_BIND`) and
terminates no TLS — see **Configuration** — so a phone on the same network reaches it
over plain `http://<lan-ip>:8000`, where the worker never registers and
`pushManager.subscribe` therefore never runs. **Push is complete in this repository and
undeliverable to a phone until the app is served over HTTPS**, which is a deployment
change (a reverse proxy with a certificate, or the hosted beta) and not a code one.
Everything up to that point — the keys, the routes, the reconciler, the worker — is
exercised by `tests/test_push.py`; the device half of the acceptance criteria is a
manual checklist that unblocks with the certificate.

**iOS.** Safari has supported web push since 16.4 and **only from an installed Home
Screen app** — the button does nothing in a Safari tab, so Settings § 05 says so rather
than letting a person find out. That, being per device, and "blocked is not off" (once
a browser has been told no, the page cannot ask again) are the three facts on that
section, each of them otherwise a support conversation.

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
- **`DS_API_URL` is one value with a translation, not one value per strategy.**
  `NATIVE_API_URL` (`http://127.0.0.1:8000`) is this server's address to a process
  running *beside* it — the native Phase 1 subprocess, and `run_operator.py`, which
  runs in this container — and `_container_api_url` rewrites the loopback host to
  `host.docker.internal` at the one boundary that needs it, the `-e DS_API_URL=` on
  `docker compose run`. It used to be chosen by execution strategy, and
  `mps_native` set the loopback for *both* processes: the pipeline runs in a
  container on **every** strategy, so on a Mac it was handed the address of itself
  and the collector's `send_internal_telemetry` POSTed into the void, taking the
  WebSocket fan-out of live print telemetry with it. Silent three times over — the
  relay falls back to a local broadcaster the container does not have, the pipeline
  still exits 0, and it only bites once Phase 5 runs *inside* the pipeline
  (`--print`), which the web app never asks for because it stops at the dispatch
  gate. `container_reachable_url` is deliberately *not* reused: it asks whether
  *this* process is containerised, which is the wrong question when the process
  that opens the connection is the pipeline container, and it prefers the OctoPrint
  simulator's compose route. `tests/test_api_url_routing.py` asserts the forwarded
  argument names no loopback host on any strategy.
- **`host.docker.internal` is the fallback, not the answer, when the server is a
  container too.** It resolves to the host's gateway address, while `ports:`
  publishes the api-server on `${DS_API_BIND:-127.0.0.1}` — and a socket bound to
  loopback does not accept a connection arriving on another interface. So under
  `docker compose up api-server` on the default bind the name resolves and the
  connect fails, which is the same silent dead relay by a second route.
  `_container_api_url` therefore prefers the compose network, via
  `SimulatorManager.own_internal_url` — the mirror of `internal_url`: the container
  being addressed is the one the server runs in, and the caller is the pipeline
  container it is about to start. It lives on that class because the server's one
  Docker client and its "which container am I" lookup are already there, and
  because `tests/conftest.py` cuts *that object* off from the daemon; a second
  client built elsewhere would reach a developer's real Docker during a test run.
  **The project it is asked about is the caller's, not its own**
  (`_compose_project_name`, read from `COMPOSE_PROJECT_NAME` with `COMPOSE_FILE`'s
  directory as the fallback compose itself would use): compose names a project
  after the directory of the first `-f` file, so an api-server brought up from
  `infra/` is in project `infra` while the pipeline it launches — carrying
  `COMPOSE_PROJECT_NAME=ds-mvp` from the compose file — is in `ds-mvp`, and a
  service name does not resolve across two default networks. Every decline (not a
  container, another project, no published port, no network, Docker unreachable)
  falls back to the host gateway rather than to an address that fails at connect
  time, and a native server does not ask Docker at all.
  **The route therefore fires only where the two project names agree, and in the
  documented `make up` they do not yet.** `docker compose -f
  infra/docker-compose.yml up api-server` from the repo root labels the api-server's
  project `infra` — compose takes the directory of the first `-f` file and the
  compose file carries no top-level `name:` — while that container's own
  environment sets `COMPOSE_PROJECT_NAME=ds-mvp`, which is what the pipeline it
  launches will use. Two projects are two default networks, so `own_internal_url`
  correctly declines and the pipeline gets the host gateway, which on the default
  `DS_API_BIND` is the dead route this bullet describes: that configuration still
  has no live relay. Exporting `COMPOSE_PROJECT_NAME` to match is the workaround
  (`make start-native` already sets it). Aligning the two for good is a compose
  change — a top-level `name: ds-mvp`, which would also end the
  `infra-*`/`ds-mvp-*` duplicate container records `SimulatorManager._prefer_running`
  works around — and it renames every existing container and volume on a
  developer's machine, so it is its own change rather than one smuggled into a
  telemetry-routing fix.
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
- **The fit photo is evidence, not a verdict** (`fit_photo_path`,
  `db.update_job_fit_photo()`, its own `fit_photo` stage in `trace.STAGES`). One column,
  holding the repo-relative `data/outputs/{job_id}/fit_photo.{jpg|png|webp}` that
  `POST /jobs/{id}/photo` wrote. It is the only record of what a part actually looked
  like: `printability_score` is a prediction about a mesh, `outcome` is one word about a
  print, and neither can be re-derived into "the lid sat 0,4 mm proud" — the photograph
  either exists or the observation is gone the moment the part is thrown away or used.
  **It is deliberately not routed through `update_job_outcome_verdict`**, for the same
  reason `print_duration_s` is not: someone can photograph a part that did not fit and
  then say nothing, and the job has to stay `awaiting_verdict` until a person answers. A
  writer that touched `outcome` would answer on their behalf, take the job out of the
  pending queue, and then have the machine-never-overwrites-human rule refuse the verdict
  they gave a minute later. It is its own stage for the same reason a stage names exactly
  one `TelemetryDB` method.
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
  `ProcessProfile.from_printer_profile()` derives limits from `pythonsrc/profiles/*.json`.
  `fit_offsets` is the one field on it **no check reads** — see the section below.
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

### Fit offsets (`pythonsrc/fit_offsets.py`) — a profile suggests, a spec decides

Issue #89 asked a person to decide where per-printer fit tolerances live, and the owner
decided on 2026-09-17: **(b), they stay in the spec.** A printer profile is the source
the composer pre-fills a form from, never an input to the compiler. Everything here
follows from that one sentence.

**Why (b) and not (a).** Under (a) — offsets applied at compile time — a mesh becomes a
function of a machine, so `spec_hash` has to hash the profile too, the same spec exports
different bytes on two printers, and a spec handed to somebody else stops being a design
and becomes a build log. It also needs the printer profile *before* Phase 2, which the
pipeline does not read until after it, so a user with no printer configured could not
compile at all. The case for (a) was the Phase 4 coupon → calibration loop wanting to
update offsets per printer and material; it dissolves, because applying a new offset to
an existing design under (b) **is a spec-diff**, which is already a Phase 3 roadmap box —
and a re-fitted box is a different object that should say so rather than changing under
its owner.

**The three fields, and why one of them is shaped differently.** A profile offers
`fit_lid_clearance_mm`, `fit_cavity_clearance_offset_mm` and `fit_stack_slack_mm`. Two are
absolute; the cavity one is an *offset added to whatever `process.fit_intent` resolves
to*, because the intent is the word a person actually chooses — "a box I close" versus "a
tray I lift cards out of" — and a profile stating the clearance outright would silently
overrule it and leave the composer with a control that changes nothing. The machine
contributes an allowance, the intent keeps deciding the fit, and the names say which is
which.

**It is a standalone stdlib-only module, and that is load-bearing rather than tidy.** The
numbers belong to `ProcessProfile`, and `printability` imports numpy, trimesh and scipy —
none of which the api-server image installs (`infra/docker/server.Dockerfile` is the
list). So `POST /organizer/resolve`, which is where the pre-fill happens, cannot ask
`ProcessProfile` what a profile says. Both sides import `fit_offsets` instead, which is
what stops the composer and the printability scorer growing two opinions about what four
keys in a profile file mean — `_profile_build_volume`'s single-implementation rule again,
and for the same reason.

**The compiler cannot reach an offset, and that is asserted rather than agreed.** Nothing
under `pythonsrc/organizer/` mentions the module, checked by grep over the package in
`tests/test_fit_offsets.py`. An import is all it would take for a well-meant change to
start applying a machine's millimetres inside `compile_spec`, at which point (b) quietly
becomes (a) and nothing else in the suite notices.

**Two classes, and the honest part is which half of each number is sourced.**
`FIT_OFFSET_CLASSES` has `tuned` (the Bambu P1S: ±0,1 mm typical, shrink-compensated —
`dimension-kb-research.md` §6, Bambu forum) and `desktop` (Ender 3, Anycubic Mega S,
Klipper test: ±0,5 % with a ±0,5 mm floor, Hubs). The *bands* are sourced — §5's
0,2–0,4 mm friction lip, §3's 1,5–2 and 4–6 mm clearances — and the *class accuracies*
are sourced, but **the placement of each number inside its band is this project's
reasoning, not a measurement**, and the module says that in those words the way
`Process.base_chamfer_mm` labels itself an unsourced design default. A JSON file cannot
carry a comment, so each profile names its class in `fit_offsets_class` and
`tests/test_fit_offsets.py` binds the name to the row: the numbers cannot drift from the
sources without a test going red.

The one figure with two independent sources behind it is the desktop cavity allowance:
+0,5 mm is §6's accuracy floor, and added to the intents it lands `snug` at 2,0 mm and
`easy` at 4,5 mm — **both inside §3's own bands**, which were gathered from commercial
deck boxes and have nothing to do with §6. Two sections agreeing is what a sourced number
looks like; one section and a round figure is not.

**The finding that matters is a negative one.** No figure in a 0,2–0,4 mm friction band
survives a ±0,5 mm machine: on a desktop printer at the bottom of its sourced accuracy, a
lid designed to any clearance in that band can print interference-fit. That gap is not
closable by choosing a better default, and pretending otherwise is the
"printer-accuracy assumption" §6 ends by naming. This table is the prior the Phase 4
test-fit coupon and the calibration loop start from, not the answer they replace.

**`stack_slack_mm` is the same on every bundled profile, deliberately.** Nothing sources
a per-machine figure for it and nothing should: what it absorbs is the *stack's* error —
sleeve thickness varies by brand and by wear, and §2 keeps a 120-vs-130 µm disagreement on
one line of Dragon Shield alone — not the printer's. It is a field rather than an omission
so the calibration loop has somewhere to put a measured figure if one ever turns up, and
the docstring says it carries none today.

**Where the pre-fill happens, and what the person sees.** `POST /organizer/resolve`
answers `fit_defaults`: the three millimetres resolved against the profile *and* against
this spec's own fit intent, the profile and printer they came from, a `declared` flag, and
a `basis` sentence. It is **never null and is answered on the refusal branch too** — a
spec is invalid for most of the time somebody is composing one, so a default that arrived
only once it parsed would arrive after the fields it fills had been filled by hand; "no
printer configured" resolves to the schema's own numbers with `declared: false` saying
nobody was asked, which is the same millimetres and a different fact. The cavity figure
arrives **already summed**, and the offset is beside it to be shown rather than applied: a
client adding the two would be a second copy of `FIT_INTENT_CLEARANCE_MM`, which is the
drift that endpoint exists to refuse.

In the composer the three are a ruled-off group, and they are **the only fields in that
form where blank does not mean "the archetype's own default"** — blank means the
printer's, `specFromForm` writes that figure into the spec, and anything typed wins. They
open blank rather than seeded, which is the whole mechanism: a seeded value is one the
person has to notice and delete, and it would need re-seeding every time the fit intent
moved the cavity figure underneath it. Blank needs no has-this-been-touched flag anywhere,
so there is none to go wrong. With neither a typed value nor an offer the field is
*omitted* and the schema resolves its own default exactly as before — a browser inventing
0,2 mm to fill that hole would be the one number in the form with nothing behind it.

**What the row records, and why it has to.** Under (b) the mesh is not a function of a
printer, so nothing else in a finished job says which machine's figures were on screen
when a person accepted them — and "this box does not close" is a complaint about a
printer. `generation_params.fit_profile` carries the profile, `FIT_OFFSETS_VERSION` and
what the profile *offered*, with `declared` separating "this machine suggested the
schema's own numbers" from "nothing was asked". It never records what the spec chose: the
spec is that record, in millimetres, written beside it. It is a **sibling** of
`features_document()` rather than part of it, assembled in `pipeline._profile_fit_record`,
because `CompileResult` is what the compiler produced and the compiler is not allowed to
see a fit offset.

The four `fit_*` keys are dropped silently by `CuraSlicer._profile_settings`
(`FIT_PROFILE_KEYS`), for `DOCUMENTATION_KEYS`' reason — four "not a CuraEngine setting"
lines on every slice is the noise that trains a reader to skip the line that would have
told them about a mistyped setting name — and because by the time a profile reaches the
slicer, the millimetres it pre-filled are already in the spec the geometry was built from.

**The tripwire that reopens this**: closed-beta evidence that users routinely print one
design across several printers and expect each to fit. That would make (b) force them to
maintain N variants of one design, and (a) would become right. Watch for it in cohort 1;
until then this is settled.

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
**Every free-text field is screened, and each on its own tokens** (`CHANNELS`): `prompt`,
`material_colour` — free text the blueprint wrapper interpolates, so a screen reading
`prompt` alone leaves the colour box as a second, unwatched prompt channel — and
`embossing_text`, the third. The three were joined into one string before matching until
2026-09-17, which was wrong twice: one field lent another its grammar, and a flag could
not say which box the name was typed into. Now the most severe verdict across the
channels wins, ties go to `CHANNELS` order (the prompt first), and
`ScreenVerdict.channel` rides on the refusal and on `ip_screen_flagged`.

**A functional article is not a reproduction, and the grammar is what says which**
(`_classify_usage`, 2026-09-10, issue #79). This screen was written for the figurine
product, where every curated name meant "print me Pikachu". The parametric product's
users name a franchise as the *contents*: "deck box for Pokémon cards" is the primary
persona's literal prompt, and it was refused with score 1,0 while MTG, Yu-Gi-Oh!,
Lorcana and One Piece passed by omission from the list — inconsistent, and worse than
either consistent answer. So a match carries a second axis, and **only for strong
hits**: a **depiction** cue **blocks** — the name is what the part is meant to look
like; a **purpose** cue **flags** — the name is what the part is *for*; and with
neither, **the category decides**, a `character` blocked as the prompt's subject ("a
Pikachu deck box") and a `franchise` or `brand` flagged as its contents ("a Pokémon
deck box") — the latter **only when one of the parts this product makes follows the
name** (`ARTICLE_NOUNS`/`CONTENTS_NOUNS`, within 3 tokens). A franchise in front of
anything else is naming the subject — "a star wars x-wing", "a hogwarts castle", "a
nintendo switch dock" — which is a reproduction of someone else's design however the
sentence is arranged, and stays refused exactly as it was.

**Each cue is scoped to the construction it belongs to, never to a window**, and both
loosenings were reachable: a purpose cue that only had to sit within 6 tokens read
"for my son, a pikachu" as a purpose, so *any* prompt could be prefixed past Tier 1,
and a depiction cue that only had to be within ±4 read "deck box for pokemon cards,
lid on top" as a likeness — refusing the primary persona again by a second route. So a
purpose cue has to reach the name across `BRIDGE_TOKENS` only (articles, possessives,
digits, `sleeved`/`double`/`standard`, contents nouns), which is what separates "fits
60 double sleeved lorcana cards" from "for my son, a pikachu"; a depiction **noun**
(`emblem`, `figurine`, `engraved`) is read in the window either side; `in the shape of`
counts only *before* the name and `shaped`/`themed` only *immediately after* it,
because "shaped like a cube" after the name describes the box; and there is **no bare
locational cue** — "on the lid" locates a depiction noun and is not evidence of one,
and the nouns already carry "charizard emblem on the lid" unaided.

Depiction wins when both fire and the most severe verdict across
every match wins, so "deck box for Pokémon cards with a Charizard emblem on the lid"
is still refused; the best near-match is weighed **alongside** the exact hits rather
than only in their absence, because an exact functional hit no longer refuses the
prompt by itself and an evasion has to be caught on the fuzzy path. The ambiguous→strong
promotion ("the joker from batman" is not a playing card) triggers on a strong hit
**that is itself a refusal**, not on any strong hit: a functional franchise is the one
construction this screen accepts, and promoting on it refused "a deck box for pokemon
cards with a creeper vine engraved on the lid" over a plant. The cues are
English grammar the matcher reads, so they are module constants — the blocklist
promises to be descriptive data about marks only, and the TCG franchises are on it
**for the flag**, so every franchise is treated alike rather than passing unlisted.
Two boundaries are stated rather than discovered: a character named only as contents,
with no depiction cue ("a stand for Pikachu"), is flagged; and a brand naming an
accessory's subject ("a nintendo switch dock") is refused, with the rephrasing that
says what the part is for ("a dock for a Nintendo Switch") as the appeal path the
refusal's own wording asks for. Both classes
reach the human gate, which remains the last word; where the line sits is a **product
decision pending counsel**, recorded in `docs/deferred-legal-tasks.md` § L6 and not
legal advice. `ip_screen_flagged` carries the `usage`, which makes "how often does the
functional rule fire" a query.

**The embossing field is not a functional-article context** (`DEPICTION_ONLY_CHANNELS`,
2026-09-17, issue #156 — part (b) of the same re-scope, and what PRD F13 waits on).
F13 raises typed words *on the part*, which is the one place this product can put
someone else's mark on a manufactured good — and the functional rule has no purchase
there, because nothing raised on a face holds anything. So in that channel a **strong
hit is refused whatever grammar surrounds it**: "deck box for Pokémon cards" still
passes as a purpose, "Pokémon" embossed on that same box does not, and separate
screening is what keeps the first from demoting the second. An *ambiguous* term still
only flags — "joker" and "frozen" are ordinary English on a lid as much as in a prompt —
and the refusal names the appeal path it can actually offer: keep the prompt, emboss
your own words. `JobRequest.embossing_text` is the field, bounded at 64 characters like
the colour box and screened before `job_id` is minted and before `dump_spec` writes the
job's input directory, so a refused submission leaves neither a row nor a file. It
compiles to nothing yet by design: the geometry is issue #157, and the screen ships
first. Where the line sits is a product decision pending counsel, recorded in
`docs/deferred-legal-tasks.md` § L6.

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
holds refs to its scene, its material and its dimension-line materials for the same
reason. The callout *labels* need none of it: they are DOM nodes styled from the ink
tokens, so a theme change reaches them the way it reaches everything else on the page.

**The mesh preview is in millimetres, and its numbers come out of the pipeline**
(2026-09-17, issue #88). `MeshViewer` normalised every mesh to 80 scene units, which
made any annotation a lie waiting to happen: a figure in mm over a mesh whose size came
from a ratio. Four decisions:

- **Scene units are millimetres.** Nothing is scaled; the camera is framed from the
  bounding box instead — `distance = (extent / 2) / tan(fov / 2) × 1.7`, with `near`,
  `far`, `minDistance` and `maxDistance` all derived from it. A 200 mm tray and a 50 mm
  divider are now genuinely different sizes at the same zoom, which is the point.
  `GCodeViewer` keeps its own camera, so the slice tab still shows the part at a
  different size than the mesh tab does.
- **One group carries both view transforms.** The mesh and the callouts hang off a
  `THREE.Group` that holds the Z-up → Y-up convention and the centre-and-floor
  translation, rather than those being baked into the geometry. An anchor cannot drift
  from the surface it names, because there is no second transform to drift through.
- **No millimetre is computed in a browser.** Every figure is `ViewCallout.value_mm` from
  `view.json`, rendered with a comma decimal; the viewer has one formatter and one call
  site, which `tests/test_job_spec_endpoint.py` pins. It reconciles the served mesh
  against the document's frame first and draws nothing when they disagree.
- **A prompt job is told nothing.** `hasSpec` is false, so the viewer fetches nothing and
  draws nothing extra — no message, no reason string. The three absences already have
  three sentences in `SpecPanel`, and a fourth written by a viewer would be one it
  invented. Below **720 px**, the phone step of the one breakpoint ladder, only tier 1
  is drawn: the cavity and the closure, which is what a misparse costs an eight-hour
  print over. Labels are `CSS2DObject`s (`three`'s own — no new dependency) over a
  `pointer-events: none` layer, faded to 0,22 when their `offset` turns away from the
  camera. That fade is a stand-in for occlusion, not occlusion: labels on a near-square
  part can still overlap, and true label layout is not in scope.

**The composer's parametric path** (2026-09-11, issue #76). The redesigned composer said
"your words become a spec" and had no path from a person to one: the archetype strip
reported its choice to UI telemetry and sent it nowhere, `createJob` had no `spec` field,
and the only way to run a spec job was the CLI or a hand-built `POST`. Five decisions, and
each of them is a refusal of something easier:

- **The strip is the mode, not a hint.** It was documented as a steer that travelled with
  the prompt to a composer phase, which would be true of a composer that extracted a spec
  from words — and nothing extracts anything yet (a later issue, and the rule that keeps
  them apart is the one the pivot turns on). As a hint it therefore did nothing at all.
  Picking an archetype opens `SpecForm`; clearing it is the generative path, unchanged.
- **The form is the alpha vehicle** (roadmap §5A cut #3). Cards, sleeving, fit intent, wall
  and lid engagement for the deck box; plate thickness, tab width, tab height and tab
  position for the divider; rows, columns, the three pocket dimensions and the wall for the
  token tray. The controls follow the archetype because the archetype decides
  which fields are *read*: `card_divider` reads neither `process.wall_mm` nor `fit_intent`,
  and offering them would suggest they change the plate. The tray went further and dropped
  the *cards* and *sleeves* controls entirely (issue #84): its compartments are pockets,
  `specFromForm` sends no card stack for it, and a control that sends nothing is a control
  that cannot be refused — which is worse than one that is not there. Its `StackReadout`
  says there is no stack to resolve rather than *fix the fields above*, for the reason
  `unreachable` exists: telling somebody their input is wrong when it is not is the worst
  answer available, because it is the one they act on.
- **Every millimetre on screen came back from the server.** A blank optional field is sent
  *absent*, so what the spec panel shows is the schema's own default — the deck box's
  2,4 mm wall, the `snug` intent's 1,5 mm clearance — rather than a copy of it in a
  browser. The one figure the form states as prose is the `standard` card's 63,5 × 88,9 mm,
  and `tests/test_composer_options.py` binds it to `dimensions.CARD_KINDS`.
  **The three pocket dimensions are the one exception, and `REQUIRED_CONTENT_MM` is where
  the exception is declared** (issue #84): the schema has no default for them and must not
  have one, so a blank field there is a *missing value* rather than "take yours", and the
  form opens on the example's 20 × 20 × 15 mm exactly as it opens on 100 cards. The test
  that forbids millimetre defaults reads that list and then holds every name in it to the
  claim by poking the schema — `process.wall_mm` could not be added to it, because an
  omitted wall means "take the archetype's default".
- **Nothing is offered that the engine refuses.** Five closed vocabularies live in
  `organizer/spec.ts` beside `ARCHETYPES`, bound to their Python counterparts by the same
  kind of text-reading test, for the reason the strip needed one. `CARD_KINDS` and
  `LID_KINDS` have one entry each and are rendered as *sentences* rather than as
  single-option selects — a select you cannot change is a control that is lying about being
  one.
- **Every refusal lands on the field it names.** `FIELD_BY_PATH` maps the schema's dotted
  paths onto controls; anything unrecognised falls to `form` and is shown whole, because a
  validation message that matches nothing and is quietly dropped is a submit button that
  stops working for no visible reason. The test pokes each mapped path into a spec and
  requires the schema to name it, rather than trusting the table — against **two** base
  specs since the token tray, because a compartment is a card stack *or* a pocket and no
  one spec can carry both. A tray sends one identical pocket per grid cell, so a blank
  pocket width is the same sentence once per compartment; `flattenCompartment` drops the
  index before both the routing and the de-duplication, so six refusals become the one
  refusal they are rather than one on the control and five on `form`.

The height control is *absent* in spec mode rather than disabled — the server refuses a
spec sent beside `target_mm`, so a height control there could not be obeyed — and the
prompt field becomes the job's name, captioned with what it is: the spec decides every
dimension, and nothing reads that line back into the geometry.

Five layout rules are load-bearing enough to name, because breaking them is invisible in a
diff and obvious on screen:

- **There is one breakpoint ladder and it has two steps: 900px and 720px**
  (`tests/test_layout_ladder.py`). 900 is where a split becomes a stack; 720 is the phone.
  `global.css` stepped `--gutter` at exactly those two from the beginning and the pages did
  not — they collapsed at 900, 1000, 820, 700, 640, 560 and 540, so a tablet at 960px got
  `JobDetail`'s single column *and* `JobList`'s six columns at once, and `PrintabilityCard`
  held three 24px figures side by side for 180px after the page around it had folded. **375px
  is a test viewport, not a step**: the phone layout is whatever 720 produced, and a rule that
  seems to want its own width at 375 belongs at 720. A third step is a scene that folds where
  nothing else does, which is found on a device rather than in a diff — hence the test, and
  its `EXCEPTIONS` table wanting a reason rather than an entry.
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

**The camera is ten lines of the fit photo** (`components/FitPhotoInput.tsx`).
`capture="environment"` on an `<input type="file" accept="image/jpeg,image/png,image/webp">`
opens the rear camera directly on a phone and degrades to a file picker on a desktop —
no `getUserMedia`, no preview canvas, no permission dialog to explain, no dependency.
The input is visually hidden behind an ordinary button rather than `display: none`, which
keeps the keyboard path intact.

Three decisions around it. **The upload is its own request, fired on selection**, not
carried with the verdict: the verdict stays one tap, and the phone that walked out of
Wi-Fi range beside the printer never blocks the answer that matters more. **The
acknowledgement is a local object URL**, created from the picked `File` and revoked on
unmount, so it does not wait for a round trip back over the connection that just carried
the bytes up — a never-revoked object URL keeps a several-megabyte photo alive for the
life of the document. And the control is mounted **twice**: in `OutcomeCard`, beside the
verdicts in the app-shell banner, and in `JobDetail`'s own **Fit photo** panel, where the
stored image is shown — through `useAuthedObjectUrl`, because the browser attaches none
of our headers to an `<img src>`, and asked for only when the row says `has_fit_photo`,
so `/photo` is not a 404 in the network log of every job page anyone opens.

That panel appears on a job that **has** a photo *or* on any finished job whose verdict
has been given, which is the case that would otherwise be lost: answering "it fits" in
the banner dismisses the card, and with it the only camera in the app — while the part
is still on the bed for the hour in which someone actually thinks to photograph it. A
job still awaiting its verdict is excluded, because the "Does it fit?" panel above it
already carries the control and a second, empty panel underneath would read as a second
question.

**It added no `@media` rule.** 375 px is whatever the 720 px step produced, which is the
ladder below; the one figure the component states for the phone is a 44 px minimum height
on its button, which is a touch target and not a breakpoint.

**The app is installable, and the service worker is an allowlist** (`web/src/sw.ts`,
`web/public/manifest.webmanifest`). Every route but `GET /health` and the bundle is
authenticated with one shared secret held in the page's `localStorage`; a worker cannot
read it and must never need to, because a worker that answered `/jobs/{id}` from a cache
would serve one person's job record to whoever next opened the app on that device, and one
that replayed a `POST` would dispatch a print. So the worker handles navigations
(network-first, cached shell as the fallback), `/assets/*` and an **enumerated** list of
root files, and declines everything else *by not listing it* — it returns from `fetch`
without calling `respondWith`, which hands the request back to the browser untouched.
`/jobs`, `/ws`, `/config` and every prefix added after the file was written therefore reach
the network exactly as they would with no worker installed. The list is enumerated rather
than prefixed because `/` is shared with the API: "anything at the root that looks static"
is one endpoint away from caching `/health`. `tests/test_pwa_shell.py` holds the worker's
set and `vite.config.ts`'s proxy prefixes apart, and fails when they intersect.

`/health` gets in one other way, and the navigation path has to say no to it twice. A
person who types `/health` into the address bar makes a request whose `mode` is `navigate`
and whose response is `200` — so "cache an OK navigation as the shell" would replace the
shell with `{"status": "ok"}`, and every offline load afterwards would open to that JSON
until the next successful navigation repaired it. The worker therefore caches a navigation
only when its `Content-Type` is `text/html`: a page and a route a person happened to
navigate to are not distinguishable by status or by mode, only by what came back.

Four smaller facts hang off that one. The worker is a **second Rollup input** emitted as
an unhashed `/sw.js`, not a hand-written file in `public/`: a worker's scope is the
directory it is served from, so `assets/sw-a1b2c3.js` would control `/assets/` and nothing
else — and as a build input `tsc -b` checks the one file that can brick the app for a
returning visitor. Its cache name carries a **build id** (`__SW_BUILD__`) so `activate`
deletes every other cache; without it a deploy leaves the previous shell installed and the
cure is a person unregistering a worker they cannot see. Registration is guarded by
`import.meta.env.PROD`, because a cached shell in front of `npm run dev` is a dev server
whose edits stop appearing. And **no server route was added**: the `@public` SPA catch-all
already serves anything in `web/dist`, so there is no third `@public` exemption — only
`mimetypes.add_type("application/manifest+json", ".webmanifest")` beside `DIST_DIR`,
because CPython learned that extension in 3.11 and the server image is 3.10, where the
guess is `None`, Starlette falls back to `text/plain` and Safari — unlike Chrome — declines
to install.

Installing is offered rather than nagged: an **Install section in Printer setup**
(`hooks/useInstallPrompt.ts`), the `beforeinstallprompt` button on Chromium and the
Share → Add to Home Screen sentence on iOS, hidden under `display-mode: standalone`. No
banner. One consequence is worth knowing before it is reported as a bug: **an iOS
standalone window has its own `localStorage`, so the API token is entered once more there**
than in Safari.

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

**A job directory is created at its first write, not at the start of the run**
(`pipeline._ensure_outputs_dir`). Choosing the directory and creating it used to be
one statement, so every run that died before Phase 2 produced anything — a compose
mount error, a spec the archetype refuses, a killed container — left one behind, and
nothing revisits or prunes those: 93 directories on one dev machine, 57 of them empty,
and no way to tell from a listing which of the other 36 held a mesh. Removing the
directory on the way out cannot cover it, because a SIGKILLed container runs no
handler; not creating it can. Most writers already did their own
`parent.mkdir` — `Engineer.export_mesh`, `SculptorBackend.postprocess`,
`CuraSlicer.slice`, `_install_dev_asset` — so the helper is for the four writes
`pipeline.py` performs directly (the blueprint snapshot, the compiled spec's
artifacts, the printability report and its failure envelope). The blueprint gate's
deliberate pre-creation is untouched and must stay: it writes a snapshot into
`data/outputs/{job_id}` before Phase 2, and `_job_outputs_dir`'s snapshot-only branch
is what stops that from claiming the plain namespace.

**`python -m pythonsrc.outputs` (`make outputs`) is the disk-side index, and
`--prune` (`make clean-outputs`) is the broom.** It is **stdlib-only and reads no
database**, which is the point rather than an economy: the directories a person cannot
account for are the ones left by runs that never wrote a telemetry row, so
`telemetry/trace.py --list` — which opens a READ ONLY session against PostgreSQL —
cannot answer for exactly that population. `--prune` removes **empty directories
only**; `--days N` additionally removes job directories older than N days, prints
every path before deleting, and **exempts a directory holding only the gate's
blueprint snapshot**, because a job can sit parked indefinitely and that image is what
a person is being asked to approve. `remove()` refuses any path that is not a direct,
non-symlink child of the root — `DS_OUTPUTS_DIR` and `--root` are both caller-supplied,
and the age mode deletes real meshes. `docs/README-docker.md` §13 is the table of what
`data/` holds and what is safe to delete; `tests/test_output_directories.py` binds all
of it, including a source-level guard that no second `outputs_dir.mkdir` reappears in
`pipeline.py` — re-adding one is invisible in a diff and the only symptom is a
directory nobody looks at.

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
`licenses/` and commits it, on the 1st and the 15th, on a pull request that touches a
dependency manifest, and on demand. Not on every merge: two amd64 image builds to
rewrite a timestamp was the largest single consumer of this repository's CI minutes.
What it runs: `pip-licenses` **inside the built images** (the requirements files are
not what ships — `pipeline.Dockerfile` installs `diffusers` from git HEAD and
`server.Dockerfile` pins nothing at all), `license-checker` over the web app's
production tree, and `syft` SBOMs, which are the only thing that can see `cura-engine`
arriving as an AGPL-3.0 apt package.
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
  re-deriving the same list every run. The block between the `generated:` markers is
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