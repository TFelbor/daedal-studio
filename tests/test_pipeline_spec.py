"""`pipeline.py --spec`: a compiled spec enters Phases 3–5 as a real run.

The seam already existed — `--skip-visualizer --skip-sculptor --mesh box.stl --no-scale`
— and `--spec` is that seam with the compile step in front of it. Three things must be
true of it, and each was once false of a neighbouring path: it must not land in the
`dev-` namespace (nothing in it is a fixture), it must not get an invented blueprint
(there was never an image), and it must not be combinable with a second source of
geometry or with hollowing (which cannot honour authored dimensions).
"""
import argparse
from pathlib import Path

import pytest

from pythonsrc.pipeline import (
    _apply_spec_mode,
    _build_parser,
    _job_outputs_dir,
    _should_install_reference_blueprint,
    _will_use_reference_assets,
)


def parse(*argv):
    return _apply_spec_mode(_build_parser().parse_args(list(argv)))


def test_spec_implies_the_three_flags_the_seam_is_made_of():
    args = parse("--spec", "deck.json")
    assert args.skip_visualizer and args.skip_sculptor and args.no_scale


def test_spec_needs_no_prompt():
    assert parse("--spec", "deck.json").prompt is None


def test_spec_refuses_a_second_source_of_geometry():
    with pytest.raises(ValueError) as exc:
        parse("--spec", "deck.json", "--mesh", "other.stl")
    assert "--mesh" in str(exc.value)


def test_spec_refuses_hollowing():
    with pytest.raises(ValueError) as exc:
        parse("--spec", "deck.json", "--hollow")
    assert "--hollow" in str(exc.value)


def test_without_spec_nothing_changes():
    args = parse("a vase")
    assert not args.skip_visualizer and not args.skip_sculptor and not args.no_scale


def _ns(**kw):
    base = dict(spec=None, mesh=None, skip_visualizer=False, skip_sculptor=False, job_id="j1", stop_after_phase=None)
    base.update(kw)
    return argparse.Namespace(**base)


def test_a_spec_run_never_uses_reference_assets(tmp_path):
    args = _ns(spec="deck.json", skip_visualizer=True, skip_sculptor=True)
    assert _will_use_reference_assets(args, tmp_path / "missing.png", [tmp_path / "missing.obj"]) is False


def test_a_spec_run_gets_no_invented_blueprint(tmp_path):
    args = _ns(spec="deck.json", skip_visualizer=True, skip_sculptor=True)
    assert _should_install_reference_blueprint(args, tmp_path / "missing.png") is False


def test_a_spec_run_writes_to_the_real_namespace(tmp_path):
    args = _ns(spec="deck.json", skip_visualizer=True, skip_sculptor=True)
    assert _job_outputs_dir(args, tmp_path, tmp_path / "missing.png") == tmp_path / "j1"


import json  # noqa: E402

from pythonsrc.organizer.archetypes import example_spec  # noqa: E402
from pythonsrc.organizer.spec import SpecError, dump_spec, spec_hash  # noqa: E402
from pythonsrc.pipeline import _compile_spec_phase  # noqa: E402


def test_the_compile_step_writes_the_three_artifacts_and_returns_the_mesh(tmp_path):
    spec = example_spec("deck_box")
    spec_path = dump_spec(spec, tmp_path / "in" / "deck.json")
    outputs = tmp_path / "out"
    mesh_path, result = _compile_spec_phase(_ns(spec=str(spec_path)), outputs)
    assert mesh_path == outputs / "compiled_mesh.stl" and mesh_path.stat().st_size > 84
    written = json.loads((outputs / "spec.json").read_text())
    assert written["archetype"] == "deck_box"
    features = json.loads((outputs / "compile_features.json").read_text())
    assert features["spec_sha256"] == spec_hash(spec) == result.spec_hash
    assert features["parts"] == ["body", "lid"]
    assert features["features"]["cavity_width_mm"] == 68.5


def test_a_bad_spec_is_a_spec_error_not_a_crash(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text('{"archetype": "deck_box", "compartments": [], "schema_version": 1}')
    with pytest.raises(SpecError):
        _compile_spec_phase(_ns(spec=str(bad)), tmp_path / "out")


def test_the_generation_record_names_the_compiler(tmp_path, monkeypatch):
    """`generation_model` records what actually made the mesh — here, the archetype."""
    import pythonsrc.pipeline as pipeline
    recorded = {}
    monkeypatch.setattr(pipeline, "_record_generation",
                        lambda args, **kw: recorded.update(kw))
    spec_path = dump_spec(example_spec("deck_box"), tmp_path / "deck.json")
    mesh_path, result = _compile_spec_phase(_ns(spec=str(spec_path)), tmp_path / "out")
    pipeline._record_spec_generation(_ns(spec=str(spec_path)), result, duration_s=0.01)
    assert recorded["model"] == "organizer/deck_box"
    assert recorded["model_version"] == "1"
    assert recorded["backend"] == "local"
    assert recorded["params"]["spec_sha256"] == result.spec_hash
    assert recorded["cost_eur"] is None


# ── The assert half: Phase 3 checks a compiled mesh rather than repairing it ──────
#
# The scaling half of N1 is `--no-scale`. This is the other half: a spec run's Phase 3
# runs `Engineer.process(repair_mode="assert")` and then measures the engineered mesh
# against the spec's own features, writing the record beside the mesh *before* deciding,
# so a failure is inspectable, and failing Phase 3 when anything is out of tolerance.

import trimesh  # noqa: E402

from pythonsrc.organizer.compiler import MeasureError  # noqa: E402
from pythonsrc.pipeline import _assert_spec_dimensions, _repair_mode_for  # noqa: E402


def test_a_spec_run_drops_a_blueprint_it_is_handed():
    """The server's mps_native strategy hardcodes `--blueprint <shared path>`. A spec run
    has no image, and reading that path would snapshot whichever job's render sits
    there and stamp its hash as this job's Phase 1 provenance."""
    args = parse("--spec", "deck.json", "--blueprint", "/app/data/inputs/blueprint.png")
    assert args.blueprint is None


def test_phase_3_asserts_for_a_spec_and_repairs_for_everything_else():
    assert _repair_mode_for(_ns(spec="deck.json")) == "assert"
    assert _repair_mode_for(_ns(spec=None)) == "repair"
    assert _repair_mode_for(_ns(spec=None, mesh="own.stl")) == "repair"


def _compiled_and_engineered(tmp_path):
    from pythonsrc.engineer import Engineer
    spec_path = dump_spec(example_spec("deck_box"), tmp_path / "in" / "deck.json")
    outputs = tmp_path / "out"
    mesh_path, result = _compile_spec_phase(_ns(spec=str(spec_path)), outputs)
    engineered = outputs / "engineered_mesh.obj"
    eng = Engineer()
    eng.process(input_path=mesh_path, output_path=engineered, target_mm=None, repair_mode="assert")
    return outputs, result, engineered, eng


def test_the_dimension_check_writes_its_report_and_says_so(tmp_path, capsys):
    outputs, result, engineered, eng = _compiled_and_engineered(tmp_path)
    report = _assert_spec_dimensions(result, engineered, outputs)
    assert report["within_tolerance"] is True
    assert report["features_checked"] == 19 and report["features_within"] == 19
    written = json.loads((outputs / "dimension_report.json").read_text())
    assert written == report
    out = capsys.readouterr().out
    assert "[DS] Dimensions: 19/19" in out and "±0.05 mm" in out
    # Six decimals: the noise floor of a float32 STL is ~1e-5 mm, and a line that
    # rounds it to "0.0000 mm" reports a measurement that was not made.
    import re
    assert re.search(r"max error \d\.\d{6} mm", out), out


def test_the_dimension_check_fails_phase_3_on_drift_and_still_writes_the_report(tmp_path, capsys):
    outputs, result, engineered, eng = _compiled_and_engineered(tmp_path)
    drifted = trimesh.load(str(engineered), force="mesh")
    drifted.apply_scale(1.002)
    drifted.export(str(engineered))
    with pytest.raises(MeasureError) as exc:
        _assert_spec_dimensions(result, engineered, outputs)
    assert "cavity_width_mm" in str(exc.value)
    written = json.loads((outputs / "dimension_report.json").read_text())
    assert written["within_tolerance"] is False
    assert "cavity_width_mm" in written["out_of_tolerance"]
    out = capsys.readouterr().out
    assert "✗ cavity_width_mm" in out


def test_the_dimension_check_reads_the_spec_phase_2_recorded_not_the_argument(tmp_path):
    """`spec.json` in the job directory is what was compiled; the check must measure
    against that, so a spec file edited between phases cannot move the goalposts."""
    outputs, result, engineered, eng = _compiled_and_engineered(tmp_path)
    (outputs / "spec.json").unlink()
    with pytest.raises(FileNotFoundError):
        _assert_spec_dimensions(result, engineered, outputs)
