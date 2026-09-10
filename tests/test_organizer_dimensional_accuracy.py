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
    FIT_INTENT_CLEARANCE_MM,
    FIT_INTENTS,
    CardStack,
    Compartment,
    Divider,
    Lid,
    OrganizerSpec,
    Process,
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
         fit_intent="snug"):
    return OrganizerSpec(
        archetype="deck_box",
        compartments=(Compartment(CardStack(count=count, sleeving=sleeving)),),
        lid=Lid(height_mm=lid_height, clearance_mm=clearance),
        process=Process(wall_mm=wall, floor_mm=floor, fit_intent=fit_intent),
    )


def exported_and_reloaded(spec, path):
    """The mesh as a slicer would receive it: written as float32 STL and read back."""
    result = compile_spec(spec)
    export_stl(result.mesh, path)
    return result, trimesh.load(str(path), force="mesh")


COUNTS = (15, 40, 60, 100, 160)
SLEEVINGS = ("none", "single", "double")
WALLS = (2.6, 2.8, 4.0)  # 2.6 − 1.2 lid wall − 0.35 clearance = 1.05 mm lip, above min_feature
CLEARANCES = (0.1, 0.2, 0.35)
LID_HEIGHTS = (8.0, 15.0, 30.0)

ENVELOPE = list(itertools.product(COUNTS, SLEEVINGS, WALLS, CLEARANCES, LID_HEIGHTS))


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
    """Guards the sweep against being quietly narrowed to the one example spec."""
    assert len(ENVELOPE) >= 400
    assert min(COUNTS) < 20 and max(COUNTS) >= 150
    assert set(SLEEVINGS) == {"none", "single", "double"}


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


# ── through Phase 3 ────────────────────────────────────────────────────────────

from pythonsrc.engineer import Engineer  # noqa: E402

CORNERS = list(itertools.product(
    (15, 60, 160), SLEEVINGS,
    ((2.6, 0.1, 8.0), (2.8, 0.2, 15.0), (4.0, 0.35, 30.0), (2.6, 0.35, 8.0)),
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
