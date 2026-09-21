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

import itertools
from dataclasses import dataclass
from typing import Any, Optional

import manifold3d
import numpy as np

from .. import lettering
from ..compiler import (
    Box,
    CompileResult,
    FaceFrame,
    FitsResult,
    MeasureError,
    letter,
    manifold_to_trimesh,
    plane_set,
    text_outline,
)
from ..dimensions import ResolvedStack, resolve_stack
from ..spec import (
    EMBOSS_EDGE_MARGIN_MM,
    CardStack,
    Compartment,
    Divider,
    Emboss,
    OrganizerSpec,
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
    measured_relief,
    shifted_region,
    single_compartment_problem,
    stray_section_problem,
    view_frame,
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
#: The faces this archetype letters (F13, issue #157): the tab, and only the tab.
#:
#: The tab is the one part of a divider anybody looks at — it is what stands proud of the
#: cards so a thumb can find it, and the whole reason the archetype has one. It is also
#: the only face of any archetype here that **points up as it prints**: the plate lies
#: flat on Z = 0, so the tab's own top face at `Z = thickness` is the last surface the
#: nozzle lays, with nothing above it. That is what lets this face take `raised` text
#: when every deck box face takes only `recessed`, and it is why a lettered divider is
#: the acceptance criterion's `expected_components = 1` case.
#:
#: The plate's face is deliberately not offered: a divider stands *between* cards, so
#: what is written on the plate is inside the stack where nobody can read it.
EMBOSS_FACES: tuple[str, ...] = ("tab",)
#: `measure()` needs the spec, to know where the lettering it must skip is (issue #157).
#: The box insert's precedent — see `archetypes.measure_spec_mesh`.
MEASURE_NEEDS_SPEC = True
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

        A decorated divider designs one more, `emboss_relief_mm`. Decoration is not a
        designed *dimension* — issue #157: it must not move one — but its own relief is,
        and the sweep measures it back like everything else here: a 0,6 mm emboss that
        came out 0,3 mm deep is a part that does not say what it was asked to say.
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
        if spec.emboss is not None:
            raw["emboss_relief_mm"] = spec.emboss.relief_mm
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
    for section, owner in (("tray", "token_tray"), ("insert", "box_insert")):
        stray = stray_section_problem(
            spec, section=section, subject=f"card_divider v{ARCHETYPE_VERSION}", owner=owner
        )
        if stray:
            problems.append(stray)
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


def emboss_frame(spec: OrganizerSpec) -> FaceFrame:
    """Where lettering goes on a divider: centred on the tab's upward face.

    The usable rectangle is the tab itself, inset by `EMBOSS_EDGE_MARGIN_MM` on every
    side. The tab has no corner round and no chamfer — it is an extruded outline, see the
    module docstring — so the margin is the whole of the inset, and it is what keeps the
    measurer's exclusion region (`FaceFrame.region_mm`) inside the face rather than
    reaching the tab's own edge and taking that plane out of the count.

    `u` is +X and `v` is +Y, which reads left to right looking down at the plate as it
    prints — the way a divider is looked at in the box it stands in, since a tab is read
    from above. `n` is +Z, and the frame is right-handed: `u × v = n`.

    Both modes are honoured, and this is the only face of any archetype here that honours
    `raised` — see `EMBOSS_FACES`.

    The material behind the face is the plate itself, so a recess is held to
    `process.min_feature_mm`: at the 1,4 mm default thickness a 0,6 mm recess leaves
    0,8 mm and is refused, which is right — that is a divider you could see daylight
    through.

    Raises:
        SpecError: If the spec is not one this archetype can derive at all.
    """
    problems = _structural_problems(spec)
    if problems:
        raise SpecError(problems)
    d = derive(spec)
    margin = EMBOSS_EDGE_MARGIN_MM
    return FaceFrame(
        face="tab",
        part="divider",
        origin=(
            d.tab_offset + d.tab_w / 2.0,
            d.plate_h + d.tab_h / 2.0,
            d.thickness,
        ),
        u=(1.0, 0.0, 0.0),
        v=(0.0, 1.0, 0.0),
        normal=(0.0, 0.0, 1.0),
        width_mm=max(d.tab_w - 2.0 * margin, 0.0),
        height_mm=max(d.tab_h - 2.0 * margin, 0.0),
        modes=("raised", "recessed"),
        material_mm=d.thickness,
        material_name="divider.thickness_mm",
        material_floor_mm=spec.process.min_feature_mm,
    )


def _emboss_region(spec: OrganizerSpec, origin_mm: Any) -> Optional[Box]:
    """The box the lettering occupies on a built plate, or None for an undecorated one.

    `origin_mm` is where the part's minimum corner actually sits, which is not where the
    design put it: Phase 3 re-centres a plate in X and Y and sets it on Z = 0 before
    anything measures it. The design's minimum corner is the origin, so the offset *is*
    the measured corner, and every region here follows the part rather than assuming it
    stayed where it was compiled.
    """
    emboss = spec.emboss
    if emboss is None:
        return None
    frame = emboss_frame(spec)
    ink_w, ink_h = lettering.ink_extent_mm(emboss.text, emboss.height_mm)
    box = frame.region_mm(ink_w, ink_h, emboss.relief_mm, emboss.mode)
    return shifted_region(box, origin_mm, (0.0, 0.0, 0.0))


def build(spec: OrganizerSpec) -> tuple[dict[str, "manifold3d.Manifold"], DividerDimensions]:
    """Validate, derive, and build the one solid in plate position.

    The lettering is applied **last**, to the finished plate. It has to be: a raised slab
    sunk `LETTER_SINK_MM` into a face is a transverse boolean against a solid that already
    exists, and there is nothing after it to cut the decoration in half.
    """
    validate(spec)
    d = derive(spec)
    prism = manifold3d.CrossSection([outline(d)]).extrude(d.thickness)
    if spec.emboss is not None:
        prism = letter(
            prism,
            text_outline(spec.emboss.text, spec.emboss.height_mm),
            emboss_frame(spec),
            spec.emboss.relief_mm,
            spec.emboss.mode,
        )
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


def measured_features(spec: OrganizerSpec) -> tuple[str, ...]:
    """`MEASURED_FEATURES`, plus the relief when the spec carries an emboss.

    A function of the spec rather than a constant, on the token tray's precedent: the
    feature exists only when the section does, and a fixed tuple could only either
    promise a relief on every plain divider — which would report `not measured` on every
    one of them — or promise it on none, which would leave the one thing a decorated
    divider adds unchecked while the report still said *within tolerance*.
    """
    if spec.emboss is None:
        return MEASURED_FEATURES
    return MEASURED_FEATURES + ("emboss_relief_mm",)


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


def _outside_region(vertices: Any, region: Optional[Box]) -> Any:
    """A mask over `vertices`: True for those outside the lettering region.

    The tab's X planes are read off **vertices** rather than faces — see `measure` — and
    a raised `T` puts a vertex column at the end of its crossbar that no design plane
    accounts for. So the vertex read gets the same exclusion the face reads get, for the
    same reason: the decoration is not one of the planes being counted.
    """
    keep = np.ones(len(vertices), dtype=bool)
    if region is None:
        return keep
    inside = np.ones(len(vertices), dtype=bool)
    for axis, (low, high) in enumerate(region):
        inside &= (vertices[:, axis] >= low) & (vertices[:, axis] <= high)
    return ~inside


def measure(mesh: Any, spec: OrganizerSpec) -> dict[str, float]:
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

    **Lettering is excluded from every read here and measured on its own.** A raised
    glyph's top is a real Z plane and the stems of `I`, `L` and `T` are real X and Y
    walls, so a decorated plate genuinely has more planes than a divider has — and the
    count is what says "this is a divider", so it has to be the count of the part the
    design describes. The region comes from the spec (`_emboss_region`) and the numbers
    still come from the mesh, exactly as `box_insert` reads a ragged row: what the design
    supplies is *where to look*. The relief itself is then read inside that region with
    `face_planes_within`, as a difference of the face's own plane and the glyph's.

    Args:
        mesh: The compiled or post-Phase-3 mesh.
        spec: The spec it was compiled from — needed only to know where the decoration
            is. `MEASURE_NEEDS_SPEC` declares that on the module, so a reader sees the
            claim in the diff rather than inferring it from an argument count.

    Raises:
        MeasureError: If the mesh is not one body with the divider's plane structure.
    """
    parts = mesh.split(only_watertight=False)
    if len(parts) != 1:
        raise MeasureError(f"expected 1 body (the divider plate), found {len(parts)}")
    part = parts[0]
    region = _emboss_region(spec, part.bounds[0])
    y = expect_planes(part, 1, 3, what="divider", subject=_SUBJECT, exclude_mm=region)
    z = expect_planes(part, 2, 2, what="divider", subject=_SUBJECT, exclude_mm=region)
    keep = _outside_region(part.vertices, region)
    plate_x = _region_planes(part, keep & (part.vertices[:, 1] < y[0] + 1e-3), "plate")
    tab_x = _region_planes(part, keep & (part.vertices[:, 1] > y[1] + 1e-3), "tab")
    measured = {
        "plate_width_mm": plate_x[1] - plate_x[0],
        "plate_height_mm": y[1] - y[0],
        "thickness_mm": z[1] - z[0],
        "tab_width_mm": tab_x[1] - tab_x[0],
        "tab_height_mm": y[2] - y[1],
        "tab_offset_mm": tab_x[0] - plate_x[0],
        "total_height_mm": y[2] - y[0],
    }
    if region is not None:
        measured["emboss_relief_mm"] = measured_relief(part, region, 2, subject=_SUBJECT)
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


def callouts(spec: OrganizerSpec) -> list[dict[str, Any]]:
    """The dimension lines the viewer draws on a divider, in the plate frame.

    A divider has no inside, so its **tier 1** is the three figures that decide whether
    it fits the box it stands in — the plate's width and height, and the thickness that
    is the one number a person is likely to have asked for by feel. The tab is tier 2:
    it is the part you can see the size of.

    Every anchor sits on the top face (`Z = thickness`), which is the face a viewer
    looking down at a flat plate can actually see. `tab_offset_mm` gets no line: it is a
    position rather than a length, and a dimension line from the plate's edge to the
    tab's would be indistinguishable from one measuring a tab twice as wide.
    """
    d = derive(spec)
    t, top = d.thickness, d.plate_h + d.tab_h
    x0 = d.tab_offset
    up, front = (0.0, 0.0, 1.0), (0.0, -1.0, 0.0)
    return [
        callout("plate_width_mm", "Plate width", d.plate_w, part="divider",
                frm=(0.0, 0.0, t), to=(d.plate_w, 0.0, t), offset=up),
        callout("plate_height_mm", "Plate height", d.plate_h, part="divider",
                frm=(0.0, 0.0, t), to=(0.0, d.plate_h, t), offset=up),
        callout("thickness_mm", "Thickness", d.thickness, part="divider",
                frm=(d.plate_w / 2.0, 0.0, 0.0), to=(d.plate_w / 2.0, 0.0, t),
                offset=front),
        callout("tab_width_mm", "Tab width", d.tab_w, part="divider",
                frm=(x0, top, t), to=(x0 + d.tab_w, top, t), offset=up,
                tier=CALLOUT_TIER_EXTERNAL),
        callout("tab_height_mm", "Tab height", d.tab_h, part="divider",
                frm=(x0, d.plate_h, t), to=(x0, top, t), offset=up,
                tier=CALLOUT_TIER_EXTERNAL),
        callout("total_height_mm", "Total height", d.total_h, part="divider",
                frm=(x0, 0.0, t), to=(x0, top, t), offset=up,
                tier=CALLOUT_TIER_EXTERNAL),
    ]


def to_view(spec: OrganizerSpec, result: CompileResult) -> dict[str, Any]:
    """The spec as `web/src/organizer/spec.ts` declares it: labelled millimetres, a fits
    verdict, the hash the gate binds to, and the annotated preview's `frame` and
    `callouts` (issue #88).

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
    if spec.emboss is not None:
        # The text itself is a *word*, and `SpecDimension.value` is a number, so it rides
        # as the note of the row it sizes — `tab_position` and `fit_intent` before it.
        ink_w, ink_h = lettering.ink_extent_mm(spec.emboss.text, spec.emboss.height_mm)
        dimensions.extend([
            row("emboss_height_mm", "Lettering height", spec.emboss.height_mm, "mm", True,
                f"cap height of {spec.emboss.text!r}, {spec.emboss.mode} on the "
                f"{spec.emboss.face}; sets {ink_w:.1f} × {ink_h:.1f} mm"),
            row("emboss_relief_mm", "Lettering relief", spec.emboss.relief_mm, "mm", True,
                "design default, unsourced — three 0,2 mm layers"),
        ])
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
# See `common.SweepCase` for what an envelope is and `deck_box.envelope` for the axis
# that made the sweep generic. Five axes here, and the **tab position** is the one this
# archetype contributes that no other has: it is the only parameter that changes the
# *shape* of the outline rather than a length. An edge tab shares a side plane with the
# plate, which is exactly the case a union got wrong and an extruded outline does not,
# so dropping `left` and `right` would leave the sweep looking parametrized while the
# only interesting outline went unbuilt.

#: One count, not an axis: the plate's footprint comes from the sleeve envelope, and
#: `SWEEP_SLEEVINGS` already moves it. A second count would move nothing else.
SWEEP_COUNT: int = 100
SWEEP_SLEEVINGS: tuple[str, ...] = ("none", "single", "double")
SWEEP_POSITIONS: tuple[str, ...] = ("left", "centre", "right")
#: The audited 1,2–1,6 mm insert band, plus one over it.
SWEEP_THICKNESSES: tuple[float, ...] = (1.2, 1.4, 1.6, 2.0)
SWEEP_TAB_WIDTHS: tuple[float, ...] = (12.0, 20.0, 30.0)
SWEEP_TAB_HEIGHTS: tuple[float, ...] = (6.0, 10.0, 15.0)
#: The corner set that goes on through Phase 3's assert path, as (thickness, tab width,
#: tab height) triples swept against every sleeving and every position — each one a
#: point of the product above, so the corners are a subset of the envelope.
SWEEP_PHASE_3_TABS: tuple[tuple[float, float, float], ...] = (
    (1.2, 12.0, 6.0), (1.4, 20.0, 10.0), (2.0, 30.0, 15.0), (1.2, 30.0, 6.0),
)


# ── The lettering envelope (issue #157) ───────────────────────────────────────
#
# Its own prefix (`letter-`) and its own axes, rather than multiplying the 324 above by
# them. Decoration is orthogonal to the tab geometry — it neither moves a designed
# dimension nor is moved by one, which is the property the sweep is there to prove — so
# crossing the two would buy repetition and 2 000 booleans.
#
# The tab these are set on is deliberately generous (44 × 16 mm): the *default* 20 × 10 mm
# tab does not take an 8 mm cap height and is refused with a remedy, which is a rule
# `tests/test_card_divider.py` asserts rather than an envelope case. An envelope asks only
# for parts the archetype would accept.

#: The tab every lettering case is set on, mm. Wide enough for the longest string below
#: and no wider: 64 mm leaves 62 mm of usable face inside `EMBOSS_EDGE_MARGIN_MM`, and
#: `"COMMANDER"` at a 6 mm cap sets 60,9 mm. It stays under the 67 mm plate width a
#: double-sleeved standard card gives, which `validate` requires of any tab.
SWEEP_LETTER_TAB: tuple[float, float] = (64.0, 16.0)
#: The four strings the issue asks for, by name: the longest that fits, the shortest, a
#: mixed-case one whose ascenders and descenders make the ink taller than the cap height,
#: and a glyph set at the stroke floor. "Empty" is a *refusal*, not a sweep case — the
#: schema will not build an `Emboss` with no text — and is asserted as one in the tests.
SWEEP_LETTER_TEXTS: tuple[tuple[str, str, float], ...] = (
    ("longest", "COMMANDER", 6.0),
    ("shortest", "A", 12.0),
    ("mixed", "Lands", 8.0),
    # 6,3 mm is a whisker over the 6,21 mm at which `a`'s 0,117 em stroke reaches
    # `process.min_feature_mm`, so this case sets a glyph **at** the floor and is the one
    # that fails first if the stroke measurement ever drifts.
    ("floor", "a", 6.3),
)
SWEEP_LETTER_MODES: tuple[str, ...] = ("raised", "recessed")
#: 2,0 mm of plate, so a 0,6 mm recess still leaves 1,4 mm over `min_feature_mm`.
SWEEP_LETTER_THICKNESS = 2.0
SWEEP_LETTER_RELIEFS: tuple[float, ...] = (0.4, 0.6, 1.0)


def _lettering_cases() -> list[SweepCase]:
    """The decorated specs, one per (text, mode, relief) — 24 of them."""
    tab_w, tab_h = SWEEP_LETTER_TAB
    cases: list[SweepCase] = []
    for (name, text, height), mode, relief in itertools.product(
        SWEEP_LETTER_TEXTS, SWEEP_LETTER_MODES, SWEEP_LETTER_RELIEFS,
    ):
        cases.append(SweepCase(
            id=f"letter-{name}-{mode}-h{height:g}-r{relief:g}",
            spec=OrganizerSpec(
                archetype=ARCHETYPE,
                compartments=(Compartment(CardStack(count=SWEEP_COUNT)),),
                divider=Divider(thickness_mm=SWEEP_LETTER_THICKNESS,
                                tab_width_mm=tab_w, tab_height_mm=tab_h),
                emboss=Emboss(text=text, face="tab", mode=mode,
                              height_mm=height, relief_mm=relief),
            ),
            # One corner through Phase 3, on the sweep's own rule: the repair round is
            # orthogonal to these axes and costs a mesh repair per case. `raised` rather
            # than `recessed`, because a raised glyph is the one that could come back as
            # a separate body.
            phase_3=(name == "mixed" and mode == "raised" and relief == 0.6),
        ))
    return cases


def envelope() -> tuple[SweepCase, ...]:
    """Every spec the dimensional sweep drives this archetype over — 348 of them."""
    cases: list[SweepCase] = []
    for sleeving, position, thickness, tab_width, tab_height in itertools.product(
        SWEEP_SLEEVINGS, SWEEP_POSITIONS, SWEEP_THICKNESSES, SWEEP_TAB_WIDTHS,
        SWEEP_TAB_HEIGHTS,
    ):
        cases.append(SweepCase(
            id=(f"{sleeving}-{position}-t{thickness:g}"
                f"-tab{tab_width:g}x{tab_height:g}"),
            spec=OrganizerSpec(
                archetype=ARCHETYPE,
                compartments=(
                    Compartment(CardStack(count=SWEEP_COUNT, sleeving=sleeving)),
                ),
                divider=Divider(thickness_mm=thickness, tab_width_mm=tab_width,
                                tab_height_mm=tab_height, tab_position=position),
            ),
            phase_3=(thickness, tab_width, tab_height) in SWEEP_PHASE_3_TABS,
        ))
    return tuple(cases + _lettering_cases())
