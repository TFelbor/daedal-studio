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

## Open question for counsel (not blocking)

EU AI Act Art. 50 imposes transparency duties around artificially generated content. The
plain target is synthetic media — image, audio, video, text — and its machine-readable
marking obligation sits on *providers* of generative systems rather than on a deployer
using an openly licensed model downstream. Whether any part of it reaches a physical
object produced from a generated image, and whether the pilot's scale engages it at all,
is a question for counsel rather than something to design around now. Raised here only so
it is not discovered late.
