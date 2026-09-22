# Deferred legal tasks

Two items surfaced while designing the IP controls in the pipeline. Both are legal
work products, not code, and neither is being started now. This file exists so the
context does not have to be rediscovered when they are picked up — attach it to the
task.

Everything below assumes the operating posture of the Trento pilot: Daedal Studio
takes a natural-language prompt from a user, generates a mesh, and **prints and hands
over a physical object**. That last step is what makes these necessary. A platform
that only hosts files has intermediary defences available to it; a shop that
manufactures the article does not.

---

## Task L1 — Terms of Service, user warranty, indemnity

**Why it is needed.** The infringing act in the risky case is *making and supplying*
an object that reproduces a protected character. That is direct infringement analysis:
copyright in the character as an artistic work, plus a registered EU trademark, plus
possibly a registered Community design. The Digital Services Act hosting exemptions do
not reach it, because nothing is being hosted — goods are being produced. The
private/non-commercial-use exception (Art. 20(1)(a) Community Design Regulation) covers
a person printing at home for themselves; it is expressly unavailable to a paid service
printing on their behalf.

So the operator cannot make the exposure disappear contractually. What the ToS *can* do
is (a) allocate risk to the party who chose the subject, (b) create a documented right to
refuse, and (c) evidence good faith, which is what separates an ordinary infringement
claim from an aggravated one.

**What the document has to contain, at minimum:**

- A user warranty: the user owns, or is licensed for, the rights in whatever the prompt
  describes, and the resulting object is for their own use.
- An indemnity flowing from the user to the operator for third-party IP claims arising
  from their prompt.
- An express, unconditional right to refuse or cancel any job, at any stage, without
  refund obligation beyond unspent cost — this is the contractual hook the automated IP
  screen and the human approval gate hang from. Without it, refusing a paid job is a
  breach.
- A statement that outputs are machine-generated, that no copyright is claimed in them by
  the operator, and that the operator makes no warranty of resemblance to anything the
  user had in mind. (This second half is also the honest answer to the expectation gap:
  the pipeline discards appearance and prints in one colour.)
- Data terms covering prompt retention — see the retention note below, which is a live
  code-side concern and not only a policy one.
- Governing law and forum. The pilot is in Italy, so Italian law and an Italian forum
  unless counsel prefers otherwise.

**Related code-side facts counsel will want:**

- Prompts are stored verbatim and permanently on the job row (`print_job.prompt`), and the
  engineered variant alongside it (`blueprint_prompt_engineered`). A pilot dataset full of
  franchise names is itself discoverable material. Decide a retention window and whether
  refused prompts are stored at all, or only the fact of refusal.
- The pipeline records `git_sha` per job, so "which version of the screen was running when
  this job was accepted" is answerable. Keep that — it is the good-faith evidence.

---

## Task L2 — Published notice-and-action contact and a written takedown / refusal procedure

This is the item that was unclear, so here is what it actually means. It is two things
that are usually confused with each other.

### L2a — The outward-facing contact ("notice-and-action")

A published, monitored channel — an email address or a web form, named on the site — by
which a rights holder can tell you that something you produced or offered infringes their
rights, together with a commitment about what happens next: acknowledgement of receipt, a
decision without undue delay, and a statement of what was done.

Under the DSA this mechanism is a **hard obligation for hosting services** (Art. 16), with
member-state penalties reaching 6% of turnover for non-compliance. Whether Daedal Studio is
a hosting service depends on product decisions not yet made: the moment there is a public
gallery of user prints, a shared model library, or user-uploaded files visible to others,
it very likely is one. Today, printing to order, it probably is not.

**But it is worth having before it is mandatory**, for a reason independent of the DSA: a
rights holder who finds an infringing print and has an obvious place to complain sends a
notice. One who does not, sends a lawyer. The channel converts the expensive failure mode
into the cheap one, and a documented record of prompt compliance is the single strongest
mitigation available on damages and willfulness.

**Deliverable:** a short public page — contact address, what information a notice should
contain (identification of the right, the allegedly infringing job or listing, contact
details, a good-faith statement), the response target, and a counter-notice route for the
user whose job was refused.

### L2b — The internal written procedure

The other half, and the one that actually gets used. A one-page runbook stating, for a
notice or an internal flag:

- Who triages it and within what time.
- What happens to a job at each pipeline stage — queued, mid-generation, sliced and
  awaiting dispatch, printing, printed and unshipped, shipped. These are materially
  different: the system already distinguishes them (`dispatch_state`, and the print
  outcome column), and "cancel before the nozzle heats" is a different action from
  "recall a shipped part".
- Whether and how the artifacts are deleted, and what is retained as a record of the
  decision. Deleting everything destroys your own evidence of having acted; keeping
  everything keeps the infringing file. The usual answer is: destroy the deliverable,
  retain the decision record.
- Who may refuse a job outright, and on what standard. The automated screen produces
  flags, not verdicts; someone has to own the borderline cases.
- Escalation to counsel, and the threshold for it.
- Where the decision is logged. The code side should carry this: an IP-screen decision is
  recorded as a job event, and a human refusal should be too, so "how often did we refuse,
  and were we right" is a query rather than an inbox search.

**Deliverable:** an internal runbook, plus whatever code-side event types the procedure
implies. Flag those back to engineering — a procedure that cannot be logged is a procedure
nobody can audit.

---

---

## Task L3 — Decide the outbound licence, deliberately

**This is a choice, not an obligation, and the two halves of it are unrelated.** They
got conflated once, so they are written down separately here.

### Nothing in the dependency set forces this project to be open source

Every direct dependency is permissive — trimesh (MIT), manifold3d (Apache-2.0),
FastAPI, transformers, diffusers. Permissive licences let this project be licensed
however its owner wants, **including fully proprietary**.

The only copyleft components are **CuraEngine and OctoPrint, both AGPL-3.0**, and both
are reached at arm's length: a CLI subprocess and an HTTP client. That distance is the
entire reason this project's own code is not subject to their terms. It is enforced by
tests (`test_no_source_file_links_an_agpl_component`,
`test_no_install_manifest_pulls_an_agpl_python_package`,
`test_the_slicer_still_invokes_curaengine_as_a_subprocess`) rather than by memory.

### Apache-2.0 does not prevent commercialisation

Two facts that resolve most of the apparent contradiction:

1. **Open source does not mean non-commercial.** Apache-2.0 permits commercial use
   explicitly. Selling software under it is ordinary.
2. **The product is not the code.** A customer pays for a printed object — machine
   time, filament, the fleet, logistics, someone answering when a part warps. Apache-2.0
   has nothing to say about what is charged for a service that is operated rather than
   distributed, and its obligations (retain notices, state changes, pass the licence on)
   all trigger on **distribution**. Running a hosted service is not distribution.

### The repository is private, so nothing has been open-sourced yet

`Daedal-Studio/ds-mvp` is private and GitHub detects no licence on it. There is an
Apache-2.0 `LICENSE` file in the tree, but a licence is a grant to whoever *receives*
the software, and nobody outside the organisation has. **Today that file is a statement
of intent, not an active grant.**

One inaccuracy to correct whenever the file is next touched: `THIRD-PARTY-NOTICES.md`
opens with "Daedal Studio (ds-mvp) is distributed under the Apache License 2.0." It is
not distributed at all.

### The options, and what each costs

| Option | Gives | Costs |
|---|---|---|
| Keep Apache-2.0, stay private | Every door open; publish later or never | Nothing today |
| Publish under Apache-2.0 | Goodwill, contributions, hiring signal | A competitor may run the same pipeline as their own service with no obligation back |
| Proprietary / source-available | Nobody else runs this stack | Loses the open-source position; cannot retract the grant on anything already shared |
| Open core | Pipeline open, fleet and dispatch closed | Boundary policing forever |
| AGPL the project's own code | A competitor offering it as a service must publish their changes | Enterprise customers avoid AGPL; complicates any later proprietary offering |

**Recommendation:** not urgent. Apache-2.0 while private costs nothing and forecloses
nothing. What *is* urgent is L4 below.

### What the licence does not cover

The moat is not the code. It is the printer fleet, the operational competence, and the
**telemetry dataset** — which prompts produce printable geometry, which meshes fail,
what people said about the parts they received. A code licence says nothing about data;
publishing the pipeline would not publish a single row of it.

---

## Task L4 — Confirm the model-weight terms before launch (revenue-gating)

**This constrains commercialisation far more than the outbound licence does**, because
weight licences restrict *use*, not only distribution. They bind a service that
distributes nothing at all.

For each checkpoint on the live path, three questions have to be answered, and the
third is the one that is usually skipped:

1. Does the licence permit **commercial use**?
2. Does it permit use **in a hosted service** — deployed, not merely experimented with?
3. Does it place any restriction on **commercial use of the generated output**?

Question 3 is the revenue gate. If a model's terms restricted commercial use of what it
produces, the mesh could be generated legally and the printed part could not be sold —
which is the entire business. `microsoft/TRELLIS.2-4B` is MIT with no restriction on
generated output, which is why Phase 2 is viable; that needs confirming per checkpoint
rather than assumed.

**This audit has now been done once, in full**, for every dependency — libraries,
tools, base images, models and the hosted service — in
`THIRD-PARTY-NOTICES.md` § 0 *Commercial-use audit*. It records the three answers per
component, marks whether each was read from the source or taken from declared metadata,
and ends with five findings. The headline: **nothing in the current dependency set
restricts commercial use of the output**, so the business model is not blocked. What
remains is the Pixazo contract question below, plus four hygiene items (a narrow NVIDIA
redistribution route for the worker image, an unused LGPLv3 Qt payload in
`opencv-python`, LGPL `gmpy2`, and a publishing toolchain pinned into the runtime
requirements).

Summary of the model path, all recorded in `THIRD-PARTY-NOTICES.md`:

| Checkpoint | Status | What still needs doing |
|---|---|---|
| `black-forest-labs/FLUX.2-klein-4B` | Apache-2.0 | Confirm no output restriction |
| `microsoft/TRELLIS.2-4B` | MIT, no output restriction | — |
| `facebook/dinov3-vitl16-pretrain-lvd1689m` | Commercial use permitted **with conditions** | **See L5** |
| `ZhengPeng7/BiRefNet` | MIT | Substituted for the encumbered default; keep the substitution |
| `google/siglip-base-patch16-224` | Apache-2.0, no out-of-scope clause | Pin a revision before launch |
| ~~`briaai/RMBG-2.0`~~ | CC BY-NC 4.0 — **never loaded** | Residual exposure is Pixazo's deployment, not this code — see below |
| ~~`openai/clip-vit-*`~~ | Tag says MIT; card puts all deployed use out of scope | On the deny list. **Do not remove the entry** |

### The Pixazo residual, stated plainly

The RMBG-2.0 problem is **solved in this codebase** for the two backends it runs in.
`microsoft/TRELLIS.2-4B`'s own `pipeline.json` configures
`BiRefNet(model_name="briaai/RMBG-2.0")`; `permissive_rembg()` substitutes MIT BiRefNet
weights *before* the pipeline is constructed, and `assert_permissive_matte()` verifies
the outcome rather than the mechanism, so an upstream reshuffle fails the load instead
of silently reverting. That covers `trellis2` (in-process) and `remote` (the worker runs
this same code).

It does **not** cover the `pixazo` backend, and it cannot: that is someone else's
deployment of the same model, running on their hardware. Whether their matte step uses
the encumbered weights is invisible from here and unfixable from here. **This is a
contract question, not a code question**, and it is the one genuinely open exposure:

- Ask Pixazo, in writing, to confirm which background-removal weights their
  `trellis-2-image-to-3d` endpoint uses.
- Get a warranty in the service agreement that the outputs are free of third-party
  licence restrictions and that commercial use of the generated mesh is permitted.
- Failing that, treat the hosted backend as unsuitable for production and keep it for
  development only — which is close to its current role, since it is the last resort in
  `resolve_backend_name` and the only backend that bills.

#### The terms, read from the primary source (2026-09-19)

Until this date the Pixazo position above was reasoned from the *shape* of a standard
hosted-API agreement rather than from the document. The terms have now been read and
archived at
[`docs/audits/vendor-terms/pixazo-2026-09-19.md`](audits/vendor-terms/pixazo-2026-09-19.md);
the Terms of Use are dated effective 16 September 2025, **last updated 14 September
2026**. Three things they say are sharper than "get a warranty", and all three are for
counsel.

- **Output ownership is split by plan, and the split may not be in our favour.** §5.3.1
  makes free-plan output ("Free Content") the property of **Appy Pie LLP**, licensed
  back to the user non-exclusively, revocably and with an attribution duty. §5.3.2 gives
  paid subscribers "Full Ownership", expressly including the right to sell. §5.3.4 makes
  the free-plan assignment permanent — upgrading later does not reclaim anything already
  generated. **Which of the two a usage-based API key falls under, the terms do not
  say**: §5.3 is written in the vocabulary of the consumer tiers (Free / Pro Monthly /
  Pro Yearly), and API access is sold separately. If the answer is §5.3.1, no mesh this
  backend has ever produced is ours, and the question is retrospective as well as
  prospective.
- **Two documents disagree.** Appy Pie's own *Generative AI Additional Terms* (last
  updated 5 June 2025) contain no assignment, state that "Appy Pie does not guarantee
  ownership of AI-generated content", and prohibit "intermediation/resale". Neither
  document says which governs an API call to `gateway.pixazo.ai`.
- **The disclaimers point the other way from the indemnity.** §11.2 specifically
  declines to warrant that generated content is "UNIQUE, ORIGINAL, OR NON-INFRINGING";
  §9.3 disclaims responsibility for a third-party model's training data and for "any
  claim arising from a specific model used at the User's direction" — and this code
  names the model by slug. Meanwhile §13.1's indemnity runs **from the user to Pixazo**
  and expressly covers "Failure to comply with AI model licence terms", while §5.6.2
  provides that where the terms conflict with a model's licence the more restrictive
  provision applies. Taken together: an undisclosed upstream weight licence binds us,
  and we indemnify the vendor for breaching a licence they will not name. That is the
  RMBG-2.0 / DINOv3 flow-through question above, with the contractual consequence
  attached.
- **Governing law is India, forum New Delhi** (§15.1.1, §15.2.1), against a pilot
  operating in Italy. Not a defect, but counsel should hold it alongside the ToS work in
  Task L1 rather than discover it.

**What to ask, and of whom.** The plan question and the conflicting-documents question
are for counsel to frame and for Pixazo to answer in writing; the weights question is
for Pixazo alone. Until both are answered, the standing position is unchanged: keep the
`pixazo` backend beta-only.

#### Added 2026-09-21 by the external licence watch: **who owns the mesh is unsettled**

The 2026-09-19 reading above raised the plan split and left it as "which of the two a
usage-based API key falls under, the terms do not say". Re-reading the same terms on
2026-09-21 against Pixazo's own Trellis 2 API page answers the second half of that:
neither clause describes how we buy. The finding below supersedes the open question
above rather than repeating it.

**The one new fact: this project is neither plan.** The split in § 5.3 is set out in
the 09-19 block above and is not restated here. What 09-19 could not resolve, and what
this run resolves, is which side of it a wallet-funded API caller falls on: Pixazo's
Trellis 2 API page sells **pay-per-use credits against a wallet balance** — USD 0,35 per
generation, a `402` on insufficient funds — and offers **no subscription** for API
access. A wallet-funded caller therefore has no "active subscription period", so § 5.3.2
cannot describe how we buy, and § 5.3.1 — output owned by Appy Pie LLP — is the clause
written for everyone who is not a subscriber. Nothing in the document says whether
topping up a wallet makes a "Paid User" for § 5.3 purposes.

**Why that is the revenue gate and not a technicality.** Task L4's three questions
assume the generated mesh is ours to sell. If § 5.3.1 governs, the mesh the `pixazo`
backend produces is owned by Appy Pie LLP and licensed back to us revocably, for
"personal and limited commercial" use, with attribution. This product prints that mesh
and hands over a physical object for money. That is the business, and it would be
running on a revocable licence from a third party under a term neither side has ever
discussed.

**Three clause numbers that differ from the 09-19 reading**, and are recorded because a
letter to counsel has to cite the right subclause. The points are the same points made
above; only the citations moved, and both readings are from the same document:

- **§ 11.1** disclaims all warranties including non-infringement. The 09-19 block cites
  **§ 11.2** for the same disclaimer, quoting "UNIQUE, ORIGINAL, OR NON-INFRINGING".
- **§ 5.6** assigns third-party model licences to the customer and names Flux, DALL-E,
  Stable Diffusion and Ideogram — **not** TRELLIS.2, and no background-removal or
  conditioning component. 09-19 cites **§ 5.6.2** for the conflict rule beneath it.
- **§ 15.1** — Indian law, New Delhi. 09-19 cites **§ 15.1.1** and **§ 15.2.1**.

**What to ask for, in the same letter as the matte-weight question above:** written
confirmation that a wallet-funded API caller owns generated output under § 5.3.2.

**The cheap resolution, reached twice independently.** `create_sculptor()` makes the
backend swappable and `pixazo` is the last resort in `resolve_backend_name`, so keeping
it development-only costs a config change and moots this whole section. The 09-19
residual reached the same conclusion from the matte weights; that two readings of
different clauses arrive at one answer is itself the argument. #168 has since done it
in code — `ALLOW_PROMPT_JOBS` is off by default.

Archived terms and the full reading: `docs/audits/vendor-terms/pixazo-2026-09-21.md`.
Tracked as **E5** (ownership), **E6** (warranty and indemnity direction) and **E11**
(governing law) in `docs/audits/2026-09-21-external-licence.md`.

> Those were **E1**, **E2** and **E9** when that report was merged. It had renumbered
> from scratch over 2026-09-19's set, which is declared permanent, so "E1" named two
> different findings in two consecutive reports — and the older one, `easydict`, is the
> live LGPL-3.0 exposure a reader following this line would have landed on. The report
> carries the correction and the full mapping at its head.

### Why the deny-list entries must stay

Two entries in this codebase name things this project does **not** use:
`openai/clip-vit-*` in `ip_screen_image.DENIED_MODEL_REPOS`, and
`nvdiffrast`/`nvdiffrec` in `test_licensing_guards.FORBIDDEN_RENDERER_PACKAGES`.

There is **no usage of either** — every occurrence is a deny-list entry, a test that the
deny-list works, a comment explaining why an upstream install flag is omitted, or a
notices row recording the rejection. Deleting them would remove the protection, not the
exposure:

- The runtime refusal in `assert_permissive_vision_model` is what stops
  `DS_IP_MODEL_ID=openai/clip-vit-base-patch32` from loading.
- `FORBIDDEN_RENDERER_PACKAGES` is what fails the build if `--nvdiffrast` is added to a
  Dockerfile — and upstream TRELLIS.2's own documented install line asks for it, so the
  tempting copy-paste is the encumbered one.
- The comments are how the next engineer learns why the flags are missing.
- The notices rows are the audit trail showing these were **considered and rejected**.
  To a reviewer, that reads as diligence; their absence reads as ignorance.

The guards match executable lines only, so explanatory comments naming them are
deliberately permitted.

---

## Task L5 — DINOv3: accept the licence as the right legal entity

DINOv3 is TRELLIS.2's `image_cond_model`, on the shape path, and cannot be structurally
avoided the way the rasterizer and the matte weights were. The **DINOv3 License permits
commercial use**; what it requires is:

- **Attribution** — "Built with DINOv3", carried in the UI footer, `README.md` and
  `THIRD-PARTY-NOTICES.md`, and held there by `test_dinov3_attribution_is_present_in_the_ui`
  and its docs counterpart.
- Compliance with its **Acceptable Use Policy** and **trade-control terms**.
- **Propagation of the licence** if the weights or a derivative are ever redistributed.
- Acknowledgement in publications.

Two things to settle before launch:

1. **Who the licensee is.** The Hugging Face repo is gated, so whoever accepted the
   terms with the token in `HF_TOKEN` is the accepting party. If that is a personal
   account, the licence may not run to the company. Re-accept as the corporate entity
   and record when and by whom.
2. **Never bake the weights into a distributed image.** Using them at runtime is a use;
   shipping a container with them inside is a redistribution, and the gated acceptance
   does not travel to whoever pulls the image. Enforced by
   `test_no_install_manifest_bakes_model_weights`, which fails the build on
   `huggingface-cli download`, `snapshot_download`, `from_pretrained` in a `RUN`, a
   `COPY` of `*.safetensors`, or a `curl` from `huggingface.co` — comments excluded.

---

## Task L6 — Confirm the functional-article line in the prompt screen (not blocking)

**What was decided, and by whom.** As of 2026-09-10 (issue #79) `pythonsrc/ip_screen.py`
distinguishes a curated name used as a **depiction** from the same name used to say what
the part is **for**. "Deck box for Pokémon cards" is accepted and flagged for the human
gate; "a Pikachu figurine", "Charizard emblem on the lid" and "a Pikachu deck box" are
refused before a job row exists. That is a **product decision taken by the team**, on the
reasoning below, not advice from counsel and not a legal conclusion.

**The reasoning.** The exposure this project carries is *making and supplying* an object
that reproduces a protected character (Task L1). A storage box sized for a game's cards
does not reproduce anything: the geometry is a rectangular enclosure whose dimensions come
from a card footprint, the pipeline discards appearance and prints in one colour, and the
franchise name appears only in the request, never on the part. **That last clause is a
premise, not an observation** — F13's embossing field is the one thing in the product that
could put the name on the part, and it is held by code rather than by hope: see the
embossing position below. Naming a product's brand to
say what an accessory fits is the ordinary indication-of-purpose case — Art. 14(1)(c) EUTMR
permits use of a mark to indicate the intended purpose of an accessory where it is
necessary and in accordance with honest practices. The counter-consideration is the one
counsel should weigh: TCG rightsholders police "compatible with" accessory marketing, so
honest-practice conditions (no implied endorsement, no franchise name or livery on the
article or in its listing) are doing real work, and none of that is enforced by code.

**Why the alternative was worse.** Refusing the prompt refused the pilot's primary persona
for describing their own use case, with **no appeal path** — the refusal is a 400 before
`job_id` exists. And the coverage was inconsistent: Pokémon was refused while Magic: The
Gathering, Yu-Gi-Oh!, Lorcana and One Piece were not on the list at all, which is worse
than either consistent answer because it looks like a policy and is not one.

**What counsel is asked to confirm, when L1 is picked up:**

- That flagging functional use, rather than refusing it, is the right posture for a
  service that manufactures — and if not, whether the answer is a refusal or a term in
  the ToS.
- Whether the product must additionally suppress the franchise name **downstream** of the
  screen: it is stored verbatim on the job row and interpolated into the blueprint prompt,
  and honest-practice conditions are about what the *listing and the article* say. Nothing
  today prints or publishes it.
- The accepted false negative: a **character** named as contents with no depiction cue
  ("a stand for Pikachu") is flagged rather than refused, and reaches a human.
- The boundary in the other direction, which is where the rule is **stricter** than the
  functional reading: a franchise or brand in front of anything that is not one of the
  parts this product makes is treated as naming the *subject* and refused — "a star wars
  x-wing" and "a nintendo switch dock" are both refused, the second of which is arguably
  an accessory case Art. 14(1)(c) would cover. The appeal path is the rephrasing the
  refusal already asks for ("a dock for a Nintendo Switch" is flagged), and the head noun
  is the only signal available in the sentence. Whether that trade is the right way round
  is a question for counsel; the code pins both directions in
  `tests/test_ip_screen.py` so moving the line is one decision in one place.
**The embossing field — where the line sits on the third channel.** Decided 2026-09-17
(issue #156), the same way and on the same standing: a product decision by the team,
pending counsel. F13 raises typed words *on the part*, which is the one place this
product could put someone else's mark on a manufactured good, so:

- **A curated name in the embossing field is refused, whatever surrounds it.** The
  functional-article rule does not reach this channel — nothing raised on a face holds
  anything, so there is no reading in which the name describes contents. "Deck box for
  Pokémon cards" still passes as a purpose; "Pokémon" embossed on that same box does not.
  In the code this is `ip_screen.DEPICTION_ONLY_CHANNELS`.
- **Each channel is screened on its own tokens.** The three free-text fields were joined
  into one string before matching, which would have let the box's own purpose text lend
  the emboss field its grammar and demote that refusal to a flag. They are separate
  channels and are screened separately; `ScreenVerdict.channel` says which one matched,
  and the refusal and the `ip_screen_flagged` event both carry it.
- **An ambiguous term still only flags here.** "Joker", "frozen" and "creeper" are
  ordinary English on a lid as much as in a prompt, and refusing someone's own word is
  the mistake with no appeal path.
- **The appeal path is stated in the refusal itself**: keep the prompt, emboss your own
  words. A refusal telling someone to describe the shape differently would be advice
  about a field that was not the problem.

**What counsel is asked to confirm about this channel:** that refusal (rather than a
flag to the human gate) is the right posture for a name on the article itself, given
that the honest-practice conditions above turn on the article and its listing carrying
no franchise name or livery; and whether a *character* embossed differs from a
*franchise* embossed, which the code today does not distinguish — both are refused.

**Where the code is:** `_classify_usage` in `pythonsrc/ip_screen.py`, the cue constants
beside it, `CHANNELS` and `DEPICTION_ONLY_CHANNELS` in the same module,
`JobRequest.embossing_text` in `server/app.py`, `category` in
`pythonsrc/data/ip_blocklist.json`, and the `ip_screen_flagged` job event's `usage` and
`channel` fields, which are how often each rule fires and in which box. The lines are
pinned by `tests/test_ip_screen.py`, so moving either is one decision in one place.

---

## Task L7 — TypeSafe (Jev) as a processor of prompt text (not blocking; owed before #181)

**What it is.** Roadmap §0.7 (2026-09-22) admits a second hosted, paid model into the
words → spec path, gated behind issue #181: TypeSafe's Jev, which returns typed judgments
(a choice among options code supplies, a yes-probability, an ordered level) and never
text or a number. If #181 ships, the server will send to `api.typesafe.ai` **the person's
prompt and the number-candidates code found in it — nothing else**: no spec millimetres,
no photo, no printer profile, no identity, no job id. Prompts are user content under
GDPR, so this is a processor relationship whether or not the request is small.

**What has to be read and recorded before the first external prompt leaves the server
(issue #182, legal pair):** the Master Customer Agreement, the Data Processing Agreement
and the Privacy Policy at `https://typesafe.ai/legal/…`, archived with the date under
`docs/audits/vendor-terms/typesafe-<date>.md` exactly as Task L4 did for Pixazo; the
sub-processor region and the retention window for request text on the standard tier —
TypeSafe's own docs say zero-data-retention is **enterprise-only**; the rate-limit terms
("adjusting dynamically … can change without notice"), which are why #181 fails open and
never refuses a job; Art. 28 processor terms and the line in the privacy policy naming
TypeSafe (Task L5's list); the note in Task L1's retention item that prompt text may now
reach a second processor. Output ownership does not arise — Jev returns judgments, not
content — but say so in the § 0 audit row rather than leave it implied.

**What it does not change.** The deterministic prompt screen (Task L6) runs before any
prompt leaves the server and is never overruled by the model; the functional-article line
stays pinned in code. The key is environment-only, like `PIXAZO_API_KEY`, and is
deliberately not a `CONFIG_KEYS` entry, so the credential protecting `PUT /config` cannot
be used to rotate it.

**Nothing to do until #178 says the Jev arm is worth having.** This task exists so the
context is not rediscovered; it is triggered by #182, not by the calendar.

---

## Open question for counsel (not blocking)

EU AI Act Art. 50 imposes transparency duties around AI systems and artificially
generated content. It splits, and the two halves are now in different states.

**Art. 50(1) — telling a person they are interacting with an AI system — is handled in
the interface** (issue #78, 2026-09-11). Research verified 3–4 September 2026: Art. 50
applies from **2 August 2026**, and the Commission's May 2026 guidelines say a line in
the T&Cs does not discharge 50(1) — the interface itself has to say it, at the latest at
the first interaction. The Digital Omnibus grace period to 2 December 2026 reaches only
systems placed on the market before 2 August 2026, so this product gets none of it.

What is live, and where:

- One sentence in `web/src/components/PromptNotice.tsx`, which all three composers (the
  landing field, the inline "New job" field and the zoomed field) share, so they cannot
  tell people different things: *"Your prompt is read by an AI system that turns it into
  a parametric spec; the geometry itself is computed, not generated."* Wording approved
  by the owner on 2026-09-09.
- The same disclosure in fewer words on the running view's Composer stage, where the
  extracted spec is shown — because someone opening a job someone else started never
  passed a composer.
- `AI_SYSTEM_NOTICE` / `AI_SYSTEM_NOTICE_SHORT` are the one place either is worded, and
  `tests/test_ip_notice.py` fails if the disclosure leaves any of the four files.

Two things counsel should know about the wording rather than discover. The first half —
a person's prompt is read by an AI system — is true on both paths the product has: FLUX
reads it on the generative path running today, and the extractor will read it on the
parametric one. The tail ("turns it into a parametric spec … computed, not generated")
describes the parametric pipeline, which is literal for a `--spec` job, where
`pythonsrc/organizer/` compiles geometry deterministically, and is the vocabulary the
whole UI was deliberately moved onto ahead of the engine
(`docs/SYSTEM-AS-BUILT.md` § Project Overview).
Until the composer can build a spec, a *prompt* job's mesh is still reconstructed by
TRELLIS.2 from a FLUX image — generated, not computed. Nothing on the page claims
otherwise about a given job, and the telemetry columns (`generation_model`,
`blueprint_model`) record what actually ran; but if counsel reads the tail as a
representation about output rather than about the product, it wants revisiting before
the pilot rather than after.

**Art. 50(2) — machine-readable marking of AI-generated content — is deferred with the
decorative tier.** It does not arise in the spec-driven v0.2 scope: the deliverable is a
compiled mesh and its G-code, and no AI-generated image is shown to or handed to a user.
It returns with PRD F13/F14 (decorative personalization, roadmap §4A), which is where a
generated image becomes part of the product again, and where the third prompt channel
for the IP screen also lands. Do not ship F13 without answering 50(2) alongside the F13
screen named in Task L6.

**Still open.** Whether any part of Art. 50 reaches the *physical object* produced from
a generated image — marking has no obvious meaning for a single-colour FDM part — and
whether the pilot's scale engages the rest of the Act at all. Neither is blocking; both
are raised here so they are not discovered late.
