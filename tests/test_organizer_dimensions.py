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
    PITCH_MM_PER_CARD,
    SLEEVED_FOOTPRINT_MM,
    SLEEVINGS,
    resolve_stack,
)


def test_the_double_sleeved_design_pitch_is_the_measured_one_not_the_folk_one():
    assert PITCH_MM_PER_CARD["double"] == pytest.approx(0.70)
    assert PITCH_MM_PER_CARD["single"] == pytest.approx(0.60)
    assert PITCH_MM_PER_CARD["none"] == pytest.approx(0.305)


def test_every_sleeving_has_a_pitch_and_a_footprint_entry():
    assert set(SLEEVINGS) == set(PITCH_MM_PER_CARD) == set(SLEEVED_FOOTPRINT_MM)


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
