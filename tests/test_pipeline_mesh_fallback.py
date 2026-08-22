"""Guard on Phase 2 having no fallback geometry.

`--skip-sculptor` with no mesh on disk used to export a 50mm cube and carry on.
That is the worst available outcome, because nothing downstream can tell the cube
apart from the model that was asked for: it is watertight, it has no overhangs, it
sits flat on the plate, so repair passes it, printability scores it well, the
slicer produces clean G-code and Phase 5 dispatches it to the printer. The failure
surfaced as filament spent on a cube — and as telemetry rows whose mesh features
describe a box under a prompt that asked for something else.

The stand-in *blueprint* is deliberately still there (see
`test_pipeline_blueprint.py`). An image is input to a phase that names its own
model and refuses to pay for a placeholder; a mesh is the deliverable.
"""

from pathlib import Path

import pytest

import pythonsrc.pipeline as pipeline
from pythonsrc.pipeline import _build_parser, run


@pytest.fixture(autouse=True)
def isolated_dirs(tmp_path, monkeypatch):
    """Keep `run()` out of the repo's `data/` tree.

    `run()` creates `INPUTS_DIR`/`OUTPUTS_DIR` and, for a job id, snapshots the
    shared blueprint into a per-job directory — so an unredirected test leaves a
    stray `data/outputs/<job>/` behind. A stray file there is not inert: the
    server's artifact lookup falls back to the flat layout, so a leftover
    `printability.json` makes an unrelated job answer 200 where it owes a 404.
    """
    monkeypatch.setattr(pipeline, "INPUTS_DIR", str(tmp_path / "inputs"))
    monkeypatch.setattr(pipeline, "OUTPUTS_DIR", str(tmp_path / "outputs"))
    monkeypatch.setenv("P2P_LOGS_DIR", str(tmp_path / "logs"))


def _args(mesh: Path, **overrides):
    parsed = _build_parser().parse_args(
        ["--skip-visualizer", "--skip-sculptor", "--mesh", str(mesh)]
    )
    for key, value in overrides.items():
        setattr(parsed, key, value)
    return parsed


def test_a_missing_mesh_stops_the_pipeline(tmp_path):
    missing = tmp_path / "raw_mesh.obj"

    with pytest.raises(SystemExit) as exc:
        run(_args(missing))

    assert exc.value.code == 1
    assert not missing.exists()


def test_nothing_is_written_where_the_mesh_should_be(tmp_path, capsys):
    """The point is not just the exit code: no geometry may be invented."""
    missing = tmp_path / "raw_mesh.obj"

    with pytest.raises(SystemExit):
        run(_args(missing))

    assert list(tmp_path.glob("*.obj")) == []
    assert list(tmp_path.glob("*.stl")) == []
    out = capsys.readouterr().out
    assert "--skip-sculptor" in out
    assert "PHASE 3" not in out


def test_the_failure_is_recorded_against_phase_2(tmp_path, monkeypatch):
    """A job that dies here must not look like a job that simply skipped Phase 2."""
    import json

    logs = tmp_path / "logs"
    job_id = "test-missing-mesh"
    # Set the way the entrypoint sets it — `_write_status` keys off the module
    # global, not off the parsed arguments.
    monkeypatch.setattr(pipeline, "CURRENT_JOB_ID", job_id)

    with pytest.raises(SystemExit):
        run(_args(tmp_path / "raw_mesh.obj", job_id=job_id))

    records = [
        json.loads(line)
        for line in (logs / f"{job_id}.status").read_text().splitlines()
        if line.strip()
    ]
    assert any(r["phase"] == 2 and r["status"] == "error" for r in records)
