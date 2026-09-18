"""Deck box, version 2: a body with a lip and a lift-off lid, with treated edges.

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

**Every vertical corner carries a radius and every part carries a base chamfer**, from
`process.corner_radius_mm`, `process.cavity_corner_radius_mm` and
`process.base_chamfer_mm` through `compiler.rounded_rect_prism` and
`compiler.base_chamfer`. Two of the four radii are *derived* rather than stated, and
that is what keeps the closure's fit exact around a corner:

    r_lip = max(r − lip_inset, 0)        r_lid_cavity = max(r − lw, 0)

Both arcs then share the external corner's own centre at `(r, r)`, so the gap between
the lip's outer arc and the lid cavity's arc is `(r − lw) − (r − lip_inset)` =
`lid.clearance_mm` — the same clearance around the corners as along the sides. When `r`
is under the lip inset, as it is at the defaults, both derive to 0 and the closure is
square-cornered while the outside is rounded.

The chamfer belongs to each part's **outer prism**, and the cavities are cut into it
afterwards — `compiler.base_chamfer` says why a chamfer generated with the wall and one
cut into a finished solid are not the same mesh. `validate` holds it below
`process.floor_mm` and `lid.top_mm`, which keeps it out of the cavity it sits under.

`cc` is `process.cavity_clearance_mm`, which `process.fit_intent` chooses when the spec
does not state it: 1,5 mm for `snug` (a box you close) and 4,0 mm for `easy` (a tray you
lift cards out of), both from `docs/dimension-kb-research.md` §3. An `easy` deck box
compiles; it is refused only when those wider millimetres are what push it past a stated
`constraints.max_external_mm` — see `_easy_fit_problems`.

`w` is `process.wall_mm`, and this archetype's default for it is
`spec.ARCHETYPE_WALL_MM["deck_box"]` = **2,4 mm**, which is not a taste figure: it is
`Lid.wall_mm` + `Lid.clearance_mm` + `Process.min_feature_mm`, the thinnest body wall
that still leaves the lip below a valid feature — `validate` refuses anything thinner,
so a smaller default would be a default that does not compile. It replaces an
unsourced 2,8 mm (issue #72). Below it the spec is refused by the lip rule; below
`spec.wall_floor_mm(nozzle)` — three extrusion widths — it is refused by
`archetypes.compile_spec` before this module is reached.

Rules that belong to this *shape* rather than to specs in general — exactly one
compartment, a lift-off lid without magnets, no `divider` section, a lip no thinner than
`process.min_feature_mm`, a lid shorter than the cavity, a corner round no larger than
the wall it is cut from, a chamfer below the floor it sits under — are checked here and
refused with the remedy named. Ignoring an unsupported field would print a different box than
the one asked for, silently. The rules that are not about deck boxes — the
compartment count, the plane-count assertion, the view row — come from
`common.py`, which exists so the second archetype states them in the same words.

Authored in Claude Code against `manifold3d` directly (roadmap §0.2's "authored with
text-to-cad, source frozen"): text-to-cad drives build123d on OCCT, which the kernel
decision defers; what is borrowed is its measure/align discipline.
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from typing import Any

import manifold3d

from ..compiler import (
    CompileResult,
    FitsResult,
    MeasureError,
    manifold_to_trimesh,
    rounded_rect_prism,
)
from ..dimensions import ResolvedStack, resolve_stack
from ..spec import (
    ARCHETYPE_WALL_MM,
    CardStack,
    Compartment,
    Lid,
    OrganizerSpec,
    Process,
    SpecError,
    spec_hash,
)
from .common import (
    CALLOUT_TIER_EXTERNAL,
    SweepCase,
    callout,
    card_contents_problem,
    expect_planes,
    external_overshoots,
    measured_chamfer,
    measured_corner_radius,
    single_compartment_problem,
    stray_section_problem,
    view_frame,
    view_row,
)

ARCHETYPE = "deck_box"
#: Bumped when the geometry a given spec produces changes. Recorded on every job.
#:
#: **2** since the edge treatments landed (issue #80). The first bump this constant has
#: had, and it is the case its docstring is for: a spec stored before that PR carries no
#: `process.base_chamfer_mm`, so reading it back gives the new default and compiles a
#: different mesh than it did. `generation_model_version` on the old telemetry rows is
#: what says which geometry those jobs got.
ARCHETYPE_VERSION = "2"
#: The body wall *is* `process.wall_mm` here, so `compile_spec` holds it to the
#: nozzle-derived floor. `spec.ARCHETYPE_WALL_MM["deck_box"]` is what it defaults to.
USES_PROCESS_WALL_MM = True
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
    base_chamfer: float
    corner_radius: float
    cavity_corner_radius: float
    lip_corner_radius: float
    lid_cavity_corner_radius: float

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
            # The edge treatments. The chamfer and the external round are designed once
            # and measured on **both** bodies, because "the lid got it too" is exactly
            # the kind of thing a build refactor drops silently.
            "base_chamfer_mm": self.base_chamfer,
            "lid_base_chamfer_mm": self.base_chamfer,
            "corner_radius_mm": self.corner_radius,
            "lid_corner_radius_mm": self.corner_radius,
            "cavity_corner_radius_mm": self.cavity_corner_radius,
            "lip_corner_radius_mm": self.lip_corner_radius,
            "lid_cavity_corner_radius_mm": self.lid_cavity_corner_radius,
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
    cards = card_contents_problem(spec, subject=f"deck_box v{ARCHETYPE_VERSION}")
    if cards:
        problems.append(cards)
    if spec.divider is not None:
        problems.append(
            f"deck_box v{ARCHETYPE_VERSION} has no divider plate; the divider section "
            "belongs to archetype 'card_divider' — remove it or change the archetype"
        )
    for section, owner in (("tray", "token_tray"), ("insert", "box_insert")):
        stray = stray_section_problem(
            spec, section=section, subject=f"deck_box v{ARCHETYPE_VERSION}", owner=owner
        )
        if stray:
            problems.append(stray)
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
    # The lip's outline and the lid's cavity are the outer wall stepped in, so their
    # corner radii are the outer one stepped in by the same amount — which puts all
    # three arcs on the same centre and leaves exactly `lid.clearance_mm` between the
    # lip and the lid around the corner, as along the sides. Clamped at 0: a step wider
    # than the radius leaves a square corner, not a negative one.
    corner_radius = p.corner_radius_mm
    lip_corner_radius = max(corner_radius - lip_inset, 0.0)
    lid_cavity_corner_radius = max(corner_radius - lid.wall_mm, 0.0)

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
        base_chamfer=r(p.base_chamfer_mm), corner_radius=r(corner_radius),
        cavity_corner_radius=r(p.cavity_corner_radius_mm),
        lip_corner_radius=r(lip_corner_radius),
        lid_cavity_corner_radius=r(lid_cavity_corner_radius),
    )


def _easy_fit_problems(spec: OrganizerSpec, d: DeckBoxDimensions) -> list[str]:
    """The refusal for an `easy` fit that will not fit its stated external limit.

    A loose deck box is a valid request — `process.fit_intent = "easy"` compiles, and
    +4 mm over the sleeve envelope (`docs/dimension-kb-research.md` §3) is a real way
    to want a box. What it must not do is quietly cost 2,5 mm on every axis of a spec
    that named a limit, because that clearance is a number **nobody typed**: the
    requester chose a word and the schema chose the millimetres, exactly as
    `constraints.fit_margin_mm` chooses two millimetres nobody typed and is spelled out
    wherever it refuses something.

    A `snug` overshoot is deliberately *not* refused here, and the asymmetry is the
    point rather than an oversight: `snug` is what every deck box this project has
    compiled was built with, `fits_check` already reports its overshoot with the axis
    and the card count that would fit, and turning that report into a refusal would
    take a spec the UI can show a verdict for and make it uncompilable.

    Keyed on `fit_intent` alone — never on whether the clearance happened to be
    derived — because two specs with the same canonical form must compile the same,
    and derivation is not in the canonical form.
    """
    if spec.process.fit_intent != "easy":
        return []
    over = external_overshoots(
        spec, (d.external_w, d.external_d, d.external_h), prefix="external "
    )
    if not over:
        return []
    return [
        f"process.fit_intent 'easy' puts {spec.process.cavity_clearance_mm:g} mm of "
        f"clearance over the sleeve envelope, and " + "; ".join(o.note for o in over)
        + ". Set process.fit_intent to 'snug', give process.cavity_clearance_mm "
        "explicitly, or relax constraints.max_external_mm"
    ]


def _edge_treatment_problems(spec: OrganizerSpec, d: DeckBoxDimensions) -> list[str]:
    """The three refusals the chamfer and the corner rounds bring, each with its remedy.

    None of them is a taste rule; each names a thing the geometry would do wrong.

    - **A round no larger than the wall it is cut from.** With an external radius `r`
      and a square cavity corner at `(w, w)`, the wall at the corner measures `w` while
      `r ≤ w` — the cavity's corner is then outside the arc's quarter and the nearest
      surface is the flat side. Above it the wall thins to `r − (r − w)·√2`, so a 2,4 mm
      radius on a 1,2 mm wall leaves 0,70 mm at the corner: a wall the spec does not
      claim and the printability gate would have to catch after the fact.
    - **A chamfer below every floor it sits under.** `base_chamfer` cuts from `z = 0` up
      to `c`, so a chamfer at or above `process.floor_mm` reaches the body's cavity, and
      one at or above `lid.top_mm` reaches the lid's. It would also make the footprint
      at `z = c` a ring rather than an outline, which the primitive refuses anyway —
      this is the same fact said where a person can act on it.
    - **An internal round that stays out of the contents' envelope.** A corner arc of
      radius `ρ` sits `ρ·(√2 − 1)` back from the corner it replaces, along the diagonal;
      the cavity is the sleeve envelope plus `process.cavity_clearance_mm` **total per
      axis**, so the room at that corner is `cc/2` per side, `cc·√2/2` along the
      diagonal. Judged against a sharp-cornered envelope on purpose: `resolve_stack`
      returns a rectangle, and a card's own ~3 mm corner radius is slack this rule
      declines to spend.
    """
    p = spec.process
    lid = spec.lid
    assert lid is not None
    problems: list[str] = []
    if d.corner_radius > p.wall_mm + 1e-9:
        problems.append(
            f"process.corner_radius_mm {d.corner_radius:g} mm is larger than "
            f"process.wall_mm {p.wall_mm:g} mm, which would thin the wall to "
            f"{d.corner_radius - (d.corner_radius - p.wall_mm) * math.sqrt(2.0):.3f} mm at "
            "each corner. Reduce the radius to the wall or thicken the wall"
        )
    for limit, name in ((p.floor_mm, "process.floor_mm"), (lid.top_mm, "lid.top_mm")):
        if d.base_chamfer >= limit - 1e-9:
            problems.append(
                f"process.base_chamfer_mm {d.base_chamfer:g} mm must be less than "
                f"{name} {limit:g} mm, or the chamfer cuts into the cavity above it. "
                f"Reduce the chamfer or thicken {name.rsplit('.', 1)[1]}"
            )
    room = p.cavity_clearance_mm * math.sqrt(2.0) / 2.0
    intrusion = d.cavity_corner_radius * (math.sqrt(2.0) - 1.0)
    if intrusion > room + 1e-9:
        problems.append(
            f"process.cavity_corner_radius_mm {d.cavity_corner_radius:g} mm sets the "
            f"cavity's corner {intrusion:.3f} mm back along the diagonal, past the "
            f"{room:.3f} mm that process.cavity_clearance_mm "
            f"{p.cavity_clearance_mm:g} mm leaves there. Reduce the radius, or widen "
            "the clearance"
        )
    return problems


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
    problems.extend(_easy_fit_problems(spec, d))
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
    problems.extend(_edge_treatment_problems(spec, d))
    if problems:
        raise SpecError(problems)


def build(spec: OrganizerSpec) -> tuple[dict[str, "manifold3d.Manifold"], DeckBoxDimensions]:
    """Validate, derive, and build the two solids in plate position."""
    validate(spec)
    d = derive(spec)
    p = spec.process
    lid = spec.lid
    assert lid is not None

    def prism(
        x: float, y: float, z: float, r: float = 0.0, chamfer: float = 0.0
    ) -> "manifold3d.Manifold":
        """A box with its four vertical edges rounded to `r` and its base chamfered.
        A square-cornered, unchamfered one is `Manifold.cube` vertex for vertex, which is
        what this archetype built before issue #80."""
        return rounded_rect_prism(x, y, z, r, chamfer_mm=chamfer)

    W, D = d.external_w, d.external_d
    # Each part's **outer prism carries the chamfer**, and the cavities are cut into it
    # afterwards. Not a stylistic choice: a chamfer cut into a finished solid by any
    # boolean leaves degenerate triangles along the seam where the 45° face meets the
    # wall, and they open the mesh once it is exported as float32. `base_chamfer`'s
    # docstring has the measurement.
    c = d.base_chamfer
    # Body: the outer block minus the cavity (open through the top: +1 mm overshoot).
    body = prism(W, D, d.body_h, d.corner_radius, c) - prism(
        d.cavity_w, d.cavity_d, d.cavity_h + 1.0, d.cavity_corner_radius
    ).translate([p.wall_mm, p.wall_mm, p.floor_mm])
    # Lip: remove the outer band of the top `lid.height_mm`. The band is a slab over
    # the lip height (overshooting the top) minus the lip's own outline (overshooting
    # both ways), so exactly the perimeter strip of width `lip_inset` is cut. The slab
    # carries the outer radius and the outline the derived one, so the cut is a constant
    # `lip_inset` around the corners too rather than widening across them.
    band = prism(W, D, lid.height_mm + 1.0, d.corner_radius).translate(
        [0.0, 0.0, d.body_h - lid.height_mm]
    ) - prism(
        d.lip_outer_w, d.lip_outer_d, lid.height_mm + 3.0, d.lip_corner_radius
    ).translate([d.lip_inset, d.lip_inset, d.body_h - lid.height_mm - 1.0])
    body = body - band
    # Lid: an inverted tray. Its cavity is the lip outline plus the clearance per side,
    # `lid.height_mm` deep (open through the top when printed open side up).
    lid_part = prism(W, D, d.lid_h, d.corner_radius, c) - prism(
        d.lid_cavity_w, d.lid_cavity_d, lid.height_mm + 1.0, d.lid_cavity_corner_radius
    ).translate([lid.wall_mm, lid.wall_mm, lid.top_mm])
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
    "base_chamfer_mm", "lid_base_chamfer_mm",
    "corner_radius_mm", "lid_corner_radius_mm",
    "cavity_corner_radius_mm", "lip_corner_radius_mm", "lid_cavity_corner_radius_mm",
)

def _planes(part: Any, axis: int, expected: int, what: str) -> list[float]:
    return expect_planes(part, axis, expected, what=what, subject=_SUBJECT)


def _chamfer(part: Any, what: str) -> float:
    """This archetype's subject, on `common.measured_chamfer`. Both bodies carry the
    treatment, so `what` is the one that says which body a finding is about."""
    return measured_chamfer(part, what=what, subject=_SUBJECT)


#: `common.measured_corner_radius`, under the name this module's `measure()` calls it by.
#: The measurement moved to `common.py` when the box insert gained the same outer round
#: (issue #152); the four call sites below are unchanged.
_corner_radius = measured_corner_radius


def measure(mesh: Any) -> dict[str, float]:
    """Read the designed features back off a deck-box mesh — compiled or post-Phase-3.

    Splits the plate into its two bodies (the body is the larger by volume), takes the
    distinct axis-aligned planes of each, and reads every feature as a difference of
    planes. A plane count that does not match the design is a `MeasureError`: geometry
    that does not have the planes the design says it has *is* the finding.

    The edge treatments are read off the same planes and cost the design none of them.
    A vertical fillet takes a wall's face back to its tangent points without moving the
    plane the face lies in, so every count below is what it was before there were
    rounds; a 45° chamfer has no horizontal face where it meets the wall, so the Z
    counts are unchanged too. What each of the four radii is measured against is the
    wall it is a corner of: the outer round against the body's own `X = 0`, the lip's
    against the lip's, the cavity's against the cavity's, the lid's cavity against the
    lid's inner wall.

    Raises:
        MeasureError: If the mesh is not two bodies with the deck box's plane structure,
            or if a face that should be a 45° chamfer is not one.
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
        "base_chamfer_mm": _chamfer(body, "body"),
        "lid_base_chamfer_mm": _chamfer(lid, "lid"),
        "corner_radius_mm": _corner_radius(body, by[0], bx[0]),
        "lip_corner_radius_mm": _corner_radius(body, by[1], bx[1]),
        "cavity_corner_radius_mm": _corner_radius(body, by[2], bx[2]),
        "lid_corner_radius_mm": _corner_radius(lid, ly[0], lx[0]),
        "lid_cavity_corner_radius_mm": _corner_radius(lid, ly[1], lx[1]),
    }
    return {k: float(v) for k, v in measured.items()}


def fits_check(spec: OrganizerSpec) -> FitsResult:
    """The millimetre arithmetic, and whether the result fits its external constraint.

    Without a constraint the deck fits its own cavity by construction — the cavity is
    derived from the stack — and the sum is still returned, because the sum *is* the
    value: it is what a person checks against their own callipers. With
    `constraints.max_external_mm`, each assembled external dimension is compared and a
    failing remedy names the axis, the overshoot and the card count that would fit.

    **The comparison is against the limit minus `constraints.fit_margin_mm`** (2,0 mm
    by default — `docs/dimension-kb-research.md` §7), which is also the figure the
    card count is derived from. A box internal measured off one copy is not a
    dimension to build to, and an insert that presses outward splits the box.
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
    over = external_overshoots(
        spec, (d.external_w, d.external_d, d.external_h), prefix="external "
    )
    if over:
        fits = False
        notes = [o.note for o in over]
        depth = next((o for o in over if o.axis == "depth"), None)
        if depth is not None:
            # The count is derived from the *effective* limit, or the remedy would
            # name a card count that busts the safety margin all over again.
            room = depth.limit - 2 * spec.process.wall_mm - spec.process.stack_slack_mm
            fitting = max(0, int(math.floor(room / s.pitch_mm + 1e-9)))
            notes.append(f"{fitting} cards would fit the depth limit")
        remedy = "; ".join(notes) + ". Reduce the card count, the wall or the slack, or relax the constraint."
    return FitsResult(fits=fits, line=line, basis=s.basis, remedy=remedy)


def callouts(spec: OrganizerSpec) -> list[dict[str, Any]]:
    """The dimension lines the viewer draws on a deck box, in the plate frame.

    Twelve of them, and the five **tier 1** lines are the ones the annotated preview
    exists for (issue #88, PRD §8): the cavity a deck goes into on all three axes, the
    lip the lid closes on, and the lid's own engagement. Those are the figures a misparse
    costs an eight-hour print over, and they are exactly the ones a person cannot check
    by holding callipers to the outside of the rendered box. Tier 2 is the externals, the
    wall and the floor — worth having on a desktop, dropped on a phone.

    Every line is anchored to the *geometry*: `cavity_width_mm` runs along the cavity's
    own top rim from `X = wall` to `X = wall + cavity_w`, both of which are planes the
    body actually has (`measure` reads the same two), so a wrong anchor is a test failure
    rather than a plausible-looking picture. The lid's anchors carry the plate offset
    `W + PLATE_GAP_MM`, because the lid is compiled beside the body rather than on it.

    `offset` is the free space beside each line, which is where a dimension line is
    legible from: the two lines across the cavity's mouth are nudged up out of the
    opening, and the two vertical ones lie against an inner wall and are nudged into the
    cavity they measure.
    """
    d = derive(spec)
    p = spec.process
    lid = spec.lid
    assert lid is not None
    W, D, bh = d.external_w, d.external_d, d.body_h
    wall, floor = p.wall_mm, p.floor_mm
    # The cavity's minimum corner and its mid-lines, which every internal anchor uses.
    cx, cy = wall + d.cavity_w / 2.0, wall + d.cavity_d / 2.0
    lx = W + PLATE_GAP_MM  # the lid's own origin on the plate
    up, front, left = (0.0, 0.0, 1.0), (0.0, -1.0, 0.0), (-1.0, 0.0, 0.0)
    right, inward = (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)

    return [
        # ── tier 1: the millimetres the deck has to fit into ──────────────────
        callout("cavity_width_mm", "Internal width", d.cavity_w, part="body",
                frm=(wall, cy, bh), to=(wall + d.cavity_w, cy, bh), offset=up),
        callout("cavity_depth_mm", "Internal depth", d.cavity_d, part="body",
                frm=(cx, wall, bh), to=(cx, wall + d.cavity_d, bh), offset=up),
        callout("cavity_height_mm", "Internal height", d.cavity_h, part="body",
                frm=(cx, wall, floor), to=(cx, wall, bh), offset=inward),
        callout("lip_height_mm", "Lip height", lid.height_mm, part="body",
                frm=(W - d.lip_inset, D / 2.0, bh - lid.height_mm),
                to=(W - d.lip_inset, D / 2.0, bh), offset=right),
        callout("lid_cavity_height_mm", "Lid engagement", lid.height_mm, part="lid",
                frm=(lx + W / 2.0, lid.wall_mm, lid.top_mm),
                to=(lx + W / 2.0, lid.wall_mm, lid.top_mm + lid.height_mm),
                offset=inward),
        # ── tier 2: the outside, and what it is made of ───────────────────────
        callout("external_width_mm", "External width", d.external_w, part="body",
                frm=(0.0, 0.0, 0.0), to=(W, 0.0, 0.0), offset=front,
                tier=CALLOUT_TIER_EXTERNAL),
        callout("external_depth_mm", "External depth", d.external_d, part="body",
                frm=(0.0, 0.0, 0.0), to=(0.0, D, 0.0), offset=left,
                tier=CALLOUT_TIER_EXTERNAL),
        callout("body_height_mm", "Body height", d.body_h, part="body",
                frm=(0.0, D / 2.0, 0.0), to=(0.0, D / 2.0, bh), offset=left,
                tier=CALLOUT_TIER_EXTERNAL),
        callout("wall_mm", "Wall", p.wall_mm, part="body",
                frm=(0.0, cy, bh), to=(wall, cy, bh), offset=up,
                tier=CALLOUT_TIER_EXTERNAL),
        callout("floor_mm", "Floor", p.floor_mm, part="body",
                frm=(0.0, D / 2.0, 0.0), to=(0.0, D / 2.0, floor), offset=left,
                tier=CALLOUT_TIER_EXTERNAL),
        callout("lid_height_mm", "Lid height", d.lid_h, part="lid",
                frm=(lx, D / 2.0, 0.0), to=(lx, D / 2.0, d.lid_h), offset=left,
                tier=CALLOUT_TIER_EXTERNAL),
        callout("lid_wall_mm", "Lid wall", lid.wall_mm, part="lid",
                frm=(lx, D / 2.0, d.lid_h), to=(lx + lid.wall_mm, D / 2.0, d.lid_h),
                offset=up, tier=CALLOUT_TIER_EXTERNAL),
    ]


#: The five figures the phone step of the viewer shows, and the acceptance criterion
#: this archetype is measured against: the cavity on three axes, the lip, the lid's
#: engagement. Declared here so `tests/test_view_callouts.py` asserts the set rather
#: than counting rows.
TIER_1_FEATURES: tuple[str, ...] = (
    "cavity_width_mm", "cavity_depth_mm", "cavity_height_mm",
    "lip_height_mm", "lid_cavity_height_mm",
)


def to_view(spec: OrganizerSpec, result: CompileResult) -> dict[str, Any]:
    """The spec as `web/src/organizer/spec.ts` declares it: labelled millimetres, a fits
    verdict, the hash the gate binds to — and, since issue #88, the annotated preview's
    own two keys, `frame` and `callouts`. Phase 2 writes the whole document to
    `view.json`; the api-server image has no kernel, so this is the only place that has
    the spec, the kernel and the compile result in one frame."""
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
        # `fit_intent` is a word and `SpecDimension.value` is a number, so — like the
        # divider's `tab_position` — it rides as the note of the row it decides.
        row("cavity_clearance_mm", "Cavity clearance", p.cavity_clearance_mm, "mm", True,
            f"total per axis over the sleeve envelope; {p.fit_intent} fit"),
        row("stack_slack_mm", "Stack slack", p.stack_slack_mm, "mm", True),
        row("lid_clearance_mm", "Lid clearance", lid.clearance_mm, "mm", True,
            "per side; the fit tolerance a test coupon prints first"),
        row("lid_height_mm", "Lid engagement", lid.height_mm, "mm", True),
        # The three edge treatments. Their notes say **design default, unsourced** in
        # as many words, as the divider's tab rows do: the audited insert document
        # (roadmap §0.5) calls all three features mandatory and names no millimetre for
        # any of them, and presenting a number this project chose as though it came
        # from a source is the same fabrication as an unmeasured fits badge.
        row("base_chamfer_mm", "Base chamfer", p.base_chamfer_mm, "mm", True,
            "45°, against warping; design default, unsourced — three 0,2 mm layers"),
        row("corner_radius_mm", "Corner radius", p.corner_radius_mm, "mm", True,
            "external vertical corners, against elephant-foot flare; design default, "
            "unsourced"),
        row("cavity_corner_radius_mm", "Cavity corner radius", p.cavity_corner_radius_mm,
            "mm", True,
            "internal vertical corners; 0 — a sleeved deck lifts out whole"),
    ]
    return {
        "archetype": ARCHETYPE,
        "archetypeVersion": f"v{ARCHETYPE_VERSION}",
        "hash": result.spec_hash,
        "dimensions": dimensions,
        "fits": fits_check(spec).to_dict(),
        "frame": view_frame(result),
        "callouts": callouts(spec),
    }


# ── The dimensional envelope (issue #85) ──────────────────────────────────────
#
# The domain of this archetype's ±0,05 mm claim, declared beside the geometry that has
# to honour it rather than inside the test that drives it. The sweep used to be written
# for the deck box and then copied per archetype; a module now says which specs it holds
# itself to, `tests/test_organizer_dimensional_accuracy.py` sweeps whatever every
# registered module declares, and a new archetype that declares nothing fails by name.
#
# Five axes, and the wall is the one worth reading twice: `None` states no wall at all
# and takes this module's own default, which is what almost every real spec compiles
# with, so it is swept as a value rather than checked once — a dimensional claim about a
# wall nobody typed is worth as much as one about 2,8 mm.

#: Card counts, from a starter pile to a double-sleeved Commander deck.
SWEEP_COUNTS: tuple[int, ...] = (15, 40, 60, 100, 160)
SWEEP_SLEEVINGS: tuple[str, ...] = ("none", "single", "double")
#: `None` is "no wall stated" — `ARCHETYPE_WALL_MM["deck_box"]`, 2,4 mm. 2.6 − 1.2 lid
#: wall − 0.35 clearance = 1.05 mm of lip, above `min_feature_mm`; at the 2,4 mm default
#: that same clearance leaves 0.85 mm and `validate` refuses it, so `_lip_is_buildable`
#: drops the pair rather than sweeping a box that does not exist.
SWEEP_WALLS: tuple[float | None, ...] = (None, 2.6, 2.8, 4.0)
SWEEP_CLEARANCES: tuple[float, ...] = (0.1, 0.2, 0.35)
SWEEP_LID_HEIGHTS: tuple[float, ...] = (8.0, 15.0, 30.0)
#: The corner set that goes on through Phase 3's assert path: three counts against five
#: (wall, clearance, lid height) triples, every one of them a point of the product above
#: so the corners are a *subset* of the envelope rather than a second list to maintain.
SWEEP_PHASE_3_COUNTS: tuple[int, ...] = (15, 60, 160)
SWEEP_PHASE_3_PROCESSES: tuple[tuple[float | None, float, float], ...] = (
    (2.6, 0.1, 8.0), (2.8, 0.2, 15.0), (4.0, 0.35, 30.0), (2.6, 0.35, 8.0),
    (None, 0.2, 15.0),
)


def _lip_is_buildable(wall: float | None, clearance: float) -> bool:
    """`validate`'s lip rule, restated so the envelope asks only for boxes that exist:
    the body wall less the lid's wall and clearance must reach `min_feature_mm`."""
    body_wall = ARCHETYPE_WALL_MM[ARCHETYPE] if wall is None else wall
    return body_wall - (Lid().wall_mm + clearance) >= Process().min_feature_mm - 1e-9


def envelope() -> tuple[SweepCase, ...]:
    """Every spec the dimensional sweep drives this archetype over — 495 of them.

    Nothing here states a floor, a fit intent or an edge treatment, so every case
    carries `Process`'s own defaults and the sweep measures the geometry a real spec
    gets. The three axes that are *not* here have corners of their own in the test,
    because each is orthogonal to these five and multiplying 495 by them would buy
    repetition rather than coverage: the fit intent moves two lengths (issue #71), the
    edge treatments change the kind of surface rather than a length (issue #80), and the
    nozzle-derived wall floor has no mesh to measure at all — below it nothing compiles.
    """
    cases: list[SweepCase] = []
    for count, sleeving, wall, clearance, lid_height in itertools.product(
        SWEEP_COUNTS, SWEEP_SLEEVINGS, SWEEP_WALLS, SWEEP_CLEARANCES, SWEEP_LID_HEIGHTS,
    ):
        if not _lip_is_buildable(wall, clearance):
            continue
        cases.append(SweepCase(
            id=(f"n{count}-{sleeving}-wall{'default' if wall is None else f'{wall:g}'}"
                f"-clr{clearance:g}-lid{lid_height:g}"),
            spec=OrganizerSpec(
                archetype=ARCHETYPE,
                compartments=(Compartment(CardStack(count=count, sleeving=sleeving)),),
                lid=Lid(height_mm=lid_height, clearance_mm=clearance),
                process=Process(wall_mm=wall),
            ),
            phase_3=(
                count in SWEEP_PHASE_3_COUNTS
                and (wall, clearance, lid_height) in SWEEP_PHASE_3_PROCESSES
            ),
        ))
    return tuple(cases)
