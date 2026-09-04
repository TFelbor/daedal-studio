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


#: Card kinds a spec may name. ``standard`` is the footprint the four target games share
#: (MTG 63,5 × 88,9 spec; Pokémon, Lorcana, Flesh and Blood and One Piece within
#: ±0,5 mm — Draftsim, folio.fyi, Card Fit Lab, CardShellz). The Japanese size
#: (59 × 86, Yu-Gi-Oh) is in the research but has **no sourced sleeve envelope**, and a
#: footprint invented to fill that gap is exactly the fabricated number this module
#: exists to refuse. It arrives with the KB.
CARD_KINDS: dict[str, CardSize] = {
    "standard": CardSize(
        width_mm=63.5,
        height_mm=88.9,
        thickness_mm=0.305,
        source="MTG spec (Draftsim); Pokémon / Lorcana / FaB / One Piece within ±0,5 mm",
    ),
}

#: How the cards are sleeved. Keys of the two tables below.
SLEEVINGS: tuple[str, ...] = ("none", "single", "double")

#: Outside W × H of one sleeved card, mm. ``None`` means the bare card footprint.
#: single — Dragon Shield / Ultra Pro Eclipse / Gamegenic outer sleeves: 66 × 91.
#: double — measured double-sleeved deck width 67 mm (MTG Salvation thread 572115);
#: the outer sleeve's 91–92 mm height governs.
SLEEVED_FOOTPRINT_MM: dict[str, tuple[float, float] | None] = {
    "none": None,
    "single": (66.0, 91.0),
    "double": (67.0, 92.0),
}

#: Design pitch per card in the stack direction, mm. These are *design rules*, not
#: nominal sums. The double-sleeved figure rests on two independent caliper
#: measurements of 100-card Commander stacks (KMC Hyper Matte + Perfect Fit = 66 mm;
#: Dragon Shield + Perfect Fit = 66,7 mm) plus an air margin. The folk 0,72–0,80 mm is
#: unsupported by any measured stack — those were box depths designers *chose*.
PITCH_MM_PER_CARD: dict[str, float] = {
    "none": 0.305,
    "single": 0.60,
    "double": 0.70,
}

#: One sentence per pitch saying where it came from, for the UI's fits line.
PITCH_BASIS: dict[str, str] = {
    "none": "0.305 mm/card (bare card thickness, spec)",
    "single": "0.60 mm/card design pitch (derived + air margin)",
    "double": "0.70 mm/card design pitch (two measured 100-card stacks at 66–67 mm)",
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
        else f"{sleeving}-sleeved envelope {fw:g} × {fh:g} mm"
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
