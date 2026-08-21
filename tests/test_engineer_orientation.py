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
