"""Card divider, version 1: a flat plate the size of the cards with a label tab.

The second archetype, and therefore the one that answers whether the archetype API is
an API or one module's habits. It is deliberately the smallest shape the pivot needs:
**one** body, printed flat, whose every dimension is a difference of two axis-aligned
planes, so `compiler.plane_set` measures all of it and no new measurer was written for
it. The shared rules it needs — the compartment count, the plane-count assertion, the
view row — moved into `common.py` when this module landed rather than being copied.

A divider stands between groups of cards in a deck box or a storage box; the tab
carries the label and stands proud of the cards so a thumb can find it. One part on
the plate, flat on Z = 0, no overhangs anywhere. With `(fw, fh)` the sleeved envelope
from `resolve_stack` and `t, tw, th, pos` from `spec.divider`:

    tab_offset = 0 | (fw − tw)/2 | fw − tw             # left | centre | right
    outline    = (0,0) (fw,0) (fw,fh) (x1,fh) (x1,fh+th) (x0,fh+th) (x0,fh) (0,fh)
    divider    = extrude(outline, t)                   # one body, prism, Z = 0..t
    total_h    = fh + th                               # x0 = tab_offset, x1 = x0 + tw

**The tab is part of one outline, not a second solid unioned on.** Boxes and a union
were tried first, the way the deck box builds its parts, and they are wrong here for a
reason worth recording: a tab at `left` or `right` has a side face coplanar with the
plate's, and the kernel keeps vertices from that intersection — so the mesh came back
carrying a Y plane at `fh − overlap` that no design dimension accounts for, and
`measure` could not tell that artefact from a real plane. An extruded outline has
exactly the design's planes and nothing else (16 vertices for a centred tab, 14 for an
edge one), and it needs no boolean at all. `manifold3d.CrossSection` is the same
Apache-2.0 kernel — no new dependency, and the primitive roadmap §0.5 already names for
the chamfer work.

`tab_width_mm < fw` is a validation rule, which is what keeps the plate's own top plane
at Y = fh on the mesh and therefore `plate_height_mm` measurable.

**The plate carries no margin over the sleeved envelope.** No divider margin is sourced
anywhere in `docs/dimension-kb-research.md`, and the obvious candidate —
`process.cavity_clearance_mm`, 1,5 mm — would make the plate exactly as wide as this
project's own deck box cavity, which is a zero-clearance fit that jams. A plate equal
to the envelope fits any box the cards fit, and uses only numbers that have a source.

**`Process` fields this archetype does not read still hash.** It reads
`min_feature_mm` and nothing else, so two divider specs differing only in
`process.wall_mm` compile identically and hash differently. Accepted, as
`constraints` already is: the spec records what was asked for, and the compiler
records what it built (`compile_features.json`).

`CardStack.count` does not enter the geometry either — a divider labels a group of
cards of any size — so it is accepted at any value and the fits line says it is not
geometric. The sleeving, which fixes the envelope, is the field that matters.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import manifold3d

from ..compiler import CompileResult, FitsResult, MeasureError, manifold_to_trimesh, plane_set
from ..dimensions import ResolvedStack, resolve_stack
from ..spec import CardStack, Compartment, Divider, OrganizerSpec, SpecError, spec_hash
from .common import (
    card_contents_problem,
    expect_planes,
    external_overshoots,
    single_compartment_problem,
    stray_section_problem,
    view_row,
)

ARCHETYPE = "card_divider"
#: Bumped when the geometry a given spec produces changes. Recorded on every job.
ARCHETYPE_VERSION = "1"
#: This archetype has no wall — the plate's one thickness is `divider.thickness_mm`
#: (see "Process fields this archetype does not read still hash" above) — so
#: `compile_spec` does not hold `process.wall_mm` to the nozzle floor. It would
#: otherwise refuse a perfectly good divider on a 0,6 mm nozzle over a number that
#: builds nothing.
USES_PROCESS_WALL_MM = False
#: How this archetype names itself in a refusal or a measurement finding.
_SUBJECT = f"a card divider v{ARCHETYPE_VERSION}"


@dataclass(frozen=True)
class DividerDimensions:
    """Every derived dimension, in mm, from one spec. Pure arithmetic — no kernel."""

    stack: ResolvedStack
    plate_w: float
    plate_h: float
    thickness: float
    tab_w: float
    tab_h: float
    tab_offset: float
    total_h: float

    def features(self, spec: OrganizerSpec) -> dict[str, float]:
        """The designed features by name. `measure()` reads the same names back.

        Every one of them is on the mesh, so `MEASURED_FEATURES` is this whole set —
        unlike the deck box, which designs a stack height no geometry carries.
        """
        raw = {
            "plate_width_mm": self.plate_w,
            "plate_height_mm": self.plate_h,
            "thickness_mm": self.thickness,
            "tab_width_mm": self.tab_w,
            "tab_height_mm": self.tab_h,
            "tab_offset_mm": self.tab_offset,
            "total_height_mm": self.total_h,
        }
        return {k: round(float(v), 3) for k, v in raw.items()}


def _tab_offset(plate_w: float, tab_w: float, position: str) -> float:
    """Where the tab's left edge sits, measured from the plate's left edge."""
    if position == "left":
        return 0.0
    if position == "right":
        return plate_w - tab_w
    return (plate_w - tab_w) / 2.0


def _structural_problems(spec: OrganizerSpec) -> list[str]:
    problems: list[str] = []
    if spec.archetype != ARCHETYPE:
        problems.append(f"archetype {spec.archetype!r} is not {ARCHETYPE!r}")
    one = single_compartment_problem(
        spec, subject=f"card_divider v{ARCHETYPE_VERSION}", holds="the cards it labels"
    )
    if one:
        problems.append(one)
    cards = card_contents_problem(spec, subject=f"card_divider v{ARCHETYPE_VERSION}")
    if cards:
        problems.append(cards)
    tray = stray_section_problem(
        spec, section="tray", subject=f"card_divider v{ARCHETYPE_VERSION}", owner="token_tray"
    )
    if tray:
        problems.append(tray)
    if spec.divider is None:
        problems.append(
            f"card_divider v{ARCHETYPE_VERSION} needs a divider section (divider is "
            "null); it carries the plate thickness and the tab"
        )
    if spec.lid is not None:
        problems.append(
            f"card_divider v{ARCHETYPE_VERSION} is a single flat plate and has no "
            "closure; remove the lid section or change the archetype"
        )
    return problems


def derive(spec: OrganizerSpec) -> DividerDimensions:
    """Every dimension the geometry is built from. Assumes `_structural_problems` is empty."""
    stack_spec: CardStack = spec.compartments[0].contents
    stack = resolve_stack(stack_spec.count, stack_spec.card, stack_spec.sleeving)
    div = spec.divider
    assert div is not None  # validated before derive() is reached
    plate_w = stack.footprint_w_mm
    plate_h = stack.footprint_h_mm
    tab_offset = _tab_offset(plate_w, div.tab_width_mm, div.tab_position)

    def r(x: float) -> float:  # every value to 1 µm, like the schema
        return round(float(x), 3)

    return DividerDimensions(
        stack=stack,
        plate_w=r(plate_w), plate_h=r(plate_h), thickness=r(div.thickness_mm),
        tab_w=r(div.tab_width_mm), tab_h=r(div.tab_height_mm), tab_offset=r(tab_offset),
        total_h=r(plate_h + div.tab_height_mm),
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
    div = spec.divider
    assert div is not None
    min_feature = spec.process.min_feature_mm
    if d.tab_w >= d.plate_w:
        problems.append(
            f"divider.tab_width_mm {d.tab_w:g} must be less than the plate width "
            f"{d.plate_w:g} mm ({d.stack.sleeving}-sleeved envelope); a tab as wide as "
            "the plate is a taller plate, not a tab — narrow the tab"
        )
    for name, value in (
        ("divider.thickness_mm", d.thickness),
        ("divider.tab_width_mm", d.tab_w),
        ("divider.tab_height_mm", d.tab_h),
    ):
        if value < min_feature:
            problems.append(
                f"{name} {value:g} mm is below process.min_feature_mm {min_feature:g}; "
                "thicken the feature or lower the minimum"
            )
    if problems:
        raise SpecError(problems)


def outline(d: DividerDimensions) -> list[tuple[float, float]]:
    """The plate-and-tab profile in the XY plane, counter-clockwise.

    Consecutive duplicate points are dropped, which is what makes an edge tab a valid
    polygon: at `left` the tab's own left corner *is* the plate's, and a repeated
    vertex is a zero-length edge. The collinear point that survives on the plate's side
    edge is harmless — it lies on a plane the design already has.
    """
    x0, x1 = d.tab_offset, d.tab_offset + d.tab_w
    top = d.plate_h + d.tab_h
    points = [
        (0.0, 0.0), (d.plate_w, 0.0), (d.plate_w, d.plate_h),
        (x1, d.plate_h), (x1, top), (x0, top), (x0, d.plate_h), (0.0, d.plate_h),
    ]
    unique: list[tuple[float, float]] = []
    for point in points:
        if not unique or abs(point[0] - unique[-1][0]) > 1e-9 or abs(point[1] - unique[-1][1]) > 1e-9:
            unique.append(point)
    if len(unique) > 1 and unique[0] == unique[-1]:
        unique.pop()
    return unique


def build(spec: OrganizerSpec) -> tuple[dict[str, "manifold3d.Manifold"], DividerDimensions]:
    """Validate, derive, and build the one solid in plate position."""
    validate(spec)
    d = derive(spec)
    prism = manifold3d.CrossSection([outline(d)]).extrude(d.thickness)
    return {"divider": prism}, d


def compile(spec: OrganizerSpec) -> CompileResult:  # noqa: A001 — the registry's verb
    """Spec → plate mesh, parts, designed features."""
    solids, d = build(spec)
    parts = {name: manifold_to_trimesh(solid) for name, solid in solids.items()}
    return CompileResult(
        archetype=ARCHETYPE,
        archetype_version=ARCHETYPE_VERSION,
        spec_hash=spec_hash(spec),
        mesh=manifold_to_trimesh(solids["divider"]),
        parts=parts,
        features=d.features(spec),
    )


def example() -> OrganizerSpec:
    """A divider for a double-sleeved Commander deck, with the default tab."""
    return OrganizerSpec(
        archetype=ARCHETYPE,
        compartments=(Compartment(CardStack(count=100, card="standard", sleeving="double")),),
        divider=Divider(),
    )


#: Features `measure()` reads off geometry — all of them, for this archetype.
MEASURED_FEATURES: tuple[str, ...] = (
    "plate_width_mm", "plate_height_mm", "thickness_mm",
    "tab_width_mm", "tab_height_mm", "tab_offset_mm", "total_height_mm",
)


def _region_planes(part: Any, selector: Any, what: str) -> list[float]:
    """The two X planes bounding one region of the plate, or the finding.

    `selector` is a boolean mask over `part.vertices`. Exactly two planes is the design;
    anything else means this is not a divider and says so with the planes it found.
    """
    planes = plane_set(part.vertices[selector][:, 0])
    if len(planes) != 2:
        raise MeasureError(
            f"the divider's {what} has {len(planes)} distinct X planes where {_SUBJECT} "
            f"has 2: {[round(v, 3) for v in planes]}"
        )
    return planes


def measure(mesh: Any) -> dict[str, float]:
    """Read the designed features back off a divider mesh — compiled or post-Phase-3.

    One body. Y carries three planes (the plate's bottom edge, the plate's top edge
    where the tab starts, the tab's top edge) and Z two, so the plate height, the tab
    height and the thickness are plane differences of the whole body.

    X is read per *region* instead, and deliberately not from the whole body's plane
    count. Two reasons, and the second is why the first is not enough. The kernel's
    union retriangulates around the join and puts vertices on the plate's top face that
    no design plane accounts for, so the body's X plane count is not the design's. And
    even without them the count would not identify the design: a centred tab gives four
    X planes and an edge tab three, because the tab's edge is then the plate's. So the
    plate's own two X planes come from the vertices on its **bottom** edge — the one
    edge the union cannot touch — and the tab's from the vertices **strictly above the
    plate's measured top plane**, where nothing but the tab reaches. Two planes each,
    and a different count is the finding. The offset is taken relative to the plate's
    left plane rather than to 0, because `orient_for_print` re-centres the part in X and
    Y before the slicer ever sees it.

    Raises:
        MeasureError: If the mesh is not one body with the divider's plane structure.
    """
    parts = mesh.split(only_watertight=False)
    if len(parts) != 1:
        raise MeasureError(f"expected 1 body (the divider plate), found {len(parts)}")
    part = parts[0]
    y = expect_planes(part, 1, 3, what="divider", subject=_SUBJECT)
    z = expect_planes(part, 2, 2, what="divider", subject=_SUBJECT)
    plate_x = _region_planes(part, part.vertices[:, 1] < y[0] + 1e-3, "plate")
    tab_x = _region_planes(part, part.vertices[:, 1] > y[1] + 1e-3, "tab")
    measured = {
        "plate_width_mm": plate_x[1] - plate_x[0],
        "plate_height_mm": y[1] - y[0],
        "thickness_mm": z[1] - z[0],
        "tab_width_mm": tab_x[1] - tab_x[0],
        "tab_height_mm": y[2] - y[1],
        "tab_offset_mm": tab_x[0] - plate_x[0],
        "total_height_mm": y[2] - y[0],
    }
    return {k: float(v) for k, v in measured.items()}


def fits_check(spec: OrganizerSpec) -> FitsResult:
    """The millimetre arithmetic, and whether the result fits its external constraint.

    Without a constraint a divider fits by construction: the plate *is* the sleeved
    envelope, so any box the cards fit takes the plate. The sum is still returned,
    because the sum is the value — it is what a person checks against their own
    callipers — and it states how far the tab stands proud, so nobody reads "fits" as
    "fits inside the deck box with the lid on". It does not: a tabbed divider is a
    storage-box part, and the deck box cavity is only `cavity_clearance_mm` taller
    than the cards.

    `constraints.max_external_mm` is `(W, D, H)` of the divider **in use, standing
    upright**: W the plate width, D the plate thickness, H the total height including
    the tab. A failing remedy names the axis and the overshoot.

    **The comparison is against the limit minus `constraints.fit_margin_mm`** (2,0 mm
    by default — `docs/dimension-kb-research.md` §7), on every axis including the
    thickness. The margin is a property of the *measurement*, not of the part: it is
    the ±1–2 mm a box internal varies by between copies, so a divider that presses on
    the box walls splits them exactly as an insert does.
    """
    validate(spec)
    d = derive(spec)
    s = d.stack
    envelope = (
        f"{s.footprint_w_mm:g} × {s.footprint_h_mm:g} mm "
        + ("bare card" if s.sleeving == "none" else f"{s.sleeving}-sleeved")
        + " envelope"
    )
    div = spec.divider
    assert div is not None
    line = (
        f"{envelope} · plate {d.plate_w:g} × {d.plate_h:g} × {d.thickness:g} mm · "
        f"tab {d.tab_w:g} × {d.tab_h:g} mm {div.tab_position} · "
        f"stands {d.tab_h:g} mm proud of the cards · "
        f"{s.count} cards labelled (not a geometric input)"
    )
    fits = True
    remedy = None
    over = external_overshoots(spec, (d.plate_w, d.thickness, d.total_h))
    if over:
        fits = False
        remedy = (
            "; ".join(o.note for o in over)
            + ". Thin the plate, shorten the tab, choose a lighter sleeving, or "
            "relax the constraint."
        )
    return FitsResult(fits=fits, line=line, basis=s.basis, remedy=remedy)


def to_view(spec: OrganizerSpec, result: CompileResult) -> dict[str, Any]:
    """The spec as `web/src/organizer/spec.ts` declares it: labelled millimetres, a fits
    verdict, and the hash the gate binds to.

    `tab_position` is a word, and `SpecDimension.value` is a number, so the position
    rides as the offset row's note rather than as a row of its own. The tab's own
    figures are marked as design defaults, because no source in
    `docs/dimension-kb-research.md` gives a divider tab and a number presented as
    sourced when it is not is the failure this whole engine exists to avoid.
    """
    d = derive(spec)
    s = d.stack
    div = spec.divider
    assert div is not None
    row = view_row
    dimensions = [
        row("card_count", "Cards", s.count, "cards", True, "labelled, not a geometric input"),
        row("plate_width_mm", "Plate width", d.plate_w, "mm", False,
            f"{s.footprint_w_mm:g} mm envelope, no margin"),
        row("plate_height_mm", "Plate height", d.plate_h, "mm", False,
            f"{s.footprint_h_mm:g} mm envelope, no margin"),
        row("thickness_mm", "Thickness", d.thickness, "mm", True,
            "1,2–1,6 mm insert band (roadmap §0.5 — one practitioner's practice)"),
        row("tab_width_mm", "Tab width", d.tab_w, "mm", True, "design default, unsourced"),
        row("tab_height_mm", "Tab height", d.tab_h, "mm", True,
            "design default, unsourced; how far the tab stands proud"),
        row("tab_offset_mm", "Tab offset", d.tab_offset, "mm", False,
            f"from the left edge; tab_position {div.tab_position!r}"),
        row("total_height_mm", "Total height", d.total_h, "mm", False, "plate plus tab"),
        row("min_feature_mm", "Minimum feature", spec.process.min_feature_mm, "mm", True,
            "the archetype refuses anything thinner"),
    ]
    return {
        "archetype": ARCHETYPE,
        "archetypeVersion": f"v{ARCHETYPE_VERSION}",
        "hash": result.spec_hash,
        "dimensions": dimensions,
        "fits": fits_check(spec).to_dict(),
    }
