"""Dimensional accuracy: spec → exported mesh, per critical feature (PRD N1).

An accuracy claim with no test is a marketing number. These tests measure the error
between what a spec designed and what the *exported* mesh carries — the STL a slicer
would be handed, float32, vertices merged on reload — for every feature the archetype
can read back off geometry, across its parameter envelope, and then again through Phase
3's assert path. The bound is `DEFAULT_TOLERANCE_MM` (0,05 mm). Nothing here is asserted
from the spec's own arithmetic; every number is read off planes in the mesh.

**The sweep is archetype-generic (issue #85).** Each archetype module declares its own
envelope — `envelope()`, returning `common.SweepCase`s, the parameter ranges plus the
corner set that goes on through Phase 3 — and one parametrized test drives every spec
of every registered archetype through the same five assertions. It used to be written
for the deck box and then copied per archetype, which meant a fourth archetype could be
registered, compiled, offered in the composer and printed while nothing had ever
measured a mesh it produced. A module that declares no envelope now fails by name:
being swept is what makes an archetype an archetype rather than a mesh generator.

What stays per-archetype below is the corner each one contributes on its own — the deck
box's nozzle-derived wall floor (no mesh exists below it, so the coverage is a refusal),
its fit intent and its edge treatments, and the drift cases that prove the check bites
on each archetype's own geometry, including inside a token tray's grid.

Two further tests prove the assertion bites, because a check that cannot fail is not a
check: a mesh scaled by 0,2 % is caught and the feature named, and a mesh with a face
missing is refused before anything is exported.

CI runs this file as its own named step (`.github/workflows/ci.yml`), and the run ends
with one line per archetype (`deck_box: 495/495`) from the hooks in `tests/conftest.py`,
so a regression in dimensional accuracy — or an archetype that quietly contributes
nothing — is legible from the job list without opening a log.
"""
import itertools
import json

import pytest
import trimesh

from pythonsrc.engineer import Engineer
from pythonsrc.organizer.archetypes import (
    REGISTRY,
    box_insert,
    card_divider,
    compile_spec,
    deck_box,
    envelope_for,
    required_measurements,
    token_tray,
    verify_spec_mesh,
)
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
    Insert,
    Lid,
    OrganizerSpec,
    Pocket,
    Process,
    SpecError,
    Tray,
    wall_floor_mm,
)
from tests.sweep_tally import SweepTally

TOL_MM = DEFAULT_TOLERANCE_MM


def exported_and_reloaded(spec, path):
    """The mesh as a slicer would receive it: written as float32 STL and read back."""
    result = compile_spec(spec)
    export_stl(result.mesh, path)
    return result, trimesh.load(str(path), force="mesh")


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


# ── the generic sweep (issue #85) ──────────────────────────────────────────────
#
# One parametrize over every registered archetype's declared envelope. Collection asks
# `envelope_for` for each name and tolerates the refusal — an archetype with no envelope
# must fail as *itself*, naming itself, rather than taking every other archetype's
# coverage down with a collection error — which is what the first test below is for.


def _declared_envelope(name):
    """This archetype's envelope, or nothing at all if it declares none."""
    try:
        return envelope_for(name)
    except SpecError:
        return ()


SWEEP = [
    pytest.param(name, case, id=f"{name}-{case.id}")
    for name in sorted(REGISTRY)
    for case in _declared_envelope(name)
]
PHASE_3_SWEEP = [
    pytest.param(name, case, id=f"{name}-{case.id}")
    for name in sorted(REGISTRY)
    for case in _declared_envelope(name)
    if case.phase_3
]


@pytest.mark.parametrize("name", sorted(REGISTRY))
def test_every_registered_archetype_declares_an_envelope(name):
    """The sweep is the definition of "an archetype exists". A module registered without
    one compiles, is offered in the composer and reaches a printer with nothing ever
    having measured a mesh it produced, and the parametrize above would be silently
    empty for it — so this asks each name on its own and fails naming it."""
    cases = envelope_for(name)
    assert cases, f"{name} declares an empty envelope"
    assert all(case.spec.archetype == name for case in cases)
    assert len({case.id for case in cases}) == len(cases), f"{name} repeats a case id"
    assert any(case.phase_3 for case in cases), (
        f"{name} sends nothing through Phase 3's assert path"
    )


@pytest.mark.dimensional_sweep
@pytest.mark.parametrize("archetype,case", SWEEP)
def test_every_spec_in_every_envelope_is_a_solid_within_tolerance(tmp_path, archetype, case):
    """Five assertions, the same five for every archetype.

    `Engineer.assert_manifold` is the production check rather than a restatement of it:
    watertight, no boundary edge, no non-manifold edge, consistent winding and positive
    volume, and acceptance by the `manifold3d` kernel. It runs on the *exported,
    reloaded* mesh, which is the point of this file — a degenerate triangle along a
    chamfer seam survives float64 and opens the surface in float32.

    Then the dimensions, and the *set* of them: equality with `required_measurements`
    rather than containment, because a report that silently checked five of a tray's
    thirty features would say "within tolerance" and mean almost nothing.
    """
    result, mesh = exported_and_reloaded(case.spec, tmp_path / f"{archetype}.stl")
    findings = Engineer().assert_manifold(mesh)
    assert findings["watertight"] is True
    assert findings["nonmanifold_edges"] == 0 and findings["boundary_edges"] == 0
    assert findings["kernel_status"] == "NoError"
    report = verify_spec_mesh(case.spec, result.features, mesh)
    assert report.within_tolerance, report.problems()
    assert set(report.features) == set(required_measurements(case.spec))


@pytest.mark.parametrize("archetype,case", PHASE_3_SWEEP)
def test_phase_3_assert_path_hands_the_slicer_every_envelope_corner(tmp_path, archetype, case):
    """A spec run's Phase 3 asserts rather than repairs, so the corner set has to arrive
    as a solid and leave with the same millimetres: nothing there may rescale a cavity,
    and nothing may decimate an arc away, which is what `faces_dropped` is for.

    Deliberately *not* marked `dimensional_sweep`: the run summary counts envelope
    cases, and folding a slower corner set into the same figure would make
    `deck_box: 495/495` mean two different things depending on which tests ran.
    """
    result, _ = exported_and_reloaded(case.spec, tmp_path / "compiled_mesh.stl")
    eng = Engineer()
    out = eng.process(
        input_path=tmp_path / "compiled_mesh.stl", output_path=tmp_path / "engineered.obj",
        target_mm=None, repair_mode="assert",
    )
    report = verify_spec_mesh(case.spec, result.features, trimesh.load(str(out), force="mesh"))
    assert report.within_tolerance, report.problems()
    assert eng.last_report["repair_method"] == "asserted"
    assert eng.last_report["scale_applied"] is False
    assert eng.last_report.get("faces_dropped", 0) == 0


def test_the_sweep_covers_every_archetype_the_registry_can_compile():
    """The property the generic sweep exists for: adding an archetype adds its cases
    here without anybody editing this file. Guards against the parametrize being
    narrowed to a list of names somebody has to remember to extend."""
    assert {name for name, _ in ((p.values[0], p.values[1]) for p in SWEEP)} == set(REGISTRY)
    assert len(SWEEP) == sum(len(envelope_for(name)) for name in REGISTRY)


# ── the run summary, one line per archetype ────────────────────────────────────
#
# What CI prints and what `tests/conftest.py`'s hooks count. The figures are tested
# here rather than through a nested pytest run; the binding between this test's marker
# and the hook that reads it is the last test in the block.

def test_the_summary_prints_one_line_per_archetype_swept():
    tally = SweepTally()
    for name in sorted(REGISTRY):
        tally.record(name, "passed")
    assert tally.lines() == [f"{name}: 1/1" for name in sorted(REGISTRY)]


def test_the_summary_names_a_shortfall_rather_than_leaving_it_to_subtraction():
    tally = SweepTally()
    for outcome in ("passed", "passed", "failed", "skipped"):
        tally.record("deck_box", outcome)
    assert tally.lines() == ["deck_box: 2/4 (1 failed, 1 skipped)"]


def test_a_run_that_swept_nothing_prints_nothing():
    """A denominator derived from the envelope would say 495/495 for a run that
    collected no case at all; the tally counts reports, so it stays silent."""
    tally = SweepTally()
    assert not tally and tally.lines() == []


def test_the_summary_hook_can_find_what_it_counts():
    """`conftest.pytest_collection_modifyitems` looks for the `dimensional_sweep` marker
    and reads the `archetype` parameter off the callspec. Both are spelled in this file
    and read in that one, so nothing else would notice them drifting apart — the summary
    would simply stop printing."""
    sweep = test_every_spec_in_every_envelope_is_a_solid_within_tolerance
    marks = getattr(sweep, "pytestmark", [])
    assert "dimensional_sweep" in {mark.name for mark in marks}
    parametrize = next(mark for mark in marks if mark.name == "parametrize")
    assert parametrize.args[0].split(",")[0].strip() == "archetype"


# ── the deck box's own corners ─────────────────────────────────────────────────

COUNTS = deck_box.SWEEP_COUNTS
SLEEVINGS = deck_box.SWEEP_SLEEVINGS


def deck(count=100, sleeving="double", wall=2.8, clearance=0.2, lid_height=15.0, floor=2.0,
         fit_intent="snug", chamfer=None, radius=None, cavity_radius=None):
    """A deck box spec. `wall=None` states no wall and takes the archetype's default,
    which is what every spec that does not mention one compiles with (issue #72). The
    three edge treatments default to `None`, which likewise leaves `Process`'s own
    defaults — a 0,6 mm chamfer and a 1,0 mm corner round — in place, so what these
    corners sweep is the geometry a real spec gets rather than a square-cornered
    variant."""
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


def _wall_mm(wall):
    """The wall a swept case actually builds with; `None` is the archetype's default."""
    return ARCHETYPE_WALL_MM["deck_box"] if wall is None else wall


def test_the_deck_box_envelope_is_wide_enough_to_mean_something():
    """Guards the module's declared envelope against being quietly narrowed to the one
    example spec, and in particular against losing the unstated wall: `None` is what
    almost every real spec is, and it is the case a changed archetype default moves."""
    cases = envelope_for("deck_box")
    assert len(cases) >= 400
    assert min(COUNTS) < 20 and max(COUNTS) >= 150
    assert set(SLEEVINGS) == {"none", "single", "double"}
    assert None in deck_box.SWEEP_WALLS
    # The default is not also in the tuple as a number, so counting specs that carry it
    # counts the ones that stated no wall at all.
    default = ARCHETYPE_WALL_MM["deck_box"]
    assert default not in deck_box.SWEEP_WALLS
    assert len([c for c in cases if c.spec.process.wall_mm == default]) >= 90


# ── the wall: the archetype's default, and the nozzle's floor (issue #72) ──────
#
# The sweep carries the default as one of its `SWEEP_WALLS`, which proves the
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
# Its own corner rather than a sixth axis on the deck box's envelope: `fit_intent` moves
# exactly two lengths (the cavity's width and height, by 2,5 mm each) and is orthogonal
# to the wall, the lid and the clearance, so doubling 495 cases would buy repetition
# rather than coverage. What it must prove is that the wider cavity is *measured back*
# off the exported mesh, across the counts and sleevings that change the numbers around
# it.

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
# Its own corner rather than three more axes on the envelope, for `fit_intent`'s reason
# and one more. The reason: a chamfer and a corner round are orthogonal to the wall, the
# lid and the clearance, so multiplying 495 by 24 would buy repetition. The one more:
# unlike every other axis there, these two change the *kind* of surface the mesh carries
# — an arc where there was a plane, a 45° face where there was an edge — so what has to
# be swept is the span from "absent" to "as large as the rules allow", on both bodies,
# and through the export the rest of this file measures on.
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


# ── the card divider's own corners ─────────────────────────────────────────────

def divider(sleeving="double", thickness=1.4, tab_width=20.0, tab_height=10.0,
            position="centre", count=100):
    return OrganizerSpec(
        archetype="card_divider",
        compartments=(Compartment(CardStack(count=count, sleeving=sleeving)),),
        divider=Divider(thickness_mm=thickness, tab_width_mm=tab_width,
                        tab_height_mm=tab_height, tab_position=position),
    )


def test_the_divider_envelope_is_wide_enough_to_mean_something():
    """Guards the module's declared envelope against being quietly narrowed to the one
    example spec, and pins the three tab positions in particular — dropping `left` and
    `right` would remove the only cases where the tab's plane is the plate's, which is
    the case a union got wrong and an extruded outline does not."""
    assert len(envelope_for("card_divider")) >= 300
    assert set(card_divider.SWEEP_POSITIONS) == {"left", "centre", "right"}
    assert set(card_divider.SWEEP_SLEEVINGS) == {"none", "single", "double"}
    assert min(card_divider.SWEEP_THICKNESSES) <= 1.2
    assert max(card_divider.SWEEP_THICKNESSES) >= 2.0


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


# ── the token tray's own corners ───────────────────────────────────────────────
#
# The grid is what this archetype contributes to the generic sweep: it is the only
# parameter anywhere that changes how many features there are to measure rather than
# what they measure, which is why the sweep asserts `set(report.features) ==
# set(required_measurements(spec))` rather than containment. The two tests below are
# the ones a fixed feature tuple would have passed.


def token_tray_spec(rows, columns, pocket, wall, floor):
    return OrganizerSpec(
        archetype="token_tray",
        compartments=tuple(
            Compartment(Pocket(width_mm=pocket[0], depth_mm=pocket[1], height_mm=pocket[2]))
            for _ in range(rows * columns)
        ),
        tray=Tray(columns=columns),
        process=Process(wall_mm=wall, floor_mm=floor),
    )


def test_the_tray_envelope_is_wide_enough_to_mean_something():
    """Guards the module's declared envelope against being quietly narrowed to the one
    example spec: the unstated wall (what almost every real spec is), the 1 × 1 grid
    (the only one with no divider at all), a grid with more rows than columns and one
    with more columns than rows, and a pocket that is not square so a swapped W and D
    would show."""
    assert len(envelope_for("token_tray")) >= 120
    assert None in token_tray.SWEEP_WALLS
    assert (1, 1) in token_tray.SWEEP_GRIDS
    assert any(r > c for r, c in token_tray.SWEEP_GRIDS)
    assert any(c > r for r, c in token_tray.SWEEP_GRIDS)
    assert any(p[0] != p[1] for p in token_tray.SWEEP_POCKETS)
    assert len(set(token_tray.SWEEP_FLOORS)) == 2


@pytest.mark.parametrize("grid", token_tray.SWEEP_GRIDS)
def test_the_tray_sweep_measures_every_pocket_and_every_wall_in_the_grid(tmp_path, grid):
    """The count behind the sweep's `set(report.features) == required_measurements`:
    five fixed features, three per grid position, and one thickness per wall including
    the outer ones — `columns + 1` and `rows + 1`, which are not each other's mirror."""
    rows, columns = grid
    spec = token_tray_spec(rows, columns, (20.0, 20.0, 15.0), None, 2.0)
    result, mesh = exported_and_reloaded(spec, tmp_path / "tray.stl")
    report = verify_spec_mesh(spec, result.features, mesh)
    assert report.within_tolerance, report.problems()
    assert len(report.features) == 5 + 3 * rows * columns + (columns + 1) + (rows + 1)


def test_a_tray_scaled_by_a_fifth_of_a_percent_is_caught_and_a_pocket_named(tmp_path):
    """The check bites on the third archetype, and it bites *inside the grid*: a 20 mm
    pocket drifts 0,04 mm at 0,2 %, which is under the bound, so what catches this is
    the 66,4 mm external — and the report has to name a feature rather than shrug."""
    spec = token_tray_spec(2, 3, (20.0, 20.0, 15.0), None, 2.0)
    result, mesh = exported_and_reloaded(spec, tmp_path / "tray.stl")
    drifted = mesh.copy()
    drifted.apply_scale(1.002)
    report = verify_spec_mesh(spec, result.features, drifted)
    assert report.within_tolerance is False
    assert "external_width_mm" in report.out_of_tolerance
    assert report.max_abs_error_mm > TOL_MM


def test_a_single_pocket_out_of_position_is_caught_by_name(tmp_path):
    """What a fixed feature tuple would have missed. One divider moved 0,5 mm leaves
    every external and every outer wall exactly right, and is visible only because each
    grid position and each wall is measured on its own."""
    spec = token_tray_spec(1, 2, (20.0, 20.0, 15.0), 1.6, 2.0)
    result, _ = exported_and_reloaded(spec, tmp_path / "tray.stl")
    designed = dict(result.features)
    # Shift the divider: the left pocket gains what the right one loses, so the tray's
    # own outline is untouched and only the per-pocket figures move.
    designed["pocket_r0c0_width_mm"] += 0.5
    designed["pocket_r0c1_width_mm"] -= 0.5
    report = verify_spec_mesh(spec, designed, trimesh.load(str(tmp_path / "tray.stl"), force="mesh"))
    assert report.within_tolerance is False
    assert set(report.out_of_tolerance) == {"pocket_r0c0_width_mm", "pocket_r0c1_width_mm"}
    assert "external_width_mm" not in report.out_of_tolerance


def test_the_example_tray_has_sub_micron_error_on_the_exported_mesh(tmp_path):
    spec = token_tray_spec(2, 3, (20.0, 20.0, 15.0), None, 2.0)
    result, mesh = exported_and_reloaded(spec, tmp_path / "tray.stl")
    assert verify_spec_mesh(spec, result.features, mesh).max_abs_error_mm < 1e-4


# ── the box insert's own corners ───────────────────────────────────────────────
#
# What this archetype contributes is the **ragged layout**: the first shape in the
# registry whose features cannot be read off a global plane count at all, because a
# compartment shallower or shorter than its neighbour puts a plane where nothing else has
# one. Every feature is therefore measured inside the region the design says one
# compartment occupies, and the two things a region can get wrong are the two drift cases
# below: a well the right size in the wrong *place*, and a well the right place at the
# wrong *depth*. Both leave every external dimension exact, and a fixed feature tuple —
# or a plane count — would report *within tolerance* about either.


def box_insert_spec(rows, contents, wall=None, floor=2.0):
    """An insert from `(rows, contents)`, with `contents` in `box_insert.SWEEP_LAYOUTS`'
    own shape so a corner and an envelope case are written the same way."""
    return OrganizerSpec(
        archetype="box_insert",
        compartments=tuple(box_insert._compartment(c) for c in contents),
        insert=Insert(rows=tuple(rows)),
        process=Process(wall_mm=wall, floor_mm=floor),
    )


#: The example's layout, and the one every corner below is built on: a card well across
#: the front with two differently sized, differently deep pockets behind it.
MIXED_CONTENTS = (
    ("card", 60, "double"), ("pocket", 40.0, 40.0, 15.0), ("pocket", 20.0, 20.0, 18.0),
)


def test_the_insert_envelope_is_wide_enough_to_mean_something():
    """Guards the module's declared envelope against being narrowed to the one example.

    Five properties, each naming a failure it would hide: the unstated wall (what almost
    every real spec is); a layout with **one** compartment, which is the only one with no
    divider at all; rows of unequal width in *both* orders, so the slack lands in the back
    row in one case and the front row in the other; differing depths and heights inside a
    single row, which is the ragged case the token tray refuses outright; and at least two
    layouts mixing a resolved card footprint with typed pockets, which is the composition
    the archetype exists for.
    """
    cases = envelope_for("box_insert")
    assert len(cases) >= 150
    assert None in box_insert.SWEEP_WALLS
    layouts = {name: (rows, contents) for name, rows, contents in box_insert.SWEEP_LAYOUTS}
    assert any(sum(rows) == 1 for rows, _ in layouts.values())
    assert len(set(box_insert.SWEEP_FLOORS)) == 2
    assert (0.0, 0.0) in box_insert.SWEEP_EDGES, "no square-cornered case"

    def widths(rows, contents):
        """Each row's compartment count, and the footprints in it, row by row."""
        out, i = [], 0
        for n in rows:
            out.append(contents[i:i + n])
            i += n
        return out

    ragged_rows, ragged_within, mixed = 0, 0, 0
    for rows, contents in layouts.values():
        grouped = widths(rows, contents)
        sizes = [[c[1:] for c in row] for row in grouped]
        if len({len(row) for row in grouped}) > 1:
            ragged_rows += 1
        if any(len({s for s in row}) > 1 for row in sizes):
            ragged_within += 1
        kinds = {c[0] for c in contents}
        if kinds == {"card", "pocket"}:
            mixed += 1
    assert ragged_rows >= 2, "rows of unequal width are swept in only one order"
    assert ragged_within >= 2, "no row holds two differently sized compartments"
    assert mixed >= 2, "the card-and-pocket composition is swept once or not at all"


@pytest.mark.parametrize("rows,contents", [
    ((1,), (("pocket", 20.0, 20.0, 15.0),)),
    ((1, 2), MIXED_CONTENTS),
    ((3, 1), (("pocket", 15.0, 15.0, 10.0), ("pocket", 15.0, 15.0, 12.0),
              ("pocket", 15.0, 15.0, 14.0), ("pocket", 30.0, 20.0, 20.0))),
])
def test_the_insert_sweep_measures_every_compartment_and_every_wall(tmp_path, rows, contents):
    """The count behind the sweep's `set(report.features) == required_measurements`:
    seven fixed features, **five** per compartment — three sizes and two positions — one
    wall per row and one per row boundary."""
    spec = box_insert_spec(rows, contents)
    result, mesh = exported_and_reloaded(spec, tmp_path / "insert.stl")
    report = verify_spec_mesh(spec, result.features, mesh)
    assert report.within_tolerance, report.problems()
    assert len(report.features) == 7 + 5 * sum(rows) + len(rows) + (len(rows) + 1)


def test_a_compartment_out_of_position_is_caught_by_name(tmp_path):
    """What a plane count cannot see. A regular grid's dividers are shared planes, so
    moving one moves two pockets' widths; a ragged layout's are not, so a well shifted
    0,5 mm leaves every external, every wall and every *size* exactly right and shows up
    only because where each compartment is is a measured feature."""
    spec = box_insert_spec((1, 2), MIXED_CONTENTS)
    result, mesh = exported_and_reloaded(spec, tmp_path / "insert.stl")
    designed = dict(result.features)
    designed["c2_x_mm"] += 0.5
    report = verify_spec_mesh(spec, designed, mesh)
    assert report.within_tolerance is False
    assert set(report.out_of_tolerance) == {"c2_x_mm"}
    assert "external_width_mm" not in report.out_of_tolerance


def test_a_compartment_at_the_wrong_depth_is_caught_by_name(tmp_path):
    """Per-compartment depth is the feature `token_tray` deferred, and it is measured per
    compartment for the same reason: three wells give three floor planes, and a global Z
    read would see all three and be unable to say which one had moved."""
    spec = box_insert_spec((1, 2), MIXED_CONTENTS)
    result, mesh = exported_and_reloaded(spec, tmp_path / "insert.stl")
    designed = dict(result.features)
    designed["c1_height_mm"] -= 0.5
    report = verify_spec_mesh(spec, designed, mesh)
    assert report.within_tolerance is False
    assert set(report.out_of_tolerance) == {"c1_height_mm"}
    assert "external_height_mm" not in report.out_of_tolerance
    assert "floor_mm" not in report.out_of_tolerance


def test_an_insert_scaled_by_a_fifth_of_a_percent_is_caught_and_a_feature_named(tmp_path):
    """The check bites on the fourth archetype: a 0,2 % scale is 0,28 mm on the 138 mm
    depth, and the report names which feature moved rather than shrugging."""
    spec = box_insert_spec((1, 2), MIXED_CONTENTS)
    result, mesh = exported_and_reloaded(spec, tmp_path / "insert.stl")
    drifted = mesh.copy()
    drifted.apply_scale(1.002)
    report = verify_spec_mesh(spec, result.features, drifted)
    assert report.within_tolerance is False
    assert "external_depth_mm" in report.out_of_tolerance
    assert report.max_abs_error_mm > TOL_MM


def test_the_example_insert_has_sub_micron_error_on_the_exported_mesh(tmp_path):
    spec = box_insert_spec((1, 2), MIXED_CONTENTS)
    result, mesh = exported_and_reloaded(spec, tmp_path / "insert.stl")
    assert verify_spec_mesh(spec, result.features, mesh).max_abs_error_mm < 1e-4
