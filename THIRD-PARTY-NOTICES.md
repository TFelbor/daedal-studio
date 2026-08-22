# Third-Party Notices

Prompt2Print (p2p-mesh) is distributed under the Apache License 2.0 (see
[`LICENSE`](LICENSE)). It bundles, links, or invokes the third-party components
listed below, each under its own licence.

This file exists to satisfy the attribution and source-offer obligations those
licences impose. It is reviewed whenever a dependency is added or bumped.

Last reviewed: 2026-08-22.

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
| TRELLIS.2-4B (`microsoft/TRELLIS.2-4B`) | MIT | Yes | © Microsoft Corporation. Phase 2's image→3D model. No restriction on generated output |
| DINOv3 ViT-L/16 (`facebook/dinov3-vitl16-pretrain-lvd1689m`) | [DINOv3 License](https://ai.meta.com/resources/models-and-libraries/dinov3-license/) | Yes, with conditions | © Meta Platforms. TRELLIS.2's `image_cond_model`. Attribution, Acceptable Use Policy and trade-control terms apply — see below |
| BiRefNet (`ZhengPeng7/BiRefNet`) | MIT | Yes | Background removal. **Substituted by this project** for the checkpoint's configured default — see below |
| ~~BRIA RMBG-2.0 (`briaai/RMBG-2.0`)~~ | CC BY-NC 4.0 | **No** — paid BRIA agreement required | Upstream TRELLIS.2's configured matte model. **Never loaded.** Overridden before construction — see below |
| SigLIP base/16-224 (`google/siglip-base-patch16-224`) | Apache-2.0 | Yes | © Google. Zero-shot screen on the generated blueprint (`pythonsrc/ip_screen_image.py`). Natively supported by `transformers`, so no `trust_remote_code`. Compared image↔**text**: **no reference images of protected characters are stored in this repository** |
| ~~OpenAI CLIP (`openai/clip-vit-*`)~~ | MIT *tag*, but see Notes | **No** | Considered for the blueprint screen and **rejected**. The repository is tagged MIT while its own model card states that *"Any deployed use case of the model — whether commercial or not — is currently out of scope."* Reading the tag is not reading the licence. On the deny list in `ip_screen_image.DENIED_MODEL_REPOS`; construction raises |
| ~~SigLIP 2 (`google/siglip2-*`)~~ | Apache-2.0 | Yes, but unused | Permissively licensed and a candidate for the same role, deferred on a correctness report rather than a licence one — `huggingface/transformers` issue #43994 reports nonsensical `AutoModel`/pipeline output for `siglip2-base-patch16-224`. Revisit when that closes |

#### Built with DINOv3

> This product is **Built with DINOv3**. DINOv3 is © Meta Platforms, Inc. and
> licensed under the [DINOv3
> License](https://ai.meta.com/resources/models-and-libraries/dinov3-license/).

DINOv3 is TRELLIS.2's image conditioning encoder — `image_cond_model` in the
checkpoint's `pipeline.json`, consumed by `pipeline.get_cond()`. It sits on the
shape path, so unlike the rasterizer (§ *nvdiffrast and nvdiffrec*) and the matte
weights (below) it **cannot be structurally avoided**; the model does not work
without it. That is acceptable, because the DINOv3 License **permits commercial
use**. What it requires:

- **Attribution.** "Built with DINOv3" displayed prominently. Carried in this
  file, in `README.md`, and in the application's UI footer
  (`web/src/App.tsx`).
- **Acceptable Use Policy.** No military, warfare, nuclear, espionage or
  weapons-development use, and no reverse-engineering of the underlying
  components.
- **Trade controls.** Use must comply with applicable export-control and
  sanctions regulations.
- **Propagation on redistribution.** Distributing the weights or a derivative of
  them is only permitted under the same agreement, with a copy provided. **Do not
  bake DINOv3 weights into a distributed image** — that converts a use into a
  redistribution and pulls the licence onto the artifact. The weights are fetched
  at run time into a named volume, which is why this stays a use.
- **Acknowledgement in publications** reporting research performed with it.

The repo is **gated**: access is granted per-account after accepting the terms, so
whoever accepted them with the project's `HF_TOKEN` is the licensee of record.

#### The checkpoint's background-removal weights are non-commercial and are overridden

> `microsoft/TRELLIS.2-4B`'s `pipeline.json` configures background removal as:
>
> ```json
> "rembg_model": { "name": "BiRefNet", "args": { "model_name": "briaai/RMBG-2.0" } }
> ```
>
> The **class** is BiRefNet (MIT). The **weights** are BRIA RMBG-2.0, published
> under **CC BY-NC 4.0** — free for non-commercial use only, with commercial use
> requiring a paid agreement with BRIA. Loading them would put a non-commercial
> restriction on the pipeline, exactly as `pymeshfix` did (§3).

This is the `rembg` / u2net hazard returning by a **different route**. The old one
was a library silently changing its default; this one is an upstream config file
naming the encumbered repo outright. The lesson generalises: **an explicitly named
model id is no protection when the id someone else named is the encumbered one.**
Read the id, not the class name.

Phase 2 therefore substitutes MIT BiRefNet weights
([`pythonsrc/sculptors/background.py`](pythonsrc/sculptors/background.py)):

- `permissive_rembg()` rebinds `trellis2.pipelines.rembg.BiRefNet` to
  `PermissiveBiRefNet` for the duration of `Pipeline.from_pretrained`. It must wrap
  the *load*, not follow it: upstream constructs the matte model eagerly, so
  reassigning `pipeline.rembg_model` afterwards would already have downloaded the
  BRIA weights and accepted their gated-repo terms to get there.
- `assert_permissive_matte()` then verifies the loaded pipeline actually holds the
  substitute. It checks the outcome rather than the mechanism, so the day upstream
  stops resolving that config entry through `getattr` the load **fails** instead of
  quietly reverting.
- `NON_COMMERCIAL_MATTE_MODEL_IDS` is a deny-list, enforced by
  [`tests/test_licensing_guards.py`](tests/test_licensing_guards.py).
- This covers the `trellis2` and `remote` backends both — the GPU worker imports
  this same code. It does **not** cover `pixazo`; see *Hosted services*.

> **Our MIT BiRefNet is still loaded with `trust_remote_code=True`**, matching
> upstream's own call. That executes modelling code fetched from the Hugging Face
> Hub at load time. MIT, so no licence hazard — but it is remote code execution on
> the GPU worker. Pin a revision via `$P2P_BIREFNET_MODEL_ID` (`repo@sha`) before
> any untrusted deployment.

> **Do not reintroduce `rembg`** without restoring both of its old controls (a
> version pin *and* an explicitly named permissive model), and **do not remove the
> matte substitution** on the theory that upstream names its model explicitly. It
> does. That is the problem.

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

### Hosted services

Called over HTTPS, never linked or vendored, so they add no licence obligation to
the distributed artifact. Listed because what they *return* enters the pipeline.

| Service | Notes |
|---|---|
| Pixazo `trellis-2-image-to-3d` | Runs TRELLIS.2 (MIT) as a paid endpoint, €0,32 per generation. Returns GLB. No client library is installed — `pythonsrc/sculptors/pixazo.py` uses `requests` against the documented REST API, so the arm's-length rule that governs CuraEngine and OctoPrint applies here by construction |

> **The upstream defaults this project overrides are not overridden on someone
> else's servers.** A hosted TRELLIS.2 endpoint most likely runs the checkpoint as
> shipped, which means BRIA RMBG-2.0 for background removal and DINOv3 for
> conditioning, under *their* licences rather than ours. Running their code is not
> our copyright act, so this is a **contractual** exposure, not a copyright one:
> if a provider is not licensed for what it runs, the loss lands wherever the
> terms of service put it, and standard terms disclaim it. Before the `pixazo`
> backend is used for anything beyond the beta, get written confirmation from the
> provider that its deployment is licensed for commercial use and that generated
> output carries commercial rights, plus an indemnity for third-party IP claims.
> Absent that, keep this backend beta-only. `create_sculptor()` already makes it
> swappable, so that costs nothing but a config change.

> **The blueprint leaves the machine when this backend is used.** `image_url` is
> either a `data:` URI or a public URL, so the prompt's rendered image is uploaded
> to a third party and the resulting mesh is served from their CDN. That is a
> privacy property of the deployment, not a licence one, but it is the reason
> `generation_backend` distinguishes `hosted_api` from `remote_worker`: only one of
> them sends user content off-premises.

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
react-router-dom (MIT), three (MIT), recharts (MIT), gcode-preview (MIT)
and its transitive `lil-gui` (MIT), lucide-react (ISC), Vite (MIT),
TypeScript (Apache-2.0).

`gcode-preview` pins `three@^0.159` while the app is on `0.184`, so npm installs a
second nested copy rather than deduplicating. That is a bundle-size cost, not a
licence one — both copies are MIT — and it is deliberate: deduplicating would run the
previewer against a three.js eleven minors newer than the one it was tested on.

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
The `rembg` removal retires that package's version pin — but **not** the hazard it
was pinned against. TRELLIS.2 names its own background-removal model, and the model
it names *is* BRIA RMBG-2.0. The control moved rather than disappearing: see §2,
*The checkpoint's background-removal weights are non-commercial and are overridden*.

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
