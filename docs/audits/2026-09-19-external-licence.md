# External licence watch — 2026-09-19

The surfaces the committed audit pipeline structurally cannot reach: remote API terms,
upstream relicensing of components already in the tree, and the trees CI never scans.
The dependency tree itself is **not** re-derived here — `licence-data.yml`,
`infra/scripts/licence_report.py` and `tests/test_licensing_guards.py` do that better,
and this file starts from their output.

Nothing in this file is legal advice. Items marked **[legal]** are in
`docs/deferred-legal-tasks.md`.

---

## 0. Scope — which path each finding belongs to

**Added 2026-09-20, after review.** This report was written without asking which of the
two geometry paths is actually shipping, and it ordered its recommendations as if the
TRELLIS.2 path were. It is not. Both paths are stated here so every finding below can be
read against the right one.

**The parametric organizer path — the customization layer — uses no model weights at
all.** `_apply_spec_mode` (`pythonsrc/pipeline.py:847`) sets `skip_sculptor = True`, so a
spec job never constructs a sculptor. Phase 2 becomes `_compile_spec_phase`, which calls
`compile_spec` in `pythonsrc/organizer/` and writes `compiled_mesh.stl` deterministically.
`_record_spec_generation` books `generation_model = "organizer/<archetype>"`, backend
`local`, and no cost. **Nothing in §§ 3.1, 5, 6 E1–E5 touches this path**: no Pixazo, no
TRELLIS.2, no DINOv3, no RMBG-2.0, no GPU worker image, no charge.

**The prompt path still exists and is still wired.** `startJob`
(`web/src/pages/NewJob.tsx:777`) takes `spec` as an *optional* second argument; a
submission with text and no spec posts a job with no spec, and `JobRequest.prompt`
defaults to `""` rather than being required. That job runs Phase 1 (FLUX) and Phase 2
(sculptor). `SKIP_SCULPTOR` is a config-store key defaulting to `false`
(`server/app.py:2125`), so nothing gates it by default.

**And `auto` reaches the billing backend on exactly the machine this is developed on.**
`resolve_backend_name` (`pythonsrc/sculptors/__init__.py:61`) resolves `auto` as remote →
CUDA → **`pixazo` if `PIXAZO_API_KEY` is set**. An Apple Silicon Mac has no CUDA, so a
prompt job on a dev laptop with a key in `.env` selects the hosted endpoint, bills €0,32,
and does so under terms whose output-ownership clause is unresolved (E5).

**So the Pixazo and worker findings are dormant by intent and live by wiring.** They are
not urgent while nobody submits a spec-less job, and they are not closed either, because
nothing in the code says nobody will. The one action that settles it is a product
decision, not an audit finding — see § 7.

## 1. Freshness

`licenses/report.json` was generated **2026-09-15T09:31:11Z** at commit
`01b15e7a5a4c5593300aa3e225ca713b1fa8a655` — **4 days old**. The fortnightly workflow ran
on schedule on the 15th. Every number quoted below is current.

Newest generated audit: [`docs/audits/2026-09-15-licence.md`](2026-09-15-licence.md).
Verdict **flag**; **2 488 packages across 12 sources**; **0 denials / 1 384 flags**;
79 finding rows in its digest.

Two things about that file are findings in themselves.

**The judgement half is empty.** Everything outside the generated block is the
boilerplate header and nothing else, so the 18 new findings that run reported were never
triaged. They are all one event — the `ds-mvp-pipeline` SBOM was scanned where it had
not been before (packages 2 131 → 2 488), which is why `base-ubuntu-22.04`'s three
aggregate rows moved into it. Twelve of the eighteen are the OS-layer and unreadable
aggregates plus `python-apt` (already in `DISTRO_PROVIDED_PACKAGES`) and the four
`psycopg` rows (already `allow`). The six that are genuinely new *rows* rather than new
*locations* — `autocommand`, `launchpadlib`, `lazr-restfulclient`, `lazr-uri`,
`pygobject`, `wadllib`, all LGPL v3, plus `bidict`/`certifi`/`tqdm` MPL-2.0 — are Ubuntu
`python3` dist-packages and Python transitives, weak copyleft, in an image that is not
distributed today. **None is a denial and none is urgent**, but saying so is the triage,
and it had not been said. See § 7.

**`licenses/python-worker.json` is still absent**, and `report.json`'s
`missing_sources` is `[]` — the absence is not counted as a gap by the report's own
bookkeeping, so a reader checking that field concludes the tree is complete. It is not.
Regenerating it needs a CUDA host (`licenses/README.md` § Deliberate gaps):

```bash
docker compose -f infra/docker-compose.yml --profile gpu-worker build trellis2-worker
docker run --rm --entrypoint /bin/sh ds-trellis2-worker:latest -c \
  'pip install -q pip-licenses && pip-licenses --format=json --with-urls --with-authors \
     --with-license-file --no-license-path' > licenses/python-worker.json
python3 infra/scripts/normalise_licence_data.py licenses/python-worker.json
```

**Which packages therefore have no scanned licence.** Everything installed by
`infra/docker/trellis2-worker.Dockerfile` and nothing else: `torch` 2.6.0 and
`torchvision` 0.21.0 from PyTorch's cu124 index; `imageio`, `imageio-ffmpeg`, `tqdm`,
`easydict`, `opencv-python-headless`, `ninja`, `trimesh`, `transformers`, `pandas`,
`zstandard`, `kornia`, `timm`, `safetensors`, `huggingface_hub`, `einops`, `omegaconf`,
`scipy`; `utils3d` at a pinned commit; `flash-attn` 2.7.3; TRELLIS.2 itself with
`o-voxel` (and the Eigen it vendors); `CuMesh`; `FlexGEMM`; `fastapi`,
`uvicorn[standard]`, `python-multipart`; and the `nvidia/cuda:12.4.1-devel-ubuntu22.04`
OS layer, which *is* scanned as a base image
(`licenses/sbom/base-nvidia-cuda-12.4.1-devel.json`) but not as built.

`THIRD-PARTY-NOTICES.md` § *Phase 2 GPU worker* records seven of these by hand —
TRELLIS.2, o-voxel, Eigen, CuMesh, FlexGEMM, flash-attn, utils3d. **It does not record
the `setup.sh --basic` Python dependencies on the line above them**, and two of those
need a decision. See E1 and E2.

## 2. What changed since the last external watch

**There has not been one.** No `*-external-licence.md` exists in `docs/audits/`, and
nothing in `docs/`, `.github/` or the root markdown refers to a prior external watch.
This file establishes the series and the E-numbering in § 6; later runs amend it by
writing a new dated file and carrying the numbers forward.

The August 2026 register this routine inherits its open items from is not in the
repository. Its findings are re-checked in § 5 against the tree as it stands.

## 3. Vendor terms

### 3.1 Pixazo — `https://gateway.pixazo.ai`, slug `trellis-2-image-to-3d`

Archived copy: not published (it quoted the vendor's terms; read the primary source).
Called from `pythonsrc/sculptors/pixazo.py`. The only code in this repository that
incurs a charge.

**The terms have moved.** Pixazo's Terms of Use are dated *effective 16 September 2025,
last updated 14 September 2026* — five days before this run. This is the first time they
have been read from the primary source against this repository, so what follows is the
whole position, not a delta.

- **§5.3.1 still assigns free-plan output to Appy Pie LLP**, with a Pixazo attribution
  duty attached to the licence back to the user. §5.3.4 makes that permanent: free
  content stays Appy Pie's *regardless of a subsequent upgrade*.
- **§5.3.2 gives paid subscribers full ownership**, expressly including the right to
  sell — which is what this business needs.
- **Which of the two an API key is, the terms do not say.** §5.3 speaks of "free plan"
  and "paid subscription plans", the consumer tiers; API access is sold separately as
  usage-based billing. A per-call API customer is described by neither clause. **[legal]**
- **No warranty helps us.** §11.2 specifically declines to warrant that output is
  "UNIQUE, ORIGINAL, OR NON-INFRINGING". §9.3 disclaims responsibility for third-party
  model training data and for "any claim arising from a specific model used at the
  User's direction" — and we name the model by slug. §13.1's indemnity runs *from us to
  them* and expressly covers "Failure to comply with AI model licence terms."
- **§5.6.2** — where the terms conflict with a model's licence, the more restrictive
  provision applies. So an undisclosed upstream licence still binds the caller.
- **Governing law: India; exclusive forum New Delhi** (§15.1.1, §15.2.1), against an
  Italian pilot. **[legal]**
- Appy Pie's own *Generative AI Additional Terms* (5 June 2025) say something different
  — no assignment, "Appy Pie does not guarantee ownership of AI-generated content", and
  a prohibition on "intermediation/resale". **Which document governs an API call is not
  stated in either.** **[legal]**

**Which upstream weights back the endpoint: UNKNOWN — unverified.** Tried: the model
page, the Terms of Use, the fair-use policy, the Appy Pie additional terms, and the
vendor's public documentation. None names the conditioning model or the
background-removal model; the model page gives only "Trellis v2" and the slug. So
whether DINOv3's "Built with DINOv3" attribution duty and BRIA RMBG-2.0's CC BY-NC
terms flow through to meshes we sell **cannot be established from outside**. Combined
with §13.1, the risk sits with us and the facts sit with them. This is a **blocker**,
open since August 2026 — E3.

**Price.** Vendor list is **USD 0,35** per generation. The ECB euro reference rate on
**2026-09-18 is EUR 1 = USD 1,1460**, so the list price is **€0,3054**. The code pins
`PRICE_EUR_PER_GENERATION = 0.32`, set 2026-08-20; the vendor's own page displays
€0,33. Three different euro figures for one dollar price. The constant overstates by
€0,015 per generation (≈ 4,8 %) — conservative in direction, wrong in fact, and it will
keep drifting because **a euro constant pinned against a dollar list price has no
mechanism to stay right**. See E4.

### 3.2 Hugging Face — `https://huggingface.co`

Archived: [`vendor-terms/huggingface-2026-09-19.md`](vendor-terms/huggingface-2026-09-19.md).
Called from `server/app.py` (`api/whoami-v2`, to validate `HF_TOKEN`) and by every
`from_pretrained` on the model path. No charge.

Terms effective **15 September 2022**; unchanged. The Hub conveys nothing of its own,
warrants nothing about a third-party model's licence, and puts compliance on the
downloader. It says **nothing about gated repositories or who the accepting party is**,
which is precisely the hole Task L5 names for DINOv3: the acceptance is made by whoever
holds `HF_TOKEN`, and no platform term makes it run to a company. Governing law New York.

No obligation flows from the Hub itself; every model obligation comes from the
individual repository licence, recorded in `THIRD-PARTY-NOTICES.md` § 0.

### 3.3 Not remote APIs, for the record

- **Hosted text-to-image (Phase 1) — still not chosen.** `pythonsrc/visualizer.py` names
  `black-forest-labs/FLUX.2-klein-4B` and loads it locally; `pythonsrc/config.py` has
  `FLUX_MODEL_PATH` and no hosted endpoint. Nothing to read terms for. Re-check next run.
- **Printer operators** (`pythonsrc/operators/`) reach OctoPrint, Moonraker and Bambu
  over the local network. No vendor terms, no charge.
- **Web push** (`server/push.py`) POSTs to whatever endpoint the *browser* supplies at
  subscription time. We contract with no push service and send no identity; the
  obligations are `pywebpush`/`py-vapid`'s licences, handled in § 4.
- **Supabase** holds the telemetry database over the PostgreSQL wire protocol with no
  SDK installed. Its terms and DPA govern **prompt and telemetry data**, not licensing,
  and belong with Task L1's retention question rather than here.

## 4. Upstream relicensing

Every component whose recorded decision a relicense could silently invalidate, checked
against its primary source on 2026-09-19. **No change to any of them.**

| Component | Recorded as | Verified today | Source |
|---|---|---|---|
| CuraEngine | AGPL-3.0, arm's-length CLI | `LICENSE` is GNU AGPL v3; `conanfile.py` `license = "AGPL-3.0"` | `Ultimaker/CuraEngine@main` |
| OctoPrint | AGPL-3.0, arm's-length HTTP | `"GNU Affero General Public License v3"`, classifier `License :: OSI Approved :: GNU Affero General Public License v3`, v1.11.8 | PyPI JSON |
| `psycopg` (+`-binary`, `-pool`) | LGPL-3.0-only, reviewed weak copyleft | `license_expression: "LGPL-3.0-only"`, v3.3.6 | PyPI JSON |
| `pywebpush` | MPL-2.0, reviewed weak copyleft | `license_expression: "MPL-2.0"`, v2.5.0 | PyPI JSON |
| `py-vapid` | MPL-2.0, reviewed weak copyleft | `license: "MPL-2.0"`, v1.9.4 | PyPI JSON |
| `opencv-python-headless` | Apache-2.0, bundled FFmpeg LGPLv2.1, Qt 5 LGPLv3 kept out by the headless pin | `license: "Apache 2.0"`; description still splits wrapper MIT / OpenCV Apache-2 / bundled FFmpeg LGPLv2.1 / Qt 5 LGPLv3 in the **non-headless** Linux wheels only | PyPI JSON |

The AGPL→LGPL relicense people cite remains `Ultimaker/Cura`, the frontend. It is not
CuraEngine, and CuraEngine is what this project invokes.

One note, not a change: upstream `psycopg` is 3.3.6 while the scanned tree holds 3.3.5,
and `opencv-python-headless` is 5.0.0.93 upstream. Version drift, same licences.

## 4b. Both delivery branches

Delivery is undecided — SaaS-hosted versus shipped Docker images — and the two sets of
obligations are different enough that collapsing them into one recommendation would give
the wrong answer to whichever branch is actually taken. Reported separately, deliberately.

### If delivery is SaaS-hosted

Nothing is conveyed, so **the obligations that trigger on distribution do not arise**:

- No GPL/LGPL source offer for the Ubuntu 22.04 layer — which is not a small saving. The
  `ds-mvp-pipeline` image alone carries **106 strong-copyleft and 32 weak-copyleft OS
  packages, plus 160 with no readable licence** (`2026-09-15-licence.md` digest).
- No AGPL-3.0 § 6 source offer for CuraEngine, which arrives as Ubuntu's `cura-engine`
  `.deb` (`infra/docker/pipeline.Dockerfile:49`).
- No NVIDIA CUDA EULA **Attachment A** question for the worker image.
- No MPL-2.0 file-level source obligation for `pywebpush`, `py-vapid`, `certifi`,
  `bidict`, `tqdm` or `lightningcss` — MPL § 3.2 triggers on distributing Executable Form.
- **E1 and E2 go dormant.** `easydict`'s LGPL and `imageio-ffmpeg`'s bundled binary both
  matter only in a conveyed artifact.

**AGPL § 13 does not go away, but read what it actually attaches to.** § 13 obliges
whoever *modifies* a covered work and makes the modified version available over a
network to offer that version's source to its remote users. This project modifies
neither AGPL component: CuraEngine is Ubuntu's package, unmodified, invoked as a CLI
subprocess (`pythonsrc/slicer.py`); OctoPrint is a peer service reached over HTTP and
SockJS (`pythonsrc/operators/`). On those facts § 13 creates no obligation today.

It creates one the moment either is patched, vendored, or linked in-process — and a
hosted service is exactly where that happens quietly, because nothing ships and nobody
reviews a build. The whole defence on this branch is
`licence_policy.AGPL_IN_PROCESS_PACKAGES` (`octoprint`, `libarcus`, `libsavitar`,
`uranium`), `ARM_LENGTH_COMPONENTS`, and the three guard tests
`test_no_source_file_links_an_agpl_component`,
`test_no_install_manifest_pulls_an_agpl_python_package` and
`test_the_slicer_still_invokes_curaengine_as_a_subprocess`. They are static, free, and
on this branch they are the only thing standing between the project and § 13.

What SaaS **adds** rather than removes, none of it visible to a dependency scanner:

- **Use restrictions bind a service that distributes nothing.** DINOv3's licence,
  attribution duty and Acceptable Use Policy attach to use (Task L5), as does the gated
  acceptance question — who the licensee is.
- **Pixazo's output ownership (E5)** decides whether the meshes a hosted service sells
  are the service's to sell.
- **Data terms**, not licence terms: prompts and telemetry live in Supabase, and
  retention is Task L1's open question.
- **EU AI Act Art. 50(1)** attaches to the interface, and is handled
  (`docs/deferred-legal-tasks.md`, "Open question for counsel").

### If delivery is shipped Docker images

Everything above reverses, and four items become work rather than theory:

1. **A written offer for source** covering the Ubuntu 22.04 GPL/LGPL layer and
   CuraEngine (AGPL-3.0 § 6). The scope is the 106 + 32 + 160 rows named above, per
   image, per release — which is why the SBOMs are committed.
2. **NVIDIA CUDA EULA Attachment A.** The worker is built on
   `nvidia/cuda:12.4.1-devel-ubuntu22.04` — the *devel* tag, the full toolkit including
   the compilers, not the runtime redistributable set Attachment A enumerates. There is
   a narrow redistribution route and the devel image is not obviously inside it. This is
   the NVIDIA hygiene item `docs/deferred-legal-tasks.md` Task L4 already names; it
   becomes blocking only on this branch.
3. **The `triton` bundled-tools question is unanswered and currently invisible.** No
   `triton` or `nvidia-*` distribution appears in any scanned tree — because the CPU
   images install CPU torch, and the CUDA torch in the worker image (`torch==2.6.0`
   from the cu124 index) is in the tree nobody scans. Whether it pulls `triton` with its
   bundled LLVM and `ptxas`, and under what terms, is another consequence of E1's root
   cause rather than a separate problem. The worker scan answers it.
4. **E1 and E2 become live**, along with the MPL-2.0 file-level obligations, and
   `test_no_install_manifest_bakes_model_weights` becomes load-bearing rather than
   precautionary — shipping an image with gated DINOv3 weights inside it is a
   redistribution the gated acceptance does not travel with (Task L5).

**The asymmetry worth naming:** SaaS trades a large, enumerable, one-time compliance job
(source offers, redistribution routes) for a small set of permanent, invisible ones (use
licences, output ownership, data retention). Neither is obviously cheaper. What is
obviously true is that **the shipped-image branch cannot be costed at all until the
worker image is scanned** — three of its four items are unanswerable today.

## 5. Closed / downgraded

**The August 2026 register's local-TRELLIS.2 findings — `nvdiffrast`, `nvdiffrec`,
`plyfile`, `easydict`, `libigl`, `cubvh`, `pymeshfix`, `torchmcubes` — appear in no
scanned tree**: none is present in `licenses/report.json`, in any of the six
`licenses/*.json` files, or in any of the seven SBOMs. TripoSR is gone
(`tests/test_sculptors.py::test_triposr_is_gone`), `pymeshfix` was replaced
(`pythonsrc/engineer.py`), and the GPU worker builds only under `--profile gpu-worker`,
which CI never runs.

**One of them is not actually closed.** `easydict` **is installed**, at
`infra/docker/trellis2-worker.Dockerfile:62`. It is absent from the scans because the
worker tree has never been scanned, not because it was removed — the exact failure this
step exists to catch, running in the other direction. It is carried to § 6 as E1.

The other seven are genuinely absent from the images that are built, and
`licence_policy.FORBIDDEN_RENDERER_PACKAGES` plus the guard tests keep
`nvdiffrast`/`nvdiffrec` out by construction. **Downgraded from blocker to
closed-pending-worker-scan**, and they stop being carried once `python-worker.json`
exists.

## 6. Still open

Numbered E1…E5; these numbers are permanent and later runs keep them.

**E1 — `easydict` (LGPL-3.0) is in the worker image with no recorded decision.**
Path: **TRELLIS.2 worker only** — not on the organizer path (§ 0).
Status: **open, new this run; dormant while the worker does not ship.** Installed at `trellis2-worker.Dockerfile:62` as part of
TRELLIS.2's `setup.sh --basic` set. PyPI declares `LGPL-3.0` with the LGPLv3 classifier.
It is not in `licence_policy.REVIEWED_WEAK_COPYLEFT`, and `THIRD-PARTY-NOTICES.md`'s
worker table covers only the seven CUDA-stack components, not the pip line above them.
The policy's own rule is "anything LGPL *not* on this list stays a flag" — and it cannot
even be flagged, because the tree is unscanned. LGPL is satisfiable here (a separate,
unmodified wheel, dynamically imported), so this is a recording gap, not a violation.
It matters only on the shipped-image branch. *Open: this run.*

**E2 — `imageio-ffmpeg` bundles an FFmpeg executable of unknown build.**
Path: **TRELLIS.2 worker only** (§ 0).
Status: **open, new this run; dormant while the worker does not ship.** Also at `trellis2-worker.Dockerfile:62`. The package is
BSD-2-Clause, but its platform wheels ship an ffmpeg binary (~60 MiB), and neither the
PyPI metadata nor the project README states whether that build is LGPL or GPL. An LGPL
build in a distributed image is a source offer; a GPL build is strong copyleft in a
distributed artifact. Determinable only by reading the wheel inside the built image,
which needs a CUDA host. Worth checking first whether it is needed at all: the worker
runs inference on the shape-only path and never writes video, and `gradio`, `tensorboard`
and `lpips` were already dropped from the same line for that reason. *Open: this run.*

**E3 — Which weights back Pixazo's `trellis-2-image-to-3d`: UNKNOWN — unverified.**
Path: **prompt path only** (§ 0) — no spec job can reach it.
Status: **blocker while a spec-less job can be submitted; dormant the moment one cannot.** See § 3.1. The DINOv3 attribution duty and RMBG-2.0's
CC BY-NC terms may flow through to meshes we sell, §5.6.2 makes an undisclosed model
licence bind us anyway, and §13.1 indemnifies the vendor against our failure to comply
with it. Unanswerable without the vendor. `THIRD-PARTY-NOTICES.md` already says keep the
backend beta-only absent written confirmation; that remains the correct posture.
*Open since August 2026 — about one month.*

**E4 — `PRICE_EUR_PER_GENERATION` is a euro constant tracking a dollar list price.**
Path: **prompt path only** (§ 0).
Status: **open, new this run; cosmetic while no job bills.** €0,32 pinned 2026-08-20 against a USD 0,35 list, which
is €0,3054 at the ECB rate of 2026-09-18. Every historical `generation_cost_eur` is
overstated by ≈ 4,8 % and the error grows or shrinks with FX. The docstring's reasoning
— record per job so a price change does not rewrite history — is right; the flaw is that
it pins the *converted* figure rather than the price and the rate. Engineering, small.
*Open: this run.*

**E5 — Pixazo: which ownership clause governs an API key.**
Path: **prompt path only** (§ 0), but reachable today on any GPU-less host with
`PIXAZO_API_KEY` set, because `resolve_backend_name`'s `auto` falls through to it.
Status: **blocker while that is true.** §5.3.1 gives free-plan output to Appy Pie LLP
permanently; §5.3.2 gives paid subscribers full ownership including the right to sell;
neither describes a usage-based API customer, and Appy Pie's separate Generative AI
terms disclaim ownership altogether and forbid "intermediation/resale". If the API
resolves to the free tier, **no mesh produced through this backend is ours**. This is
narrower and sharper than Task L4's general "get a warranty", and is added to that task.
*Open since August 2026 as part of L4 — about one month; specified this run.*

## 7. What I would do first

**Reordered 2026-09-20.** The original ordering put "scan the CUDA worker" first. That is
wrong: the worker serves a path the product is not shipping (§ 0), so scanning it buys
evidence for obligations nobody is about to incur. The live path is the parametric
organizer, the CPU images, the slicer and the printer — and almost nothing in this report
is about them, which is itself the useful result.

**Product decision — this one gates the other five:**

1. **Decide whether a spec-less job can still be submitted.** If TRELLIS.2 is benched,
   bench it in code rather than by intention: set `SKIP_SCULPTOR` in the config store, or
   make `POST /jobs` refuse a job with neither a spec nor an explicit opt-in. Today
   `startJob` will happily post one and `resolve_backend_name`'s `auto` will pick the
   backend that bills. Once that is closed, **E1–E5 all go dormant together** and this
   report shrinks to § 4 and the paragraph below it.

**Engineering, on the live path:**

2. **Triage the 2026-09-15 findings** in that file's judgement half, using § 1's
   paragraph. They are about `ds-mvp-pipeline` — the image that actually ships — and they
   are the only untriaged thing here that is not about a benched subsystem. Two minutes.
3. **Fix E4** if and only if the prompt path stays live. Store the price and the currency
   and convert at a recorded rate, rather than pinning the converted figure.

**Engineering, only if the TRELLIS.2 path is un-benched or the worker ships:**

4. Build and scan the worker image on a CUDA host (`licenses/README.md`'s command,
   reproduced in § 1). Closes E1 and E2 and answers the `triton` question. **Do not spend
   a GPU host's time on this while the path is benched.**

**Counsel — only if the prompt path stays live:**

5. Does a usage-based Pixazo API key fall under §5.3.2 (full ownership) or §5.3.1
   (Appy Pie owns it)? And which document governs — Pixazo's Terms of Use or Appy Pie's
   Generative AI Additional Terms? Indian law, New Delhi forum, against an Italian pilot.
   **If the answer to (1) is "benched", this question can wait** — but note it is
   retrospective as well as prospective: §5.3.4 means any mesh already generated on a
   free-tier key stays Appy Pie's whatever we do next.

**Vendor email — same condition:**

6. (a) Which plan does an API key resolve to for §5.3.1/§5.3.2? (b) Which
   background-removal and conditioning weights does `trellis-2-image-to-3d` run?
   (c) Will you warrant that outputs carry commercial rights notwithstanding §11.2?
   (d) Will you confirm the list price and its currency, and give notice of changes?

Until (a) and (b) are answered in writing, `pixazo` stays beta-only — which, if (1) lands
on "benched", it already is by construction rather than by policy.
