# The Claude Code pipeline

How a labelled issue becomes a reviewed pull request, what each label means, and how
to stop it. One page on purpose.

Operated only by the two technical co-founders. Everyone else may read it.

## The path

```
issue + labels
      │
      ├─ tier:fable-plan ──▶ claude-plan.yml (Fable 5.1)
      │                        posts a "Plan" comment, adds `plan-ready`
      │                                    │
      └─ tier:opus-direct ─────────────────┤
                                           ▼
                              claude-implement.yml · job `implement` (Opus 5)
                                branch claude/issue-<n>, tests run, PR opened
                                — or, when the run ends early: work pushed,
                                  draft PR opened, issue told why (§ When a run fails)
                                           │
                                           ▼
                              claude-review.yml (Fable 5.1)
                                required check `claude-review`
                                  ├─ approve ─────────▶ green
                                  └─ request changes ─▶ red + "@claude please
                                                        address the review"
                                                              │
                                           claude-implement.yml · job `fix` (Opus 5)
                                             pushes to the same branch ─┐
                                                                        │
                                           (back to claude-review) ◀─────┘
                                           │
                                           ▼
                              human merges  ·  or, in Phase 2 only,
                                              claude-automerge.yml
```

Nothing in this pipeline merges anything while `AUTO_MERGE` is `off`, which is how it
is created. Phase 1 is: a human reads the PR and merges it.

## The workflows

| File | Model | Trigger | What it does |
|---|---|---|---|
| `.github/workflows/claude-plan.yml` | `claude-fable-5-1`, 60 turns | issue labelled | Posts one **Plan** comment — approach, files, tests, risks, open questions — then adds `plan-ready`. Writes no code. On failure, says so on the issue. |
| `.github/workflows/claude-implement.yml` (`implement`) | `claude-opus-5`, 200 turns | issue labelled, or `workflow_dispatch` with an issue number | Builds the CI environment, creates `claude/issue-<n>`, implements on it, runs the tests, opens a PR with the acceptance criteria as a checklist. Whatever happens, keeps the transcript and leaves the work findable (§ When a run fails). |
| `.github/workflows/claude-implement.yml` (`fix`) | `claude-opus-5`, 200 turns | `@claude` comment on an **open, unmerged** PR | The fix loop. Interactive mode: no `prompt` input, so the comment *is* the request. Same tail as `implement`. |
| `.github/workflows/claude-review.yml` | `claude-fable-5-1`, 80 turns | PR opened / synchronised / reopened / marked ready; **drafts are skipped** | Reviews against the linked issue and `CLAUDE.md`, posts one review, and **fails the check** when it asks for changes. |
| `.github/workflows/claude-automerge.yml` | none — plain `gh` | review submitted, check suite completed | Phase 2 only. Squash-merges and deletes the branch when every gate below passes. |
| `.github/workflows/claude-resume.yml` | none — `infra/ci/claude_resume.py` | every two hours, or by hand | Re-dispatches `claude-implement` for drafts the safety net left after a transient failure — the subscription's usage limit above all. Retries only a transient failure — never a budget failure, a finished run or a cancelled one — never touches a draft a person or the model opened, and stops after three attempts or the first human comment. |

### One exemption, and only one

The action validates its own workflow file against the default branch and refuses to
run when they differ. That is unavoidable on a pull request that edits
`.github/workflows/` — including a pull request to this pipeline itself. In that one
case `claude-review` passes and says, in the job summary, that nothing reviewed the
pull request and a human has to. Every other empty verdict is a red check.

So: **a pull request that changes a workflow is never machine-reviewed. Read it
yourself.**

### The reviewer's subject is a bot, and the action refuses bots by default

`claude-implement.yml` opens its pull requests as the Claude app, so on
`pull_request` the actor `claude-review.yml` runs under is `claude[bot]` — type `Bot`,
not `User`. The action rejects a non-human actor unless the workflow names it in
`allowed_bots`, and it rejects it *before* it reaches the model: the step fails in
about two seconds with

```
Workflow initiated by non-human actor: claude (type: Bot).
Add bot to allowed_bots list or use '*' to allow all bots.
```

which is an empty verdict, which is a red check. That is the gate working — nothing
reviewed the pull request — but the cause is a missing input, not a review that went
wrong, and it made Tier 3 unable to review Tier 2's work at all. `claude-review.yml`
therefore passes `allowed_bots: "claude[bot],claude-code[bot]"`, the way
`claude-implement.yml`'s `fix` job already passes `github-actions[bot]` for the fix
request it answers.

The `implement` job passes the same two logins, for the plan-first tier: `claude-plan`
adds `plan-ready` with the App's token, so the `labeled` event that starts the
implementer is *sent by* `claude[bot]`. Without the input, the handoff between Tier 1
and Tier 2 fails in the same two seconds with the same message — and it had never been
exercised, because no plan run has completed yet. `tests/test_claude_pipeline_workflows.py`
pins it.

**Do not widen either list to `'*'`.** An allowed bot skips the write-permission check
as well as the human check, so `'*'` lets any GitHub App that can open a pull request
choose this job's prompt. Names are matched case-insensitively with a trailing `[bot]`
stripped, so one entry covers both spellings of a login.

A symptom worth recognising: the two-second failure looks identical in the check list
to a genuine `request_changes`. Read the **Review with Fable** step, not the
**Decide the check from the verdict** step — the second one only reports that the
first produced nothing.

### `--max-turns` is a budget assertion, not a limiter

Set it too low and a **finished** review is thrown away. On PR #55 the reviewer ran to
completion, returned `subtype: "success"` with `is_error: false`, and posted its comment
and three inline comments — and the action then failed the step:

```
Claude reported a successful result after 32 turns, exceeding the configured maximum of 20
```

The throw is in `base-action/src/run-claude-sdk.ts`, *before* the block that sets
`structured_output`, so the verdict never reaches the gate and the check goes red for a
missing verdict. It went red on a pull request its reviewer had just approved.

Two things follow. **The SDK's turn budget and the result message's `num_turns` are not
the same counter** — the first did not trip at 20, the second reported 32 — so the cap
must carry slack rather than being set to a measured figure. And **the cap buys no cost
control**: `timeout-minutes` on the job is the real bound, and those 32 turns took four
minutes of the twenty. `claude-review` is therefore at 80, the same as
`claude-implement`, which does far more work and fits inside it.

The implementer has the measurement the reviewer lacked. Issue #53 — a README section,
the smallest task the pipeline has run — took **32 turns**, USD 2,99 and 4 permission
denials. Issue #60 — a Size L security issue naming four sub-decisions in a 3 800-line
`server/app.py` — hit the 80-turn cap at **81 turns**, USD 9,44, 12,5 minutes, with no
branch pushed, no pull request and no comment. Both `claude-implement` jobs are
therefore at **200**, with `timeout-minutes: 90` as the actual cost bound (81 turns took
12,5 minutes of model time; the install is another five). `claude-plan.yml` is at 60 and
has still never completed a run here, so that number is unmeasured; if it fails this
way, the error names both figures.

Two consequences for whoever labels an issue. A budget is not a substitute for tiering:
an issue that names a decision to make first, or spans several modules, is
`tier:fable-plan` or several issues, not `tier:opus-direct` with a bigger number. And
the turns are spent where the model spends them — #60 also carried the whole of
`CLAUDE.md` (130 KB) into every turn's context, which costs tokens rather than turns,
but reading a 3 800-line file in 200-line pieces costs turns.

### When the fix loop does not ask

`claude-review.yml` posts `@claude please address the review` only when both hold:

- **the pull request is still open.** A review is queued at `opened` and lands minutes
  later; a human who merges inside that window would otherwise get a fix request
  pointing at a branch already in `main`. That happened on merged PR #52, and the
  `fix` job — sixty-minute timeout, PostgreSQL service, full dependency install —
  ran on it.
- **the author is the Claude app.** The loop exists so the implementer can answer its
  reviewer. On a human's pull request it is an unsolicited @-mention that would have
  Opus push to someone else's branch.

Neither precondition changes the check's colour: `request_changes` is still
`request_changes`, and the check is still red. Only the comment is withheld, and the
job summary says which precondition withheld it.

`claude-implement.yml`'s `fix` job carries the open/unmerged half of the same guard,
because it answers *any* `@claude` comment on a PR, not only the reviewer's.

One detail worth knowing before editing either guard: **`gh` spells the same GitHub App
three ways, by field.** A pull request's `author.login` from `gh pr view --json author`
is `app/claude` (with `is_bot: true`); the same actor is `claude` on comments and
reviews through `gh pr view --json comments`, and `claude[bot]` through the REST
endpoint. `CLAUDE_LOGINS` lists all three, in `claude-review.yml` and
`claude-automerge.yml` alike, and both comparisons strip the `app/` prefix and the
`[bot]` suffix first — neither `/` nor `[` is legal in a human login, so that widens
nothing. It went wrong once already: on PR #92 the reviewer requested changes on two
real defects and then withheld the fix request with "the author is app/claude, not
the Claude app", so the loop stalled on a red check until a person posted the
request by hand. `tests/test_claude_pipeline_workflows.py` pins the list and the
normalisation in both files.

## The action does not create the branch in automation mode

`branch_name_template` is documented as the pattern for the branch the action creates.
It creates one only in **tag mode**. With a `prompt` input — every job in this pipeline
— the action runs in automation mode, and `src/modes/agent/index.ts` never calls
`setupBranch`: the checkout stays on `main`, and the branch is whatever the model
decides to `git checkout -b`, whenever it gets to it. `claude-implement.yml` therefore
creates `claude/issue-<n>` itself, in a step before the model runs, and the prompt says
so. If the branch already exists on origin — a previous attempt that ended early — the
step resumes it rather than replacing it, because its commits are the work.

## When a run fails

The first real turn-budget failure (issue #60) left exactly one trace: a red run in the
Actions tab. The model had spent 81 turns and USD 9,44, and had committed nothing,
pushed nothing, opened nothing and said nothing. Every `claude-implement` job now ends
with the same two steps, run with `if: always()` so that they run *especially* when the
model step failed:

1. **The transcript is kept.** The action hides the model's turns from the log for good
   reason (tool results can print secrets), so the execution file it writes is the only
   record of where a budget went. It is uploaded as an artifact named
   `claude-implement-issue-<n>-transcript`, kept 14 days. `gh run download <run-id>`
   fetches it; the result message at its end says `subtype`, `num_turns` and how many
   tool calls were denied.
2. **The work is left where a person can find it** (`infra/ci/claude_implement_report.sh`,
   tested by `tests/test_claude_implement_report.py`):
   - uncommitted edits become one `WIP:` commit, marked as the workflow's, not the model's;
   - commits origin does not have are pushed;
   - commits with no pull request get a **draft** one, titled `WIP: <issue title>`,
     whose description says how the run ended and how to resume or restart;
   - commits with a pull request get a comment on it saying the same;
   - nothing committed gets a comment on the issue saying so, and why.

   The draft is opened with the App's token when the action produced one, so it is the
   Claude app's pull request and the fix loop can act on it. A successful run that
   opened its own pull request gets nothing from this step: the pull request is the
   report.

**Resuming.** Comment on the draft:

```
@claude please continue implementing #<n>: read the issue, the Plan comment if there is
one, and the diff so far, then finish the remaining acceptance criteria and mark the
pull request ready for review.
```

That is the `fix` job, in interactive mode, on the same branch. **Restarting** is:
close the draft, delete the branch, and re-apply the tier label — or run the workflow
by hand, `gh workflow run claude-implement.yml -f issue_number=<n>`, which is also how
a failed run is retried without the remove-and-re-add label dance. The dispatched issue
must still carry `claude`; the Resolve step refuses otherwise. The PR-exists guard
counts open and merged pull requests from `claude/issue-<n>`, not closed ones, so a
closed draft does not block the restart.

**Drafts are not reviewed.** `claude-review.yml` skips a pull request while
`draft == true` and runs on `ready_for_review`. A review of a diff nobody claims is
finished would request changes on it and start the fix loop against it; the finished
version gets its review when a person says it is finished.

### Resuming on its own after a usage limit

The subscription behind `CLAUDE_CODE_OAUTH_TOKEN` has a usage wall, and a run that hits
it fails mid-task with `error_during_execution` and the API's error text. The safety net
leaves the draft and the transcript, as above; **`claude-resume.yml`** then brings the
run back without anyone watching:

1. Every safety-net draft body and comment carries
   `<!-- claude-implement-safety-net subtype=<result subtype> -->`. That is the protocol:
   the subtype says whether waiting would help.
2. Every two hours `infra/ci/claude_resume.py` lists open drafts with the marker and, for
   each one whose **latest** safety-net record names a retryable subtype, where **no
   person has commented since the pipeline last acted**, fewer than **three** attempts
   have been made and the last one is more than two hours old, runs
   `gh workflow run claude-implement.yml -f issue_number=<n>` and leaves a
   `<!-- claude-implement-resume -->` comment saying so. `workflow_dispatch` is the one
   event a workflow token may trigger, so this depends on no comment-trigger behaviour.
3. The implementer's guard sees the safety-net draft and **resumes** instead of skipping:
   the branch step checks the branch out from origin, and the prompt gains a note
   naming the draft and telling the model to read the diff and continue, not start over.
4. A resumed run that finishes marks the draft **ready** (which starts `claude-review`)
   and leaves `<!-- claude-implement-finished -->`, which stops the loop. A run that
   fails again adds another safety-net comment and the cycle repeats, up to the cap.

**Which subtypes are retried is a positive list, not a deny list** —
`RETRYABLE_SUBTYPES`, `{error_during_execution, none}`, held in both scripts and bound
together by a test so the note on the draft cannot promise a retry the scheduler will not
make. A deny list was written first and it was wrong three times over, each in the same
direction: it would have spent a full Opus run on `success` (the run *finished* without
opening a pull request — the draft is waiting on a person to read it, not on another
run), on `cancelled`, and on any subtype nobody has thought of yet. The list says what is
worth another attempt; everything else is left where it is, with the reason on the draft.

`cancelled` is in the protocol at all because the safety net runs under `if: always()`:
pressing Cancel in the Actions tab still reaches it, still pushes the work and still
opens the draft — and the run leaves no result message, so the subtype would have read
`none`, which *is* retryable. Someone stopping a run is a decision, and re-dispatching it
two hours later would quietly undo it, so `subtype()` lets `CONCLUSION=cancelled`
override the file. **§ How to stop it below says cancelling stops it; that skip is the
only thing that makes the sentence true.**

Three things it deliberately does not do. It never retries `error_max_turns`: that is a
budget, not a limit, and another 200 turns on the same scope repeats the failure —
split the issue or resume it by hand. It never touches a draft without the marker: that
is the model saying "not finished" on purpose, or a person's work. And it stands down
the moment a person comments on the draft, because they have taken over — measured from
**the last thing the pipeline did of its own accord** (the resume dispatch, or the
safety-net record when there has not been one), not from the last record. A comment
posted *while* an attempt is in flight is older than the record that attempt writes when
it fails, so measuring from the record would read it as already answered and dispatch
over the top of the person who wrote it.

When a resumed run finishes, the draft loses its `WIP:` title along with its draft
status: the prefix said the run had not finished, and leaving it hands the reviewer a
ready pull request that calls itself work in progress. Only that exact prefix is dropped;
a title a person edited is theirs.

`tests/test_claude_resume.py` pins every rule on the pure `decide()` function.

## Skills are vendored, not installed

`claude-implement` and `claude-review` both load the skills in `.claude/skills/`. They
are copied into this repository rather than installed through the action's `plugins`
and `plugin_marketplaces` inputs, and that is not a preference:

- `plugin_marketplaces` validates against `^https://…\.git$`. There is no ref, tag or
  sha in that grammar, and `claude plugin marketplace add` has no flag for one.
- `claude plugin install <name>` reads `@` as a **marketplace** selector, not a version
  (`use plugin@marketplace for specific marketplace`).

So an installed plugin resolves to somebody else's default-branch HEAD, re-resolved on
every run — a third party deciding what reviews this repository's code, with no diff
anywhere. A copy in the tree is pinned by the commit, reviewable, costs no install time
and needs no network at run time. `THIRD-PARTY-NOTICES.md` § 2 carries the source,
version and licence of each, and the upstream `LICENSE` sits in each directory.

Two mechanics are load-bearing, and each is silent when wrong. Both are asserted by
`tests/test_vendored_skills.py`, which also binds the tracked directories to
`.gitignore`'s allowlist, to each directory's `LICENSE` and to the § 2 table in both
directions — none of which anything checked until three skills had to be removed:

- **`Skill` must be on `--allowedTools`.** Discovery is automatic — the action leaves
  `settingSources` at `["user","project","local"]`, so the checkout's own skills are
  indexed — but the tool allowlist is exhaustive. Without `Skill` the model sees every
  skill's description and can invoke none of them: the port is inert, the workflows
  look correct, and nothing in the log says so.
- **A vendored skill's cross-references must lose the plugin namespace.**
  `superpowers:test-driven-development` does not resolve for a skill loaded from a
  repository. Those were rewritten on vendoring; the rewrite is recorded in
  `THIRD-PARTY-NOTICES.md` because modifying a third party's MIT source is a thing you
  disclose, not a thing you do quietly.

**Which skills, and which job.** Two, both from `obra/superpowers`:
`test-driven-development` and `verification-before-completion`. They are the
disciplines behind "tests for every behaviour change" and a definition of done that
says the tests were actually run. Both jobs keep `Skill` on the allowlist and both
therefore index them, but they use them differently, and that asymmetry is the
point rather than an oversight. `claude-implement` is the only job that can
*execute* the loop — it brings up a `postgres:17-alpine` service on
`DS_TEST_DATABASE_URL`, puts the CuraEngine stub on PATH and allows
`Bash(pytest:*)`, so a red test can actually be watched go green. `claude-review`
has `Read,Glob,Grep,Skill` and `gh`; it can run nothing, but its prompt asks
whether "tests present and meaningful", and a test whose expectation is computed by
the code under test is visible on the page without running it. That is what
`writing-good-tests.md` is for, and it is the half of the review the required check
cannot get from `pytest` in `ci.yml`.

**`verification-before-completion` earns its place on two lines nothing else in the
tree states** — "Revert fix → Run (MUST FAIL) → Restore". There is no coverage
tooling anywhere in this repository, so a test that passes but *could not fail* is
undetectable, and `claude-review` cannot execute a test to find out. That is the
same failure `tests/test_phase_banners.py` exists to prevent ("a test retyping the
regex would agree with itself forever"), generalised.

**Where a vendored skill and CLAUDE.md disagree, CLAUDE.md wins.** Both are third
party text written for other repositories, and two disagreements are known and
deliberate rather than oversights:

- `verification-before-completion` gates completion on "Linter clean | Linter
  output: 0 errors". `npm run lint` here fails on 27 pre-existing errors, CI runs
  it `continue-on-error`, and CLAUDE.md's rule is a **delta** rule: leave it no
  redder than you found it. An agent reading the skill literally has two exits and
  both are wrong — clear 27 unrelated errors, which is the out-of-scope diff
  `claude-review` fails a pull request for, or refuse to report finished work.
- `test-driven-development`'s Iron Law ("no production code without a failing test
  first") has no satisfiable form for a `web/` change: `web/package.json` defines
  only `dev`, `build`, `lint`, `preview` and there is no test framework. Installing
  one to obey the skill would be a new dependency, which CLAUDE.md makes a licence
  decision. The frontend gate is `npm run build` (which is `tsc -b`) plus
  `npm run lint`. Its `npm test …` verify commands and its "ask your human partner"
  exceptions are likewise written for somewhere else; the command of record is
  `pytest tests/`, and a `labeled`-triggered job has no partner.

**The cost is about 75 tokens per run**, in both jobs, always: each skill
contributes its name and description to the index whether or not it fires. The two
descriptions are 79 and 225 characters. Bodies load only on a description match and
run 3.3k and 8.9k characters. This is down from about 500 tokens across five
skills, and the number is the reason the list is short rather than generous — see
THIRD-PARTY-NOTICES.md § 2 for the three that were removed and the 1 361 that were
assessed and rejected, ~123 000 tokens of description between them.

**What is deliberately absent.** No MCP server is configured for CI. `codegraph` would
help — call paths grep cannot follow — but CI would have to install the binary and
build the index (12 MB for this repository), and that build has not been measured;
proposing it without a number would be guessing. `pixazo` bills EUR 0,32 a call and has
no business in a job triggered by a pull request. The `supabase` MCP server exposes
`execute_sql` and `apply_migration` against the live telemetry project, which is why no
Postgres skill is vendored to stand in for it either: the rules pack that used to be
here pointed the agent at raw DDL and at `supabase/migrations/`, the one file this
repository generates and forbids editing. `claude-plan.yml` is untouched: it gets no
skills, so it needs no `Skill`.

One property to know, and it is worth reading in the source rather than taking on
trust, because the whole vendoring scheme rests on it —
`base-action/src/parse-sdk-options.ts` in the pinned action:

```ts
settingSources: extraArgs["setting-sources"]
  ? (extraArgs["setting-sources"].split(",") as SdkOptions["settingSources"])
  : ["user", "project", "local"],
```

`project` is what indexes `.claude/skills/` out of the checkout, so the skills need
no install step. The same default has a second consequence: the action loads
`.claude/settings.json` **and `.claude/settings.local.json` from the pull request's
own checkout**, and a `settings.local.json` carries `permissions.allow` and
`enabledMcpjsonServers`. A committed one would let a pull request widen its own tool
allowance. It is in `.gitignore` for that reason — it had been ignored only by one
developer's global gitignore, which the next clone does not have. On a private
repository where only the two technical co-founders can push, the residual risk is
the same argument `allowed_bots` rests on. It stops holding the day this repository
becomes public, and the lever then is `--setting-sources user` in `claude_args`,
which also turns the vendored skills off.

## The labels

| Label | Meaning |
|---|---|
| `claude` | This issue is pipeline work. Without it nothing runs. |
| `tier:fable-plan` | Plan first. For multi-module, architectural or ambiguous work, or Size L. One extra pass, and it saves a wrong PR. |
| `tier:opus-direct` | Implement straight away. Single-module, clear approach, Size S/M, unambiguous spec. A README section took 32 turns; a Size L issue with a decision in it exhausted 80 (§ `--max-turns`). |
| `plan-ready` | A Plan comment exists. Added by `claude-plan`; it is what starts the implementer. |
| `risk:review` | A human makes the merge decision. The default. |
| `risk:auto` | Eligible for auto-merge — **only** when `AUTO_MERGE` is `on`, and only alongside every other gate. |
| `do-not-merge` | Never merge automatically, whatever else is true. Overrides `risk:auto`. |

## The auto-merge gate (Phase 2)

`claude-automerge.yml` merges only when **all** of these hold:

1. repository variable `AUTO_MERGE` is `on` (created as `off`);
2. the PR carries `risk:auto`;
3. the PR does not carry `do-not-merge`;
4. every check on the head commit is green (`SKIPPED` and `NEUTRAL` count; still-running does not);
5. the `claude-review` check specifically concluded `SUCCESS` — a PR with no `claude-review` entry is declined, because never reviewed is not approved;
6. the PR's author is the Claude app;
7. no changed file contains `LEGAL-DEFERRED`, read at the head commit.

Both of its triggers run the workflow file from the default branch, so a pull request
cannot loosen its own gate.

## How to stop it

Smallest lever first.

- **One pull request:** add `do-not-merge`. Auto-merge declines immediately.
- **A draft the safety net opened:** close it. Nothing reviews or resumes a closed
  draft, and the PR-exists guard ignores it, so the issue can be re-labelled. To keep
  the draft but stop the automatic attempts, comment on it — any human comment stands
  `claude-resume` down.
- **All automatic resumes:** `gh workflow disable claude-resume.yml`.
- **One issue:** remove the `claude` label, or remove `plan-ready` / `tier:*`. Nothing
  triggers without them.
- **A run that is going wrong right now:** cancel it in the Actions tab. Nothing
  resumes on its own — the safety net still runs (`if: always()`), so it pushes what
  the run had committed and opens a draft, but that draft is marked `subtype=cancelled`
  and `claude-resume` leaves it alone.
- **All auto-merging, everywhere:** `gh variable set AUTO_MERGE --body off`. This is
  the Phase 2 kill switch and it is the default state.
- **The whole pipeline:** disable the five `claude-*` workflows in the Actions tab
  (`gh workflow disable claude-plan.yml`, and the same for the other four). Disabling
  them does not touch `ci.yml` or `licence-data.yml`.
- **The fix loop:** capped at 3 rounds per PR inside `claude-review.yml`. After that it
  says so in a comment and stops asking. The Dispatcher counts rounds too. It also
  refuses to ask at all unless the pull request is **open** and its author is the
  **Claude app** — see below.

## Requiring the check

`claude-review` can only be selected as a required status check on `main` after it has
run once. Open the test issue from the setup guide, let the check run, then add both
`ci` and `claude-review` under Settings → Branches.

## Secrets

**`CLAUDE_CODE_OAUTH_TOKEN` is the one auth secret, and every workflow here uses it.**
`/install-github-app` created it, and `gh secret list` returns that name and nothing
else.

**`ANTHROPIC_API_KEY` does not exist in this repository**, and no workflow names it.
These workflows used to pass both credentials on the theory that whichever secret
existed would be the one used. That is not what the action does: it maps the input
straight onto the model's environment as

```yaml
ANTHROPIC_API_KEY: ${{ inputs.anthropic_api_key || env.ANTHROPIC_API_KEY }}
```

and an unset secret renders as the empty string, so naming a secret that does not
exist sets an *empty* credential rather than no credential. If anyone adds an
`ANTHROPIC_API_KEY` later — a billing decision, since the OAuth token draws on a
Claude subscription and an API key bills per token — switch the workflows to it
deliberately, one credential at a time.

No secret value belongs anywhere but GitHub's secrets UI.

## Pinned versions

`anthropics/claude-code-action` is pinned to an exact release (`v1.0.216`), not to
`@v1`. `@v1` is a moving tag: it is re-pointed as releases land, and at the time of
pinning it resolved to a commit *behind* the newest release. A moving tag on the one
third-party action in this pipeline means the model, its tool surface and its auth
handling can change under a workflow nobody edited. Bumping it is a one-line commit
that shows up in the diff, which is the point.

The first-party `actions/*` steps stay on their major tags (`@v4`, `@v5`, `@v6`),
matching `ci.yml` and `licence-data.yml`.
