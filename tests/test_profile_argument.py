"""The printer profile the server forwards must be one the pipeline can open.

A profile is a **name** at the HTTP boundary and a **path** to `pipeline.py`, and the two
were never translated. `POST /jobs` accepts `ender3.json` as well as
`pythonsrc/profiles/ender3.json` — `resolve_profile_path` exists to accept both, and
`DEFAULT_PROFILE` is stored in either spelling — but `_run_pipeline` forwarded whichever
string it was given straight into `--profile`. The pipeline resolves that against its own
working directory, `/app` in the container, where `ender3.json` is nothing.

Found by the first real end-to-end spec run (#110), not by the suite: every job-submission
test patches `_run_pipeline` wholesale, so the argv it assembles is unreachable from them,
and `tests/test_slicer_profile.py` asserts on the command line `CuraSlicer` builds *given*
a profile it was handed. Between the two sat a seam nothing crossed. The symptom is as
late and as expensive as it gets — Phase 2 compiles, Phase 3 asserts every dimension,
printability scores the mesh, and then:

    [DS] ═══ PHASE 4 FAIL  ✗ ═══
    [DS] ERROR: Printer definition not found: ender3.json

so the whole run is spent before the flag is discovered to be wrong. `_load_profile` is
called here rather than reimplemented: the assertion that matters is that the *slicer*
accepts the value, and a test with its own `exists()` check would agree with itself
forever.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pythonsrc.slicer import CuraSlicer
from server import app as app_module
from server.app import PROFILES_DIR, profile_pipeline_argument

REPO_ROOT = Path(app_module.__file__).resolve().parent.parent

#: Every profile the Settings UI offers. `PrinterSetup`'s datalist is exactly this
#: directory, so each one is a value a person can really submit.
BUNDLED = sorted(path.name for path in PROFILES_DIR.glob("*.json"))


def _request(profile: str):
    return app_module.JobRequest(
        prompt="a deck box", printer_id="default", profile=profile,
    )


def test_there_are_bundled_profiles_to_check():
    assert BUNDLED, f"no profiles in {PROFILES_DIR} — the rest of this module is vacuous"
    assert "ender3.json" in BUNDLED, "the bundled default is gone"


@pytest.mark.parametrize("name", BUNDLED)
def test_a_bare_name_becomes_a_path_the_slicer_can_open(name):
    """The failing case: `ender3.json` submitted, `--profile ender3.json` forwarded."""
    value = profile_pipeline_argument(name)
    assert value == f"pythonsrc/profiles/{name}"
    # Relative to the pipeline's working directory, which is the repository root
    # natively and `/app` in the container — the same tree either way.
    assert CuraSlicer._load_profile(REPO_ROOT / value) is not None


@pytest.mark.parametrize("name", BUNDLED)
def test_the_prefixed_spelling_gives_the_same_answer(name):
    """Both spellings reach here — the Settings UI writes one, the runbook the other."""
    assert profile_pipeline_argument(f"pythonsrc/profiles/{name}") == (
        profile_pipeline_argument(name)
    )


def test_nothing_named_forwards_nothing():
    """`None` must stay `None`: the pipeline's own default is not `ender3.json`.

    `CuraSlicer(profile=None)` uses the bundled *definition* and emits no `-s` overrides
    at all, which is a different slice from the one `ender3.json` produces. Substituting
    a default here would change what an unconfigured job prints.
    """
    assert profile_pipeline_argument(None) is None
    assert profile_pipeline_argument("") is None


@pytest.mark.parametrize("candidate", ["default", "test", "no_such_printer.json"])
def test_a_profile_that_names_no_file_forwards_nothing(candidate):
    """A merely missing profile is tolerated everywhere else and must be here too.

    `"default"` and `"test"` are submitted by name in `tests/test_server.py`, which pins
    that they are a 202 and not a 422. Forwarding them as a path is a certain Phase 4
    crash; omitting the flag leaves the pipeline's own default in force, which is what
    "no profile was named" has always meant.
    """
    assert profile_pipeline_argument(candidate) is None


@pytest.mark.parametrize(
    "candidate",
    ["/etc/passwd", "../../etc/passwd", "pythonsrc/profiles/../../.env"],
)
def test_a_profile_outside_the_profiles_directory_forwards_nothing(candidate):
    """The confinement holds on this path too, and falls back rather than raising.

    `POST /jobs` refuses an escaping path outright, but `DEFAULT_PROFILE` reaches
    `_run_pipeline` from the config store without passing that boundary.
    """
    assert profile_pipeline_argument(candidate) is None


def test_the_forwarded_value_is_what_lands_on_the_command_line():
    """The flag itself, since a value computed and not forwarded is inert."""
    value = profile_pipeline_argument("ender3.json")
    args = app_module._pipeline_args(
        _request("ender3.json"), skip_viz=False, skip_sculpt=False, profile=value,
    )
    assert "--profile" in args
    assert args[args.index("--profile") + 1] == value


def test_no_profile_means_no_flag():
    args = app_module._pipeline_args(
        _request(""), skip_viz=False, skip_sculpt=False, profile=None,
    )
    assert "--profile" not in args
