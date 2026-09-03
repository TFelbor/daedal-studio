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


from pythonsrc.organizer.spec import canonical_json, dump_spec, load_spec, spec_diff, spec_hash  # noqa: E402


# ── canonical form and hash ────────────────────────────────────────────────────

def test_canonical_json_ignores_key_order():
    d = deck().to_dict()
    shuffled = {k: d[k] for k in reversed(list(d))}
    assert canonical_json(OrganizerSpec.from_dict(shuffled)) == canonical_json(OrganizerSpec.from_dict(d))


def test_canonical_json_is_compact_and_sorted():
    text = canonical_json(deck())
    assert " " not in text
    keys = list(json.loads(text))
    assert keys == sorted(keys)


def test_the_hash_is_sha256_of_the_canonical_form():
    import hashlib
    spec = deck()
    assert spec_hash(spec) == hashlib.sha256(canonical_json(spec).encode("utf-8")).hexdigest()
    assert len(spec_hash(spec)) == 64


def test_any_field_change_changes_the_hash():
    base = spec_hash(deck())
    assert spec_hash(deck(count=99)) != base
    assert spec_hash(deck(lid=Lid(clearance_mm=0.25))) != base
    assert spec_hash(deck(process=Process(wall_mm=2.4))) != base


def test_the_hash_is_stable_across_processes():
    """A fixed vector: if this changes, every stored hash in the world changes with it,
    which is a schema-version bump, not a refactor."""
    spec = OrganizerSpec(
        archetype="deck_box",
        compartments=(Compartment(CardStack(count=100)),),
        lid=Lid(),
    )
    assert canonical_json(spec) == (
        '{"archetype":"deck_box","compartments":[{"contents":{"card":"standard",'
        '"count":100,"sleeving":"double"}}],"constraints":{"max_external_mm":null},'
        '"lid":{"clearance_mm":0.2,"height_mm":15.0,"kind":"lift_off","magnets":false,'
        '"top_mm":2.0,"wall_mm":1.2},"process":{"cavity_clearance_mm":1.5,"floor_mm":2.0,'
        '"min_feature_mm":1.0,"stack_slack_mm":1.0,"wall_mm":2.8},"schema_version":1}'
    )


# ── diff ───────────────────────────────────────────────────────────────────────

def test_diff_reports_a_changed_path_with_old_and_new():
    a, b = deck(), deck(lid=Lid(height_mm=20.0))
    assert spec_diff(a, b) == {"lid.height_mm": (15.0, 20.0)}


def test_diff_reports_added_and_removed_paths_with_none():
    a = deck()
    b = deck(constraints=Constraints(max_external_mm=(80.0, 80.0, 100.0)))
    d = spec_diff(a, b)
    assert d["constraints.max_external_mm[0]"] == (None, 80.0)
    assert spec_diff(b, a)["constraints.max_external_mm[0]"] == (80.0, None)


def test_diff_of_identical_specs_is_empty():
    assert spec_diff(deck(), deck()) == {}


def test_diff_indexes_into_lists():
    a, b = deck(count=100), deck(count=60)
    assert spec_diff(a, b) == {"compartments[0].contents.count": (100, 60)}


# ── files ──────────────────────────────────────────────────────────────────────

def test_dump_then_load_round_trips(tmp_path):
    spec = deck()
    path = dump_spec(spec, tmp_path / "deck.json")
    assert load_spec(path) == spec
    assert path.read_text().endswith("\n")


def test_load_refuses_a_bad_file_with_the_problems(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text('{"archetype": "deck_box", "compartments": []}')
    with pytest.raises(SpecError) as exc:
        load_spec(path)
    assert "compartments" in str(exc.value)


def test_the_package_exports_the_schema_without_the_kernel():
    """`pythonsrc.organizer` must stay importable where trimesh is not installed, so its
    `__init__` may import the schema and nothing else."""
    import ast, importlib.util
    import pythonsrc.organizer as pkg
    assert pkg.OrganizerSpec is OrganizerSpec and pkg.spec_hash is spec_hash
    tree = ast.parse(open(importlib.util.find_spec("pythonsrc.organizer").origin).read())
    imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    imported |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert imported == {"spec"}
