#!/usr/bin/env python3
"""Re-dispatch claude-implement for drafts the safety net left behind.

The subscription behind `CLAUDE_CODE_OAUTH_TOKEN` has a usage wall. When a run hits it,
the model step fails mid-task; `claude_implement_report.sh` then pushes what exists and
opens a draft pull request carrying `<!-- claude-implement-safety-net subtype=… -->`.
This script runs from `.github/workflows/claude-resume.yml` every two hours and
re-dispatches `claude-implement` (`workflow_dispatch`, the event a workflow token is
allowed to trigger) for exactly those drafts, and for nothing else. The implementer's
guard recognises the draft, resumes the branch and tells the model it is resuming.

Every rule in `decide()` exists to stop the loop spending a run where a run would not
help, or where a person is already at work:

- not a draft, or a draft without a marker           -> not the pipeline's; leave it
- a draft-first draft with no outcome recorded yet   -> that run is still going, or said nothing
- a `<!-- claude-implement-finished -->` comment      -> a run already finished; a person decides
- latest safety-net subtype is not retryable         -> only a transient failure is worth another run
- a human commented since the pipeline last acted    -> a person took over
- attempts at the cap                                 -> stop
- last attempt too recent                             -> that run may still be going

Stdlib only: the workflow installs nothing. Tested by tests/test_claude_resume.py.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

SAFETY_NET_MARKER = "<!-- claude-implement-safety-net"
SUBTYPE_RE = re.compile(r"<!-- claude-implement-safety-net subtype=([A-Za-z0-9_-]+) -->")
FINISHED_MARKER = "<!-- claude-implement-finished -->"
#: The draft the *model* opens as its first action on the branch, before it implements
#: anything (`claude-implement.yml`'s prompt). It is the normal route now — the workflow's
#: own token may not create pull requests here — so most unfinished work arrives carrying
#: this marker rather than the safety net's, and the safety net adds its `subtype=` record
#: as a *comment* on it when the run ends. Such a draft is a candidate; whether it is
#: dispatched is still decided by that record, so a draft whose run has not reported
#: anything yet is left alone.
DRAFT_FIRST_MARKER = "<!-- claude-implement-draft-first"
RESUME_MARKER = "<!-- claude-implement-resume -->"
BRANCH_RE = re.compile(r"^claude/issue-(\d+)$")

#: Logins that are the pipeline talking to itself. GraphQL (which `gh --json` reads)
#: reports a GitHub App without the `[bot]` suffix; REST spells it with. Both accepted.
BOT_LOGINS = {"claude", "claude-code", "github-actions"}

DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_MIN_GAP = timedelta(hours=2)

#: The result subtypes another run would help with, and the only ones. A positive list, not
#: a deny list: a subtype nobody anticipated is left alone rather than retried by default,
#: and every subtype the safety net can stamp today is one it would have been wrong to
#: retry — `success` (the work is done, the draft is waiting on a person), `error_max_turns`
#: (a budget, and another 200 turns on the same scope repeats it), `cancelled` (someone
#: stopped it on purpose). `RETRYABLE_SUBTYPES` in `infra/ci/claude_implement_report.sh`
#: holds the same set for its own retry note; a test binds the two so they cannot drift.
RETRYABLE_SUBTYPES = frozenset({"error_during_execution", "none"})

#: Why a non-retryable subtype is not retried, in the words the log and the reason use.
#: A subtype missing from here still skips; it just says less.
WHY_NOT_RETRYABLE = {
    "error_max_turns": "a budget, not a limit; retrying repeats it",
    "success": "the run finished; the draft is waiting on a person, not on another run",
    "cancelled": "a person stopped that run; re-dispatching it would undo that",
}


@dataclass(frozen=True)
class Decision:
    action: str  # "dispatch" | "skip"
    reason: str
    attempt: int = 0
    issue: Optional[int] = None


def _when(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _is_bot(login: str) -> bool:
    # `gh` spells one App three ways: `app/claude` (a pull request's author), `claude`
    # (comments, reviews), `claude[bot]` (REST). Neither `/` nor `[` is legal in a human
    # login, so stripping both admits no person.
    return login.lower().removeprefix("app/").removesuffix("[bot]") in BOT_LOGINS


def decide(
    pr: dict[str, Any],
    comments: list[dict[str, Any]],
    now: datetime,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    min_gap: timedelta = DEFAULT_MIN_GAP,
) -> Decision:
    if not pr.get("isDraft"):
        return Decision("skip", "not a draft")
    body = pr.get("body") or ""
    body_subtype = SUBTYPE_RE.search(body)
    if not body_subtype and DRAFT_FIRST_MARKER not in body:
        return Decision("skip", "not one of the pipeline's drafts (no marker)")
    branch = BRANCH_RE.match(pr.get("headRefName") or "")
    if not branch:
        return Decision("skip", f"branch {pr.get('headRefName')!r} is not claude/issue-<n>")
    issue = int(branch.group(1))

    ordered = sorted(comments, key=lambda c: _when(c["createdAt"]))
    if any(FINISHED_MARKER in (c.get("body") or "") for c in ordered):
        return Decision("skip", "a resumed run already finished; a person decides what happens next", issue=issue)

    records: list[tuple[datetime, str]] = []
    if body_subtype:
        records.append((_when(pr["createdAt"]), body_subtype.group(1)))
    for c in ordered:
        m = SUBTYPE_RE.search(c.get("body") or "")
        if m:
            records.append((_when(c["createdAt"]), m.group(1)))
    # A draft-first draft carries no subtype in its body: the model opened it before it
    # had an outcome to report. Until the safety net records one as a comment, the run is
    # either still going or ended in a way nothing has described — dispatching over the
    # top of it would be a second Opus run on the same branch, decided on no evidence.
    if not records:
        return Decision("skip", "the run that opened this draft has not reported an outcome yet", issue=issue)
    latest_time, latest_subtype = max(records, key=lambda r: r[0])
    if latest_subtype not in RETRYABLE_SUBTYPES:
        why = WHY_NOT_RETRYABLE.get(latest_subtype, "only a transient failure is retried")
        return Decision("skip", f"the latest run ended with {latest_subtype} — {why}", issue=issue)

    resumes = [c for c in ordered if RESUME_MARKER in (c.get("body") or "")]

    # A person who speaks up has taken over. "Since the last safety-net record" is the
    # wrong line once the loop is running, though: a comment posted *while* an attempt is
    # in flight is older than the record that attempt writes when it fails, so it would be
    # read as already answered and the next tick would dispatch over the top of it. The
    # line is the last thing the pipeline did of its own accord — the resume dispatch when
    # there has been one, the safety-net record otherwise.
    spoke_last = _when(resumes[-1]["createdAt"]) if resumes else latest_time
    humans_after = [c for c in ordered if not _is_bot(c["author"]["login"]) and _when(c["createdAt"]) > spoke_last]
    if humans_after:
        return Decision("skip", f"a person ({humans_after[-1]['author']['login']}) commented after the last run; leaving it to them", issue=issue)

    if len(resumes) >= max_attempts:
        return Decision("skip", f"{len(resumes)} resume attempts made; the cap is {max_attempts}", issue=issue)
    if resumes:
        since = now - _when(resumes[-1]["createdAt"])
        if since < min_gap:
            return Decision("skip", f"the last attempt was {int(since.total_seconds() // 60)} minutes ago; that run may still be going", issue=issue)

    return Decision("dispatch", f"attempt {len(resumes) + 1} of {max_attempts}", attempt=len(resumes) + 1, issue=issue)


def _gh(*args: str) -> str:
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout


def main() -> int:
    max_attempts = int(os.environ.get("MAX_ATTEMPTS", DEFAULT_MAX_ATTEMPTS))
    min_gap = timedelta(minutes=int(os.environ.get("MIN_GAP_MINUTES", int(DEFAULT_MIN_GAP.total_seconds() // 60))))
    run_url = os.environ.get("RUN_URL", "")
    now = datetime.now(timezone.utc)

    try:
        prs = json.loads(_gh("pr", "list", "--state", "open", "--limit", "100",
                             "--json", "number,isDraft,body,headRefName,createdAt"))
    except (subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        # Red, not green. A scheduled run that cannot see the drafts it exists to pick up
        # has done nothing, and a green tick on it means the first sign of trouble is
        # somebody wondering why a draft has sat for a day. The per-pull-request failure
        # below is swallowed on purpose: the next tick retries that one.
        print(f"claude-resume: could not list pull requests: {exc}", file=sys.stderr)
        return 1

    candidates = [
        p
        for p in prs
        if p.get("isDraft")
        and (SAFETY_NET_MARKER in (p.get("body") or "") or DRAFT_FIRST_MARKER in (p.get("body") or ""))
    ]
    print(f"claude-resume: {len(prs)} open pull request(s), {len(candidates)} unfinished pipeline draft(s)")
    for pr in candidates:
        number = pr["number"]
        try:
            comments = json.loads(_gh("pr", "view", str(number), "--json", "comments")).get("comments", [])
            d = decide(pr, comments, now, max_attempts=max_attempts, min_gap=min_gap)
            print(f"#{number}: {d.action} — {d.reason}")
            if d.action != "dispatch":
                continue
            _gh("workflow", "run", "claude-implement.yml", "-f", f"issue_number={d.issue}")
            _gh("pr", "comment", str(number), "--body",
                f"{RESUME_MARKER}\n**Resume attempt {d.attempt} of {max_attempts} dispatched** for #{d.issue}: "
                f"`claude-implement` will resume this branch and mark the pull request ready when it finishes. "
                f"Comment here to take over and stop the automatic attempts. Dispatched by {run_url}")
            print(f"dispatched #{d.issue} (attempt {d.attempt} of {max_attempts}) for pull request #{number}")
        except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError) as exc:
            print(f"#{number}: could not act: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
