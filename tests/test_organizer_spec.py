"""The organizer spec: the object everything in the pivot is a function of.

The governing rule is *the LLM interprets words; it never produces geometry*, and this
schema is the boundary that rule describes. Left of it is probabilistic, right of it
deterministic. So the tests here are about the properties a boundary object needs:
it round-trips exactly, it refuses anything malformed with every problem named at once,
two specs can be compared line by line, and one spec has one hash.
"""
import json

import pytest

from pythonsrc.organizer.spec import (
    ARCHETYPES,
    CardStack,
    Compartment,
    Constraints,
    Lid,
    OrganizerSpec,
    Process,
    SpecError,
)


def deck(count=100, sleeving="double", **overrides):
    """A valid deck-box spec with sensible defaults, overridable per test."""
    base = dict(
        archetype="deck_box",
        compartments=(Compartment(CardStack(count=count, sleeving=sleeving)),),
        lid=Lid(),
    )
    base.update(overrides)
    return OrganizerSpec(**base)


# ── round trip ─────────────────────────────────────────────────────────────────

def test_dict_round_trip_is_exact():
    spec = deck()
    assert OrganizerSpec.from_dict(spec.to_dict()) == spec


def test_json_round_trip_is_exact():
    spec = deck(constraints=Constraints(max_external_mm=(80.0, 80.0, 100.0)))
    assert OrganizerSpec.from_json(spec.to_json()) == spec


def test_to_dict_is_pure_json_types():
    """Tuples become lists so the dict equals what `json.loads(to_json())` returns —
    one shape for the file and the in-memory view."""
    spec = deck(constraints=Constraints(max_external_mm=(80.0, 80.0, 100.0)))
    d = spec.to_dict()
    assert d == json.loads(spec.to_json())
    assert isinstance(d["compartments"], list)
    assert isinstance(d["constraints"]["max_external_mm"], list)


def test_millimetres_round_to_one_micron_on_construction():
    """Float noise must not reach the canonical form, so the schema rounds once, on
    the way in — three orders of magnitude below N1's ±0,05 mm."""
    p = Process(wall_mm=2.80000004, floor_mm=2.0004)
    assert p.wall_mm == 2.8
    assert p.floor_mm == 2.0


def test_the_deck_box_is_a_known_archetype():
    assert "deck_box" in ARCHETYPES


# ── validation: every rule, with the field named ───────────────────────────────

@pytest.mark.parametrize("bad, field", [
    (dict(count=0), "count"),
    (dict(count=-3), "count"),
    (dict(count=2.5), "count"),
    (dict(count=True), "count"),
    (dict(count=10, card="japanese"), "card"),
    (dict(count=10, sleeving="triple"), "sleeving"),
])
def test_card_stack_refuses_bad_fields_by_name(bad, field):
    with pytest.raises(SpecError) as exc:
        CardStack(**bad)
    assert field in str(exc.value)


@pytest.mark.parametrize("bad, field", [
    (dict(kind="hinged"), "kind"),
    (dict(height_mm=0), "height_mm"),
    (dict(wall_mm=-1), "wall_mm"),
    (dict(clearance_mm=-0.1), "clearance_mm"),
    (dict(top_mm=float("nan")), "top_mm"),
])
def test_lid_refuses_bad_fields_by_name(bad, field):
    with pytest.raises(SpecError) as exc:
        Lid(**bad)
    assert field in str(exc.value)


def test_lid_clearance_may_be_zero():
    """Zero clearance is a real (very tight) design; only negatives are nonsense."""
    assert Lid(clearance_mm=0).clearance_mm == 0.0


@pytest.mark.parametrize("bad, field", [
    (dict(wall_mm=0), "wall_mm"),
    (dict(floor_mm="thick"), "floor_mm"),
    (dict(cavity_clearance_mm=-1), "cavity_clearance_mm"),
    (dict(stack_slack_mm=-1), "stack_slack_mm"),
    (dict(min_feature_mm=0), "min_feature_mm"),
])
def test_process_refuses_bad_fields_by_name(bad, field):
    with pytest.raises(SpecError) as exc:
        Process(**bad)
    assert field in str(exc.value)


def test_constraints_need_three_positive_numbers_or_nothing():
    assert Constraints().max_external_mm is None
    assert Constraints(max_external_mm=[80, 80, 100]).max_external_mm == (80.0, 80.0, 100.0)
    with pytest.raises(SpecError):
        Constraints(max_external_mm=(80, 80))
    with pytest.raises(SpecError):
        Constraints(max_external_mm=(80, -1, 100))


def test_spec_refuses_an_unknown_archetype_and_an_empty_compartment_list():
    with pytest.raises(SpecError) as exc:
        OrganizerSpec(archetype="dragon", compartments=())
    message = str(exc.value)
    assert "archetype" in message and "compartments" in message


def test_spec_refuses_a_foreign_schema_version():
    with pytest.raises(SpecError) as exc:
        deck(schema_version=2)
    assert "schema_version" in str(exc.value)


def test_several_problems_are_reported_together():
    """A bad spec is refused once with the whole list, not one field per attempt."""
    with pytest.raises(SpecError) as exc:
        Process(wall_mm=0, floor_mm=-1, min_feature_mm=0)
    assert len(exc.value.problems) == 3


# ── from_dict: strict, path-annotated ──────────────────────────────────────────

def test_from_dict_refuses_unknown_keys():
    """A typo in a field name must not silently become the default."""
    d = deck().to_dict()
    d["process"]["wal_mm"] = 3.0
    with pytest.raises(SpecError) as exc:
        OrganizerSpec.from_dict(d)
    assert "wal_mm" in str(exc.value)


def test_from_dict_names_the_path_of_a_nested_problem():
    d = deck().to_dict()
    d["compartments"][0]["contents"]["count"] = 0
    with pytest.raises(SpecError) as exc:
        OrganizerSpec.from_dict(d)
    assert "compartments[0].contents.count" in str(exc.value)


def test_from_dict_collects_problems_across_branches():
    d = deck().to_dict()
    d["compartments"][0]["contents"]["count"] = 0
    d["lid"]["wall_mm"] = -1
    d["process"]["floor_mm"] = 0
    with pytest.raises(SpecError) as exc:
        OrganizerSpec.from_dict(d)
    assert len(exc.value.problems) == 3


def test_from_dict_reports_a_missing_required_field():
    d = deck().to_dict()
    del d["compartments"][0]["contents"]["count"]
    with pytest.raises(SpecError) as exc:
        OrganizerSpec.from_dict(d)
    assert "count" in str(exc.value)


def test_from_dict_accepts_a_missing_optional_lid_as_none():
    d = deck().to_dict()
    del d["lid"]
    assert OrganizerSpec.from_dict(d).lid is None


def test_from_json_refuses_text_that_is_not_json():
    with pytest.raises(SpecError) as exc:
        OrganizerSpec.from_json("{not json")
    assert "JSON" in str(exc.value)
