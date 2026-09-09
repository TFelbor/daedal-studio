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

- not a draft, or a draft without the marker         -> not the safety net's; leave it
- a `<!-- claude-implement-finished -->` comment      -> a run already finished; a person decides
- latest safety-net record says `error_max_turns`    -> a budget, not a limit; retrying repeats it
- a human commented after the last safety-net record -> a person took over
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
RESUME_MARKER = "<!-- claude-implement-resume -->"
BRANCH_RE = re.compile(r"^claude/issue-(\d+)$")

#: Logins that are the pipeline talking to itself. GraphQL (which `gh --json` reads)
#: reports a GitHub App without the `[bot]` suffix; REST spells it with. Both accepted.
BOT_LOGINS = {"claude", "claude-code", "github-actions"}

DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_MIN_GAP = timedelta(hours=2)


@dataclass(frozen=True)
class Decision:
    action: str  # "dispatch" | "skip"
    reason: str
    attempt: int = 0
    issue: Optional[int] = None


def _when(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _is_bot(login: str) -> bool:
    return login.lower().removesuffix("[bot]") in BOT_LOGINS


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
    if not body_subtype:
        return Decision("skip", "not the safety net's draft (no marker)")
    branch = BRANCH_RE.match(pr.get("headRefName") or "")
    if not branch:
        return Decision("skip", f"branch {pr.get('headRefName')!r} is not claude/issue-<n>")
    issue = int(branch.group(1))

    ordered = sorted(comments, key=lambda c: _when(c["createdAt"]))
    if any(FINISHED_MARKER in (c.get("body") or "") for c in ordered):
        return Decision("skip", "a resumed run already finished; a person decides what happens next", issue=issue)

    records: list[tuple[datetime, str]] = [(_when(pr["createdAt"]), body_subtype.group(1))]
    for c in ordered:
        m = SUBTYPE_RE.search(c.get("body") or "")
        if m:
            records.append((_when(c["createdAt"]), m.group(1)))
    latest_time, latest_subtype = max(records, key=lambda r: r[0])
    if latest_subtype == "error_max_turns":
        return Decision("skip", "the latest run ended with error_max_turns — a budget, not a limit; retrying repeats it", issue=issue)

    humans_after = [c for c in ordered if not _is_bot(c["author"]["login"]) and _when(c["createdAt"]) > latest_time]
    if humans_after:
        return Decision("skip", f"a person ({humans_after[-1]['author']['login']}) commented after the last run; leaving it to them", issue=issue)

    resumes = [c for c in ordered if RESUME_MARKER in (c.get("body") or "")]
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
        print(f"claude-resume: could not list pull requests: {exc}", file=sys.stderr)
        return 0

    candidates = [p for p in prs if p.get("isDraft") and SAFETY_NET_MARKER in (p.get("body") or "")]
    print(f"claude-resume: {len(prs)} open pull request(s), {len(candidates)} safety-net draft(s)")
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
