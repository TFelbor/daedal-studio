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
| `.github/workflows/claude-implement.yml` (`fix`) | `claude-opus-5`, 80 turns | `@claude` comment on a PR | The fix loop. Interactive mode: no `prompt` input, so the comment *is* the request. |
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
  says so in a comment and stops asking. The Dispatcher counts rounds too.

## Requiring the check

`claude-review` can only be selected as a required status check on `main` after it has
run once. Open the test issue from the setup guide, let the check run, then add both
`ci` and `claude-review` under Settings → Branches.

## Secrets

`ANTHROPIC_API_KEY` is a repository secret, installed by `/install-github-app`. No
workflow here reads any other secret, and none should be pasted anywhere but GitHub's
secrets UI.
