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
