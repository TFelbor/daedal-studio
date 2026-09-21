"""The things every archetype module has that are not about its own shape.

Extracted when the second archetype landed (issue #65), because that is the moment a
habit becomes an API: `deck_box.py` had a compartment-count rule, a plane-count
assertion and a view-row builder, and a card divider needs all three in the same words.
Copying them would have given two archetypes two spellings of "holds exactly one
compartment" — and the pilot's own question, *is the archetype API an API*, is answered
by what a second module has to duplicate. The external-limit comparison (issue #70)
joined them for the same reason and one more: `constraints.fit_margin_mm` is a rule
about *specs*, so two archetypes subtracting it in two places is one refactor away from
two archetypes subtracting it differently.

The annotated preview's two builders (issue #88) joined for the third reason: `callout`
refuses a line whose length disagrees with the number printed on it, and a rule that
keeps a drawn millimetre honest is worth exactly one implementation.

It lives here rather than in `compiler.py` (the kernel bridge and the measurers) or in
`archetypes/__init__.py` (which imports the archetype modules, so a helper there is a
circular import). Each function is deliberately thin and takes its wording as an
argument: the *subject* of a refusal is the archetype's, not this module's, so the
messages a person reads stay the archetype's own sentences.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from .. import lettering
from ..compiler import (
    Box,
    CompileResult,
    FaceFrame,
    MeasureError,
    face_plane_extent,
    face_planes,
    face_planes_within,
    thinnest_stroke_mm,
    tilted_face_extent,
)
from ..spec import (
    DEFAULT_NOZZLE_DIAMETER_MM,
    EMBOSS_MODES,
    CardStack,
    OrganizerSpec,
    SpecError,
)

#: The order `constraints.max_external_mm` is written in, and the words a remedy uses.
EXTERNAL_AXES: tuple[str, str, str] = ("width", "depth", "height")

#: The tier a callout the viewer shows on a phone belongs to (issue #88). Tier 1 is the
#: internal figures a misparse costs an eight-hour print over — the cavity a deck goes
#: into, the engagement a lid closes on; tier 2 is the externals and the material
#: thicknesses, which a person reads off the fits line anyway. The 720 px step of the
#: app's one breakpoint ladder (`tests/test_layout_ladder.py`) shows tier 1 only.
CALLOUT_TIER_INTERNAL = 1
CALLOUT_TIER_EXTERNAL = 2


@dataclass(frozen=True)
class Overshoot:
    """One axis whose extent does not fit inside the effective external limit.

    Attributes:
        axis: `"width"`, `"depth"` or `"height"`.
        extent: What the part measures on that axis, mm.
        limit: The limit actually compared against — `stated − margin`, mm.
        stated: `constraints.max_external_mm` on that axis, mm.
        margin: `constraints.fit_margin_mm`, mm.
        note: The sentence a remedy is built from.
    """

    axis: str
    extent: float
    limit: float
    stated: float
    margin: float
    note: str


def external_overshoots(
    spec: OrganizerSpec, extents: Iterable[float], *, prefix: str = ""
) -> list[Overshoot]:
    """Every axis on which `extents` exceeds the effective external limit.

    The limit compared against is `constraints.max_external_mm` **minus**
    `constraints.fit_margin_mm` on every axis — see `Constraints` for why a measured
    box internal is not the number to build to. The margin is named in the sentence
    (`"… exceeds 88 mm (max_external 90 − 2 margin)"`) so that a part refused by two
    millimetres nobody typed is explained where it is refused rather than in a
    docstring. A **zero** margin prints no parenthetical at all, so a person who
    measured the box they are filling and set `fit_margin_mm: 0` reads exactly the
    sentence this project printed before the margin existed.

    Args:
        spec: The spec whose `constraints` supply the limit.
        extents: The part's (width, depth, height) in mm, in that order.
        prefix: What the archetype calls the measurement, e.g. `"external "`.

    Returns:
        One `Overshoot` per failing axis, in axis order; empty when the spec carries
        no `max_external_mm` or every axis fits.
    """
    limits = spec.constraints.effective_max_external_mm()
    if limits is None:
        return []
    stated = spec.constraints.max_external_mm
    assert stated is not None  # effective_max_external_mm() returned a tuple
    margin = spec.constraints.fit_margin_mm
    out: list[Overshoot] = []
    for axis, extent, limit, stated_limit in zip(EXTERNAL_AXES, extents, limits, stated, strict=True):
        if extent <= limit + 1e-9:
            continue
        how = f" (max_external {stated_limit:g} − {margin:g} margin)" if margin else ""
        out.append(Overshoot(
            axis=axis, extent=extent, limit=limit, stated=stated_limit, margin=margin,
            note=(
                f"{prefix}{axis} {extent:g} mm exceeds {limit:g} mm{how} "
                f"by {extent - limit:.1f} mm"
            ),
        ))
    return out


@dataclass(frozen=True)
class Undershoot:
    """One axis on which the part is *smaller* than the room it was given.

    The mirror of `Overshoot`, and it exists because an insert fails in both directions
    while a deck box only fails in one. A box you carry that comes out 3 mm narrower than
    a limit somebody typed is simply a box; an insert 3 mm narrower than the interior it
    fills **rattles**, which slides the compartments under the lid and tips the contents
    out — the failure mode locking tabs and fill-to-interior exist for, neither of which
    is built. So the gap is reported rather than passed over in silence, and it is
    reported as a *number* rather than as a verdict: an insert that does not fill the box
    is not refused and is not "does not fit", it is an insert with a stated gap.

    Measured against the **effective** limit — `stated − fit_margin_mm` — for the same
    reason `Overshoot` is: the margin is room the insert is not allowed to use, so
    counting it as a gap would report two millimetres of deliberate clearance as a fault
    on every part that fits perfectly.

    Attributes:
        axis: `"width"`, `"depth"` or `"height"`.
        extent: What the part measures on that axis, mm.
        limit: The limit actually compared against — `stated − margin`, mm.
        gap: `limit − extent`, mm. Always positive.
        note: The sentence a fits line is built from.
    """

    axis: str
    extent: float
    limit: float
    gap: float
    note: str


def external_undershoots(
    spec: OrganizerSpec, extents: Iterable[float], *, tol_mm: float = 0.05
) -> list[Undershoot]:
    """Every axis on which `extents` falls short of the effective external limit.

    Args:
        spec: The spec whose `constraints` supply the limit.
        extents: The part's (width, depth, height) in mm, in that order.
        tol_mm: How short an axis may fall before it is worth saying so. The default is
            `compiler.DEFAULT_TOLERANCE_MM`, spelled as a number rather than imported,
            because it is answering a different question — the smallest gap worth
            printing, not the largest error allowed — and tying them together would make
            a tolerance change silently rewrite a sentence.

    Returns:
        One `Undershoot` per short axis, in axis order; empty when the spec carries no
        `max_external_mm` or every axis fills its limit.
    """
    limits = spec.constraints.effective_max_external_mm()
    if limits is None:
        return []
    out: list[Undershoot] = []
    for axis, extent, limit in zip(EXTERNAL_AXES, extents, limits, strict=True):
        gap = limit - extent
        if gap <= tol_mm:
            continue
        out.append(Undershoot(
            axis=axis, extent=extent, limit=limit, gap=gap,
            note=f"{gap:.1f} mm short of the box on {axis}",
        ))
    return out


def single_compartment_problem(
    spec: OrganizerSpec, *, subject: str, holds: str
) -> Optional[str]:
    """The problem sentence for an archetype that takes exactly one compartment, or None.

    The two card archetypes take one: a deck box holds one deck, a divider labels one
    group. It is no longer the *only* rule available — `token_tray` (issue #84) lays out
    a grid, and `Compartment.contents` is a `CardStack | Pocket` union — so this is the
    rule for the archetypes that hold one card stack rather than a fact about specs.

    Args:
        spec: The spec to check.
        subject: How the archetype names itself in a refusal, e.g. `"deck_box v1"`.
        holds: What the one compartment is, e.g. `"the deck"`.
    """
    count = len(spec.compartments)
    if count == 1:
        return None
    return f"{subject} holds exactly one compartment ({holds}); got {count}"


def card_contents_problem(spec: OrganizerSpec, *, subject: str) -> Optional[str]:
    """The problem sentence for a card archetype handed a pocket compartment, or None.

    `Compartment.contents` became a union when the token tray landed, so an archetype
    that resolves its geometry from the dimension table can now be handed millimetres
    it has no envelope, pitch or sleeving for. `derive()` would reach for
    `contents.count` and raise an `AttributeError` three frames in; this refuses it by
    name, with the archetype that *does* build pockets named as the remedy — which is
    what every other archetype-level rule here does.

    Args:
        spec: The spec to check.
        subject: How the archetype names itself in a refusal, e.g. `"deck_box v1"`.
    """
    wrong = [i for i, c in enumerate(spec.compartments) if not isinstance(c.contents, CardStack)]
    if not wrong:
        return None
    return (
        f"{subject} holds card stacks, not pockets; compartments{wrong} carry a pocket. "
        "Give each compartment a card stack (count, card, sleeving), use archetype "
        "'token_tray' for a grid of pockets, or 'box_insert' for cards and pockets in "
        "one part"
    )


def stray_section_problem(
    spec: OrganizerSpec, *, section: str, subject: str, owner: str
) -> Optional[str]:
    """The problem sentence for a spec carrying a section this archetype never reads.

    Ignoring one prints a different part in silence, which is the rule every archetype
    here already states in its own words for the sections that existed when it was
    written. It became worth sharing at the third section (`tray`): each archetype now
    has to refuse two it does not own, and three near-identical sentences in three
    modules is how two of them end up saying different things.

    Args:
        spec: The spec to check.
        section: The field name on `OrganizerSpec`, e.g. `"tray"`.
        subject: How the archetype names itself, e.g. `"deck_box v1"`.
        owner: The archetype the section belongs to, e.g. `"token_tray"`.
    """
    if getattr(spec, section) is None:
        return None
    return (
        f"{subject} does not lay out a {section}; the {section} section belongs to "
        f"archetype {owner!r} — remove it or change the archetype"
    )


# ── lettering (F13, issue #157) ────────────────────────────────────────────────

#: The archetypes that letter a face. Named in the refusal a tray or an insert gives, so
#: a person who asked the wrong shape for an emboss is told which shape to ask instead —
#: which is what every archetype-level rule here already does.
#: `tests/test_lettering_rules.py` binds this tuple to the modules that declare
#: `EMBOSS_FACES`, in both directions, so it cannot drift from the truth.
LETTERING_ARCHETYPES: tuple[str, ...] = ("deck_box", "card_divider")

#: How many extrusion widths a glyph stroke is held to, beside `process.min_feature_mm`.
#:
#: **Two**, not the wall's three (`spec.WALL_FLOOR_NOZZLE_MULTIPLE`), and the difference
#: is the difference between the two questions. A wall carries load and wants three
#: perimeters; a raised letter carries nothing and only has to *exist* — two extrusion
#: widths is `printability.min_wall_mm`, what the extruder can physically put down, which
#: is the same floor the printability gate will judge the finished mesh against. Spelled
#: here rather than imported from `printability`, which the api-server does not ship and
#: which would drag trimesh into this module.
STROKE_NOZZLE_MULTIPLE = 2.0


def stroke_floor_mm(
    spec: OrganizerSpec, nozzle_diameter_mm: float = DEFAULT_NOZZLE_DIAMETER_MM
) -> float:
    """The thinnest glyph stroke this spec may ask for on this nozzle, in mm.

    The larger of `process.min_feature_mm` — what the *design* calls a feature — and two
    extrusion widths, what the *machine* can lay. At the defaults the first wins (1,0 mm
    against 0,8 mm); on a 0,6 mm nozzle the second does (1,0 against 1,2), which is the
    whole reason it is expressed as a multiple of the nozzle and not as a millimetre.
    """
    return max(
        float(spec.process.min_feature_mm),
        round(STROKE_NOZZLE_MULTIPLE * float(nozzle_diameter_mm), 3),
    )


def lettering_problems(
    spec: OrganizerSpec,
    module: Any,
    nozzle_diameter_mm: float = DEFAULT_NOZZLE_DIAMETER_MM,
) -> list[str]:
    """Every refusal `spec.emboss` earns on this archetype and this nozzle, or [].

    Called from `archetypes.compile_spec`, beside `wall_floor_problems` and for its
    reasons verbatim: this is the one place that has the spec, the archetype *and* the
    printer profile's nozzle in one frame, and it runs before Phase 2 has written a mesh,
    a spec file or a features document into the job directory. A glyph the machine cannot
    lay must be refused where a person can still change it — **not discovered in Phase 4**
    as a slicer that quietly omitted the name the box was printed for.

    A list rather than a raise, so the caller reports it beside the archetype's own
    findings: a spec is refused whole, with every problem named at once.

    Five rules, in the order a reader can act on them:

    1. **The archetype letters this face at all.** A token tray and a box insert letter
       nothing (their outer faces live inside a game box, and a 1,6 mm wall cannot host a
       0,6 mm recess above the floor), so they refuse the section naming the two that do.
    2. **The font can set the text.** A missing glyph is named with its code point; it is
       never substituted.
    3. **The face honours this mode.** A face that lies against the bed, or stands
       vertical, honours `recessed` only — see the archetype's `emboss_frame`.
    4. **The ink fits the face.** Refused *with the measurement and the cap height that
       would fit*, never scaled and never wrapped. Shrinking a person's lettering to make
       it fit is the same fabrication as shrinking the part.
    5. **The stroke, the relief and the material behind it clear their floors.** Each
       names the field that moves it and the number it has to clear.

    Args:
        spec: The spec, already schema-valid.
        module: The archetype module. Read for `ARCHETYPE`, `ARCHETYPE_VERSION`,
            `EMBOSS_FACES` and `emboss_frame`.
        nozzle_diameter_mm: The printer profile's `machine_nozzle_size`.
    """
    emboss = spec.emboss
    if emboss is None:
        return []
    subject = f"{getattr(module, 'ARCHETYPE', '?')} v{getattr(module, 'ARCHETYPE_VERSION', '?')}"
    faces = tuple(getattr(module, "EMBOSS_FACES", ()))
    if not faces:
        owners = " and ".join(repr(name) for name in LETTERING_ARCHETYPES)
        return [
            f"spec.emboss is not a section {subject} builds; lettering belongs to "
            f"archetypes {owners} — remove it or change the archetype"
        ]
    if emboss.face not in faces:
        return [
            f"spec.emboss.face {emboss.face!r} is not a face {subject} letters; it "
            f"letters {list(faces)}. Choose one of those, or change the archetype"
        ]
    problems = lettering.text_problems(emboss.text, "spec.emboss.text")
    if problems:
        return problems
    try:
        frame = module.emboss_frame(spec)
    except SpecError:
        # The spec is unbuildable for reasons that are not about its lettering, and the
        # archetype's own `validate` is about to name every one of them. Adding "the text
        # does not fit a face that does not exist" would be noise on top of the finding.
        return []
    if emboss.mode not in frame.modes:
        refused = [m for m in EMBOSS_MODES if m not in frame.modes]
        problems.append(
            f"spec.emboss.mode {emboss.mode!r} is not available on the {emboss.face!r} "
            f"face of {subject}, which takes {list(frame.modes)}. "
            + _mode_reason(frame, refused)
        )
        return problems
    ink_w, ink_h = lettering.ink_extent_mm(emboss.text, emboss.height_mm)
    if ink_w > frame.width_mm + 1e-9 or ink_h > frame.height_mm + 1e-9:
        largest = lettering.largest_cap_height_mm(
            emboss.text, frame.width_mm, frame.height_mm
        )
        # Rounded **down** to 0,1 mm: a remedy that has to be rounded up again is not a
        # remedy, and the schema keeps millimetres to 1 µm anyway.
        remedy = math.floor(largest * 10.0) / 10.0
        problems.append(
            f"spec.emboss.text {emboss.text!r} at {emboss.height_mm:g} mm sets "
            f"{ink_w:.1f} × {ink_h:.1f} mm, and the {emboss.face!r} face of {subject} "
            f"offers {frame.width_mm:.1f} × {frame.height_mm:.1f} mm. Shorten the text, "
            + (
                f"or set spec.emboss.height_mm to {remedy:g} mm or less"
                if remedy > 0.0
                else "or letter a larger face — nothing this long fits it at any size"
            )
        )
    stroke = thinnest_stroke_mm(emboss.text, emboss.height_mm)
    floor = stroke_floor_mm(spec, nozzle_diameter_mm)
    if stroke + 1e-9 < floor:
        needed = math.ceil(emboss.height_mm * floor / stroke * 10.0) / 10.0
        problems.append(
            f"spec.emboss.height_mm {emboss.height_mm:g} mm sets {emboss.text!r} with a "
            f"{stroke:.2f} mm thinnest stroke, below the {floor:g} mm floor "
            f"(the larger of process.min_feature_mm {spec.process.min_feature_mm:g} and "
            f"{STROKE_NOZZLE_MULTIPLE:g} × the {float(nozzle_diameter_mm):g} mm nozzle "
            "this printer profile declares). A raised stroke thinner than an extrusion "
            "is a fin the nozzle cannot lay, and a recess narrower than one is filled in "
            f"by the next pass. Set spec.emboss.height_mm to {needed:g} mm or more, or "
            "fit a finer nozzle"
        )
    elif emboss.mode == "raised" and emboss.relief_mm > stroke + 1e-9:
        problems.append(
            f"spec.emboss.relief_mm {emboss.relief_mm:g} mm stands taller than the "
            f"{stroke:.2f} mm thinnest stroke of {emboss.text!r} at "
            f"{emboss.height_mm:g} mm, so the narrowest letter would be a fin taller "
            "than it is wide and would snap off. Reduce the relief, or raise "
            "spec.emboss.height_mm"
        )
    if emboss.mode == "recessed":
        left = frame.material_mm - emboss.relief_mm
        if left + 1e-9 < frame.material_floor_mm:
            problems.append(
                f"spec.emboss.relief_mm {emboss.relief_mm:g} mm cut into the "
                f"{emboss.face!r} face leaves {left:.3f} mm of {frame.material_name} "
                f"({frame.material_mm:g} mm), below the {frame.material_floor_mm:g} mm "
                f"floor that wall is held to. Reduce the relief, thicken "
                f"{frame.material_name}, or raise the text instead of sinking it"
            )
    return problems


def measured_relief(part: Any, region: Box, axis: int, *, subject: str) -> float:
    """How far the lettering stands off its face, mm, read inside its own region.

    Two planes and only two live in there on the face's own axis: the face, and the glyph
    tops (raised) or the recess floor (recessed). Their difference is the relief whichever
    way round it is, which is why one measurement serves both modes and every face — the
    axis is the frame's, and nothing else about the read changes. Anything other than two
    planes means the decoration is not the shape the design says, and *that* is the
    measurement's finding rather than a per-feature error.

    Shared for `measured_chamfer`'s reason: it is the measurement of a spec-level feature
    rather than of one archetype's shape, and two modules reading it off two spellings is
    one refactor away from two modules disagreeing about how deep 0,6 mm is.

    Raises:
        MeasureError: Naming the axis and what was found instead.
    """
    planes = face_planes_within(part, axis, region)
    if len(planes) != 2:
        raise MeasureError(
            f"the lettering region has {len(planes)} distinct {'XYZ'[axis]} planes where "
            f"{subject} puts 2 (the face and the glyphs): {[round(v, 3) for v in planes]}"
        )
    return planes[1] - planes[0]


def shifted_region(region: Box, measured_min: Any, design_min: Iterable[float]) -> Box:
    """`region` moved by however far the part has actually travelled since it was built.

    Phase 3 re-centres a plate in X and Y and sets it on Z = 0 before anything measures
    it, so a region stated in the frame the design was built in is in the wrong place by
    one vector. The offset is the part's measured minimum corner less the corner the
    design put it at — a translation the whole body shares, which is the only thing Phase
    3's assert path does to a compiled plate (`--target-mm` is refused there).
    """
    shift = [float(m) - float(dsn) for m, dsn in zip(measured_min, design_min, strict=True)]
    return tuple(  # type: ignore[return-value]
        (low + shift[axis], high + shift[axis]) for axis, (low, high) in enumerate(region)
    )


def _mode_reason(frame: FaceFrame, refused: list[str]) -> str:
    """Why a face honours only some of `EMBOSS_MODES`, in one sentence.

    The sentence is here rather than on the archetype because it is a fact about *how a
    part is printed* rather than about a shape: a raised feature cannot stand on the face
    that is against the bed, and one on a vertical wall needs a 45° underside
    `base_chamfer` cannot build — that primitive wants one convex contour and a glyph is
    neither.
    """
    if "raised" not in refused:
        return ""
    if frame.normal[2] < -0.5:
        return (
            "This face lies against the build plate — the part is printed with it down —"
            " so raised text would have to stand through the bed. Sink it instead"
        )
    if abs(frame.normal[2]) < 0.5:
        return (
            "This face is vertical, so a raised letter would overhang at 90° along its "
            "whole underside and need support. Sink it instead, or letter a face that "
            "points up"
        )
    return "Sink it instead"


def expect_planes(
    part: Any,
    axis: int,
    expected: int,
    *,
    what: str,
    subject: str,
    exclude_mm: Optional[Box] = None,
) -> list[float]:
    """The distinct axis-aligned planes of `part` on `axis`, or the finding.

    A plane count that does not match the design *is* the measurement's finding, not a
    per-feature error: geometry without the planes the design says it has cannot be
    measured against that design at all.

    Reads the mesh's **faces** (`compiler.face_planes`) rather than a column of its
    vertices. The two agree exactly on a part built from axis-aligned boxes, which is
    what every archetype was when this helper was written; they stop agreeing the
    moment an edge is rounded, because a vertical fillet puts a vertex at every
    coordinate between the tangent point and the corner while leaving the design's walls
    the only faces square to the axis. Faces are the honest reading of "which planes
    does this part have", and it is the reading a rounded box survives.

    Args:
        part: A mesh (or mesh body) with `vertices` and `faces` arrays.
        axis: 0, 1 or 2 for X, Y or Z.
        expected: How many distinct planes the design puts on that axis.
        what: The body being measured, e.g. `"lid"`, for the message.
        subject: The archetype and version, e.g. `"a deck box v2"`.
        exclude_mm: A region to leave out of the read — the box a decoration occupies.
            Decoration is not a designed feature, so the planes its glyphs put on the
            mesh are not planes this count is about; see `compiler._outside`.

    Raises:
        MeasureError: Naming the count found, the count designed and every plane.
    """
    planes = face_planes(part, axis, exclude_mm=exclude_mm)
    if len(planes) != expected:
        raise MeasureError(
            f"the {what} has {len(planes)} distinct {'XYZ'[axis]} planes where {subject} "
            f"has {expected}: {[round(v, 3) for v in planes]}"
        )
    return planes


#: How far a chamfer face may sit from 45° before the measurement is a finding rather
#: than a number. `compiler.base_chamfer` builds the angle exactly — every face is the
#: supporting plane through a chord and the same chord moved in by `c` and down by `c` —
#: so this is a check on the *mesh*, not a tolerance on the design: a tenth of a degree
#: is four orders above what the kernel's own float noise produces and far below anything
#: a broken construction would.
CHAMFER_ANGLE_TOL_DEG = 0.1


def measured_chamfer(
    part: Any, *, what: str, subject: str, exclude_mm: Optional[Box] = None
) -> float:
    """The height of `part`'s base chamfer, refusing a mesh whose slope is not 45°.

    A chamfer is not a difference of two planes, so it is measured off the faces that
    slope: the only ones on these archetypes that point downward without being the bed
    face. Their Z extent *is* the chamfer, and their tilt is checked rather than assumed,
    because a face at 30° would measure a plausible height off a part nobody designed. A
    part with no sloping face measures 0 — right for a designed 0, out of tolerance for
    anything else.

    Here rather than in `deck_box.py`, where it was written, at the moment a second
    archetype carries the same treatment: the chamfer and the external round are
    `process` parameters that every body on a bed wants, so two modules reading them off
    two spellings is one refactor away from two modules disagreeing about what 45° means.

    Args:
        part: A mesh body with `vertices` and `faces`.
        what: The body being measured, e.g. `"lid"`, for the message.
        subject: How the archetype names itself, e.g. `"a deck box v2"`.
        exclude_mm: The lettering region, when the body carries one. A glyph sunk into a
            vertical wall puts downward-facing faces at every angle between 8° and 87°
            along the top of every bowl, and a chamfer read that counted them would report
            a body 41° out of true — see `compiler.tilted_face_extent`.

    Raises:
        MeasureError: If any sloping face is further than `CHAMFER_ANGLE_TOL_DEG` from 45°.
    """
    low, high, worst_error_deg = tilted_face_extent(part, exclude_mm=exclude_mm)
    if worst_error_deg > CHAMFER_ANGLE_TOL_DEG:
        raise MeasureError(
            f"the {what}'s base chamfer is {45.0 + worst_error_deg:.3f}° at its worst "
            f"where {subject} cuts 45°"
        )
    return high - low


def measured_corner_radius(part: Any, y_plane: float, x_plane: float) -> float:
    """The radius of the vertical corners a wall runs between, as a plane difference.

    The wall in the plane `Y = y_plane` runs from its tangent point to its tangent
    point — `r` in from each end — so the radius is where that wall starts along X minus
    the X plane the design says it starts at. Exact vertices both, which is why a radius
    survives the float32 export like every other feature here; a square corner gives 0.

    Shared for `measured_chamfer`'s reason: it is the measurement of a `process`
    parameter rather than of one archetype's shape.
    """
    return face_plane_extent(part, 1, y_plane, 0)[0] - x_plane


def view_row(
    key: str,
    label: str,
    value: float,
    unit: str,
    editable: bool,
    note: str | None = None,
) -> dict[str, Any]:
    """One row of `to_view`'s table, shaped as `SpecDimension` in
    `web/src/organizer/spec.ts`. `note` is omitted when empty rather than sent as null,
    because the interface declares it optional."""
    out: dict[str, Any] = {
        "key": key, "label": label, "value": value, "unit": unit, "editable": editable,
    }
    if note:
        out["note"] = note
    return out


def view_frame(result: CompileResult) -> dict[str, Any]:
    """The frame `callouts` are stated in: millimetres, Z up, and the plate's own bounds.

    The viewer reconciles this against the mesh it was served before it draws a single
    number (issue #88). Phase 3's assert path only *translates* a compiled plate — it is
    XY-centred and sat on Z = 0, and `--target-mm` is refused in assert mode — so the
    served mesh differs from these bounds by one vector and the callouts follow it. If
    that ever stops being true the extents stop matching, and the viewer draws nothing
    rather than annotating a part with another part's millimetres.

    `min` is not assumed to be the origin even though every archetype here builds from
    it: a frame that states its own minimum is a frame the reconciliation can subtract.
    """
    low, high = result.mesh.bounds
    return {
        "units": "mm",
        "up": "z",
        "bounds_mm": {
            "min": [round(float(v), 3) for v in low],
            "max": [round(float(v), 3) for v in high],
        },
    }


def callout(
    feature: str,
    label: str,
    value_mm: float,
    *,
    part: str,
    frm: tuple[float, float, float],
    to: tuple[float, float, float],
    offset: tuple[float, float, float],
    tier: int = CALLOUT_TIER_INTERNAL,
) -> dict[str, Any]:
    """One dimension line the viewer draws in millimetres, anchored to the geometry.

    A callout is **not allowed to carry a number of its own**. `value_mm` is a designed
    feature the archetype already publishes under `feature`, and the endpoints are where
    that length physically is on the part — so a spec diff re-annotates by changing the
    spec, and nothing in a browser ever computes a millimetre. The one check made here is
    the one that makes the anchor honest: the endpoints have to be `value_mm` apart, or
    the line drawn on screen would disagree with the number printed beside it.

    The line is axis-aligned by construction — exactly one coordinate differs — which is
    what lets `tests/test_view_callouts.py` assert that both ends sit on face planes of
    the part named. That is the assertion which catches a cavity callout drawn on the
    outer wall: the number would be right and the line would be somewhere else.

    Args:
        feature: A key of the archetype's designed features, and a name
            `archetypes.required_measurements` promises Phase 3 measures back.
        label: What a person reads, e.g. `"Internal width"`.
        value_mm: The designed value, taken verbatim from the feature — never re-derived.
        part: Which body of the compile result the line lies on, e.g. `"body"`.
        frm: The line's start, mm, in the plate frame `view_frame` describes.
        to: The line's end, in the same frame.
        offset: The free-space direction beside the line — a unit vector **across** it,
            which the viewer nudges the line along to clear the surface and fades the
            label by when it turns away from the camera. Across rather than along,
            because an offset parallel to the line would shorten the thing it labels.
        tier: `CALLOUT_TIER_INTERNAL` or `CALLOUT_TIER_EXTERNAL`.

    Raises:
        MeasureError: If the endpoints are not `value_mm` apart, are not on one axis, or
            the offset runs along the line rather than across it.
    """
    span = [b - a for a, b in zip(frm, to, strict=True)]
    moved = [i for i, v in enumerate(span) if abs(v) > 1e-9]
    if len(moved) != 1:
        raise MeasureError(
            f"callout {feature!r} runs along {len(moved)} axes; a dimension line is "
            f"axis-aligned: {list(frm)} → {list(to)}"
        )
    length = abs(span[moved[0]])
    if abs(length - float(value_mm)) > 1e-6:
        raise MeasureError(
            f"callout {feature!r} is labelled {value_mm} mm and drawn {length:.6f} mm "
            f"long ({list(frm)} → {list(to)}); the line and the number must agree"
        )
    if offset[moved[0]] or not any(offset):
        raise MeasureError(
            f"callout {feature!r} is offset {list(offset)}, which runs along the line "
            f"rather than across it; the nudge would shorten what it labels"
        )
    return {
        "feature": feature,
        "label": label,
        "value_mm": round(float(value_mm), 3),
        "part": part,
        "from": [round(float(v), 3) for v in frm],
        "to": [round(float(v), 3) for v in to],
        "offset": [float(v) for v in offset],
        "tier": int(tier),
    }


@dataclass(frozen=True)
class SweepCase:
    """One spec in an archetype's declared dimensional envelope (issue #85).

    The envelope is the **domain of the ±0,05 mm claim**: the set of specs an archetype
    holds itself to, declared by the module that builds them rather than by the test
    that drives them. `tests/test_organizer_dimensional_accuracy.py` iterates every
    registered archetype, asks it for these, and asserts the same five things about
    each — watertight, no non-manifold edge, accepted by the `manifold3d` kernel, every
    measured feature within `DEFAULT_TOLERANCE_MM`, and the measured set equal to what
    `required_measurements` promised. A module that declares none fails that test by
    name: an archetype nothing sweeps has made no accuracy claim, and the claim is what
    makes it an archetype rather than a mesh generator.

    Attributes:
        id: Unique within the archetype, and read by a person in a pytest node id, so
            it names the axes rather than an index — `n100-double-wall2.8-clr0.2-lid15`.
        spec: The spec to compile. Schema-valid, and buildable: an envelope asks only
            for parts the archetype would accept, so a refusal is a failure.
        phase_3: Whether this case also goes through Phase 3's assert path. A corner
            set rather than the whole envelope, because Phase 3 costs a mesh repair
            round per case and is orthogonal to the axes the envelope sweeps.
    """

    id: str
    spec: OrganizerSpec
    phase_3: bool = False
