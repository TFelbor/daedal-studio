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

It lives here rather than in `compiler.py` (the kernel bridge and the measurers) or in
`archetypes/__init__.py` (which imports the archetype modules, so a helper there is a
circular import). Each function is deliberately thin and takes its wording as an
argument: the *subject* of a refusal is the archetype's, not this module's, so the
messages a person reads stay the archetype's own sentences.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Optional

from ..compiler import MeasureError, face_planes
from ..spec import CardStack, OrganizerSpec

#: The order `constraints.max_external_mm` is written in, and the words a remedy uses.
EXTERNAL_AXES: tuple[str, str, str] = ("width", "depth", "height")


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
    for axis, extent, limit, stated_limit in zip(EXTERNAL_AXES, extents, limits, stated):
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
        "Give each compartment a card stack (count, card, sleeving), or use archetype "
        "'token_tray' for pockets"
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


def expect_planes(part: Any, axis: int, expected: int, *, what: str, subject: str) -> list[float]:
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

    Raises:
        MeasureError: Naming the count found, the count designed and every plane.
    """
    planes = face_planes(part, axis)
    if len(planes) != expected:
        raise MeasureError(
            f"the {what} has {len(planes)} distinct {'XYZ'[axis]} planes where {subject} "
            f"has {expected}: {[round(v, 3) for v in planes]}"
        )
    return planes


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
