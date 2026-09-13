"""Polling cost of GET /jobs/{id}, before and after the spec fields.

Not part of the suite — run explicitly:
    pytest tests/_bench_poll.py -s -q

"Before" is the same endpoint with `job_spec_summary` stubbed to the all-None dict it
returns for a prompt job, i.e. exactly the work this change added and nothing else.
"""
import shutil
import statistics
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from pythonsrc.telemetry.db import TelemetryDB
from server import app as app_module
from server.app import app

client = TestClient(app)
ROOT = Path(app_module.__file__).parent.parent
SPEC = {
    "archetype": "deck_box",
    "compartments": [{"contents": {"count": 100, "card": "standard", "sleeving": "double"}}],
    "lid": {"kind": "lift_off", "magnets": False, "height_mm": 15.0, "wall_mm": 1.2,
            "clearance_mm": 0.2, "top_mm": 2.0},
    "schema_version": 1,
}
EMPTY = {"spec": None, "spec_hash": None, "archetype": None,
         "archetype_version": None, "dimension_check": None}


def _make(payload):
    with patch("server.app._run_pipeline", new_callable=AsyncMock):
        resp = client.post("/jobs", json=payload)
    assert resp.status_code == 202, resp.text
    return resp.json()["job_id"]


def _timed(job_id, n=300):
    for _ in range(30):
        client.get(f"/jobs/{job_id}")
    samples = []
    for _ in range(n):
        start = time.perf_counter()
        client.get(f"/jobs/{job_id}")
        samples.append((time.perf_counter() - start) * 1000)
    return statistics.median(samples)


def test_polling_cost(printer_configured):
    spec_id = _make({"prompt": "a deck box", "printer_id": "default", "spec": SPEC})
    prompt_id = _make({"prompt": "a vase", "printer_id": "default"})

    db = TelemetryDB()
    db.update_job_generation(spec_id, params={
        "archetype": "deck_box", "archetype_version": "2", "spec_sha256": "a" * 64})
    # 26 features, which is what a deck box measures since issue #80 — the payload this
    # benchmark weighs has to be the one the endpoint actually serves.
    db.update_job_mesh_lineage(spec_id, repair_report={"dimension_check": {
        "tolerance_mm": 0.05, "within_tolerance": True, "features_checked": 26,
        "features_within": 26, "max_abs_error_mm": 0.002,
        "features": {f"f{i}_mm": {"designed_mm": 1.0, "measured_mm": 1.0, "error_mm": 0.0}
                     for i in range(26)},
        "missing": [], "out_of_tolerance": []}})
    db.close()

    real = app_module.job_spec_summary
    try:
        app_module.job_spec_summary = lambda job: EMPTY
        before_spec = _timed(spec_id)
        before_prompt = _timed(prompt_id)
    finally:
        app_module.job_spec_summary = real
    after_spec = _timed(spec_id)
    after_prompt = _timed(prompt_id)

    print(f"\nspec job   before {before_spec:.3f} ms  after {after_spec:.3f} ms  "
          f"(+{after_spec - before_spec:.3f} ms)")
    print(f"prompt job before {before_prompt:.3f} ms  after {after_prompt:.3f} ms  "
          f"(+{after_prompt - before_prompt:.3f} ms)")

    for jid in (spec_id, prompt_id):
        shutil.rmtree(ROOT / "data" / "inputs" / jid, ignore_errors=True)
