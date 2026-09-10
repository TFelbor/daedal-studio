"""Deck box, version 1: a body with a lip and a lift-off lid, from box CSG.

The first archetype, and the product thesis in one testable artifact: a spec compiles
to a mesh whose every dimension is *designed*, and every one of those dimensions can
be read back off the geometry by `measure()`. Nothing after this module scales the
part — it enters Phase 3 with `--no-scale` because these millimetres are the deliverable.

Two parts on one plate, both flat on Z = 0, no overhangs anywhere:

- **Body** — an open-top box with a floor. Its top `lid.height_mm` is a **lip**: the
  outer wall steps in by `lid.wall_mm + lid.clearance_mm` per side, so the lid sits
  flush with the body below it.
- **Lid** — an inverted tray printed open side up, `PLATE_GAP_MM` to +X of the body.

Cards stand upright: width along X, stack along Y, height along Z. With `n, pitch,
(fw, fh)` from `resolve_stack`, `w, f, cc, ss` from `process`, `lh, lw, lc, lt` from `lid`:

    cavity_w   = fw + cc            cavity_d   = n·pitch + ss        cavity_h = fh + cc
    external_w = cavity_w + 2w      external_d = cavity_d + 2w       body_h   = cavity_h + f
    lip_inset  = lw + lc            lip_wall   = w − lip_inset
    lip_outer  = external − 2·lip_inset          lid_cavity = external − 2·lw = lip_outer + 2·lc
    lid_h      = lh + lt            external_h (assembled) = body_h + lt

The one tolerance-critical surface is the lid cavity over the lip: `lid.clearance_mm`
per side. That is the number a test-fit coupon (F12) will print first.

Rules that belong to this *shape* rather than to specs in general — exactly one
compartment, a lift-off lid without magnets, no `divider` section, a lip no thinner than
`process.min_feature_mm`, a lid shorter than the cavity — are checked here and refused
with the remedy named. Ignoring an unsupported field would print a different box than
the one asked for, silently. The rules that are not about deck boxes — the
compartment count, the plane-count assertion, the view row — come from
`common.py`, which exists so the second archetype states them in the same words.

Authored in Claude Code against `manifold3d` directly (roadmap §0.2's "authored with
text-to-cad, source frozen"): text-to-cad drives build123d on OCCT, which the kernel
decision defers; what is borrowed is its measure/align discipline.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import manifold3d

from ..compiler import CompileResult, FitsResult, MeasureError, manifold_to_trimesh
from ..dimensions import ResolvedStack, resolve_stack
from ..spec import CardStack, Compartment, Lid, OrganizerSpec, SpecError, spec_hash
from .common import expect_planes, single_compartment_problem, view_row

ARCHETYPE = "deck_box"
#: Bumped when the geometry a given spec produces changes. Recorded on every job.
ARCHETYPE_VERSION = "1"
#: Clear space between the body and the lid on the plate, mm.
PLATE_GAP_MM = 10.0
#: How this archetype names itself in a refusal or a measurement finding.
_SUBJECT = f"a deck box v{ARCHETYPE_VERSION}"


@dataclass(frozen=True)
class DeckBoxDimensions:
    """Every derived dimension, in mm, from one spec. Pure arithmetic — no kernel."""

    stack: ResolvedStack
    cavity_w: float
    cavity_d: float
    cavity_h: float
    external_w: float
    external_d: float
    body_h: float
    lip_inset: float
    lip_wall: float
    lip_outer_w: float
    lip_outer_d: float
    lid_cavity_w: float
    lid_cavity_d: float
    lid_h: float
    external_h: float

    def features(self, spec: OrganizerSpec) -> dict[str, float]:
        """The designed features by name. `measure()` reads the same names back."""
        lid = spec.lid
        p = spec.process
        assert lid is not None  # validated before derive() is reached
        raw = {
            "cavity_width_mm": self.cavity_w,
            "cavity_depth_mm": self.cavity_d,
            "cavity_height_mm": self.cavity_h,
            "external_width_mm": self.external_w,
            "external_depth_mm": self.external_d,
            "external_height_mm": self.external_h,
            "body_height_mm": self.body_h,
            "floor_mm": p.floor_mm,
            "wall_mm": p.wall_mm,
            "lip_height_mm": lid.height_mm,
            "lip_wall_mm": self.lip_wall,
            "lip_outer_width_mm": self.lip_outer_w,
            "lip_outer_depth_mm": self.lip_outer_d,
            "lid_cavity_width_mm": self.lid_cavity_w,
            "lid_cavity_depth_mm": self.lid_cavity_d,
            "lid_cavity_height_mm": lid.height_mm,
            "lid_height_mm": self.lid_h,
            "lid_wall_mm": lid.wall_mm,
            "lid_clearance_mm": lid.clearance_mm,
            "stack_height_mm": self.stack.stack_height_mm,
        }
        return {k: round(float(v), 3) for k, v in raw.items()}


def _structural_problems(spec: OrganizerSpec) -> list[str]:
    problems: list[str] = []
    if spec.archetype != ARCHETYPE:
        problems.append(f"archetype {spec.archetype!r} is not {ARCHETYPE!r}")
    one = single_compartment_problem(
        spec, subject=f"deck_box v{ARCHETYPE_VERSION}", holds="the deck"
    )
    if one:
        problems.append(one)
    if spec.divider is not None:
        problems.append(
            f"deck_box v{ARCHETYPE_VERSION} has no divider plate; the divider section "
            "belongs to archetype 'card_divider' — remove it or change the archetype"
        )
    if spec.lid is None:
        problems.append(f"deck_box v{ARCHETYPE_VERSION} needs a lid (lid is null)")
    else:
        if spec.lid.kind != "lift_off":
            problems.append(
                f"deck_box v{ARCHETYPE_VERSION} supports lid.kind 'lift_off' only, got {spec.lid.kind!r}"
            )
        if spec.lid.magnets:
            problems.append(
                f"deck_box v{ARCHETYPE_VERSION} has no magnet pockets; a magnetic lid is a "
                "later archetype variant — set lid.magnets to false"
            )
    return problems


def derive(spec: OrganizerSpec) -> DeckBoxDimensions:
    """Every dimension the geometry is built from. Assumes `_structural_problems` is empty."""
    stack_spec: CardStack = spec.compartments[0].contents
    stack = resolve_stack(stack_spec.count, stack_spec.card, stack_spec.sleeving)
    p = spec.process
    lid = spec.lid
    assert lid is not None
    cavity_w = stack.footprint_w_mm + p.cavity_clearance_mm
    cavity_d = stack.stack_height_mm + p.stack_slack_mm
    cavity_h = stack.footprint_h_mm + p.cavity_clearance_mm
    external_w = cavity_w + 2 * p.wall_mm
    external_d = cavity_d + 2 * p.wall_mm
    body_h = cavity_h + p.floor_mm
    lip_inset = lid.wall_mm + lid.clearance_mm
    lip_wall = p.wall_mm - lip_inset
    lip_outer_w = external_w - 2 * lip_inset
    lip_outer_d = external_d - 2 * lip_inset
    lid_cavity_w = external_w - 2 * lid.wall_mm
    lid_cavity_d = external_d - 2 * lid.wall_mm
    lid_h = lid.height_mm + lid.top_mm
    external_h = body_h + lid.top_mm

    def r(x: float) -> float:  # every value to 1 µm, like the schema
        return round(float(x), 3)

    return DeckBoxDimensions(
        stack=stack,
        cavity_w=r(cavity_w), cavity_d=r(cavity_d), cavity_h=r(cavity_h),
        external_w=r(external_w), external_d=r(external_d), body_h=r(body_h),
        lip_inset=r(lip_inset), lip_wall=r(lip_wall),
        lip_outer_w=r(lip_outer_w), lip_outer_d=r(lip_outer_d),
        lid_cavity_w=r(lid_cavity_w), lid_cavity_d=r(lid_cavity_d),
        lid_h=r(lid_h), external_h=r(external_h),
    )


def validate(spec: OrganizerSpec) -> None:
    """Refuse a spec this archetype cannot honour, naming every problem and its remedy.

    Raises:
        SpecError: With every archetype-level problem.
    """
    problems = _structural_problems(spec)
    if problems:
        raise SpecError(problems)
    d = derive(spec)
    lid = spec.lid
    assert lid is not None
    if d.lip_wall < spec.process.min_feature_mm:
        problems.append(
            f"the lip wall would be {d.lip_wall:.3f} mm (process.wall_mm {spec.process.wall_mm:g} − "
            f"lid.wall_mm {lid.wall_mm:g} − lid.clearance_mm {lid.clearance_mm:g}), below "
            f"process.min_feature_mm {spec.process.min_feature_mm:g}; thicken the body wall, "
            "thin the lid wall, or reduce the clearance"
        )
    if lid.height_mm >= d.cavity_h:
        problems.append(
            f"lid.height_mm {lid.height_mm:g} must be less than the cavity height "
            f"{d.cavity_h:.3f} mm, or the lip would cut into the floor"
        )
    if problems:
        raise SpecError(problems)


def build(spec: OrganizerSpec) -> tuple[dict[str, "manifold3d.Manifold"], DeckBoxDimensions]:
    """Validate, derive, and build the two solids in plate position."""
    validate(spec)
    d = derive(spec)
    p = spec.process
    lid = spec.lid
    assert lid is not None

    def cube(x: float, y: float, z: float) -> "manifold3d.Manifold":
        return manifold3d.Manifold.cube([x, y, z], False)

    W, D = d.external_w, d.external_d
    # Body: the outer block minus the cavity (open through the top: +1 mm overshoot).
    body = cube(W, D, d.body_h) - cube(d.cavity_w, d.cavity_d, d.cavity_h + 1.0).translate(
        [p.wall_mm, p.wall_mm, p.floor_mm]
    )
    # Lip: remove the outer band of the top `lid.height_mm`. The band is a slab over
    # the lip height (overshooting the top) minus the lip's own outline (overshooting
    # both ways), so exactly the perimeter strip of width `lip_inset` is cut.
    band = cube(W, D, lid.height_mm + 1.0).translate([0.0, 0.0, d.body_h - lid.height_mm]) - cube(
        d.lip_outer_w, d.lip_outer_d, lid.height_mm + 3.0
    ).translate([d.lip_inset, d.lip_inset, d.body_h - lid.height_mm - 1.0])
    body = body - band
    # Lid: an inverted tray. Its cavity is the lip outline plus the clearance per side,
    # `lid.height_mm` deep (open through the top when printed open side up).
    lid_part = cube(W, D, d.lid_h) - cube(d.lid_cavity_w, d.lid_cavity_d, lid.height_mm + 1.0).translate(
        [lid.wall_mm, lid.wall_mm, lid.top_mm]
    )
    lid_part = lid_part.translate([W + PLATE_GAP_MM, 0.0, 0.0])
    return {"body": body, "lid": lid_part}, d


def compile(spec: OrganizerSpec) -> CompileResult:  # noqa: A001 — the registry's verb
    """Spec → plate mesh, parts, designed features."""
    solids, d = build(spec)
    parts = {name: manifold_to_trimesh(solid) for name, solid in solids.items()}
    plate = manifold_to_trimesh(solids["body"] + solids["lid"])
    return CompileResult(
        archetype=ARCHETYPE,
        archetype_version=ARCHETYPE_VERSION,
        spec_hash=spec_hash(spec),
        mesh=plate,
        parts=parts,
        features=d.features(spec),
    )


def example() -> OrganizerSpec:
    """A 100-card double-sleeved Commander deck box with the default process."""
    return OrganizerSpec(
        archetype=ARCHETYPE,
        compartments=(Compartment(CardStack(count=100, card="standard", sleeving="double")),),
        lid=Lid(),
    )


#: Features `measure()` reads off geometry. `stack_height_mm` is designed only — a card
#: stack is not on the mesh — so it is the one designed feature deliberately absent here.
MEASURED_FEATURES: tuple[str, ...] = (
    "cavity_width_mm", "cavity_depth_mm", "cavity_height_mm",
    "external_width_mm", "external_depth_mm", "external_height_mm",
    "body_height_mm", "floor_mm", "wall_mm",
    "lip_height_mm", "lip_wall_mm", "lip_outer_width_mm", "lip_outer_depth_mm",
    "lid_cavity_width_mm", "lid_cavity_depth_mm", "lid_cavity_height_mm",
    "lid_height_mm", "lid_wall_mm", "lid_clearance_mm",
)


def _planes(part: Any, axis: int, expected: int, what: str) -> list[float]:
    return expect_planes(part, axis, expected, what=what, subject=_SUBJECT)


def measure(mesh: Any) -> dict[str, float]:
    """Read the designed features back off a deck-box mesh — compiled or post-Phase-3.

    Splits the plate into its two bodies (the body is the larger by volume), takes the
    distinct axis-aligned planes of each, and reads every feature as a difference of
    planes. A plane count that does not match the design is a `MeasureError`: geometry
    that does not have the planes the design says it has *is* the finding.

    Raises:
        MeasureError: If the mesh is not two bodies with the deck box's plane structure.
    """
    parts = mesh.split(only_watertight=False)
    if len(parts) != 2:
        raise MeasureError(f"expected 2 bodies (body and lid), found {len(parts)}")
    body, lid = sorted(parts, key=lambda p: p.volume, reverse=True)
    # Body planes: X and Y each {0, lip_inset, wall, wall + cavity, W − lip_inset, W};
    # Z {0, floor, body_h − lip_height, body_h}.
    bx = _planes(body, 0, 6, "body")
    by = _planes(body, 1, 6, "body")
    bz = _planes(body, 2, 4, "body")
    # Lid planes: X and Y each {0, lid_wall, W − lid_wall, W}; Z {0, top, top + height}.
    lx = _planes(lid, 0, 4, "lid")
    ly = _planes(lid, 1, 4, "lid")
    lz = _planes(lid, 2, 3, "lid")
    lid_cavity_w = lx[2] - lx[1]
    lip_outer_w = bx[4] - bx[1]
    measured = {
        "external_width_mm": bx[5] - bx[0],
        "external_depth_mm": by[5] - by[0],
        "body_height_mm": bz[3] - bz[0],
        "floor_mm": bz[1] - bz[0],
        "lip_height_mm": bz[3] - bz[2],
        "cavity_width_mm": bx[3] - bx[2],
        "cavity_depth_mm": by[3] - by[2],
        "cavity_height_mm": bz[3] - bz[1],
        "lip_outer_width_mm": lip_outer_w,
        "lip_outer_depth_mm": by[4] - by[1],
        "wall_mm": bx[2] - bx[0],
        "lip_wall_mm": bx[2] - bx[1],
        "lid_cavity_width_mm": lid_cavity_w,
        "lid_cavity_depth_mm": ly[2] - ly[1],
        "lid_cavity_height_mm": lz[2] - lz[1],
        "lid_height_mm": lz[2] - lz[0],
        "lid_wall_mm": lx[1] - lx[0],
        "lid_clearance_mm": (lid_cavity_w - lip_outer_w) / 2.0,
        "external_height_mm": (bz[3] - bz[0]) + (lz[1] - lz[0]),
    }
    return {k: float(v) for k, v in measured.items()}


def fits_check(spec: OrganizerSpec) -> FitsResult:
    """The millimetre arithmetic, and whether the result fits its external constraint.

    Without a constraint the deck fits its own cavity by construction — the cavity is
    derived from the stack — and the sum is still returned, because the sum *is* the
    value: it is what a person checks against their own callipers. With
    `constraints.max_external_mm`, each assembled external dimension is compared and a
    failing remedy names the axis, the overshoot and the card count that would fit.
    """
    validate(spec)
    d = derive(spec)
    s = d.stack
    line = (
        f"{s.count} × {s.pitch_mm:g} mm = {s.stack_height_mm:g} mm stack · "
        f"internal {d.cavity_d:g} mm · "
        f"external {d.external_w:g} × {d.external_d:g} × {d.external_h:g} mm"
    )
    fits = s.stack_height_mm <= d.cavity_d
    remedy = None
    limit = spec.constraints.max_external_mm
    if limit is not None:
        over = [
            (axis, extent, maximum)
            for axis, extent, maximum in zip(
                ("width", "depth", "height"), (d.external_w, d.external_d, d.external_h), limit
            )
            if extent > maximum + 1e-9
        ]
        if over:
            fits = False
            notes = [
                f"external {axis} {extent:g} mm exceeds {maximum:g} mm by {extent - maximum:.1f} mm"
                for axis, extent, maximum in over
            ]
            if any(axis == "depth" for axis, _, _ in over):
                room = limit[1] - 2 * spec.process.wall_mm - spec.process.stack_slack_mm
                fitting = max(0, int(math.floor(room / s.pitch_mm + 1e-9)))
                notes.append(f"{fitting} cards would fit the depth limit")
            remedy = "; ".join(notes) + ". Reduce the card count, the wall or the slack, or relax the constraint."
    return FitsResult(fits=fits, line=line, basis=s.basis, remedy=remedy)


def to_view(spec: OrganizerSpec, result: CompileResult) -> dict[str, Any]:
    """The spec as `web/src/organizer/spec.ts` declares it: labelled millimetres, a fits
    verdict, and the hash the gate binds to. Not wired to the server in M0; it exists so
    that wiring is one field rather than a second derivation."""
    d = derive(spec)
    s = d.stack
    p = spec.process
    lid = spec.lid
    assert lid is not None

    row = view_row
    dimensions = [
        row("card_count", "Cards", s.count, "cards", True),
        row("pitch_mm", "Pitch per card", s.pitch_mm, "mm", False, s.basis),
        row("stack_height_mm", "Stack height", s.stack_height_mm, "mm", False, f"{s.count} × {s.pitch_mm:g} mm"),
        row("cavity_width_mm", "Internal width", d.cavity_w, "mm", False,
            f"{s.footprint_w_mm:g} mm envelope + {p.cavity_clearance_mm:g} mm clearance"),
        row("cavity_depth_mm", "Internal depth", d.cavity_d, "mm", False,
            f"{s.stack_height_mm:g} mm stack + {p.stack_slack_mm:g} mm slack"),
        row("cavity_height_mm", "Internal height", d.cavity_h, "mm", False,
            f"{s.footprint_h_mm:g} mm envelope + {p.cavity_clearance_mm:g} mm clearance"),
        row("external_width_mm", "External width", d.external_w, "mm", False),
        row("external_depth_mm", "External depth", d.external_d, "mm", False),
        row("external_height_mm", "External height", d.external_h, "mm", False, "assembled, lid on"),
        row("wall_mm", "Wall", p.wall_mm, "mm", True),
        row("floor_mm", "Floor", p.floor_mm, "mm", True),
        row("cavity_clearance_mm", "Cavity clearance", p.cavity_clearance_mm, "mm", True,
            "total per axis over the sleeve envelope"),
        row("stack_slack_mm", "Stack slack", p.stack_slack_mm, "mm", True),
        row("lid_clearance_mm", "Lid clearance", lid.clearance_mm, "mm", True,
            "per side; the fit tolerance a test coupon prints first"),
        row("lid_height_mm", "Lid engagement", lid.height_mm, "mm", True),
    ]
    return {
        "archetype": ARCHETYPE,
        "archetypeVersion": f"v{ARCHETYPE_VERSION}",
        "hash": result.spec_hash,
        "dimensions": dimensions,
        "fits": fits_check(spec).to_dict(),
    }
