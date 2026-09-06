"""The README's testing instructions are checked against the thing they describe.

A "how to run the tests" section is the one piece of documentation whose readers are
strangers: someone follows it verbatim on a fresh checkout, and every sentence in it is
either true or an hour of their time. It also rots faster than prose about the product,
because it names the *machinery* — markers, make targets, npm scripts, environment
variables, the files CI invokes — and all of that moves.

It had already rotted once. The section told people that `tests/conftest.py` "redirects
`TELEMETRY_DB_PATH` to a temporary directory", a variable retired when the telemetry
database moved from a SQLite file to PostgreSQL on Supabase — so the paragraph that
existed to say "this suite cannot touch your real data" named a mechanism that no longer
protects anything, and said nothing about the PostgreSQL the suite now requires before it
will even collect. `tests/test_single_database.py` catches a stray *reader* of that
variable in the code; nothing was reading the documentation.

So each assertion below takes one claim out of the section and re-derives it from the
source: `pytest.ini` for the markers, the `Makefile` for the targets, `web/package.json`
for the scripts, `.github/workflows/ci.yml` for what CI actually invokes,
`tests/testing_postgres.py` for the database's own constants. A claim that stops being
true fails here rather than in a stranger's terminal.
"""

from __future__ import annotations

import configparser
import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
README = REPO_ROOT / "README.md"
PYTEST_INI = REPO_ROOT / "pytest.ini"
MAKEFILE = REPO_ROOT / "Makefile"
PACKAGE_JSON = REPO_ROOT / "web" / "package.json"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"

#: The heading the section lives under.
HEADING = "## Running Tests"

#: Named in the section as a file a fresh checkout does *not* have — it is gitignored,
#: which is exactly why the section tells people to copy the template over it.
GITIGNORED_PATHS = {"pythonsrc/config.py"}


def _section() -> str:
    """The body of the Running Tests section, up to the next top-level heading."""
    text = README.read_text()
    start = text.find(HEADING)
    assert start != -1, f"README.md no longer has a {HEADING!r} section"
    rest = text[start + len(HEADING) :]
    end = rest.find("\n## ")
    return rest if end == -1 else rest[:end]


def _declared_markers() -> set[str]:
    parser = configparser.ConfigParser()
    parser.read(PYTEST_INI)
    return {
        line.split(":", 1)[0].strip()
        for line in parser["pytest"]["markers"].splitlines()
        if line.strip()
    }


def _npm_scripts() -> dict[str, str]:
    return json.loads(PACKAGE_JSON.read_text())["scripts"]


def test_the_section_exists_and_shows_the_command():
    """The whole point: a reader must find a runnable command, not a description of one."""
    section = _section()
    assert "```bash" in section, "the section carries no runnable commands"
    assert "pytest tests/" in section


def test_the_default_selection_is_described_as_pytest_ini_configures_it():
    """`pytest tests/` skips the slow markers only because `addopts` says so."""
    addopts = configparser.ConfigParser()
    addopts.read(PYTEST_INI)
    assert 'not slow' in addopts["pytest"]["addopts"], (
        "pytest.ini no longer deselects the slow markers by default, so the README's "
        "claim that `pytest tests/` is already the CI selection is wrong."
    )
    assert 'not slow' in _section(), (
        "the section must say what `pytest tests/` leaves out — otherwise a reader who "
        "needs the hardware-bound tests has no way to know they were never run."
    )


def test_every_declared_marker_is_documented():
    """A marker nobody has heard of is a selection nobody makes."""
    section = _section()
    missing = sorted(name for name in _declared_markers() if name not in section)
    assert not missing, f"markers declared in pytest.ini and undocumented in the README: {missing}"


def test_every_marker_the_section_selects_on_is_declared():
    """The other direction: a `-m` expression naming a dead marker selects nothing."""
    expressions = re.findall(r'-m "([^"]+)"', _section())
    assert expressions, "the section no longer shows a marker-selected run"
    declared = _declared_markers()
    used = {
        word
        for expression in expressions
        for word in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", expression)
        if word not in {"not", "and", "or"}
    }
    unknown = sorted(used - declared)
    assert not unknown, f"the README selects on markers pytest.ini does not declare: {unknown}"


def test_every_make_target_named_exists():
    makefile = MAKEFILE.read_text()
    targets = sorted(set(re.findall(r"\bmake ([a-z][a-z0-9-]*)\b", _section())))
    assert targets, "the section no longer mentions the Makefile shortcuts"
    missing = [t for t in targets if not re.search(rf"^{re.escape(t)}:", makefile, re.M)]
    assert not missing, f"the README names make targets that do not exist: {missing}"


def test_every_npm_script_named_exists():
    scripts = _npm_scripts()
    named = sorted(set(re.findall(r"npm(?: --prefix web)? run ([a-z][a-z0-9:-]*)", _section())))
    assert named, "the section no longer shows how to check the frontend"
    missing = [name for name in named if name not in scripts]
    assert not missing, f"the README names npm scripts web/package.json does not define: {missing}"


def test_the_claim_that_there_is_no_javascript_test_runner_holds():
    """The section tells people `npm run build` *is* the frontend check. If a real test
    runner ever lands, that sentence is the thing that stops anyone running it."""
    if "no JavaScript test runner" not in _section():
        pytest.skip("the section no longer makes that claim")
    assert "test" not in _npm_scripts(), (
        "web/package.json now has a `test` script, so the README's claim that there is "
        "no JavaScript test runner is false and the section must document the command."
    )


def test_every_repository_path_named_exists():
    """A link or a code span pointing at nothing sends a reader looking for a file."""
    section = _section()
    candidates = set(re.findall(r"[\w./-]+\.(?:py|sh|ini|yml|json)", section))
    assert candidates, "the section points at no file in the repository at all"
    missing = sorted(
        path
        for path in candidates
        if path not in GITIGNORED_PATHS
        and "/" in path
        and not (REPO_ROOT / path).exists()
    )
    assert not missing, f"the section names paths that do not exist: {missing}"


def test_every_test_file_ci_names_is_documented():
    """CI runs three Python steps, and the section claims to list them.

    The two named steps are subsets of the full run, chosen because a licence break and a
    dimensional regression should be legible from the job list. Adding a fourth without
    saying so here leaves the README describing a CI that no longer exists.
    """
    section = _section()
    invoked = {
        path
        for command in re.findall(r"run: (pytest [^\n]+)", CI_WORKFLOW.read_text())
        for path in re.findall(r"tests/\S+\.py", command)
    }
    assert invoked, "ci.yml no longer names individual test files"
    missing = sorted(path for path in invoked if path not in section)
    assert not missing, f"CI invokes test files the README's CI list omits: {missing}"


def test_every_environment_variable_named_is_one_something_reads():
    """An invented variable name is worse than none: it looks like a knob and is not."""
    named = set(re.findall(r"\bDS_[A-Z0-9_]+\b", _section()))
    assert named, "the section names no environment variables at all"
    sources = [
        (REPO_ROOT / "tests" / "conftest.py").read_text(),
        (REPO_ROOT / "tests" / "testing_postgres.py").read_text(),
    ] + [
        path.read_text()
        for root in ("pythonsrc", "server")
        for path in (REPO_ROOT / root).rglob("*.py")
    ]
    unread = sorted(name for name in named if not any(name in text for text in sources))
    assert not unread, f"the README documents variables nothing reads: {unread}"


def test_the_retired_database_variable_is_not_documented_anywhere_in_the_readme():
    """It named the protection that stopped existing when the database moved."""
    assert "TELEMETRY_DB_PATH" not in README.read_text(), (
        "TELEMETRY_DB_PATH is retired; documenting it tells a reader the suite is "
        "isolated by a mechanism that no longer runs."
    )


def test_the_database_prerequisite_matches_the_suite_own_constants():
    """Both routes to a PostgreSQL, and the image and container name the suite uses."""
    from tests.testing_postgres import CONTAINER_PREFIX, DEFAULT_IMAGE, IMAGE_ENV, URL_ENV

    section = _section()
    for value in (URL_ENV, IMAGE_ENV, DEFAULT_IMAGE, CONTAINER_PREFIX):
        assert value in section, (
            f"{value!r} is how the suite gets or names its PostgreSQL, and the section "
            "does not mention it — a reader with no Docker and no URL gets a "
            "collection error they cannot act on."
        )


def test_the_kill_switch_the_section_names_is_the_one_conftest_sets():
    """Phase 2's hosted backend bills EUR 0,32 a generation; the flag is the only guard."""
    conftest = (REPO_ROOT / "tests" / "conftest.py").read_text()
    assert 'os.environ["DS_DISABLE_PAID_BACKENDS"] = "1"' in conftest
    assert "DS_DISABLE_PAID_BACKENDS" in _section()
