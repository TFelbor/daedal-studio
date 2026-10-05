# External licence watch — 2026-10-05

This watch covers what the automated pipeline cannot reach: vendor terms of service,
upstream relicensing, and whether earlier blockers are still live. It was written by
hand, and it does not re-derive the dependency tree. That tree comes from
`.github/workflows/licence-data.yml` and `infra/scripts/licence_report.py`, and it is
this report's input.

It amends **[`2026-09-28-external-licence.md`](2026-09-28-external-licence.md)**. It
keeps the E-numbers from 2026-09-19, which that report declared permanent.

**This is not legal advice.** Items marked **[LEGAL]** need a lawyer and are carried in
`docs/deferred-legal-tasks.md`. No new legal task arises this run; E12 and E13 are
already recorded there (lines 368 and 372).

---

## Headline

**Nothing material changed, and for the first time in this series the scan data is
current.** The fortnightly workflow ran on 2026-10-01 as scheduled, so **E10 closes**:
the scanned trees had been behind `main` since 2026-09-21, and they no longer are.

Two smaller facts are worth the ink. Pixazo's **Terms of Use were updated today**, and
the one substantive change is a wallet top-up condition on the free tier that takes
effect **today** — it does not touch 3D, but it sets a tripwire worth naming. And
**E4 narrowed to 2,63 %** on exchange-rate movement alone.

**E3 is unchanged and is still the blocker.** The weights behind
`trellis-2-image-to-3d` remain undisclosed, and five Pixazo pages were tried again.

## 1. Freshness

**The data is 4 days old. The fortnightly workflow ran on schedule.** This is the
freshest this report has been able to say.

- `licenses/report.json` — `generated_at` **2026-10-01T11:05:33Z**, commit `bb2b73d`.
  Verdict `flag`, **2 603 packages across 12 sources**, **0 denials / 1 477 flags**,
  86 finding rows. `missing_sources` and `unreadable_sources` are both empty, and all
  12 sources report `status: ok`.
- Against 2026-09-28 (which was quoting the 2026-09-15 run): +115 packages, +93 flags,
  +7 finding rows. **Deny is still 0.** The growth is the scan catching up with
  everything merged between 09-15 and 10-01 — it is not new exposure.
- The newest generated audit is **`2026-10-01-licence.md`**, and its digest agrees with
  the report: `allow 1126 / flag 1477 / deny 0`.
- **`licenses/python-worker.json` still does not exist.** The TRELLIS.2 GPU worker has
  never been scanned. The command that produces it on a CUDA host is in
  `licenses/README.md`. With no scan, **no package installed by
  `infra/docker/trellis2-worker.Dockerfile` has a scanned licence** — including
  `easydict`, `imageio-ffmpeg`, `tqdm`, `ninja` (line 62), `torch==2.6.0` from the
  cu124 index (line 55) and the four compiled CUDA extensions. Whether that torch build
  pulls `triton` with it is still unanswered, as 2026-09-19 first noted: `triton` has
  zero occurrences across every scan file, but that is the unscanned tree speaking, not
  evidence of absence. This is **E7**.
- **The judgement half of `2026-10-01-licence.md` is empty** — `<!-- generated:end -->`
  is the last line of 316. That makes **13 consecutive generated audits with no
  triage**; the only audit that has one is the 2026-08-27 baseline. This is **E8**.

## 2. What changed since 2026-09-28

1. **The scan caught up. E10 closes.** The 2026-10-01 run picked up `pywebpush`,
   `py-vapid`, `fonttools`, `ruff` and `@playwright/test`, all of which 09-21 and 09-28
   recorded as present in `main` but absent from the scanned trees. `pywebpush@2.5.0`
   and `py-vapid@1.9.4` now appear in `python-api-server.json` and
   `sbom/ds-api-server.json`, both scored `allow`.
2. **No dependency changed in the repository.** `git diff ea631fb..HEAD` over
   `requirements-*.txt`, `web/package.json`, `pyproject.toml` and `infra/docker/` is
   **empty**. The only commit since the last watch is `a39189a`, the licence-data
   regeneration. There is nothing new to classify.
3. **Pixazo's Terms of Use moved to 5 October 2026** (24 September at the last watch).
   The substantive change is § 7.9.1: the free tier is now "available only on API
   accounts that have added funds to their wallet at least once (minimum US$10)", and
   § 7.9.3 dates that condition to **today**. Detail and the tripwire it creates are in
   § 3.1(e).
4. **The API Terms did not move.** Still 9 April 2026. All five clauses the register
   turns on — § 4.1, § 6.4, § 8.1, § 9.4 and the precedence clause — were re-read
   verbatim and are identical.
5. **E4 narrowed to 2,63 %**, from 4,26 %. The list price did not move; the euro
   weakened.
6. **Routine hygiene from 09-28 is done.** Every `legal`/`terms`/`policy` link on
   `/terms-of-use` was enumerated rather than guessed. The complete set is
   `/api-terms-of-use` and `/privacy-policy`. There is no third document, so the gap
   that hid the API Terms for two watches is now closed by method, not by luck.

## 3. Vendor terms

The vendor list was rebuilt by grepping the code for outbound hosts. Every `http(s)://`
literal in `pythonsrc/`, `server/` and `services/` resolves to one of: `localhost`,
`127.0.0.1`, `host.docker.internal`, a LAN printer (`printer`, `octopi.local`,
`mainsail.local`, `192.168.x.x`), a docstring example (`attacker.example`,
`gpu-host`), a documentation link (`docs.octoprint.org`), or the two real vendors
below. **Unchanged since 2026-09-21.**

| Endpoint | Where | Paid | Section |
|---|---|---|---|
| `https://gateway.pixazo.ai` | `pythonsrc/sculptors/pixazo.py:46` | **Yes — EUR 0,32/gen booked** | § 3.1 |
| `https://huggingface.co` | `server/app.py` (token check) + weight downloads | No | § 3.2 |
| OctoPrint / Moonraker | `pythonsrc/operators/` | No | The operator's own printer on the LAN. No vendor |

**Phase 1 still has no hosted vendor.** `pythonsrc/visualizer.py` contains no URL, no
API key and no endpoint; it builds a local `diffusers` pipeline from `FLUX_MODEL_PATH`.
`config.template.py` names no image API. The planned hosted text-to-image endpoint has
not been chosen, so there is nothing to read terms for.

### 3.1 Pixazo (Appy Pie LLP)

**Archived copy: [`vendor-terms/pixazo-2026-10-05.md`](vendor-terms/pixazo-2026-10-05.md).**
Sources: `/api-terms-of-use` (9 April 2026), `/terms-of-use` (**5 October 2026**),
`/models/trellis3d`, `/api/free` and `/pricing`, all retrieved 2026-10-05. Quotations
were checked against the raw HTML.

**(a) Ownership: unchanged. [LEGAL], confirmatory. E5.**
API Terms § 6.4 still reads "Pixazo does not claim ownership of Output Content generated
through the API Services", and the precedence clause still puts the API Terms above the
Terms of Use for API Services. The two limits named on 09-28 stand: "does not claim" is
not an assignment, and "Output Content" is defined as "images, videos, audio, or other
media" without naming a mesh.

One clarification worth recording, because it joins E3 to E5: Terms of Use § 5.3.3 says
ownership "does not extend to training data, model weights, or **embedded third-party
IP**". That sentence is not new — the 2026-09-19 archive already has it — but it is
exactly the clause that the unknown weights would operate through. **E3 is not merely a
provenance question; it is the input to E5.**

**(b) No warranty; the indemnity runs from us to Pixazo. Unchanged. E6.**
API Terms § 6.2 disclaims "originality, legality, non-infringement"; § 6.4 and § 10.1
put the indemnity on the Client; § 10.2 caps Pixazo's liability at 12 months' fees.

**(c) The weights are still undisclosed. UNKNOWN — unverified. BLOCKER. E3.**
`/models/trellis3d`'s raw HTML has **zero occurrences** of `licen`, `commercial`,
`Microsoft`, `RMBG`, `BRIA`, `DINO`, `BiRefNet`, `MIT`, `open source` or `weights`. The
model page that § 5.6.1 points to summarises no restriction, which makes § 5.6.1's
promise unperformed.

*A false lead, recorded so it is not re-chased:* a keyword sweep of both terms pages
returns five hits for "Microsoft". All five are
`filter:progid:DXImageTransform.Microsoft.gradient(...)` — legacy IE CSS in the
stylesheet. There is no model disclosure in either document.

The upstream remains fully legible by contrast. `microsoft/TRELLIS.2-4B` (`license:mit`,
ungated) still wires `briaai/RMBG-2.0` as `rembg_model` and
`facebook/dinov3-vitl16-pretrain-lvd1689m` as `image_cond_model` in `pipeline.json`,
re-fetched today. RMBG-2.0's card, read today: "released under a CC BY-NC 4.0 license
for non-commercial use. Commercial use is subject to a commercial agreement with BRIA."

Pages tried this run: the API Terms, the Terms of Use, the model page, the free-tier
page and the pricing page. `/api-pricing` returns **HTTP 410 Gone**. None names an
upstream component. Only a written answer from Pixazo closes this.

**(d) Price: the list price is unchanged; the constant still overstates it. E4.**

| | |
|---|---|
| List price | USD 0,35 per generated 3D model |
| ECB euro reference rate | **USD 1,1225 = EUR 1, 2026-10-02** |
| Converted | **EUR 0,3118** |
| `PRICE_EUR_PER_GENERATION` | EUR 0,32 (implies 1,09375) |
| Overstatement | EUR 0,0082 per generation, **2,63 %** (EUR 320,00 booked vs EUR 311,80 payable per 1 000) |

The overstatement fell from 4,26 % because the euro weakened 1,56 % against the dollar
(1,1403 on 2026-09-25 to 1,1225 on 2026-10-02), not because anything was fixed. **A
figure that moves by itself is the argument for the fix in § 7, item 4.**

**(e) New: the free tier now has a wallet condition, effective today.**
§ 7.9.1 now restricts the free tier to "API accounts that have added funds to their
wallet at least once (minimum US$10)", and § 7.9.3 dates that from 5 October 2026.

This does **not** change our exposure. `/api/free`, re-read today, lists Flux, LTX,
Pixelforge, Stable Diffusion, SDXL and Tracks — **no Trellis model and no 3D endpoint**.
The free tier covers image, video and audio only, so no 3D generation is served from it
and none becomes "Free Content" owned by Appy Pie LLP under § 5.3.1.

**The tripwire.** We necessarily top up the wallet, because the 3D endpoint is
pay-per-use. From today that top-up makes our account automatically free-tier eligible.
If Pixazo ever adds a 3D model to `/api/free`, generations could begin arriving as Free
Content without any action on our side. This is folded into E5 rather than given its own
number, because it is a conditional, not a live defect. **The guard is re-reading
`/api/free` every watch**, which this routine already does — it is now load-bearing
rather than incidental.

**(f) Obligations carried, unchanged. E12, E13, E11.**
§ 9.4 ("delete any cached API responses" on termination, against `_cache_glb`), § 8.1
(flow-down into End User terms) and the Indian law / New Delhi forum are all identical
to the 09-28 readings. § 3 and § 6.3 — no endpoint exposure, no resale, no training on
Output Content, moderation before release — remain satisfied by the current design.

### 3.2 Hugging Face Hub

The Terms of Service (<https://huggingface.co/terms-of-service>, retrieved 2026-10-05)
are still **effective 15 September 2022**, governing law New York, and still silent on
gated repositories. **Unchanged. The archive from
[`vendor-terms/huggingface-2026-09-19.md`](vendor-terms/huggingface-2026-09-19.md)
stands, and I did not archive a new copy.**

Model repos, via the HF API today:

| Repo | Gated | Licence tag | Last modified |
|---|---|---|---|
| `facebook/dinov3-vitl16-pretrain-lvd1689m` | **manual** | `other` (DINOv3 Licence) | 2025-08-19 |
| `briaai/RMBG-2.0` | auto | `other` — card says CC BY-NC 4.0 | 2026-04-06 |
| `ZhengPeng7/BiRefNet` | no | `mit` | 2026-02-04 |
| `microsoft/TRELLIS.2-4B` | no | `mit` | 2025-12-27 |

No gating status and no licence tag changed.

## 4. Upstream relicensing

**No change. Nothing in `ARM_LENGTH_COMPONENTS` or `REVIEWED_WEAK_COPYLEFT` has
relicensed.** Each was read from the primary source today:

- **CuraEngine** — `LICENSE` is "GNU AFFERO GENERAL PUBLIC LICENSE Version 3", and
  `conanfile.py:18` reads `license = "AGPL-3.0"` (`Ultimaker/CuraEngine@main`). For
  contrast, `Ultimaker/Cura@main` `conanfile.py:28` reads `license = "LGPL-3.0"` — the
  frontend, not the engine. The relicense people cite still does not reach us.
- **OctoPrint** — `LICENSE.txt` is AGPL v3 (`OctoPrint/OctoPrint@master`).
- **`psycopg` 3.3.6, `psycopg-binary` 3.3.6, `psycopg-pool` 3.3.3** — PyPI
  `license_expression` is `LGPL-3.0-only` for all three.
- **`pywebpush` 2.5.0** and **`py-vapid` 1.9.4** — both `MPL-2.0`.
- **`opencv-python-headless`** — `Apache 2.0`. Latest is **5.0.0.93**; we pin
  `4.13.0.92`. Unchanged from 09-28, including the standing note that a bump to 5.x
  needs the bundled FFmpeg build re-checked at that point.
- **`fonttools` 4.66.1** — `MIT`, now scanned (see E10).

## 5. Closed / downgraded

- **E10 closes.** The 2026-10-01 scan landed and the trees match `main`. Open 14 days.
- **The August local-TRELLIS.2 register is still dead, and this was re-checked rather
  than assumed.** `nvdiffrast`, `nvdiffrec`, `plyfile`, `easydict`, `libigl`, `cubvh`,
  `pymeshfix`, `torchmcubes`, `triposr` and `pymeshlab` have **zero occurrences** across
  `licenses/report.json`, `licenses/*.json` and `licenses/sbom/*.json`. The only file
  under `licenses/` that names any of them is `README.md`, which is prose. No workflow
  builds `trellis2-worker`: it sits behind `--profile gpu-worker` in
  `infra/docker-compose.yml:131`. `FORBIDDEN_RENDERER_PACKAGES` keeps `nvdiffrast` and
  `nvdiffrec` denied outright, and the deny-list stays.
- **E1 and E2 stay open.** `easydict` and `imageio-ffmpeg` also show zero occurrences,
  but only because the worker tree is unscanned (E7). They are still installed at
  `infra/docker/trellis2-worker.Dockerfile:62`. Absence from a scan that never ran is
  not evidence.

## 6. Still open

"Open since" counts from the 2026-08-27 baseline unless stated otherwise. Today is
2026-10-05.

**E1 — `easydict` (PyPI: `LGPL-3.0`, v1.13) is in the worker image with no recorded
decision.**
*Status: unchanged, dormant while the worker does not ship. Open since 2026-09-19
(16 days).* Closes when E7 produces `python-worker.json` and a decision is recorded.

**E2 — `imageio-ffmpeg` bundles an FFmpeg binary whose build licence is unknown.**
*Status: unchanged, dormant. Open since 2026-09-19 (16 days).* The package is
`BSD-2-Clause`; the bundled binary is the open question, and no primary source states
whether it is LGPL or GPL. Closes on the same condition as E1.

**E3 — The weights behind `trellis-2-image-to-3d` are UNKNOWN — unverified. BLOCKER.**
*Status: unchanged. Open 39 days, and unverified since August 2026.* See § 3.1(c). Five
Pixazo pages tried this run; the model page § 5.6.1 points to summarises no restriction.
**This run establishes that E3 is an input to E5, not a parallel question** — Terms of
Use § 5.3.3 excludes "embedded third-party IP" from whatever ownership we have. Only a
written answer from Pixazo closes it.

**E4 — `PRICE_EUR_PER_GENERATION` overstates cost by 2,63 %.**
*Status: re-quantified at ECB 1,1225 (2026-10-02). Open 39 days.* It was 4,26 % on
09-21 and 4,78 % before that. The figure has now moved three watches running on exchange
rate alone. Engineering, not legal.

**E5 — Pixazo output ownership. [LEGAL]**
*Status: unchanged since the 09-28 downgrade. Open 39 days.* API Terms § 6.4 disclaims
ownership and prevails. For a lawyer: does "other media" cover a mesh, and does
disclaiming ownership leave it with us? Now carries the free-tier tripwire from
§ 3.1(e). The 09-19 point about the *Generative AI Additional Terms* (5 June 2025) was
again **not re-checked**; it matters less, because two Pixazo-specific documents, one
with a precedence clause, sit above it.

**E6 — No warranty of non-infringement; the indemnity runs from us to Pixazo. [LEGAL]**
*Status: unchanged. API Terms § 6.2, § 6.4, § 10.1, § 10.2. Open 39 days.*

**E7 — `licenses/python-worker.json` does not exist.**
*Status: unchanged. Open 39 days.* Producing it closes E1 and E2 and answers the
`triton` question. Needs a CUDA host.

**E8 — No generated audit has been triaged since the baseline.**
*Status: worse by one. Open since 2026-08-31 (35 days).* **Thirteen** audits now have
empty judgement halves, and 1 477 flags stand unread — up from 1 384. Facts gathered for
whoever does the triage, re-confirmed on PyPI today: `certifi` (2026.7.22) is `MPL-2.0`,
and `tqdm` (4.70.1) is `MPL-2.0 AND MIT`. Both are weak copyleft at file level and
neither is in `REVIEWED_WEAK_COPYLEFT`.

**E9 — DINOv3: the licensee may be a person rather than the company. [LEGAL]**
*Status: unchanged. The repo is still gated `manual`. Open 39 days.* Task L5.

**E10 — The scanned trees are behind `main`.** ✅ **CLOSED 2026-10-05.**
*Was open since 2026-09-21 (14 days).* The 2026-10-01 scheduled run landed and all five
carried packages are now scanned. See § 2.1.

**E11 — Indian law and a New Delhi forum.**
*Status: unchanged. Open since 2026-09-21 (14 days).* Context for E5, E6, E12 and E13,
not a defect.

**E12 — On termination, API Terms § 9.4 requires deleting "any cached API responses".
[LEGAL]**
*Status: unchanged; re-read verbatim. Open since 2026-09-28 (7 days).*
`PixazoSculptor._cache_glb` caches purchased GLBs by design. The terms do not say
whether stored or delivered meshes count. Carried in `docs/deferred-legal-tasks.md:368`.

**E13 — API Terms § 8.1 flows Pixazo's protections down into our own End User terms.
[LEGAL]**
*Status: unchanged; re-read verbatim. Open since 2026-09-28 (7 days).* Our Terms of
Service (Task L1) must be "no less protective of Pixazo than" the API Terms before any
End User reaches the `pixazo` backend. Carried in `docs/deferred-legal-tasks.md:372`.

## 7. Delivery: both branches, reported separately

Delivery is still undecided, and the two branches carry different obligations. They are
not collapsed into one recommendation.

**SaaS-hosted** — we run the images; nothing is distributed.
- **AGPL § 13 still attaches**, because it is triggered by network-facing use rather
  than by distribution. The isolation that answers it is architectural and is recorded
  in `pythonsrc/licence_policy.py`: CuraEngine is invoked as a CLI subprocess
  (`ARM_LENGTH_COMPONENTS`), OctoPrint is reached over HTTP/SockJS, and
  `AGPL_IN_PROCESS_PACKAGES` denies `octoprint`, `libarcus`, `libsavitar` and `uranium`
  as Python distributions. **This is the one obligation SaaS does not remove**, and it
  is the reason the in-process/arm's-length distinction in the policy is load-bearing
  rather than cosmetic.
- **Removed:** the Ubuntu GPL written-offer-for-source duty, the NVIDIA CUDA EULA
  Attachment A redistribution limits, and the `triton` bundled-tools question. Nothing
  leaves our infrastructure, so none of the three is engaged.
- The Pixazo obligations are **unaffected** by this choice. § 8.1 (E13) binds whenever
  an End User reaches the backend, however the software is delivered.

**Shipped Docker images** — a customer runs them.
- Base images that would ship: `ubuntu:22.04`, `python:3.10-slim`, `node:20-alpine`,
  and `nvidia/cuda:12.4.1-devel-ubuntu22.04` for the worker.
- **Ubuntu** brings the GPL source-offer duty for every GPL package in
  `sbom/base-ubuntu-22.04.json` (101 packages).
- **NVIDIA CUDA EULA Attachment A** limits which CUDA components may be redistributed,
  and the `triton` bundled-tools question (first raised 2026-09-19) turns on whether
  `torch==2.6.0+cu124` pulls `triton` into the worker image. **Neither can be assessed
  today**, because the worker tree is unscanned — this is E7 wearing a different hat,
  and it is the single largest unknown on this branch.
- AGPL § 13 applies here too, through the customer's own network use.

**The asymmetry to hold onto:** SaaS retires three obligations and E7's redistribution
half; shipping images retires none and makes E7 blocking. E7 is cheap on the SaaS branch
and load-bearing on the other.

## 8. What I would do first

Ordered by leverage, separated by who does the work.

**Vendor email — one letter to Pixazo** (`support@pixazo.ai` is the only API contact the
API Terms give). Unchanged from 09-28 and still unsent; this is the highest-leverage
item in the report, and a second week has passed without it.
1. **E3:** which background-removal and conditioning weights `trellis-2-image-to-3d`
   runs. Still the blocker, and nothing published will answer it. § 5.6.1 promises the
   model page carries this; the page does not, which is a fair thing to say in the
   letter.
2. **E5:** written confirmation that § 6.4 covers 3D mesh output as "other media" and
   that Pixazo claims no rights in it. A yes/no question.
3. **E12:** confirmation that § 9.4's "cached API responses" does not reach meshes
   already stored or delivered.
4. **E6:** the warranty and IP-indemnity carve-out. Expect a refusal, and treat the
   refusal as the answer.

**Engineering — independent of the letter.**
5. **E4:** book the USD list price and convert at the ECB rate on the job date, rather
   than re-pinning a EUR constant. The figure has now moved on three consecutive watches
   without anyone touching it, which is the whole argument. § 4.1's 30-day notice covers
   a list-price change; only a dated conversion covers the rate. Note `PRICE_EUR_PER_GENERATION`
   and `generation_cost_eur` sit behind the "anything that spends money" rule in
   `CLAUDE.md`, so this needs its own issue.
6. **E8:** write a standing decision for the distro aggregates, then triage the
   remainder into `2026-10-01-licence.md`. Thirteen audits deep and 1 477 flags is past
   the point where the gate carries signal; `certifi` and `tqdm` are two concrete
   `REVIEWED_WEAK_COPYLEFT` candidates to start from.
7. **E7:** produce `python-worker.json` the next time a CUDA host is available. It
   closes E1 and E2 outright and is the gating unknown for the shipped-images branch.

**Legal — after the letter is answered.**
8. **E13, with Task L1.** The flow-down belongs in the Terms of Service, which do not
   exist. Nothing changes until they do, because `ALLOW_PROMPT_JOBS` is off by default
   (#168) and no End User reaches `pixazo`.
9. **E9 (Task L5).** Re-accept DINOv3 as the company. Independent of Pixazo.

**Routine.** The 09-28 hygiene item is done and should stay done: enumerate every
`legal`/`terms`/`policy` link on a vendor's terms page rather than fetching the obvious
URL. Doing it this run is what established there is no third Pixazo document.
