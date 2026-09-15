"""The spec-job runbook is checked against the thing it describes.

`docs/RUNBOOK-spec-job.md` is written to be followed verbatim by a stranger on a machine
that has never run this: it names compose services, an image, config keys, endpoints,
artifact filenames, telemetry columns and CLI flags. Every one of those is machinery, and
machinery moves — the README's testing section had already rotted once, telling people
about a `TELEMETRY_DB_PATH` that no longer existed, which is why
`tests/test_readme_testing_docs.py` exists. This module is that test's twin for the
runbook, and each assertion below takes one claim out of the document and re-derives it
from the source: `Makefile` for the targets, `infra/docker-compose.yml` for the services
and the image, `server.app` for the routes and the config keys, `Engineer` and
`SPEC_ARTIFACTS` for the files a job leaves behind, `PrintJob` for the columns, the
`trace` module's own parser for its flags.

A runbook that names something which no longer exists costs its reader an hour and
teaches them to distrust the rest of it. This fails here instead.
"""

from __future__ import annotations

import configparser
import json
import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNBOOK = REPO_ROOT / "docs" / "RUNBOOK-spec-job.md"
MAKEFILE = REPO_ROOT / "Makefile"
COMPOSE = REPO_ROOT / "infra" / "docker-compose.yml"
PYTEST_INI = REPO_ROOT / "pytest.ini"

#: The automated form of the same run. The runbook points at it and it points back.
END_TO_END_TEST = REPO_ROOT / "tests" / "test_spec_job_end_to_end.py"

#: Paths the runbook names that a fresh checkout deliberately does not have: gitignored
#: runtime state, and the scratch file its own `cat >` creates.
ABSENT_BY_DESIGN = {"pythonsrc/config.py", "/tmp/deck_box.json"}

COMPOSE_SUBCOMMANDS = {
    "up", "down", "build", "run", "logs", "stop", "start", "ps", "exec", "config",
}
#: Compose flags that take a value, so the value is not a service name.
COMPOSE_VALUE_FLAGS = {"-f", "--file", "--profile", "-p", "--project-name"}


def _text() -> str:
    assert RUNBOOK.exists(), f"{RUNBOOK.relative_to(REPO_ROOT)} is gone"
    return RUNBOOK.read_text(encoding="utf-8")


def _shell() -> str:
    """Everything inside the document's bash blocks, which is what a reader runs."""
    blocks = re.findall(r"```bash\n(.*?)```", _text(), re.S)
    assert blocks, "the runbook carries no runnable commands at all"
    return "\n".join(blocks)


def _compose_document() -> dict:
    return yaml.safe_load(COMPOSE.read_text())


def _routes() -> set[tuple[str, str]]:
    """Every `(method, path)` the API server declares, with parameters anonymised.

    Anonymised because the runbook writes `/jobs/{job_id}` while a handler may name the
    parameter anything; compared as a *set* rather than matched, because `serve_spa` is a
    catch-all `/{full_path:path}` and would otherwise make every invented path look real.
    """
    from server.app import app

    found = set()
    for route in app.routes:
        path = re.sub(r"\{[^}]+\}", "{}", getattr(route, "path", ""))
        for method in getattr(route, "methods", set()) or set():
            found.add((method, path))
    return found


def _documented_endpoints() -> set[tuple[str, str]]:
    """`METHOD /path` as the prose writes it, plus the URLs its `curl` lines call.

    Only `curl` lines: the document's Python heredocs carry their method in a
    `urllib.request.Request(..., method=...)` argument, and guessing GET for those
    invented an endpoint that does not exist. The prose names every one of them anyway,
    which is the copy a reader reads.
    """
    endpoints = {
        (method, re.sub(r"\{[^}]+\}", "{}", path.rstrip("/") or "/"))
        for method, path in re.findall(r"\b(GET|POST|PUT|DELETE) (/[\w{}/$.-]*)", _text())
    }
    for line in _shell().splitlines():
        if "curl" not in line or "localhost:8000" not in line:
            continue
        method = (re.search(r"-X (GET|POST|PUT|DELETE)", line) or [None, "GET"])[1]
        for url in re.findall(r"http://localhost:8000([\w{}/$.-]*)", line):
            path = re.sub(r"\$\w+|\{[^}]+\}", "{}", url.split("?")[0].rstrip("/")) or "/"
            endpoints.add((method, path))
    return {(method, path) for method, path in endpoints if path.startswith("/")}


# ── it is a runbook ───────────────────────────────────────────────────────────

def test_it_carries_commands_and_says_what_it_proves():
    text = _text()
    assert "```bash" in text
    assert "print_job" in text, "the runbook must say which row it is producing"
    assert "size_source" in text


def test_it_points_at_the_automated_form_of_the_same_run():
    """A reader who does not need to watch it should be told the test exists."""
    text = _text()
    assert END_TO_END_TEST.exists(), "the runbook's automated twin is gone"
    assert END_TO_END_TEST.relative_to(REPO_ROOT).as_posix() in text


def test_the_marker_selection_it_shows_is_the_one_pytest_declares():
    parser = configparser.ConfigParser()
    parser.read(PYTEST_INI)
    declared = {
        line.split(":", 1)[0].strip()
        for line in parser["pytest"]["markers"].splitlines()
        if line.strip()
    }
    expressions = re.findall(r'-m "([^"]+)"', _shell())
    assert expressions, "the runbook no longer shows how to select the slow run"
    used = {
        word
        for expression in expressions
        for word in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", expression)
        if word not in {"not", "and", "or"}
    }
    assert not used - declared, f"markers pytest.ini does not declare: {sorted(used - declared)}"
    # And the test really carries them, or the selection runs nothing.
    body = END_TO_END_TEST.read_text()
    for marker in used:
        assert f"pytest.mark.{marker}" in body, (
            f"{END_TO_END_TEST.name} does not carry the {marker} marker the runbook selects on"
        )


# ── the machinery it names ────────────────────────────────────────────────────

def test_every_make_target_it_names_exists():
    makefile = MAKEFILE.read_text()
    targets = sorted(set(re.findall(r"\bmake ([a-z][a-z0-9-]*)\b", _text())))
    assert targets, "the runbook names no Makefile shortcut"
    missing = [t for t in targets if not re.search(rf"^{re.escape(t)}:", makefile, re.M)]
    assert not missing, f"the runbook names make targets that do not exist: {missing}"


def test_every_compose_service_and_profile_it_names_is_declared():
    document = _compose_document()
    services = set(document.get("services") or {})
    profiles = {
        profile
        for service in (document.get("services") or {}).values()
        for profile in (service.get("profiles") or [])
    }

    named_services: set[str] = set()
    named_profiles: set[str] = set()
    for line in _shell().splitlines():
        line = line.strip()
        if not line.startswith("docker compose"):
            continue
        tokens = line.split()[2:]
        expect_value = False
        seen_subcommand = False
        # Paired with its predecessor rather than tracked in a variable: the loop body
        # has five `continue`s, and a `previous = token` at the end of it is one edit away
        # from being skipped on whichever branch someone adds next.
        for previous, token in zip([None, *tokens], tokens):
            if expect_value:
                if previous == "--profile":
                    named_profiles.add(token)
                expect_value = False
                continue
            if token in COMPOSE_VALUE_FLAGS:
                expect_value = True
                continue
            if token.startswith("-"):
                continue
            if token in COMPOSE_SUBCOMMANDS and not seen_subcommand:
                seen_subcommand = True
                continue
            if seen_subcommand:
                named_services.add(token)

    assert named_services, "the runbook starts no compose service"
    assert not named_services - services, (
        f"the runbook names compose services that do not exist: "
        f"{sorted(named_services - services)}"
    )
    assert not named_profiles - profiles, (
        f"the runbook names compose profiles nothing declares: "
        f"{sorted(named_profiles - profiles)}"
    )


def test_the_image_it_checks_for_curaengine_is_the_one_compose_builds():
    """Phase 4 runs inside the pipeline image, so that is where the slicer has to be."""
    images = {
        service.get("image")
        for service in (_compose_document().get("services") or {}).values()
        if service.get("image")
    }
    named = set(re.findall(r"\bds-[\w.-]+:[\w.-]+", _shell()))
    assert named, "the runbook no longer checks any image for a real CuraEngine"
    assert not named - images, (
        f"the runbook names images compose does not build: {sorted(named - images)}"
    )
    assert "CuraEngine" in _shell(), (
        "the runbook must show how to prove the slicer is real — the suite runs against "
        "a stub that exits 70"
    )


def test_every_config_key_it_writes_is_one_the_server_accepts():
    """`POST /config` refuses an unknown key with a 400, so a typo here is dead prose."""
    from server.config_store import CONFIG_KEYS

    named = set(re.findall(r"\b([A-Z][A-Z0-9_]{3,})=", _shell())) | set(
        re.findall(r'"key": "([A-Z0-9_]+)"', _text())
    )
    written = {key for key in named if key in CONFIG_KEYS or key.startswith(("OCTOPRINT", "DEFAULT_", "MOONRAKER"))}
    assert written, "the runbook no longer points the app at a printer"
    unknown = sorted(key for key in written if key not in CONFIG_KEYS)
    assert not unknown, f"the runbook writes config keys the server refuses: {unknown}"


def test_every_endpoint_it_names_is_a_route():
    documented = _documented_endpoints()
    assert documented, "the runbook names no endpoint at all"
    routes = _routes()
    missing = sorted(
        f"{method} {path}" for method, path in documented if (method, path) not in routes
    )
    assert not missing, f"the runbook names endpoints the server does not serve: {missing}"


def test_every_repository_path_it_names_exists():
    candidates = set(
        re.findall(r"[\w./$-]+\.(?:py|sh|ini|yml|yaml|json|md|template)", _text())
    )
    assert candidates, "the runbook points at no file in the repository"
    missing = sorted(
        path
        for path in candidates
        # `data/` is gitignored runtime state and `$JOB` is a shell variable: both are
        # paths a reader creates by following the document, not paths it asserts about.
        if path not in ABSENT_BY_DESIGN
        and "/" in path
        and not path.startswith(("data/", "/tmp/"))
        and "{" not in path
        and "$" not in path
        and not (REPO_ROOT / path).exists()
    )
    assert not missing, f"the runbook names paths that do not exist: {missing}"


def test_the_simulator_helpers_it_calls_exist():
    from server.simulator_manager import simulator_manager

    called = set(re.findall(r"simulator_manager\.(\w+)", _text()))
    assert called, "the runbook no longer says where the simulator's API key comes from"
    missing = sorted(name for name in called if not hasattr(simulator_manager, name))
    assert not missing, f"the runbook calls SimulatorManager methods that are gone: {missing}"


def test_the_trace_flags_it_documents_are_the_ones_trace_declares():
    from pythonsrc.telemetry import trace

    source = Path(trace.__file__).read_text()
    declared = set(re.findall(r'add_argument\(\s*"(--[\w-]+)"', source))
    # Every `## ` section that mentions the module, and nothing else. Slicing from the
    # first mention to the end of the document instead attributed each later section's
    # flags to `trace`: naming the module once in step 0 pulled step 2's
    # `--force-recreate` — a compose flag — into the set and failed the assertion below
    # on a document that was correct. A heading is the natural scope for "which tool is
    # this flag for", and the module may be named in more than one section.
    sections = re.split(r"^## ", _text(), flags=re.M)
    section = "\n".join(s for s in sections if "pythonsrc.telemetry.trace" in s)
    assert section, "the runbook never names the trace module"
    # Both halves: the flag the reader actually runs, and the ones the prose offers.
    invoked = set(re.findall(r"trace ((?:--[\w-]+\s*)+)", _shell()))
    named = set(re.findall(r"`(--[\w-]+)`", section)) | {
        flag for group in invoked for flag in group.split()
    }
    assert "--latest" in named, "the runbook must show how to read the row it just wrote"
    unknown = sorted(flag for flag in named if flag not in declared)
    assert not unknown, f"the runbook documents trace flags it does not have: {unknown}"


def test_every_module_it_runs_is_importable():
    import importlib.util

    modules = set(re.findall(r"python(?:3)? -m ([\w.]+)", _shell()))
    assert modules, "the runbook runs no module"
    missing = sorted(
        name for name in modules
        if name not in ("json.tool", "uvicorn") and importlib.util.find_spec(name) is None
    )
    assert not missing, f"the runbook runs modules that do not exist: {missing}"


def test_every_environment_variable_it_names_is_one_something_reads():
    named = set(re.findall(r"\bDS_[A-Z0-9_]+\b", _text()))
    assert named, "the runbook names no environment variable, not even the database URL"
    sources = [
        path.read_text()
        for root in ("pythonsrc", "server", "infra")
        for path in (REPO_ROOT / root).rglob("*")
        if path.is_file() and path.suffix in {".py", ".yml", ".sh", ".template"}
    ] + [(REPO_ROOT / ".env.template").read_text()]
    unread = sorted(name for name in named if not any(name in text for text in sources))
    assert not unread, f"the runbook documents variables nothing reads: {unread}"


# ── the outputs it tells the reader to look at ────────────────────────────────

def test_the_spec_it_submits_is_one_the_schema_accepts():
    """The document's own JSON, parsed and validated — a runbook whose payload is a 422
    wastes its reader's time at the one step everything after depends on."""
    from pythonsrc.organizer.spec import ARCHETYPES, OrganizerSpec

    blocks = re.findall(r"```bash\n.*?<<'JSON'\n(.*?)\nJSON", _text(), re.S)
    assert blocks, "the runbook no longer contains a spec to submit"
    spec = OrganizerSpec.from_dict(json.loads(blocks[0]))
    assert spec.archetype in ARCHETYPES
    assert spec.lid is not None, (
        "the point of this run is a two-body plate through the real slicer: without a lid "
        "the deck box compiles to one part and the adhesion decision is never made over two"
    )


def test_the_artifacts_it_lists_are_the_ones_a_spec_job_writes():
    from pythonsrc.engineer import EXPORT_SUFFIXES
    from server.app import SPEC_ARTIFACTS

    text = _text()
    for filename in SPEC_ARTIFACTS.values():
        assert filename in text, (
            f"{filename} is served by GET /jobs/{{id}}/spec and the runbook does not "
            "tell the reader to look at it"
        )
    for name in ("compiled_mesh.stl", "spec.json", "printability.json"):
        assert name in text, f"a spec run writes {name} and the runbook omits it"
    assert "engineered_mesh.obj" in text, "the viewer's copy is the one GET /jobs/{id}/mesh serves"
    for suffix in EXPORT_SUFFIXES:
        assert f"engineered_mesh{suffix}" in text or f"`{suffix}`" in text, (
            f"Phase 3 writes engineered_mesh{suffix} and the runbook does not mention it"
        )


def test_the_row_facts_it_promises_are_real_columns_and_real_values():
    import dataclasses

    from pythonsrc.telemetry.schema import VALID_SIZE_SOURCES, PrintJob

    columns = {field.name for field in dataclasses.fields(PrintJob)}
    promised = {
        "size_source", "requested_size_mm", "requested_scale_axis", "generation_model",
        "generation_backend", "generation_cost_eur", "slice_status", "layer_count",
        "printability_verdict", "repair_report", "dispatched_printer_url",
    }
    text = _text()
    for column in sorted(promised):
        assert column in columns, f"{column} is not a print_job column any more"
        assert column in text, f"the runbook stopped telling the reader to check {column}"
    assert "spec" in VALID_SIZE_SOURCES
    assert 'size_source = spec' in text or 'size_source: "spec"' in text


def test_the_generation_model_it_promises_is_the_one_the_pipeline_records():
    """`organizer/deck_box` is assembled in `_record_spec_generation`, from the
    archetype's own name — so a renamed archetype must move this sentence too."""
    from pythonsrc.organizer.spec import ARCHETYPES

    named = set(re.findall(r"organizer/([\w_]+)", _text()))
    assert named, "the runbook no longer says what the generation model should read"
    unknown = sorted(name for name in named if name not in ARCHETYPES)
    assert not unknown, f"the runbook names archetypes that do not exist: {unknown}"


def test_the_dimension_tolerance_it_quotes_is_the_one_the_check_uses():
    from pythonsrc.organizer.compiler import DEFAULT_TOLERANCE_MM

    text = _text()
    assert f"{DEFAULT_TOLERANCE_MM:g}" in text.replace("±", ""), (
        f"the runbook quotes a tolerance other than DEFAULT_TOLERANCE_MM "
        f"({DEFAULT_TOLERANCE_MM} mm), which is the number Phase 3 asserts at"
    )


def test_the_dispatch_confirmation_it_shows_is_the_one_the_gate_requires():
    """`confirmed: true` *is* the gate: there is no unconfirmed code path."""
    from server.app import DispatchRequest

    fields = set(DispatchRequest.model_fields)
    shown = set(re.findall(r'"(\w+)": (?:True|true|shown\[)', _shell()))
    confirmation = shown & (fields | {"confirmed", "profile", "base_url"})
    assert "confirmed" in confirmation, "the runbook no longer confirms the dispatch"
    unknown = sorted(name for name in confirmation if name not in fields)
    assert not unknown, f"the runbook sends dispatch fields the endpoint ignores: {unknown}"
    for expected in ("profile", "base_url"):
        assert expected in _shell(), (
            f"the gate 409s when the target moved, so the runbook must send {expected} "
            "as it was displayed"
        )
