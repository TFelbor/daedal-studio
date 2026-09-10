"""One spec job, all the way through: `POST /jobs` → CuraEngine → simulator → the row.

Everything about the parametric path is covered by the default selection up to Phase 3
plus printability — with a CuraEngine **stub** on PATH. So the one thing nobody had
watched is the thing this module runs: a two-body plate (a deck box is a body *and* a
lid) through the real slicer, the dispatch gate, the dockerised OctoPrint simulator, and
into a real `print_job` row. Each of those has a defect class the stub cannot show:
CuraEngine slices two grounded bodies and `_adhesion_args` decides a brim for both at
once; the row's `slice_status`, `layer_count` and material estimates come from
`gcode_stats` reading an E axis that only exists once something really sliced; and
`dimension_check` rides on `repair_report`, which nothing writes unless Phase 3 ran with
a `--job-id` against a database.

It is `slow` and `real_printer` because it needs a machine the repository cannot assume:
the Docker daemon, the built `ds-mvp-pipeline` image (the slice happens *inside* it — the
server launches every pipeline as `docker compose run`), and a simulator answering on
5001. Each of those is checked by name before anything runs, and a missing one is a skip
that says which, so `pytest tests/` is unchanged and `-m "slow and real_printer"` on a
machine that is half set up says what to fix rather than failing four minutes in.

Two deliberate choices about how it drives the server:

**In-process, through `TestClient`, not a `uvicorn` subprocess.** `_run_pipeline` is a
background task on the app's own loop and `TestClient` runs that loop in its own thread,
so the pipeline's stdout keeps being drained while this thread sleeps between polls. A
subprocess server would also fire the shutdown hook on teardown, and that hook stops the
OctoPrint simulator — the exact damage `tests/conftest.py` cuts the shared
`SimulatorManager` off from Docker to prevent. The ASGI app is the same one `uvicorn`
serves; what is exercised here is the pipeline path, and `docs/RUNBOOK-spec-job.md` is
the real server.

**It dispatches to the simulator and to nothing else.** The gate test asserts the
resolved target is the address this module configured — `http://localhost:5001` — and
skips otherwise, so a developer's real printer configured in Settings cannot be handed a
print by a test run. The print that does start is cancelled in teardown.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from pythonsrc.organizer.spec import OrganizerSpec
from pythonsrc.telemetry.db import TelemetryDB
from server import app as app_module
from server.app import app
from server.config_store import ConfigStore
from server.simulator_manager import simulator_manager

pytestmark = [pytest.mark.slow, pytest.mark.real_printer]

REPO_ROOT = Path(app_module.__file__).resolve().parent.parent

#: The image `infra/docker-compose.yml` builds for `pipeline-runner`, which is where
#: Phase 4 runs and therefore where CuraEngine has to exist.
PIPELINE_IMAGE = "ds-mvp-pipeline:latest"

#: What a person types into Printer Setup for the dockerised simulator, and what
#: `dispatched_printer_url` must record — see `container_reachable_url`.
SIMULATOR_URL = "http://localhost:5001"

#: The profile the job slices against; `pythonsrc/profiles/ender3.json` is the bundled
#: default and the one `PROFILES_DIR` confinement accepts by name.
PROFILE = "ender3.json"

#: A cold `docker compose run` pulls nothing but does create a container, and Phase 4 on
#: a ~95 mm part is hundreds of layers. Generous rather than tight: a timeout here is
#: reported as a failure with the log tail, and a flaky one would teach nobody anything.
PIPELINE_TIMEOUT_S = 1200
DISPATCH_TIMEOUT_S = 180
POLL_INTERVAL_S = 2.0

#: Twenty single-sleeved cards rather than a hundred double-sleeved ones: the card's own
#: height fixes the part at ~96 mm whatever the count, and a thinner box slices in a
#: fraction of the time while still compiling to **two** parts, which is the whole point
#: of running this one through the real slicer.
DECK_BOX_SPEC = {
    "archetype": "deck_box",
    "schema_version": 1,
    "compartments": [
        {"contents": {"count": 20, "card": "standard", "sleeving": "single"}}
    ],
    "lid": {
        "kind": "lift_off",
        "magnets": False,
        "height_mm": 12.0,
        "wall_mm": 1.2,
        "clearance_mm": 0.2,
        "top_mm": 2.0,
    },
}

PROMPT = "a deck box for 20 single-sleeved standard cards"


# ── what this needs, checked by name ──────────────────────────────────────────

def _docker(*args: str, timeout: float = 120) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, timeout=timeout
    )


def _why_not_runnable() -> str | None:
    """The reason this cannot run here, or None. One sentence, naming the remedy."""
    if shutil.which("docker") is None:
        return "no `docker` on PATH: the server runs every pipeline as `docker compose run`."
    try:
        if _docker("info").returncode != 0:
            return "the Docker daemon is not reachable — start Docker and try again."
    except (OSError, subprocess.SubprocessError) as exc:
        return f"could not ask the Docker daemon anything: {exc}"

    if _docker("image", "inspect", PIPELINE_IMAGE).returncode != 0:
        return (
            f"{PIPELINE_IMAGE} is not built, and Phase 4 runs inside it. "
            "Build it with `make build` (see docs/RUNBOOK-spec-job.md)."
        )
    probe = _docker("run", "--rm", PIPELINE_IMAGE, "sh", "-c", "command -v CuraEngine",
                    timeout=300)
    if probe.returncode != 0:
        return (
            f"{PIPELINE_IMAGE} carries no CuraEngine, so there is no real slicer to "
            "exercise. Rebuild the image."
        )

    key = simulator_manager.octoprint_api_key()
    if not key:
        return (
            "no OctoPrint API key in data/octoprint/octoprint/config.yaml — start the "
            "simulator once (`docker compose -f infra/docker-compose.yml --profile "
            "simulator up -d octoprint-simulator`) and let it write its config."
        )
    try:
        answer = httpx.get(
            f"{SIMULATOR_URL}/api/version", headers={"X-Api-Key": key}, timeout=5.0
        )
    except httpx.HTTPError as exc:
        return f"nothing answered at {SIMULATOR_URL}: {exc}. Start the OctoPrint simulator."
    if answer.status_code != 200:
        return (
            f"{SIMULATOR_URL} answered {answer.status_code} to an authenticated "
            "/api/version — check the simulator's API key."
        )
    return None


@pytest.fixture(scope="module")
def runnable_host() -> None:
    reason = _why_not_runnable()
    if reason:
        pytest.skip(f"This end-to-end run needs more than the suite: {reason}")


@pytest.fixture(scope="module")
def printer_pointed_at_the_simulator(runnable_host):
    """Point the config store at the simulator, and put back what was there.

    `printer_status` refuses a job unless a printer *answered*, and the answer comes
    from the encrypted config store. The store is the test session's own — `conftest`
    redirects both `DS_CONFIG_KEY_PATH` and `DS_DATABASE_URL` — but it is shared with
    every other module in the run, so the three values are restored afterwards.
    """
    store = ConfigStore()
    wanted = {
        "DEFAULT_PROFILE": PROFILE,
        "OCTOPRINT_URL": SIMULATOR_URL,
        "OCTOPRINT_API_KEY": simulator_manager.octoprint_api_key(),
    }
    previous = {key: store.get(key) for key in wanted}
    for key, value in wanted.items():
        store.set(key, value)
    yield wanted
    for key, value in previous.items():
        if value is None:
            store.delete(key)
        else:
            store.set(key, value)


@pytest.fixture(scope="module")
def spec_job(printer_pointed_at_the_simulator):
    """Submit one deck-box spec and wait for the pipeline to settle.

    Yields the client, the job id and the final `GET /jobs/{id}` body, so each
    assertion below is one fact about one run rather than one run each.
    """
    with TestClient(app) as client:
        status = client.get("/system/printer/status").json()
        if not status.get("running"):
            pytest.skip(
                "the printer did not answer, so POST /jobs would refuse: "
                f"{status.get('detail')}"
            )

        response = client.post("/jobs", json={
            "prompt": PROMPT,
            "printer_id": "default",
            "profile": PROFILE,
            "spec": DECK_BOX_SPEC,
            # The web app's own submission: Phase 5 waits for a person.
            "print": False,
            "start_print": False,
        })
        assert response.status_code == 202, response.text
        job_id = response.json()["job_id"]

        body = _wait_for(client, job_id, PIPELINE_TIMEOUT_S,
                         lambda b: b["outcome"] not in (None, "unknown"))
        yield SimpleNamespace(client=client, job_id=job_id, body=body)

        _cancel_any_simulator_print()
        # The input goes and the output stays, and the asymmetry is the point. The spec
        # is already on the row canonically (`request_params["spec"]`), so
        # `data/inputs/{job_id}/spec.json` is a duplicate of something durable. The eight
        # files in `data/outputs/{job_id}` and the log beside them are not on any row —
        # the compiled mesh, the G-code, `compile_features.json`,
        # `dimension_report.json`, `printability.json` — and they are the only evidence a
        # slow run leaves that a person can open afterwards. That matters more here than
        # anywhere: this test's row is written into the schema `tests/conftest.py` drops
        # at exit, so the artifacts outlive the row that describes them. `data/` is
        # gitignored runtime state and is cleared wholesale when it is in the way.
        shutil.rmtree(REPO_ROOT / "data" / "inputs" / job_id, ignore_errors=True)


def _wait_for_operator(job_id: str, timeout_s: float) -> dict:
    """Wait for the phase-5 record the dispatch endpoint's background task appends.

    `GET /jobs/{id}` cannot answer "has the operator finished". `dispatch_state` is
    `dispatched` from the moment the row says `awaiting_verdict`, which is written
    before the subprocess is even spawned. And `current_phase` is worse than useless
    here: the endpoint rewrites a `running` phase to `error: "Stopped"` whenever the
    row's outcome is settled, and `awaiting_verdict` satisfies that test — so phase 5
    reads as a failure for the whole dispatch window.

    The `.status` file is what `_append_phase_status` actually writes: append-only, one
    JSON object per line, and the operator's exit appends phase 5 `complete` or `error`
    to it.
    """
    status_file = REPO_ROOT / "data" / "logs" / f"{job_id}.status"
    deadline = time.monotonic() + timeout_s
    last: dict = {}
    while time.monotonic() < deadline:
        for line in status_file.read_text().splitlines() if status_file.exists() else []:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict) and record.get("phase") == 5:
                last = record
                if record.get("status") in ("complete", "error"):
                    return record
        time.sleep(2.0)
    raise AssertionError(
        f"the operator did not finish within {timeout_s}s; last phase-5 record: {last}"
    )


def _wait_for(client, job_id: str, timeout_s: float, done) -> dict:
    """Poll `GET /jobs/{id}` until `done(body)`, then return that body."""
    deadline = time.monotonic() + timeout_s
    body: dict = {}
    while time.monotonic() < deadline:
        response = client.get(f"/jobs/{job_id}")
        assert response.status_code == 200, response.text
        body = response.json()
        if done(body):
            return body
        time.sleep(POLL_INTERVAL_S)
    log = "\n".join(body.get("log_tail") or ["(no log)"])
    pytest.fail(
        f"job {job_id} did not settle within {timeout_s:.0f}s "
        f"(outcome={body.get('outcome')}, phase={body.get('current_phase')}).\n{log}"
    )


def _cancel_any_simulator_print() -> None:
    """Leave the simulator as it was found: dispatching starts a real virtual print."""
    key = simulator_manager.octoprint_api_key()
    if not key:
        return
    try:
        httpx.post(
            f"{SIMULATOR_URL}/api/job",
            headers={"X-Api-Key": key},
            json={"command": "cancel"},
            timeout=5.0,
        )
    except httpx.HTTPError:
        pass


def _row(job_id: str):
    db = TelemetryDB()
    try:
        return db.get_job(job_id)
    finally:
        db.close()


# ── the run ───────────────────────────────────────────────────────────────────

def test_the_pipeline_finished(spec_job):
    """Everything below reads one run; if it failed, say so once, with the log."""
    log = "\n".join(spec_job.body.get("log_tail") or ["(no log)"])
    assert spec_job.body["outcome"] == "success", (
        f"the spec job did not finish: outcome={spec_job.body['outcome']}\n{log}"
    )


def test_the_row_says_the_spec_decided_the_size(spec_job):
    """`size_source="spec"` is the whole reason that value exists: no size was
    requested, so recording `default` would claim the 50 mm default applied to a part
    whose every dimension the spec fixed."""
    row = _row(spec_job.job_id)
    assert row.size_source == "spec"
    assert row.requested_size_mm is None
    assert row.requested_scale_axis is None
    assert row.request_params["spec"] == OrganizerSpec.from_dict(DECK_BOX_SPEC).to_dict()


def test_the_compiler_is_the_generation_model(spec_job):
    """No new column: the archetype *is* what made this mesh."""
    row = _row(spec_job.job_id)
    assert row.generation_model == "organizer/deck_box"
    assert row.generation_backend == "local"
    assert row.generation_cost_eur is None, "compiling geometry bills nothing"
    assert row.generation_params["spec_sha256"], "the spec hash is the join back to the spec"
    assert row.generation_params["parts"] == ["body", "lid"]
    # No image ever existed, and the blueprint columns say so rather than carrying a
    # fixture's hash.
    assert row.blueprint_sha256 is None
    assert row.blueprint_seed is None
    assert row.used_reference_assets in (0, False), "a spec run substitutes nothing"


def test_the_real_slicer_produced_gcode(spec_job):
    """The stub cannot reach any of this: every figure below is derived from an E axis."""
    body = spec_job.body
    assert body["slice_status"] == "success"
    assert body["layer_count"] and body["layer_count"] > 0
    assert body["estimated_print_time_s"] and body["estimated_print_time_s"] > 0
    assert body["filament_used_mm3"] and body["filament_used_mm3"] > 0

    row = _row(spec_job.job_id)
    assert row.slice_duration_s is not None and row.slice_duration_s > 0
    # Two grounded bodies, so the adhesion decision was made over both at once. Whether
    # it chose a brim depends on the measured bed contact; what must be true is that the
    # decision is recorded rather than left to `fdmprinter`'s own default.
    assert isinstance(row.slice_stats, dict) and row.slice_stats


def test_every_designed_feature_came_back_within_tolerance(spec_job):
    """Phase 3 asserted a spec run rather than repairing it, and then measured it.

    The report rides on `repair_report` — the `achieved_extent_mm` precedent, no new
    column — and it is the honest one because it measures the mesh the slicer received.
    """
    row = _row(spec_job.job_id)
    report = row.repair_report or {}
    assert report.get("repair_method") == "asserted", (
        "a compiled mesh is watertight by construction; repairing it would hide a "
        "compiler bug and discard the dimensions the spec fixed"
    )
    assert report.get("scale_applied") is False
    assert report.get("scale_axis") == "preserved"

    check = report.get("dimension_check")
    assert check, "no dimension_check on the row — Phase 3 measured nothing"
    assert check["within_tolerance"] is True
    assert check["missing"] == []
    assert check["out_of_tolerance"] == []
    assert check["features_checked"] > 0
    assert check["features_within"] == check["features_checked"]
    assert check["max_abs_error_mm"] <= check["tolerance_mm"]


def test_printability_scored_the_compiled_plate(spec_job):
    """A verdict, and a report with checks in it — not the error envelope a crash writes."""
    body = spec_job.body
    assert body["printability_verdict"] in ("ready", "risky"), body["printability_verdict"]
    assert body["printability_score"] is not None

    report = spec_job.client.get(f"/jobs/{spec_job.job_id}/printability").json()
    assert report.get("checks"), f"not a printability report: {json.dumps(report)[:400]}"
    # The gate was told the part count off `len(compile_result.parts)`, so a body and a
    # lid are two grounded bodies *as designed* rather than an unintended split.
    assert report["features"].get("component_count") == 2
    floating = [c for c in report["checks"] if c["check"] == "floating_components"]
    assert floating and floating[0]["status"] == "pass", floating


def test_phase_5_waits_for_a_person(spec_job):
    """`print: false` is the web app's submission, so the job stops at the gate."""
    body = spec_job.body
    assert body["dispatch_state"] == "awaiting_confirmation"
    assert body["dispatch_target"]["base_url"] == SIMULATOR_URL
    assert body["dispatch_target"]["firmware"] == "octoprint"
    # The gate has something to send, in all three formats Phase 3 writes.
    for fmt in ("gcode", "stl", "3mf"):
        served = spec_job.client.get(
            f"/jobs/{spec_job.job_id}/download?format={fmt}&preview=1"
        )
        assert served.status_code == 200, f"{fmt}: {served.text[:200]}"


def test_the_confirmed_dispatch_reaches_the_simulator(spec_job):
    """The last leg: a person confirms, the operator uploads, the row records where.

    Guarded on the target being the simulator this module configured — a test must not
    hand a print to whatever machine a developer has in Settings.
    """
    target = spec_job.body["dispatch_target"]
    if target["base_url"] != SIMULATOR_URL:
        pytest.skip(f"the resolved printer is {target['base_url']}, not the simulator")

    response = spec_job.client.post(
        f"/jobs/{spec_job.job_id}/print-dispatch",
        json={"confirmed": True, "profile": target["profile"],
              "base_url": target["base_url"]},
    )
    assert response.status_code == 200, response.text

    # Not `dispatch_state == "dispatched"`: the endpoint writes `awaiting_verdict`
    # and appends phase 5 `running` *before* `asyncio.create_task(_run())`, and
    # `dispatch_state` reports `dispatched` on that outcome alone — so a wait on it
    # returns on its first poll with `run_operator.py` still uploading. An operator
    # that then exits non-zero flips the row to `failure` after this test has gone
    # green, and the fixture's cancel could land before `start_print` and leave the
    # virtual print running. So wait for the operator's own exit.
    record = _wait_for_operator(spec_job.job_id, DISPATCH_TIMEOUT_S)
    assert record["status"] == "complete", (
        f"the operator exited non-zero: {record.get('error')}"
    )

    body = spec_job.client.get(f"/jobs/{spec_job.job_id}").json()
    assert body["dispatch_state"] == "dispatched"
    assert body["outcome"] == "awaiting_verdict", (
        "dispatched is not printed — only a person closes this out"
    )

    row = _row(spec_job.job_id)
    assert row.dispatched_printer_url == SIMULATOR_URL, (
        "the row must name the printer a person chose, not the container route that "
        "stood in for it"
    )
    db = TelemetryDB()
    try:
        events = db.get_job_events(spec_job.job_id, kind="dispatch_confirmed")
    finally:
        db.close()
    assert len(events) == 1, "one confirmation, one event"
