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
| `.github/workflows/claude-plan.yml` | `claude-fable-5-1`, 30 turns | issue labelled | Posts one **Plan** comment — approach, files, tests, risks, open questions — then adds `plan-ready`. Writes no code. |
| `.github/workflows/claude-implement.yml` (`implement`) | `claude-opus-5`, 80 turns | issue labelled | Builds the CI environment, implements on `claude/issue-<n>`, runs the tests, opens a PR with the acceptance criteria as a checklist. |
| `.github/workflows/claude-implement.yml` (`fix`) | `claude-opus-5`, 80 turns | `@claude` comment on an **open, unmerged** PR | The fix loop. Interactive mode: no `prompt` input, so the comment *is* the request. |
| `.github/workflows/claude-review.yml` | `claude-fable-5-1`, 20 turns | PR opened / synchronised / reopened | Reviews against the linked issue and `CLAUDE.md`, posts one review, and **fails the check** when it asks for changes. |
| `.github/workflows/claude-automerge.yml` | none — plain `gh` | review submitted, check suite completed | Phase 2 only. Squash-merges and deletes the branch when every gate below passes. |

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

**Do not widen either list to `'*'`.** An allowed bot skips the write-permission check
as well as the human check, so `'*'` lets any GitHub App that can open a pull request
choose this job's prompt. Names are matched case-insensitively with a trailing `[bot]`
stripped, so one entry covers both spellings of a login.

A symptom worth recognising: the two-second failure looks identical in the check list
to a genuine `request_changes`. Read the **Review with Fable** step, not the
**Decide the check from the verdict** step — the second one only reports that the
first produced nothing.

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

One detail worth knowing before editing either guard: **`gh --json` reads GraphQL, and
GraphQL returns a GitHub App's login without the `[bot]` suffix.** The same comment is
authored by `claude` through `gh pr view --json comments` and by `claude[bot]` through
the REST endpoint. Both forms are listed in `CLAUDE_LOGINS`, in `claude-review.yml` and
`claude-automerge.yml` alike.

## The labels

| Label | Meaning |
|---|---|
| `claude` | This issue is pipeline work. Without it nothing runs. |
| `tier:fable-plan` | Plan first. For multi-module, architectural or ambiguous work, or Size L. One extra pass, and it saves a wrong PR. |
| `tier:opus-direct` | Implement straight away. Single-module, clear approach, Size S/M, unambiguous spec. |
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
- **One issue:** remove the `claude` label, or remove `plan-ready` / `tier:*`. Nothing
  triggers without them.
- **A run that is going wrong right now:** cancel it in the Actions tab. Nothing
  resumes on its own.
- **All auto-merging, everywhere:** `gh variable set AUTO_MERGE --body off`. This is
  the Phase 2 kill switch and it is the default state.
- **The whole pipeline:** disable the four `claude-*` workflows in the Actions tab
  (`gh workflow disable claude-plan.yml`, and the same for the other three). Disabling
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
