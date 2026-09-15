"""A spec reaches the pipeline through `POST /jobs`, and the row says the spec decided.

`size_source` had three values — `default`, `user`, `prompt_hint` — and a spec job fit
none of them: its row read `size_source="default"`, a claim that the 50 mm default applied
to a part whose every dimension the spec fixed. The request model now carries the spec,
validated on the model with the stdlib-only schema (the reason `pythonsrc.organizer`
imports nothing heavy), written canonically into the job's own input directory, and
forwarded as `--spec`. The row records `size_source="spec"` with no size and no axis: the
spec is the size.

A spec run is also never a Phase 1 run. It must not be handed the shared blueprint path,
must not arm the blueprint gate, and must not be combinable with a requested size.
"""
import json
import shutil
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from pythonsrc.organizer.spec import OrganizerSpec, canonical_json
from pythonsrc.telemetry.db import TelemetryDB
from pythonsrc.telemetry.schema import VALID_SIZE_SOURCES, PrintJob
from server import app as app_module
from server.app import app

client = TestClient(app)
REPO_ROOT = Path(app_module.__file__).parent.parent

SPEC = {
    "archetype": "deck_box",
    "compartments": [{"contents": {"count": 100, "card": "standard", "sleeving": "double"}}],
    "lid": {"kind": "lift_off", "magnets": False, "height_mm": 15.0, "wall_mm": 1.2,
            "clearance_mm": 0.2, "top_mm": 2.0},
    "schema_version": 1,
}

DIVIDER_SPEC = {
    "archetype": "card_divider",
    "compartments": [{"contents": {"count": 100, "card": "standard", "sleeving": "double"}}],
    "divider": {"thickness_mm": 1.4, "tab_width_mm": 20.0, "tab_height_mm": 10.0,
                "tab_position": "centre"},
    "schema_version": 1,
}


def _request(**overrides):
    payload = {"prompt": "a 100-card commander deck box", "printer_id": "default"}
    payload.update(overrides)
    return app_module.JobRequest(**payload)


def _row_count():
    db = TelemetryDB()
    n = db.query_one("SELECT COUNT(*) AS n FROM print_job")["n"]
    db.close()
    return n


@pytest.fixture
def clean_inputs():
    """Remove the per-job input directory a spec job writes under the real `data/`."""
    created = []
    yield created
    for job_id in created:
        shutil.rmtree(REPO_ROOT / "data" / "inputs" / job_id, ignore_errors=True)


# ── the schema ────────────────────────────────────────────────────────────────

def test_spec_is_a_valid_size_source():
    assert "spec" in VALID_SIZE_SOURCES
    PrintJob(job_id="j", prompt="p", printer_id="d", printer_firmware="octoprint",
             slicer="cura", profile_name="default", started_at=None, completed_at=None,
             outcome="unknown", size_source="spec")


# ── the argv ──────────────────────────────────────────────────────────────────

def test_a_spec_path_reaches_the_pipeline_as_the_spec_flag():
    request = _request(spec=SPEC)
    request.spec_path = "/app/data/inputs/j1/spec.json"
    args = app_module._pipeline_args(request, skip_viz=True, skip_sculpt=True, profile=None)
    assert args[args.index("--spec") + 1] == "/app/data/inputs/j1/spec.json"


def test_a_spec_run_is_not_handed_the_shared_blueprint():
    """`--skip-visualizer --blueprint <shared>` is how a skip-Phase-1 run reuses an image
    someone put there. A spec run has no image; given that path it would snapshot another
    job's render and record its hash as this job's provenance."""
    request = _request(spec=SPEC)
    request.spec_path = "/app/data/inputs/j1/spec.json"
    args = app_module._pipeline_args(request, skip_viz=True, skip_sculpt=True, profile=None)
    assert "--blueprint" not in args
    assert "--skip-visualizer" not in args and "--skip-sculptor" not in args
    assert "--target-mm" not in args and "--scale-axis" not in args


def test_a_spec_request_skips_both_generative_phases_and_is_not_gated():
    skip_viz, skip_sculpt = app_module._phase_skips(_request(spec=SPEC))
    assert skip_viz is True and skip_sculpt is True


def test_without_a_spec_the_skips_come_from_the_request():
    skip_viz, skip_sculpt = app_module._phase_skips(_request())
    assert skip_viz is False and skip_sculpt is False
    skip_viz, skip_sculpt = app_module._phase_skips(_request(skip_visualizer=True))
    assert skip_viz is True


# ── the row ───────────────────────────────────────────────────────────────────

@patch("server.app._run_pipeline", new_callable=AsyncMock)
def test_a_spec_job_records_that_the_spec_decided_the_size(mock_run, printer_configured, clean_inputs):
    resp = client.post("/jobs", json={"prompt": "a deck box", "printer_id": "default", "spec": SPEC})
    assert resp.status_code == 202, resp.text
    job_id = resp.json()["job_id"]
    clean_inputs.append(job_id)

    db = TelemetryDB()
    job = db.get_job(job_id)
    db.close()
    assert job.size_source == "spec"
    assert job.requested_size_mm is None
    assert job.requested_scale_axis is None
    # Canonical, not as submitted: the request omitted `process` and `constraints`
    # and meant the schema's defaults by them, and a row that records the omission
    # describes a different part than the one the compiler built. See
    # `JobRequest._spec_is_valid`.
    assert job.request_params["spec"] == OrganizerSpec.from_dict(SPEC).to_dict()
    # 2,4 mm is `spec.ARCHETYPE_WALL_MM["deck_box"]`, resolved on construction —
    # the request named no wall, and a row that recorded none would describe a
    # part whose thickness nothing in the system states.
    assert job.request_params["spec"]["process"]["wall_mm"] == 2.4
    assert job.request_params["spec_path"] == f"/app/data/inputs/{job_id}/spec.json"


@patch("server.app._run_pipeline", new_callable=AsyncMock)
def test_the_spec_is_written_canonically_into_the_jobs_own_input_directory(mock_run, printer_configured, clean_inputs):
    resp = client.post("/jobs", json={"prompt": "a deck box", "printer_id": "default", "spec": SPEC})
    assert resp.status_code == 202, resp.text
    job_id = resp.json()["job_id"]
    clean_inputs.append(job_id)

    written = REPO_ROOT / "data" / "inputs" / job_id / "spec.json"
    assert written.exists()
    on_disk = OrganizerSpec.from_json(written.read_text())
    assert canonical_json(on_disk) == canonical_json(OrganizerSpec.from_dict(SPEC))
    # The subprocess was launched with a request that names the container path.
    launched = mock_run.call_args.args[1]
    assert launched.spec_path == f"/app/data/inputs/{job_id}/spec.json"


# ── refusals, on the model, before a row exists ───────────────────────────────

@patch("server.app._run_pipeline", new_callable=AsyncMock)
def test_a_spec_and_a_requested_size_are_refused_together(mock_run, printer_configured):
    before = _row_count()
    resp = client.post("/jobs", json={
        "prompt": "a deck box", "printer_id": "default", "spec": SPEC, "target_mm": 80.0,
    })
    assert resp.status_code == 422
    assert "spec" in resp.text and "target_mm" in resp.text
    assert _row_count() == before
    mock_run.assert_not_called()


@patch("server.app._run_pipeline", new_callable=AsyncMock)
def test_an_invalid_spec_is_refused_with_every_problem_named(mock_run, printer_configured):
    before = _row_count()
    bad = dict(SPEC, compartments=[], lid=dict(SPEC["lid"], clearance_mm=-1))
    resp = client.post("/jobs", json={"prompt": "a deck box", "printer_id": "default", "spec": bad})
    assert resp.status_code == 422
    assert "compartments" in resp.text and "clearance_mm" in resp.text
    assert _row_count() == before
    mock_run.assert_not_called()


@patch("server.app._run_pipeline", new_callable=AsyncMock)
def test_a_spec_the_archetype_refuses_is_a_422_not_a_failed_phase_2(mock_run, printer_configured):
    """`deck_box.validate` is not importable in the api-server image (it needs the
    kernel), so the server can only run the schema. It must at least not accept what
    the schema refuses."""
    before = _row_count()
    bad = dict(SPEC, archetype="dragon")
    resp = client.post("/jobs", json={"prompt": "a deck box", "printer_id": "default", "spec": bad})
    assert resp.status_code == 422
    assert "archetype" in resp.text
    assert _row_count() == before


@patch("server.app._run_pipeline", new_callable=AsyncMock)
def test_a_divider_spec_is_accepted_and_stored_canonically(mock_run, printer_configured, clean_inputs):
    """The api-server image installs neither trimesh nor manifold3d, so the second
    archetype's section has to validate on the stdlib-only schema like the first's —
    which is the reason `pythonsrc.organizer` imports nothing heavy."""
    resp = client.post("/jobs", json={
        "prompt": "a divider for my commander deck", "printer_id": "default",
        "spec": DIVIDER_SPEC,
    })
    assert resp.status_code == 202, resp.text
    job_id = resp.json()["job_id"]
    clean_inputs.append(job_id)

    db = TelemetryDB()
    job = db.get_job(job_id)
    db.close()
    assert job.size_source == "spec"
    stored = job.request_params["spec"]
    assert stored == OrganizerSpec.from_dict(DIVIDER_SPEC).to_dict()
    assert stored["divider"]["tab_position"] == "centre"
    # An absent optional section is omitted from the canonical form, not stored as null.
    assert "lid" not in stored
    written = REPO_ROOT / "data" / "inputs" / job_id / "spec.json"
    assert json.loads(written.read_text()) == stored


@patch("server.app._run_pipeline", new_callable=AsyncMock)
def test_an_invalid_divider_section_is_refused_with_its_path(mock_run, printer_configured):
    before = _row_count()
    bad = dict(DIVIDER_SPEC, divider=dict(DIVIDER_SPEC["divider"], tab_position="middle"))
    resp = client.post("/jobs", json={
        "prompt": "a divider", "printer_id": "default", "spec": bad,
    })
    assert resp.status_code == 422
    assert "tab_position" in resp.text
    assert _row_count() == before
    mock_run.assert_not_called()


def test_a_client_cannot_claim_spec_as_a_size_source():
    """Only the server derives it, from the presence of a spec."""
    with pytest.raises(ValidationError):
        _request(target_mm=80.0, size_source="spec")


# ── the composer's round trip ─────────────────────────────────────────────────

@patch("server.app._run_pipeline", new_callable=AsyncMock)
def test_what_the_composer_resolved_is_what_the_job_is_built_from(mock_run, printer_configured, clean_inputs):
    """The whole path the configurator walks, at the API level.

    A person fills the form, the composer posts the spec to `/organizer/resolve` and
    shows what comes back — the canonical spec, the resolved stack and its basis —
    and then submits. What they were shown and what the pipeline is handed have to be
    the same object, or the panel was describing a different part than the one that
    gets printed. They are one object because both ends run `OrganizerSpec.from_dict`
    and store the canonical form.
    """
    # What the form builds: every millimetre field blank, so the sections are bare.
    composed = {
        "archetype": "deck_box",
        "compartments": [{"contents": {"count": 100, "card": "standard", "sleeving": "double"}}],
        "lid": {"kind": "lift_off"},
        "process": {"fit_intent": "snug"},
        "schema_version": 1,
    }

    shown = client.post("/organizer/resolve", json={"spec": composed}).json()
    assert shown["schema_valid"] is True
    assert shown["stacks"][0]["stack_height_mm"] == 70.0     # 100 × 0,70 mm
    assert shown["spec"]["process"]["wall_mm"] == 2.4        # the archetype's own

    resp = client.post("/jobs", json={"printer_id": "default", "spec": composed})
    assert resp.status_code == 202, resp.text
    job_id = resp.json()["job_id"]
    clean_inputs.append(job_id)

    db = TelemetryDB()
    job = db.get_job(job_id)
    db.close()
    assert job.size_source == "spec"
    assert job.request_params["spec"] == shown["spec"]
    assert job.prompt == shown["label"]
    # And the spec the running view shows back is that same object. (Issue #66.)
    assert client.get(f"/jobs/{job_id}").json()["spec"] == shown["spec"]
    # Phases 1 and 2 are skipped and the pipeline is handed the file, not a size.
    launched = mock_run.call_args.args[1]
    args = app_module._pipeline_args(launched, skip_viz=True, skip_sculpt=True, profile=None)
    assert args[args.index("--spec") + 1] == f"/app/data/inputs/{job_id}/spec.json"
    assert "--target-mm" not in args


# ── the 422 reaches the field that caused it ──────────────────────────────────
#
# A composer can only put a refusal on the control that caused it if the path is a
# value. Splitting the joined sentence in the browser was the alternative, on a
# separator no test here could hold.

def _spec_error(resp):
    """The one 422 detail entry about the spec."""
    entries = [e for e in resp.json()["detail"] if e["loc"][-1] == "spec"]
    assert len(entries) == 1, resp.text
    return entries[0]


@patch("server.app._run_pipeline", new_callable=AsyncMock)
def test_a_refused_spec_carries_every_problem_with_its_dotted_path(mock_run, printer_configured):
    bad = dict(
        SPEC,
        compartments=[{"contents": {"count": 0, "card": "standard", "sleeving": "double"}}],
        lid=dict(SPEC["lid"], clearance_mm=-1),
    )
    resp = client.post("/jobs", json={"prompt": "a deck box", "printer_id": "default", "spec": bad})
    assert resp.status_code == 422
    problems = _spec_error(resp)["ctx"]["problems"]
    assert {p["path"] for p in problems} == {
        "spec.compartments[0].contents.count", "spec.lid.clearance_mm",
    }
    for problem in problems:
        assert problem["message"].startswith(problem["path"] + " ")


@patch("server.app._run_pipeline", new_callable=AsyncMock)
def test_the_joined_refusal_survives_beside_the_structured_one(mock_run, printer_configured):
    """A caller that reads only `msg` still gets the whole refusal — a spec is refused
    whole, and that must not depend on understanding the new field."""
    resp = client.post("/jobs", json={
        "prompt": "a deck box", "printer_id": "default", "spec": dict(SPEC, archetype="dragon"),
    })
    assert resp.status_code == 422
    entry = _spec_error(resp)
    assert "archetype" in entry["msg"]
    assert entry["msg"] == "invalid spec: " + "; ".join(
        p["message"] for p in entry["ctx"]["problems"]
    )


# ── the label a spec job is titled with ───────────────────────────────────────

@patch("server.app._run_pipeline", new_callable=AsyncMock)
def test_a_spec_job_with_no_prompt_is_titled_from_its_spec(mock_run, printer_configured, clean_inputs):
    """A spec job has no prompt — nobody typed words, the geometry is the spec's. The
    row's `prompt` is what every list and feed line names a job with, so the server
    derives a label from the spec rather than storing an empty column or inventing a
    sentence about a box nobody described."""
    resp = client.post("/jobs", json={"printer_id": "default", "spec": SPEC})
    assert resp.status_code == 202, resp.text
    job_id = resp.json()["job_id"]
    clean_inputs.append(job_id)

    db = TelemetryDB()
    job = db.get_job(job_id)
    db.close()
    assert job.prompt == "deck box · 100 double-sleeved standard cards"
    # And the request the gate's continuation replays says the same thing.
    assert job.request_params["prompt"] == job.prompt


@patch("server.app._run_pipeline", new_callable=AsyncMock)
def test_a_line_somebody_typed_beats_the_generated_one(mock_run, printer_configured, clean_inputs):
    resp = client.post("/jobs", json={
        "printer_id": "default", "spec": SPEC, "prompt": "Kess deck, birthday present",
    })
    assert resp.status_code == 202, resp.text
    job_id = resp.json()["job_id"]
    clean_inputs.append(job_id)

    db = TelemetryDB()
    job = db.get_job(job_id)
    db.close()
    assert job.prompt == "Kess deck, birthday present"


def test_a_job_with_neither_a_prompt_nor_a_spec_is_refused():
    """What `min_length=1` used to do, kept: a prompt job with no prompt has nothing to
    build and nothing to call itself."""
    with pytest.raises(ValidationError):
        _request(prompt="   ")


@pytest.mark.parametrize("body, id", [
    pytest.param({"printer_id": "default"}, "absent", id="prompt-absent"),
    pytest.param({"printer_id": "default", "prompt": ""}, "empty", id="prompt-empty"),
    pytest.param({"printer_id": "default", "prompt": "   "}, "blank", id="prompt-blank"),
])
def test_post_jobs_refuses_a_body_with_neither_a_prompt_nor_a_spec(body, id):
    """The rule over HTTP, where it is actually reached, and with no row written.

    `prompt` stopped being `min_length=1` so a spec job could carry none, and what
    replaced it is a model validator — which is a different thing to get wrong:
    `pytest.raises(Exception)` on a direct construction passes just as well when the
    validator raises `TypeError` from a bug in the label it builds. Three shapes,
    because `min_length=1` accepted `"   "` and `.strip()` does not, so the blank case
    is the one that changed.
    """
    before = _row_count()
    resp = client.post("/jobs", json=body)

    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert any(
        "prompt must not be empty unless a spec is supplied" in entry.get("msg", "")
        for entry in detail
    ), detail
    assert _row_count() == before, "a refused request must not leave a job row"
