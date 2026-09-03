# ARCHITECTURE — the phase-by-phase map

One prompt becomes one physical part. This file is the **factual index** of that chain:
what runs each phase, which version is pinned and where, which Hugging Face repo the
weights come from, which hardware it can run on, and what it has been measured to cost.

**Direction (committed 2026-08-31):** the product is parametric — prompt → structured
spec → compiled geometry → Phases 3–5 (see `docs/PRD_daedal_tcg_organizers.md` and
`docs/ds-mvp-roadmap.md` §0.1+). Phases 1–2 below are the **generative branch**: fully
built, benched off the critical path, returning as the engine behind decorative
personalization (PRD F13/F14). Phases 3–5 are shared by both paths, unchanged.

It exists to be read *first* — by a person new to the repo, and by the recurring audit
routines, which otherwise infer the stack from `requirements-base.txt` and guess at the
numbers. [`CLAUDE.md`](CLAUDE.md) explains *why* each design decision is what it is and
is the authority when the two disagree; this file is the shape of the thing.

**Every number below names where it came from.** A figure nobody has measured is written
`not measured` rather than estimated — an "expected gain" computed against an invented
baseline is worse than one computed against nothing.

---

## The chain

**Product path (in build — `pythonsrc/organizer/` does not exist yet):**

```
prompt ──▶ Extract (LLM → spec) ──▶ [clarify loop: ≤3 questions] ──▶ Compile (archetype → mesh)
                                                │
                       exact.stl ──▶ P3 Engineer (validate, seat, NEVER rescale) ──▶ [printability gate]
                                                │
                              part.gcode ◀── P4 Slicer
                                                │
                                  [dispatch gate: a person confirms]
                                                │
                                          P5 Operator ──▶ printer ──▶ telemetry ──▶ fit verdict
```

Geometry is arithmetic on CPU — sub-second, exact by construction. The only network
call is one LLM extraction request (~€0,002); nothing on this path needs a GPU. Entry
is the seam that already exists: `--skip-visualizer --skip-sculptor --mesh <path>
--no-scale`. **Nothing on this path is measured yet.**

**Generative branch (benched — everything below this line is built and measured):**

```
prompt ──▶ P1 Visualizer ──▶ blueprint.png ──▶ [IP screen] ──▶ [blueprint gate: a person looks]
                                                                        │
                                            raw_mesh ◀── P2 Sculptor ◀──┘
                                                │
                     repaired.stl ◀── P3 Engineer ──▶ [printability gate]
                                                │
                              part.gcode ◀── P4 Slicer
                                                │
                                  [dispatch gate: a person confirms]
                                                │
                                          P5 Operator ──▶ printer ──▶ telemetry
```

Phases 1 and 3–5 run on hardware you own. **Phase 2 is the exception** and is the only
part of the pipeline that can cost money per job.

### The geometry kernel (PRD §9.1, answered)

**`manifold3d` now; `build123d`/OCCT only when an archetype needs true fillets or
chamfers.** `manifold3d` 3.5.2 is already a hard Apache-2.0 dependency (it does the CSG
union in `engineer.repair_mesh` and backs `printability.self_intersections`), every v1
archetype is axis-aligned box CSG inside its envelope, and choosing it costs no new
dependency and no new licence review. build123d is Apache-2.0 but wraps **OCCT**
(LGPL-2.1 with an additional exception — commercial use permitted, prominent notice
required): adopting it requires recording OCCT in
`licence_policy.REVIEWED_WEAK_COPYLEFT`, adding a "Built with Open CASCADE Technology"
notice alongside the DINOv3 one, and letting the licence workflow sweep its wheel's
dependency tree. Full reasoning: `docs/pivot-brief-tcg-organizers.md` §6,
`docs/ds-mvp-roadmap.md` §7A.

---

## Phase 1 — Visualizer: text → blueprint image

| | |
|---|---|
| **Code** | `pythonsrc/visualizer.py`, prompt wrapper in `pythonsrc/blueprint_spec.py` |
| **Model** | `black-forest-labs/FLUX.2-klein-4B` (`Visualizer.MODEL_ID`) |
| **Weights licence** | Apache-2.0 — commercial use permitted, no output restriction |
| **Library** | `diffusers` — **pinned two ways**: `diffusers==0.37.0` in `requirements-base.txt`, git `HEAD` in `infra/docker/pipeline.Dockerfile` (Flux2KleinPipeline was not in a release when written) |
| **Also** | `transformers` (5.1.0 pinned / `>=4.45.0` in the image), `accelerate`, `safetensors`, `sentencepiece` |
| **Torch** | 2.7.1 + torchvision 0.22.1 (macOS and the CPU image alike) |
| **Hardware** | `mps` on Apple Silicon, `cuda` if visible, else `cpu` — chosen by `visualizer.get_device()` |
| **Sampling** | 1024×1024, `num_inference_steps=2`, `guidance_scale=3.5` |
| **Note** | The checkpoint is **distilled**, so upstream's classifier-free-guidance branch never runs and the recorded `guidance_scale` is inert. Every constraint is therefore phrased positively — there is no negative prompt. |

**Measured:** ~30 s native on Apple Silicon MPS; ~84 min in the amd64 CPU image
(`README.md`, "Phase 1: Visualizer"). The MPS-native path is the primary Mac workflow
for exactly that reason (`make phase1-native`).

### Screening, between Phase 1 and Phase 2

| | |
|---|---|
| **Code** | `pythonsrc/ip_screen.py` (prompt), `pythonsrc/ip_screen_image.py` (render) |
| **Model** | `google/siglip-base-patch16-224` — Apache-2.0, no out-of-scope clause, native in the pinned `transformers` (no new dependency, no `trust_remote_code`) |
| **Denied** | `openai/clip-vit-*` — repo tag says MIT, model card puts *all* deployed use out of scope |
| **Hardware** | CPU or MPS; never imported by the api-server image, which has no torch |

**Measured:** one ViT-B/16 forward pass ≈ 17 GFLOPs; text embeddings computed once and
cached; ~800 MB added to the pipeline image; no per-call fee. It runs *before* Phase 2,
so every block avoids one EUR 0,32 hosted generation.

---

## Phase 2 — Sculptor: image → 3D geometry

The same model behind three deployments. Which one runs is resolved by
`sculptors.resolve_backend_name`: `remote` if `$DS_SCULPTOR_REMOTE_URL` is set, else
`trellis2` if CUDA is visible, else `pixazo` if `$PIXAZO_API_KEY` is set, else **raise**.
There is deliberately no CPU path.

| | |
|---|---|
| **Model** | `microsoft/TRELLIS.2-4B` — MIT, no output restriction. **The mesh is yours**, which is what makes this phase saleable |
| **Source** | Upstream is not pip-installable; cloned separately and found via `$TRELLIS2_REPO_PATH` |
| **Image conditioner** | `facebook/dinov3-vitl16-pretrain-lvd1689m` — DINOv3 License. Commercial use permitted **with** attribution ("Built with DINOv3"), acceptable-use and trade-control terms, and no redistribution of weights. On the shape path; cannot be avoided |
| **Background matte** | `ZhengPeng7/BiRefNet` (MIT), substituted by `pythonsrc/sculptors/background.py` for the checkpoint's configured `briaai/RMBG-2.0` (CC BY-NC 4.0) |
| **Never installed** | `nvdiffrast`, `nvdiffrec` — NVIDIA Source Code License, non-commercial research only. Avoided structurally: the shape-only path never rasterizes |
| **Defaults** | `pipeline_type=1024_cascade`, `gpu_simplify_target=200_000`, `DEFAULT_TARGET_FACES=100_000`, `smooth=0` |

| Backend | Where it runs | Stack | Cost | Up axis |
|---|---|---|---|---|
| `trellis2` | In-process on a CUDA host | torch 2.6.0+cu124, flash-attn 2.7.3, CuMesh, FlexGEMM, o-voxel; base image `nvidia/cuda:12.4.1-devel-ubuntu22.04` | — | `z` |
| `remote` | `services/trellis2_worker/` over HTTP | Same, held resident on the GPU; returns **raw** geometry | — | from `X-DS-Up-Axis` |
| `pixazo` | Pixazo's hosted `trellis-2-image-to-3d` | Someone else's deployment | **EUR 0,32 / generation** | `y` (returns GLB, and glTF is Y-up) |

**Hardware floor:** NVIDIA GPU, ~24 GB VRAM, four compiled CUDA extensions with no CPU
kernels. `TORCH_CUDA_ARCH_LIST` must match the deployment GPU. Not runnable in this
project's amd64 CPU images and not on Apple Silicon — on a Mac, `pixazo` is the only
option.

**Measured:** ~220 s per reconstruction (`CLAUDE.md`, Sculptor); raw output ~195k faces,
GPU-simplified to 200k before leaving the GPU and CPU-decimated to 100k. Worker image
first build: 30–60 min (the CUDA extensions compile from source). Cascade-vs-native
resolution quality: **not measured**.

---

## Phase 2 — Compiler: spec → geometry (parametric path)

The pivot's engine (`docs/PRD_daedal_tcg_organizers.md` F5; roadmap §0.3 Phase 1). Runs
under the same phase number and banners as the sculptor; `pipeline.py --spec` selects it
and Phases 1–2 above are then not run at all.

| | |
|---|---|
| **Code** | `pythonsrc/organizer/` — `spec.py` (schema), `dimensions.py` (seed numbers), `archetypes/deck_box.py` (v1) |
| **Model** | None. Deterministic CSG; the same spec compiles to the same STL byte for byte |
| **Kernel** | `manifold3d` 3.5.2 (Apache-2.0) — the decision recorded under *The geometry kernel* above, exercised |
| **Recorded as** | `generation_model = organizer/deck_box`, `generation_model_version = 1`, `generation_backend = local`, spec sha256 in `generation_params` |
| **Licence delta** | None — no new dependency, no weights |
| **Measured** | Compile of a 100-card deck box: 72 faces, 0.1 s in the pipeline image. Every designed feature within 0.05 mm on the compiled mesh and on Phase 3's output (`tests/test_deck_box.py`; 19/19 on the container run of 2026-09-03). Across the envelope — 405 specs, counts 15–160 × three sleevings × walls 2.6–4.0 × clearances 0.1–0.35 × lid engagement 8–30 mm — the largest error on the exported, reloaded STL is float32 noise, ~5 µm (`tests/test_organizer_dimensional_accuracy.py`). Gate 92.9 / `risky`, the one warn being the wall check's quantisation on a 158 mm plate |
| **Asserted, not repaired** | A spec run's Phase 3 is `Engineer.process(repair_mode="assert")`: watertight, no boundary or non-manifold edges, consistent winding, kernel acceptance — refused with `MeshAssertionError` rather than fixed — then every designed feature measured on the engineered mesh at 0,05 mm (`dimension_report.json`, `repair_report["dimension_check"]`); a miss fails Phase 3. `repair_method="asserted"` on the row, `size_source="spec"` from `POST /jobs` |
| **Not yet** | Envelope sweep across *every* archetype (there is one), the spec on `GET /jobs/{id}` for the UI, dimension KB, LLM extraction |

## Phase 3 — Engineer: repair or assert, scale, orient, hollow

| | |
|---|---|
| **Code** | `pythonsrc/engineer.py` |
| **Libraries** | `trimesh` 4.11.2 pinned, 5.0.0 resolved in the image (MIT) closes the surface; `manifold3d` 3.5.2 (Apache-2.0) guarantees the result and does the boolean union; `fast-simplification` 0.1.13; `scipy` 1.15.3; `numpy` 2.2.6 |
| **Removed** | `pymeshfix` — wraps MeshFix, which requires a negotiated contract for commercial use |
| **Hardware** | CPU only. Runs anywhere, including in the amd64 images |
| **Knobs** | `--target-mm` (50.0), `--scale-axis` (`height`), `--faces`, `--hollow`, `VOXEL_REMESH_RESOLUTION=128`, `MAX_CLOSE_ROUNDS=8` |

**Measured** (all from `CLAUDE.md`, Mesh repair):

| Operation | Figure | Conditions |
|---|---|---|
| Full repair | ~6 s | at the 100k-face budget, against Phase 2's 220 s |
| Repair, after dropping the redundant winding pass | 20 s → 0.5 s | 82k-face mesh |
| Same change | 63 s → 2 s | 328k-face mesh |
| Edge counting (int64 key vs `np.unique(axis=0)`) | 0.216 s → 0.014 s | 80k-face mesh, once per round |
| Non-manifold repair strategy (connectivity vs area ranking) | 198 vs 440 faces dropped; converged in 1 round vs never | 80k-face sphere with 200 fins |

### Printability gate (between Phase 3 and Phase 4)

`pythonsrc/printability.py` — 11 deterministic checks, weighted 0–100 score, verdict
`ready` / `risky` / `unprintable`. Backed by `manifold3d` for the self-intersection
test. Wall thickness is measured by voxelising and taking a distance transform, **not**
by ray casting, because `trimesh.proximity.thickness` needs `rtree`. (`trimesh[easy]`
does install `rtree` in the CPU images — so the measurement is independent of it by
choice, not by absence.) Advisory: a low score blocks nothing unless
`--min-printability` is passed. **Runtime: not measured.**

---

## Phase 4 — Slicer: mesh → G-code

| | |
|---|---|
| **Code** | `pythonsrc/slicer.py` (subprocess wrapper), `pythonsrc/gcode_stats.py` (E-axis parser) |
| **Engine** | **CuraEngine**, Ubuntu `cura-engine` apt package (universe). Version observed in the image: 4.13 |
| **Licence** | AGPL-3.0 — **CLI subprocess only, never linked**. All FOSS slicers are AGPL/GPL, so isolation is the design, not a workaround |
| **Profiles** | `pythonsrc/profiles/*.json`, translated into `-s` overrides and validated against `fdmprinter.def.json` |
| **Hardware** | CPU only, amd64 only (the apt package exists for no other architecture — which is why every image is `linux/amd64`) |

**Measured:** brim line counts on CuraEngine 4.13 — `brim_line_count=5` → 119 adhesion
moves, `=20` → 907, while `brim_width=2` changed nothing (it is a frontend setting).
Profile translation verified by G-code: `M104 S200`/`M140 S55` under Anycubic Mega
against `M104 S210`/`M140 S60` under Ender 3, where the two files used to be
byte-identical. **Slice wall-clock: not measured** (recorded per job in
`slice_duration_s`, so it is queryable from the telemetry database).

---

## Phase 5 — Operator: G-code → printer

| Firmware | Transport | Library | Licence |
|---|---|---|---|
| OctoPrint | HTTP + SockJS WebSocket | `requests`, `websockets` | OctoPrint is AGPL-3.0 — **HTTP client only, never imported** |
| Klipper / Moonraker | JSON-RPC over WebSocket | `websockets` | — |
| Bambu | MQTT | `paho-mqtt` 2.1.0 | — |

Phase 5 does not follow Phase 4 for a job submitted from the web app: the pipeline stops
after the slicer and waits for a person to confirm the target printer
(`POST /jobs/{id}/print-dispatch`). `--print --start-print` dispatch immediately, which
is what the CLI and automation use.

**End-to-end latency: not measured.** A published figure is still an open item in
`README.md`.

---

## Server, storage and UI

| | |
|---|---|
| **API** | FastAPI + uvicorn (`server/app.py`), WebSocket phase/telemetry fan-out |
| **Database** | SQLite at `~/.ds-mvp/telemetry.db` — **one file in every execution mode**, reached from containers through a bind mount. WAL is deliberately off |
| **Config** | Fernet-encrypted key-value store in the same database; key at `.config_key` |
| **Frontend** | React 19.2.6, Vite 8, TypeScript ~6.0.2, `three` 0.184, `recharts` 3.8.1, `react-router-dom` 7.17, `gcode-preview` 2.18 |
| **Served** | `web/dist/` is built into the api-server image and served by a catch-all route |

---

## Images

| Image | Base | Contains | Built in CI |
|---|---|---|---|
| `ds-base` | `ubuntu:22.04` | Python 3.10, mesh/OpenGL system libs | yes |
| `ds-mvp-pipeline` | `ds-base` | All phases: torch 2.7.1 CPU, diffusers HEAD, trimesh, manifold3d, `cura-engine` | yes |
| `ds-api-server` | `python:3.10-slim` + `node:20-alpine` builder | FastAPI stack (**unpinned** `pip install` list), Docker CLI, `web/dist` | yes |
| `ds-trellis2-worker` | `nvidia/cuda:12.4.1-devel-ubuntu22.04` | torch 2.6.0+cu124, flash-attn, CuMesh, FlexGEMM, o-voxel, TRELLIS.2 | **no** — needs a GPU arch to compile against |
| `octoprint/octoprint` | upstream | Virtual-printer simulator on port 5001 | n/a |

Everything except the worker is pinned `linux/amd64`, because `cura-engine` is an amd64
apt package. On Apple Silicon, Docker Desktop emulates.

---

## Pin conflicts worth knowing

These are facts, not bugs to fix in passing — but an audit or an upgrade plan that
misses them will draw the wrong conclusion about what is installed.

| Package | `requirements-base.txt` | What the image installs |
|---|---|---|
| `diffusers` | `==0.37.0` | `git+https://github.com/huggingface/diffusers.git` (unpinned HEAD) |
| `transformers` | `==5.1.0` | `>=4.45.0` |
| `accelerate` | `==1.12.0` | `>=0.33.0` |
| `trimesh` | `==4.11.2` | `trimesh[easy]>=4.0.0` — **resolved to 5.0.0** in the image built 2026-08-27, a major version ahead of the pin |
| `manifold3d` | `==3.5.2` | `>=3.0.0` |
| `numpy` | `==2.2.6` | `>=1.24.0` |

Two more shapes worth holding in mind:

* **`requirements.txt` is `-r requirements-mac.txt`.** A plain
  `pip install -r requirements.txt` on Linux tries to install `mflux`/`mlx`.
  Use `requirements-linux.txt`, or the images.
* **`trimesh[all]` was `trimesh[easy]` as of 2026-08-27.** `[all]` includes trimesh's own
  `test-more` extra, which installed `pymeshlab` (GPL-3.0) and `triangle` (LGPL-3.0) into
  both CPU images. `[easy]` still installs `rtree`, which
  `pythonsrc/printability.py`'s comment says is absent — the comment describes a
  deliberate independence from it, not the contents of the image.
* **`infra/docker/server.Dockerfile` pins nothing.** Its `pip install` list appears in no
  requirements file, which is why the api-server tree is captured from the built image
  (`licenses/python-api-server.json`) rather than read off a manifest.

---

## Re-measuring

```bash
# Phase 1, native MPS
time make phase1-native PROMPT="a ceramic vase"

# Phases 3-5 on an existing mesh, no GPU needed
docker compose -f infra/docker-compose.yml run --rm pipeline-runner \
  python pythonsrc/pipeline.py "a vase" --skip-visualizer --skip-sculptor --mesh data/outputs/raw_mesh.obj

# Phase 2 on a CUDA host, once the worker is up
make worker-health && time curl -F image=@data/inputs/blueprint.png http://localhost:8100/sculpt -o /tmp/mesh.glb
```

Per-job figures are already captured in the telemetry database and do not need
re-running: `blueprint_duration_s`, `generation_duration_s`, `generation_cost_eur`,
`slice_duration_s`, `estimated_print_time_s`, `print_duration_s`, plus
`repair_report` for Phase 3. `python -m pythonsrc.telemetry.trace --latest` shows one
job's row as the writes that filled it.

---

## Companion files

| File | What it holds |
|---|---|
| [`CLAUDE.md`](CLAUDE.md) | Why every decision is what it is. The authority on intent |
| [`THIRD-PARTY-NOTICES.md`](THIRD-PARTY-NOTICES.md) | Per-component licence reasoning and obligations |
| [`licenses/`](licenses/README.md) | The resolved dependency tree, regenerated by CI |
| [`docs/audits/`](docs/audits/README.md) | Dated audit runs, with deltas |
| [`pythonsrc/licence_policy.py`](pythonsrc/licence_policy.py) | What a licence string means, in code |
