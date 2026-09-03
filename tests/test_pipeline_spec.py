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
