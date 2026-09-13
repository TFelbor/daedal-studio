"""The two shape primitives every archetype composes edges from.

`rounded_rect_prism` (vertical corner fillets, external or internal) and `base_chamfer`
(a 45° chamfer against warping and elephant-foot) are the features the audited insert
standard calls mandatory — roadmap §0.5, `ARCHITECTURE.md` § The geometry kernel — and
this file is where the claim that they are *watertight, genus 0 and dimensionally what
they say* is made, once, away from any archetype that uses them.

Two properties get the most attention, because everything downstream rests on them:

- **Zero is an identity.** `r = 0` is `Manifold.cube` vertex for vertex and `c = 0` is
  the input object. That is what lets a spec asking for square corners compile to the
  bytes it always did.
- **A tangent point is an exact vertex.** A wall with a fillet of radius `r` runs from
  `r` to `w − r` and not a micron either side, which is the whole reason a corner radius
  can be *measured* off a mesh rather than assumed from the spec.
"""
import math

import manifold3d
import numpy as np
import pytest
import trimesh

from pythonsrc.organizer.compiler import (
    AXIS_ALIGNED_COS,
    CIRCULAR_SEGMENTS,
    MeasureError,
    base_chamfer,
    export_stl,
    face_normals,
    face_plane_extent,
    face_planes,
    manifold_to_trimesh,
    rounded_rect,
    rounded_rect_prism,
    tilted_face_extent,
)

ANGLE_TOL_DEG = 0.01  # a chamfer facet is 45° by construction, not approximately


def _solid_is_sound(solid):
    assert solid.status() == manifold3d.Error.NoError
    assert solid.genus() == 0
    assert manifold_to_trimesh(solid).is_watertight


# ── rounded_rect / rounded_rect_prism ──────────────────────────────────────────

def test_a_rounded_prism_is_watertight_genus_zero_and_the_size_it_was_asked_for():
    solid = rounded_rect_prism(60.0, 40.0, 20.0, 3.0)
    _solid_is_sound(solid)
    assert solid.bounding_box() == pytest.approx((0.0, 0.0, 0.0, 60.0, 40.0, 20.0), abs=1e-9)


def test_a_zero_radius_prism_is_the_cube_call_the_archetypes_always_made():
    """The compatibility claim of the primitives, asserted rather than asserted about:
    `r = 0` is not "close to" a cube, it is the same vertices and the same triangles."""
    rounded = rounded_rect_prism(70.0, 95.0, 100.0, 0.0).to_mesh64()
    cube = manifold3d.Manifold.cube([70.0, 95.0, 100.0], False).to_mesh64()
    assert np.array_equal(
        np.asarray(rounded.vert_properties), np.asarray(cube.vert_properties)
    )
    assert np.array_equal(np.asarray(rounded.tri_verts), np.asarray(cube.tri_verts))


def test_the_radius_defaults_to_a_square_corner():
    assert rounded_rect_prism(10.0, 10.0, 10.0).num_tri() == (
        manifold3d.Manifold.cube([10.0, 10.0, 10.0], False).num_tri()
    )


@pytest.mark.parametrize("r", [0.5, 1.0, 2.4, 5.0])
def test_each_straight_side_runs_exactly_between_its_tangent_points(r):
    """The property `measure()` reads a corner radius from."""
    w, d = 60.0, 40.0
    mesh = manifold_to_trimesh(rounded_rect_prism(w, d, 12.0, r))
    x = face_planes(mesh, 0)
    y = face_planes(mesh, 1)
    assert x == pytest.approx([0.0, w], abs=1e-9)
    assert y == pytest.approx([0.0, d], abs=1e-9)
    assert face_plane_extent(mesh, 1, y[0], 0) == pytest.approx((r, w - r), abs=1e-9)
    assert face_plane_extent(mesh, 0, x[0], 1) == pytest.approx((r, d - r), abs=1e-9)


def test_the_footprint_area_is_the_polygon_the_segment_count_describes():
    """`CIRCULAR_SEGMENTS` chords per 360°, so each corner is an inscribed arc and the
    area is the rectangle less four polygonal corner bites — not the ideal circle's."""
    w, d, r = 60.0, 40.0, 3.0
    n = CIRCULAR_SEGMENTS
    quarter = n // 4
    # Area of the inscribed arc polygon filling one quarter-corner of radius r.
    arc = 0.5 * r * r * quarter * math.sin(2 * math.pi / n)
    assert rounded_rect(w, d, r).area() == pytest.approx(w * d - 4 * (r * r - arc), abs=1e-6)


def test_a_rounded_prism_has_no_face_square_to_an_axis_it_should_not():
    """The arc chords sit half a step — 5,625° — off the wall they spring from, which is
    the margin `AXIS_ALIGNED_COS` lives inside."""
    normals, areas = face_normals(manifold_to_trimesh(rounded_rect_prism(60.0, 40.0, 12.0, 3.0)))
    real = areas > 1e-9
    off_axis = np.abs(normals[real]).max(axis=1)
    ambiguous = (off_axis < AXIS_ALIGNED_COS) & (off_axis > math.cos(math.radians(5.0)))
    assert not ambiguous.any()


def test_an_internal_round_is_the_same_primitive_subtracted():
    """There is no `r_inner`: a cavity is its own prism, so its corners carry the radius
    the prism that made the hole was built with."""
    body = rounded_rect_prism(60.0, 40.0, 20.0, 2.0) - rounded_rect_prism(
        54.0, 34.0, 19.0, 1.5
    ).translate([3.0, 3.0, 2.0])
    _solid_is_sound(body)
    mesh = manifold_to_trimesh(body)
    x, y = face_planes(mesh, 0), face_planes(mesh, 1)
    assert x == pytest.approx([0.0, 3.0, 57.0, 60.0], abs=1e-9)
    assert face_plane_extent(mesh, 1, y[1], 0)[0] - x[1] == pytest.approx(1.5, abs=1e-9)


@pytest.mark.parametrize(
    "args, message",
    [
        ((0.0, 40.0, 10.0, 1.0), "w must be a positive"),
        ((60.0, -1.0, 10.0, 1.0), "d must be a positive"),
        ((60.0, 40.0, 0.0, 1.0), "h must be a positive"),
        ((60.0, 40.0, 10.0, -0.5), "r must be a radius"),
        ((60.0, 40.0, 10.0, 21.0), "does not fit"),
    ],
)
def test_a_prism_that_cannot_exist_is_refused_with_the_reason(args, message):
    with pytest.raises(MeasureError) as exc:
        rounded_rect_prism(*args)
    assert message in str(exc.value)


@pytest.mark.parametrize("segments", [0, 3, 6, -4])
def test_a_segment_count_that_is_not_a_whole_number_of_quarter_turns_is_refused(segments):
    with pytest.raises(MeasureError) as exc:
        rounded_rect(60.0, 40.0, 2.0, circular_segments=segments)
    assert "multiple of 4" in str(exc.value)


# ── base_chamfer ───────────────────────────────────────────────────────────────

def test_a_zero_chamfer_is_the_plain_prism():
    section = rounded_rect(60.0, 40.0, 2.0)
    assert base_chamfer(section, 20.0, 0.0).volume() == pytest.approx(
        section.area() * 20.0, rel=1e-12
    )


def test_a_zero_chamfer_zero_radius_prism_is_still_the_cube_call():
    """Both zeros together, through the wrapper the archetypes actually call."""
    prism = rounded_rect_prism(70.0, 95.0, 100.0, 0.0, chamfer_mm=0.0).to_mesh64()
    cube = manifold3d.Manifold.cube([70.0, 95.0, 100.0], False).to_mesh64()
    assert np.array_equal(np.asarray(prism.vert_properties), np.asarray(cube.vert_properties))
    assert np.array_equal(np.asarray(prism.tri_verts), np.asarray(cube.tri_verts))


@pytest.mark.parametrize("r", [0.0, 1.0, 3.0])
@pytest.mark.parametrize("c", [0.4, 0.6, 1.5])
def test_every_chamfer_face_is_exactly_45_degrees(r, c):
    """Square corner or round, the eroded chord is parallel to the chord it came from
    and `c` away horizontally and vertically — so the face through the pair is at 45°
    by construction, and this is the assertion that says so."""
    solid = rounded_rect_prism(60.0, 40.0, 20.0, r, chamfer_mm=c)
    _solid_is_sound(solid)
    low, high, worst_error_deg = tilted_face_extent(manifold_to_trimesh(solid))
    assert worst_error_deg < ANGLE_TOL_DEG
    # Clipper2 offsets on a scaled integer grid, so the eroded ring — and with it the
    # top of the chamfer — lands ~10⁻⁷ mm off. Two orders under float32 STL noise.
    assert (low, high) == pytest.approx((0.0, c), abs=1e-6)


def test_the_chamfer_sets_the_base_back_by_its_own_height():
    """45° means the horizontal setback *is* the height, which is the measurement the
    kernel note recorded on 2026-09-05: cross-section at z ≈ 0 against the design."""
    w, d, c = 60.0, 40.0, 0.8
    solid = rounded_rect_prism(w, d, 20.0, 0.0, chamfer_mm=c)
    assert solid.slice(1e-9).area() == pytest.approx((w - 2 * c) * (d - 2 * c), abs=1e-6)
    assert solid.slice(c).area() == pytest.approx(w * d, abs=1e-6)


def test_the_chamfer_takes_exactly_the_volume_the_45_degree_wedge_does():
    """Closed form for a square prism: `∫₀^c [wd − (w−2t)(d−2t)] dt = (w+d)c² − 4c³/3`.
    Arithmetic nothing in the kernel knows about, against a solid it built."""
    w, d, h, c = 60.0, 40.0, 20.0, 0.8
    solid = rounded_rect_prism(w, d, h, 0.0, chamfer_mm=c)
    loss = (w + d) * c * c - 4.0 * c ** 3 / 3.0
    assert solid.volume() == pytest.approx(w * d * h - loss, abs=1e-6)


def test_a_chamfer_leaves_the_walls_above_it_where_they_were():
    mesh = manifold_to_trimesh(rounded_rect_prism(60.0, 40.0, 20.0, 2.0, chamfer_mm=0.6))
    assert face_planes(mesh, 0) == pytest.approx([0.0, 60.0], abs=1e-9)
    assert face_planes(mesh, 1) == pytest.approx([0.0, 40.0], abs=1e-9)
    # No horizontal face where the chamfer meets the wall: one hull, so no seam.
    assert face_planes(mesh, 2) == pytest.approx([0.0, 20.0], abs=1e-9)
    assert face_plane_extent(mesh, 1, 0.0, 0) == pytest.approx((2.0, 58.0), abs=1e-9)


def test_a_chamfered_prism_survives_the_float32_export_as_one_solid(tmp_path):
    """What a degenerate triangle costs, asserted end to end. Two of its corners are the
    same point; float32 merges them, and the STL comes back with non-manifold edges and
    a couple of dozen loose bodies. Both constructions are exercised here — `(1.0, 1.5)`
    and `(0.5, 0.6)` take the general one."""
    for r, c in [(0.0, 0.6), (1.0, 0.6), (0.5, 0.6), (1.0, 1.5)]:
        solid = rounded_rect_prism(73.3, 75.8, 95.5, r, chamfer_mm=c)
        path = export_stl(manifold_to_trimesh(solid), tmp_path / f"{r}-{c}.stl")
        reloaded = trimesh.load(str(path))
        assert reloaded.is_watertight, (r, c)
        assert len(reloaded.split(only_watertight=False)) == 1, (r, c)


def test_a_chamfered_prism_carries_no_degenerate_triangle():
    """The property that made `base_chamfer` build rather than cut. A zero-area triangle
    is two vertices in the same place; float32 merges them on export and the STL comes
    back open. There are none to merge."""
    for r, c in [(0.0, 0.6), (1.0, 0.6), (2.4, 0.8), (0.5, 0.6), (1.0, 1.5), (2.0, 2.4)]:
        mesh = manifold_to_trimesh(rounded_rect_prism(73.3, 75.8, 95.5, r, chamfer_mm=c))
        assert (mesh.area_faces < 1e-9).sum() == 0, (r, c)


def test_a_cavity_cut_into_a_chamfered_prism_does_not_reach_the_chamfer():
    body = rounded_rect_prism(60.0, 40.0, 20.0, 1.0, chamfer_mm=0.6) - rounded_rect_prism(
        54.0, 34.0, 19.0, 0.0
    ).translate([3.0, 3.0, 2.0])
    _solid_is_sound(body)
    mesh = manifold_to_trimesh(body)
    assert face_planes(mesh, 0) == pytest.approx([0.0, 3.0, 57.0, 60.0], abs=1e-9)
    assert face_planes(mesh, 2) == pytest.approx([0.0, 2.0, 20.0], abs=1e-9)
    assert tilted_face_extent(mesh)[1] == pytest.approx(0.6, abs=1e-6)


def test_an_unchamfered_prism_measures_a_chamfer_of_zero():
    low, high, worst = tilted_face_extent(manifold_to_trimesh(rounded_rect_prism(60.0, 40.0, 20.0, 1.0)))
    assert (low, high, worst) == (0.0, 0.0, 0.0)


def test_the_two_constructions_are_the_same_solid_where_both_are_valid():
    """The fast path's whole claim. Three rings hulled and a 45° half-space per edge
    build the same prism whenever the erosion keeps every edge — so `base_chamfer` may
    take the cheap one — and this is the assertion that they do."""
    from pythonsrc.organizer.compiler import (
        _chamfered_hull,
        _chamfered_trims,
        _erosion_keeps_every_edge,
    )

    for r, c in [(0.0, 0.6), (0.0, 2.0), (1.0, 0.6), (3.0, 1.5), (2.4, 0.8)]:
        section = rounded_rect(60.0, 40.0, r)
        eroded = section.offset(-c, manifold3d.JoinType.Round, 2.0, CIRCULAR_SEGMENTS)
        assert _erosion_keeps_every_edge(section, eroded, c), (r, c)
        hulled = _chamfered_hull(section, eroded, 20.0, c)
        trimmed = _chamfered_trims(section, 20.0, c)
        assert hulled.volume() == pytest.approx(trimmed.volume(), rel=1e-9), (r, c)
        assert hulled.surface_area() == pytest.approx(trimmed.surface_area(), rel=1e-6), (r, c)


def test_a_chamfer_taller_than_the_corner_it_runs_around_still_comes_out_at_45():
    """The case three rings cannot do: when the erosion loses the corner's chords, they
    no longer describe the shape, and the general construction is used."""
    from pythonsrc.organizer.compiler import _erosion_keeps_every_edge

    section = rounded_rect(60.0, 40.0, 1.0)
    eroded = section.offset(-2.0, manifold3d.JoinType.Round, 2.0, CIRCULAR_SEGMENTS)
    assert not _erosion_keeps_every_edge(section, eroded, 2.0)
    chamfered = base_chamfer(section, 20.0, 2.0)
    _solid_is_sound(chamfered)
    _, high, worst_error_deg = tilted_face_extent(manifold_to_trimesh(chamfered))
    assert worst_error_deg < ANGLE_TOL_DEG
    assert high == pytest.approx(2.0, abs=1e-6)
    # The corner is square by then, so the base is the outline inset by the chamfer.
    assert chamfered.slice(1e-9).area() == pytest.approx(56.0 * 36.0, abs=1e-4)


@pytest.mark.parametrize(
    "h, c, message",
    [
        (20.0, -0.1, "height in mm ≥ 0"),
        (20.0, 20.0, "does not fit a prism"),
        (20.0, 30.0, "does not fit a prism"),
        (0.0, 0.6, "h must be a positive"),
    ],
)
def test_a_chamfer_that_cannot_be_cut_is_refused_with_the_reason(h, c, message):
    with pytest.raises(MeasureError) as exc:
        base_chamfer(rounded_rect(60.0, 40.0, 1.0), h, c)
    assert message in str(exc.value)


def test_a_chamfer_that_would_erode_the_outline_away_is_refused():
    with pytest.raises(MeasureError) as exc:
        base_chamfer(rounded_rect(2.0, 2.0, 0.0), 20.0, 1.5)
    assert "erodes this outline away" in str(exc.value)


def test_a_chamfer_refuses_an_outline_the_hull_would_fill_in():
    """An L-shaped outline: the hull that builds the 45° face would add the missing
    quadrant back, so the primitive refuses rather than returning a part nobody asked
    for."""
    ell = manifold3d.CrossSection.square([40.0, 40.0], False) - manifold3d.CrossSection.square(
        [20.0, 20.0], False
    ).translate([20.0, 20.0])
    with pytest.raises(MeasureError) as exc:
        base_chamfer(ell, 20.0, 0.6)
    assert "convex outline" in str(exc.value)


def test_a_chamfer_refuses_an_outline_that_is_more_than_one_contour():
    """Two parts on a plate are chamfered one at a time; a plate is not one outline."""
    plate = manifold3d.CrossSection.square([20.0, 20.0], False) + manifold3d.CrossSection.square(
        [20.0, 20.0], False
    ).translate([30.0, 0.0])
    with pytest.raises(MeasureError) as exc:
        base_chamfer(plate, 10.0, 0.6)
    assert "one closed outline" in str(exc.value)


# ── the readers ────────────────────────────────────────────────────────────────

def test_face_planes_ignores_the_arc_vertices_a_vertex_column_would_count():
    """The reason `face_planes` exists: a fillet puts vertices at every coordinate from
    the tangent point to the corner, so reading a coordinate column states dozens of
    planes where the design has two."""
    from pythonsrc.organizer.compiler import plane_set

    mesh = manifold_to_trimesh(rounded_rect_prism(60.0, 40.0, 12.0, 3.0))
    assert len(plane_set(mesh.vertices[:, 0])) > 2
    assert face_planes(mesh, 0) == pytest.approx([0.0, 60.0], abs=1e-9)


def test_face_planes_weighs_a_plane_by_area_and_drops_what_has_none():
    """The area gate. Nothing this repository builds relies on it any more — the
    chamfer stopped producing seam slivers when it stopped being a boolean — but the
    reader still has to be the kind that cannot be fooled by one."""
    mesh = manifold_to_trimesh(rounded_rect_prism(60.0, 40.0, 20.0, 2.0, chamfer_mm=0.6))
    assert face_planes(mesh, 2) == pytest.approx([0.0, 20.0], abs=1e-9)
    assert face_planes(mesh, 2, min_area_mm2=1e6) == []


def test_face_plane_extent_refuses_a_plane_no_face_lies_in():
    mesh = manifold_to_trimesh(rounded_rect_prism(60.0, 40.0, 12.0, 1.0))
    with pytest.raises(MeasureError) as exc:
        face_plane_extent(mesh, 1, 17.0, 0)
    assert "no face lies in the plane Y = 17.000 mm" in str(exc.value)
