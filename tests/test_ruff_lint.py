"""The Python lint gate — the rule set, and the five files that have to agree about it.

`CLAUDE.md § Build and test` carried a TODO for months saying no Python linter was
configured: no ruff, no flake8, no black, no pyproject at the root. Every pull request
this repository opens is read by a model, and a review round spent on an unused import
is a review round not spent on the diff. Issue #81 turned ruff on.

A linter is only a gate while five statements stay true at once, and every one of them
fails silently:

* **The tree is clean.** `ruff check .` passes. This is the only test here that runs
  the linter rather than reading a file, and it is the one that would otherwise be
  discovered in CI by whoever pushed next.
* **CI enforces it.** One step in `.github/workflows/ci.yml` runs it, and — unlike the
  frontend lint beside it — without `continue-on-error`. A reported-only linter is a
  linter whose red everyone learns to scroll past.
* **The rule set is the agreed one.** `pyproject.toml` selects `E`, `F`, `W`, `I`, `B`.
  Quietly dropping `B` from that list does not fail anything; it just stops checking.
* **Every exception says why.** An ignore with no reason beside it is indistinguishable
  from one added to make a red run go away, which is the only way this gate can be
  defeated without touching a line of code.
* **The command is written down.** `CLAUDE.md` and `make lint` must name the same
  invocation CI runs, or following the documentation does not reproduce the gate.

Everything except the first test is static: no file is written and the linter is run
exactly once.

**The two CI tests are red until a person applies the workflow patch.** GitHub refuses
any push from an App that creates or updates a file under `.github/workflows/`, so the
run that wrote the rest of this could not add the step — see `docs/PIPELINE.md` § A
pipeline run cannot change this pipeline, which is why the patch is in the pull
request body instead. They are deliberately not skipped or xfailed: a gate nobody can
see missing is the failure mode this whole file exists to prevent.
"""

from __future__ import annotations

import importlib.metadata
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = REPO_ROOT / "pyproject.toml"
CONTRACT = REPO_ROOT / "CLAUDE.md"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
MAKEFILE = REPO_ROOT / "Makefile"
REQUIREMENTS = REPO_ROOT / "requirements-base.txt"
NOTICES = REPO_ROOT / "THIRD-PARTY-NOTICES.md"

#: The one invocation. CI, `make lint` and CLAUDE.md all have to spell it this way, or
#: the three of them are gating three different things.
LINT_COMMAND = "ruff check ."

#: The rule set issue #81 settled on, deliberately conservative: pycodestyle errors and
#: warnings, pyflakes, import order, and bugbear. Widening it is a decision someone
#: should make on purpose; narrowing it is how a gate stops gating.
REQUIRED_RULES = ("E", "F", "W", "I", "B")


def _pyproject() -> dict:
    return tomllib.loads(PYPROJECT.read_text())


def _ruff_config() -> dict:
    return _pyproject()["tool"]["ruff"]


def _ci_steps() -> list[dict]:
    return yaml.safe_load(CI_WORKFLOW.read_text())["jobs"]["python"]["steps"]


def _ci_lint_step() -> dict | None:
    for step in _ci_steps():
        if LINT_COMMAND in " ".join(str(step.get("run", "")).split()):
            return step
    return None


def _make_target(name: str) -> list[str]:
    """The recipe lines of a Makefile target, tabs stripped, comments dropped."""
    match = re.search(rf"^{name}:\n((?:\t.*\n)+)", MAKEFILE.read_text(), re.M)
    assert match, f"the Makefile no longer has a `{name}` target"
    return [line.lstrip("\t") for line in match.group(1).splitlines() if line.strip()]


def _comment_lines() -> list[str]:
    return [line for line in PYPROJECT.read_text().splitlines() if line.lstrip().startswith("#")]


# ── The tree is clean ────────────────────────────────────────────────────────


def test_the_repository_passes_its_own_linter():
    """`ruff check .`, run for real. Everything else in this file reads a file."""
    ruff = shutil.which("ruff")
    command = [ruff, "check", "."] if ruff else [sys.executable, "-m", "ruff", "check", "."]
    result = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True)
    assert result.returncode == 0, (
        "`ruff check .` fails on this checkout:\n\n"
        f"{result.stdout}{result.stderr}\n"
        "Fix the finding, or — if it is behavioural rather than mechanical — add a "
        "`# noqa` with a one-line reason. See CLAUDE.md § Build and test."
    )


# ── CI enforces it ───────────────────────────────────────────────────────────


def test_ci_runs_the_linter():
    assert _ci_lint_step() is not None, (
        f"no step in ci.yml runs {LINT_COMMAND!r}. The linter then only ever runs "
        "where someone remembers to run it, which is the state issue #81 found."
    )


def test_the_ci_lint_step_is_blocking():
    """The frontend lint beside it is `continue-on-error`; this one must not be.

    That one is reported-only because it landed on a backlog of 27 pre-existing
    errors. This one landed green, and a green gate is the only kind whose red means
    anything.
    """
    step = _ci_lint_step()
    assert step is not None, f"no step in ci.yml runs {LINT_COMMAND!r}"
    assert not step.get("continue-on-error"), (
        "the Python lint step is `continue-on-error`, so a lint failure is a green "
        "run with a warning in it. Either the gate blocks or it is decoration."
    )


# ── The rule set is the agreed one ───────────────────────────────────────────


def test_the_pyproject_exists_and_configures_only_the_linter():
    assert PYPROJECT.exists(), "pyproject.toml is gone; ruff now runs on its defaults"
    assert "project" not in _pyproject(), (
        "pyproject.toml grew a [project] table. Nothing here is a package — the code "
        "runs from the checkout — and declaring one invites `pip install -e .`, which "
        "no part of this repository supports."
    )


@pytest.mark.parametrize("rule", REQUIRED_RULES)
def test_the_selected_rule_set_still_carries_every_agreed_family(rule):
    selected = _ruff_config()["lint"]["select"]
    assert rule in selected, (
        f"rule family {rule!r} is no longer selected (select = {selected}). Dropping "
        "one does not fail the lint step — it silently stops checking a whole class "
        "of defect."
    )


def test_a_line_length_is_recorded_even_though_e501_is_off():
    """The number is what a future `ruff format` would wrap to; losing it loses the
    measurement that chose it."""
    assert isinstance(_ruff_config().get("line-length"), int)


# ── Every exception says why ─────────────────────────────────────────────────


@pytest.mark.parametrize("code", sorted(_ruff_config()["lint"].get("ignore", [])))
def test_every_globally_ignored_rule_is_explained_in_a_comment(code):
    assert any(code in line for line in _comment_lines()), (
        f"{code} is ignored repository-wide and no comment in pyproject.toml mentions "
        "it. An unexplained ignore is indistinguishable from one added to make a red "
        "run go away."
    )


@pytest.mark.parametrize("path", sorted(_ruff_config()["lint"].get("per-file-ignores", {})))
def test_every_per_file_ignore_names_its_file_in_a_comment(path):
    stem = Path(path).stem
    assert any(stem in line for line in _comment_lines()), (
        f"{path} carries a per-file ignore that no comment in pyproject.toml "
        "justifies. The rule in CLAUDE.md is that a behavioural finding is ignored "
        "*with a stated reason*, not merely ignored."
    )


@pytest.mark.parametrize("path", sorted(_ruff_config()["lint"].get("per-file-ignores", {})))
def test_every_per_file_ignore_still_has_a_file(path):
    """A dead ignore is a rename away, and it hides whatever moved into its place."""
    assert (REPO_ROOT / path).exists(), (
        f"{path} is named in pyproject.toml's per-file-ignores and does not exist."
    )


# ── The command is written down ──────────────────────────────────────────────


def test_the_contract_names_the_command():
    assert LINT_COMMAND in CONTRACT.read_text(), (
        f"CLAUDE.md § Build and test no longer names {LINT_COMMAND!r}. It is loaded "
        "into every turn of every pipeline run, and is where an agent learns the gate "
        "exists at all."
    )


def test_the_contract_no_longer_carries_the_linter_todo():
    """Issue #81's TODO said no Python linter was configured anywhere. One is now."""
    todos = re.findall(r"<!--\s*TODO:.*?-->", CONTRACT.read_text(), re.S)
    stale = [todo for todo in todos if "linter" in todo.lower() or "ruff" in todo.lower()]
    assert not stale, f"CLAUDE.md still asks for a Python linter: {stale}"


def test_make_lint_runs_both_linters_and_blocks_on_ruff():
    recipe = _make_target("lint")
    assert any(line.strip() == LINT_COMMAND for line in recipe), (
        f"`make lint` no longer runs {LINT_COMMAND!r} — the documented local command "
        "has to be the one CI runs."
    )
    assert not any(line.startswith("-") and "ruff" in line for line in recipe), (
        "the ruff line in `make lint` is prefixed with `-`, so make ignores its exit "
        "status and the target is green whatever ruff says."
    )
    assert any("web run lint" in line for line in recipe), (
        "`make lint` no longer runs the web lint. It is `-`-prefixed on purpose — 27 "
        "pre-existing ESLint errors, mirroring ci.yml's continue-on-error — but it "
        "still has to run, or nobody sees the backlog shrink."
    )


# ── The linter is installed, and pinned ──────────────────────────────────────


def test_ruff_is_pinned_in_the_installed_requirements():
    match = re.search(r"^ruff==([\d.]+)$", REQUIREMENTS.read_text(), re.M)
    assert match, (
        "requirements-base.txt must pin ruff: CI installs that file, and an unpinned "
        "linter turns an unrelated pull request red on the day a new rule ships."
    )
    installed = importlib.metadata.version("ruff")
    assert installed == match.group(1), (
        f"ruff {installed} is installed and requirements-base.txt pins "
        f"{match.group(1)}. Reinstall from the requirements file — a lint run is only "
        "reproducible against the version CI builds."
    )


def test_the_notices_record_the_dev_dependency():
    """Adding a dependency is a licence decision here, including a dev-only one."""
    notices = NOTICES.read_text()
    assert "ruff" in notices, "THIRD-PARTY-NOTICES.md does not record ruff"
    assert re.search(r"ruff \(dev only\)\s*\|\s*MIT", notices), (
        "the Python libraries table must list ruff as dev-only and MIT, the way "
        "pytest-cov is listed. A dev dependency lands in no image, and saying so is "
        "what makes the distribution claim in § 2 checkable."
    )
