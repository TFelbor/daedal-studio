"""The three things every archetype module has that are not about its own shape.

Extracted when the second archetype landed (issue #65), because that is the moment a
habit becomes an API: `deck_box.py` had a compartment-count rule, a plane-count
assertion and a view-row builder, and a card divider needs all three in the same words.
Copying them would have given two archetypes two spellings of "holds exactly one
compartment" — and the pilot's own question, *is the archetype API an API*, is answered
by what a second module has to duplicate.

It lives here rather than in `compiler.py` (the kernel bridge and the measurers) or in
`archetypes/__init__.py` (which imports the archetype modules, so a helper there is a
circular import). Each function is deliberately thin and takes its wording as an
argument: the *subject* of a refusal is the archetype's, not this module's, so the
messages a person reads stay the archetype's own sentences.
"""
from __future__ import annotations

from typing import Any, Optional

from ..compiler import MeasureError, plane_set
from ..spec import OrganizerSpec


def single_compartment_problem(
    spec: OrganizerSpec, *, subject: str, holds: str
) -> Optional[str]:
    """The problem sentence for an archetype that takes exactly one compartment, or None.

    Both v1 archetypes take one: a deck box holds one deck, a divider labels one group.
    `Compartment.contents` accepts a `CardStack` only and `compartments` is plural in
    name alone (roadmap §0.5), so this is the shared rule until the box-insert
    archetype makes it genuinely plural.

    Args:
        spec: The spec to check.
        subject: How the archetype names itself in a refusal, e.g. `"deck_box v1"`.
        holds: What the one compartment is, e.g. `"the deck"`.
    """
    count = len(spec.compartments)
    if count == 1:
        return None
    return f"{subject} holds exactly one compartment ({holds}); got {count}"


def expect_planes(part: Any, axis: int, expected: int, *, what: str, subject: str) -> list[float]:
    """The distinct axis-aligned planes of `part` on `axis`, or the finding.

    A plane count that does not match the design *is* the measurement's finding, not a
    per-feature error: geometry without the planes the design says it has cannot be
    measured against that design at all.

    Args:
        part: A mesh (or mesh body) with a `vertices` array.
        axis: 0, 1 or 2 for X, Y or Z.
        expected: How many distinct planes the design puts on that axis.
        what: The body being measured, e.g. `"lid"`, for the message.
        subject: The archetype and version, e.g. `"a deck box v1"`.

    Raises:
        MeasureError: Naming the count found, the count designed and every plane.
    """
    planes = plane_set(part.vertices[:, axis])
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
