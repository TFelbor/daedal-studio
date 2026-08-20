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

**torchmcubes** — Mozilla Public License 2.0 (MPL-2.0).
Upstream https://github.com/tatsy/torchmcubes, pinned to commit
`3381600ddc3d2e4d74222f8495866be5fafbace4`. Installed unmodified. MPL-2.0 is
file-level copyleft: modifications to MPL-licensed *files* must be published,
but the licence does not extend to the rest of this project. **If you patch
torchmcubes, that patch must be released under MPL-2.0.** Prefer carrying
changes as a fork with its own published source over vendoring edits here.

---

## 2. Permissive components

No source-disclosure obligation. Attribution is required and is satisfied by
this file.

### Vendored source

| Component | Licence | Notes |
|---|---|---|
| TripoSR (`pythonsrc/tsr/`) | MIT | © 2024 Tripo AI & Stability AI. Vendored with local MPS patches. Full text: [`pythonsrc/tsr/LICENSE`](pythonsrc/tsr/LICENSE) |

### Models and weights

Model weights carry licences **independent of** the libraries that load them.
This is the most common place for a licence problem to enter unnoticed.

| Model | Licence | Commercial use | Notes |
|---|---|---|---|
| FLUX.2-klein-4B (`black-forest-labs/FLUX.2-klein-4B`) | Apache-2.0 | Yes | Black Forest Labs' openly-licensed variant |
| TripoSR (`stabilityai/TripoSR`) | MIT | Yes | |
| U²-Net / `u2net` (via rembg) | Apache-2.0 | Yes | © Xuebin Qin et al. |

> **rembg model selection is a licensing decision, not a tuning knob.**
> `rembg` itself is MIT, but its *default* model has changed across releases:
> current versions default to **BRIA RMBG-2.0, which requires a paid commercial
> agreement**. Prompt2Print therefore pins `rembg==2.0.69` **and** names the
> model explicitly via `REMBG_MODEL` in `pythonsrc/sculptor.py`. Changing that
> variable to a BRIA model without a signed agreement makes commercial
> distribution non-compliant. Both controls must stay in place — the version pin
> alone does not survive a dependency bump.

### Python libraries

| Component | Licence |
|---|---|
| manifold3d | Apache-2.0 |
| trimesh | MIT |
| rembg (library) | MIT |
| PyMatting | MIT |
| fast-simplification | MIT |
| xatlas | MIT |
| moderngl | MIT |
| mflux | MIT |
| PyTorch, NumPy, SciPy, scikit-image | BSD-3-Clause |
| diffusers, transformers, huggingface_hub, safetensors, tokenizers | Apache-2.0 |
| onnxruntime | MIT |
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

---

## Maintaining this file

When adding or bumping a dependency:

1. Check the licence of the package **and**, separately, of any model weights
   it downloads at runtime.
2. Reject AGPL/GPL for anything that would be imported in-process.
3. Pin anything whose *default behaviour* carries a licence implication.
4. Add it to the correct table above and update the review date.
