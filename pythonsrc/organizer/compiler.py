"""What every archetype compiler shares: the kernel bridge, the shape primitives,
plane reading, result types.

The archetypes build solids with `manifold3d` (Apache-2.0, already the project's CSG
and manifoldness kernel — see `ARCHITECTURE.md`, "The geometry kernel") and hand them
to trimesh for export. Four rules hold across all of them:

- **The kernel's vertices are exported untouched.** `manifold_to_trimesh` builds the
  Trimesh with `process=False`: no merging, no re-indexing, so the planes the design
  put at 2.4 mm are at 2.4 mm in the file. (STL itself is float32, so a 156.6 mm
  extent reads back as 156.6000061 — six millionths of a millimetre, four orders of
  magnitude under N1's ±0,05 mm.)
- **Designed features are measured, never assumed.** `face_planes` reads the distinct
  axis-aligned planes off a mesh; an archetype's `measure()` turns those into the same
  feature names its `compile()` designed, and `compare_features` puts the two side by
  side. This is the shape of text-to-cad's `measure`/`align` checkers, and it is what
  lets the dimensional assertion run on Phase 3's *output* rather than on the input.
- **A shape primitive lives here, once.** `rounded_rect_prism` and `base_chamfer` are
  the two edge treatments the audited insert standard calls mandatory (roadmap §0.5),
  and they are shared by every archetype rather than re-derived per module — one
  spelling of a vertical fillet, one spelling of a 45° base chamfer.
- **A zero parameter is an identity.** `rounded_rect_prism(w, d, h, 0)` is
  `Manifold.cube([w, d, h])`, the call every archetype made before the primitives
  existed, and `base_chamfer(solid, 0)` returns `solid` itself. So a spec that asks
  for no edge treatment runs the code path it always ran and compiles to the bytes it
  always did; the primitives are a superset, not a replacement.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import numpy as np
import trimesh

try:  # the kernel is a hard dependency; the guard only makes the error readable
    import manifold3d
except ImportError as exc:  # pragma: no cover
    raise ImportError("manifold3d is required to compile organizer specs") from exc


#: Widest a measured feature may sit from its designed value, in mm (PRD N1).
DEFAULT_TOLERANCE_MM = 0.05

#: Straight segments a full 360° of `JoinType.Round` is approximated by.
#:
#: Passed explicitly on every `offset` call rather than set through
#: `manifold3d.set_circular_segments`, because that is process-global state and the
#: same spec must compile to the same mesh whatever else ran first in the interpreter.
#:
#: 32 is chosen from the chord error, not from taste: a 360°/32 step leaves a sagitta
#: of `r·(1 − cos(π/32))` = 0,0048·r mm, so every radius under 10 mm is inside N1's
#: ±0,05 mm by at least an order of magnitude, and a corner round on a card organizer
#: is 1–3 mm. It is a multiple of four so that each quarter-turn is a whole number of
#: steps and **no chord lands square on an axis** — the closest is half a step, 5,625°,
#: which is what keeps `face_planes` able to tell an arc facet from a wall.
CIRCULAR_SEGMENTS = 32

#: How square a face's normal must be to an axis to count as a plane on that axis.
#: cos(1,8°); the nearest arc facet at `CIRCULAR_SEGMENTS` is 5,625° off-axis, and a
#: 45° chamfer facet is 45° off, so both sit far outside it.
AXIS_ALIGNED_COS = 0.9995

#: Total face area, in mm², a cluster needs before `face_planes` calls it a plane.
#:
#: An intersection against a coplanar wall leaves slivers — triangles of ~4·10⁻⁸ mm²
#: along the seam where the chamfer envelope meets the wall it was cut from. They are
#: real triangles with a real normal and they state a plane the design does not have,
#: so something has to exclude them, and area is the honest discriminant. The threshold
#: is on the **cluster total**, not on one triangle: a plane the design put there is a
#: wall, a floor or a rim and totals whole square millimetres, while a whole seam of
#: slivers totals ~10⁻⁶ mm². 10⁻³ mm² therefore sits three orders above every seam this
#: has produced and three orders below the smallest designed plane, and summing per
#: cluster means float32 export noise scattering a seam over two clusters cannot
#: promote either of them.
MIN_PLANE_AREA_MM2 = 1e-3


class MeasureError(RuntimeError):
    """The geometry does not have the planes the design says it has, or a feature is
    out of tolerance. Either way the finding is the message."""


@dataclass(frozen=True)
class FitsResult:
    """The verdict the millimetre arithmetic returns, with the sum that produced it.

    Mirrors `FitsResult` in `web/src/organizer/spec.ts` field for field.
    """

    fits: bool
    line: str
    basis: str
    remedy: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"fits": self.fits, "line": self.line, "basis": self.basis}
        if self.remedy:
            d["remedy"] = self.remedy
        return d


@dataclass
class CompileResult:
    """What compiling a spec produced: the plate, its parts, and the designed features."""

    archetype: str
    archetype_version: str
    spec_hash: str
    mesh: trimesh.Trimesh
    parts: dict[str, trimesh.Trimesh]
    features: dict[str, float] = field(default_factory=dict)

    def features_document(self) -> dict[str, Any]:
        """The JSON written beside the mesh, and recorded as `generation_params`."""
        return {
            "archetype": self.archetype,
            "archetype_version": self.archetype_version,
            "spec_sha256": self.spec_hash,
            "parts": sorted(self.parts),
            "features": {k: self.features[k] for k in sorted(self.features)},
        }


def manifold_to_trimesh(man: "manifold3d.Manifold") -> trimesh.Trimesh:
    """Export a Manifold's geometry as a Trimesh with its vertices untouched.

    Raises:
        MeasureError: If the solid is empty or the kernel reports an error status.
    """
    status = man.status()
    if status != manifold3d.Error.NoError:
        raise MeasureError(f"the kernel rejected the solid: {status}")
    if man.is_empty():
        raise MeasureError("the solid is empty — the CSG subtracted everything")
    mesh = man.to_mesh64() if hasattr(man, "to_mesh64") else man.to_mesh()
    vertices = np.asarray(mesh.vert_properties, dtype=np.float64)[:, :3]
    faces = np.asarray(mesh.tri_verts, dtype=np.int64)
    return trimesh.Trimesh(vertices, faces, process=False)


# ── shape primitives ───────────────────────────────────────────────────────────

def _positive(name: str, value: float) -> float:
    number = float(value)
    if not np.isfinite(number) or number <= 0.0:
        raise MeasureError(f"{name} must be a positive number of mm, got {value!r}")
    return number


def _segments(circular_segments: int) -> int:
    n = int(circular_segments)
    if n < 4 or n % 4:
        raise MeasureError(
            f"circular_segments must be a positive multiple of 4, got {circular_segments!r}; "
            "a quarter turn has to be a whole number of steps or a chord lands on an axis "
            "and stops being distinguishable from a wall"
        )
    return n


def rounded_rect(
    w: float, d: float, r: float, *, circular_segments: int = CIRCULAR_SEGMENTS
) -> "manifold3d.CrossSection":
    """A `w × d` rectangle in the first quadrant with its four corners rounded to `r`.

    The erode-then-dilate recipe measured on manifold3d 3.5.2 (`ARCHITECTURE.md`, "The
    geometry kernel"): `offset(-r, Round)` pulls each edge in by `r`, `offset(+r, Round)`
    pushes it back out and sweeps a round of radius `r` across every corner. The result
    is watertight and genus 0 once extruded, and — the property `measure()` depends on —
    **each straight edge still runs between its exact tangent points**, `r` and `w − r`,
    because Clipper2 starts and ends the arc there. A corner radius is therefore read
    back off the mesh as a difference of two exact vertices.

    Args:
        w: Extent along X, mm. Positive.
        d: Extent along Y, mm. Positive.
        r: Corner radius, mm. **0 means a square corner**, and returns the rectangle
            with no offset call at all.
        circular_segments: Straight segments per full 360° of round; see
            `CIRCULAR_SEGMENTS`.

    Raises:
        MeasureError: If `w` or `d` is not positive, `r` is negative, `2r` does not fit
            inside the smaller side, or `circular_segments` is not a multiple of 4.
    """
    w = _positive("w", w)
    d = _positive("d", d)
    radius = float(r)
    if not np.isfinite(radius) or radius < 0.0:
        raise MeasureError(f"r must be a radius in mm ≥ 0, got {r!r}")
    square = manifold3d.CrossSection.square([w, d], False)
    if radius == 0.0:
        return square
    if 2.0 * radius > min(w, d) + 1e-9:
        raise MeasureError(
            f"a corner radius of {radius:g} mm does not fit a {w:g} × {d:g} mm rectangle; "
            f"2r must be at most the shorter side ({min(w, d):g} mm)"
        )
    n = _segments(circular_segments)
    return square.offset(-radius, manifold3d.JoinType.Round, 2.0, n).offset(
        radius, manifold3d.JoinType.Round, 2.0, n
    )


def rounded_rect_prism(
    w: float, d: float, h: float, r: float = 0.0, *,
    chamfer_mm: float = 0.0,
    circular_segments: int = CIRCULAR_SEGMENTS,
) -> "manifold3d.Manifold":
    """A `w × d × h` box in the first octant, its four **vertical** edges rounded to `r`
    and its base chamfered by `chamfer_mm`.

    The round is the anti-elephant-foot treatment the audited insert standard calls
    mandatory (roadmap §0.5), and the same call builds an internal one: a cavity is its
    own prism subtracted from a body, so the radius of a pocket's vertical corners is
    just this primitive's `r` on the prism that makes the hole. One shape, one argument —
    there is no separate `r_inner`, because a hollow is a boolean here and not a feature
    of a solid.

    `r = 0` with no chamfer returns `Manifold.cube([w, d, h], False)` — literally the
    call the archetypes made before this function existed, so a spec that asks for
    square corners compiles to the bytes it always did.

    Raises:
        MeasureError: As `rounded_rect` and `base_chamfer`, or if `h` is not positive.
    """
    h = _positive("h", h)
    section = rounded_rect(w, d, r, circular_segments=circular_segments)
    if float(r) == 0.0 and float(chamfer_mm) == 0.0:
        return manifold3d.Manifold.cube([_positive("w", w), _positive("d", d), h], False)
    return base_chamfer(section, h, chamfer_mm, circular_segments=circular_segments)


def _ring(section: "manifold3d.CrossSection", z: float) -> list[list[float]]:
    return [[float(x), float(y), float(z)] for poly in section.to_polygons() for x, y in poly]


def _edge_planes(section: "manifold3d.CrossSection") -> tuple[np.ndarray, np.ndarray]:
    """Outward unit normal and origin distance for every edge of a CCW contour."""
    poly = np.asarray(section.to_polygons()[0], dtype=np.float64)
    edges = np.roll(poly, -1, axis=0) - poly
    normals = np.stack([edges[:, 1], -edges[:, 0]], axis=1)
    lengths = np.linalg.norm(normals, axis=1)
    keep = lengths > 0.0
    normals = normals[keep] / lengths[keep, None]
    return normals, (normals * poly[keep]).sum(axis=1)


#: How far an eroded edge may sit from where the erosion should have put it and still
#: count as the same edge, in mm. Clipper2 offsets on a scaled integer grid and lands
#: ~10⁻⁷ mm off; this is an order above that and four below float32 STL noise.
_EROSION_EPS_MM = 1e-6


def _erosion_keeps_every_edge(
    section: "manifold3d.CrossSection", eroded: "manifold3d.CrossSection", c: float
) -> bool:
    """Whether every edge of `section` is still an edge of `section ⊖ c`.

    Asks each edge whether the erosion still touches its line: `max(n·v)` over the
    eroded contour against `n·a − c`. An edge that survived is attained exactly; one the
    chamfer swallowed leaves the eroded contour strictly inside its line. Asked of the
    *planes* rather than of the vertex counts, because a contour carries collinear
    duplicates and a count would be answering a different question.
    """
    normals, offsets = _edge_planes(section)
    if normals.size == 0:
        return False
    vertices = np.asarray(
        [v for poly in eroded.to_polygons() for v in poly], dtype=np.float64
    )
    if vertices.size == 0:
        return False
    attained = (vertices @ normals.T).max(axis=0)
    return bool(np.all(np.abs(attained - (offsets - c)) <= _EROSION_EPS_MM))


def _chamfered_hull(
    section: "manifold3d.CrossSection",
    eroded: "manifold3d.CrossSection",
    h: float,
    c: float,
) -> "manifold3d.Manifold":
    """One convex hull over three rings: the eroded base, the outline at `c`, the outline
    at `h`. Correct only when every edge survived the erosion — `base_chamfer` knows."""
    return manifold3d.Manifold.hull_points(
        np.asarray(
            _ring(eroded, 0.0) + _ring(section, c) + _ring(section, h), dtype=np.float64
        )
    )


def _chamfered_trims(
    section: "manifold3d.CrossSection", h: float, c: float
) -> "manifold3d.Manifold":
    """The column over `section`, cut by the 45° half-space of every one of its edges.
    The definition, valid for any chamfer height, at one kernel trim per edge.

    Re-hulled at the end, and not for tidiness: a chamfered prism over a convex outline
    *is* convex — a convex extrusion cut by half-spaces — so its convex hull is the same
    solid, and the hull comes back cleanly triangulated where a chain of trims comes back
    carrying a dozen zero-area triangles from the cuts that meet each other. They are the
    triangles `base_chamfer`'s docstring is about, and a hull is the cheapest way to have
    the same volume without them.
    """
    prism = section.extrude(h)
    normals, offsets = _edge_planes(section)
    root_two = math.sqrt(2.0)
    for (nx, ny), p in zip(normals, offsets):
        prism = prism.trim_by_plane([-nx, -ny, 1.0], -(p - c) / root_two)
    return prism.hull()


def base_chamfer(
    section: "manifold3d.CrossSection", h: float, c: float, *,
    circular_segments: int = CIRCULAR_SEGMENTS,
) -> "manifold3d.Manifold":
    """The prism `section × h` standing on `z = 0`, with a 45° chamfer of height `c` cut
    into its base.

    The anti-warp, anti-curl treatment the audited insert standard calls mandatory
    (roadmap §0.5): the first few layers step outward at 45° instead of meeting the bed
    as a sharp corner, so there is no thin edge to lift and no elephant-foot flare to
    fight. `c = 0` returns the plain prism.

    **It takes an outline and builds the part, rather than taking a finished part and
    cutting a chamfer into it**, and both halves of that are load-bearing:

    - *Builds, not cuts.* Every boolean formulation — intersect the solid against a 45°
      envelope, subtract the ring between them, union a frustum onto a trimmed body —
      leaves the kernel retriangulating a tangential seam where the 45° face runs into
      the vertical wall, and it emits zero-area triangles along it, two of whose three
      corners are the same point to within 10⁻¹⁰ mm. Harmless in float64 and fatal after
      export: float32 merges those corners, and the STL comes back with non-manifold
      edges and forty loose bodies. Hulling the chamfer and the wall into existence
      together emits none of them.
    - *The design's outline, not one recovered from the mesh.* `Manifold.slice` and
      `Manifold.project` both rebuild an outline out of triangles and both land ~4·10⁻¹⁰
      mm² off the one the design has — enough, hulled against an exact eroded ring, to
      produce those same near-duplicate vertices. So the caller hands over the
      `CrossSection` it built the part from, and the chamfer is exact because its input
      was.

    A chamfered part is therefore composed the way a printed one is: chamfer the outer
    prism, then cut the cavities into it. `rounded_rect_prism(..., chamfer_mm=c)` is
    that in one call, and `tests/test_deck_box.py` asserts the exported, reloaded plate
    is still one watertight solid so this cannot quietly regress.

    **Every** face of the chamfer is an exact 45° plane, corners included, which is
    worth stating because it is not obvious: eroding a polygon moves each edge inward
    along its own normal by `c`, so each eroded chord is parallel to the chord it came
    from and `c` away from it horizontally and `c` below it, and the plane through the
    pair is at 45° by construction — at a rounded corner exactly as on a straight side.
    What the faceting does cost is the *base* corner radius: it comes out at
    `r − c·sec(π/segments)` rather than `r − c`, 0,003 mm at the defaults, and is not a
    feature anything measures.

    Two constructions build it and they are the same solid wherever both apply. The fast
    one hulls three rings — the eroded base, the outline at `c`, the outline at `h` —
    which is right whenever the erosion keeps every edge of the outline. When the chamfer
    outgrows the corner it runs around an edge vanishes from the erosion, three rings
    stop describing the shape, and the general construction cuts one 45° half-space per
    edge instead: exact for any chamfer height, at ~70 ms a body against 4 ms.

    Args:
        section: The part's outline. One convex contour.
        h: Prism height, mm.
        c: Chamfer height, mm, and therefore the horizontal setback too, the angle being
            45°. **0 returns the plain prism.**
        circular_segments: See `CIRCULAR_SEGMENTS`.

    Raises:
        MeasureError: If `h` is not positive, `c` is negative or at least `h`, the
            outline is not one convex contour, or the chamfer erodes it away entirely.
    """
    h = _positive("h", h)
    chamfer = float(c)
    if not np.isfinite(chamfer) or chamfer < 0.0:
        raise MeasureError(f"the base chamfer must be a height in mm ≥ 0, got {c!r}")
    if chamfer == 0.0:
        return section.extrude(h)
    n = _segments(circular_segments)
    if chamfer >= h:
        raise MeasureError(
            f"a {chamfer:g} mm base chamfer does not fit a prism {h:g} mm tall; "
            "the chamfer must be shorter than the body it is cut into"
        )
    if section.is_empty() or section.num_contour() != 1:
        raise MeasureError(
            f"a base chamfer needs one closed outline, found {section.num_contour()}; "
            "chamfer each body on its own outline, before anything is cut into it"
        )
    area = section.area()
    if abs(section.hull().area() - area) > 1e-9 * max(area, 1.0):
        raise MeasureError(
            "a base chamfer needs a convex outline; this one is not, so the hull that "
            "builds the 45° face would add material the part does not have"
        )
    eroded = section.offset(-chamfer, manifold3d.JoinType.Round, 2.0, n)
    if eroded.is_empty():
        raise MeasureError(
            f"a {chamfer:g} mm base chamfer erodes this outline away entirely; "
            "reduce the chamfer or widen the part"
        )
    if _erosion_keeps_every_edge(section, eroded, chamfer):
        return _chamfered_hull(section, eroded, h, chamfer)
    return _chamfered_trims(section, h, chamfer)


# ── plane reading ──────────────────────────────────────────────────────────────

def plane_set(coords: np.ndarray, tol_mm: float = 1e-3) -> list[float]:
    """The distinct axis-aligned planes in one coordinate column, sorted.

    Values closer than `tol_mm` are one plane (float32 export noise is ~1e-5 mm on a
    100 mm part); values a micron or more apart are two. Returns cluster means.
    """
    values = np.sort(np.asarray(coords, dtype=np.float64).ravel())
    if values.size == 0:
        return []
    planes: list[float] = []
    cluster = [values[0]]
    for v in values[1:]:
        if v - cluster[-1] > tol_mm:
            planes.append(float(np.mean(cluster)))
            cluster = [v]
        else:
            cluster.append(v)
    planes.append(float(np.mean(cluster)))
    return planes


def _triangles(mesh: Any) -> np.ndarray:
    """`(n, 3, 3)` of the mesh's triangle corners, kernel order, nothing merged."""
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    return vertices[faces]


def face_normals(mesh: Any) -> tuple[np.ndarray, np.ndarray]:
    """Unit normal and area per triangle, computed from the vertices themselves.

    Not `trimesh.face_normals`, which normalises degenerate faces to zero and hides how
    small they were: the area is the thing `face_planes` needs, so both come out of the
    one cross product. A triangle with no area gets a zero normal and is excluded from
    every axis by construction.
    """
    tri = _triangles(mesh)
    if tri.size == 0:
        return np.zeros((0, 3)), np.zeros(0)
    cross = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    lengths = np.linalg.norm(cross, axis=1)
    normals = np.zeros_like(cross)
    real = lengths > 0.0
    normals[real] = cross[real] / lengths[real, None]
    return normals, lengths / 2.0


def face_planes(
    mesh: Any,
    axis: int,
    tol_mm: float = 1e-3,
    *,
    min_area_mm2: float = MIN_PLANE_AREA_MM2,
) -> list[float]:
    """The distinct planes perpendicular to `axis` that the mesh's **faces** lie in.

    Reads faces rather than vertices, which `plane_set` over a coordinate column cannot
    do and which the edge treatments made necessary: a vertical fillet puts a ring of
    arc vertices at every coordinate between the tangent point and the corner, and a
    base chamfer puts one at the setback, so a vertex column on a rounded box states
    dozens of X planes where the design has six. A *face* perpendicular to X is a wall,
    and only a wall; an arc chord is 5,625° off-axis and a chamfer facet 45°, so both
    fall outside `AXIS_ALIGNED_COS` and neither is counted.

    Clusters are merged at `tol_mm` like `plane_set`, dropped below `min_area_mm2`
    (see that constant for the seam slivers this excludes), and returned as their
    **area-weighted** mean: a plane is where most of its square millimetres are, not
    where the average of its triangles happens to sit.
    """
    normals, areas = face_normals(mesh)
    if normals.size == 0:
        return []
    selected = (np.abs(normals[:, axis]) >= AXIS_ALIGNED_COS) & (areas > 0.0)
    if not selected.any():
        return []
    tri = _triangles(mesh)[selected]
    coords = tri[:, :, axis].mean(axis=1)
    weights = areas[selected]
    order = np.argsort(coords, kind="stable")
    coords, weights = coords[order], weights[order]
    planes: list[float] = []
    start = 0
    for i in range(1, len(coords) + 1):
        if i < len(coords) and coords[i] - coords[i - 1] <= tol_mm:
            continue
        block, w = coords[start:i], weights[start:i]
        if w.sum() >= min_area_mm2:
            planes.append(float(np.average(block, weights=w)))
        start = i
    return planes


def face_plane_extent(
    mesh: Any,
    axis: int,
    coord: float,
    along: int,
    tol_mm: float = 1e-3,
    *,
    min_area_mm2: float = MIN_PLANE_AREA_MM2,
) -> tuple[float, float]:
    """`(min, max)` along `along` of the faces that lie in the plane `axis = coord`.

    This is how a corner radius is read off a mesh. A wall with a vertical fillet of
    radius `r` runs between its **tangent points**, so the `X` extent of the `Y = 0`
    wall of a rounded box is `[r, w − r]` exactly — the arc that carries the corner is
    a different set of faces, tilted off the axis, and does not belong to this plane at
    all. Subtracting the box's own `X = 0` plane from the left end therefore yields `r`
    as a difference of two exact vertices, which is a plane difference in all but name
    and survives float32 STL, the OBJ/3MF round trip and Phase 3's re-centring the same
    way every other feature here does. A square corner yields exactly 0.

    Raises:
        MeasureError: If no face of any area lies in that plane.
    """
    normals, areas = face_normals(mesh)
    tri = _triangles(mesh)
    if normals.size == 0:
        raise MeasureError(f"the mesh has no faces to measure on {'XYZ'[axis]}")
    on_axis = (np.abs(normals[:, axis]) >= AXIS_ALIGNED_COS) & (areas > 0.0)
    in_plane = on_axis & (np.abs(tri[:, :, axis].mean(axis=1) - float(coord)) <= tol_mm)
    if not in_plane.any() or areas[in_plane].sum() < min_area_mm2:
        raise MeasureError(
            f"no face lies in the plane {'XYZ'[axis]} = {float(coord):.3f} mm, so the "
            f"extent along {'XYZ'[along]} cannot be measured there"
        )
    values = tri[in_plane][:, :, along]
    return float(values.min()), float(values.max())


def tilted_face_extent(
    mesh: Any,
    axis: int = 2,
    *,
    low: float = 0.05,
    high: float = 0.99,
    min_area_mm2: float = MIN_PLANE_AREA_MM2,
) -> tuple[float, float, float]:
    """`(min, max, worst_error_deg)` over the faces that slope against `-axis`.

    How a base chamfer is measured. A chamfer's faces are the only ones on these
    archetypes that point downward without being the bed face itself, so "normal
    component between `-high` and `-low`" isolates them without needing to know the
    angle in advance. `worst_error_deg` is the largest departure from 45° over those
    faces, so a caller asserting the chamfer's angle is asserting something it read
    rather than something it assumed. A body with no such faces has no chamfer and
    returns `(0, 0, 0)` — exactly right for a designed chamfer of 0, and out of
    tolerance for any other.
    """
    normals, areas = face_normals(mesh)
    if normals.size == 0:
        return 0.0, 0.0, 0.0
    component = normals[:, axis]
    sloped = (component <= -low) & (component >= -high) & (areas > min_area_mm2)
    if not sloped.any():
        return 0.0, 0.0, 0.0
    tri = _triangles(mesh)[sloped]
    values = tri[:, :, axis]
    # The face's tilt from vertical: 45° for a chamfer, read off the normal itself.
    angles = np.degrees(np.arccos(np.clip(-component[sloped], -1.0, 1.0)))
    return float(values.min()), float(values.max()), float(np.max(np.abs(angles - 45.0)))


def compare_features(
    designed: dict[str, float],
    measured: dict[str, float],
    tol_mm: float = DEFAULT_TOLERANCE_MM,
) -> dict[str, tuple[float, float, float]]:
    """`{feature: (designed, measured, measured − designed)}` for every designed
    feature that was measured. Features the archetype cannot read off geometry (a
    stack height, say) are simply absent from `measured` and skipped here."""
    return {
        name: (float(designed[name]), float(measured[name]), float(measured[name] - designed[name]))
        for name in sorted(designed)
        if name in measured
    }


@dataclass(frozen=True)
class DimensionReport:
    """Spec → mesh error per feature: the record the pipeline writes beside the mesh.

    `features` maps a name to `(designed_mm, measured_mm, error_mm)` for every required
    feature that was measured; `missing` names required features the archetype could
    not read off this mesh; `out_of_tolerance` names the measured ones whose absolute
    error exceeds `tolerance_mm`. The verdict is derived from those two tuples, so it
    cannot disagree with the rows it summarises.
    """

    tolerance_mm: float
    features: dict[str, tuple[float, float, float]]
    missing: tuple[str, ...] = ()
    out_of_tolerance: tuple[str, ...] = ()

    @property
    def within_tolerance(self) -> bool:
        return not self.missing and not self.out_of_tolerance

    @property
    def max_abs_error_mm(self) -> Optional[float]:
        """The largest absolute error over the measured features, or None if none were."""
        if not self.features:
            return None
        return max(abs(err) for _, _, err in self.features.values())

    def problems(self) -> list[str]:
        """One sentence per finding, in the order a reader fixes them: missing first."""
        out = [f"{name}: not measured" for name in self.missing]
        for name in self.out_of_tolerance:
            want, got, err = self.features[name]
            out.append(f"{name}: designed {want:.3f} mm, measured {got:.3f} mm (error {err:+.3f} mm)")
        return out

    def to_dict(self) -> dict[str, Any]:
        """Plain JSON types. Errors are kept to the micron; the noise floor of a float32
        STL is ~1e-5 mm and rounding it away would report a measurement that was not
        made."""
        return {
            "tolerance_mm": self.tolerance_mm,
            "within_tolerance": self.within_tolerance,
            "features_checked": len(self.features),
            "features_within": len(self.features) - len(self.out_of_tolerance),
            "max_abs_error_mm": (
                None if self.max_abs_error_mm is None else round(self.max_abs_error_mm, 6)
            ),
            "features": {
                name: {
                    "designed_mm": designed,
                    "measured_mm": round(measured, 6),
                    "error_mm": round(error, 6),
                }
                for name, (designed, measured, error) in self.features.items()
            },
            "missing": list(self.missing),
            "out_of_tolerance": list(self.out_of_tolerance),
        }


def check_dimensions(
    designed: dict[str, float],
    measured: dict[str, float],
    tol_mm: float = DEFAULT_TOLERANCE_MM,
    required: Optional[set[str]] = None,
) -> DimensionReport:
    """Compare designed and measured features and report, without raising.

    Args:
        designed: Feature → designed mm (everything the archetype derived).
        measured: Feature → measured mm (everything `measure()` read off the mesh).
        tol_mm: Allowed absolute error per feature.
        required: Features that must be present in `measured`; defaults to all of
            `designed`. An archetype passes its `MEASURED_FEATURES`, because a designed
            feature that is not on the mesh (a stack height) is not a missing one.
    """
    required = set(designed) if required is None else set(required)
    rows = {
        name: values
        for name, values in compare_features(designed, measured, tol_mm).items()
        if name in required
    }
    missing = tuple(sorted(required - set(measured)))
    out = tuple(name for name, (_, _, err) in rows.items() if abs(err) > tol_mm)
    return DimensionReport(
        tolerance_mm=float(tol_mm), features=rows, missing=missing, out_of_tolerance=out,
    )


def assert_features_within(
    designed: dict[str, float],
    measured: dict[str, float],
    tol_mm: float = DEFAULT_TOLERANCE_MM,
    required: Optional[set[str]] = None,
) -> None:
    """Raise `MeasureError` naming every feature outside `tol_mm`, or missing.

    The raising form of `check_dimensions`, for callers that want a verdict and not a
    report. Same arguments.
    """
    report = check_dimensions(designed, measured, tol_mm, required)
    if not report.within_tolerance:
        raise MeasureError("features out of tolerance: " + "; ".join(report.problems()))


def export_stl(mesh: trimesh.Trimesh, path: str | Path) -> Path:
    """Write a binary STL. Deterministic for the same vertices and faces."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    mesh.export(str(path), file_type="stl")
    return path
