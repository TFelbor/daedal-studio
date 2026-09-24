"""Seed dimensions the organizer archetypes resolve a spec against.

This is the M0 stand-in for the dimension KB (PRD F4; roadmap M2; sourced research in
`docs/dimension-kb-research.md`). Every number below names its source in the comment
beside it, because the promise this product makes to a community that distrusts AI
output is that the millimetres are checkable against their own callipers. When the KB
lands (`pythonsrc/data/dimension_kb.v1.json`) `resolve_stack` reads it instead and
nothing downstream changes shape.

Deliberately dependency-free: the schema imports this, and the schema must be
importable where trimesh and manifold3d are not (the api-server image installs neither).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CardSize:
    width_mm: float
    height_mm: float
    thickness_mm: float
    source: str


#: Card kinds a spec may name. ``standard`` is the MTG spec, 63,5 × 88,9 (Draftsim).
#: Pokémon, Lorcana, Flesh and Blood and One Piece cards are the same size or up to
#: about 1 mm smaller: 63 × 88, per folio.fyi, Card Fit Lab and CardShellz. Sizing for
#: MTG is deliberate, because a box that fits the largest card fits the rest. The
#: Japanese size (59 × 86, Yu-Gi-Oh) is in the research but has **no sourced sleeve
#: envelope**, and a footprint invented to fill that gap is exactly the fabricated number
#: this module exists to refuse. It arrives with the KB.
CARD_KINDS: dict[str, CardSize] = {
    "standard": CardSize(
        width_mm=63.5,
        height_mm=88.9,
        thickness_mm=0.305,
        source=(
            "MTG spec (Draftsim); Pokémon / Lorcana / FaB / One Piece the same size "
            "or up to ~1 mm smaller"
        ),
    ),
}

#: How the cards are sleeved. Keys of the tables below. ``double_thick`` is
#: double-sleeving with 100 µm "thick" inners (Dragon Shield Perfect Fit Thick, KMC
#: Perfect Hard), which is too thick for ``double``'s pitch.
SLEEVINGS: tuple[str, ...] = ("none", "single", "double", "double_thick")

#: How each sleeving reads inside a noun phrase ("100 double-sleeved standard cards",
#: "double-sleeved envelope"). This is the one Python copy: `server.app` imports it for
#: a spec job's label, and the archetypes use it in their captions, so that a key never
#: reaches a person as ``double_thick-sleeved``. `SLEEVING_NOTE` in
#: `web/src/organizer/spec.ts` captions the same field with the same keys.
SLEEVING_WORDS: dict[str, str] = {
    "none": "unsleeved",
    "single": "single-sleeved",
    "double": "double-sleeved",
    "double_thick": "thick-inner double-sleeved",
}

#: Outside W × H of one sleeved card, mm. ``None`` means the bare card footprint.
#: single — Dragon Shield / Ultra Pro Eclipse / Gamegenic outer sleeves: 66 × 91.
#: double — measured double-sleeved deck width 67 mm (MTG Salvation thread 572115);
#: the outer sleeve's 91–92 mm height governs.
#: double_thick — the same outer sleeve, so the same envelope. Dragon Shield says its
#: Thick inners fit inside its regular sleeves. The outer sleeve sets the outside size,
#: and the thicker inner only makes the stack deeper.
SLEEVED_FOOTPRINT_MM: dict[str, tuple[float, float] | None] = {
    "none": None,
    "single": (66.0, 91.0),
    "double": (67.0, 92.0),
    "double_thick": (67.0, 92.0),
}

#: Design pitch per card in the stack direction, mm. These are *design rules*, not
#: nominal sums. The double-sleeved figure rests on two independent caliper
#: measurements of 100-card Commander stacks (KMC Hyper Matte + Perfect Fit = 66 mm;
#: Dragon Shield + Perfect Fit = 66,7 mm) plus an air margin. The folk 0,72–0,80 mm is
#: unsupported by any measured stack — those were box depths designers *chose*.
#:
#: double_thick has no measured stack, so its pitch is derived. The worst nominal is a
#: 100 µm inner plus the 130 µm Double Sleeved gives for Dragon Shield Matte:
#: 0,305 + 2 × 0,100 + 2 × 0,130 = 0,765 mm. On top of that goes the air margin
#: ``double`` keeps over its measured stack, 3,3 mm per 100 cards. That gives 0,798,
#: rounded up to 0,80.
#: That this equals the top of the folk range is a coincidence. The folk figure was
#: wrong for regular inners, and this one applies only to 100 µm inners
#: (`docs/dimension-kb-research.md` §2).
PITCH_MM_PER_CARD: dict[str, float] = {
    "none": 0.305,
    "single": 0.60,
    "double": 0.70,
    "double_thick": 0.80,
}

#: One sentence per pitch saying where it came from, for the UI's fits line.
PITCH_BASIS: dict[str, str] = {
    "none": "0.305 mm/card (bare card thickness, spec)",
    "single": "0.60 mm/card design pitch (derived + air margin)",
    "double": "0.70 mm/card design pitch (two measured 100-card stacks at 66–67 mm)",
    "double_thick": (
        "0.80 mm/card design pitch (100 µm thick inners; derived + air margin, "
        "no measured stack)"
    ),
}


@dataclass(frozen=True)
class ResolvedStack:
    """A card stack with every number the geometry needs, and its provenance."""

    count: int
    card: str
    sleeving: str
    footprint_w_mm: float
    footprint_h_mm: float
    pitch_mm: float
    stack_height_mm: float
    basis: str


def resolve_stack(count: int, card: str, sleeving: str) -> ResolvedStack:
    """Resolve a card stack to its sleeved footprint and stack height.

    Args:
        count: Number of cards.
        card: A key of `CARD_KINDS`.
        sleeving: A member of `SLEEVINGS`.

    Returns:
        The resolved stack, with a `basis` sentence naming every source used.

    Raises:
        KeyError: For an unknown card kind or sleeving. The schema validates both
            before this is reached; the KeyError is for callers that bypass it.
    """
    size = CARD_KINDS[card]
    footprint = SLEEVED_FOOTPRINT_MM[sleeving]
    fw, fh = footprint if footprint is not None else (size.width_mm, size.height_mm)
    pitch = PITCH_MM_PER_CARD[sleeving]
    sleeve_note = (
        "unsleeved"
        if sleeving == "none"
        else f"{SLEEVING_WORDS[sleeving]} envelope {fw:g} × {fh:g} mm"
    )
    basis = (
        f"{card} card {size.width_mm:g} × {size.height_mm:g} mm, {sleeve_note}; "
        f"{PITCH_BASIS[sleeving]}"
    )
    return ResolvedStack(
        count=count,
        card=card,
        sleeving=sleeving,
        footprint_w_mm=fw,
        footprint_h_mm=fh,
        pitch_mm=pitch,
        stack_height_mm=round(count * pitch, 3),
        basis=basis,
    )
