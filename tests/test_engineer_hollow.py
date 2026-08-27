"""Guards on hollowing producing a shell that is the *same object*, in one
piece, with a way out for the air.

Three separate things went wrong here, and each was invisible downstream because
the result was watertight, sliced, and printed — just not as the part anyone asked
for.

**Frame.** `VoxelGrid.marching_cubes` is `ops.matrix_to_marching_cubes(matrix=
self.matrix)`: it meshes the occupancy array at a spacing of one and **ignores the
grid's transform**, so the surface it returns lives in voxel-index space — one unit
per voxel, origin at the grid corner. Hollowing runs after scaling and orienting,
so returning that unmapped meant a 50 mm sphere left Phase 3 as a 43 mm one, base
0.5 mm under the plate and centre 21 mm off in X and Y.

**Connectivity.** The shell was built by eroding the filled grid one layer, making
it one voxel thick — and a one-voxel layer on a curved surface is a diagonal
staircase whose voxels meet only at edges and corners. `marching_cubes` meshes
face-adjacency, so a hollowed 50 mm sphere came back as 378 disconnected chips, 314
of them floating clear of the plate.

**Venting.** Meshing a closed shell yields an outer surface and an inner one, and
the inner one is a sealed cavity. `printability.escape_hole` rates that *fatal*
when the Engineer caused it, so every `--hollow` job was unprintable by
construction.
"""

import numpy as np
import trimesh

from pythonsrc.engineer import Engineer
from pythonsrc.printability import evaluate_printability


def _placed_sphere(radius: float = 25.0) -> trimesh.Trimesh:
    """A sphere the size and placement Phase 3 hands to `hollow_mesh`: centred in
    X/Y, sitting on Z=0."""
    mesh = trimesh.creation.icosphere(subdivisions=3, radius=radius)
    mesh.apply_translation([0.0, 0.0, radius])
    return mesh


def _blob_with_a_small_pocket(radius: float) -> trimesh.Trimesh:
    """A 12 mm sphere with a second sphere stuck on by a neck thinner than the wall.

    The neck being sub-wall is what keeps the two interiors from merging into one
    cavity, which is the whole point: it gives a mesh with a cavity worth hollowing
    and a cavity that is not, so the small-cavity and severed-vent paths have
    something to act on.
    """
    parts = [
        trimesh.creation.icosphere(subdivisions=3, radius=12.0),
        trimesh.creation.icosphere(subdivisions=3, radius=radius).apply_translation(
            [0.0, 0.0, 12.0 + radius + 1.4]
        ),
        trimesh.creation.cylinder(radius=0.45, height=4.0).apply_translation(
            [0.0, 0.0, 13.0]
        ),
    ]
    mesh = trimesh.util.concatenate(parts)
    mesh.apply_translation([0.0, 0.0, -mesh.bounds[0][2]])
    return mesh


def test_the_shell_keeps_the_size_it_was_given():
    """Within the voxel the pitch inevitably adds, not a factor of the pitch.

    The index-space bug divided the part by the pitch — 50 mm became 43 mm at a
    1.2 mm wall, and 6 mm at a 0.15 mm one. The dilation asserted here instead is
    inherent and bounded by the pitch: the isosurface runs outside the input's own
    surface by up to a voxel, never inside it, and never by a factor.
    """
    solid = _placed_sphere()
    wall = 1.2
    hollow = Engineer().hollow_mesh(solid, wall_thickness=wall)
    assert np.all(hollow.extents >= solid.extents - 1e-6)
    assert np.all(hollow.extents <= solid.extents + 2 * wall)


def test_the_shell_stays_where_it_was_put():
    """A shell centred on the grid corner rather than the origin is off the plate."""
    solid = _placed_sphere()
    hollow = Engineer().hollow_mesh(solid, wall_thickness=1.2)
    centre = hollow.bounds.mean(axis=0)
    assert abs(centre[0]) < 1.2
    assert abs(centre[1]) < 1.2
    assert abs(centre[2] - solid.bounds.mean(axis=0)[2]) < 1.2


def test_hollowing_actually_removes_material():
    """The point of the exercise: a shell, not a re-meshed solid."""
    solid = _placed_sphere()
    hollow = Engineer().hollow_mesh(solid, wall_thickness=1.2)
    assert hollow.is_watertight
    assert hollow.volume < solid.volume * 0.5


def test_a_fine_wall_stays_in_frame():
    """The finer the requested wall, the worse the index-space bug got.

    At 0.15 mm the unmapped shell came back roughly 6 mm across for a 50 mm part —
    the error scaled with the pitch, so a single pitch cannot show that the mapping
    is a mapping rather than a constant.

    The wall asked for here is *not* the wall that gets built: 0.15 mm needs a
    0.075 mm pitch, which is 299 million voxels for a 50 mm part, so
    `HOLLOW_MAX_VOXELS` coarsens it and the wall is floored at two voxels of
    whatever pitch survives (about 1.1 mm here). That is deliberate — a coarsened
    grid must thicken the wall, never thin it, because a sub-two-voxel shell is the
    fragmenting one. So the bound asserted is absolute and generous rather than a
    function of the requested wall: it still catches a part divided by its pitch,
    which is what this test exists for.
    """
    solid = _placed_sphere()
    engineer = Engineer()
    hollow = engineer.hollow_mesh(solid, wall_thickness=0.15)

    assert np.all(hollow.extents >= solid.extents - 1e-6)
    assert np.all(hollow.extents <= solid.extents + 2.0)
    # The floor, stated rather than implied: the wall came out thicker than asked.
    assert engineer._hollow_stats["wall_thickness_achieved_mm"] > 0.15
    # And the shell it produced is still one body, which is the point of the floor.
    assert len(hollow.split(only_watertight=False)) == 1


def test_the_exported_hollow_part_is_the_requested_size_and_on_the_plate(tmp_path):
    """End to end through `process`, which is where the truth has to hold.

    The pitch's half-voxel dilation is removed by re-scaling and re-seating after
    hollowing, so `--target-mm 50 --hollow` exports a 50 mm part on the plate
    rather than a 51.6 mm one starting 0.6 mm below it — where CuraEngine would
    silently truncate the base.

    It is the *scaled axis* that is exact, and only that one. This used to assert
    `extents.max()`, which passed on luck: a voxel grid does not respect its
    object's symmetry unless the object happens to align with it, and at the old
    1.2 mm pitch a sphere centred on z=25 came out isotropic by coincidence. At any
    other pitch the unscaled axes carry up to one voxel of dilation, so they are
    bounded by the pitch the run actually used rather than asserted equal.
    """
    raw = tmp_path / "raw.obj"
    trimesh.creation.icosphere(subdivisions=3, radius=1.0).export(raw)
    out = tmp_path / "engineered.obj"

    engineer = Engineer()
    engineer.process(raw, out, target_mm=50.0, hollow=True, wall_thickness=1.2)
    pitch = engineer.last_report["hollow_pitch_mm"]

    mesh = trimesh.load(out, force="mesh")
    assert np.isclose(mesh.extents[2], 50.0, atol=1e-3)          # height: the scaled axis
    assert np.all(mesh.extents <= 50.0 + pitch + 1e-3)           # the rest: within a voxel
    assert np.isclose(mesh.bounds[0][2], 0.0, atol=1e-6)
    assert np.allclose(mesh.bounds.mean(axis=0)[:2], 0.0, atol=1e-6)
    assert mesh.volume < trimesh.creation.icosphere(radius=25.0).volume * 0.5


def test_the_shell_is_one_connected_body():
    """The 378-chip regression.

    One-voxel erosion left a shell whose voxels touched only diagonally, and
    `marching_cubes` meshes face-adjacency: a hollowed 50 mm sphere split into 378
    closed surfaces, 314 of which did not reach the plate. Every check downstream
    passed it — watertight, sliceable — and it would have printed as a pile of
    chips. Asserted as an exact count because "fewer than 378" is not the property;
    one body is.
    """
    hollow = Engineer().hollow_mesh(_placed_sphere(), wall_thickness=1.2)

    assert len(hollow.split(only_watertight=False)) == 1
    assert hollow.is_watertight


def test_the_cavity_gets_an_escape_hole():
    """A hollowed part has to clear the gate that judges hollowed parts.

    `printability.escape_hole` is *critical* when the mesh was hollowed, because a
    sealed cavity is a defect the Engineer introduced rather than a choice the
    requester made. Before venting, that check failed on every `--hollow` job by
    construction — so this asserts the whole report, not just the one check: a
    verdict of `unprintable` here means hollowing produced something nobody can
    print, whatever the reason.
    """
    engineer = Engineer()
    hollow = engineer.hollow_mesh(_placed_sphere(), wall_thickness=1.2)
    hollow = engineer.orient_for_print(hollow)

    assert engineer._hollow_stats["escape_holes"] == 1
    assert engineer._hollow_stats["sealed_cavities"] == 0

    report = evaluate_printability(hollow, job_id="test", was_hollowed=True)
    escape = next(c for c in report.checks if c.check == "escape_hole")
    assert escape.status == "pass", escape.detail
    assert report.verdict != "unprintable"
    assert [c.check for c in report.checks if c.status == "fail"] == []


def test_an_unvented_shell_is_reported_sealed_and_fails_the_gate():
    """`vent=False` is the old shape, and the gate's verdict on it is the honest one.

    Kept reachable because a sealed shell is a real thing to ask for, not because
    it is a reasonable default — so the guard is that asking for it produces
    exactly what the gate is meant to reject: two surfaces, the inner one a cavity
    with no way out, failed as critical.
    """
    engineer = Engineer()
    sealed = engineer.hollow_mesh(_placed_sphere(), wall_thickness=1.2, vent=False)
    sealed = engineer.orient_for_print(sealed)

    assert engineer._hollow_stats["escape_holes"] == 0
    assert engineer._hollow_stats["sealed_cavities"] == 1
    assert len(sealed.split(only_watertight=False)) == 2

    report = evaluate_printability(sealed, job_id="test", was_hollowed=True)
    escape = next(c for c in report.checks if c.check == "escape_hole")
    assert escape.status == "fail"
    assert escape.critical is True
    assert report.verdict == "unprintable"


def test_a_cavity_too_small_to_vent_is_filled_instead():
    """Below a certain size the vent removes more material than the cavity saves.

    A real reconstruction hollowed at 1.2 mm had 37 cavities, 36 of them small
    enough that venting them all severed the shell. Filling them is not a
    concession: a pocket that cannot hold its own escape hole is all defect and no
    saving. The fixture is the shape that produces one of each — a 12 mm sphere
    whose cavity is worth hollowing, joined by a neck thinner than the wall to a
    1.8 mm blob whose cavity is not.
    """
    engineer = Engineer()
    hollow = engineer.hollow_mesh(_blob_with_a_small_pocket(1.8), wall_thickness=1.2)

    assert engineer._hollow_stats["cavities_filled"] == 1
    assert engineer._hollow_stats["cavities"] == 1
    assert engineer._hollow_stats["escape_holes"] == 1
    assert engineer._hollow_stats["sealed_cavities"] == 0
    assert len(hollow.split(only_watertight=False)) == 1


def test_a_vent_that_would_sever_the_shell_is_abandoned():
    """And abandoned one cavity at a time, not all of them together.

    A 2.4 mm vent aimed out of a cavity that sits inside a thin appendage takes the
    appendage off with it, which is worse than the cavity: the gate would report
    floating components on a part that is no longer the requested shape. So that
    vent is dropped — while the cavity that *can* be vented safely still is, which
    is what per-cavity rather than all-or-nothing buys.
    """
    engineer = Engineer()
    hollow = engineer.hollow_mesh(_blob_with_a_small_pocket(2.4), wall_thickness=1.2)

    stats = engineer._hollow_stats
    assert stats["cavities"] == 2
    assert stats["escape_holes"] == 1        # the large cavity, vented
    assert stats["sealed_cavities"] == 1     # the appendage, left alone
    # The part is intact: an outer surface plus the one cavity still sealed.
    assert len(hollow.split(only_watertight=False)) == 2
