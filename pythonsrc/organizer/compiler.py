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
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import numpy as np
import trimesh

from . import lettering

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
    #: Which curated box interior this part was sized against, or None for a typed one.
    #: `{"id", "kb_version", "interior_mm", "sources"}` — set by `archetypes.compile_spec`
    #: off `spec.box`, because the spec knows and a `CompileResult` does not keep one.
    game_box: Optional[dict[str, Any]] = None

    def features_document(self) -> dict[str, Any]:
        """The JSON written beside the mesh, and recorded as `generation_params`.

        `game_box` is present **only** when the spec named one, which is deliberate on
        both sides. A part built to typed millimetres must not carry a key implying a
        curated source, and the omission keeps every `compile_features.json` written
        before the KB existed byte-identical to what it was.
        """
        document = {
            "archetype": self.archetype,
            "archetype_version": self.archetype_version,
            "spec_sha256": self.spec_hash,
            "parts": sorted(self.parts),
            "features": {k: self.features[k] for k in sorted(self.features)},
        }
        if self.game_box is not None:
            document["game_box"] = self.game_box
        return document


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
    for (nx, ny), p in zip(normals, offsets, strict=True):
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


# ── lettering ──────────────────────────────────────────────────────────────────
#
# The kernel half of the decorative tier (F13, issue #157). `lettering.py` has the font
# and the metric arithmetic and no kernel at all, because the api-server has to answer
# "does this fit" with no kernel installed; everything below needs one.

#: How much of a glyph's area a morphological opening must keep before the opened radius
#: still counts as "the stroke survived". See `thinnest_stroke_mm`.
#:
#: 0,80 is not a calibration constant — it is a gap. Opening a shape by `ρ` rounds its
#: convex corners and loses `(4 − π)ρ²` per right angle, which on a glyph is a few per
#: cent; when `ρ` passes half a **stroke's** width that whole stroke vanishes at once and
#: the loss jumps to a fifth of the letter or more. Anything between those two regimes
#: reads the same answer, and `tests/test_lettering.py` pins the one that matters: the
#: `H` of this font measures its design stem, 385/2048 em, to the micron.
STROKE_COVERAGE = 0.80

#: How far a raised slab is sunk *into* the face it stands on, mm.
#:
#: The `base_chamfer` lesson restated, in the other direction: a boolean between two
#: solids that merely touch on a plane leaves the kernel retriangulating a coplanar seam,
#: and it emits near-degenerate triangles that float32 export then merges into
#: non-manifold edges. A transverse overlap has no seam to retriangulate. A tenth of a
#: millimetre is half a layer — it changes no measured feature and it is four orders
#: above the kernel's own float noise.
LETTER_SINK_MM = 0.1

#: How far a recessing cutter stands **proud** of the face it cuts into, mm. The
#: cavity-overshoot idiom every archetype here already cuts its pockets with (`+1.0` on
#: the deck box's cavity), for the same reason: a cutter flush with the surface is a
#: coplanar boolean.
LETTER_OVERSHOOT_MM = 1.0

#: The two things an emboss can be. `raised` unions a slab onto the face, `recessed`
#: subtracts one out of it; `spec.EMBOSS_MODES` is the same tuple and
#: `tests/test_composer_options.py` binds it to the composer's.
LETTER_MODES: tuple[str, str] = ("raised", "recessed")

#: How far outside the ink a measurer's exclusion region reaches, mm. A quarter of a
#: millimetre: five times the float32 STL noise on a 200 mm plate and a quarter of the
#: `EMBOSS_EDGE_MARGIN_MM` the fit rule keeps clear, so the box always sits inside the
#: face it is cut from and never swallows the face's own edge.
LETTER_REGION_PAD_MM = 0.25


@dataclass(frozen=True)
class FaceFrame:
    """Where on a part the lettering goes, and which way round it reads.

    The archetype supplies this and nothing else about the decoration: it is the one
    piece of the emboss that is a fact about *that shape*. Everything downstream — the
    outline, the slab, the boolean, the measurement region — is the same code for every
    face of every archetype, which is what keeps a second decorated archetype from
    growing a second spelling of "0,6 mm deep".

    Attributes:
        face: The `spec.EMBOSS_FACES` name, carried so a refusal can say which face.
        part: Which body of the compile result the face belongs to, e.g. `"lid"`.
        origin: The **centre** of the usable rectangle, in the part's own mm frame.
        u: Unit vector along the text's reading direction.
        v: Unit vector along the text's up direction.
        normal: Unit outward normal of the face. `u × v` by construction — asserted,
            because a left-handed frame mirrors every letter and nothing else about the
            mesh would look wrong.
        width_mm: Usable extent along `u`: the flat face, inset by its corner radius,
            its base chamfer and `EMBOSS_EDGE_MARGIN_MM`.
        height_mm: Usable extent along `v`, inset the same way.
        modes: Which of `LETTER_MODES` this face honours. A face that is against the
            bed, or vertical, honours `recessed` only — see `archetypes/common.py`
            `lettering_problems`.
        material_mm: How much material stands behind the face, mm — what a recess eats
            into.
        material_name: The spec path that number comes from, e.g. `"lid.top_mm"`, so a
            refusal names the field a person would change.
        material_floor_mm: How little of it may be left, mm.
    """

    face: str
    part: str
    origin: tuple[float, float, float]
    u: tuple[float, float, float]
    v: tuple[float, float, float]
    normal: tuple[float, float, float]
    width_mm: float
    height_mm: float
    modes: tuple[str, ...]
    material_mm: float
    material_name: str
    material_floor_mm: float

    @property
    def normal_axis(self) -> int:
        """0, 1 or 2 — which world axis the face's normal lies on.

        Every face of every archetype here is axis-aligned, so this is always defined;
        the relief is measured as a difference of two planes on this axis, whichever face
        and whichever mode.
        """
        return int(np.argmax(np.abs(np.asarray(self.normal, dtype=np.float64))))

    def matrix(self) -> np.ndarray:
        """The 3 × 4 affine that carries a slab built in `XY × +Z` onto this face.

        manifold3d's `transform` reads the first three columns as the images of the local
        x, y and z axes and the fourth as the translation, so the frame *is* the matrix:
        `[u | v | n | origin]`.
        """
        u = np.asarray(self.u, dtype=np.float64)
        v = np.asarray(self.v, dtype=np.float64)
        n = np.asarray(self.normal, dtype=np.float64)
        if abs(np.linalg.norm(np.cross(u, v) - n)) > 1e-9:
            raise MeasureError(
                f"the {self.face!r} frame is left-handed (u × v ≠ n); every letter on it "
                "would read backwards"
            )
        return np.column_stack([u, v, n, np.asarray(self.origin, dtype=np.float64)])

    def region_mm(
        self,
        ink_width_mm: float,
        ink_height_mm: float,
        relief_mm: float,
        mode: str,
        *,
        pad_mm: float = LETTER_REGION_PAD_MM,
    ) -> "Box":
        """The axis-aligned box the decoration occupies, in the part's own mm frame.

        What `face_planes(..., exclude_mm=…)` drops so a plane count stays the design's,
        and what `face_planes_within` reads the relief back out of. Axis-aligned because
        every frame here is — `u`, `v` and `n` are ± unit axes on all six faces — so the
        box is exactly the ink rectangle swept through the relief, padded by `pad_mm` on
        every side because the *design*'s region has to contain the *mesh*'s faces after
        float32 has rounded them.

        It is the **ink** box and not the usable rectangle, which is the difference
        between a measurer that still works and one that does not: the face's own plane
        runs right up to the part's edge, and excluding the whole rectangle would take
        that plane out of the count along with the decoration. The `EMBOSS_EDGE_MARGIN_MM`
        the fit rule keeps clear is exactly the room this box needs to sit inside.
        """
        low = [0.0, 0.0, 0.0]
        high = [0.0, 0.0, 0.0]
        half_u, half_v = float(ink_width_mm) / 2.0, float(ink_height_mm) / 2.0
        near, far = (
            (-LETTER_SINK_MM, float(relief_mm)) if mode == "raised"
            else (-float(relief_mm), LETTER_SINK_MM)
        )
        for axis in range(3):
            extents = [
                self.u[axis] * s + self.v[axis] * t + self.normal[axis] * w
                for s in (-half_u, half_u)
                for t in (-half_v, half_v)
                for w in (near, far)
            ]
            low[axis] = self.origin[axis] + min(extents) - pad_mm
            high[axis] = self.origin[axis] + max(extents) + pad_mm
        return ((low[0], high[0]), (low[1], high[1]), (low[2], high[2]))


def text_outline(text: str, cap_height_mm: float) -> "manifold3d.CrossSection":
    """The glyphs of `text` as one cross-section in mm, centred on the origin.

    `FillRule.NonZero`, and not `EvenOdd`: TrueType winds an outer contour opposite to
    the counter inside it, so non-zero fills the letter and punches the hole — while an
    even-odd read of a *composite* glyph (every accented character in this font) would
    punch a hole wherever the base letter and its accent happen to overlap.

    `simplify` at 1 µm afterwards, for `base_chamfer`'s reason one step earlier in the
    pipeline: flattening a curve at a fixed segment count leaves collinear and
    near-duplicate vertices, and a pair of vertices a nanometre apart in float64 is one
    vertex in the float32 STL — which is how a watertight solid comes back with a
    non-manifold edge. 1 µm is the schema's own rounding (`spec.MM_DECIMALS`) and four
    orders under N1.

    Raises:
        lettering.LetteringError: If the font cannot set the text.
        MeasureError: If the text has no ink at all — a caller asking for the outline of
            a space has a bug, and an empty cross-section would union to nothing and be
            found three phases later.
    """
    contours = lettering.text_contours(text, cap_height_mm)
    if not contours:
        raise MeasureError(
            f"{text!r} sets no ink at this size, so there is no outline to build; "
            "an emboss must carry at least one glyph that marks the part"
        )
    section = manifold3d.CrossSection(
        [np.asarray(contour, dtype=np.float64) for contour in contours],
        manifold3d.FillRule.NonZero,
    )
    return section.simplify(1e-3)


@lru_cache(maxsize=512)
def _stroke_em(character: str) -> float:
    """The character's thinnest stroke as a fraction of the em, by opening.

    **Why an opening and not a distance.** The obvious measurement — the smallest
    distance from any point of the outline to the material on the other side — is the
    wrong one, and wrong in a way that would refuse every real font: a tapered terminal
    or a cut corner has a *local* thickness that goes to zero at its tip. No slicer cares.
    What a slicer cares about is whether a whole **stroke** is narrower than one
    extrusion, and that is exactly what a morphological opening answers: erode by `ρ`,
    dilate by `ρ`, and everything narrower than `2ρ` is gone while everything wider is
    back. Bisect `ρ` for the largest that still keeps `STROKE_COVERAGE` of the area, and
    `2ρ` is the stroke.

    Cached per character and measured **per glyph**, never over a whole word: the gap
    between two letters is not a stroke of either, and opening `"II"` as one shape would
    report the word spacing.

    Returns `inf` for a character with no ink, which is right — a space has no stroke,
    and `min()` over the word then ignores it.
    """
    contours = lettering.glyph_contours(character)
    if not contours:
        return math.inf
    per_em = 1.0 / lettering.units_per_em()
    section = manifold3d.CrossSection(
        [np.asarray(contour, dtype=np.float64) * per_em for contour in contours],
        manifold3d.FillRule.NonZero,
    )
    area = section.area()
    if area <= 0.0:
        return math.inf
    low, high = 0.0, 0.5  # no stroke of a glyph is half an em wide
    for _ in range(16):
        mid = (low + high) / 2.0
        eroded = section.offset(-mid, manifold3d.JoinType.Round, 2.0, CIRCULAR_SEGMENTS)
        kept = (
            0.0 if eroded.is_empty()
            else eroded.offset(mid, manifold3d.JoinType.Round, 2.0, CIRCULAR_SEGMENTS).area()
        )
        if kept >= STROKE_COVERAGE * area:
            low = mid
        else:
            high = mid
    return 2.0 * low


def thinnest_stroke_mm(text: str, cap_height_mm: float) -> float:
    """The narrowest stroke any glyph of `text` has at this cap height, in mm.

    The number the printability floor is enforced against: a raised stroke thinner than
    one extrusion is a fin the nozzle cannot lay, and a recessed one narrower than a line
    width is a slot the slicer fills in. Both come out as a part that does not carry the
    name it was printed for, which is the only thing this feature is for.

    `inf` for text with no ink — a caller that got there has already been refused by
    `text_outline`.
    """
    scale = lettering.scale_for(cap_height_mm) * lettering.units_per_em()
    strokes = [_stroke_em(c) for c in lettering.distinct_inked_characters(text)]
    return min(strokes) * scale if strokes else math.inf


def letter(
    solid: "manifold3d.Manifold",
    section: "manifold3d.CrossSection",
    frame: FaceFrame,
    relief_mm: float,
    mode: str,
) -> "manifold3d.Manifold":
    """`solid` with `section` raised on or recessed into the face `frame` describes.

    One function for both modes and all six faces, because the difference between them is
    three numbers and a sign — and two spellings of "0,6 mm of relief" is how a lid and a
    divider end up decorated to different depths.

    **Neither boolean is ever coplanar with the face.** A raised slab starts
    `LETTER_SINK_MM` *below* the surface and a recessing cutter stands
    `LETTER_OVERSHOOT_MM` proud of it, so in both directions the operands overlap
    transversely and the kernel has no tangential seam to retriangulate — `base_chamfer`
    has the measurement of what happens when it does. It is also what makes
    `expected_components` safe: every glyph intersects the body it decorates, so a raised
    letter cannot float off as a body of its own.

    Raises:
        MeasureError: For an unknown mode, a non-positive relief, or a left-handed frame.
    """
    if mode not in LETTER_MODES:
        raise MeasureError(f"an emboss is {' or '.join(LETTER_MODES)}, got {mode!r}")
    relief = _positive("the emboss relief", relief_mm)
    matrix = frame.matrix()
    if mode == "raised":
        slab = section.extrude(relief + LETTER_SINK_MM).translate([0.0, 0.0, -LETTER_SINK_MM])
        return solid + slab.transform(matrix)
    slab = section.extrude(relief + LETTER_OVERSHOOT_MM).translate([0.0, 0.0, -relief])
    return solid - slab.transform(matrix)


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


#: A box in mm as `((x_min, x_max), (y_min, y_max), (z_min, z_max))`.
Box = tuple[tuple[float, float], tuple[float, float], tuple[float, float]]


def _outside(tri: np.ndarray, exclude_mm: Optional[Box]) -> np.ndarray:
    """A mask over triangles: True for those whose centroid is **not** in `exclude_mm`.

    What decoration costs the measurers, and the whole of it. A raised glyph's top is a
    real Z plane and the stems of `I`, `L`, `T` and `E` are real axis-aligned walls, so a
    lettered part genuinely *has* more planes than its design says — and a measurement
    that counted them would report a `MeasureError` about geometry that is exactly right.
    Decoration is not a designed feature (issue #157: "must not break
    `expected_components=1` or move a measured dimension"), so the region it occupies is
    excluded and every count below is the count the undecorated part had.

    The centroid is the test rather than any overlap, for `face_planes`' reason: a face
    is one triangle's worth of plane, and a triangle is in the region or it is not.
    """
    if exclude_mm is None:
        return np.ones(len(tri), dtype=bool)
    centroids = tri.mean(axis=1)
    inside = np.ones(len(tri), dtype=bool)
    for i, (low, high) in enumerate(exclude_mm):
        inside &= (centroids[:, i] >= float(low)) & (centroids[:, i] <= float(high))
    return ~inside


def face_planes(
    mesh: Any,
    axis: int,
    tol_mm: float = 1e-3,
    *,
    min_area_mm2: float = MIN_PLANE_AREA_MM2,
    exclude_mm: Optional[Box] = None,
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

    `exclude_mm` drops a region from the read — see `_outside`. It is how a decorated
    part still measures as the part it was designed to be.
    """
    normals, areas = face_normals(mesh)
    if normals.size == 0:
        return []
    tri = _triangles(mesh)
    selected = (
        (np.abs(normals[:, axis]) >= AXIS_ALIGNED_COS)
        & (areas > 0.0)
        & _outside(tri, exclude_mm)
    )
    return _cluster_planes(tri, areas, selected, axis, tol_mm, min_area_mm2)


def _cluster_planes(
    tri: np.ndarray,
    areas: np.ndarray,
    selected: np.ndarray,
    axis: int,
    tol_mm: float,
    min_area_mm2: float,
) -> list[float]:
    """The clustering half of `face_planes`, shared with `face_planes_within`.

    Selection is the caller's — which faces count as being on this axis, and (for a
    region read) which lie inside it — and everything after it is the same arithmetic in
    both: sort by coordinate, merge at `tol_mm`, drop a cluster under `min_area_mm2`, and
    return each survivor's **area-weighted** mean. One spelling, because a region read
    whose clusters merged differently from a global one would put two answers to "where
    is this plane" in one measurer.
    """
    if not selected.any():
        return []
    coords = tri[selected][:, :, axis].mean(axis=1)
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


def face_planes_within(
    mesh: Any,
    axis: int,
    box_mm: tuple[tuple[float, float], tuple[float, float], tuple[float, float]],
    tol_mm: float = 1e-3,
    *,
    min_area_mm2: float = MIN_PLANE_AREA_MM2,
) -> list[float]:
    """`face_planes`, restricted to the triangles whose centroid lies inside `box_mm`.

    What a **ragged** layout has to be measured with, and the reason it can be built at
    all. `face_planes` over a whole mesh answers "which planes does this part have",
    which is the right question for a regular grid — a token tray's `2n + 2` planes per
    axis *are* its grid — and the wrong one the moment two compartments in the same row
    have different depths: one well's back face is then a Y plane nothing else shares,
    and a global read cannot tell it from an artefact. `token_tray`'s docstring names
    that as the reason its grid is regular, and this is the answer to it.

    The **design supplies the region and the mesh supplies the numbers**, which is the
    whole of what keeps this a measurement. An archetype hands in the box it believes one
    compartment occupies, widened by a fraction of a wall; what comes back is whatever
    faces are actually there. A wall in the wrong place therefore reads as a wrong
    *number* while the region still contains it, and as a `MeasureError` — no planes, or
    more than the design says — once it has moved further than that. Neither outcome is
    "within tolerance", which is the only outcome that would be a lie.

    The centroid is the test rather than any overlap, for `face_planes`' reason: a face
    is one triangle's worth of plane, and a triangle is in the region or it is not.

    Args:
        mesh: A mesh (or mesh body) with `vertices` and `faces` arrays.
        axis: 0, 1 or 2 for X, Y or Z.
        box_mm: `((x_min, x_max), (y_min, y_max), (z_min, z_max))`, inclusive, mm.
        tol_mm: Cluster width, as `face_planes`.
        min_area_mm2: Cluster area floor, as `face_planes`.

    Returns:
        The distinct planes perpendicular to `axis` among those triangles, sorted.
        Empty when the region holds no face of any area on that axis.
    """
    normals, areas = face_normals(mesh)
    if normals.size == 0:
        return []
    tri = _triangles(mesh)
    centroids = tri.mean(axis=1)
    inside = np.ones(len(tri), dtype=bool)
    for i, (low, high) in enumerate(box_mm):
        inside &= (centroids[:, i] >= float(low)) & (centroids[:, i] <= float(high))
    selected = inside & (np.abs(normals[:, axis]) >= AXIS_ALIGNED_COS) & (areas > 0.0)
    return _cluster_planes(tri, areas, selected, axis, tol_mm, min_area_mm2)


def face_plane_extent(
    mesh: Any,
    axis: int,
    coord: float,
    along: int,
    tol_mm: float = 1e-3,
    *,
    min_area_mm2: float = MIN_PLANE_AREA_MM2,
    exclude_mm: Optional[Box] = None,
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
    on_axis = (
        (np.abs(normals[:, axis]) >= AXIS_ALIGNED_COS)
        & (areas > 0.0)
        & _outside(tri, exclude_mm)
    )
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
    exclude_mm: Optional["Box"] = None,
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

    `exclude_mm` is not optional politeness here — it is load-bearing for a decorated
    part. "Points downward without being the bed face" isolates a chamfer on an
    *undecorated* archetype and stops doing so the moment a glyph is sunk into a vertical
    wall: the top of the bowl of an `o` or a `C` is a downward-facing face at every angle
    between 8° and 87°, and it would be read as a chamfer 41° out of true. The decoration
    is excluded for the reason it is excluded everywhere else — it is not a designed
    feature and its faces are not the ones being measured.
    """
    normals, areas = face_normals(mesh)
    if normals.size == 0:
        return 0.0, 0.0, 0.0
    component = normals[:, axis]
    sloped = (
        (component <= -low)
        & (component >= -high)
        & (areas > min_area_mm2)
        & _outside(_triangles(mesh), exclude_mm)
    )
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
