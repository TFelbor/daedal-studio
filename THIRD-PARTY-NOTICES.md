# Third-Party Notices

Prompt2Print (p2p-mesh) is distributed under the Apache License 2.0 (see
[`LICENSE`](LICENSE)). It bundles, links, or invokes the third-party components
listed below, each under its own licence.

This file exists to satisfy the attribution and source-offer obligations those
licences impose. It is reviewed whenever a dependency is added or bumped.

Last reviewed: 2026-08-20.

---

## 1. Copyleft components — invoked as separate programs

Both components below are licensed under the **GNU Affero General Public
License v3 (AGPL-3.0)**. Neither is linked into the Prompt2Print codebase.
Each runs as a **separate program** communicating over a process or network
boundary, so Prompt2Print is not a derivative work of either.

This separation is architectural and load-bearing. It must be preserved:

> **Do not link, embed, import, or statically compile CuraEngine or OctoPrint
> into Prompt2Print code.** Communicate only via CLI subprocess or HTTP/socket.
> Linking either one in-process would place the entire pipeline under AGPL-3.0.

### CuraEngine

| | |
|---|---|
| Licence | AGPL-3.0 |
| Upstream | https://github.com/Ultimaker/CuraEngine |
| Copyright | Ultimaker B.V. and contributors |
| How used | Invoked as an unmodified CLI subprocess by `pythonsrc/slicer.py` |
| Modified? | No |
| Distributed? | Yes — installed via `apt` into the Phase 4 and pipeline Docker images |

### OctoPrint

| | |
|---|---|
| Licence | AGPL-3.0 |
| Upstream | https://github.com/OctoPrint/OctoPrint |
| Copyright | Gina Häußge and contributors |
| How used | Runs as a separate container; contacted over its REST API and SockJS socket |
| Modified? | No |
| Distributed? | Yes — the `octoprint/octoprint` image is referenced by `infra/docker-compose.yml` |

### Written offer for source code

Both components are distributed **unmodified**. Their complete corresponding
source is available from the upstream repositories linked above, at the exact
versions our images install.

For a copy of the corresponding source of either component as distributed in a
Prompt2Print image, contact **legal@prompt2print.xyz**. We will supply it for no
more than the cost of distribution, as AGPL-3.0 §6 permits.

### Weak copyleft — file-level

None currently. `torchmcubes` (MPL-2.0) was removed with TripoSR — see
[§3 Removed components](#3-removed-components).

---

## 2. Permissive components

No source-disclosure obligation. Attribution is required and is satisfied by
this file.

### Vendored source

None currently. Phase 2's model source (TRELLIS.2) is **not** vendored: it is
cloned at image build time by
[`infra/docker/trellis2-worker.Dockerfile`](infra/docker/trellis2-worker.Dockerfile),
or located on a developer machine via `$TRELLIS2_REPO_PATH`. The upstream repo is
not pip-installable, which is the only reason it is a checkout rather than a
dependency.

### Models and weights

Model weights carry licences **independent of** the libraries that load them.
This is the most common place for a licence problem to enter unnoticed.

| Model | Licence | Commercial use | Notes |
|---|---|---|---|
| FLUX.2-klein-4B (`black-forest-labs/FLUX.2-klein-4B`) | Apache-2.0 | Yes | Black Forest Labs' openly-licensed variant |
| TRELLIS.2-4B (`microsoft/TRELLIS.2-4B`) | MIT | Yes | © Microsoft Corporation. Phase 2's image→3D model |
| BiRefNet (`ZhengPeng7/BiRefNet`) | MIT | Yes | Background removal inside TRELLIS.2's `preprocess_image` |

> **BiRefNet is loaded with `trust_remote_code=True`.** That is upstream
> TRELLIS.2's own call (`trellis2/pipelines/rembg/BiRefNet.py`), and it executes
> modelling code fetched from the Hugging Face Hub at load time. The licence is
> MIT and the repo is named explicitly rather than resolved from a shifting
> default, so there is no licence hazard — but it is remote code execution on the
> GPU worker, and pinning a revision is worth doing before any untrusted
> deployment.

> **The rembg / u2net pin is gone because rembg is gone.** Phase 2 previously used
> `rembg` for TripoSR's background cut-out, which required pinning
> `rembg==2.0.69` *and* naming `u2net` explicitly, because newer rembg releases
> default to BRIA RMBG-2.0 — a model requiring a paid commercial agreement.
> TRELLIS.2 does its own background removal with an explicitly named model, so
> that hazard no longer exists in this codebase. **Do not reintroduce `rembg`
> without restoring both controls.**

### Phase 2 GPU worker — TRELLIS.2 and its CUDA stack

These are installed **only** into
[`infra/docker/trellis2-worker.Dockerfile`](infra/docker/trellis2-worker.Dockerfile).
None of them is present in the CPU images, and none is imported by the sculptor
client (`pythonsrc/sculptors/remote.py`).

| Component | Licence | Notes |
|---|---|---|
| TRELLIS.2 | MIT | © Microsoft Corporation. Cloned at build time, unmodified |
| o-voxel | MIT | Ships inside the TRELLIS.2 repo; covered by its LICENCE |
| Eigen (vendored by o-voxel) | MPL-2.0 | Core module only, unmodified, header-only |
| CuMesh | MIT | https://github.com/JeffreyXiang/CuMesh |
| FlexGEMM | MIT | https://github.com/JeffreyXiang/FlexGEMM |
| flash-attn | BSD-3-Clause | https://github.com/Dao-AILab/flash-attention |
| utils3d | MIT | Pinned to a commit, per upstream's `setup.sh` |

#### nvdiffrast and nvdiffrec must not be installed

> Upstream TRELLIS.2's documented install line includes `--nvdiffrast
> --nvdiffrec`. **Do not use it as-is.** Both packages are published under the
> **NVIDIA Source Code License**, which permits non-commercial research use only.
> Installing either into a Prompt2Print image would put a non-commercial
> restriction on a distributed artifact and make this project's Apache-2.0 grant
> incoherent — the same class of mistake as `pymeshfix` (§3).

This project avoids them structurally rather than by remembering not to type a
flag:

- **Phase 2 never rasterizes.** `Trellis2Backend` drives the pipeline stages
  itself and stops after shape decoding, so it never calls
  `o_voxel.postprocess.to_glb()`, which is the only thing on the image→3D path
  that needs a rasterizer. `trellis2/pipelines/__init__.py` resolves submodules
  lazily, so importing `Trellis2ImageTo3DPipeline` does not pull in the texturing
  pipeline or the renderers either.
- **The worker image does not install them.** Its `pip install` lines are
  explicit, and the renderer packages are absent.

An FDM printer consumes geometry, so nothing is lost. If a future feature needs
textured output — a preview render, a GLB export — the renderer must come from a
permissively licensed backend (PyTorch3D, BSD-3-Clause, is the substitution
upstream's structure accommodates), **not** from nvdiffrast. Adding one also
reopens the question for the CPU images, which currently need no rasterizer at all.

### Python libraries

| Component | Licence |
|---|---|
| manifold3d | Apache-2.0 |
| trimesh | MIT |
| fast-simplification | MIT |
| xatlas | MIT |
| moderngl | MIT |
| mflux | MIT |
| PyTorch, NumPy, SciPy, scikit-image | BSD-3-Clause |
| diffusers, transformers, huggingface_hub, safetensors, tokenizers | Apache-2.0 |
| opencv-python, opencv-python-headless | Apache-2.0 |
| FastAPI, uvicorn, pydantic, starlette | MIT / BSD-3-Clause |
| aiohttp, websockets, httpx, requests | Apache-2.0 / BSD-3-Clause |
| cryptography | Apache-2.0 OR BSD-3-Clause |
| paho-mqtt | EPL-2.0 OR BSD-3-Clause |
| numba, llvmlite | BSD-2-Clause |
| Pillow | MIT-CMU |

### Frontend (`web/`)

All production dependencies are permissive — MIT, ISC, Apache-2.0 or
BSD-3-Clause. No copyleft. Principal packages: React and React DOM (MIT),
react-router-dom (MIT), three (MIT), recharts (MIT), gcode-preview (MIT),
lucide-react (ISC), Vite (MIT), TypeScript (Apache-2.0).

---

## 3. Removed components

**pymeshfix** — removed 2026-08-20, replaced by `manifold3d` (Apache-2.0).

pymeshfix wraps MeshFix (M. Attene, IMATI-GE/CNR, 2010) and is published under
GPL-3.0 / AGPL-3.0 with an explicit additional condition: commercial use
requires a separately negotiated licensing contract with the authors and
IMATI-GE/CNR. It was previously imported in-process by `pythonsrc/engineer.py`,
which would have made the pipeline a derivative work of AGPL code and left
Prompt2Print's own Apache-2.0 grant incoherent.

**Do not reintroduce pymeshfix.** The replacement in `Engineer.repair_mesh`
composes trimesh (surface closing, MIT) with manifold3d (manifoldness guarantee
and boolean union, Apache-2.0).

**TripoSR** — removed 2026-08-20, replaced by TRELLIS.2-4B (MIT).

Removed for capability, not licence: TripoSR (MIT, © Tripo AI & Stability AI) was
compliant and is simply superseded. Its removal took three dependencies with it,
each of which had carried an obligation of its own:

| Gone with it | Was | Why it existed |
|---|---|---|
| `pythonsrc/tsr/` | MIT, vendored with local MPS patches | TripoSR's model source |
| `torchmcubes` | **MPL-2.0** (file-level copyleft) | Marching-cubes iso-surface extraction |
| `rembg` + `u2net` weights | MIT + Apache-2.0, both pinned defensively | Background cut-out before reconstruction |

The `torchmcubes` removal retires this project's only weak-copyleft dependency.
The `rembg` removal retires the pin documented in §2: TRELLIS.2 names its own
background-removal model, so the "default model silently becomes a paid one"
hazard no longer applies here.

---

## Maintaining this file

When adding or bumping a dependency:

1. Check the licence of the package **and**, separately, of any model weights
   it downloads at runtime.
2. Reject AGPL/GPL for anything that would be imported in-process.
3. Reject "source-available, non-commercial" licences outright — the NVIDIA
   Source Code License is the live example. These are easy to miss because GitHub
   reports them as `Other` rather than as copyleft.
4. Pin anything whose *default behaviour* carries a licence implication.
5. Note which image a dependency lands in. The GPU worker and the CPU images have
   different dependency sets on purpose; a package added to the wrong one changes
   what is distributed.
6. Add it to the correct table above and update the review date.
