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
compartment, a lift-off lid without magnets, a lip no thinner than
`process.min_feature_mm`, a lid shorter than the cavity — are checked here and refused
with the remedy named. Ignoring an unsupported field would print a different box than
the one asked for, silently.

Authored in Claude Code against `manifold3d` directly (roadmap §0.2's "authored with
text-to-cad, source frozen"): text-to-cad drives build123d on OCCT, which the kernel
decision defers; what is borrowed is its measure/align discipline.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import manifold3d

from ..compiler import CompileResult, FitsResult, MeasureError, manifold_to_trimesh, plane_set
from ..dimensions import ResolvedStack, resolve_stack
from ..spec import CardStack, Compartment, Lid, OrganizerSpec, SpecError, spec_hash

ARCHETYPE = "deck_box"
#: Bumped when the geometry a given spec produces changes. Recorded on every job.
ARCHETYPE_VERSION = "1"
#: Clear space between the body and the lid on the plate, mm.
PLATE_GAP_MM = 10.0


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
    if len(spec.compartments) != 1:
        problems.append(
            f"deck_box v{ARCHETYPE_VERSION} holds exactly one compartment (the deck); "
            f"got {len(spec.compartments)}"
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
