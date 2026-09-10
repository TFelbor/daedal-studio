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
    TAB_POSITIONS,
    CardStack,
    Compartment,
    Constraints,
    Divider,
    Lid,
    OrganizerSpec,
    Process,
    SpecError,
)


def card_divider(**overrides):
    """A valid card-divider spec — the second archetype's own optional section."""
    base = dict(
        archetype="card_divider",
        compartments=(Compartment(CardStack(count=100)),),
        divider=Divider(),
    )
    base.update(overrides)
    return OrganizerSpec(**base)


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


def test_the_card_divider_is_a_known_archetype():
    assert "card_divider" in ARCHETYPES


def test_the_divider_section_round_trips():
    spec = card_divider(divider=Divider(thickness_mm=1.6, tab_width_mm=25.0,
                                        tab_height_mm=12.0, tab_position="left"))
    assert OrganizerSpec.from_dict(spec.to_dict()) == spec
    assert OrganizerSpec.from_json(spec.to_json()) == spec


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
    (dict(thickness_mm=0), "thickness_mm"),
    (dict(thickness_mm=-1.4), "thickness_mm"),
    (dict(tab_width_mm="wide"), "tab_width_mm"),
    (dict(tab_height_mm=float("inf")), "tab_height_mm"),
    (dict(tab_position="middle"), "tab_position"),
    (dict(tab_position="Centre"), "tab_position"),
])
def test_divider_refuses_bad_fields_by_name(bad, field):
    with pytest.raises(SpecError) as exc:
        Divider(**bad)
    assert field in str(exc.value)


@pytest.mark.parametrize("position", TAB_POSITIONS)
def test_every_tab_position_the_schema_names_is_accepted(position):
    assert Divider(tab_position=position).tab_position == position


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


def test_the_fit_margin_defaults_to_two_millimetres():
    """`docs/dimension-kb-research.md` §7: no public DB of game-box internals exists,
    the measurements that do are per-copy, and boxes vary ±1–2 mm — so the KB's own
    consequence is a −2 mm safety default, and the audited insert standard makes the
    same 2 mm reduction mandatory."""
    assert Constraints().fit_margin_mm == 2.0


def test_the_effective_limit_is_the_stated_one_less_the_margin_on_every_axis():
    c = Constraints(max_external_mm=(90.0, 80.0, 100.0))
    assert c.effective_max_external_mm() == (88.0, 78.0, 98.0)


def test_a_zero_margin_leaves_the_stated_limit_alone():
    c = Constraints(max_external_mm=(90.0, 80.0, 100.0), fit_margin_mm=0)
    assert c.effective_max_external_mm() == (90.0, 80.0, 100.0)


def test_the_effective_limit_is_none_without_a_stated_one():
    """The margin has nothing to subtract from, so there is no limit — not a
    limit of −2 mm that nothing could ever satisfy."""
    assert Constraints(fit_margin_mm=2.0).effective_max_external_mm() is None


def test_a_margin_larger_than_the_limit_goes_negative_rather_than_clamping():
    """A limit nothing can satisfy is the honest answer, and the arithmetic is in the
    remedy; clamping to zero would hide which of the two numbers is wrong."""
    assert Constraints(max_external_mm=(1.0, 1.0, 1.0)).effective_max_external_mm() == (
        -1.0, -1.0, -1.0
    )


@pytest.mark.parametrize("bad", [-0.001, -2.0, "wide", float("nan")])
def test_constraints_refuse_a_bad_fit_margin_by_name(bad):
    with pytest.raises(SpecError) as exc:
        Constraints(fit_margin_mm=bad)
    assert "fit_margin_mm" in str(exc.value)


def test_a_zero_fit_margin_is_accepted_because_somebody_measured_the_box():
    assert Constraints(fit_margin_mm=0).fit_margin_mm == 0.0


def test_the_fit_margin_round_trips():
    a = deck(constraints=Constraints(max_external_mm=(90.0, 80.0, 100.0)))
    b = deck(constraints=Constraints(max_external_mm=(90.0, 80.0, 100.0), fit_margin_mm=0))
    assert OrganizerSpec.from_dict(a.to_dict()) == a
    assert OrganizerSpec.from_dict(b.to_dict()) == b
    assert a.to_dict()["constraints"]["fit_margin_mm"] == 2.0
    assert b.to_dict()["constraints"]["fit_margin_mm"] == 0.0


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


def test_from_dict_refuses_an_unknown_key_under_the_divider_with_its_path():
    d = card_divider().to_dict()
    d["divider"]["tab_with_mm"] = 25.0
    with pytest.raises(SpecError) as exc:
        OrganizerSpec.from_dict(d)
    assert "spec.divider" in str(exc.value) and "tab_with_mm" in str(exc.value)


def test_from_dict_names_the_path_of_a_bad_divider_field():
    d = card_divider().to_dict()
    d["divider"]["thickness_mm"] = -1
    with pytest.raises(SpecError) as exc:
        OrganizerSpec.from_dict(d)
    assert "spec.divider.thickness_mm" in str(exc.value)


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


def test_an_absent_optional_section_is_omitted_from_the_canonical_form():
    """The hash of a deck box must not move because another archetype gained a section.
    `dataclasses.asdict` would have written `"divider":null` into every deck box spec
    ever stored, for a field those specs do not mention — and the next archetype's
    section would move them all again. `from_dict` defaults each to None, so nothing is
    lost: the round-trip test above is the other half of this one."""
    d = deck().to_dict()
    assert "divider" not in d and "lid" in d
    assert "divider" not in canonical_json(deck())
    div = card_divider().to_dict()
    assert "lid" not in div and "divider" in div
    # And a section explicitly set to null on the way in is still absent on the way out.
    assert "lid" not in OrganizerSpec.from_dict({**div, "lid": None}).to_dict()


def test_the_hash_is_stable_across_processes():
    """A fixed vector: if this changes, every stored hash in the world changes with it,
    which is a schema-version bump, not a refactor.

    It has moved exactly once, deliberately: `constraints.fit_margin_mm` (issue #70)
    is a scalar with a default, not an optional *section*, so it is written for every
    spec the way `process.wall_mm` is. A section is omitted when absent — that is what
    `_OPTIONAL_SECTIONS` is for — but omitting a scalar at its default would mean the
    canonical form no longer says what the spec is, and the next default to change
    would be unreadable in a diff. The alternative, a `SCHEMA_VERSION` bump, refuses
    every existing spec file for an additive field. Rows already written keep the hash
    they recorded; nothing re-derives one.
    """
    spec = OrganizerSpec(
        archetype="deck_box",
        compartments=(Compartment(CardStack(count=100)),),
        lid=Lid(),
    )
    assert canonical_json(spec) == (
        '{"archetype":"deck_box","compartments":[{"contents":{"card":"standard",'
        '"count":100,"sleeving":"double"}}],'
        '"constraints":{"fit_margin_mm":2.0,"max_external_mm":null},'
        '"lid":{"clearance_mm":0.2,"height_mm":15.0,"kind":"lift_off","magnets":false,'
        '"top_mm":2.0,"wall_mm":1.2},"process":{"cavity_clearance_mm":1.5,"floor_mm":2.0,'
        '"min_feature_mm":1.0,"stack_slack_mm":1.0,"wall_mm":2.8},"schema_version":1}'
    )


# ── diff ───────────────────────────────────────────────────────────────────────

def test_diff_reports_a_changed_path_with_old_and_new():
    a, b = deck(), deck(lid=Lid(height_mm=20.0))
    assert spec_diff(a, b) == {"lid.height_mm": (15.0, 20.0)}


def test_diff_reports_the_fit_margin_which_is_what_makes_it_iterable():
    """F8 iterates a design by spec diff, so "I measured the box myself, use all of
    it" has to be a path — `constraints.fit_margin_mm` — rather than a hidden default."""
    a = deck(constraints=Constraints(max_external_mm=(90.0, 80.0, 100.0)))
    b = deck(constraints=Constraints(max_external_mm=(90.0, 80.0, 100.0), fit_margin_mm=0))
    assert spec_diff(a, b) == {"constraints.fit_margin_mm": (2.0, 0.0)}


def test_diff_reports_added_and_removed_paths_with_none():
    a = deck()
    b = deck(constraints=Constraints(max_external_mm=(80.0, 80.0, 100.0)))
    d = spec_diff(a, b)
    assert d["constraints.max_external_mm[0]"] == (None, 80.0)
    assert spec_diff(b, a)["constraints.max_external_mm[0]"] == (80.0, None)


def test_diff_of_identical_specs_is_empty():
    assert spec_diff(deck(), deck()) == {}


def test_diff_reports_a_divider_path_which_is_what_makes_f8_mechanical():
    """"Make the tab wider" has to be a path, which is why the divider's parameters are
    a spec section rather than constants inside the archetype."""
    a = card_divider()
    b = card_divider(divider=Divider(tab_width_mm=30.0))
    assert spec_diff(a, b) == {"divider.tab_width_mm": (20.0, 30.0)}


def test_the_fixed_divider_vector_carries_no_lid():
    spec = card_divider()
    assert canonical_json(spec) == (
        '{"archetype":"card_divider","compartments":[{"contents":{"card":"standard",'
        '"count":100,"sleeving":"double"}}],'
        '"constraints":{"fit_margin_mm":2.0,"max_external_mm":null},'
        '"divider":{"tab_height_mm":10.0,"tab_position":"centre","tab_width_mm":20.0,'
        '"thickness_mm":1.4},"process":{"cavity_clearance_mm":1.5,"floor_mm":2.0,'
        '"min_feature_mm":1.0,"stack_slack_mm":1.0,"wall_mm":2.8},"schema_version":1}'
    )


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
