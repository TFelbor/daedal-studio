"""The size a person asked for must reach the pipeline, and be recorded as theirs.

`--target-mm` has existed on `pythonsrc/pipeline.py` since Phase 3 was written, and
nothing ever forwarded it. Every job submitted through the web app therefore printed
at the pipeline's 50 mm default, whatever the prompt said and whatever the user
wanted — "small pikachu figurine" and "giant pikachu statue" came out the same size.

Two things are tested here, and they are deliberately one unit:

- the value reaches the subprocess, and
- the row says whether a person chose it.

Recording a size the run did not use, or recording 50.0 for a user who never spoke,
is the same class of fabricated capture that the `dev-` output prefix and
`used_reference_assets` exist to prevent. A column that cannot distinguish "the
default happened to be 50 mm" from "they asked for 50 mm" answers no question worth
asking.
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from pythonsrc.telemetry.db import TelemetryDB
from server import app as app_module
from server.app import app

client = TestClient(app)


def _request(**overrides):
    """Build a JobRequest the way POST /jobs would, with test defaults."""
    payload = {"prompt": "a low-poly fox", "printer_id": "default"}
    payload.update(overrides)
    return app_module.JobRequest(**payload)


# ── The value reaches the subprocess ──────────────────────────────────────────

def test_a_requested_size_reaches_the_pipeline_as_target_mm():
    """A chosen size must appear as `--target-mm <value>` in the pipeline argv."""
    args = app_module._pipeline_args(
        _request(target_mm=80.0), skip_viz=False, skip_sculpt=False, profile=None,
    )

    assert "--target-mm" in args, f"no --target-mm in {args}"
    assert args[args.index("--target-mm") + 1] == "80.0"


def test_no_requested_size_leaves_the_pipeline_default_alone():
    """Omitting a size must omit the flag, so the pipeline's own 50.0 stays the default.

    Passing an explicit 50.0 from the server would duplicate the default in a second
    place, and the two would drift the first time either is changed.
    """
    args = app_module._pipeline_args(
        _request(), skip_viz=False, skip_sculpt=False, profile=None,
    )

    assert "--target-mm" not in args


def test_the_native_strategy_filter_keeps_a_flag_and_its_value_together():
    """The mps_native path rewrites the argv, and must not decapitate a flag.

    That branch strips `--skip-visualizer` and `--blueprint <path>` because it
    supplies its own, using a value-blind `skip_next` toggle. A flag whose value
    looks like a flag, or an off-by-one in that loop, would leave `--target-mm`
    without its number and the pipeline would consume the *next* argument as the
    size.
    """
    kept = app_module._strip_phase1_args(
        ["--skip-visualizer", "--blueprint", "/app/data/inputs/blueprint.png",
         "--slice", "--target-mm", "80.0", "--seed", "7"],
    )

    assert kept == ["--slice", "--target-mm", "80.0", "--seed", "7"]


# ── The row says whether a person chose it ────────────────────────────────────

@patch("server.app._run_pipeline", new_callable=AsyncMock)
def test_a_default_size_is_recorded_as_default_not_as_null(mock_run, printer_configured):
    """No size chosen: `size_source` says "default" and the size itself stays NULL.

    NULL + "default" rather than 50.0 + "default": the applied value is already
    recoverable from `repair_report["target_mm"]`, and a stored 50.0 is
    indistinguishable from a user who typed 50.
    """
    resp = client.post("/jobs", json={"prompt": "a vase", "printer_id": "default"})
    assert resp.status_code == 202

    db = TelemetryDB()
    job = db.get_job(resp.json()["job_id"])
    db.close()

    assert job.requested_size_mm is None
    assert job.size_source == "default"


@patch("server.app._run_pipeline", new_callable=AsyncMock)
def test_a_chosen_size_is_recorded_as_the_users_own(mock_run, printer_configured):
    """A size in the request is recorded with `size_source == "user"`."""
    resp = client.post(
        "/jobs", json={"prompt": "a vase", "printer_id": "default", "target_mm": 120.0},
    )
    assert resp.status_code == 202

    db = TelemetryDB()
    job = db.get_job(resp.json()["job_id"])
    db.close()

    assert job.requested_size_mm == pytest.approx(120.0)
    assert job.size_source == "user"


# ── Refusal happens on the model, before a row exists ─────────────────────────

@pytest.mark.parametrize("bad", [0, -5, 5000])
@patch("server.app._run_pipeline", new_callable=AsyncMock)
def test_an_impossible_size_is_refused_by_the_request_model(mock_run, bad):
    """An out-of-range size is a 422 from the model, not a 400 from the handler.

    Validating in the handler is the mistake `OutcomeRequest` already made once: it
    wrote the row and *then* refused the request, leaving a settled job behind a 422.
    A refusal on the model cannot leave anything behind, because the handler never
    runs — which is what the row count asserts.
    """
    db = TelemetryDB()
    before = db.query_one("SELECT COUNT(*) AS n FROM print_job")["n"]
    db.close()

    resp = client.post(
        "/jobs", json={"prompt": "a vase", "printer_id": "default", "target_mm": bad},
    )
    assert resp.status_code == 422

    db = TelemetryDB()
    after = db.query_one("SELECT COUNT(*) AS n FROM print_job")["n"]
    db.close()

    assert after == before
    mock_run.assert_not_called()


# ── Which axis the size describes ─────────────────────────────────────────────
#
# The axis is captured separately from the size because it is a promise made to the
# requester: a control labelled "Height" that submits a longest-edge job is the
# silent-wrong-size bug in a new place. `requested_scale_axis` is what the person
# was shown. The axis actually *applied* is `repair_report["scale_axis"]`, written by
# Phase 3 itself — two different facts, and they must be able to disagree, because
# that disagreement is the bug report.

def test_a_chosen_scale_axis_reaches_the_pipeline():
    """The axis must be forwarded, or the label in the UI is a lie."""
    args = app_module._pipeline_args(
        _request(target_mm=80.0, scale_axis="height"),
        skip_viz=False, skip_sculpt=False, profile=None,
    )

    assert args[args.index("--scale-axis") + 1] == "height"


def test_no_chosen_axis_leaves_the_pipeline_default_alone():
    """Same rule as the size: one default, and it lives in the pipeline."""
    args = app_module._pipeline_args(
        _request(target_mm=80.0), skip_viz=False, skip_sculpt=False, profile=None,
    )

    assert "--scale-axis" not in args


def test_an_unknown_scale_axis_is_refused_by_the_request_model():
    """Only the two axes `Engineer.SCALE_AXES` implements may be requested."""
    with pytest.raises(Exception):
        _request(target_mm=80.0, scale_axis="tallest")


@patch("server.app._run_pipeline", new_callable=AsyncMock)
def test_the_requested_axis_is_recorded_on_the_row(mock_run, printer_configured):
    """What the requester was shown is captured; what ran is in `repair_report`."""
    resp = client.post("/jobs", json={
        "prompt": "a vase", "printer_id": "default",
        "target_mm": 90.0, "scale_axis": "height",
    })
    assert resp.status_code == 202

    db = TelemetryDB()
    job = db.get_job(resp.json()["job_id"])
    db.close()

    assert job.requested_scale_axis == "height"


# ── The composer needs a ceiling before a job exists ──────────────────────────
#
# `build_volume_mm` lived only on `GET /jobs/{id}`, derived by a helper nested inside
# that handler. So the composer — which has to clamp a size *before* there is a job —
# had no source for the machine's limits at all. Extending the probe rather than
# reimplementing the `machine_*` read is the point: two readers of one profile is how
# a clamp ends up disagreeing with `printability.build_volume_fit`.

def test_the_printer_probe_reports_a_build_volume_from_the_profile(monkeypatch):
    """A profile that declares its machine size must say so before a job exists.

    Points at the bundled `pythonsrc/profiles/ender3.json` rather than writing a
    profile into `tmp_path`. A profile may only come from `pythonsrc/profiles` — see
    `resolve_profile_path` — and the bundled file already declares 220/220/250, so this
    is the same assertion against the profile the Settings UI actually offers instead of
    against a fixture that happens to reproduce its numbers.
    """
    import asyncio

    profile = "pythonsrc/profiles/ender3.json"

    monkeypatch.setattr(
        app_module.simulator_manager, "get_status", lambda: {"octoprint": {"running": False}},
    )
    monkeypatch.setattr(app_module.config_store, "get", lambda key, *a, **k: (
        profile if key == "DEFAULT_PROFILE" else None
    ))
    monkeypatch.setattr(app_module, "resolve_printer_target",
                        lambda path: ("octoprint", "http://localhost:5001", None))

    async def _probe(_request):
        return {"success": True, "message": "ok"}
    monkeypatch.setattr(app_module, "test_connection", _probe)

    status = asyncio.run(app_module.printer_status())

    assert status["build_volume_mm"] == [220.0, 220.0, 250.0]


def test_a_profile_without_machine_keys_reports_no_ceiling(monkeypatch):
    """"No ceiling known" is a first-class case, not a zero.

    `bambu_test.json` declares no machine dimensions at all, so it is used directly
    rather than reconstructed in `tmp_path`: a copy would keep passing if the bundled
    profile grew machine keys, which is the one change that should break this.
    A composer that assumes a number would clamp to 0 or NaN and refuse every size for
    that printer.
    """
    import asyncio

    profile = "pythonsrc/profiles/bambu_test.json"

    monkeypatch.setattr(
        app_module.simulator_manager, "get_status", lambda: {"octoprint": {"running": False}},
    )
    monkeypatch.setattr(app_module.config_store, "get", lambda key, *a, **k: (
        profile if key == "DEFAULT_PROFILE" else None
    ))
    monkeypatch.setattr(app_module, "resolve_printer_target",
                        lambda path: ("bambu", "http://x", None))

    async def _probe(_request):
        return {"success": False, "message": "no"}
    monkeypatch.setattr(app_module, "test_connection", _probe)

    status = asyncio.run(app_module.printer_status())

    assert "build_volume_mm" in status
    assert status["build_volume_mm"] is None


def test_the_probe_and_the_job_row_read_the_volume_through_one_helper():
    """One implementation, so a clamp cannot disagree with the printability check."""
    assert callable(app_module._profile_build_volume)
    assert app_module._profile_build_volume(
        {"machine_width": 220, "machine_depth": 220, "machine_height": 250},
    ) == [220.0, 220.0, 250.0]
    assert app_module._profile_build_volume({"machine_width": 220}) is None
    assert app_module._profile_build_volume({}) is None
