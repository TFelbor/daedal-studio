"""Guards on Phase 3 leaving an authored mesh at the size it was authored in.

`Engineer.process` scaled **unconditionally**. `target_mm` defaults to 50.0, so a
mesh whose every dimension was already fixed in millimetres — one compiled from a
parametric spec rather than reconstructed from an image — left Phase 3 with its
*height* set to 50 mm and every other dimension dragged along by the same factor.

The failure is total and completely invisible downstream. The mesh is still
watertight, `printability` still scores it, CuraEngine still slices it and the
printer still prints it. Nothing in the pipeline, the report or the telemetry row
says a dimension changed. The only symptom is a part that does not fit, discovered
by a person eight hours later.

It is reachable today, without any new code: `--skip-visualizer --skip-sculptor
--mesh box.stl` is the documented way to hand Phase 3 a mesh of your own, and that
path is deliberately *not* a fixture run — its outputs land in the real namespace.

So `target_mm=None` means "these dimensions are final", and the tests below pin
both halves: that it preserves, and that omitting it still scales exactly as before.
"""

import numpy as np
import pytest
import trimesh

from pythonsrc.engineer import Engineer

# Repair hands vertices to the manifold kernel as float32, so a round-trip is not
# bit-exact. Sub-micron on a part this size — three orders of magnitude below the
# 0.15 mm the PRD asks for, and far below one layer height.
TOL_MM = 1e-3

#: Deliberately not a cube and deliberately not 50 mm on any axis: a cube cannot
#: show which extent was scaled, and a 50 mm extent would make the bug invisible.
BOX_MM = (62.0, 94.0, 31.5)


def _authored_box(tmp_path):
    """A mesh standing in for parametric output: exact dimensions, watertight,
    single-component, nothing for repair to do."""
    mesh = trimesh.creation.box(extents=BOX_MM)
    path = tmp_path / "authored.stl"
    mesh.export(str(path))
    return path


def _extent(path):
    mesh = trimesh.load(str(path), force="mesh")
    return mesh.bounds[1] - mesh.bounds[0]


def test_none_preserves_every_dimension(tmp_path):
    """The fix. All three extents survive, not just the one being measured."""
    out = tmp_path / "out.obj"
    Engineer().process(input_path=_authored_box(tmp_path), output_path=out, target_mm=None)

    assert _extent(out) == pytest.approx(np.array(BOX_MM), abs=TOL_MM)


def test_the_default_still_scales_to_height(tmp_path):
    """The regression guard. Phase 2 emits geometry in an arbitrary scale and has no
    dimensions of its own, so every existing caller must be untouched: 50.0 stays
    the default and it still sizes the *height*."""
    out = tmp_path / "out.obj"
    Engineer().process(input_path=_authored_box(tmp_path), output_path=out)

    extent = _extent(out)
    assert extent[2] == pytest.approx(50.0, abs=TOL_MM)
    # And uniformly, so the part is not distorted.
    assert extent[0] / extent[2] == pytest.approx(BOX_MM[0] / BOX_MM[2], rel=1e-4)


def test_the_bug_this_fixes(tmp_path):
    """States the defect as an assertion rather than only in prose: the *old*
    behaviour on an authored mesh, so that if the conditional is ever removed this
    file explains what broke and why it mattered."""
    out = tmp_path / "out.obj"
    Engineer().process(input_path=_authored_box(tmp_path), output_path=out, target_mm=50.0)

    # 31.5 mm tall becomes 50 mm tall — a 1.59× enlargement of a part whose
    # dimensions were the point of it.
    assert _extent(out)[2] == pytest.approx(50.0, abs=TOL_MM)
    assert _extent(out)[2] != pytest.approx(BOX_MM[2], abs=0.5)


def test_none_overrides_the_instance_default(tmp_path):
    """`target_dimensions` is set on the Engineer, not per call. A caller stating
    that the mesh is authoritative must win over a constructor default it may not
    even know about — otherwise the flag is silently ignored in exactly the
    configuration where it matters."""
    out = tmp_path / "out.obj"
    eng = Engineer()
    eng.target_dimensions = 120.0
    eng.process(input_path=_authored_box(tmp_path), output_path=out, target_mm=None)

    assert _extent(out) == pytest.approx(np.array(BOX_MM), abs=TOL_MM)


def test_hollow_is_refused_rather_than_silently_wrong(tmp_path):
    """Hollowing voxelises at a `wall_thickness` pitch, which is why the hollow path
    re-scales afterwards. So there is no way to honour authored dimensions *and*
    hollow, and both remedies are wrong — re-scaling discards the dimensions,
    skipping the re-scale ships the wrong size with its base under the plate.
    Refuse, at the top, before any work."""
    with pytest.raises(ValueError, match="hollow"):
        Engineer().process(
            input_path=_authored_box(tmp_path),
            output_path=tmp_path / "out.obj",
            target_mm=None,
            hollow=True,
        )


def test_report_distinguishes_preserved_from_degenerate(tmp_path):
    """`scale_axis="none"` already means "a scale was asked for and there was no
    extent to apply it to". Reusing it for "the caller declared the mesh final"
    would make an honoured request indistinguishable from a degenerate mesh, so
    `scale_applied` is written separately and unconditionally."""
    out = tmp_path / "out.obj"
    eng = Engineer()
    eng.process(input_path=_authored_box(tmp_path), output_path=out, target_mm=None)

    report = eng.last_report
    assert report["scale_applied"] is False
    assert report["scale_axis"] == "preserved"
    # Not 50.0. A recorded default is indistinguishable from a chosen value — the
    # same reason `requested_size_mm` is NULL when nobody chose.
    assert report["target_mm"] is None
    assert report["achieved_extent_mm"] == pytest.approx(np.array(BOX_MM), abs=TOL_MM)


def test_report_still_describes_a_real_scale(tmp_path):
    """The other side of the same key, so `scale_applied` cannot quietly become a
    constant."""
    out = tmp_path / "out.obj"
    eng = Engineer()
    eng.process(input_path=_authored_box(tmp_path), output_path=out, target_mm=40.0)

    report = eng.last_report
    assert report["scale_applied"] is True
    assert report["scale_axis"] == "height"
    assert report["target_mm"] == pytest.approx(40.0)


def test_pipeline_exposes_the_flag_and_defaults_it_off(tmp_path):
    """The seam is a CLI flag, and the CLI is how a mesh of one's own reaches Phase
    3 at all. Parsed here rather than asserted in prose, because a flag that is
    added to `engineer.py` and forgotten in `pipeline.py` is the same class of
    dropped-parameter bug as `--target-mm` never reaching `POST /jobs`."""
    from pythonsrc.pipeline import _build_parser

    parser = _build_parser()
    assert parser.parse_args(["a vase"]).no_scale is False
    assert parser.parse_args(["a vase", "--no-scale"]).no_scale is True
