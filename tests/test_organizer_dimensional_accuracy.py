"""Dimensional accuracy: spec → exported mesh, per critical feature (PRD N1).

An accuracy claim with no test is a marketing number. These tests measure the error
between what a spec designed and what the *exported* mesh carries — the STL a slicer
would be handed, float32, vertices merged on reload — for every feature the archetype
can read back off geometry, across its parameter envelope, and then again through Phase
3's assert path. The bound is `DEFAULT_TOLERANCE_MM` (0,05 mm). Nothing here is asserted
from the spec's own arithmetic; every number is read off planes in the mesh.

Two archetypes now have an envelope here, each with its own parametrize — the deck box
(counts × sleevings × walls × clearances × lid engagement) and the card divider
(sleevings × tab positions × thicknesses × tab sizes). The generic sweep across *every*
archetype is issue #85 and is still open; until it lands, a new archetype adds a block.

Two further tests prove the assertion bites, because a check that cannot fail is not a
check: a mesh scaled by 0,2 % is caught and the feature named, and a mesh with a face
missing is refused before anything is exported.

CI runs this file as its own named step (`.github/workflows/ci.yml`), so a regression in
dimensional accuracy is legible from the job list without opening a log.
"""
import itertools
import json

import pytest
import trimesh

from pythonsrc.organizer.archetypes import card_divider, compile_spec, deck_box, verify_spec_mesh
from pythonsrc.organizer.compiler import (
    DEFAULT_TOLERANCE_MM,
    DimensionReport,
    check_dimensions,
    export_stl,
)
from pythonsrc.organizer.dimensions import resolve_stack
from pythonsrc.organizer.spec import (
    ARCHETYPE_WALL_MM,
    FIT_INTENT_CLEARANCE_MM,
    FIT_INTENTS,
    CardStack,
    Compartment,
    Divider,
    Lid,
    OrganizerSpec,
    Process,
    SpecError,
    wall_floor_mm,
)

TOL_MM = DEFAULT_TOLERANCE_MM


# ── the check itself ───────────────────────────────────────────────────────────

def test_check_dimensions_reports_every_feature_with_its_error():
    report = check_dimensions(
        {"a_mm": 10.0, "b_mm": 5.0}, {"a_mm": 10.01, "b_mm": 5.0}, tol_mm=0.05, required={"a_mm", "b_mm"},
    )
    assert isinstance(report, DimensionReport)
    assert report.tolerance_mm == 0.05
    assert report.features["a_mm"] == pytest.approx((10.0, 10.01, 0.01))
    assert report.features["b_mm"] == (5.0, 5.0, 0.0)
    assert report.max_abs_error_mm == pytest.approx(0.01)
    assert report.within_tolerance is True
    assert report.missing == () and report.out_of_tolerance == ()
    assert report.problems() == []


def test_check_dimensions_names_what_is_out_of_tolerance_and_what_is_missing():
    report = check_dimensions(
        {"a_mm": 10.0, "b_mm": 5.0, "c_mm": 1.0}, {"a_mm": 10.2, "b_mm": 5.0}, tol_mm=0.05,
        required={"a_mm", "b_mm", "c_mm"},
    )
    assert report.within_tolerance is False
    assert report.out_of_tolerance == ("a_mm",)
    assert report.missing == ("c_mm",)
    problems = report.problems()
    assert any("a_mm" in p and "+0.200" in p for p in problems)
    assert any("c_mm" in p and "not measured" in p for p in problems)


def test_check_dimensions_ignores_designed_features_that_are_not_required():
    """A stack height is designed but not on the mesh; it is skipped, not reported missing."""
    report = check_dimensions({"a_mm": 1.0, "stack_mm": 70.0}, {"a_mm": 1.0}, tol_mm=0.05, required={"a_mm"})
    assert report.within_tolerance is True
    assert "stack_mm" not in report.features and report.missing == ()


def test_the_report_serialises_to_the_json_written_beside_the_mesh():
    report = check_dimensions({"a_mm": 10.0}, {"a_mm": 10.02}, tol_mm=0.05, required={"a_mm"})
    doc = json.loads(json.dumps(report.to_dict()))
    assert doc["tolerance_mm"] == 0.05
    assert doc["within_tolerance"] is True
    assert doc["features_checked"] == 1 and doc["features_within"] == 1
    assert doc["features"]["a_mm"] == {"designed_mm": 10.0, "measured_mm": 10.02, "error_mm": pytest.approx(0.02)}
    assert doc["missing"] == [] and doc["out_of_tolerance"] == []
    assert doc["max_abs_error_mm"] == pytest.approx(0.02)


# ── the envelope ───────────────────────────────────────────────────────────────

def deck(count=100, sleeving="double", wall=2.8, clearance=0.2, lid_height=15.0, floor=2.0,
         fit_intent="snug", chamfer=None, radius=None, cavity_radius=None):
    """A deck box spec. `wall=None` states no wall and takes the archetype's default,
    which is what every spec that does not mention one compiles with (issue #72). The
    three edge treatments default to `None`, which likewise leaves `Process`'s own
    defaults — a 0,6 mm chamfer and a 1,0 mm corner round — in place, so the envelope
    above sweeps the geometry a real spec gets rather than a square-cornered variant."""
    edges = {
        name: value
        for name, value in (("base_chamfer_mm", chamfer), ("corner_radius_mm", radius),
                            ("cavity_corner_radius_mm", cavity_radius))
        if value is not None
    }
    return OrganizerSpec(
        archetype="deck_box",
        compartments=(Compartment(CardStack(count=count, sleeving=sleeving)),),
        lid=Lid(height_mm=lid_height, clearance_mm=clearance),
        process=Process(wall_mm=wall, floor_mm=floor, fit_intent=fit_intent, **edges),
    )


def exported_and_reloaded(spec, path):
    """The mesh as a slicer would receive it: written as float32 STL and read back."""
    result = compile_spec(spec)
    export_stl(result.mesh, path)
    return result, trimesh.load(str(path), force="mesh")


COUNTS = (15, 40, 60, 100, 160)
SLEEVINGS = ("none", "single", "double")
#: `None` states no wall at all and takes the archetype's own default (2,4 mm). It is
#: swept as a value rather than checked once, because it is what almost every real spec
#: compiles with, and a dimensional claim about a wall nobody typed is worth as much as
#: one about 2,8 mm. 2.6 − 1.2 lid wall − 0.35 clearance = 1.05 mm lip, above
#: min_feature; at the 2,4 mm default that same clearance leaves 0.85 mm and the
#: archetype refuses it, so `_lip_is_buildable` drops the pair rather than sweeping a
#: box that does not exist.
WALLS = (None, 2.6, 2.8, 4.0)
CLEARANCES = (0.1, 0.2, 0.35)
LID_HEIGHTS = (8.0, 15.0, 30.0)


def _wall_mm(wall):
    """The wall a swept case actually builds with; `None` is the archetype's default."""
    return ARCHETYPE_WALL_MM["deck_box"] if wall is None else wall


def _lip_is_buildable(wall, clearance):
    """`deck_box.validate`'s lip rule, restated so the sweep asks only for boxes that
    exist: the body wall less the lid's wall and clearance must reach `min_feature_mm`."""
    return _wall_mm(wall) - (Lid().wall_mm + clearance) >= Process().min_feature_mm - 1e-9


ENVELOPE = [
    case for case in itertools.product(COUNTS, SLEEVINGS, WALLS, CLEARANCES, LID_HEIGHTS)
    if _lip_is_buildable(case[2], case[3])
]


@pytest.mark.parametrize("count,sleeving,wall,clearance,lid_height", ENVELOPE)
def test_every_measured_feature_of_the_exported_mesh_is_within_tolerance(
    tmp_path, count, sleeving, wall, clearance, lid_height,
):
    spec = deck(count, sleeving, wall, clearance, lid_height)
    result, mesh = exported_and_reloaded(spec, tmp_path / "deck.stl")
    report = verify_spec_mesh(spec, result.features, mesh)
    assert report.within_tolerance, report.problems()
    assert set(report.features) == set(deck_box.MEASURED_FEATURES)


def test_the_envelope_is_wide_enough_to_mean_something():
    """Guards the sweep against being quietly narrowed to the one example spec, and in
    particular against losing the unstated wall: `None` is what almost every real spec
    is, and it is the case a changed archetype default moves."""
    assert len(ENVELOPE) >= 400
    assert min(COUNTS) < 20 and max(COUNTS) >= 150
    assert set(SLEEVINGS) == {"none", "single", "double"}
    assert None in WALLS
    assert len([c for c in ENVELOPE if c[2] is None]) >= 90


# ── the wall: the archetype's default, and the nozzle's floor (issue #72) ──────
#
# The sweep above carries the default as one of its `WALLS`, which proves the
# millimetres. What it cannot carry is the floor: below it nothing compiles, so there
# is no mesh to measure and the coverage is a refusal instead. Both halves live here —
# the default is *measured off the mesh*, the floor is *named in the refusal* — and
# both are swept across the counts and sleevings that move the numbers around them.

FLOOR_NOZZLES = (0.4, 0.6, 0.8)


@pytest.mark.parametrize("count,sleeving", list(itertools.product(COUNTS, SLEEVINGS)))
def test_the_wall_the_archetype_chose_is_on_the_exported_mesh(tmp_path, count, sleeving):
    """A spec that states no wall gets 2,4 mm, and the mesh has to carry it — not the
    dataclass, the geometry. Read as the difference between two planes in the exported
    float32 STL, like every other number in this file."""
    spec = deck(count, sleeving, wall=None)
    assert spec.process.wall_mm == ARCHETYPE_WALL_MM["deck_box"]
    result, mesh = exported_and_reloaded(spec, tmp_path / "deck.stl")
    report = verify_spec_mesh(spec, result.features, mesh)
    assert report.within_tolerance, report.problems()
    measured_wall = report.features["wall_mm"][1]
    assert measured_wall == pytest.approx(ARCHETYPE_WALL_MM["deck_box"], abs=TOL_MM)
    # And the externals move with it: the wall is on both sides of every axis.
    envelope_w = resolve_stack(count, "standard", sleeving).footprint_w_mm
    assert report.features["external_width_mm"][1] - envelope_w == pytest.approx(
        FIT_INTENT_CLEARANCE_MM["snug"] + 2 * ARCHETYPE_WALL_MM["deck_box"], abs=TOL_MM
    )


@pytest.mark.parametrize("nozzle", FLOOR_NOZZLES)
def test_a_wall_under_the_nozzles_floor_is_refused_with_both_numbers(tmp_path, nozzle):
    """One micron under the floor is refused; the floor itself compiles and measures
    back. The lid is thinned so the *only* thing standing between this spec and a mesh
    is the floor — otherwise the lip rule would be doing the refusing."""
    floor = wall_floor_mm(nozzle)
    assert floor == pytest.approx(3.0 * nozzle)

    def at(wall):
        return OrganizerSpec(
            archetype="deck_box",
            compartments=(Compartment(CardStack(count=100, sleeving="double")),),
            lid=Lid(height_mm=15.0, wall_mm=0.6, clearance_mm=0.1),
            process=Process(wall_mm=wall, min_feature_mm=0.2),
        )

    with pytest.raises(SpecError) as exc:
        compile_spec(at(round(floor - 0.001, 3)), nozzle_diameter_mm=nozzle)
    message = str(exc.value)
    assert f"{floor:g} mm wall floor" in message and f"{nozzle:g} mm nozzle" in message

    spec = at(floor)
    result, mesh = exported_and_reloaded(spec, tmp_path / "floor.stl")
    report = verify_spec_mesh(spec, result.features, mesh)
    assert report.within_tolerance, report.problems()
    assert report.features["wall_mm"][1] == pytest.approx(floor, abs=TOL_MM)


def test_the_floor_is_the_same_rule_at_every_nozzle_the_sweep_names():
    """Guards the parametrize above against collapsing to 0,4 mm, which is the one
    nozzle where a hard-coded 1,2 mm and the derived floor are indistinguishable."""
    assert len(set(FLOOR_NOZZLES)) >= 3
    assert len({wall_floor_mm(n) for n in FLOOR_NOZZLES}) == len(FLOOR_NOZZLES)


# ── the easy fit intent's corner (issue #71) ───────────────────────────────────
#
# Its own corner rather than a sixth axis on ENVELOPE: `fit_intent` moves exactly two
# lengths (the cavity's width and height, by 2,5 mm each) and is orthogonal to the wall,
# the lid and the clearance, so doubling 405 cases would buy repetition rather than
# coverage. What it must prove is that the wider cavity is *measured back* off the
# exported mesh, across the counts and sleevings that change the numbers around it.

INTENT_CORNERS = list(itertools.product(FIT_INTENTS, COUNTS, SLEEVINGS))


@pytest.mark.parametrize("fit_intent,count,sleeving", INTENT_CORNERS)
def test_the_cavity_the_fit_intent_chose_is_on_the_exported_mesh(
    tmp_path, fit_intent, count, sleeving,
):
    spec = deck(count, sleeving, fit_intent=fit_intent)
    result, mesh = exported_and_reloaded(spec, tmp_path / "deck.stl")
    report = verify_spec_mesh(spec, result.features, mesh)
    assert report.within_tolerance, report.problems()
    # Not asserted from the spec's arithmetic: the clearance is read as the difference
    # between two planes in the mesh and the sleeve envelope the KB sourced.
    envelope_w = resolve_stack(count, "standard", sleeving).footprint_w_mm
    measured_w = report.features["cavity_width_mm"][1]
    assert measured_w - envelope_w == pytest.approx(
        FIT_INTENT_CLEARANCE_MM[fit_intent], abs=TOL_MM
    )


def test_both_intents_are_swept_and_they_differ(tmp_path):
    """Guards the corner above against collapsing to one intent, which would leave
    `easy` unmeasured while the sweep still looked parametrized."""
    assert {i for i, _, _ in INTENT_CORNERS} == set(FIT_INTENTS)
    assert len(set(FIT_INTENT_CLEARANCE_MM.values())) == len(FIT_INTENTS)


# ── the edge treatments' corner (issue #80) ───────────────────────────────────
#
# Its own corner rather than three more axes on ENVELOPE, for `fit_intent`'s reason and
# one more. The reason: a chamfer and a corner round are orthogonal to the wall, the lid
# and the clearance, so multiplying 405 by 24 would buy repetition. The one more: unlike
# every other axis here, these two change the *kind* of surface the mesh carries — an
# arc where there was a plane, a 45° face where there was an edge — so what has to be
# swept is the span from "absent" to "as large as the rules allow", on both bodies, and
# through the export the rest of this file measures on.
#
# `(0,5, 0,6)` and `(1,0, 1,5)` are in deliberately: a chamfer taller than the corner it
# runs around is the case `base_chamfer`'s fast construction cannot do, so those two send
# it down the general one. `radius = 2,4` needs `wall = 4,0` — a round may not exceed the
# wall it is cut from — and is the case where the lip and the lid cavity get derived
# radii of their own instead of clamping to zero.

EDGE_CORNERS = [
    (chamfer, radius, cavity_radius, wall, count, sleeving)
    for chamfer, radius, cavity_radius, wall in (
        (0.0, 0.0, 0.0, None),     # the geometry this project built before issue #80
        (0.6, 1.0, 0.0, None),     # the defaults
        (0.6, 0.0, 0.0, None),     # chamfer alone
        (0.0, 1.0, 0.75, None),    # rounds alone, inside and out
        (1.5, 1.0, 0.0, None),     # chamfer taller than the corner: general construction
        (0.6, 0.5, 0.0, None),     # ditto, by a tenth
        (0.8, 2.4, 0.75, None),    # radius exactly at the wall; derived radii non-zero
        (1.5, 2.4, 2.5, 4.0),      # every rule at its ceiling, on a thicker wall
    )
    for count, sleeving in itertools.product((15, 160), SLEEVINGS)
]


@pytest.mark.parametrize("chamfer,radius,cavity_radius,wall,count,sleeving", EDGE_CORNERS)
def test_every_edge_treatment_is_on_the_exported_mesh(
    tmp_path, chamfer, radius, cavity_radius, wall, count, sleeving,
):
    spec = deck(count, sleeving, wall=wall, chamfer=chamfer, radius=radius,
                cavity_radius=cavity_radius)
    result, mesh = exported_and_reloaded(spec, tmp_path / "deck.stl")
    # The float32 round trip is the point of this file, and a chamfer is the feature
    # most likely to fail it: a degenerate triangle along a seam survives float64 and
    # opens the mesh in float32. Two bodies, both closed, or the measurement below is
    # measuring something that could not be printed.
    assert mesh.is_watertight
    assert len(mesh.split(only_watertight=False)) == 2
    report = verify_spec_mesh(spec, result.features, mesh)
    assert report.within_tolerance, report.problems()
    assert set(report.features) == set(deck_box.MEASURED_FEATURES)
    assert report.features["base_chamfer_mm"][1] == pytest.approx(chamfer, abs=TOL_MM)
    assert report.features["corner_radius_mm"][1] == pytest.approx(radius, abs=TOL_MM)
    assert report.features["cavity_corner_radius_mm"][1] == pytest.approx(
        cavity_radius, abs=TOL_MM)


def test_the_edge_corner_spans_absent_and_present_on_every_axis():
    """Guards the block above against collapsing to one setting — which would leave a
    treatment unmeasured while the sweep still looked parametrized — and against losing
    the zero case, which is the pre-#80 geometry every stored spec file compiles to."""
    for axis, name in enumerate(("chamfer", "external round", "internal round")):
        values = {case[axis] for case in EDGE_CORNERS}
        assert 0.0 in values and len(values) >= 2, name
    assert any(c[0] > c[1] > 0 for c in EDGE_CORNERS), "no case takes the general construction"
    assert any(c[1] == _wall_mm(c[3]) for c in EDGE_CORNERS), "no case puts the round at the wall"
    # And one where the lip and the lid cavity get radii of their own rather than
    # clamping to zero, which is the derivation that keeps the closure's fit exact.
    assert any(c[1] > Lid().wall_mm + Lid().clearance_mm for c in EDGE_CORNERS)


# ── through Phase 3 ────────────────────────────────────────────────────────────

from pythonsrc.engineer import Engineer  # noqa: E402

CORNERS = list(itertools.product(
    (15, 60, 160), SLEEVINGS,
    ((2.6, 0.1, 8.0), (2.8, 0.2, 15.0), (4.0, 0.35, 30.0), (2.6, 0.35, 8.0),
     (None, 0.2, 15.0)),
))


@pytest.mark.parametrize("count,sleeving,process", CORNERS)
def test_phase_3_assert_path_hands_the_slicer_the_designed_dimensions(tmp_path, count, sleeving, process):
    wall, clearance, lid_height = process
    spec = deck(count, sleeving, wall, clearance, lid_height)
    result, _ = exported_and_reloaded(spec, tmp_path / "compiled_mesh.stl")
    eng = Engineer()
    out = eng.process(
        input_path=tmp_path / "compiled_mesh.stl", output_path=tmp_path / "engineered.obj",
        target_mm=None, repair_mode="assert",
    )
    report = verify_spec_mesh(spec, result.features, trimesh.load(str(out), force="mesh"))
    assert report.within_tolerance, report.problems()
    assert eng.last_report["repair_method"] == "asserted"
    assert eng.last_report["scale_applied"] is False


EDGE_PHASE_3_CORNERS = [
    (chamfer, radius, cavity_radius, wall, sleeving)
    for chamfer, radius, cavity_radius, wall in (
        (0.0, 0.0, 0.0, None), (0.6, 1.0, 0.0, None),
        (0.6, 0.5, 0.75, None), (1.5, 2.4, 2.5, 4.0),
    )
    for sleeving in SLEEVINGS
]


@pytest.mark.parametrize("chamfer,radius,cavity_radius,wall,sleeving", EDGE_PHASE_3_CORNERS)
def test_phase_3_assert_path_hands_the_slicer_the_treated_edges(
    tmp_path, chamfer, radius, cavity_radius, wall, sleeving,
):
    """A spec run's Phase 3 asserts rather than repairs, so an edge treatment has to
    arrive as a *solid* — a chamfer that left degenerate triangles behind would be
    refused here with `MeshAssertionError` rather than measured. Nothing may decimate
    the arcs away either, which is what `faces_dropped` is for."""
    spec = deck(60, sleeving, wall=wall, chamfer=chamfer, radius=radius,
                cavity_radius=cavity_radius)
    result, _ = exported_and_reloaded(spec, tmp_path / "compiled_mesh.stl")
    eng = Engineer()
    out = eng.process(
        input_path=tmp_path / "compiled_mesh.stl", output_path=tmp_path / "engineered.obj",
        target_mm=None, repair_mode="assert",
    )
    report = verify_spec_mesh(spec, result.features, trimesh.load(str(out), force="mesh"))
    assert report.within_tolerance, report.problems()
    assert eng.last_report["repair_method"] == "asserted"
    assert eng.last_report.get("faces_dropped", 0) == 0


EASY_CORNERS = list(itertools.product((15, 160), SLEEVINGS))


@pytest.mark.parametrize("count,sleeving", EASY_CORNERS)
def test_phase_3_assert_path_hands_the_slicer_an_easy_fit_unchanged(tmp_path, count, sleeving):
    """The intent's millimetres have to survive the same seam the snug ones do: Phase 3
    asserts a spec run rather than repairing it, and nothing there may resize a cavity
    somebody widened on purpose."""
    spec = deck(count, sleeving, fit_intent="easy")
    result, _ = exported_and_reloaded(spec, tmp_path / "compiled_mesh.stl")
    eng = Engineer()
    out = eng.process(
        input_path=tmp_path / "compiled_mesh.stl", output_path=tmp_path / "engineered.obj",
        target_mm=None, repair_mode="assert",
    )
    report = verify_spec_mesh(spec, result.features, trimesh.load(str(out), force="mesh"))
    assert report.within_tolerance, report.problems()
    assert eng.last_report["scale_applied"] is False


# ── the check can fail ─────────────────────────────────────────────────────────

def test_a_mesh_scaled_by_a_fifth_of_a_percent_is_caught_and_the_feature_named(tmp_path):
    spec = deck()
    result, mesh = exported_and_reloaded(spec, tmp_path / "deck.stl")
    drifted = mesh.copy()
    drifted.apply_scale(1.002)  # 68.5 mm → 68.637 mm: 0.137 mm over a 0.05 mm bound
    report = verify_spec_mesh(spec, result.features, drifted)
    assert report.within_tolerance is False
    assert "cavity_width_mm" in report.out_of_tolerance
    assert report.max_abs_error_mm > TOL_MM


def test_the_default_deck_box_has_sub_micron_error_on_the_exported_mesh(tmp_path):
    """The headline number, stated as an assertion: float32 STL noise, not geometry."""
    spec = deck()
    result, mesh = exported_and_reloaded(spec, tmp_path / "deck.stl")
    report = verify_spec_mesh(spec, result.features, mesh)
    assert report.max_abs_error_mm < 1e-4


# ── the card divider's envelope ────────────────────────────────────────────────
#
# Its own parametrize rather than the generic sweep (#85, still open). Five axes, and
# the tab position is one of them because it is the only parameter that changes the
# *shape* of the outline rather than a length: an edge tab shares a side plane with the
# plate, which is exactly the case a union got wrong and an extruded outline does not.


def divider(sleeving="double", thickness=1.4, tab_width=20.0, tab_height=10.0,
            position="centre", count=100):
    return OrganizerSpec(
        archetype="card_divider",
        compartments=(Compartment(CardStack(count=count, sleeving=sleeving)),),
        divider=Divider(thickness_mm=thickness, tab_width_mm=tab_width,
                        tab_height_mm=tab_height, tab_position=position),
    )


D_SLEEVINGS = ("none", "single", "double")
D_POSITIONS = ("left", "centre", "right")
D_THICKNESSES = (1.2, 1.4, 1.6, 2.0)   # the audited 1,2–1,6 mm insert band, plus one over
D_TAB_WIDTHS = (12.0, 20.0, 30.0)
D_TAB_HEIGHTS = (6.0, 10.0, 15.0)

DIVIDER_ENVELOPE = list(itertools.product(
    D_SLEEVINGS, D_POSITIONS, D_THICKNESSES, D_TAB_WIDTHS, D_TAB_HEIGHTS,
))


@pytest.mark.parametrize("sleeving,position,thickness,tab_width,tab_height", DIVIDER_ENVELOPE)
def test_every_measured_feature_of_an_exported_divider_is_within_tolerance(
    tmp_path, sleeving, position, thickness, tab_width, tab_height,
):
    spec = divider(sleeving, thickness, tab_width, tab_height, position)
    result, mesh = exported_and_reloaded(spec, tmp_path / "divider.stl")
    report = verify_spec_mesh(spec, result.features, mesh)
    assert report.within_tolerance, report.problems()
    assert set(report.features) == set(card_divider.MEASURED_FEATURES)


def test_the_divider_envelope_is_wide_enough_to_mean_something():
    """Guards this sweep against being quietly narrowed to the one example spec, and
    pins the three tab positions in particular — dropping `left` and `right` would
    remove the only cases where the tab's plane is the plate's."""
    assert len(DIVIDER_ENVELOPE) >= 300
    assert set(D_POSITIONS) == {"left", "centre", "right"}
    assert set(D_SLEEVINGS) == {"none", "single", "double"}
    assert min(D_THICKNESSES) <= 1.2 and max(D_THICKNESSES) >= 2.0


DIVIDER_CORNERS = list(itertools.product(
    D_SLEEVINGS, D_POSITIONS,
    ((1.2, 12.0, 6.0), (1.4, 20.0, 10.0), (2.0, 30.0, 15.0), (1.2, 30.0, 6.0)),
))


@pytest.mark.parametrize("sleeving,position,divider_params", DIVIDER_CORNERS)
def test_phase_3_assert_path_hands_the_slicer_the_designed_divider(
    tmp_path, sleeving, position, divider_params,
):
    thickness, tab_width, tab_height = divider_params
    spec = divider(sleeving, thickness, tab_width, tab_height, position)
    result, _ = exported_and_reloaded(spec, tmp_path / "compiled_mesh.stl")
    eng = Engineer()
    out = eng.process(
        input_path=tmp_path / "compiled_mesh.stl", output_path=tmp_path / "engineered.obj",
        target_mm=None, repair_mode="assert",
    )
    report = verify_spec_mesh(spec, result.features, trimesh.load(str(out), force="mesh"))
    assert report.within_tolerance, report.problems()
    assert eng.last_report["repair_method"] == "asserted"
    assert eng.last_report["scale_applied"] is False


def test_a_divider_scaled_by_a_fifth_of_a_percent_is_caught_and_the_feature_named(tmp_path):
    """The check bites on the second archetype too: a plate 0,2 % wide is 0,134 mm out
    on a 67 mm envelope, and the report names which feature moved."""
    spec = divider()
    result, mesh = exported_and_reloaded(spec, tmp_path / "divider.stl")
    drifted = mesh.copy()
    drifted.apply_scale(1.002)
    report = verify_spec_mesh(spec, result.features, drifted)
    assert report.within_tolerance is False
    assert "plate_width_mm" in report.out_of_tolerance
    assert report.max_abs_error_mm > TOL_MM


def test_the_default_divider_has_sub_micron_error_on_the_exported_mesh(tmp_path):
    spec = divider()
    result, mesh = exported_and_reloaded(spec, tmp_path / "divider.stl")
    assert verify_spec_mesh(spec, result.features, mesh).max_abs_error_mm < 1e-4
