"""The CI pipeline's trust boundary, and the one escalation that can cross it.

Every `claude-*` job turns text somebody wrote into commits. Four surfaces feed a
model here — a comment body (interactive mode: the comment *is* the prompt), an
issue body, a diff, and the hop where `claude-review`'s `@claude` comment becomes
the *implementer's* prompt — and until issue #120 nothing in `docs/PIPELINE.md`,
`CLAUDE.md`, `docs/SYSTEM-AS-BUILT.md` or the workflows said that anything read
through `gh`, a diff, a log or the checkout is data rather than an instruction.

Two of those three guards are prose, which drifts. The third is not:

* **`.claude/settings.local.json` must never be tracked.** The action leaves
  `settingSources` at `["user", "project", "local"]`
  (`base-action/src/parse-sdk-options.ts`), so it loads that file **from the pull
  request's own checkout**, and the file carries `permissions.allow` and
  `enabledMcpjsonServers`. A committed one widens the tool allowance of the job
  reviewing it — data becoming configuration without passing through a person.
  `.gitignore` prevents an accidental `git add` and nothing more: it does not make
  the file's presence in a branch an error, and `grep -rn 'settings.local' tests/`
  was empty before this file existed.
* **The boundary section exists, and `CLAUDE.md` points at it.** The contract is
  loaded into every turn of every run, so it carries one line; the reasoning lives
  on one page in `docs/PIPELINE.md`. A pointer to a section that has been renamed
  away sends whoever follows it nowhere, and nothing else resolves it — the same
  binding `tests/test_vendored_skills.py` makes between the tree, `.gitignore` and
  the notices table.

Everything here is static: no model is called and nothing is written.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PIPELINE_DOC = REPO_ROOT / "docs" / "PIPELINE.md"
CONTRACT = REPO_ROOT / "CLAUDE.md"
GITIGNORE = REPO_ROOT / ".gitignore"

#: The file the action would load out of a pull request's checkout, and the phrase
#: `CLAUDE.md` uses to point at the section that explains why it must not be there.
LOCAL_SETTINGS = ".claude/settings.local.json"
POINTER = "docs/PIPELINE.md § The trust boundary"

#: The section's heading is matched on this rather than on the full line, so the
#: subtitle after the colon can be rewritten without breaking the binding.
SECTION_RE = re.compile(r"^## .*trust boundary.*$", re.IGNORECASE | re.MULTILINE)


def _tracked_paths() -> list[str]:
    """Every path git tracks, or a skip when there is no repository to ask."""
    try:
        out = subprocess.run(
            ["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:  # pragma: no cover - CI has git
        pytest.skip(f"git is not usable here: {exc}")
    return [line for line in out.splitlines() if line]


def _section(name_re: re.Pattern[str]) -> str:
    """The text of the `##` section whose heading matches, up to the next `##`."""
    text = PIPELINE_DOC.read_text()
    match = name_re.search(text)
    assert match, (
        "docs/PIPELINE.md has no `## ` section about the trust boundary. It is the "
        "one page that says which text a run may obey: instructions come from the "
        "issue body a maintainer labelled and from the workflow's own prompt, and "
        "everything reached through `gh`, a diff, a CI log or the checkout is data. "
        "Removing the section would leave `CLAUDE.md`'s pointer dangling."
    )
    rest = text[match.end() :]
    end = re.search(r"^## ", rest, re.MULTILINE)
    return rest[: end.start()] if end else rest


def test_the_local_settings_file_is_never_tracked() -> None:
    """A committed `settings.local.json` widens the reviewing job's own allowance."""
    offenders = [p for p in _tracked_paths() if p == LOCAL_SETTINGS or p.endswith("/" + LOCAL_SETTINGS)]
    assert not offenders, (
        f"{offenders} is tracked in git. The action leaves `settingSources` at "
        '["user", "project", "local"], so it loads that file from the pull '
        "request's own checkout — and it carries `permissions.allow` and "
        "`enabledMcpjsonServers`. A pull request that commits one therefore widens "
        "the tool allowance of the job reviewing it: it is the only place in this "
        "pipeline where a contributor's data becomes the run's configuration "
        "without passing through a person. Delete it from the branch "
        f"(`git rm --cached {LOCAL_SETTINGS}`); it is ignored for this reason. "
        "See docs/PIPELINE.md § The trust boundary."
    )


def test_gitignore_still_names_the_local_settings_file() -> None:
    """The first line of defence, and its removal is silent in a diff."""
    lines = {line.strip() for line in GITIGNORE.read_text().splitlines()}
    assert LOCAL_SETTINGS in lines, (
        f".gitignore no longer ignores {LOCAL_SETTINGS}. The test above still fails "
        "if one is committed, but only after somebody has committed it; the ignore "
        "is what stops the accidental `git add -A` that would."
    )


def test_the_boundary_section_names_every_surface_and_its_permissions() -> None:
    """Four surfaces, and the composition of two of them is the one that matters.

    A section that states the rule and lists no surface is a sentence nobody can
    act on: each of these is a place where text somebody else wrote reaches a model
    that can write, and none of them looks like a prompt while you edit it.
    """
    section = _section(SECTION_RE)
    for fragment, why in (
        ("claude-implement.yml", "the job whose comment trigger reads a comment body as the request"),
        ("issue_comment", "the trigger that makes a comment a prompt"),
        ("interactive mode", "no `prompt` input is what selects it"),
        ("claude-review.yml", "the reviewer reads the contributor's diff"),
        ("contents: write", "the permission behind the implementing jobs"),
        ("pull-requests: write", "the permission behind the reviewer"),
        ("Bash(python:*)", "the allowance the review→fix hop lands in"),
        ("@claude please address the review", "the hop from the reviewer into the implementer"),
    ):
        assert fragment in section, (
            f"the trust-boundary section no longer mentions {fragment!r} — {why}. "
            "All four surfaces belong there with the permissions behind them, or "
            "the rule is advice."
        )


def test_the_contract_points_at_the_section_in_one_line() -> None:
    """`CLAUDE.md` is loaded into every turn of every run, so it carries a pointer.

    Issue #91 cut that file from 167 KB to 11 KB precisely because its size is a
    per-turn cost; a section here would start it growing back. One line, and the
    line has to resolve.
    """
    contract = CONTRACT.read_text()
    # The pointer is written the way every other one in that file is — a backticked
    # path, and free to wrap — so it is matched on the text rather than on the bytes.
    flattened = re.sub(r"\s+", " ", contract.replace("`", ""))
    assert POINTER in flattened, (
        f"CLAUDE.md does not point at {POINTER!r}. The contract is the only text "
        "every run loads, so the boundary is not stated anywhere a run can see it "
        "unless one line there says so."
    )
    headings = [line for line in contract.splitlines() if line.startswith("#")]
    assert not [h for h in headings if "trust boundary" in h.lower()], (
        "CLAUDE.md has grown a trust-boundary *section*. One line, pointing at "
        "docs/PIPELINE.md: this file is carried into every turn of every run."
    )


def test_the_pointer_and_the_heading_cannot_drift_apart() -> None:
    """The pointer names a section; the section must be the one it names."""
    heading = SECTION_RE.search(PIPELINE_DOC.read_text())
    assert heading, "docs/PIPELINE.md has no trust-boundary section for the pointer to reach"
    name = POINTER.split("§", 1)[1].strip()
    assert name.lower() in heading.group(0).lower(), (
        f"CLAUDE.md points at § {name}, but the section is {heading.group(0)!r}. "
        "A `§` reference resolves for whoever follows it and for nothing else."
    )
