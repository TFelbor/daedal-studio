"""The spec, its hash and the dimension check reach the UI on `GET /jobs/{id}`.

`POST /jobs` has accepted a spec since 2026-09-03 and the pipeline has compiled and
measured it since, but none of it came back: `GET /jobs/{id}` named no spec field, so
`specFromJob` was always null and every spec panel in the app showed the
"no spec" sentence over a job that had one. This binds the two halves.

Three things are asserted that are easy to get wrong and invisible when they are:

- **A prompt job carries nulls, not an empty object.** A panel that renders a spec
  with no rows is indistinguishable from a compiled part whose numbers went missing.
- **The row is authoritative and the file is a fallback**, so a poll costs no I/O
  and a cleared `data/outputs/` does not erase a job's parameters.
- **The only fit verdict on the endpoint is the measured one.** There is deliberately
  no computed-fits field: a badge with no measurement behind it is the exact failure
  the Fits Check exists to prevent.
"""
import json
import re
import shutil
from dataclasses import fields
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from pythonsrc.organizer.compiler import DimensionReport
from pythonsrc.organizer.spec import Constraints, Lid, OrganizerSpec, Process, spec_hash
from pythonsrc.telemetry.db import TelemetryDB
from server import app as app_module
from server.app import SPEC_ARTIFACTS, app, job_spec_summary

client = TestClient(app)
REPO_ROOT = Path(app_module.__file__).parent.parent

SPEC = {
    "archetype": "deck_box",
    "compartments": [{"contents": {"count": 100, "card": "standard", "sleeving": "double"}}],
    "lid": {"kind": "lift_off", "magnets": False, "height_mm": 15.0, "wall_mm": 1.2,
            "clearance_mm": 0.2, "top_mm": 2.0},
    "schema_version": 1,
}
CANONICAL = OrganizerSpec.from_dict(SPEC).to_dict()

#: A dimension check as `DimensionReport.to_dict` writes it, trimmed to two features.
DIMENSION_CHECK = {
    "tolerance_mm": 0.05,
    "within_tolerance": True,
    "features_checked": 2,
    "features_within": 2,
    "max_abs_error_mm": 0.002,
    "features": {
        "external_width_mm": {"designed_mm": 76.0, "measured_mm": 76.002, "error_mm": 0.002},
        "wall_mm": {"designed_mm": 2.8, "measured_mm": 2.8, "error_mm": 0.0},
    },
    "missing": [],
    "out_of_tolerance": [],
}

COMPILE_FEATURES = {
    "archetype": "deck_box",
    "archetype_version": "1",
    "spec_sha256": spec_hash(OrganizerSpec.from_dict(SPEC)),
    "parts": ["body", "lid"],
    "features": {"external_width_mm": 76.0, "wall_mm": 2.8},
}


@pytest.fixture
def spec_job(printer_configured):
    """A job created through `POST /jobs` with a spec, cleaned up afterwards."""
    created: list[str] = []

    def make(spec: dict = SPEC) -> str:
        with patch("server.app._run_pipeline", new_callable=AsyncMock):
            resp = client.post(
                "/jobs",
                json={"prompt": "a 100-card deck box", "printer_id": "default", "spec": spec},
            )
        assert resp.status_code == 202, resp.text
        job_id = resp.json()["job_id"]
        created.append(job_id)
        return job_id

    yield make
    for job_id in created:
        shutil.rmtree(REPO_ROOT / "data" / "inputs" / job_id, ignore_errors=True)
        shutil.rmtree(REPO_ROOT / "data" / "outputs" / job_id, ignore_errors=True)


@pytest.fixture
def prompt_job(printer_configured):
    """A job created the ordinary way, with no spec."""
    created: list[str] = []
    with patch("server.app._run_pipeline", new_callable=AsyncMock):
        resp = client.post("/jobs", json={"prompt": "a vase", "printer_id": "default"})
    assert resp.status_code == 202, resp.text
    job_id = resp.json()["job_id"]
    created.append(job_id)
    yield job_id
    for jid in created:
        shutil.rmtree(REPO_ROOT / "data" / "inputs" / jid, ignore_errors=True)


def _compile(job_id: str, *, version: str = "1") -> None:
    """What Phase 2 records for a spec run."""
    db = TelemetryDB()
    db.update_job_generation(
        job_id,
        model="organizer/deck_box",
        model_version=version,
        backend="local",
        params={"schema_version": 1, **COMPILE_FEATURES, "archetype_version": version},
    )
    db.close()


def _measure(job_id: str, check: dict = DIMENSION_CHECK) -> None:
    """What Phase 3 records for a spec run — on `repair_report`, no new column."""
    db = TelemetryDB()
    db.update_job_mesh_lineage(job_id, repair_report={"repair_method": "asserted",
                                                      "dimension_check": check})
    db.close()


def _outputs(job_id: str) -> Path:
    path = REPO_ROOT / "data" / "outputs" / job_id
    path.mkdir(parents=True, exist_ok=True)
    return path


# ── GET /jobs/{id} ────────────────────────────────────────────────────────────

def test_a_spec_job_carries_its_spec_hash_archetype_and_dimension_check(spec_job):
    job_id = spec_job()
    _compile(job_id)
    _measure(job_id)

    body = client.get(f"/jobs/{job_id}").json()
    assert body["spec"] == CANONICAL
    assert body["spec_hash"] == COMPILE_FEATURES["spec_sha256"]
    assert body["archetype"] == "deck_box"
    assert body["archetype_version"] == "1"
    assert body["dimension_check"] == DIMENSION_CHECK


def test_a_prompt_job_carries_nulls(prompt_job):
    """Not an empty object: a spec panel with no rows reads as a compiled part whose
    numbers went missing, which is the opposite of what happened."""
    body = client.get(f"/jobs/{prompt_job}").json()
    for key in ("spec", "spec_hash", "archetype", "archetype_version", "dimension_check"):
        assert body[key] is None, f"{key} should be null for a prompt job"


def test_the_spec_is_carried_canonically_so_no_field_is_missing(spec_job):
    """The submitted spec named no `process` at all. A row that records the omission
    describes a part with no wall thickness, and the panel renders undefined.

    The two archetype-specific *sections* are the deliberate exception: an absent one is
    omitted rather than written as null, so that adding an archetype's section does not
    move the `spec_hash` of every spec that never mentioned it. This is a deck box, so
    `lid` is there and `divider` is not, and `RawSpec` declares both optional."""
    from pythonsrc.organizer.spec import _OPTIONAL_SECTIONS
    body = client.get(f"/jobs/{spec_job()}").json()
    assert body["spec"]["process"]["wall_mm"] == 2.8
    assert body["spec"]["constraints"] == {"max_external_mm": None, "fit_margin_mm": 2.0}
    required = {f.name for f in fields(OrganizerSpec)} - set(_OPTIONAL_SECTIONS)
    assert required <= set(body["spec"])
    assert "lid" in body["spec"] and "divider" not in body["spec"]
    assert set(body["spec"]) <= {f.name for f in fields(OrganizerSpec)}


def test_before_phase_2_the_hash_is_computed_and_the_version_is_null(spec_job):
    """A spec job is answerable the moment it is created. The version is not invented:
    nothing has compiled the spec yet, so no archetype version applies to it."""
    body = client.get(f"/jobs/{spec_job()}").json()
    assert body["spec_hash"] == spec_hash(OrganizerSpec.from_dict(SPEC))
    assert body["archetype"] == "deck_box"
    assert body["archetype_version"] is None
    assert body["dimension_check"] is None


def test_the_compiled_hash_wins_over_the_computed_one(spec_job):
    """`generation_params["spec_sha256"]` is the hash of the spec the compiler
    actually received. When the two could ever disagree, what ran is the fact."""
    job_id = spec_job()
    db = TelemetryDB()
    db.update_job_generation(job_id, params={"archetype": "deck_box", "spec_sha256": "deadbeef"})
    db.close()
    assert client.get(f"/jobs/{job_id}").json()["spec_hash"] == "deadbeef"


def test_the_row_is_read_not_the_output_directory(spec_job):
    """The poll must cost no file I/O. A `spec.json` that disagrees with the row is
    ignored — proof the endpoint never opened it."""
    job_id = spec_job()
    (_outputs(job_id) / "spec.json").write_text(json.dumps(dict(CANONICAL, schema_version=99)))
    assert client.get(f"/jobs/{job_id}").json()["spec"] == CANONICAL


def test_a_row_with_no_spec_falls_back_to_the_artifact(spec_job):
    """A row whose `request_params` predates the field, or one a CLI `--spec` run
    attached itself to. The output directory is what it has."""
    job_id = spec_job()
    (_outputs(job_id) / "spec.json").write_text(json.dumps(CANONICAL))
    _compile(job_id)

    db = TelemetryDB()
    job = db.get_job(job_id)
    db.close()
    job.request_params = {}

    summary = job_spec_summary(job)
    assert summary["spec"] == CANONICAL
    assert summary["archetype"] == "deck_box"


def test_a_row_with_no_spec_and_no_artifact_is_not_a_spec_job(spec_job):
    job_id = spec_job()
    _compile(job_id)

    db = TelemetryDB()
    job = db.get_job(job_id)
    db.close()
    job.request_params = {}

    assert job_spec_summary(job)["spec"] is None


def test_a_failed_dimension_check_is_carried_whole(spec_job):
    """The remedy the UI shows is the list of features that missed; dropping it
    leaves a red badge with nothing to act on."""
    job_id = spec_job()
    failed = dict(DIMENSION_CHECK, within_tolerance=False, features_within=1,
                  max_abs_error_mm=0.31, out_of_tolerance=["external_width_mm"])
    _measure(job_id, failed)

    body = client.get(f"/jobs/{job_id}").json()
    assert body["dimension_check"]["within_tolerance"] is False
    assert body["dimension_check"]["out_of_tolerance"] == ["external_width_mm"]


def test_the_endpoint_offers_no_unmeasured_fit_verdict(spec_job):
    """There is no `fits` field, and there must not be one. The mm arithmetic the
    composer will show is computed from a spec, not measured off a mesh; putting it
    beside a measured check on one endpoint is how a fabricated badge gets shipped."""
    body = client.get(f"/jobs/{spec_job()}").json()
    assert "fits" not in body


# ── GET /jobs/{id}/spec ───────────────────────────────────────────────────────

def test_the_spec_endpoint_carries_both_documents(spec_job):
    job_id = spec_job()
    _compile(job_id)
    _measure(job_id)
    outputs = _outputs(job_id)
    (outputs / "compile_features.json").write_text(json.dumps(COMPILE_FEATURES))
    (outputs / "dimension_report.json").write_text(json.dumps(DIMENSION_CHECK))

    body = client.get(f"/jobs/{job_id}/spec").json()
    assert body["job_id"] == job_id
    assert body["spec"] == CANONICAL
    assert body["compile_features"] == COMPILE_FEATURES
    assert body["dimension_report"] == DIMENSION_CHECK
    assert body["dimension_check"] == DIMENSION_CHECK


def test_the_spec_endpoint_answers_before_the_documents_exist(spec_job):
    body = client.get(f"/jobs/{spec_job()}/spec").json()
    assert body["spec"] == CANONICAL
    assert body["compile_features"] is None
    assert body["dimension_report"] is None


def test_the_spec_endpoint_404s_for_a_prompt_job(prompt_job):
    """Not an empty 200: that reads as "compiled, and every number is missing"."""
    resp = client.get(f"/jobs/{prompt_job}/spec")
    assert resp.status_code == 404
    assert "spec" in resp.json()["detail"].lower()


def test_the_spec_endpoint_404s_for_an_unknown_job():
    assert client.get("/jobs/does-not-exist/spec").status_code == 404


def test_an_unreadable_artifact_is_null_not_a_500(spec_job):
    job_id = spec_job()
    (_outputs(job_id) / "dimension_report.json").write_text("{not json")
    body = client.get(f"/jobs/{job_id}/spec")
    assert body.status_code == 200
    assert body.json()["dimension_report"] is None


def test_the_polled_endpoint_carries_neither_large_document(spec_job):
    """`compile_features.json` and `dimension_report.json` are read once and are far
    larger than the four values the panels re-render on every tick. The `/provenance`
    precedent: what is polled stays small."""
    job_id = spec_job()
    _compile(job_id)
    body = client.get(f"/jobs/{job_id}").json()
    assert "compile_features" not in body
    assert "dimension_report" not in body


def test_the_served_artifacts_are_the_ones_a_spec_run_writes():
    """`pipeline.py` writes exactly these names; a rename here serves nothing and
    says nothing."""
    pipeline = (REPO_ROOT / "pythonsrc" / "pipeline.py").read_text()
    for filename in SPEC_ARTIFACTS.values():
        assert f'"{filename}"' in pipeline, (
            f"{filename} is served by GET /jobs/{{id}}/spec but pipeline.py does not "
            "write it under that name."
        )


# ── the two sides of the wire ─────────────────────────────────────────────────
#
# There is no frontend test runner in this repo, so these read the sources as text —
# the guard `tests/test_download_formats.py` and `tests/test_ip_notice.py` use. Weak
# is enough: the failures here are a panel rendering `undefined mm` and a fit badge
# appearing with nothing behind it, neither of which is subtle once it happens and
# both of which are invisible in a diff.

CLIENT_TS = REPO_ROOT / "web" / "src" / "api" / "client.ts"
SPEC_TS = REPO_ROOT / "web" / "src" / "organizer" / "spec.ts"
FITS_TSX = REPO_ROOT / "web" / "src" / "components" / "FitsCheck.tsx"


def _interface(text: str, name: str) -> str:
    match = re.search(rf"export interface {name} \{{(.*?)\n\}}", text, re.S)
    assert match, f"{name} is no longer declared in the client"
    return match.group(1)


def test_the_typescript_job_response_names_every_field_the_server_sends():
    text = CLIENT_TS.read_text()
    body = _interface(text, "JobStatusResponse")
    for key in ("spec", "spec_hash", "archetype", "archetype_version", "dimension_check"):
        assert re.search(rf"\n  {key}\??:", body), (
            f"`{key}` is on JobStatusResponse in the server and not in the client."
        )


def test_the_raw_spec_interface_matches_the_python_schema():
    """The panel reads these field names off the wire. One rename on either side and
    a row renders `undefined mm` — a plausible-looking blank where a millimetre was."""
    body = _interface(CLIENT_TS.read_text(), "RawSpec")
    declared = set(re.findall(r"^  (\w+)\??:", body, re.M))
    assert declared == {f.name for f in fields(OrganizerSpec)}

    for cls in (Process, Lid, Constraints):
        for f in fields(cls):
            assert re.search(rf"\n    {f.name}\??:", body), (
                f"RawSpec does not declare {cls.__name__}.{f.name}."
            )


def test_the_panel_shows_the_fit_margin_when_the_spec_carries_one():
    """The margin decides whether a part fits, so a table that lists the stated
    limit and not the two millimetres taken off it shows a number nothing was
    compared against — the mystery the margin's own error text exists to avoid."""
    text = SPEC_TS.read_text()
    assert "fit_margin_mm" in text, "specFromJob no longer reads constraints.fit_margin_mm."
    assert "'Fit margin'" in text


def test_the_dimension_check_interface_matches_the_report_the_pipeline_writes():
    body = _interface(CLIENT_TS.read_text(), "DimensionCheck")
    declared = set(re.findall(r"^  (\w+)\??:", body, re.M))
    written = set(DimensionReport(tolerance_mm=0.05, features={}).to_dict())
    assert declared == written


def test_spec_from_job_reads_the_field_the_server_sends():
    text = SPEC_TS.read_text()
    assert "job.spec" in text, "specFromJob no longer reads the spec off the job."
    assert "job.dimension_check" in text
    assert "job.spec_hash" in text
    assert "job.archetype_version" in text


def test_the_only_fit_verdict_in_the_ui_is_the_measured_one():
    """`measuredFit` is the sole constructor of a `FitsResult`. A second one — a
    stack sum computed in the browser from a spec nothing has compiled — is the
    fabricated badge CLAUDE.md forbids, and it would enter here."""
    text = SPEC_TS.read_text()
    assert "export function measuredFit" in text
    constructors = re.findall(r"^export function (\w+)[^\n]*: FitsResult", text, re.M)
    assert constructors == ["measuredFit"], (
        f"Something other than measuredFit produces a fit verdict: {constructors}. "
        "A verdict that was not measured must not reach FitsCheck."
    )
    assert "check.within_tolerance" in text, (
        "measuredFit no longer reads the measured verdict."
    )


def test_the_three_absences_have_three_sentences():
    """A generative job, an uncomposed composer and an unmeasured spec are three
    different gaps. One sentence for all of them tells two of the three a lie."""
    text = SPEC_TS.read_text()
    for name in ("NO_SPEC_REASON", "UNCOMPOSED_SPEC_REASON", "UNMEASURED_FIT_REASON"):
        assert f"export const {name} =" in text
    assert "not wired up yet" not in text, (
        "NO_SPEC_REASON still claims the parametric engine is unwired. It is wired: "
        "a spec job now carries its spec."
    )


def test_the_fit_badge_can_say_what_it_actually_checked():
    """A dimension check compares a mesh to its spec. Labelling it "Fits" claims a
    stack was measured against a cavity, which nothing did."""
    assert "fits.verdict ??" in FITS_TSX.read_text()
    assert "Dimensions verified" in SPEC_TS.read_text()
