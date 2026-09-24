"""The seed numbers a spec resolves against, and where each one came from.

`pythonsrc/organizer/dimensions.py` is the M0 stand-in for the dimension KB (PRD F4,
seeded from `docs/dimension-kb-research.md`). These tests pin the design rules that
research settled — the 0,70 mm/card double-sleeved pitch above all, because the folk
0,72–0,80 figure is what every wrong deck box on the internet was designed to — and the
shape of `resolve_stack`, which the archetypes and the UI's fits line both read.
"""
import pytest

from pythonsrc.organizer.dimensions import (
    CARD_KINDS,
    PITCH_BASIS,
    PITCH_MM_PER_CARD,
    SLEEVED_FOOTPRINT_MM,
    SLEEVING_WORDS,
    SLEEVINGS,
    resolve_stack,
)


def test_the_double_sleeved_design_pitch_is_the_measured_one_not_the_folk_one():
    assert PITCH_MM_PER_CARD["double"] == pytest.approx(0.70)
    assert PITCH_MM_PER_CARD["single"] == pytest.approx(0.60)
    assert PITCH_MM_PER_CARD["none"] == pytest.approx(0.305)


def test_every_sleeving_has_a_pitch_and_a_footprint_entry():
    assert set(SLEEVINGS) == set(PITCH_MM_PER_CARD) == set(SLEEVED_FOOTPRINT_MM)
    assert set(SLEEVINGS) == set(PITCH_BASIS) == set(SLEEVING_WORDS)


# ── thick inners (docs/dimension-kb-research.md §2) ─────────────────────────────
#
# Per-layer maker figures, µm: Dragon Shield Perfect Fit Thick and KMC Perfect Hard are
# 100; the outers are Dragon Shield Matte 120 (maker) or 130 (Double Sleeved), KMC Hyper
# Mat 120, and Ultra Pro Eclipse 90 front / 120 back. Nominal = card + both films of each
# sleeve.
CARD_MM = 0.305
THICK_INNER_MM = 0.100
WORST_OUTER_MM = 0.130
#: The air margin `double` keeps over its measured 66,7 mm stack, per 100 cards.
AIR_MARGIN_PER_100_MM = 100 * 0.70 - 66.7


def test_regular_double_sleeving_does_not_cover_thick_inners():
    """Why `double_thick` exists: even at the makers' own 120 µm outer, 100 Thick-inner
    cards come to 74,5 mm nominal, 4,5 mm past the 70 mm `double` allows."""
    nominal = CARD_MM + 2 * THICK_INNER_MM + 2 * 0.120
    assert nominal == pytest.approx(0.745)
    assert nominal > PITCH_MM_PER_CARD["double"]


def test_the_thick_inner_pitch_keeps_doubles_air_margin_over_the_worst_nominal():
    """No thick-inner stack has been measured, so the pitch has to cover the thickest
    derivation (130 µm outer, 0,765 mm) with at least the air margin `double` has over
    its measured stack. Tightening it removes that margin, and the symptom only shows up
    after a deck is sleeved."""
    worst = CARD_MM + 2 * THICK_INNER_MM + 2 * WORST_OUTER_MM
    assert worst == pytest.approx(0.765)
    assert 100 * (PITCH_MM_PER_CARD["double_thick"] - worst) >= AIR_MARGIN_PER_100_MM
    assert PITCH_MM_PER_CARD["double_thick"] == pytest.approx(0.80)


def test_thick_inners_change_the_depth_and_not_the_envelope():
    assert SLEEVED_FOOTPRINT_MM["double_thick"] == SLEEVED_FOOTPRINT_MM["double"]
    stack = resolve_stack(100, "standard", "double_thick")
    assert stack.stack_height_mm == pytest.approx(80.0)
    assert (stack.footprint_w_mm, stack.footprint_h_mm) == (67.0, 92.0)


def test_no_sleeving_key_reaches_a_person_as_an_identifier():
    """The basis is the UI's fits line. A key spliced in as ``f"{key}-sleeved"`` reads
    ``double_thick-sleeved`` there, so every basis goes through `SLEEVING_WORDS`."""
    for sleeving in SLEEVINGS:
        basis = resolve_stack(100, "standard", sleeving).basis
        assert "_" not in basis, basis
    assert "thick-inner double-sleeved envelope" in resolve_stack(
        100, "standard", "double_thick"
    ).basis


def test_only_the_standard_card_is_offered_in_v1():
    """The Japanese size is researched but has no sourced sleeve envelope; inventing
    one would be the fabricated number this module exists to refuse."""
    assert set(CARD_KINDS) == {"standard"}
    assert (CARD_KINDS["standard"].width_mm, CARD_KINDS["standard"].height_mm) == (63.5, 88.9)


def test_a_hundred_double_sleeved_cards_resolve_to_a_seventy_mm_stack():
    stack = resolve_stack(100, "standard", "double")
    assert stack.stack_height_mm == pytest.approx(70.0)
    assert (stack.footprint_w_mm, stack.footprint_h_mm) == (67.0, 92.0)
    assert stack.pitch_mm == 0.70


def test_an_unsleeved_stack_uses_the_bare_card_footprint():
    stack = resolve_stack(60, "standard", "none")
    assert (stack.footprint_w_mm, stack.footprint_h_mm) == (63.5, 88.9)
    assert stack.stack_height_mm == pytest.approx(18.3)


def test_the_basis_names_the_card_the_sleeving_and_the_pitch_rule():
    basis = resolve_stack(100, "standard", "double").basis
    assert "63.5" in basis and "88.9" in basis
    assert "double" in basis and "67" in basis and "92" in basis
    assert "0.70" in basis


def test_every_source_is_named():
    for size in CARD_KINDS.values():
        assert size.source
