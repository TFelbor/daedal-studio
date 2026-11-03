# External licence watch — 2026-09-21

The surfaces the automated pipeline structurally cannot reach: vendor terms of service,
upstream relicensing, and whether last week's blockers are still alive. Written by hand.
Nothing here re-derives the dependency tree — `.github/workflows/licence-data.yml` and
`infra/scripts/licence_report.py` do that better, and their output is the input to this.

**Not legal advice.** Items marked **[LEGAL]** need counsel and are carried in
`docs/deferred-legal-tasks.md`.

---

> ### Correction — issued after this report was merged
>
> This run was written against a working tree that did not yet have the **2026-09-19**
> external watch in it, and it was merged without that being reconciled. Four things it
> says are wrong, and they are recorded here rather than quietly edited away, because a
> dated audit is a snapshot and the useful question about a wrong one is *how it went
> wrong*. The sections below are corrected; this block is what they said before.
>
> 1. **§ 2 claimed to be the first external watch.** It said "there is no prior
>    `docs/audits/*-external-licence.md` to amend" and that a `find` for it "returns
>    nothing". The 2026-09-19 watch and two `vendor-terms/` files were already on `main`
>    (#167, `7cfa893`), which is the commit this report's own branch forked from. § 2 is
>    rewritten below as the delta it should always have been.
>
> 2. **The E-numbers collided with a set already declared permanent.** 2026-09-19 § 6
>    says "Numbered E1…E5; these numbers are permanent and later runs keep them." This
>    report reused E1–E5 for different items and then said the same of its own. Two
>    consecutive reports naming different findings "E1" makes every cross-reference in
>    `docs/deferred-legal-tasks.md` ambiguous. § 6 is renumbered onto 09-19's set, with
>    the mapping kept so this run's numbering is still readable.
>
> 3. **`easydict` and `imageio-ffmpeg` were closed on a vacuous test.** § 5 closed them
>    because they "appear nowhere in any scanned tree". They appear nowhere because
>    **the worker tree has never been scanned** — which is this same report's E4/E7 —
>    and `easydict` (LGPL-3.0) is installed at `infra/docker/trellis2-worker.Dockerfile:62`
>    today. 2026-09-19 carried them as E1 and E2 and made exactly this point. Closing an
>    item whose tree is unscanned is the failure the delta chain exists to catch, and
>    here the chain did catch it — one merge late. Both are restored to open.
>
> 4. **The ownership finding was dated "Open 0 days".** It is 09-19's E5, open since the
>    August baseline. What is genuinely new is narrower and is stated as such below: the
>    Trellis 2 API page offers no subscription at all, so § 5.3.2's "active subscription
>    period" cannot describe a wallet-funded caller.
>
> Found by `claude-review` on #169 after the merge. The reviews ran late because the
> pull requests sat as drafts until the moment they were merged — see
> `docs/PIPELINE.md` § The draft comes first.

---

## 1. Freshness

**The fortnightly workflow ran, and the data is current.**

- `licenses/report.json` — `generated_at` **2026-09-15T09:31:11Z**, commit
  `01b15e7`. **6 days old** against a 20-day staleness threshold.
- Schedule is the 1st and the 15th (`licence-data.yml`). 2026-09-15 landed on time; the
  next scheduled run is **2026-10-01**.
- Verdict `flag`, 2 488 packages across 12 sources, **0 denials / 1 384 flags**,
  79 finding rows. `missing_sources` is empty.

Two qualifications on that freshness:

- **`licenses/python-worker.json` still does not exist.** The TRELLIS.2 GPU worker image
  compiles four CUDA extensions against a GPU architecture no hosted runner has, so CI
  has never scanned it. The one command that produces it on a CUDA host is in
  `licenses/README.md`. **No package in the worker tree has a scanned licence** — that
  is the tree where `nvdiffrast`/`nvdiffrec` would surface if they were ever installed,
  which is exactly why it is the one that matters. Carried as **E7**.
- **The scanned trees are three packages behind `main`.** `pywebpush==2.5.0`,
  `ruff==0.16.7` and `@playwright/test@^1.63.0` were added after commit `01b15e7` and
  appear in no scanned tree. All three were checked by hand this run and none is a new
  exposure — see § 5. Carried as **E10**.

**The judgement half of every generated audit since 2026-08-31 is empty.** Not the last
one, and not the last two: **all twelve** of `2026-08-31` through `2026-09-15` carry
nothing outside the generated fence — checked file by file this run. The last hand-written
judgement in `docs/audits/` is the 2026-08-27 baseline, 44 lines, three weeks ago. So
1 384 flags now stand with no recorded reading, and the mechanism the directory is built
around — the generated block reports, a person judges below it — has not been exercised
since the day it was created. The rows the 2026-09-15 delta named new — the `sbom/ds-mvp-pipeline.json` copyleft aggregates
(`os-strong_copyleft:106`, `os-unknown:160`, `os-weak_copyleft:32`, `unreadable-unknown:18`),
`python-apt@2.4.0` (GPL, distro-provided), `pygobject`, the `launchpadlib`/`lazr`/`wadllib`
LGPL family, `autocommand`, `bidict`, `certifi` and `tqdm`. Carried as **E8**.

## 2. What changed since the last external watch

The last one is **2026-09-19**, two days ago, and this is the second in the series. See
the correction block above for what this section said before.

**Genuinely new in two days: one fact.** Pixazo's Trellis 2 API page sells pay-per-use
wallet credits — USD 0,35 a generation, `402` on insufficient funds — and offers **no
subscription for API access at all**. 09-19 had read § 5.3's plan split and left the
question open as "which of the two a usage-based API key falls under, the terms do not
say". The no-subscription fact answers half of it: § 5.3.2's "active subscription
period" cannot describe a wallet-funded caller, so it is § 5.3.1 — output owned by
Appy Pie LLP — that is written for everyone this clause does not cover. That sharpens
**E5**; it does not open a new item.

**Re-verified, unchanged since 09-19:** the Pixazo terms themselves (still "last
updated 14 September 2026" — the same date 09-19 recorded, so the 14 September movement
belongs to that run and not to this one), § 11.1's non-infringement disclaimer, § 13.1's
indemnity direction, § 5.6's assignment of third-party model licences, § 15.1's Indian
law and New Delhi forum, RMBG-2.0's CC BY-NC terms, and CuraEngine / OctoPrint /
`psycopg` / `pywebpush` / `py-vapid` / `opencv-python-headless`.

**Carried forward from 09-19 unchanged:** E1 (`easydict`), E2 (`imageio-ffmpeg`) and E3
(the undisclosed weights). See § 5 for why the first two are not closed.

**Dropped by this run and reinstated by the correction:** the Appy Pie *Generative AI
Additional Terms* (5 June 2025), which contain no assignment, state that Appy Pie "does
not guarantee ownership of AI-generated content", and prohibit "intermediation/resale".
Which of the two documents governs an API call to `gateway.pixazo.ai` is one of the
three counsel items in the 09-19 block of `docs/deferred-legal-tasks.md`, and this run
neither re-checked it nor said it had not. **It was not re-checked. It stands as 09-19
left it**, and it is folded into E5 below rather than being silently absent.

Numbering: 09-19's **E1…E5** are permanent and are kept. Items genuinely first raised
here are **E6 onward**.

## 3. Vendor terms

The list is derived from the code, not from the routine's prompt. Outbound calls to a
third party, from `grep`ping every `https://` in `pythonsrc/`, `server/` and `services/`:

| Endpoint | Where | Paid | Terms reviewed |
|---|---|---|---|
| `https://gateway.pixazo.ai` | `pythonsrc/sculptors/pixazo.py:46` | **Yes — EUR 0,32/gen booked** | § 3.1 |
| `https://huggingface.co` | `server/app.py:5373` (token check) + weight downloads | No | § 3.2 |
| OctoPrint / Moonraker | `pythonsrc/operators/` | No | Not a vendor — the operator's own printer on the LAN, self-hosted, no third-party terms |

**Phase 1 has not acquired a hosted vendor.** `pythonsrc/visualizer.py` still builds a
`diffusers.DiffusionPipeline` from `FLUX_MODEL_PATH` on local disk, and
`config.template.py` names no image API key or gateway. The planned hosted text-to-image
endpoint remains unchosen, so there is no second vendor to review. One line, as promised.

### 3.1 Pixazo (Appy Pie LLP) — archived

**Archived copy:** not published (it quoted the vendor's terms; read the primary source).
Primary sources: <https://www.pixazo.ai/terms-of-use> and
<https://www.pixazo.ai/models/trellis3d>, both retrieved 2026-09-21.

**The terms moved.** Effective 16 September 2025, **last updated 14 September 2026** —
seven days before this retrieval, and the first movement since the August baseline. They
were read in full this run rather than assumed unchanged.

Four findings, in order of how much they cost if wrong.

**(a) Who owns the mesh is genuinely unsettled. [LEGAL] — new this run.**
§ 5.3.1 still assigns free-plan output to Appy Pie LLP; the August position stands.
§ 5.3.2 gives **full ownership to paid subscribers, for content created during an active
subscription period**. But the Trellis 2 API page prices the endpoint as **pay-per-use
against a wallet balance** — "Your request will cost $ 0.35 per generated 3D model", a
`402` on insufficient funds, a first-payment credit bonus — and **offers no subscription
at all** for API access. A wallet-funded caller has no subscription period, so the clause
that would hand us the mesh does not describe how we buy, and the clause that hands it to
Appy Pie LLP is the one written for everyone else. The document does not say whether a
topped-up wallet makes a "Paid User" for § 5.3 purposes.

This decides whether the object this business prints and sells belongs to it. It is a
construction question on someone else's contract and it is not answerable from here.

**(b) No warranty of non-infringement, and the indemnity points the wrong way.**
§ 11.1 disclaims merchantability, fitness, title **and non-infringement**. § 9.1–9.2
disclaim output quality and uniqueness. § 13.1 has the **user indemnify Pixazo** for
third-party IP, privacy and publicity claims — nothing runs back. The posture
`THIRD-PARTY-NOTICES.md` assumed is now **verified from the text**, and the specific
warranty Task L4 asks Pixazo to give is the specific one § 11.1 refuses.

**(c) The upstream weights are still invisible, and § 5.6 makes that our problem.**
§ 5.6 says third-party models are "governed by their own licences" and names Flux,
DALL-E, Stable Diffusion, Ideogram. **TRELLIS.2 is not named**; the model page discloses
no upstream component whatsoever. So the deployment behind `trellis-2-image-to-3d`
remains **UNKNOWN — unverified**, as it has been since August 2026.

§ 5.6 is worse than silence: it does not merely decline to warrant the model licences, it
**expressly assigns them to the customer**. If the endpoint runs stock
`microsoft/TRELLIS.2-4B`, its `pipeline.json` configures
`BiRefNet(model_name="briaai/RMBG-2.0")`, and RMBG-2.0 is **CC BY-NC 4.0, commercial use
"subject to a commercial agreement with BRIA"** (verified 2026-09-21). `permissive_rembg()`
substitutes MIT BiRefNet before pipeline construction on `trellis2` and `remote`; it
cannot reach someone else's process. DINOv3's "Built with DINOv3" attribution duty flows
on the same reasoning. **This is a blocker, not a caveat, and it is now 4 weeks old.**

**(d) The price constant has drifted — but the list price has not changed.**

| Fact | Value |
|---|---|
| List price | **USD 0,35** per generation (quoted verbatim) |
| ECB reference rate | **USD 1,1460 = EUR 1, 2026-09-18** |
| Converted | **EUR 0,3054** |
| `PRICE_EUR_PER_GENERATION` | **EUR 0,32** |

EUR 0,32 implies a rate of 1,09375 — where EUR/USD sat when the backend was written. The
euro has since strengthened, so the constant **overstates** cost by **EUR 0,0146 per
generation (4,78 %)**: EUR 320,00 booked against EUR 305,41 payable per thousand
generations. Benign direction, but `generation_cost_eur` is the only money this system
books and every historical row carries it.

**(e) Governing law.** § 15.1 — Indian law, exclusive jurisdiction New Delhi, against an
SEZ unit in Noida. The pilot is in Trento. Context for weighing what § 11.1 actually
costs.

### 3.2 Hugging Face Hub

No charge and no output-ownership term in play — the Hub is a distribution channel, and
what binds is each repo's own licence, already audited in `THIRD-PARTY-NOTICES.md` § 0.
Re-verified from the model pages this run:

- `facebook/dinov3-vitl16-pretrain-lvd1689m` — licence tag **`dinov3-license`**,
  unchanged, and the repo is **still gated** ("You need to agree to share your contact
  information"). The gating is what keeps Task L5 live: the accepting party is whoever
  holds the token in `HF_TOKEN`, and if that is a personal account the licence may not
  run to the company. Carried as **E7**.
- `briaai/RMBG-2.0` — **CC BY-NC 4.0**, unchanged, commercial use subject to a separate
  BRIA agreement. Never loaded on the local path; see § 3.1(c) for the hosted one.

## 4. Upstream relicensing

Every line below is read from the upstream repository at the primary source, this run.
Nothing is inferred from a sibling project or an older version.

- **CuraEngine — no change.** `LICENSE` is the AGPL v3 text; `conanfile.py:18` reads
  `license = "AGPL-3.0"`. Verified at
  `raw.githubusercontent.com/Ultimaker/CuraEngine/main/`. **The relicense people cite is
  a different repository**: `Ultimaker/Cura` — the frontend — carries
  `license = "LGPL-3.0"` at `conanfile.py:28`. Both were fetched side by side this run so
  the distinction is evidenced rather than remembered. The arm's-length CLI-subprocess
  record in `licence_policy.ARM_LENGTH_COMPONENTS` stands.
- **OctoPrint — no change.** `LICENSE.txt` is the AGPL v3 text. Reached over HTTP/SockJS
  from `pythonsrc/operators/`; the `ARM_LENGTH_COMPONENTS` and `ARM_LENGTH_IMAGE_SBOMS`
  records stand.
- **`psycopg` — no change.** `LICENSE.txt` is the LGPL v3 text and
  `psycopg/pyproject.toml:18` reads `license = "LGPL-3.0-only"`; PyPI metadata agrees
  (`license_expression: LGPL-3.0-only`). `REVIEWED_WEAK_COPYLEFT` record stands.
- **`pywebpush` — no change.** PyPI `license_expression: MPL-2.0`.
- **`py-vapid` — no change.** PyPI `license: MPL-2.0`.
- **`opencv-python-headless` — no change.** PyPI `Apache 2.0`,
  `License :: OSI Approved :: Apache Software License`. The LGPL exposure recorded in
  `REVIEWED_WEAK_COPYLEFT` is the bundled FFmpeg, not the package licence, and the
  headless pin that keeps Qt 5 (LGPLv3) out is unchanged.

**No component in `ARM_LENGTH_COMPONENTS` or `REVIEWED_WEAK_COPYLEFT` has relicensed.**

## 5. Closed / downgraded

**Most of the August 2026 local-TRELLIS.2 findings are dead.** Re-checked this run
against `licenses/report.json`: `nvdiffrast`, `nvdiffrec`, `plyfile`, `libigl`, `cubvh`,
`pymeshfix` and `torchmcubes` appear nowhere in any scanned tree, and neither do
`triposr`, `pymeshlab` or `triangle`. `pymeshfix` was replaced
(`pythonsrc/engineer.py`) and TripoSR is gone
(`tests/test_sculptors.py::test_triposr_is_gone`). The deny-list entries in
`FORBIDDEN_RENDERER_PACKAGES` stay — they are the protection, not the exposure.

**`easydict` and `imageio-ffmpeg` are not among them, and this report originally said
they were.** Both are still installed, on one line of
`infra/docker/trellis2-worker.Dockerfile:62`:

```
imageio imageio-ffmpeg tqdm easydict opencv-python-headless ninja
```

They are absent from `licenses/report.json` because **`licenses/python-worker.json` has
never been produced** — which is E7 in this very report — not because anything removed
them. "Appears in no scanned tree" cannot close an item whose tree is unscanned; it is
the same sentence either way, and only one of the two readings is a finding.
2026-09-19 § 5 made this point in terms and carried them as **E1** and **E2**.

They stay open, with their 09-19 numbers and status unchanged:

- **E1 — `easydict`, LGPL-3.0**, in the worker image with no recorded decision. Worker
  path only; not on the organizer path.
- **E2 — `imageio-ffmpeg`**, which ships an FFmpeg binary whose build licence (LGPL or
  GPL) no primary source states.

Both are **open, dormant while the worker does not ship**, which is 09-19's wording for
these two — its "closed-pending-worker-scan" applies to *the other seven*, which are
genuinely absent from the images that are built. They stop being carried once
`python-worker.json` exists. That the GPU worker builds only under `--profile
gpu-worker` and that CI never builds it is why they are dormant, not why they would be
closed.

**The three dependencies added since the scan are checked and clear:**

| Package | Licence (verified) | Reaches a shipped image? |
|---|---|---|
| `pywebpush==2.5.0` | MPL-2.0 | **Yes** — `infra/docker/server.Dockerfile`. Already in `REVIEWED_WEAK_COPYLEFT` and `THIRD-PARTY-NOTICES.md` § 1. Recorded decision exists |
| `py-vapid`, `http-ece` (transitive) | MPL-2.0, MIT | Yes, with the above. `py-vapid` recorded; `http-ece` is permissive |
| `ruff==0.16.7` | MIT | No — lint only, no image installs it |
| `@playwright/test@1.63.0` | Apache-2.0 | No — npm devDependency, named in no Dockerfile |

**No new licence exposure.** One hygiene note: `npm run e2e:install` runs
`playwright install --with-deps chromium`, which downloads a Chromium build at runtime —
the same "check what the package downloads, not just the package" pattern CLAUDE.md
applies to model weights. It is dev-and-CI only and is redistributed nowhere, so it is a
note rather than a finding.

## 6. Still open

Numbers are **2026-09-19's**, which declared them permanent, and items first raised in
this run take E6 onward. "Open since" is measured from the 2026-08-27 baseline unless
stated.

This run originally numbered its own items E1–E9 from scratch, colliding with five
numbers already in use. The mapping, so that anything written against the first
numbering still resolves:

| as published here | corrected | item |
|---|---|---|
| E1 | **E5** | Pixazo output ownership |
| E2 | **E6** | no warranty of non-infringement; indemnity direction |
| E3 | **E3** | weights behind `trellis-2-image-to-3d` UNKNOWN |
| E4 | **E7** | `licenses/python-worker.json` does not exist |
| E5 | **E8** | no generated audit triaged since the baseline |
| E6 | **E4** | `PRICE_EUR_PER_GENERATION` overstates cost |
| E7 | **E9** | DINOv3 licensee may be a person |
| E8 | **E10** | scanned trees three packages behind `main` |
| E9 | **E11** | Indian law, New Delhi forum |
| — | **E1**, **E2** | `easydict`, `imageio-ffmpeg` — carried from 09-19, wrongly closed here (§ 5) |

**E1 — `easydict` (LGPL-3.0) is in the worker image with no recorded decision.**
*Status: carried from 2026-09-19 unchanged — open, dormant while the worker does not
ship. Open since 2026-09-19 (2 days).* Installed at
`infra/docker/trellis2-worker.Dockerfile:62`. Worker path only. It stops being carried
once E7 produces `python-worker.json`. See § 5 — this report originally closed it in
error.

The date takes 09-19 at its word: `easydict` was in the August register, but that
register's finding was about the *local* TRELLIS.2 path, and 09-19 opened this one
fresh as "open, new this run" against the worker image. Dating it from August would
claim four weeks of exposure nobody was tracking.

**E2 — `imageio-ffmpeg` bundles an FFmpeg executable of unknown build.**
*Status: carried from 2026-09-19 unchanged — open, dormant while the worker does not
ship. Open since 2026-09-19 (2 days).* Same line of the same Dockerfile; whether that
binary is LGPL or GPL is stated by no primary source. `imageio-ffmpeg` is not in the
August register at all, so 09-19 is unambiguously its first sighting. Same closing
condition as E1, and closed in error here for the same reason.

**E3 — The weights behind `trellis-2-image-to-3d` are UNKNOWN — unverified. BLOCKER.**
*Status: unchanged, and unverified since August 2026. Open ~4 weeks.* No primary source
discloses the deployment's composition. § 5.6 expressly assigns third-party model
licences to the customer. If it is stock TRELLIS.2, RMBG-2.0 (CC BY-NC 4.0) is in the
path and `permissive_rembg()` cannot reach it. **Tried this run:** the terms of use, the
Trellis 2 model/API page and the fair-use policy; none names an upstream component.
The remaining route is a written question to the vendor.

**E4 — `PRICE_EUR_PER_GENERATION` overstates cost by 4,78 %.**
*Status: carried from 2026-09-19, now quantified. Open ~4 weeks.* EUR 0,32 pinned
against EUR 0,3054 at the 2026-09-18 ECB rate. FX drift, not a price change — USD 0,35
is unchanged. Engineering, not counsel.

**E5 — Pixazo output ownership is unsettled. [LEGAL]**
*Status: carried from 2026-09-19 and* ***sharpened this run****. Open since the August
2026 baseline — ~4 weeks, not 0 days.* § 5.3.2 grants ownership to *paid subscribers
during an active subscription period*; § 5.3.1 gives free-plan output to Appy Pie LLP.
09-19 left the question as "which of the two a usage-based API key falls under, the
terms do not say". **New this run:** the Trellis 2 API page sells pay-per-use wallet
credits and offers no subscription for API access at all, so § 5.3.2 cannot describe
how this project buys. Decides whether the printed object belongs to this business.
**Highest-consequence item in this report.**

Folded in, and *not* re-checked this run — it stands as 09-19 left it: Appy Pie's own
*Generative AI Additional Terms* (5 June 2025) contain no assignment, disclaim any
guarantee of ownership, and prohibit "intermediation/resale". Which document governs an
API call to `gateway.pixazo.ai` is unanswered by either.

**E6 — Pixazo gives no warranty of non-infringement; indemnity runs user → Pixazo. [LEGAL]**
*Status: first numbered this run; the clauses were read on 2026-09-19. Open ~4 weeks.*
§ 11.1, § 13.1. The warranty Task L4 asks for is the one expressly disclaimed.

**E7 — `licenses/python-worker.json` does not exist.**
*Status: unchanged. Open ~4 weeks.* The GPU worker tree has never been scanned; no
package in it has a scanned licence. Command on a CUDA host is in `licenses/README.md`.
Refresh after any change to `infra/docker/trellis2-worker.Dockerfile`. **This is the
item that makes E1 and E2 unresolvable**, and closing it closes all three.

**E8 — No generated audit has been triaged since the baseline.**
*Status: new this run. Open since 2026-08-31 (21 days).* **Twelve consecutive audits**,
`2026-08-31` through `2026-09-15`, have an empty judgement half; 1 384 flags stand with no
recorded reading. Untriaged in the most recent delta: the four `ds-mvp-pipeline`
aggregates, `python-apt`, `pygobject`, the `launchpadlib`/`lazr`/`wadllib` family,
`autocommand`, `bidict`, `certifi`, `tqdm`. The scale is the finding — this is a habit
that lapsed, not a run that was missed, and it is why a flag in this repository currently
means "generated" rather than "read".

**E9 — DINOv3: the licensee may be a person rather than the company. [LEGAL]**
*Status: unchanged; repo confirmed still gated this run. Open ~4 weeks.*
`docs/deferred-legal-tasks.md` Task L5. Whoever accepted with the token in `HF_TOKEN` is
the accepting party. Re-accept as the corporate entity and record when and by whom.

**E10 — Scanned trees are three packages behind `main`.**
*Status: new this run. Open 0 days.* `pywebpush`, `ruff`, `@playwright/test` are in no
scanned tree. All three verified by hand (§ 5) and clear, so this is a data-currency item,
not an exposure. Closes on the 2026-10-01 scheduled run, or immediately via
`workflow_dispatch` from `main`.

**E11 — Indian law and a New Delhi forum against an SEZ unit.**
*Status: new this run. Open 0 days.* § 15.1, against a Trento pilot. Not a defect —
context counsel needs when pricing E5 and E6.

## 7. What I would do first

Ordered by leverage. The split matters: two of these cost an email, and the expensive
ones are blocked on that email.

**Vendor emails — send these first; everything legal downstream waits on the answers.**

1. **One letter to Pixazo covering E5 and E3**, because they are the same conversation
   and the answers arrive together. Ask, in writing, for (i) confirmation that a
   wallet-funded API caller is a "Paid User" owning output under § 5.3.2, and (ii) which
   background-removal and conditioning weights `trellis-2-image-to-3d` runs. E3 has been
   unverified for four weeks and no amount of reading published pages will close it —
   three primary sources were tried this run and none discloses the stack.
2. **In the same letter, ask for the § 11.1 carve-out (E6):** a warranty that outputs are
   free of third-party licence restrictions and that commercial use of the mesh is
   permitted, plus an IP indemnity. Expect refusal — the standard terms disclaim exactly
   this — but the refusal is itself the answer, and it converts E6 from an open question
   into a decision about whether the `pixazo` backend stays beta-only.

**Engineering — small, independent of the above, and closes three items.**

3. **Run `licence-data.yml` via `workflow_dispatch` from `main` (E10).** Closes the data
   gap immediately instead of waiting for 2026-10-01. Cheap.
4. **Triage the 1 384 flags into the judgement half of `2026-09-15-licence.md` (E8).** The
   aggregates are the bulk and most are Ubuntu's own packages in an image nobody
   distributes yet — but "nobody has read them" and "they are fine" are different
   statements, and only one of them is currently true. Twelve audits deep, the cheaper
   fix may be to decide what a flag is *for*: if the aggregates will never be read row by
   row, they belong in a recorded standing decision like `DISTRO_PROVIDED_PACKAGES`
   rather than in a backlog nobody works.
5. **Decide `PRICE_EUR_PER_GENERATION` (E4).** Either re-pin to EUR 0,3054 with the ECB
   rate and date in the comment, or — better, and the reason this is worth a thought
   rather than a patch — book the USD list price and convert at the rate on the job date,
   since a EUR constant against a USD list price will drift again.
6. **Produce `licenses/python-worker.json` on a CUDA host (E7)** next time one is in
   reach. Unblocked, just not runnable from here.

**Counsel — do not start before the answers to 1 and 2 land.**

7. **E5 with Task L4.** If Pixazo will not confirm ownership, the fallback needs no
   lawyer: `create_sculptor()` already makes the backend swappable, and keeping `pixazo`
   development-only costs a config change. That is the cheap resolution and it should be
   on the table before the expensive one.
8. **E9 (Task L5), re-accept DINOv3 as the corporate entity.** Independent of Pixazo and
   independently blocking at launch.
