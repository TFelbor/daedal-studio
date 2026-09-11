"""The coverage gate — the floor, and the three files that have to agree about it.

Until issue #82 the only number anyone could quote about this suite was how many test
functions it collects, and a count of tests is not a measure of what is tested: the
figure written into `CLAUDE.md` had drifted from 949 to 2 493 without a single reader
noticing, because nothing derived it from anything. Coverage replaces that with a
figure a machine computes, and a floor turns the figure into a gate.

A floor is only a gate while three statements stay true at once, and each of them fails
silently:

* **CI still measures.** `--cov` lives on one step in `.github/workflows/ci.yml` and
  nowhere else. Drop a flag and the step still passes — it just stops checking.
* **The recorded figure still describes the floor.** `CLAUDE.md § Build and test`
  carries the measured percentage, the date it was measured and the command; the floor
  is that figure rounded down, less a point. Raise one without the other and the file
  documents a gate that is not the gate.
* **Local runs are still unmeasured.** `pytest.ini` deliberately does not carry
  `--cov`, so `pytest tests/` costs what it always did. A well-meant `addopts` edit
  would slow every local run and, worse, would apply the floor to whatever selection a
  developer happened to be running.

And one that fails loudly but in the wrong place: the exclusions. `.coveragerc` drops
the CUDA-only files a hosted runner cannot execute. That is legitimate — counting code
no CI can reach makes the floor a constant dead weight — and it is also the obvious way
to make a failing gate pass, so what may be excluded is pinned here rather than left to
whoever next sees red.

Everything below is static: no file is written, no test is run twice, and the suite's
actual coverage is not measured here. Measuring it would mean running the suite from
inside itself.
"""

from __future__ import annotations

import configparser
import datetime as dt
import importlib.metadata
import math
import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACT = REPO_ROOT / "CLAUDE.md"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
COVERAGERC = REPO_ROOT / ".coveragerc"
PYTEST_INI = REPO_ROOT / "pytest.ini"
MAKEFILE = REPO_ROOT / "Makefile"
REQUIREMENTS = REPO_ROOT / "requirements-base.txt"
NOTICES = REPO_ROOT / "THIRD-PARTY-NOTICES.md"

#: The step in `ci.yml` that runs the whole suite, and the only one that may measure.
FULL_SUITE_STEP = "Test suite"

#: Reports that name the uncovered lines. `term-missing` is what makes a red gate
#: actionable from the log alone — a bare percentage says a gate failed, not where.
REQUIRED_REPORT_PREFIX = "--cov-report=term-missing"

#: The packages measured. `services/` is absent on purpose: the GPU worker is excluded
#: outright (see `.coveragerc`), and measuring a package whose every file is omitted
#: reports 100 % of nothing.
MEASURED_PACKAGES = ("pythonsrc", "server")

#: What `.coveragerc` may omit, and the only justification accepted for an omission:
#: the file needs a CUDA GPU, so no hosted runner can execute it. Anything else added
#: here is a decision about what "covered" means and belongs in a pull request that
#: says so.
PERMITTED_OMISSIONS = {
    "services/trellis2_worker/*",
    "pythonsrc/sculptors/trellis2*",
}


def _ci_steps() -> list[dict]:
    workflow = yaml.safe_load(CI_WORKFLOW.read_text())
    return workflow["jobs"]["python"]["steps"]


def _full_suite_command() -> str:
    for step in _ci_steps():
        if step.get("name") == FULL_SUITE_STEP:
            return " ".join(step["run"].split())
    pytest.fail(f"ci.yml has no {FULL_SUITE_STEP!r} step — the full run is what is measured")


def _coverage_config() -> configparser.ConfigParser:
    parser = configparser.ConfigParser()
    parser.read(COVERAGERC)
    return parser


def _omitted() -> set[str]:
    return {line.strip() for line in _coverage_config()["run"]["omit"].splitlines() if line.strip()}


def _ci_floor() -> int:
    match = re.search(r"--cov-fail-under=(\d+)", _full_suite_command())
    assert match, (
        "the CI test-suite step does not pass --cov-fail-under, so coverage is "
        "reported and nothing enforces it."
    )
    return int(match.group(1))


def _contract_coverage_bullet() -> str:
    text = CONTRACT.read_text()
    match = re.search(r"^- \*\*Coverage:\*\*.*?(?=^- \*\*|^#{2,3} )", text, re.M | re.S)
    assert match, (
        "CLAUDE.md § Build and test no longer carries a **Coverage:** bullet. The "
        "measured figure, the date and the floor live there and nowhere else."
    )
    return match.group(0)


# ── CI measures, and fails below the floor ───────────────────────────────────


def test_ci_measures_both_packages_on_the_full_suite_step():
    command = _full_suite_command()
    assert command.startswith("pytest tests/"), (
        f"the {FULL_SUITE_STEP!r} step no longer runs the whole suite: {command!r}"
    )
    for package in MEASURED_PACKAGES:
        assert f"--cov={package}" in command, (
            f"CI stopped measuring {package}/. Removing a --cov target does not fail "
            "the step, it just shrinks what the floor is computed over."
        )


def test_ci_prints_a_report_that_names_the_uncovered_lines():
    assert REQUIRED_REPORT_PREFIX in _full_suite_command(), (
        "the step must pass a term-missing report: a floor that fails with only a "
        "total tells whoever hit it that they lost, not what they missed."
    )


def test_ci_fails_below_the_floor():
    assert 0 < _ci_floor() <= 100


def test_only_the_full_suite_step_measures():
    """The named steps above it are subsets — a floor over a subset is meaningless."""
    offending = [
        step.get("name")
        for step in _ci_steps()
        if step.get("name") != FULL_SUITE_STEP and "--cov" in str(step.get("run", ""))
    ]
    assert not offending, (
        f"these CI steps run a subset of the suite and measure coverage: {offending}. "
        "Either the step would fail the floor for tests it never ran, or the floor is "
        "low enough to be no gate at all."
    )


# ── The recorded figure describes the floor ──────────────────────────────────


def test_the_contract_records_the_measured_figure_the_date_and_the_floor():
    bullet = _contract_coverage_bullet()

    measured = re.search(r"Measured (\d+),(\d+)\s*%\s*on\s*(\d{4}-\d{2}-\d{2})", bullet)
    assert measured, (
        "the Coverage bullet must state 'Measured <n>,<n> % on YYYY-MM-DD'. A floor "
        "with no measurement behind it cannot be raised by anyone who did not set it."
    )

    whole, fraction, measured_on = measured.groups()
    figure = float(f"{whole}.{fraction}")
    assert 0 < figure <= 100

    date = dt.date.fromisoformat(measured_on)
    assert date <= dt.date.today(), f"the coverage figure is dated in the future: {date}"

    expected_floor = math.floor(figure) - 1
    assert _ci_floor() == expected_floor, (
        f"CLAUDE.md records {figure} % measured on {measured_on}, which sets a floor of "
        f"{expected_floor}; ci.yml enforces {_ci_floor()}. The floor is the measured "
        "figure rounded down, less a point — re-measure and update both together."
    )


def test_the_contract_shows_the_command_that_reproduces_the_figure():
    """A figure nobody can reproduce is a figure nobody can challenge."""
    bullet = " ".join(_contract_coverage_bullet().split())
    for fragment in (
        "pytest tests/",
        *(f"--cov={package}" for package in MEASURED_PACKAGES),
        REQUIRED_REPORT_PREFIX,
        f"--cov-fail-under={_ci_floor()}",
    ):
        assert fragment in bullet, (
            f"the Coverage bullet's command omits {fragment!r}, so following it does "
            "not reproduce what CI measured."
        )


def test_the_contract_no_longer_carries_the_coverage_todo():
    """Issue #82's TODO said no measurement existed anywhere. One does now."""
    todos = re.findall(r"<!--\s*TODO:.*?-->", CONTRACT.read_text(), re.S)
    stale = [todo for todo in todos if "coverage" in todo.lower()]
    assert not stale, f"CLAUDE.md still asks for coverage measurement: {stale}"


# ── Local runs are unmeasured ────────────────────────────────────────────────


def test_pytest_ini_does_not_measure_coverage():
    parser = configparser.ConfigParser()
    parser.read(PYTEST_INI)
    addopts = parser["pytest"]["addopts"]
    assert "--cov" not in addopts, (
        "pytest.ini's addopts now passes --cov, so every local run pays for coverage "
        "it did not ask for — and any floor there applies to whatever subset the "
        "developer selected. CI is where this is measured."
    )


def test_the_make_test_target_does_not_measure_coverage():
    """`make test` is the documented local run; it is the same selection as CI's."""
    match = re.search(r"^test:\n\t(.+)$", MAKEFILE.read_text(), re.M)
    assert match, "the Makefile no longer has a `test` target"
    assert "--cov" not in match.group(1)


# ── The exclusions stay the unrunnable ones ──────────────────────────────────


def test_the_coverage_config_exists_and_explains_itself():
    assert COVERAGERC.exists(), (
        ".coveragerc is gone; the CUDA-only exclusions went with it and the floor now "
        "counts files no hosted runner can execute."
    )
    text = COVERAGERC.read_text()
    assert "CUDA" in text, (
        "the omissions must say why they are omitted — they are the obvious lever for "
        "making a failing gate pass, and an unexplained one is indistinguishable."
    )


def test_only_the_cuda_only_paths_are_excluded():
    assert _omitted() == PERMITTED_OMISSIONS, (
        f"the coverage omissions are {sorted(_omitted())}, expected "
        f"{sorted(PERMITTED_OMISSIONS)}. Excluding a file is the quiet way to raise a "
        "coverage figure without testing anything; a new exclusion needs its own "
        "argument here."
    )


@pytest.mark.parametrize("pattern", sorted(PERMITTED_OMISSIONS))
def test_every_excluded_pattern_still_matches_a_file(pattern):
    """A dead exclusion is a rename away, and it hides whatever moved into its place."""
    directory, _, glob = pattern.rpartition("/")
    matches = sorted((REPO_ROOT / directory).glob(glob)) if directory else []
    assert matches, (
        f"{pattern!r} in .coveragerc matches nothing in the repository. Either the "
        "CUDA-only code moved — and is now silently counted, or silently excluded "
        "under its old name — or the exclusion outlived its subject."
    )


# ── The plugin is installed, and pinned ──────────────────────────────────────


def test_pytest_cov_is_pinned_in_the_installed_requirements():
    match = re.search(r"^pytest-cov==([\d.]+)$", REQUIREMENTS.read_text(), re.M)
    assert match, (
        "requirements-base.txt must pin pytest-cov: CI installs that file, and an "
        "unpinned plugin means the floor is measured against whatever resolved today."
    )
    installed = importlib.metadata.version("pytest-cov")
    assert installed == match.group(1), (
        f"pytest-cov {installed} is installed and requirements-base.txt pins "
        f"{match.group(1)}. Reinstall from the requirements file — the environment "
        "that measured the floor is the one CI builds."
    )


def test_the_notices_record_the_dev_dependency_and_what_it_pulls():
    """Adding a dependency is a licence decision here, including a test-only one."""
    notices = NOTICES.read_text()
    for token in ("pytest-cov", "coverage.py"):
        assert token in notices, f"THIRD-PARTY-NOTICES.md does not record {token}"
