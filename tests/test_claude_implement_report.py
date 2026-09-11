"""`infra/ci/claude_implement_report.sh` leaves a failed implementation where a person
can find it.

The model step of `claude-implement.yml` used to be the last step that did anything.
When it ran out of turns — as it did on issue #60, after 81 turns and with nothing
pushed — the job went red in the Actions tab and that was the whole report: no branch,
no pull request, no comment on the issue, no transcript. The person who labelled the
issue found out by going to look.

The script runs after the model with `if: always()` and turns whatever state the run
left into something with a URL: uncommitted edits become a `WIP:` commit, commits are
pushed, a branch with no pull request gets a draft one, and the issue is told which of
those happened and why the run ended. A person can then finish it, resume it with one
`@claude` comment, or throw it away — but never wonder.

These tests run the real script against a real git remote (a bare repository on disk)
with a fake `gh` on PATH that records every invocation and answers the two queries the
script makes. Asserting on the recorded argv is asserting on the GitHub calls that would
have been made; asserting on the bare repository is asserting on what was pushed.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "infra" / "ci" / "claude_implement_report.sh"

pytestmark = pytest.mark.skipif(shutil.which("jq") is None, reason="the report script needs jq, as the runner has")

FAKE_GH = r"""#!/usr/bin/env bash
# Records every call on one line (newlines in a --body flattened to spaces) and
# answers the queries the script makes.
printf '%s\n' "$(printf '%s' "$*" | tr '\n' ' ')" >> "$FAKE_GH_LOG"
# A token the App has already revoked is refused on every route, which is exactly what
# issue #65's run saw. Recorded before the refusal, because the attempt is the thing a
# test needs to see.
if [ "${GH_TOKEN:-}" = "revoked" ]; then
  echo 'HTTP 401: Bad credentials (https://api.github.com/graphql)' >&2
  exit 1
fi
case "$1 $2" in
  "api rate_limit") printf '{"rate":{"remaining":4999}}' ;;
  "pr list")   printf '%s' "${FAKE_GH_PR_LIST:-[]}" ;;
  "pr create")
    # GITHUB_TOKEN may not open a pull request unless the repository allows Actions to;
    # it is off here, so the fallback token pushes and comments and still fails at this.
    if [ -n "${FAKE_GH_PR_CREATE_FAILS:-}" ]; then
      echo 'pull request create failed: GraphQL: GitHub Actions is not permitted to create or approve pull requests' >&2
      exit 1
    fi
    echo "https://github.com/Daedal-Studio/ds-mvp/pull/${FAKE_GH_NEW_PR:-99}" ;;
  "pr comment"|"issue comment"|"pr ready"|"pr edit") : ;;
  *) echo "fake gh: unexpected invocation: $*" >&2; exit 64 ;;
esac
"""


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> dict:
    """A bare `origin` with one commit on `main`, a clone on `claude/issue-7`, and a
    fake `gh` first on PATH."""
    origin = tmp_path / "origin.git"
    seed = tmp_path / "seed"
    seed.mkdir()
    _git(seed, "init", "-q", "-b", "main")
    _git(seed, "config", "user.name", "Seed")
    _git(seed, "config", "user.email", "seed@example.invalid")
    (seed / "README.md").write_text("seed\n")
    _git(seed, "add", "README.md")
    _git(seed, "commit", "-q", "-m", "seed")
    _git(seed, "init", "-q", "--bare", str(origin))
    _git(seed, "push", "-q", str(origin), "main")

    work = tmp_path / "work"
    _git(tmp_path, "clone", "-q", str(origin), str(work))
    # The action configures the bot identity before the model runs; the script must
    # not depend on it, so most tests leave it unset (see test_wip_commit_...).
    _git(work, "checkout", "-q", "-b", "claude/issue-7")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(FAKE_GH)
    gh.chmod(0o755)
    log = tmp_path / "gh.log"
    log.touch()
    return {"origin": origin, "work": work, "bin": bin_dir, "log": log, "tmp": tmp_path}


def _run(repo: dict, **env: str) -> subprocess.CompletedProcess:
    full_env = {
        **os.environ,
        "PATH": f"{repo['bin']}{os.pathsep}{os.environ['PATH']}",
        "FAKE_GH_LOG": str(repo["log"]),
        "GH_TOKEN": "fake",
        "ISSUE_NUMBER": "7",
        "ISSUE_TITLE": "Bind the API server to loopback by default",
        "BRANCH": "claude/issue-7",
        "BASE_BRANCH": "main",
        "RUN_URL": "https://github.com/Daedal-Studio/ds-mvp/actions/runs/1",
        "MODE": "implement",
        **env,
    }
    return subprocess.run(
        ["bash", str(SCRIPT)], cwd=repo["work"], env=full_env, capture_output=True, text=True
    )


def _calls(repo: dict) -> list[str]:
    return [line for line in repo["log"].read_text().splitlines() if line]


def _reports(repo: dict) -> list[str]:
    """Every `gh` call except `select_token`'s probe. "Silent" means the script wrote
    nothing to GitHub, not that it never asked whether it could."""
    return [c for c in _calls(repo) if not c.startswith("api rate_limit")]


def _commit(repo: dict, name: str) -> None:
    (repo["work"] / name).write_text(f"{name}\n")
    _git(repo["work"], "add", name)
    _git(
        repo["work"], "-c", "user.name=Model", "-c", "user.email=model@example.invalid",
        "commit", "-q", "-m", f"feat: {name}",
    )


def _remote_has_branch(repo: dict, branch: str = "claude/issue-7") -> bool:
    out = _git(repo["origin"], "branch", "--list", branch)
    return branch in out


def _execution_file(repo: dict, subtype: str = "error_max_turns", turns: int = 81, denials: int = 1,
                    errors: list[str] | None = None) -> str:
    path = repo["tmp"] / "claude-execution-output.json"
    result = {"type": "result", "subtype": subtype, "is_error": subtype != "success",
              "num_turns": turns, "permission_denials": [{"tool_name": "Bash"}] * denials}
    if errors is not None:
        result["errors"] = errors
    messages = [{"type": "system", "subtype": "init", "session_id": "abc"}, result]
    path.write_text(json.dumps(messages))
    return str(path)


# --- nothing to save ----------------------------------------------------------------


def test_failure_with_no_commits_tells_the_issue_and_pushes_nothing(repo: dict) -> None:
    result = _run(repo, CONCLUSION="failure", EXECUTION_FILE=_execution_file(repo))
    assert result.returncode == 0, result.stderr
    calls = _calls(repo)
    assert not _remote_has_branch(repo), "an empty branch was pushed"
    assert not any(c.startswith("pr create") for c in calls)
    (comment,) = [c for c in calls if c.startswith("issue comment 7 ")]
    assert "did not open a pull request" in comment
    assert "error_max_turns" in comment and "81 turns" in comment
    assert "1 permission denial" in comment
    assert "actions/runs/1" in comment


def test_the_reason_falls_back_when_there_is_no_execution_file(repo: dict) -> None:
    result = _run(repo, CONCLUSION="failure", EXECUTION_FILE=str(repo["tmp"] / "missing.json"))
    assert result.returncode == 0, result.stderr
    (comment,) = [c for c in _calls(repo) if c.startswith("issue comment 7 ")]
    assert "did not report a result" in comment


# --- commits to save ----------------------------------------------------------------


def test_failure_with_commits_pushes_and_opens_a_draft_pull_request(repo: dict) -> None:
    _commit(repo, "server_bind.py")
    result = _run(repo, CONCLUSION="failure", EXECUTION_FILE=_execution_file(repo), RISK_LABEL="risk:review")
    assert result.returncode == 0, result.stderr
    assert _remote_has_branch(repo)
    assert _git(repo["origin"], "rev-parse", "claude/issue-7") == _git(repo["work"], "rev-parse", "HEAD")

    calls = _calls(repo)
    (create,) = [c for c in calls if c.startswith("pr create ")]
    assert "--draft" in create
    assert "--head claude/issue-7" in create and "--base main" in create
    assert "--label risk:review" in create
    assert "WIP: Bind the API server to loopback by default" in create
    assert "Closes #7" in create
    assert "error_max_turns" in create
    assert "@claude please continue" in create, "the resume instruction is what makes the draft recoverable"

    (comment,) = [c for c in calls if c.startswith("issue comment 7 ")]
    assert "pull/99" in comment


def test_uncommitted_edits_become_a_wip_commit_before_the_push(repo: dict) -> None:
    _commit(repo, "server_bind.py")
    (repo["work"] / "half_done.py").write_text("x = 1\n")
    (repo["work"] / "README.md").write_text("seed\nedited\n")
    result = _run(repo, CONCLUSION="failure", EXECUTION_FILE=_execution_file(repo))
    assert result.returncode == 0, result.stderr
    subject = _git(repo["work"], "log", "-1", "--format=%s")
    assert subject.startswith("WIP:"), subject
    assert _git(repo["work"], "status", "--porcelain") == ""
    assert _git(repo["origin"], "rev-parse", "claude/issue-7") == _git(repo["work"], "rev-parse", "HEAD")
    tracked = _git(repo["work"], "ls-tree", "--name-only", "HEAD")
    assert "half_done.py" in tracked


def test_wip_commit_respects_gitignore(repo: dict) -> None:
    (repo["work"] / ".gitignore").write_text("secrets.env\n")
    _git(repo["work"], "add", ".gitignore")
    _git(repo["work"], "-c", "user.name=Model", "-c", "user.email=model@example.invalid", "commit", "-q", "-m", "chore: ignore")
    (repo["work"] / "secrets.env").write_text("TOKEN=abc\n")
    (repo["work"] / "work.py").write_text("y = 2\n")
    _run(repo, CONCLUSION="failure", EXECUTION_FILE=_execution_file(repo))
    tracked = _git(repo["work"], "ls-tree", "--name-only", "HEAD")
    assert "work.py" in tracked
    assert "secrets.env" not in tracked


def test_failure_with_an_existing_pull_request_comments_there_instead(repo: dict) -> None:
    _commit(repo, "server_bind.py")
    pr_list = json.dumps([{"number": 12, "url": "https://github.com/Daedal-Studio/ds-mvp/pull/12", "isDraft": False}])
    result = _run(repo, CONCLUSION="failure", EXECUTION_FILE=_execution_file(repo), FAKE_GH_PR_LIST=pr_list)
    assert result.returncode == 0, result.stderr
    assert _remote_has_branch(repo)
    calls = _calls(repo)
    assert not any(c.startswith("pr create") for c in calls), "a second pull request was opened"
    (comment,) = [c for c in calls if c.startswith("pr comment 12 ")]
    assert "error_max_turns" in comment and "@claude please continue" in comment
    assert not any(c.startswith("issue comment") for c in calls), "the pull request is the place to talk"


# --- success ------------------------------------------------------------------------


def test_success_with_a_pull_request_is_silent(repo: dict) -> None:
    _commit(repo, "server_bind.py")
    _git(repo["work"], "push", "-q", "-u", "origin", "claude/issue-7")
    pr_list = json.dumps([{"number": 12, "url": "https://github.com/Daedal-Studio/ds-mvp/pull/12", "isDraft": False}])
    result = _run(repo, CONCLUSION="success", EXECUTION_FILE=_execution_file(repo, "success", 40, 0), FAKE_GH_PR_LIST=pr_list)
    assert result.returncode == 0, result.stderr
    calls = _reports(repo)
    assert calls == [c for c in calls if c.startswith("pr list ")], f"a successful run with a PR made noise: {calls}"


def test_success_without_a_pull_request_opens_a_draft_and_says_so(repo: dict) -> None:
    """The model can finish and still never run `gh pr create` — a denied tool call, a
    turn spent elsewhere. Success without a pull request is not done."""
    _commit(repo, "server_bind.py")
    result = _run(repo, CONCLUSION="success", EXECUTION_FILE=_execution_file(repo, "success", 40, 0))
    assert result.returncode == 0, result.stderr
    calls = _calls(repo)
    (create,) = [c for c in calls if c.startswith("pr create ")]
    assert "--draft" in create
    (comment,) = [c for c in calls if c.startswith("issue comment 7 ")]
    assert "without opening a pull request" in comment


def test_success_with_nothing_committed_tells_the_issue(repo: dict) -> None:
    result = _run(repo, CONCLUSION="success", EXECUTION_FILE=_execution_file(repo, "success", 12, 0))
    assert result.returncode == 0, result.stderr
    (comment,) = [c for c in _calls(repo) if c.startswith("issue comment 7 ")]
    assert "without changing any file" in comment


# --- the fix job --------------------------------------------------------------------


def test_fix_mode_pushes_unpushed_commits_and_comments_on_the_pull_request(repo: dict) -> None:
    _commit(repo, "first.py")
    _git(repo["work"], "push", "-q", "-u", "origin", "claude/issue-7")
    _commit(repo, "second.py")
    result = _run(repo, MODE="fix", PR_NUMBER="12", CONCLUSION="failure", EXECUTION_FILE=_execution_file(repo))
    assert result.returncode == 0, result.stderr
    assert _git(repo["origin"], "rev-parse", "claude/issue-7") == _git(repo["work"], "rev-parse", "HEAD")
    calls = _calls(repo)
    assert not any(c.startswith("pr create") or c.startswith("pr list") for c in calls)
    (comment,) = [c for c in calls if c.startswith("pr comment 12 ")]
    assert "error_max_turns" in comment


def test_fix_mode_success_is_silent(repo: dict) -> None:
    _commit(repo, "first.py")
    _git(repo["work"], "push", "-q", "-u", "origin", "claude/issue-7")
    result = _run(repo, MODE="fix", PR_NUMBER="12", CONCLUSION="success", EXECUTION_FILE=_execution_file(repo, "success", 20, 0))
    assert result.returncode == 0, result.stderr
    assert _reports(repo) == []


# --- it never masks the model step ---------------------------------------------------


def test_the_script_exits_zero_even_when_github_is_unreachable(repo: dict) -> None:
    """The job is already red when the model failed; a reporting error on top of it
    must not replace the real failure in the job's summary."""
    _commit(repo, "server_bind.py")
    broken = repo["bin"] / "gh"
    broken.write_text("#!/usr/bin/env bash\necho 'HTTP 502' >&2\nexit 1\n")
    result = _run(repo, CONCLUSION="failure", EXECUTION_FILE=_execution_file(repo))
    assert result.returncode == 0, result.stderr
    assert "502" in result.stderr or "502" in result.stdout


# --- the resume protocol: markers the claude-resume workflow reads -----------------------

SAFETY_NET_DRAFT = json.dumps([{
    "number": 12, "url": "https://github.com/Daedal-Studio/ds-mvp/pull/12", "isDraft": True,
    "title": "WIP: Bind the API server to loopback by default",
    "body": "Closes #7\n\n<!-- claude-implement-safety-net subtype=error_during_execution -->\n**Opened by the claude-implement workflow**",
}])
DRAFT_FIRST_DRAFT = json.dumps([{
    "number": 12, "url": "https://github.com/Daedal-Studio/ds-mvp/pull/12", "isDraft": True,
    "title": "WIP: Bind the API server to loopback by default",
    "body": "Closes #7\n\n<!-- claude-implement-draft-first -->\n## Acceptance criteria\n\n- [ ] the first one",
}])
HUMAN_DRAFT = json.dumps([{
    "number": 13, "url": "https://github.com/Daedal-Studio/ds-mvp/pull/13", "isDraft": True,
    "title": "Bind the API server to loopback by default",
    "body": "Closes #7\n\nStill working on the tests.",
}])


def test_the_reason_carries_the_first_error_text(repo: dict) -> None:
    """A usage-limit or API failure arrives as `error_during_execution` with the error in
    `errors`; the subtype alone does not say whether waiting would help."""
    ef = _execution_file(repo, "error_during_execution", 12, 0,
                         errors=['API Error: 429 {"type":"rate_limit_error","message":"usage limit reached"}'])
    result = _run(repo, CONCLUSION="failure", EXECUTION_FILE=ef)
    assert result.returncode == 0, result.stderr
    (comment,) = [c for c in _calls(repo) if c.startswith("issue comment 7 ")]
    assert "error_during_execution after 12 turns" in comment
    assert "429" in comment and "rate_limit_error" in comment


def test_draft_body_carries_the_safety_net_marker_with_the_subtype(repo: dict) -> None:
    _commit(repo, "a.py")
    _run(repo, CONCLUSION="failure", EXECUTION_FILE=_execution_file(repo, "error_during_execution", 12, 0, errors=["boom"]))
    (create,) = [c for c in _calls(repo) if c.startswith("pr create ")]
    assert "<!-- claude-implement-safety-net subtype=error_during_execution -->" in create


def test_pr_comment_carries_the_safety_net_marker_with_the_subtype(repo: dict) -> None:
    _commit(repo, "a.py")
    _run(repo, CONCLUSION="failure", EXECUTION_FILE=_execution_file(repo), FAKE_GH_PR_LIST=SAFETY_NET_DRAFT)
    (comment,) = [c for c in _calls(repo) if c.startswith("pr comment 12 ")]
    assert "<!-- claude-implement-safety-net subtype=error_max_turns -->" in comment


def test_a_transient_failure_says_the_resume_workflow_will_retry(repo: dict) -> None:
    _commit(repo, "a.py")
    _run(repo, CONCLUSION="failure", EXECUTION_FILE=_execution_file(repo, "error_during_execution", 12, 0, errors=["429"]))
    (create,) = [c for c in _calls(repo) if c.startswith("pr create ")]
    assert "claude-resume" in create and "not retried automatically" not in create


def test_a_budget_failure_says_it_is_not_retried_automatically(repo: dict) -> None:
    _commit(repo, "a.py")
    _run(repo, CONCLUSION="failure", EXECUTION_FILE=_execution_file(repo, "error_max_turns", 201, 0))
    (create,) = [c for c in _calls(repo) if c.startswith("pr create ")]
    assert "not retried automatically" in create


def test_success_with_a_safety_net_draft_marks_it_ready_and_says_so(repo: dict) -> None:
    """A resumed run that finishes has done what the draft was waiting for. Marking it
    ready is what hands it to claude-review; the finished marker is what stops
    claude-resume from dispatching it again."""
    _commit(repo, "a.py")
    result = _run(repo, CONCLUSION="success", EXECUTION_FILE=_execution_file(repo, "success", 40, 0), FAKE_GH_PR_LIST=SAFETY_NET_DRAFT)
    assert result.returncode == 0, result.stderr
    calls = _calls(repo)
    assert "pr ready 12" in calls
    (comment,) = [c for c in calls if c.startswith("pr comment 12 ")]
    assert "<!-- claude-implement-finished -->" in comment
    assert not any(c.startswith("pr create") for c in calls)


def test_the_finished_path_drops_the_wip_title_prefix(repo: dict) -> None:
    """The draft was titled `WIP:` because the run that opened it had not finished. This
    one has, so the prefix is now false, and a ready pull request that calls itself work in
    progress tells the reviewer the opposite of what its state says."""
    _commit(repo, "a.py")
    _run(repo, CONCLUSION="success", EXECUTION_FILE=_execution_file(repo, "success", 40, 0), FAKE_GH_PR_LIST=SAFETY_NET_DRAFT)
    (edit,) = [c for c in _calls(repo) if c.startswith("pr edit 12 ")]
    assert edit == "pr edit 12 --title Bind the API server to loopback by default"


def test_a_title_without_the_prefix_is_left_as_it_is(repo: dict) -> None:
    """Only that exact prefix is dropped. A title a person edited is theirs."""
    _commit(repo, "a.py")
    theirs = json.loads(SAFETY_NET_DRAFT)
    theirs[0]["title"] = "Loopback binding (I renamed this)"
    _run(repo, CONCLUSION="success", EXECUTION_FILE=_execution_file(repo, "success", 40, 0),
         FAKE_GH_PR_LIST=json.dumps(theirs))
    calls = _calls(repo)
    assert "pr ready 12" in calls
    assert not any(c.startswith("pr edit") for c in calls), calls


# --- a cancelled run is a decision, not a fault ------------------------------------------


def test_a_cancelled_run_is_marked_cancelled_in_the_protocol(repo: dict) -> None:
    """This script runs under `if: always()`, so cancelling a run in the Actions tab still
    gets here — with no result message, which would read as `none` and be re-dispatched
    within two hours. `docs/PIPELINE.md` § How to stop it promises the opposite, and this
    subtype is the only thing keeping that promise."""
    _commit(repo, "a.py")
    _run(repo, CONCLUSION="cancelled", EXECUTION_FILE="")
    (create,) = [c for c in _calls(repo) if c.startswith("pr create ")]
    assert "<!-- claude-implement-safety-net subtype=cancelled -->" in create


def test_a_cancelled_run_says_it_will_not_be_resumed(repo: dict) -> None:
    _commit(repo, "a.py")
    _run(repo, CONCLUSION="cancelled", EXECUTION_FILE="")
    (create,) = [c for c in _calls(repo) if c.startswith("pr create ")]
    assert "cancelled" in create and "nothing resumes it" in create
    assert "claude-resume` workflow re-dispatches" not in create


def test_an_unanticipated_subtype_is_not_promised_a_retry(repo: dict) -> None:
    """The retry note reads from the same positive list `claude_resume.py` decides on, so a
    subtype nobody anticipated cannot be promised a retry it will not get."""
    _commit(repo, "a.py")
    _run(repo, CONCLUSION="failure", EXECUTION_FILE=_execution_file(repo, "error_deadline_exceeded", 12, 0))
    (create,) = [c for c in _calls(repo) if c.startswith("pr create ")]
    assert "not retried automatically" in create and "error_deadline_exceeded" in create


# --- the draft the model opens before it implements anything ----------------------------


def test_success_promotes_the_draft_the_model_opened_first(repo: dict) -> None:
    """The draft-first flow's other half, and the one this script owns.

    `claude-implement.yml` tells the model to open a draft as its first action on the
    branch, because this job's token is refused `createPullRequest` by organisation
    policy and the App's token is revoked before this script runs — run 34616884881
    pushed five commits for #72, reported success and opened nothing. Promoting that
    draft is a call this token *can* make, so the promote-on-success path below is now
    the normal route rather than the exception it was written as.
    """
    _commit(repo, "a.py")
    result = _run(repo, CONCLUSION="success", EXECUTION_FILE=_execution_file(repo, "success", 40, 0),
                  FAKE_GH_PR_LIST=DRAFT_FIRST_DRAFT)
    assert result.returncode == 0, result.stderr
    calls = _calls(repo)
    assert "pr ready 12" in calls, calls
    assert "pr edit 12 --title Bind the API server to loopback by default" in calls, calls
    (comment,) = [c for c in calls if c.startswith("pr comment 12 ")]
    assert "<!-- claude-implement-finished -->" in comment
    assert not any(c.startswith("pr create") for c in calls), "a second pull request was opened"


def test_a_failed_run_records_its_subtype_on_the_draft_the_model_opened(repo: dict) -> None:
    """That comment is the *only* safety-net record such a draft ever gets: the body the
    model wrote carries no `subtype=`. `claude_resume.py` reads it to decide whether
    another run would help, so without it the usage-limit retry stops working for every
    run that opened its own draft — which is now every run."""
    _commit(repo, "a.py")
    _run(repo, CONCLUSION="failure", EXECUTION_FILE=_execution_file(repo, "error_during_execution", 12, 0, errors=["429"]),
         FAKE_GH_PR_LIST=DRAFT_FIRST_DRAFT)
    (comment,) = [c for c in _calls(repo) if c.startswith("pr comment 12 ")]
    assert "<!-- claude-implement-safety-net subtype=error_during_execution -->" in comment
    assert "@claude please continue" in comment


def test_success_with_a_draft_the_model_opened_is_left_alone(repo: dict) -> None:
    """A draft without either marker is the model's own way of saying "not finished", or
    a person's work in progress. Neither is the workflow's to promote."""
    _commit(repo, "a.py")
    result = _run(repo, CONCLUSION="success", EXECUTION_FILE=_execution_file(repo, "success", 40, 0), FAKE_GH_PR_LIST=HUMAN_DRAFT)
    assert result.returncode == 0, result.stderr
    calls = _calls(repo)
    assert not any(c.startswith("pr ready") or c.startswith("pr comment") or c.startswith("pr create") for c in calls), calls


# --- the token the App revokes before this script runs (issue #65) -------------------


def test_a_revoked_app_token_still_opens_the_draft(repo: dict) -> None:
    """The whole safety net authenticated with a token the action had already revoked.
    Issue #65's run pushed its branch — git uses actions/checkout's persisted credential,
    not this token — and then lost the draft pull request and the issue comment to
    `HTTP 401`, with a green tail and nothing for `claude-resume` to find. The work sat
    on a branch nobody knew existed."""
    _commit(repo, "card_divider.py")
    result = _run(repo, CONCLUSION="failure", EXECUTION_FILE=_execution_file(repo),
                  GH_TOKEN="revoked", GH_TOKEN_FALLBACK="workflow")
    assert result.returncode == 0, result.stderr
    assert "the App's token was refused; reporting as the workflow instead" in result.stderr
    assert any(c.startswith("pr create ") for c in _reports(repo)), (
        f"no draft was opened: {_reports(repo)}"
    )
    assert _remote_has_branch(repo)


def test_a_live_app_token_is_left_alone(repo: dict) -> None:
    """The App's token is preferred while it works: a draft it opens is the app's, which
    is what lets claude-review's fix loop ask for changes on it."""
    _commit(repo, "card_divider.py")
    result = _run(repo, CONCLUSION="failure", EXECUTION_FILE=_execution_file(repo),
                  GH_TOKEN_FALLBACK="workflow")
    assert result.returncode == 0, result.stderr
    assert "refused" not in result.stderr, result.stderr
    assert any(c.startswith("pr create ") for c in _reports(repo))


def test_a_refused_token_with_no_fallback_says_so_and_still_exits_zero(repo: dict) -> None:
    """Locally, and on any run where the workflow token is the one being refused, there
    is nothing to swap to. That is worth one line on stderr and must not turn the tail
    red on top of the model's own failure."""
    _commit(repo, "card_divider.py")
    result = _run(repo, CONCLUSION="failure", EXECUTION_FILE=_execution_file(repo),
                  GH_TOKEN="revoked")
    assert result.returncode == 0, result.stderr
    assert "no other one" in result.stderr, result.stderr


def test_an_identical_fallback_is_not_treated_as_a_second_chance(repo: dict) -> None:
    """When the action produced no token the workflow expression already collapses both
    to `github.token`. Swapping one refused token for the same string and announcing a
    fallback would be a lie in the log."""
    _commit(repo, "card_divider.py")
    result = _run(repo, CONCLUSION="failure", EXECUTION_FILE=_execution_file(repo),
                  GH_TOKEN="revoked", GH_TOKEN_FALLBACK="revoked")
    assert result.returncode == 0, result.stderr
    assert "no other one" in result.stderr, result.stderr
    assert "reporting as the workflow instead" not in result.stderr


def test_the_probe_runs_before_anything_is_written(repo: dict) -> None:
    """`implement_mode` asks `gh pr list` first, and on a refused token that returns
    "[]" — which sends the script down the open-a-draft path with no way to open one.
    The probe has to come before it, not after."""
    _commit(repo, "card_divider.py")
    _run(repo, CONCLUSION="failure", EXECUTION_FILE=_execution_file(repo),
         GH_TOKEN="revoked", GH_TOKEN_FALLBACK="workflow")
    calls = _calls(repo)
    assert calls[0].startswith("api rate_limit"), f"the first call was {calls[0]!r}"
    first_write = next(i for i, c in enumerate(calls) if c.startswith(("pr create ", "issue comment ", "pr comment ")))
    assert calls.index(next(c for c in calls if c.startswith("pr list "))) < first_write
    assert calls[:2] == [c for c in calls[:2] if c.startswith("api rate_limit")], (
        f"the probe should run once per token, before the first query: {calls[:4]}"
    )


def test_a_draft_that_could_not_be_opened_is_not_reported_as_one(repo: dict) -> None:
    """`GITHUB_TOKEN` may not open a pull request unless the repository allows Actions to,
    and that setting is off here — so the fallback token can push and comment and still
    fail at `gh pr create`. The old wording then told the issue the work was "on the
    branch as a draft pull request", which is false in the one place a person is relying
    on it, and it hid the part that matters: with no draft, `claude-resume` has nothing to
    pick up."""
    _commit(repo, "card_divider.py")
    result = _run(repo, CONCLUSION="failure", EXECUTION_FILE=_execution_file(repo),
                  GITHUB_REPOSITORY="Daedal-Studio/ds-mvp", FAKE_GH_PR_CREATE_FAILS="1")
    assert result.returncode == 0, result.stderr
    comment = next(c for c in _reports(repo) if c.startswith("issue comment "))
    assert "no pull request could be opened" in comment, comment
    assert "as a draft pull request" not in comment, comment
    assert "claude-resume` has nothing to pick up" in comment, comment
    assert "git push origin --delete claude/issue-7" in comment, comment
    assert "issue_number=7" in comment, comment
    assert "pull/new/claude/issue-7" in comment, comment


def test_commits_with_no_pull_request_are_the_first_sentence_of_the_report(repo: dict) -> None:
    """This outcome stays reachable — a run can end before the model opens its draft, and
    the token here cannot open one — so the issue comment has to lead with it.

    Run 34616884881 for #72 ended `CONCLUSION=success` with five commits pushed and no
    pull request, and said `could not open a pull request for claude/issue-72` in the run
    log. PR #122 was opened by hand to rescue those commits. Whatever else the comment
    goes on to say, its first sentence is what a person skims.
    """
    _commit(repo, "card_divider.py")
    _run(repo, CONCLUSION="failure", EXECUTION_FILE=_execution_file(repo),
         GITHUB_REPOSITORY="Daedal-Studio/ds-mvp", FAKE_GH_PR_CREATE_FAILS="1")
    comment = next(c for c in _reports(repo) if c.startswith("issue comment "))
    body = comment.split("--body ", 1)[1]
    first = body.split(".", 1)[0]
    assert "claude/issue-7" in first, first
    assert "commits" in first and "no pull request could be opened" in first, first


def test_a_refused_pr_create_names_the_cause_and_both_remedies(repo: dict) -> None:
    """`could not open a pull request for <branch>` named neither, and it was the whole
    report. The refusal is organisation policy on `createPullRequest`, not a bug in this
    script and not a missing permission it can ask for — so both ways out belong in the
    comment: the draft-first flow, which is how the pipeline avoids needing the call at
    all, and the organisation setting, which is a decision somebody has to take
    deliberately because it also grants every workflow the right to *approve*."""
    _commit(repo, "card_divider.py")
    result = _run(repo, CONCLUSION="failure", EXECUTION_FILE=_execution_file(repo),
                  GITHUB_REPOSITORY="Daedal-Studio/ds-mvp", FAKE_GH_PR_CREATE_FAILS="1")
    comment = next(c for c in _reports(repo) if c.startswith("issue comment "))
    assert "organization does not allow GitHub Actions to create or approve pull requests" in comment, comment
    assert "first action on the branch" in comment, comment
    assert "Allow GitHub Actions to create and approve pull requests" in comment, comment
    assert "create was refused" in result.stderr, result.stderr
    assert "organisation policy" in result.stderr, result.stderr
