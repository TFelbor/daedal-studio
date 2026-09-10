"""The Claude Code pipeline's workflows, checked for the properties that fail silently.

`.github/workflows/claude-*.yml` is the one part of this repository that no test ran
against until now, and it is where the silent failures live: a tool allowlist missing
`Skill` makes every vendored skill inert with nothing in the log; a bot actor the
`allowed_bots` input does not name is refused *before* the model runs; a turn budget
one size too small throws away finished work; a step that only runs on success never
reports the failure it exists to report. None of those show up as a YAML error, and
each was found by a run that spent its whole budget first.

Each assertion below is one such property, read from the workflow files with a YAML
parser rather than a regex over the text, so a re-indent or a reordered key cannot
defeat it. The reasons are in `docs/PIPELINE.md`; the assertions are what keep them
true after the next edit.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
IMPLEMENT = WORKFLOWS / "claude-implement.yml"
PLAN = WORKFLOWS / "claude-plan.yml"
REVIEW = WORKFLOWS / "claude-review.yml"
AUTOMERGE = WORKFLOWS / "claude-automerge.yml"
RESUME = WORKFLOWS / "claude-resume.yml"
PIPELINE_WORKFLOWS = (IMPLEMENT, PLAN, REVIEW, AUTOMERGE, RESUME)

#: The one third-party action in the pipeline, and the form it must be pinned in.
ACTION = "anthropics/claude-code-action"
PINNED_ACTION = re.compile(rf"^{re.escape(ACTION)}@v\d+\.\d+\.\d+$")

#: The Claude GitHub App's logins as GitHub reports them. The plan job adds
#: `plan-ready` with the App's token, so the `labeled` event that starts the
#: implementer is sent by this bot, and the action refuses bot actors it is not told
#: about.
CLAUDE_APP_LOGINS = {"claude[bot]", "claude-code[bot]"}

#: Turn budgets. Measured: a README-only task (#53) took 32 turns; a Size L security
#: issue (#60) exhausted 80 without opening a pull request. The cap is a runaway
#: guard, not a cost control — `timeout-minutes` is the cost control — so it carries
#: slack rather than tracking a measured figure.
MIN_TURNS = {"implement": 200, "fix": 200, "plan": 60, "review": 80}

#: The safety-net script the implement and fix jobs run after the model, whatever
#: happened to it.
REPORT_SCRIPT = "infra/ci/claude_implement_report.sh"

#: The script claude-resume.yml runs on a schedule to re-dispatch implementations that
#: ended for a transient reason — the subscription's usage limit above all.
RESUME_SCRIPT = "infra/ci/claude_resume.py"


def _load(path: Path) -> dict:
    data = yaml.safe_load(path.read_text())
    assert isinstance(data, dict), f"{path.name} did not parse to a mapping"
    return data


def _triggers(workflow: dict) -> dict:
    # PyYAML reads a bare `on:` key as the boolean True (YAML 1.1).
    triggers = workflow.get("on", workflow.get(True))
    assert isinstance(triggers, dict), "workflow has no `on:` mapping"
    return triggers


def _steps(workflow: dict, job: str) -> list[dict]:
    jobs = workflow["jobs"]
    assert job in jobs, f"no job named {job!r}; jobs are {sorted(jobs)}"
    return jobs[job]["steps"]


def _action_steps(workflow: dict, job: str) -> list[dict]:
    steps = [s for s in _steps(workflow, job) if str(s.get("uses", "")).startswith(ACTION)]
    assert steps, f"job {job!r} has no {ACTION} step"
    return steps


def _claude_args(step: dict) -> str:
    args = step.get("with", {}).get("claude_args", "")
    assert args, f"step {step.get('name')!r} passes no claude_args"
    return args


def _max_turns(step: dict) -> int:
    match = re.search(r"--max-turns\s+(\d+)", _claude_args(step))
    assert match, f"step {step.get('name')!r} sets no --max-turns"
    return int(match.group(1))


def _allowed_tools(step: dict) -> list[str]:
    match = re.search(r'--allowedTools\s+"([^"]*)"', _claude_args(step))
    assert match, f"step {step.get('name')!r} sets no --allowedTools"
    return [tool.strip() for tool in match.group(1).split(",")]


def _allowed_bots(step: dict) -> set[str]:
    raw = step.get("with", {}).get("allowed_bots", "") or ""
    return {bot.strip() for bot in raw.split(",") if bot.strip()}


# --- pinning and secrets -----------------------------------------------------------


def _walk(node, path=()):
    """Every (key path, value) in a parsed workflow, so a property can be asserted on
    the structure rather than on the text — comments are free to *mention* anything."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield (*path, str(key)), value
            yield from _walk(value, (*path, str(key)))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _walk(value, (*path, str(index)))


@pytest.mark.parametrize("path", PIPELINE_WORKFLOWS, ids=lambda p: p.name)
def test_pipeline_workflows_never_pass_the_absent_api_key(path: Path) -> None:
    """`ANTHROPIC_API_KEY` does not exist in this repository, and the action renders an
    unset secret as an *empty* credential rather than no credential. Neither the
    action's `anthropic_api_key` input nor an `ANTHROPIC_API_KEY` env entry may
    appear; the comments explaining why are allowed to name it."""
    offenders = [".".join(keys) for keys, _ in _walk(_load(path)) if keys[-1].lower() == "anthropic_api_key"]
    assert not offenders, (
        f"{path.name} passes the API key at {offenders}; the only auth secret is "
        "CLAUDE_CODE_OAUTH_TOKEN (docs/PIPELINE.md § Secrets)"
    )


def test_every_action_step_pins_the_same_exact_release() -> None:
    """`@v1` is a moving tag. One exact version, the same in every file, so that a bump
    is a diff someone reads rather than a change nobody made."""
    versions = set()
    for path in PIPELINE_WORKFLOWS:
        for job in _load(path)["jobs"].values():
            for step in job.get("steps", []):
                uses = str(step.get("uses", ""))
                if uses.startswith(ACTION):
                    assert PINNED_ACTION.match(uses), f"{path.name}: {uses!r} is not pinned to an exact release"
                    versions.add(uses)
    assert versions, "no claude-code-action step found in any pipeline workflow"
    assert len(versions) == 1, f"the action is pinned to different releases across the pipeline: {sorted(versions)}"


# --- the implement job --------------------------------------------------------------


def test_implement_admits_the_claude_app_as_a_labeler() -> None:
    """`claude-plan` adds `plan-ready` with the App's token, so the event that starts the
    implementer is sent by `claude[bot]`. Without `allowed_bots` the action refuses it
    in two seconds and the plan-first tier can never hand off."""
    (step,) = _action_steps(_load(IMPLEMENT), "implement")
    bots = {bot.lower() for bot in _allowed_bots(step)}
    assert bots != {"*"}, "never widen allowed_bots to '*'"
    assert CLAUDE_APP_LOGINS <= bots, f"implement allows {sorted(bots)}, not the Claude app"


@pytest.mark.parametrize("job", ["implement", "fix"])
def test_implement_jobs_carry_the_measured_turn_budget(job: str) -> None:
    (step,) = _action_steps(_load(IMPLEMENT), job)
    assert _max_turns(step) >= MIN_TURNS[job], (
        f"{job} has --max-turns {_max_turns(step)}; 80 was exhausted on issue #60 "
        "before a pull request existed"
    )


@pytest.mark.parametrize("job", ["implement", "fix"])
def test_implement_jobs_can_invoke_the_vendored_skills(job: str) -> None:
    (step,) = _action_steps(_load(IMPLEMENT), job)
    assert "Skill" in _allowed_tools(step), f"{job}: without Skill on --allowedTools every vendored skill is inert"


def test_implement_does_not_rely_on_branch_name_template() -> None:
    """The action only creates the branch in tag mode. With a `prompt` input it runs in
    automation mode, where `branch_name_template` is read by nothing — so the workflow
    must create the branch itself rather than describe one that never appears."""
    (step,) = _action_steps(_load(IMPLEMENT), "implement")
    assert "branch_name_template" not in step.get("with", {}), (
        "branch_name_template is inert in automation mode; create the branch in a step"
    )
    names = [s.get("name", "") for s in _steps(_load(IMPLEMENT), "implement")]
    assert any("branch" in n.lower() for n in names), f"no step creates the working branch; steps are {names}"


def test_implement_can_be_started_by_hand_for_one_issue() -> None:
    """A failed run must be retryable without the remove-and-re-add label dance, and
    `workflow_dispatch` is also the only way to run the job on demand."""
    workflow = _load(IMPLEMENT)
    triggers = _triggers(workflow)
    assert "workflow_dispatch" in triggers, "claude-implement has no workflow_dispatch trigger"
    inputs = (triggers["workflow_dispatch"] or {}).get("inputs", {})
    assert "issue_number" in inputs, f"workflow_dispatch inputs are {sorted(inputs)}; need issue_number"
    assert inputs["issue_number"].get("required") is True
    assert "issue_number" in str(workflow["concurrency"]["group"]), (
        "the concurrency group must key on the dispatched issue too, or two runs for one issue can overlap"
    )


def _step_named(workflow: dict, job: str, fragment: str) -> dict:
    """The step whose `uses` names the fragment, or whose `run` invokes it on a line that
    is not a comment — a step that merely *mentions* a script in a comment is not the
    step that runs it."""
    for step in _steps(workflow, job):
        if fragment in str(step.get("uses", "")):
            return step
        for line in str(step.get("run", "")).splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and fragment in stripped:
                return step
    raise AssertionError(f"job {job!r} has no step using {fragment!r}")


@pytest.mark.parametrize("job", ["implement", "fix"])
def test_implement_jobs_report_the_outcome_whatever_it_was(job: str) -> None:
    """The safety net: push what was committed, open a draft pull request when none
    exists, and say on the issue what happened. It must run when the model step fails,
    which is precisely when nothing else would."""
    workflow = _load(IMPLEMENT)
    step = _step_named(workflow, job, REPORT_SCRIPT)
    assert "always()" in str(step.get("if", "")), f"{job}: the report step must run with if: always()"
    assert (REPO_ROOT / REPORT_SCRIPT).exists(), f"{REPORT_SCRIPT} is missing"


@pytest.mark.parametrize("job", ["implement", "fix"])
def test_implement_jobs_keep_the_transcript(job: str) -> None:
    """The action hides the model's turns from the log for good reason; the execution
    file is the only record of where a budget went. Kept as an artifact on failure and
    success alike, because a transcript is only useful when nobody expected to need it."""
    workflow = _load(IMPLEMENT)
    step = _step_named(workflow, job, "actions/upload-artifact")
    assert "always()" in str(step.get("if", "")), f"{job}: the transcript upload must run with if: always()"
    assert "execution_file" in str(step.get("with", {}).get("path", "")), (
        f"{job}: the artifact must upload the action's execution_file output"
    )


@pytest.mark.parametrize("job", ["implement", "fix"])
def test_the_report_step_carries_a_second_token(job: str) -> None:
    """The App's token is revoked when the action's step ends, and the report step runs
    after it under `if: always()`. `${{ steps.X.outputs.github_token || github.token }}`
    cannot notice: the action produced a token, so the `||` never fires and a revoked
    token is a non-empty string. Issue #65 lost its draft pull request and its issue
    comment to `HTTP 401` that way, with a green tail and nothing for claude-resume to
    find. `select_token` in the script probes and swaps; it needs something to swap to."""
    step = _step_named(_load(IMPLEMENT), job, REPORT_SCRIPT)
    env = step.get("env", {})
    assert "GH_TOKEN_FALLBACK" in env, f"{job}: the report step passes no fallback token"
    assert "github.token" in str(env["GH_TOKEN_FALLBACK"]), (
        f"{job}: the fallback must be the workflow's own token, not {env['GH_TOKEN_FALLBACK']!r}"
    )
    assert "github_token" in str(env.get("GH_TOKEN", "")), (
        f"{job}: the App's token must still be preferred; GH_TOKEN is {env.get('GH_TOKEN')!r}"
    )


# --- the plan job -------------------------------------------------------------------


def test_plan_carries_a_turn_budget_with_slack() -> None:
    (step,) = _action_steps(_load(PLAN), "plan")
    assert _max_turns(step) >= MIN_TURNS["plan"]


def test_plan_reports_its_own_failure_to_the_issue() -> None:
    """A plan that never posts is an issue that waits forever for `plan-ready`."""
    steps = _steps(_load(PLAN), "plan")
    failure_steps = [s for s in steps if "failure()" in str(s.get("if", ""))]
    assert failure_steps, "claude-plan has no step that runs on failure"
    assert any("gh issue comment" in str(s.get("run", "")) for s in failure_steps), (
        "the failure step must comment on the issue"
    )


# --- the review job -----------------------------------------------------------------


def test_review_carries_the_measured_turn_budget() -> None:
    (step,) = _action_steps(_load(REVIEW), "claude-review")
    assert _max_turns(step) >= MIN_TURNS["review"]
    assert "Skill" in _allowed_tools(step)


#: How `gh` spells the Claude GitHub App, by field. The same actor is `app/claude` as a
#: pull request's `author.login` (GraphQL, with `is_bot: true`), `claude` on comments
#: and reviews, and `claude[bot]` over REST. A gate that compares one field against a
#: list written for another silently never matches — which is how claude-review
#: requested changes on PR #92 and then declined to ask for the fix.
APP_LOGIN_SPELLINGS = {"app/claude", "claude", "claude[bot]"}


def _claude_logins(workflow: dict, job: str) -> set[str]:
    for step in _steps(workflow, job):
        env = step.get("env") or {}
        if "CLAUDE_LOGINS" in env:
            return set(str(env["CLAUDE_LOGINS"]).split())
    raise AssertionError(f"job {job!r} has no step with CLAUDE_LOGINS")


def test_review_and_automerge_recognise_every_spelling_of_the_app() -> None:
    """Both gates decide on `gh pr view --json author`, which spells the App `app/claude`.
    The lists must carry that form, and must not drift from each other."""
    review = _claude_logins(_load(REVIEW), "claude-review")
    automerge = _claude_logins(_load(AUTOMERGE), "automerge")
    assert review == automerge, f"CLAUDE_LOGINS differ: review {sorted(review)} vs automerge {sorted(automerge)}"
    assert APP_LOGIN_SPELLINGS <= review, f"CLAUDE_LOGINS lacks {sorted(APP_LOGIN_SPELLINGS - review)}"


def test_review_and_automerge_normalise_the_login_before_comparing() -> None:
    """A list of spellings is a list that is wrong the next time `gh` changes one. The
    comparison strips the `app/` prefix and the `[bot]` suffix — neither can appear in a
    human login (`/` and `[` are not legal username characters), so stripping them
    widens nothing."""
    for path, job in ((REVIEW, "claude-review"), (AUTOMERGE, "automerge")):
        run = "\n".join(str(s.get("run", "")) for s in _steps(_load(path), job) if "CLAUDE_LOGINS" in (s.get("env") or {}))
        assert "app/" in run and "[bot]" in run, f"{path.name}: the comparison does not normalise app/ and [bot]"


def test_review_admits_the_workflow_bot_whose_push_re_triggers_it() -> None:
    """A fix-job push is authenticated with the run's own GITHUB_TOKEN (actions/checkout's
    persisted credential outranks the App token in the remote URL), so the `synchronize`
    it fires carries `actor: github-actions[bot]`. The review refused that actor before
    Fable ran, so every fix pushed by the loop went unreviewed — PR #92 stayed red on a
    diff that fixed the review's finding. Same trust as the `fix` job already extends."""
    (step,) = _action_steps(_load(REVIEW), "claude-review")
    bots = {bot.lower() for bot in _allowed_bots(step)}
    assert bots != {"*"}
    assert "github-actions[bot]" in bots, f"claude-review allows {sorted(bots)}"


def test_review_skips_drafts_and_returns_when_they_are_ready() -> None:
    """The safety net opens *draft* pull requests holding unfinished work. Reviewing one
    would request changes on a diff nobody claims is done and start the fix loop
    against it; skipping drafts without listening for `ready_for_review` would leave
    the finished version unreviewed."""
    workflow = _load(REVIEW)
    types = _triggers(workflow)["pull_request"]["types"]
    assert "ready_for_review" in types, f"pull_request types are {types}"
    condition = str(workflow["jobs"]["claude-review"].get("if", ""))
    assert "draft == false" in condition, f"claude-review does not skip drafts; if is {condition!r}"


def test_review_keeps_the_transcript() -> None:
    """A review that returns no structured output fails the check with nothing in the
    run saying why: the action hides the model's turns and prints only a summary of the
    final result message. The execution file is the rest of that message. Uploaded with
    `if: always()`, because the only runs worth reading are the ones that failed."""
    workflow = _load(REVIEW)
    step = _step_named(workflow, "claude-review", "actions/upload-artifact")
    assert "always()" in str(step.get("if", "")), "the transcript upload must run with if: always()"
    with_ = step.get("with", {})
    assert "execution_file" in str(with_.get("path", "")), (
        "the artifact must upload the action's execution_file output"
    )
    assert with_.get("retention-days") == 14, (
        "a transcript that may hold a printed environment must expire; 14 days matches claude-implement"
    )


def test_review_full_output_is_a_lever_and_is_off_by_default() -> None:
    """`show_full_output` prints every tool result into a run log with no retention
    limit — upstream's own input description warns it may carry secrets and API keys.
    So it is gated on a repository variable, the way AUTO_MERGE is, and never written
    as a literal `true`: a workflow that ships verbose is one nobody remembers to turn
    back off."""
    (step,) = _action_steps(_load(REVIEW), "claude-review")
    value = str(step.get("with", {}).get("show_full_output", ""))
    assert value, "the review step does not set show_full_output at all"
    assert "vars." in value, f"show_full_output must read a repository variable; it is {value!r}"
    assert value.strip().lower() not in {"true", "'true'", '"true"'}, (
        f"show_full_output must not be hardcoded on; it is {value!r}"
    )


def _decide_script() -> str:
    """The `Decide the check from the verdict` step's shell, by the name it is known by
    rather than by its index — the step order has changed twice."""
    step = _step_named(_load(REVIEW), "claude-review", "STATUS_MARKER")
    return str(step["run"])


def _marker(script: str, name: str) -> str:
    match = re.search(rf"^\s*{name}='([^']*)'", script, re.MULTILINE)
    assert match, f"{name} is not assigned a single-quoted literal in the decide script"
    return match.group(1)


def test_review_comments_its_outcome_on_every_terminal_path() -> None:
    """The outcome used to go only to the step summary, which is three clicks into the
    Actions tab. The model posts its own review whenever it runs — so the two paths
    where it does not run (the workflow-validation exemption, and a review that returns
    no structured output) were the two that reached nobody, and PRs #98 and #99 were
    merged with no verdict and nothing on either page saying so. Every path that ends
    this step must write the comment first."""
    script = _decide_script()
    assert "upsert_status()" in script, "the decide script defines no upsert_status function"
    lines = script.splitlines()
    exits = [i for i, line in enumerate(lines) if re.match(r"\s*exit [01]\s*$", line)]
    assert len(exits) == 5, f"expected the five documented terminal paths, found {len(exits)}"
    for i in exits:
        window = "\n".join(lines[max(0, i - 12) : i])
        assert "upsert_status" in window, (
            f"the exit on line {i + 1} ({lines[i].strip()}) is not preceded by an upsert_status call"
        )


def test_review_status_comment_does_not_carry_the_fix_loop_s_marker() -> None:
    """`rounds` counts comments containing the fix-request marker to enforce the
    three-round cap. A status comment carrying that string would spend the budget by
    itself and stop the loop before it ever ran — one comment per run, three runs, cap
    reached, no fix ever requested."""
    script = _decide_script()
    status = _marker(script, "STATUS_MARKER")
    fix = _marker(script, "marker")
    assert status != fix, f"both markers are {status!r}"
    assert fix not in status and status not in fix, (
        f"one marker contains the other: status={status!r} fix={fix!r}"
    )
    assert f'contains(\\"${{marker}}\\")' in script or "${marker}" in script, (
        "the round counter no longer counts the fix-request marker"
    )


def test_review_status_comment_cannot_change_the_check() -> None:
    """The verdict decides the check. Turning an approval red because GitHub answered
    502 to a comment would be the worse bug, and `set -e` is one unguarded `gh` call
    away from doing exactly that."""
    lines = _decide_script().splitlines()
    start = next(i for i, line in enumerate(lines) if "upsert_status()" in line)
    end = next(i for i, line in enumerate(lines[start:], start) if line.strip() == "}")
    body = lines[start : end + 1]
    # A line that merely mentions `gh` in a comment is not a call, the same distinction
    # `_step_named` makes.
    calls = [
        i
        for i, line in enumerate(body)
        if re.search(r"\bgh (api|pr) ", line) and not line.strip().startswith("#")
    ]
    assert calls, "upsert_status makes no gh call at all"
    for i in calls:
        # A gh call may continue over backslash-joined lines; the guard is the `||` that
        # ends the statement, so read forward to the end of it.
        statement = []
        j = i
        while True:
            statement.append(body[j])
            if not body[j].rstrip().endswith("\\"):
                break
            j += 1
        joined = " ".join(statement)
        assert "||" in joined, (
            f"unguarded gh call inside upsert_status, which `set -e` turns into a failed check: {joined.strip()}"
        )


# --- resuming after a usage limit ----------------------------------------------------------


def test_implement_admits_the_workflow_bot_that_redispatches_it() -> None:
    """claude-resume re-runs the implementer with `gh workflow run` under the workflow
    token, so the dispatch actor is `github-actions[bot]`; the action refuses it unless
    named. Same trust argument as the `fix` job's `allowed_bots`."""
    (step,) = _action_steps(_load(IMPLEMENT), "implement")
    bots = {bot.lower() for bot in _allowed_bots(step)}
    assert "github-actions[bot]" in bots, f"implement allows {sorted(bots)}"


def test_implement_prompt_tells_a_resumed_run_that_it_is_resuming() -> None:
    """The branch already has commits and a draft describes how the last run ended; a
    model that does not know that starts over. The guard step decides and the prompt
    carries its note — empty on a fresh run."""
    workflow = _load(IMPLEMENT)
    (step,) = _action_steps(workflow, "implement")
    assert "steps.guard.outputs.resume_note" in step["with"]["prompt"]
    guard = [s for s in _steps(workflow, "implement") if s.get("id") == "guard"]
    assert guard, "no step with id guard"
    assert "resume_note" in guard[0]["run"] and "isDraft" in guard[0]["run"], (
        "the guard must recognise the safety net's draft and emit a resume note"
    )


def test_resume_workflow_runs_on_a_schedule_and_can_dispatch() -> None:
    workflow = _load(RESUME)
    triggers = _triggers(workflow)
    assert "schedule" in triggers and "workflow_dispatch" in triggers, f"triggers are {sorted(triggers)}"
    perms = workflow["permissions"]
    assert perms.get("actions") == "write", "gh workflow run needs actions: write"
    assert perms.get("pull-requests") == "write", "the resume comment needs pull-requests: write"
    assert perms.get("contents") == "read"
    _step_named(workflow, "resume", RESUME_SCRIPT)
    assert (REPO_ROOT / RESUME_SCRIPT).exists()
    assert "concurrency" in workflow, "two ticks must not dispatch the same draft twice"

