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
    ARCHETYPE_WALL_MM,
    ARCHETYPES,
    DEFAULT_NOZZLE_DIAMETER_MM,
    FIT_INTENT_CLEARANCE_MM,
    FIT_INTENTS,
    TAB_POSITIONS,
    WALL_FLOOR_NOZZLE_MULTIPLE,
    CardStack,
    Compartment,
    Constraints,
    Divider,
    Lid,
    OrganizerSpec,
    Pocket,
    Process,
    SpecError,
    Tray,
    check_wall_floor,
    problem_path,
    problems_with_paths,
    wall_floor_mm,
    wall_floor_problems,
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


def token_tray(rows=2, columns=3, **overrides):
    """A valid token-tray spec — the third archetype, and the plural one."""
    pocket = Pocket(width_mm=20.0, depth_mm=20.0, height_mm=15.0)
    base = dict(
        archetype="token_tray",
        compartments=tuple(Compartment(pocket) for _ in range(rows * columns)),
        tray=Tray(columns=columns),
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


def test_the_token_tray_is_a_known_archetype():
    assert "token_tray" in ARCHETYPES


# ── the contents union: a compartment holds cards *or* a pocket (issue #84) ────

def test_a_pocket_compartment_round_trips():
    spec = token_tray()
    assert OrganizerSpec.from_dict(spec.to_dict()) == spec
    assert OrganizerSpec.from_json(spec.to_json()) == spec


def test_the_tray_section_round_trips_and_carries_the_columns():
    spec = token_tray(rows=4, columns=2)
    assert OrganizerSpec.from_dict(spec.to_dict()).tray == Tray(columns=2)
    assert len(spec.compartments) == 8


def test_a_pockets_millimetres_round_to_one_micron_like_every_other():
    pocket = Pocket(width_mm=20.0000004, depth_mm=12.3456, height_mm=15.0)
    assert pocket.width_mm == 20.0 and pocket.depth_mm == 12.346


def test_a_pocket_carries_its_own_provenance_or_none():
    assert Pocket(20.0, 20.0, 15.0).source is None
    assert Pocket(20.0, 20.0, 15.0, source="16 mm d6, +2 mm").source == "16 mm d6, +2 mm"
    with pytest.raises(SpecError) as exc:
        Pocket(20.0, 20.0, 15.0, source=16)
    assert "source" in str(exc.value)


@pytest.mark.parametrize("contents, kind", [
    ({"count": 100, "card": "standard", "sleeving": "double"}, CardStack),
    ({"width_mm": 20.0, "depth_mm": 20.0, "height_mm": 15.0}, Pocket),
])
def test_the_contents_union_is_chosen_by_the_keys_it_carries(contents, kind):
    """No `kind` discriminator, on purpose: a new field on `CardStack` would move the
    canonical form and therefore the stored hash of every spec ever written."""
    spec = OrganizerSpec.from_dict({
        "archetype": "token_tray" if kind is Pocket else "deck_box",
        "compartments": [{"contents": contents}],
        **({"tray": {"columns": 1}} if kind is Pocket else {"lid": {}}),
        "schema_version": 1,
    })
    assert isinstance(spec.compartments[0].contents, kind)


@pytest.mark.parametrize("contents, carries", [
    ({"count": 100, "width_mm": 20.0, "depth_mm": 20.0, "height_mm": 15.0}, "both"),
    ({"card": "standard"}, "neither"),
    ({}, "neither"),
])
def test_contents_that_are_both_shapes_or_neither_are_refused_naming_both(contents, carries):
    with pytest.raises(SpecError) as exc:
        OrganizerSpec.from_dict({
            "archetype": "token_tray", "compartments": [{"contents": contents}],
            "tray": {"columns": 1}, "schema_version": 1,
        })
    named = {p["path"]: p["message"] for p in problems_with_paths(exc.value.problems)}
    message = named["spec.compartments[0].contents"]
    assert carries in message
    assert "cardstack" in message and "pocket" in message
    assert "count" in message and "width_mm" in message


def test_an_unknown_pocket_key_is_refused_like_every_other_leaf():
    with pytest.raises(SpecError) as exc:
        OrganizerSpec.from_dict({
            "archetype": "token_tray",
            "compartments": [{"contents": {"width_mm": 20.0, "depth_mm": 20.0,
                                           "height_mm": 15.0, "diameter_mm": 16.0}}],
            "tray": {"columns": 1}, "schema_version": 1,
        })
    assert "unknown field(s): diameter_mm" in str(exc.value)


def test_a_missing_pocket_dimension_is_refused_as_missing_not_defaulted():
    """There is no default to fall back to and there must not be one: `dimensions.py`
    carries no token or dice sizes, so an invented figure would be the fabricated
    number the schema exists to refuse."""
    with pytest.raises(SpecError) as exc:
        OrganizerSpec.from_dict({
            "archetype": "token_tray",
            "compartments": [{"contents": {"width_mm": 20.0, "depth_mm": 20.0}}],
            "tray": {"columns": 1}, "schema_version": 1,
        })
    assert "missing a required field" in str(exc.value)
    assert "height_mm" in str(exc.value)


@pytest.mark.parametrize("columns", [0, -1, 1.5, "3", True])
def test_a_bad_column_count_is_refused_by_name(columns):
    with pytest.raises(SpecError) as exc:
        OrganizerSpec.from_dict({
            "archetype": "token_tray",
            "compartments": [{"contents": {"width_mm": 20.0, "depth_mm": 20.0,
                                           "height_mm": 15.0}}],
            "tray": {"columns": columns}, "schema_version": 1,
        })
    assert "spec.tray.columns" in {p["path"] for p in problems_with_paths(exc.value.problems)}


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
    (dict(base_chamfer_mm=-0.1), "base_chamfer_mm"),
    (dict(corner_radius_mm=-1), "corner_radius_mm"),
    (dict(cavity_corner_radius_mm="round"), "cavity_corner_radius_mm"),
])
def test_process_refuses_bad_fields_by_name(bad, field):
    with pytest.raises(SpecError) as exc:
        Process(**bad)
    assert field in str(exc.value)


# ── the edge treatments (issue #80) ────────────────────────────────────────────

def test_the_edge_treatments_default_to_the_features_the_audit_calls_mandatory():
    p = Process()
    assert (p.base_chamfer_mm, p.corner_radius_mm, p.cavity_corner_radius_mm) == (0.6, 1.0, 0.0)


@pytest.mark.parametrize(
    "field", ["base_chamfer_mm", "corner_radius_mm", "cavity_corner_radius_mm"])
def test_zero_is_a_value_and_means_the_feature_is_absent(field):
    """Not "unset": a zero chamfer and a zero radius are the geometry this project built
    before issue #80, and they have to stay askable for."""
    assert getattr(Process(**{field: 0}), field) == 0.0


@pytest.mark.parametrize(
    "field", ["base_chamfer_mm", "corner_radius_mm", "cavity_corner_radius_mm"])
def test_from_dict_names_the_path_of_a_bad_edge_treatment(field):
    d = deck().to_dict()
    d["process"][field] = -1
    with pytest.raises(SpecError) as exc:
        OrganizerSpec.from_dict(d)
    assert f"spec.process.{field}" in str(exc.value)


def test_the_edge_treatments_round_trip_and_are_in_the_canonical_form():
    spec = deck(process=Process(base_chamfer_mm=0.8, corner_radius_mm=1.6,
                                cavity_corner_radius_mm=0.75))
    assert OrganizerSpec.from_dict(spec.to_dict()) == spec
    assert '"base_chamfer_mm":0.8' in canonical_json(spec)
    assert spec_hash(spec) != spec_hash(deck())


def test_a_spec_written_without_them_reads_back_with_the_defaults():
    """What moved the archetype version: an older spec file has no edge fields, so it
    compiles to a chamfered box where it once compiled to a square-cornered one. The
    schema does not refuse it — the fields are additive — and
    `deck_box.ARCHETYPE_VERSION` is what records which geometry a job got."""
    d = deck().to_dict()
    for field in ("base_chamfer_mm", "corner_radius_mm", "cavity_corner_radius_mm"):
        del d["process"][field]
    assert OrganizerSpec.from_dict(d).process.base_chamfer_mm == 0.6


def test_diff_reports_an_edge_treatment_which_is_what_makes_it_iterable():
    """F8 iterates by spec diff, so "square off the corners" has to be a path."""
    a, b = deck(), deck(process=Process(corner_radius_mm=0.0))
    assert spec_diff(a, b) == {"process.corner_radius_mm": (1.0, 0.0)}


# ── fit intent (issue #71) ─────────────────────────────────────────────────────

def test_the_fit_intent_defaults_to_snug_and_to_todays_clearance():
    """`snug` is what every deck box this project has compiled was built with, so the
    default must be it and its millimetres must not move."""
    p = Process()
    assert p.fit_intent == "snug"
    assert p.cavity_clearance_mm == 1.5


def test_an_easy_fit_takes_the_sourced_tray_clearance():
    """`docs/dimension-kb-research.md` §3: +1,5–2 mm snug, +4–6 mm easy-in/out. The
    low end of each band, so the number is the least the convention can ask for."""
    assert Process(fit_intent="easy").cavity_clearance_mm == 4.0


@pytest.mark.parametrize("intent", FIT_INTENTS)
def test_every_intent_the_schema_names_resolves_to_a_clearance(intent):
    assert Process(fit_intent=intent).cavity_clearance_mm == FIT_INTENT_CLEARANCE_MM[intent]


@pytest.mark.parametrize("bad", ["loose", "SNUG", "", None, 1])
def test_an_unknown_fit_intent_is_a_spec_error_naming_the_field(bad):
    with pytest.raises(SpecError) as exc:
        Process(fit_intent=bad)
    assert "fit_intent" in str(exc.value)


def test_from_dict_names_the_path_of_an_unknown_fit_intent():
    d = deck().to_dict()
    d["process"]["fit_intent"] = "loose"
    with pytest.raises(SpecError) as exc:
        OrganizerSpec.from_dict(d)
    assert "spec.process.fit_intent" in str(exc.value)


def test_an_explicit_clearance_beats_the_intent():
    """The intent chooses the millimetres only when nobody typed any; a number in the
    spec is a decision somebody made and outranks a word."""
    assert Process(fit_intent="easy", cavity_clearance_mm=1.5).cavity_clearance_mm == 1.5
    assert Process(fit_intent="snug", cavity_clearance_mm=6.0).cavity_clearance_mm == 6.0


def test_a_null_clearance_means_derive_it():
    """The wire form of "I did not choose one" — `from_dict` passes the null through."""
    d = deck(process=Process(fit_intent="easy")).to_dict()
    d["process"]["cavity_clearance_mm"] = None
    assert OrganizerSpec.from_dict(d).process.cavity_clearance_mm == 4.0


def test_the_clearance_is_resolved_on_construction_so_the_round_trip_compiles_the_same():
    """The canonical form must carry the millimetres the geometry is built from. If
    the intent were read at compile time instead, a spec and its own round trip could
    disagree about the cavity while sharing a hash."""
    spec = deck(process=Process(fit_intent="easy"))
    assert spec.to_dict()["process"]["cavity_clearance_mm"] == 4.0
    assert OrganizerSpec.from_dict(spec.to_dict()) == spec
    assert OrganizerSpec.from_json(spec.to_json()) == spec


def test_the_intent_is_in_the_canonical_form_and_moves_the_hash():
    assert '"fit_intent":"snug"' in canonical_json(deck())
    assert spec_hash(deck(process=Process(fit_intent="easy"))) != spec_hash(deck())


def test_diff_reports_the_fit_intent_and_the_clearance_it_chose():
    """F8 iterates by spec diff, so "I want to be able to get the cards out" has to be
    a path — and the millimetres it moved must be visible beside it."""
    a, b = deck(), deck(process=Process(fit_intent="easy"))
    assert spec_diff(a, b) == {
        "process.fit_intent": ("snug", "easy"),
        "process.cavity_clearance_mm": (1.5, 4.0),
    }


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


# ── the wall, and the floor the nozzle puts under it (issue #72) ───────────────

def test_a_process_on_its_own_states_no_wall_until_a_spec_names_the_archetype():
    """`Process` has no archetype, so it cannot know which default applies; the spec
    resolves it. This is the one place the field is legitimately None."""
    assert Process().wall_mm is None
    assert Process(wall_mm=3.0).wall_mm == 3.0


@pytest.mark.parametrize("archetype", sorted(ARCHETYPE_WALL_MM))
def test_every_archetypes_wall_default_is_resolved_on_construction(archetype):
    """Resolved once, on the way in — `cavity_clearance_mm`'s rule verbatim — so the
    canonical form always states the wall and two equal canonical forms compile the
    same. A spec is never handed downstream with a None wall."""
    section = Divider() if archetype == "card_divider" else None
    spec = OrganizerSpec(
        archetype=archetype,
        compartments=(Compartment(CardStack(count=100)),),
        lid=None if section else Lid(),
        divider=section,
    )
    assert spec.process.wall_mm == ARCHETYPE_WALL_MM[archetype]
    assert spec.to_dict()["process"]["wall_mm"] == ARCHETYPE_WALL_MM[archetype]
    assert OrganizerSpec.from_dict(spec.to_dict()) == spec


def test_a_stated_wall_is_kept_whatever_the_archetype_would_have_chosen():
    assert deck(process=Process(wall_mm=2.8)).process.wall_mm == 2.8
    assert card_divider(process=Process(wall_mm=2.8)).process.wall_mm == 2.8


def test_a_null_wall_in_a_file_means_the_archetypes_default():
    """An omitted key and an explicit null must mean the same thing, or two spec files
    that say the same thing would hash differently."""
    d = deck().to_dict()
    d["process"]["wall_mm"] = None
    assert OrganizerSpec.from_dict(d).process.wall_mm == ARCHETYPE_WALL_MM["deck_box"]


def test_the_wall_floor_is_three_extrusion_widths_of_whatever_nozzle_is_fitted():
    """1,2 mm at 0,4 mm is the bottom of the audited insert band; the point of deriving
    it is that the same *rule* gives 1,8 mm on a 0,6 mm nozzle rather than a constant
    that only happens to be right on one machine."""
    assert WALL_FLOOR_NOZZLE_MULTIPLE == 3.0
    assert wall_floor_mm() == pytest.approx(1.2)
    assert wall_floor_mm(DEFAULT_NOZZLE_DIAMETER_MM) == pytest.approx(1.2)
    assert wall_floor_mm(0.6) == pytest.approx(1.8)
    assert wall_floor_mm(0.25) == pytest.approx(0.75)


def test_every_archetypes_default_wall_clears_the_floor_at_the_default_nozzle():
    """A default that the floor refuses would be a default that cannot compile."""
    for archetype, wall in ARCHETYPE_WALL_MM.items():
        assert wall >= wall_floor_mm(), archetype


def test_the_floor_names_both_numbers_and_check_raises_what_problems_reports():
    """"1,2 mm minimum" is unactionable on a machine that is not the reader's; the
    message has to say the floor *and* the nozzle it came from."""
    spec = deck(process=Process(wall_mm=1.0))
    assert wall_floor_problems(spec) == wall_floor_problems(spec, 0.4)
    problem = wall_floor_problems(spec, 0.4)[0]
    assert "process.wall_mm 1" in problem
    assert "1.2 mm wall floor" in problem and "0.4 mm nozzle" in problem
    with pytest.raises(SpecError) as exc:
        check_wall_floor(spec, 0.4)
    assert exc.value.problems == [problem]


def test_a_wall_exactly_on_the_floor_is_accepted():
    """The floor is a minimum, not a threshold to clear — and it must not be lost to
    float noise, which is why the comparison carries a micron of slack."""
    assert wall_floor_problems(deck(process=Process(wall_mm=1.2)), 0.4) == []
    assert wall_floor_problems(deck(process=Process(wall_mm=1.8)), 0.6) == []
    assert wall_floor_problems(deck(process=Process(wall_mm=1.799)), 0.6) != []


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


from pythonsrc.organizer.spec import (  # noqa: E402
    canonical_json,
    dump_spec,
    load_spec,
    spec_diff,
    spec_hash,
)

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
    # 2,8 mm rather than the 2,4 mm this once used: 2,4 is the deck box's own default
    # since issue #72, so it is no longer a change at all.
    assert spec_hash(deck(process=Process(wall_mm=2.8))) != base


def test_an_absent_optional_section_is_omitted_from_the_canonical_form():
    """The hash of a deck box must not move because another archetype gained a section.
    `dataclasses.asdict` would have written `"divider":null` into every deck box spec
    ever stored, for a field those specs do not mention — and the next archetype's
    section would move them all again. `from_dict` defaults each to None, so nothing is
    lost: the round-trip test above is the other half of this one."""
    d = deck().to_dict()
    assert "divider" not in d and "tray" not in d and "lid" in d
    assert "divider" not in canonical_json(deck()) and "tray" not in canonical_json(deck())
    div = card_divider().to_dict()
    assert "lid" not in div and "tray" not in div and "divider" in div
    t = token_tray().to_dict()
    assert "lid" not in t and "divider" not in t and "tray" in t
    # And a section explicitly set to null on the way in is still absent on the way out.
    assert "lid" not in OrganizerSpec.from_dict({**div, "lid": None}).to_dict()


def test_the_third_archetypes_section_moved_no_existing_hash():
    """The rule above, as the thing it exists to prevent. `tray` is `Optional[...] =
    None` and in `_OPTIONAL_SECTIONS`, so adding it left the fixed vectors below — and
    every hash ever stored against them — byte for byte where they were. Had it been a
    plain field it would have written `"tray":null` into every deck box in the world.
    """
    assert spec_hash(deck()) == spec_hash(OrganizerSpec.from_dict(deck().to_dict()))
    for spec in (deck(), card_divider()):
        assert "tray" not in canonical_json(spec)
    assert '"tray":{"columns":3}' in canonical_json(token_tray())


#: The `spec_hash` of each shipped archetype's own `example()`, captured on `main` at
#: a828492 — **before** the box insert's `insert` section was written — and pinned here
#: so the fourth archetype's section is proved additive rather than remembered to be.
#:
#: The fixed canonical vectors below say the same thing for three hand-built specs; these
#: say it for the specs the registry itself hands out, which is what
#: `tests/test_archetype_registry.py`, the CLI's `example` and the composer's preview all
#: compile. A field added to `CardStack`, `Pocket`, `Process`, `Constraints` or `Tray`
#: would move every one of them, and nothing else in the suite would notice.
EXAMPLE_SPEC_HASHES: dict[str, str] = {
    "deck_box": "5bab61fffb5790a8076e1ea15965f8e163b4c280aa2889e00fe8f54bb3f71f6d",
    "card_divider": "d6c67cd15099f3bda088566e996c25cea0f3d2f144e180af707fb4919e9d69c7",
    "token_tray": "9d3cd1b52a4709453a70d60c7552f8a043e7e1e99309b9e39d02d75b6919e67c",
}


@pytest.mark.parametrize("archetype", sorted(EXAMPLE_SPEC_HASHES))
def test_no_archetypes_example_hash_has_moved(archetype):
    """Every example spec that existed before the box insert still hashes as it did.

    The acceptance criterion "no existing `spec_hash` moves", asserted rather than
    trusted. It is the guard the box insert needed and the guard the *next* archetype
    needs: the only additive-safe change to this schema is a new optional **section**
    (`_OPTIONAL_SECTIONS`), and nothing mechanical stops a well-meant scalar on a leaf
    class — which is written into every canonical form there has ever been.
    """
    from pythonsrc.organizer.archetypes import example_spec

    assert spec_hash(example_spec(archetype)) == EXAMPLE_SPEC_HASHES[archetype]


def test_the_hash_is_stable_across_processes():
    """A fixed vector: if this changes, every stored hash in the world changes with it,
    which is a schema-version bump, not a refactor.

    It has moved four times, deliberately. `constraints.fit_margin_mm` (issue #70)
    and `process.fit_intent` (issue #71) are scalars with defaults, not optional
    *sections*, so they are written for every spec the way `process.wall_mm` is.
    Issue #72 moved it again without adding a field: `process.wall_mm`'s default
    stopped being one unsourced 2,8 mm for every archetype and became the archetype's
    own — 2,4 mm here, the lid's arithmetic. A spec that *states* 2,8 mm hashes and
    compiles exactly as it always did, which is what `tests/test_deck_box.py` pins in
    bytes; only specs that never said anything move. Issue #80 added three more
    scalars — `base_chamfer_mm`, `corner_radius_mm`, `cavity_corner_radius_mm` — and
    that one moved the *geometry* of a stored spec as well as its hash, which is why
    `deck_box.ARCHETYPE_VERSION` went to 2 with it.

    A section is omitted when absent — that is what `_OPTIONAL_SECTIONS` is for — but
    omitting a scalar at its default would mean the canonical form no longer says what
    the spec is, and the next default to change would be unreadable in a diff. That is
    also why `wall_mm` is resolved here rather than left null for the compiler:
    `"wall_mm":2.4` in the canonical form is the wall the geometry has. The
    alternative, a `SCHEMA_VERSION` bump, refuses every existing spec file for an
    additive field. Rows already written keep the hash they recorded; nothing
    re-derives one.
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
        '"top_mm":2.0,"wall_mm":1.2},"process":{"base_chamfer_mm":0.6,'
        '"cavity_clearance_mm":1.5,"cavity_corner_radius_mm":0.0,'
        '"corner_radius_mm":1.0,"fit_intent":"snug","floor_mm":2.0,'
        '"min_feature_mm":1.0,"stack_slack_mm":1.0,"wall_mm":2.4},"schema_version":1}'
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
        '"thickness_mm":1.4},"process":{"base_chamfer_mm":0.6,'
        '"cavity_clearance_mm":1.5,"cavity_corner_radius_mm":0.0,'
        '"corner_radius_mm":1.0,"fit_intent":"snug","floor_mm":2.0,'
        '"min_feature_mm":1.0,"stack_slack_mm":1.0,"wall_mm":1.2},"schema_version":1}'
    )


def test_the_fixed_tray_vector_carries_a_pocket_and_no_card_stack():
    """The third archetype's own fixed vector. Note what is *not* here: no `count`, no
    `card`, no `sleeving`, and no `kind` discriminator on either shape — the union is
    told apart by the keys it carries, which is what kept the two vectors above from
    moving. `source` is written as null rather than omitted because it is a scalar with
    a default, like `constraints.max_external_mm`; only *sections* are omitted.

    The three edge scalars issue #80 added — `base_chamfer_mm`, `corner_radius_mm`,
    `cavity_corner_radius_mm` — are here for the reason `card_divider` states in as
    many words: a `Process` field this archetype does not read still hashes. A v1 tray
    is square-pocketed and square-cornered whatever they say; turning them into tray
    geometry (the internal round is the one that archetype was named for) is its own
    issue."""
    assert canonical_json(token_tray(rows=1, columns=2)) == (
        '{"archetype":"token_tray","compartments":['
        '{"contents":{"depth_mm":20.0,"height_mm":15.0,"source":null,"width_mm":20.0}},'
        '{"contents":{"depth_mm":20.0,"height_mm":15.0,"source":null,"width_mm":20.0}}],'
        '"constraints":{"fit_margin_mm":2.0,"max_external_mm":null},'
        '"process":{"base_chamfer_mm":0.6,"cavity_clearance_mm":1.5,'
        '"cavity_corner_radius_mm":0.0,"corner_radius_mm":1.0,"fit_intent":"snug",'
        '"floor_mm":2.0,"min_feature_mm":1.0,"stack_slack_mm":1.0,"wall_mm":1.6},'
        '"schema_version":1,"tray":{"columns":2}}'
    )


def test_diff_reports_a_grid_change_which_is_what_makes_f8_mechanical():
    """"Make it three across" has to be a path — `tray.columns` — for the same reason
    "make the tab wider" does."""
    a, b = token_tray(rows=2, columns=3), token_tray(rows=3, columns=3)
    # Same columns, three more compartments: the diff is the compartments, not the grid,
    # because the rows are derived from the compartment count rather than stated.
    added = spec_diff(a, b)
    assert "tray.columns" not in added
    assert added["compartments[6].contents.width_mm"] == (None, 20.0)
    c = token_tray(rows=2, columns=2)
    assert spec_diff(a, c)["tray.columns"] == (3, 2)


def test_diff_reports_a_card_stack_becoming_a_pocket_as_both_sides():
    """The union's own diff. A `CardStack` and a `Pocket` share no path at all, so the
    change reads as every card field removed and every pocket field added — which is
    exactly what happened, and what a saved design's history should say."""
    d = spec_diff(deck(), token_tray(rows=1, columns=1))
    assert d["compartments[0].contents.count"] == (100, None)
    assert d["compartments[0].contents.width_mm"] == (None, 20.0)


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
    import ast
    import importlib.util

    import pythonsrc.organizer as pkg
    assert pkg.OrganizerSpec is OrganizerSpec and pkg.spec_hash is spec_hash
    tree = ast.parse(open(importlib.util.find_spec("pythonsrc.organizer").origin).read())
    imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    imported |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert imported == {"spec"}


# ── every problem names a field, and the name is readable as data ──────────────
#
# A form can only put a refusal on the control it is about if the path is a value
# rather than a phrase inside a sentence. These tests are what the composer's
# field-level errors and `POST /jobs`'s 422 both stand on.

def test_a_problem_path_is_its_first_token():
    assert problem_path("spec.lid.clearance_mm must be ≥ 0 mm, got -1") == "spec.lid.clearance_mm"
    assert problem_path("spec.process has unknown field(s): nope") == "spec.process"


def test_every_schema_problem_starts_with_the_path_it_is_about():
    """The convention `problem_path` rests on, exercised across the whole shape of the
    schema: a nested field, a leaf's own rule, an unknown key and a bad tuple."""
    bad = {
        "archetype": "dragon",
        "compartments": [{"contents": {"count": 0, "card": "standard", "sleeving": "double"}}],
        "lid": {"kind": "slide", "clearance_mm": -1},
        "process": {"floor_mm": -2, "nope": 1},
        "constraints": {"max_external_mm": [10, 10]},
    }
    with pytest.raises(SpecError) as exc:
        OrganizerSpec.from_dict(bad)
    pairs = problems_with_paths(exc.value.problems)
    paths = [p["path"] for p in pairs]
    assert "spec.process" in paths            # the unknown key, on its owner
    assert "spec.constraints.max_external_mm" in paths
    # Every path is dotted from `spec` and names something, never a bare sentence.
    for problem, pair in zip(exc.value.problems, pairs, strict=True):
        assert pair["message"] == problem
        assert pair["path"] == problem.split(" ")[0]
        assert pair["path"] == "spec" or pair["path"].startswith("spec.")


def test_paths_reach_into_a_compartment_by_index():
    bad = {
        "archetype": "deck_box",
        "compartments": [{"contents": {"count": 100}}, {"contents": {"count": 0}}],
    }
    with pytest.raises(SpecError) as exc:
        OrganizerSpec.from_dict(bad)
    paths = [p["path"] for p in problems_with_paths(exc.value.problems)]
    assert "spec.compartments[1].contents.count" in paths


def test_problems_with_paths_keeps_the_order_and_the_whole_sentence():
    """A spec is refused whole, so the list is the refusal — nothing may be dropped or
    reordered on the way to the field it belongs on."""
    with pytest.raises(SpecError) as exc:
        OrganizerSpec.from_dict({"archetype": "deck_box", "compartments": []})
    pairs = problems_with_paths(exc.value.problems)
    assert [p["message"] for p in pairs] == exc.value.problems
