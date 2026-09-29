# External licence watch — 2026-09-28

This watch covers what the automated pipeline cannot reach: vendor terms of service,
upstream relicensing, and whether earlier blockers are still live. It was written by
hand, and it does not re-derive the dependency tree. That tree comes from
`.github/workflows/licence-data.yml` and `infra/scripts/licence_report.py`, and it is
this report's input.

It amends **[`2026-09-21-external-licence.md`](2026-09-21-external-licence.md)**,
including the correction block at its head. It keeps the E-numbers from 2026-09-19,
which that report declared permanent.

**This is not legal advice.** Items marked **[LEGAL]** need a lawyer and are carried in
`docs/deferred-legal-tasks.md`.

---

## Headline

**Pixazo has a separate API contract, and the last two watches never read it.**
*Pixazo API Services — Supplemental Terms & Conditions* has been at
<https://www.pixazo.ai/api-terms-of-use> since **9 April 2026**. It says it **prevails
over the Terms of Use for API Services**, and its § 6.4 reads: "Pixazo does not claim
ownership of Output Content generated through the API Services."

That removes most of the force of **E5**. On 2026-09-21, E5 was this report's
highest-consequence item: the concern that Appy Pie LLP owns every mesh under
§ 5.3.1. It also means two new obligations bind us: **E12** and **E13**, below.

The weights behind the endpoint (**E3**) are still undisclosed, and that is still the
blocker.

## 1. Freshness

**The data is 13 days old and still inside the 20-day threshold. The next scheduled run
is 2026-10-01.**

- `licenses/report.json` — `generated_at` **2026-09-15T09:31:11Z**, commit `01b15e7`.
  Verdict `flag`, 2 488 packages across 12 sources, **0 denials / 1 384 flags**,
  79 finding rows, and `missing_sources` is empty. Nothing has changed since
  2026-09-21.
- The newest generated audit is still **`2026-09-15-licence.md`**, and its digest
  matches the report: `allow 1104 / flag 1384 / deny 0`.
- **`licenses/python-worker.json` still does not exist.** The TRELLIS.2 GPU worker has
  never been scanned. The command that produces the file on a CUDA host is in
  `licenses/README.md`. With no scan, **no package installed by
  `infra/docker/trellis2-worker.Dockerfile` has a scanned licence**. That includes
  `easydict`, `imageio-ffmpeg`, `tqdm`, `ninja` and the four compiled CUDA extensions.
  This is **E7**.
- **The judgement half of `2026-09-15-licence.md` is empty.** Nothing follows
  `<!-- generated:end -->` (line 296 of 296). The same is true of every generated audit
  since 2026-08-31, and none has been added since. This is **E8**.

## 2. What changed since 2026-09-21

1. **The API Services Terms were found and read.** This is new to this watch series,
   not new at Pixazo. The document was last updated 9 April 2026. The 09-19 and 09-21
   archives read only the consumer Terms of Use and the model page. § 7.9.2 of the
   Terms of Use names "the Pixazo API Services Terms", and `/terms-of-use` links to it.
   **How it was missed:** both earlier runs looked for the terms at the obvious URL and
   stopped there. From now on the routine should enumerate the `terms`/`legal`/`policy`
   links on the terms page.
2. **The Terms of Use moved again.** They were last updated **24 September 2026**
   (14 September at the previous watch). The visible addition is **§ 7.9, Pixazo Free
   Tier**, in effect since 20 September 2026. It gives each API account free monthly
   usage of USD 10 for image, USD 5 for video and USD 2 for audio. **3D is not
   covered**, and `/api/free` lists five models, none of them Trellis. So no Trellis
   generation lands in "Free Content" through the free tier. § 5.3, § 11.1, § 13.1 and
   § 15.1 are unchanged in substance. The earlier archives are summaries, so they
   cannot show whether the § 5.6.1 sentence "Key restrictions are summarised on the
   relevant model's page" is new.
3. **The price is unchanged; the exchange rate moved.** The list price is still
   USD 0,35. At the ECB rate of **1,1403 (2026-09-25)** that is EUR 0,3069, so the
   overstatement in **E4** falls to 4,26 %.
4. **Dependencies added since 2026-09-21: `fonttools` becomes direct.** Merge `e168d3e`
   (#171, decorative tier) did two things:
   - It pins `fonttools==4.61.1` in `requirements-base.txt` and adds `fonttools>=4.50`
     to the `server`, `pipeline`, `phase2` and `phase3` images. PyPI gives the licence
     as `MIT`. It was already in the scanned pipeline tree as a transitive dependency
     (`fonttools@4.65.0`, `MIT`), but it is **not in `python-api-server.json`**, because
     that scan predates the change. This is part of **E10**.
   - It vendors `pythonsrc/organizer/fonts/DejaVuSans-Bold.ttf` (DejaVu 2.35, Bitstream
     Vera licence plus public-domain changes). A vendored file is not a package, so
     neither `pip-licenses` nor `syft` will ever list it. It is recorded by hand in
     `THIRD-PARTY-NOTICES.md` § 2, with the upstream `LICENSE` beside it and a sha256.
     The file is unmodified, which respects the Bitstream Vera rename-on-modify
     condition. Nothing more is needed.

   The EU and 28DIGITAL funding marks added in `632fbc8` are trademark and
   funding-visibility assets, not licensed dependencies. `THIRD-PARTY-NOTICES.md` already
   excludes them from the Apache-2.0 grant. They are out of scope here.

## 3. Vendor terms

I built the vendor list by grepping the code for outbound endpoints. It is unchanged
since 2026-09-21:

| Endpoint | Where | Paid | Section |
|---|---|---|---|
| `https://gateway.pixazo.ai` | `pythonsrc/sculptors/pixazo.py:46` | **Yes — EUR 0,32/gen booked** | § 3.1 |
| `https://huggingface.co` | `server/app.py` (token check) + weight downloads | No | § 3.2 |
| OctoPrint / Moonraker | `pythonsrc/operators/` | No | The operator's own printer on the LAN. No vendor |

**Phase 1 still has no hosted vendor.** `pythonsrc/visualizer.py` is unchanged since
2026-09-21, and it still builds a local `diffusers` pipeline from `FLUX_MODEL_PATH`.
`config.template.py` names no image API.

### 3.1 Pixazo (Appy Pie LLP)

**Archived copy: [`vendor-terms/pixazo-2026-09-28.md`](vendor-terms/pixazo-2026-09-28.md).**
Sources: `/api-terms-of-use` (last updated 9 April 2026), `/terms-of-use` (last updated
24 September 2026), `/models/trellis3d` and `/api/free`, all retrieved 2026-09-28.
Quotations were checked against the raw HTML.

**(a) Ownership: Pixazo disclaims it for API output. Downgraded, still [LEGAL].**
- API Terms § 6.4: "Pixazo does not claim ownership of Output Content generated through
  the API Services."
- The precedence clause: "In the event of a conflict … these API Terms shall prevail
  with respect to API Services."

The 09-21 argument ran: no subscription, so not § 5.3.2, so § 5.3.1, so Appy Pie owns
the output. That argument was built on the wrong document.

Two limits stop this from closing E5:
- "Does not claim" is not an assignment to us.
- "Output Content" is defined as "images, videos, audio, or other media". A mesh is
  presumably "other media", but the text does not say so.

The question for a lawyer is now narrow and confirmatory: does § 6.4 govern Trellis
output, and does it leave the mesh with us? The earlier question was whether the
business was running on a revocable licence.

**(b) There is no warranty, and the indemnity runs from us to Pixazo.**
- API Terms § 6.2 disclaims "originality, legality, non-infringement".
- § 6.4 and § 10.1 put the indemnity on the Client.
- § 10.2 caps Pixazo's liability at 12 months' fees.

This is the same position as 09-21 under new citations. **E6** stands.

**(c) The weights are still undisclosed, and the page the terms point to is silent.**
Terms of Use § 5.6.1 puts compliance on the user and says "Key restrictions are
summarised on the relevant model's page". The Trellis 2 page's raw HTML has no
occurrence of "licen", "commercial", "Microsoft", RMBG, BiRefNet or DINO. API Terms
§ 6.1 calls Pixazo a "third-party configuration layer" and names no model.

Stock `microsoft/TRELLIS.2-4B` still wires `RMBG-2.0` and
`dinov3-vitl16-pretrain-lvd1689m` in `pipeline.json` (re-fetched today). RMBG-2.0 is
still "CC BY-NC 4.0", with "Commercial use is subject to a commercial agreement with
BRIA".

**Result: UNKNOWN — unverified. BLOCKER. E3.**

Sources tried this run: the API Terms, the Terms of Use, the model page, the free-tier
page and the pricing page. None names an upstream component.

**(d) Price: the list price is unchanged and the constant still overstates it.**

| | |
|---|---|
| List price | USD 0,35 per generated 3D model |
| ECB reference rate | **USD 1,1403 = EUR 1, 2026-09-25** |
| Converted | **EUR 0,3069** |
| `PRICE_EUR_PER_GENERATION` | EUR 0,32 (implies 1,09375) |
| Overstatement | EUR 0,0131 per generation, **4,26 %** (EUR 320,00 booked vs EUR 306,94 payable per 1 000) |

The API Terms § 4.1 add one useful fact: prices "are subject to change with thirty (30)
days' advance notice". So a list-price change has a notice channel. Exchange-rate drift
does not. **E4.**

**(e) New obligations under the API Terms.** These are the other side of finding the
document:
- **§ 9.4, termination.** The Client must "delete any cached API responses".
  `PixazoSculptor._cache_glb` caches every purchased GLB by design. Does a stored mesh,
  or one already printed and handed over, count as a "cached API response"? The terms
  do not say. If it does, termination would reach back into delivered work.
  **[LEGAL] New as E12.**
- **§ 8.1, flow-down.** The Client must hold enforceable End User agreements "no less
  protective of Pixazo than those contained in these API Terms". That puts a
  requirement on our own Terms of Service, which do not exist yet (Task L1).
  **[LEGAL] New as E13.**
- **§ 3 and § 6.3** prohibit exposing endpoints to End Users, reselling API access and
  training on Output Content. Moderation is required before output is released. The
  current design calls the API server-side, gates on IP screening and a human verdict,
  and trains nothing. On that reading it complies, so these are notes and not findings.

**(f) Governing law.** The API Terms give "Laws of India" and have no forum clause. The
Terms of Use § 15.1 give New Delhi. This is unchanged. **E11.**

### 3.2 Hugging Face Hub

I checked the Terms of Service (<https://huggingface.co/terms-of-service>, retrieved
2026-09-28). The effective date is still **15 September 2022**, governing law is New
York, and the terms still say nothing about gated repositories. **They are unchanged.
The archive from [`vendor-terms/huggingface-2026-09-19.md`](vendor-terms/huggingface-2026-09-19.md)
stands, and I did not archive a new copy.**

Model repos, checked through the HF API today:

| Repo | Gated | Licence |
|---|---|---|
| `facebook/dinov3-vitl16-pretrain-lvd1689m` | **manual** | `other` (DINOv3 Licence) |
| `briaai/RMBG-2.0` | auto | "CC BY-NC 4.0" (model card) |
| `ZhengPeng7/BiRefNet` | no | `mit` |
| `microsoft/TRELLIS.2-4B` | no | `mit` |

## 4. Upstream relicensing

**No component in `ARM_LENGTH_COMPONENTS` or `REVIEWED_WEAK_COPYLEFT` has relicensed.**
Everything below was read from the primary source today:

- **CuraEngine.** `LICENSE` is AGPL v3, and `conanfile.py:18` reads
  `license = "AGPL-3.0"` (`Ultimaker/CuraEngine@main`). `Ultimaker/Cura` reads
  `license = "LGPL-3.0"` (`conanfile.py:28`), but that is the frontend, not the engine.
- **OctoPrint.** `LICENSE.txt` is AGPL v3 (`OctoPrint/OctoPrint@master`).
- **`psycopg`**, **`psycopg-binary`** and **`psycopg-pool`.** PyPI gives
  `LGPL-3.0-only` (latest versions 3.3.6, 3.3.6 and 3.3.3). `psycopg/pyproject.toml:18`
  agrees.
- **`pywebpush`** 2.5.0 is `MPL-2.0`, and **`py-vapid`** 1.9.4 is `MPL-2.0`.
- **`opencv-python-headless`** is `Apache 2.0`. The latest release is now
  **5.0.0.93**, a new major version, and we pin `4.13.0.92`. The licence did not
  change. If the pin is ever bumped to 5.x, re-check the bundled FFmpeg build at that
  point.

## 5. Closed / downgraded

- **The August local-TRELLIS.2 register is still dead.** `nvdiffrast`, `nvdiffrec`,
  `plyfile`, `libigl`, `cubvh`, `pymeshfix`, `torchmcubes`, `triposr` and `pymeshlab`
  have zero occurrences across `licenses/report.json`, `licenses/*.json` and
  `licenses/sbom/*.json`. No workflow builds `trellis2-worker`, which is behind
  `--profile gpu-worker` in `infra/docker-compose.yml`. The deny-list stays in place.
- **E5 is downgraded** from highest-consequence to confirmatory, on the strength of API
  Terms § 6.4 and the precedence clause (§ 3.1(a)). It is not closed. See § 6.
- **E1 and E2 stay open.** `easydict` and `imageio-ffmpeg` also have zero occurrences in
  the scans, but only because the worker tree is unscanned (E7). They are still
  installed at `infra/docker/trellis2-worker.Dockerfile:62`. 2026-09-21's correction
  block explains why that is not a reason to close them.

## 6. Still open

"Open since" counts from the 2026-08-27 baseline unless stated otherwise. Today is
2026-09-28.

**E1 — `easydict` (PyPI: `LGPL-3.0`, v1.13) is in the worker image with no recorded
decision.**
*Status: unchanged, and dormant while the worker does not ship. Open since 2026-09-19
(9 days).* It closes when E7 produces `python-worker.json` and a decision is recorded.

**E2 — `imageio-ffmpeg` bundles an FFmpeg binary whose build licence is unknown.**
*Status: unchanged, and dormant. Open since 2026-09-19 (9 days).* The package itself is
`BSD-2-Clause` (PyPI, 0.6.0). The binary it ships is the open question, and no primary
source states whether that binary is LGPL or GPL. It closes on the same condition as E1.

**E3 — The weights behind `trellis-2-image-to-3d` are UNKNOWN — unverified. BLOCKER.**
*Status: unchanged. Open ~4,5 weeks (32 days), and unverified since August 2026.* See
§ 3.1(c). Five Pixazo pages were tried this run. The model page that § 5.6.1 points to
summarises no restriction. Only a written answer from Pixazo can close this.

**E4 — `PRICE_EUR_PER_GENERATION` overstates cost by 4,26 %.**
*Status: re-quantified at ECB 1,1403 (2026-09-25). Open ~4,5 weeks.* It was 4,78 % on
09-21. The cause is exchange-rate drift, not a price change. This is engineering, not
legal work.

**E5 — Pixazo output ownership. [LEGAL]**
*Status: **downgraded this run**. Open ~4,5 weeks.* API Terms § 6.4 says Pixazo "does
not claim ownership of Output Content generated through the API Services", and the API
Terms prevail. What remains for a lawyer to confirm:
- Does "other media" cover a mesh?
- Does disclaiming ownership leave the mesh with us?

The 09-19 point about the *Generative AI Additional Terms* (5 June 2025), which prohibit
"intermediation/resale", was **not re-checked** this run. It now matters less, because
two Pixazo-specific documents, one with a precedence clause, sit above it.

**E6 — No warranty of non-infringement; the indemnity runs from us to Pixazo. [LEGAL]**
*Status: unchanged in substance, with new citations: API Terms § 6.2, § 6.4, § 10.1,
§ 10.2. Open ~4,5 weeks.*

**E7 — `licenses/python-worker.json` does not exist.**
*Status: unchanged. Open ~4,5 weeks.* Producing it closes E1 and E2.

**E8 — No generated audit has been triaged since the baseline.**
*Status: unchanged. Open since 2026-08-31 (28 days).* Twelve audits have empty
judgement halves, and 1 384 flags stand unread. Two facts gathered this run would help
whoever does the triage:
- `certifi` is `MPL-2.0` on PyPI.
- `tqdm` is `MPL-2.0 AND MIT`.

Both are weak copyleft at file level and are not yet in `REVIEWED_WEAK_COPYLEFT`.

**E9 — DINOv3: the licensee may be a person rather than the company. [LEGAL]**
*Status: unchanged. The repo is still gated `manual`. Open ~4,5 weeks.* Task L5.

**E10 — The scanned trees are behind `main`.**
*Status: one package wider this run. Open since 2026-09-21 (7 days).*
- Carried from 09-21: `pywebpush`, `ruff` and `@playwright/test`.
- New this run: `fonttools` in the api-server image. It is MIT, so it adds no exposure.

This closes on the 2026-10-01 scheduled run.

**E11 — Indian law and a New Delhi forum.**
*Status: unchanged. Open since 2026-09-21 (7 days).* This is context for E5, E6, E12
and E13, not a defect.

**E12 — On termination, API Terms § 9.4 requires deleting "any cached API responses".
[LEGAL]**
*Status: new this run. Open 0 days.* `PixazoSculptor._cache_glb` caches purchased GLBs
on purpose. The terms do not say whether stored or delivered meshes count as cached
responses.

**E13 — API Terms § 8.1 flows Pixazo's protections down into our own End User terms.
[LEGAL]**
*Status: new this run. Open 0 days.* Our Terms of Service (Task L1) must be "no less
protective of Pixazo than" the API Terms before any End User reaches the `pixazo`
backend.

## 7. What I would do first

Ordered by leverage.

**Vendor email: one letter to Pixazo** (`support@pixazo.ai` is the only API contact the
API Terms give). It should ask for:
1. **E3:** which background-removal and conditioning weights `trellis-2-image-to-3d`
   runs. This is still the blocker, and nothing published will answer it.
2. **E5:** written confirmation that § 6.4 covers 3D mesh output as "other media", and
   that Pixazo claims no rights in it. This is now a yes/no question.
3. **E12:** confirmation that § 9.4's "cached API responses" does not reach meshes
   already stored or delivered.
4. **E6:** the warranty and IP-indemnity carve-out. Expect a refusal, and treat the
   refusal as the answer.

**Engineering: small, independent of the letter.**
5. **E4:** book the USD list price and convert at the ECB rate on the job date,
   instead of re-pinning a EUR constant that will drift again. § 4.1's 30-day notice
   covers list-price changes, and only a dated conversion covers the exchange rate.
6. **E8:** write a standing decision for the Ubuntu or distro aggregates, then triage
   the remainder into `2026-09-15-licence.md`, or into the 2026-10-01 audit once it
   lands.
7. **E7:** produce `python-worker.json` the next time a CUDA host is available.
8. **Routine hygiene:** enumerate every `legal`/`terms`/`policy` link on a vendor's
   terms page, not just the page itself. That is how the API Terms were missed twice.

**Legal work: start after the letter is answered.**
9. **E13, together with Task L1.** The flow-down belongs in the Terms of Service, which
   do not exist yet. Until they do, nothing changes, because `ALLOW_PROMPT_JOBS` is off
   by default (#168) and no End User reaches `pixazo`.
10. **E9 (Task L5).** Re-accept DINOv3 as the company. This is independent of Pixazo.
