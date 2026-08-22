"""Guards on Phase 3 not throwing away the orientation Phase 2 established.

`orient_for_print` used to rotate the mesh so that its *smallest-extent* axis
became Z, on the theory that the thinnest axis is the "flat" one. For anything
that stands up — a figurine, a bust, a raccoon on a skateboard — the thinnest
axis is left-to-right, so the model was laid on its side on every single job. Its
own docstring described the opposite behaviour ("the axis with the greatest
extent"), which is how it survived review.

The deeper fault is that the guess was unnecessary. Phase 2 knows which way is up:
each sculptor backend declares an `up_axis` and `SculptorBackend.postprocess`
rotates the raw output to Z-up on the strength of it. A bounding box cannot
recover that, so re-deriving orientation here could only ever discard information
that was already correct.

Measured on the real job: the sculptor wrote `raw_mesh.obj` with its widest
cross-section at the bottom (the skateboard) and `engineered_mesh.obj` came out
with the widest cross-section at the top.
"""

import numpy as np
import pytest
import trimesh

from pythonsrc.engineer import Engineer


def _footprint_profile(mesh: trimesh.Trimesh, slabs: int = 10) -> np.ndarray:
    """Relative cross-sectional area in `slabs` bands from Z-min to Z-max.

    A model standing on a base has its largest cross-section at the bottom. This is
    what "is it the right way up" reduces to without rendering anything.
    """
    verts = np.asarray(mesh.vertices)
    edges = np.linspace(verts[:, 2].min(), verts[:, 2].max(), slabs + 1)
    areas = []
    for i in range(slabs):
        band = verts[(verts[:, 2] >= edges[i]) & (verts[:, 2] < edges[i + 1])]
        if len(band) < 3:
            areas.append(0.0)
            continue
        areas.append(
            (band[:, 0].max() - band[:, 0].min()) * (band[:, 1].max() - band[:, 1].min())
        )
    profile = np.array(areas)
    return profile / (profile.max() or 1.0)


def _figurine() -> trimesh.Trimesh:
    """Something that stands up: a wide flat base under a tall narrow body.

    Deliberately thinner left-to-right than it is tall, which is the shape the old
    heuristic mishandled — and the shape almost every printed figurine has.
    """
    base = trimesh.creation.box(extents=(20.0, 18.0, 2.0))
    body = trimesh.creation.box(extents=(6.0, 8.0, 30.0))
    body.apply_translation([0.0, 0.0, 16.0])
    return trimesh.util.concatenate([base, body])


def test_an_upright_model_is_left_upright():
    """The regression: the thinnest axis is X, and X used to become Z."""
    mesh = _figurine()
    before = _footprint_profile(mesh)

    oriented = Engineer().orient_for_print(mesh)
    after = _footprint_profile(oriented)

    assert before[:3].mean() > before[-3:].mean(), "fixture must start base-down"
    assert after[:3].mean() > after[-3:].mean(), "the base must still be at the bottom"


def test_the_tall_axis_stays_the_tall_axis():
    """A 30mm-tall figurine must not come out 20mm tall and 30mm wide."""
    mesh = _figurine()
    tall_before = int(np.argmax(mesh.bounds[1] - mesh.bounds[0]))

    oriented = Engineer().orient_for_print(mesh)
    tall_after = int(np.argmax(oriented.bounds[1] - oriented.bounds[0]))

    assert tall_before == 2
    assert tall_after == 2


def test_extents_are_unchanged_because_nothing_is_rotated():
    """Centring and dropping to the plate are translations; they change no extent."""
    mesh = _figurine()
    oriented = Engineer().orient_for_print(mesh)
    assert np.allclose(
        mesh.bounds[1] - mesh.bounds[0], oriented.bounds[1] - oriented.bounds[0]
    )


def test_the_mesh_is_placed_on_the_build_plate():
    mesh = _figurine()
    mesh.apply_translation([13.0, -7.0, 41.0])

    oriented = Engineer().orient_for_print(mesh)

    assert oriented.bounds[0][2] == 0.0, "the bottom must sit on Z=0"


def test_the_mesh_is_centred_over_the_origin_in_x_and_y():
    """Centred in X/Y, but *not* in Z — Z=0 is the plate, not the middle."""
    mesh = _figurine()
    mesh.apply_translation([13.0, -7.0, 41.0])

    oriented = Engineer().orient_for_print(mesh)
    centre = oriented.bounds.mean(axis=0)

    assert np.allclose(centre[:2], [0.0, 0.0])


def test_a_model_lying_down_is_left_lying_down():
    """Phase 2 is the authority on up. Phase 3 must not second-guess it.

    A mesh whose tall axis is X arrives that way because that is what the sculptor
    produced; silently standing it up is the same class of error as laying it down.
    """
    mesh = trimesh.creation.box(extents=(40.0, 10.0, 5.0))
    oriented = Engineer().orient_for_print(mesh)
    assert np.allclose(oriented.bounds[1] - oriented.bounds[0], [40.0, 10.0, 5.0])


# ── Adhesion follows the measurement, not a fixed profile setting ────────────


class _Check:
    def __init__(self, check, status, detail=""):
        self.check, self.status, self.detail = check, status, detail


class _Report:
    def __init__(self, *checks):
        self.checks = list(checks)


def test_a_small_footprint_gets_a_brim():
    """A real job reached the plate with 6mm² against the 25mm² wanted."""
    from pythonsrc.pipeline import BRIM_WIDTH_MM, _adhesion_args

    args = _adhesion_args(_Report(_Check("bed_contact", "warn", "only 6.1mm²")))

    assert "adhesion_type=brim" in args
    assert f"brim_width={BRIM_WIDTH_MM}" in args


def test_a_part_that_already_sits_flat_gets_no_brim():
    """A brim it does not need is wasted filament and a finishing job."""
    from pythonsrc.pipeline import _adhesion_args

    assert _adhesion_args(_Report(_Check("bed_contact", "pass", "plenty"))) == []


def test_no_report_means_no_opinion():
    """Scoring is allowed to be skipped; that must not change how we slice."""
    from pythonsrc.pipeline import _adhesion_args

    assert _adhesion_args(None) == []
    assert _adhesion_args(_Report(_Check("watertight", "fail"))) == []


# ── Which axis the target size describes ──────────────────────────────────────
#
# `scale_to_dimensions` scaled the *longest bounding-box edge*, and its docstring
# said so — but "how big is it" means height to almost everyone who asks. A
# figurine with its arms out is wider than it is tall, so a request for 50 mm gave a
# part 50 mm across and under 40 mm tall: shorter than asked, in the one dimension
# the person was picturing. The axis is now a parameter, defaulting to height, and
# is recorded because a bare `target_mm` in a historical row cannot say which
# convention produced it.

def _written(mesh: trimesh.Trimesh, tmp_path) -> str:
    """Export a mesh so `Engineer.process` can be driven end to end."""
    path = tmp_path / "raw_mesh.obj"
    mesh.export(str(path))
    return str(path)


def _lying_slab() -> trimesh.Trimesh:
    """Eight times wider than it is tall — the shape that made this a bug."""
    return trimesh.creation.box(extents=(40.0, 10.0, 5.0))


def test_height_mode_scales_the_z_extent_not_the_longest_edge(tmp_path):
    """Asking for 50 mm in height mode must give 50 mm of height, however wide."""
    out = tmp_path / "engineered.obj"
    Engineer().process(
        input_path=_written(_lying_slab(), tmp_path), output_path=out,
        target_mm=50.0, scale_axis="height", hollow=False,
    )
    result = trimesh.load(str(out), force="mesh")

    assert abs(result.extents[2] - 50.0) < 0.05, f"height is {result.extents[2]}"
    # The part is 8x wider than tall, so honouring the height means 400 mm wide.
    assert abs(result.extents[0] - 400.0) < 0.5, f"width is {result.extents[0]}"
    # And it is still seated: `apply_scale` is origin-based, so scaling must happen
    # after `orient_for_print` drove Z-min to zero, never before.
    assert abs(result.bounds[0][2]) < 1e-6


def test_longest_mode_still_scales_the_longest_edge(tmp_path):
    """The old behaviour stays reachable by name, for anything that depended on it."""
    out = tmp_path / "engineered.obj"
    Engineer().process(
        input_path=_written(_lying_slab(), tmp_path), output_path=out,
        target_mm=50.0, scale_axis="longest", hollow=False,
    )
    result = trimesh.load(str(out), force="mesh")

    assert abs(result.extents[0] - 50.0) < 0.05
    assert abs(result.extents[2] - 6.25) < 0.05


def test_the_report_names_the_axis_that_was_actually_used(tmp_path):
    """`repair_report` must carry the axis, not just the number.

    `target_mm` alone is ambiguous once two conventions exist, and every row written
    before this change carries a bare one. An absent key in an unschematised blob is
    indistinguishable from a pre-change row, so it is written unconditionally.
    """
    eng = Engineer()
    eng.process(
        input_path=_written(_lying_slab(), tmp_path),
        output_path=tmp_path / "engineered.obj",
        target_mm=50.0, scale_axis="height", hollow=False,
    )

    assert eng.last_report["scale_axis"] == "height"
    assert eng.last_report["target_mm"] == 50.0
    assert eng.last_report["achieved_extent_mm"][2] == pytest.approx(50.0, abs=0.05)


def test_a_flat_mesh_does_not_divide_by_a_zero_height(tmp_path):
    """A coaster has no height to scale, and must survive rather than blow up.

    The pre-existing guard only caught a mesh with *no* extent at all. A nameplate
    lying in XY has a legitimately zero Z extent, which height mode would divide by.
    """
    plate = trimesh.creation.box(extents=(60.0, 60.0, 2.0))
    plate.apply_scale([1.0, 1.0, 0.0])          # flatten to a true zero-height sheet
    out = tmp_path / "engineered.obj"

    eng = Engineer()
    eng.process(
        input_path=_written(plate, tmp_path), output_path=out,
        target_mm=50.0, scale_axis="height", hollow=False,
    )

    # Reported honestly as what happened, not as what was asked for.
    assert eng.last_report["scale_axis"] == "none"
    assert eng.last_report["scale_factor"] is None


def test_an_unknown_axis_is_refused_rather_than_guessed(tmp_path):
    """A typo must not silently fall back to a convention nobody chose."""
    with pytest.raises(ValueError, match="scale_axis"):
        Engineer().process(
            input_path=_written(_lying_slab(), tmp_path),
            output_path=tmp_path / "engineered.obj",
            target_mm=50.0, scale_axis="tallest", hollow=False,
        )
