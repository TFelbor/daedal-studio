"""Guards on hollowing returning a shell of the *same object* it was given.

`hollow_mesh` voxelises, erodes one layer, and meshes the difference with
`VoxelGrid.marching_cubes`. That property is `ops.matrix_to_marching_cubes(
matrix=self.matrix)`: it meshes the occupancy array at a spacing of one and
**ignores the grid's transform**, so the surface it returns lives in voxel-index
space — one unit per voxel, origin at the grid corner.

Hollowing runs after scaling and orienting, so returning that unmapped shell
meant a 50 mm sphere left Phase 3 as a 43 mm one, base 0.5 mm under the plate and
centre 21 mm off in X and Y. Nothing downstream could notice: the shell is
watertight, it slices, and it prints — just as the wrong part.
"""

import numpy as np
import trimesh

from pythonsrc.engineer import Engineer


def _placed_sphere(radius: float = 25.0) -> trimesh.Trimesh:
    """A sphere the size and placement Phase 3 hands to `hollow_mesh`: centred in
    X/Y, sitting on Z=0."""
    mesh = trimesh.creation.icosphere(subdivisions=3, radius=radius)
    mesh.apply_translation([0.0, 0.0, radius])
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
    """The finer the pitch, the worse the index-space bug got — and this is the
    pitch a real 1.2 mm wall on a small part reduces to.

    At 0.15 mm the unmapped shell came back roughly 6 mm across for a 50 mm part.
    Asserted separately from the coarse case because the failure scaled with the
    pitch, so a single pitch cannot show that the mapping is a mapping rather than
    a constant.
    """
    solid = _placed_sphere()
    hollow = Engineer().hollow_mesh(solid, wall_thickness=0.15)
    assert np.all(hollow.extents >= solid.extents - 1e-6)
    assert np.all(hollow.extents <= solid.extents + 0.3)


def test_the_exported_hollow_part_is_the_requested_size_and_on_the_plate(tmp_path):
    """End to end through `process`, which is where the truth has to hold.

    The pitch's half-voxel dilation is removed by re-scaling and re-seating after
    hollowing, so `--target-mm 50 --hollow` exports a 50 mm part on the plate
    rather than a 51.6 mm one starting 0.6 mm below it — where CuraEngine would
    silently truncate the base.
    """
    raw = tmp_path / "raw.obj"
    trimesh.creation.icosphere(subdivisions=3, radius=1.0).export(raw)
    out = tmp_path / "engineered.obj"

    Engineer().process(raw, out, target_mm=50.0, hollow=True, wall_thickness=1.2)

    mesh = trimesh.load(out, force="mesh")
    assert np.isclose(mesh.extents.max(), 50.0, atol=1e-3)
    assert np.isclose(mesh.bounds[0][2], 0.0, atol=1e-6)
    assert np.allclose(mesh.bounds.mean(axis=0)[:2], 0.0, atol=1e-6)
    assert mesh.volume < trimesh.creation.icosphere(radius=25.0).volume * 0.5
