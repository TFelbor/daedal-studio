# Deferred legal tasks

Two items surfaced while designing the IP controls in the pipeline. Both are legal
work products, not code, and neither is being started now. This file exists so the
context does not have to be rediscovered when they are picked up — attach it to the
task.

Everything below assumes the operating posture of the Trento pilot: Prompt2Print
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
member-state penalties reaching 6% of turnover for non-compliance. Whether Prompt2Print is
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

## Open question for counsel (not blocking)

EU AI Act Art. 50 imposes transparency duties around artificially generated content. The
plain target is synthetic media — image, audio, video, text — and its machine-readable
marking obligation sits on *providers* of generative systems rather than on a deployer
using an openly licensed model downstream. Whether any part of it reaches a physical
object produced from a generated image, and whether the pilot's scale engages it at all,
is a question for counsel rather than something to design around now. Raised here only so
it is not discovered late.
