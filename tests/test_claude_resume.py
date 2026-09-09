"""`infra/ci/claude_resume.py` decides which unfinished implementations to re-dispatch.

The subscription that runs the pipeline has a usage wall. When a run hits it, the model
step fails mid-task; the safety net (`claude_implement_report.sh`) pushes what exists and
opens a draft pull request carrying `<!-- claude-implement-safety-net subtype=… -->`. This
script runs on a schedule and re-dispatches `claude-implement` for exactly those drafts —
and for nothing else. Every rule below exists to stop it spending a run where a run would
not help or where a person is already at work:

- not a draft, or a draft without the marker         -> not the safety net's; leave it
- a `<!-- claude-implement-finished -->` comment      -> a run already finished; a person decides
- latest safety-net subtype is not retryable         -> only a transient failure is worth another run
- a human commented since the pipeline last acted    -> a person took over
- attempts at the cap                                 -> stop, say so once
- last attempt too recent                             -> that run may still be going

`decide()` is pure and tested directly; `main()` talks to `gh` and is tested once through
a fake, the way the report script is.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "infra" / "ci" / "claude_resume.py"

spec = importlib.util.spec_from_file_location("claude_resume", SCRIPT)
resume = importlib.util.module_from_spec(spec)
# `dataclass` under `from __future__ import annotations` resolves the class's module through
# sys.modules; a module loaded by path is not there unless registered.
sys.modules["claude_resume"] = resume
spec.loader.exec_module(resume)

NOW = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
MARK = "<!-- claude-implement-safety-net subtype={} -->"


def _pr(number=12, draft=True, subtype="error_during_execution", branch="claude/issue-7", created=NOW - timedelta(hours=5)):
    body = f"Closes #7\n\n{MARK.format(subtype)}\n**Opened by the claude-implement workflow**" if subtype else "Closes #7\n\nmy own draft"
    return {"number": number, "isDraft": draft, "body": body, "headRefName": branch, "createdAt": created.isoformat()}


def _comment(author, body, when):
    return {"author": {"login": author}, "body": body, "createdAt": when.isoformat()}


def _resume_comment(k, when):
    return _comment("github-actions", f"<!-- claude-implement-resume --> Resume attempt {k} of 3 dispatched.", when)


# --- what is not ours to touch ------------------------------------------------------------


def test_a_ready_pull_request_is_never_redispatched() -> None:
    d = resume.decide(_pr(draft=False), [], NOW)
    assert d.action == "skip" and "draft" in d.reason


def test_a_draft_without_the_marker_is_left_alone() -> None:
    d = resume.decide(_pr(subtype=None), [], NOW)
    assert d.action == "skip" and "safety net" in d.reason


def test_a_finished_run_stops_the_loop() -> None:
    comments = [_comment("claude", "<!-- claude-implement-finished --> The run finished.", NOW - timedelta(hours=1))]
    d = resume.decide(_pr(), comments, NOW)
    assert d.action == "skip" and "finished" in d.reason


def test_a_budget_failure_is_not_retried() -> None:
    d = resume.decide(_pr(subtype="error_max_turns"), [], NOW)
    assert d.action == "skip" and "error_max_turns" in d.reason


def test_a_run_that_finished_without_opening_a_pull_request_is_not_retried() -> None:
    """The safety net stamps `subtype=success` on the draft it opens when a run finished
    but never opened a pull request. The work is done; the draft is waiting on a person to
    read it against the acceptance criteria, not on another Opus run to redo it."""
    d = resume.decide(_pr(subtype="success"), [], NOW)
    assert d.action == "skip" and "success" in d.reason


def test_a_cancelled_run_is_not_resumed() -> None:
    """`docs/PIPELINE.md` § How to stop it promises that cancelling a run in the Actions
    tab stops it. The safety net still runs (`if: always()`) and still opens the draft, so
    the only thing keeping that promise is this skip."""
    d = resume.decide(_pr(subtype="cancelled"), [], NOW)
    assert d.action == "skip" and "cancelled" in d.reason


def test_only_the_listed_subtypes_are_retried() -> None:
    """A positive list, so a subtype nobody anticipated is left alone rather than repeated.
    `cancelled` is the precedent: it was added to the protocol after the rule was written."""
    assert resume.RETRYABLE_SUBTYPES == {"error_during_execution", "none"}
    for unanticipated in ("error_deadline_exceeded", "refusal"):
        d = resume.decide(_pr(subtype=unanticipated), [], NOW)
        assert d.action == "skip" and unanticipated in d.reason


def test_the_two_scripts_agree_on_which_subtypes_are_retried() -> None:
    """`claude_implement_report.sh` tells the reader on the draft whether this will be
    retried; `claude_resume.py` decides whether it is. A copy of the list in each is a copy
    that disagrees the first time either is edited, and the disagreement is a sentence on a
    pull request that is the opposite of the truth."""
    shell = (REPO_ROOT / "infra" / "ci" / "claude_implement_report.sh").read_text()
    declared = re.search(r'^RETRYABLE_SUBTYPES="([^"]*)"', shell, re.MULTILINE)
    assert declared, "claude_implement_report.sh no longer declares RETRYABLE_SUBTYPES"
    assert set(declared.group(1).split()) == set(resume.RETRYABLE_SUBTYPES)


def test_the_latest_safety_net_record_decides_the_subtype() -> None:
    """The body says the first run hit the budget; a later resumed run then hit a limit.
    The latest record is the one to act on."""
    comments = [_comment("claude", MARK.format("error_during_execution") + " ended again", NOW - timedelta(hours=3))]
    d = resume.decide(_pr(subtype="error_max_turns"), comments, NOW)
    assert d.action == "dispatch"


def test_a_human_comment_after_the_last_record_means_a_person_took_over() -> None:
    comments = [_comment("TFelbor", "I'll finish this one by hand.", NOW - timedelta(hours=1))]
    d = resume.decide(_pr(), comments, NOW)
    assert d.action == "skip" and "person" in d.reason


def test_bot_comments_do_not_count_as_a_person() -> None:
    comments = [
        _comment("claude", "## claude-review …", NOW - timedelta(hours=2)),
        _comment("github-actions", "<!-- claude-fix-request --> @claude please address the review.", NOW - timedelta(hours=2)),
        _comment("claude[bot]", "noted", NOW - timedelta(hours=1)),
        _comment("app/claude", "the App as gh spells a pull request author", NOW - timedelta(minutes=30)),
    ]
    d = resume.decide(_pr(), comments, NOW)
    assert d.action == "dispatch"


def test_a_human_comment_before_the_last_record_does_not_block() -> None:
    comments = [
        _comment("TFelbor", "go ahead", NOW - timedelta(hours=6)),
    ]
    d = resume.decide(_pr(), comments, NOW)  # PR (the record) created 5 h ago, after the human spoke
    assert d.action == "dispatch"


def test_a_person_who_comments_while_an_attempt_is_running_is_not_talked_over() -> None:
    """The gap this closes: a comment made *during* an attempt is older than the
    safety-net record that attempt writes when it fails, so measuring "has a person spoken
    since?" from the record would read it as already answered and dispatch over the top of
    it. The line is the last thing the pipeline did on its own — here, the dispatch."""
    comments = [
        _resume_comment(1, NOW - timedelta(hours=4)),
        _comment("TFelbor", "hold off, I'm taking this one", NOW - timedelta(hours=3, minutes=30)),
        _comment("claude", MARK.format("error_during_execution") + " ended again", NOW - timedelta(hours=3)),
    ]
    d = resume.decide(_pr(), comments, NOW)
    assert d.action == "skip" and "TFelbor" in d.reason


def test_a_resumed_attempt_that_nobody_commented_on_is_followed_by_the_next() -> None:
    """The other side of the rule above: measuring from the dispatch must not make an
    ordinary failed attempt look like one a person intervened in."""
    comments = [
        _resume_comment(1, NOW - timedelta(hours=4)),
        _comment("claude", MARK.format("error_during_execution") + " ended again", NOW - timedelta(hours=3)),
    ]
    d = resume.decide(_pr(), comments, NOW)
    assert d.action == "dispatch" and d.attempt == 2


# --- the cap and the gap ---------------------------------------------------------------------


def test_the_first_dispatch_is_attempt_one_for_the_issue_in_the_branch_name() -> None:
    d = resume.decide(_pr(), [], NOW)
    assert d.action == "dispatch" and d.attempt == 1 and d.issue == 7


def test_attempts_at_the_cap_stop() -> None:
    comments = [_resume_comment(k, NOW - timedelta(hours=10 - 2 * k)) for k in (1, 2, 3)]
    d = resume.decide(_pr(), comments, NOW, max_attempts=3)
    assert d.action == "skip" and "3" in d.reason


def test_a_recent_attempt_is_given_time_to_finish() -> None:
    comments = [_resume_comment(1, NOW - timedelta(minutes=40))]
    d = resume.decide(_pr(), comments, NOW, min_gap=timedelta(hours=2))
    assert d.action == "skip" and "40 minutes" in d.reason


def test_an_old_attempt_is_followed_by_the_next_one() -> None:
    comments = [_resume_comment(1, NOW - timedelta(hours=3))]
    d = resume.decide(_pr(), comments, NOW, min_gap=timedelta(hours=2))
    assert d.action == "dispatch" and d.attempt == 2


def test_a_branch_that_is_not_an_issue_branch_is_skipped() -> None:
    d = resume.decide(_pr(branch="feature/something"), [], NOW)
    assert d.action == "skip" and "branch" in d.reason


# --- main(), once, through a fake gh -----------------------------------------------------------

FAKE_GH = r"""#!/usr/bin/env bash
printf '%s\n' "$(printf '%s' "$*" | tr '\n' ' ')" >> "$FAKE_GH_LOG"
case "$1 $2" in
  "pr list")     printf '%s' "$FAKE_GH_PR_LIST" ;;
  "pr view")     printf '%s' "$FAKE_GH_PR_VIEW" ;;
  "workflow run"|"pr comment") : ;;
  *) echo "fake gh: unexpected: $*" >&2; exit 64 ;;
esac
"""


def test_main_dispatches_the_implementer_and_leaves_a_resume_comment(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(FAKE_GH)
    gh.chmod(0o755)
    log = tmp_path / "gh.log"
    log.touch()
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "FAKE_GH_LOG": str(log),
        "FAKE_GH_PR_LIST": json.dumps([_pr(), _pr(number=13, subtype=None)]),
        "FAKE_GH_PR_VIEW": json.dumps({"comments": []}),
        "GH_TOKEN": "fake",
        "GH_REPO": "Daedal-Studio/ds-mvp",
        "RUN_URL": "https://github.com/Daedal-Studio/ds-mvp/actions/runs/5",
    }
    result = subprocess.run(["python3", str(SCRIPT)], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    calls = [c for c in log.read_text().splitlines() if c]
    assert any(c.startswith("workflow run claude-implement.yml") and "issue_number=7" in c for c in calls), calls
    (comment,) = [c for c in calls if c.startswith("pr comment 12 ")]
    assert "<!-- claude-implement-resume -->" in comment and "attempt 1 of 3" in comment
    assert not any("pr comment 13" in c for c in calls), "the model's own draft was touched"
    assert "dispatched #7" in result.stdout or "dispatch" in result.stdout


def test_a_run_that_cannot_list_the_drafts_goes_red(tmp_path: Path) -> None:
    """A scheduled run that cannot see the drafts it exists to pick up has done nothing.
    Green there means the first sign of trouble is somebody wondering why a draft has sat
    for a day."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text("#!/usr/bin/env bash\necho 'gh: HTTP 503' >&2\nexit 1\n")
    gh.chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
           "GH_TOKEN": "fake", "GH_REPO": "Daedal-Studio/ds-mvp"}
    result = subprocess.run(["python3", str(SCRIPT)], env=env, capture_output=True, text=True)
    assert result.returncode == 1
    assert "could not list pull requests" in result.stderr
