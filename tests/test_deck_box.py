"""The deck box archetype and the helpers every archetype shares.

The thesis of the pivot in one testable artifact: a spec compiles to a mesh whose
every designed dimension can be read back off the geometry — on the compiled mesh
*and* on what Phase 3 hands the slicer. Nothing here is asserted from the spec's
numbers alone; each feature is measured from the mesh's own planes and compared.
"""
import hashlib

import numpy as np
import pytest
import trimesh
import manifold3d

from pythonsrc.organizer.compiler import (
    MeasureError,
    assert_features_within,
    compare_features,
    manifold_to_trimesh,
    plane_set,
)


# ── helpers ────────────────────────────────────────────────────────────────────

def test_manifold_to_trimesh_keeps_the_kernels_vertices_untouched():
    box = manifold3d.Manifold.cube([70.0, 95.0, 100.0], False)
    mesh = manifold_to_trimesh(box)
    assert mesh.is_watertight
    assert mesh.extents == pytest.approx([70.0, 95.0, 100.0], abs=1e-6)
    assert mesh.volume == pytest.approx(70.0 * 95.0 * 100.0, rel=1e-9)


def test_manifold_to_trimesh_refuses_an_empty_solid():
    empty = manifold3d.Manifold.cube([1.0, 1.0, 1.0], False) - manifold3d.Manifold.cube([2.0, 2.0, 2.0], True)
    with pytest.raises(MeasureError):
        manifold_to_trimesh(empty)


def test_plane_set_clusters_float_noise_into_one_plane():
    coords = np.array([0.0, 70.89999, 70.90001, 70.9, 156.6, 156.6000061])
    assert plane_set(coords) == pytest.approx([0.0, 70.9, 156.6], abs=1e-4)


def test_plane_set_keeps_planes_a_micron_apart_distinct():
    assert len(plane_set(np.array([0.0, 0.002, 0.004]))) == 3


def test_compare_features_reports_designed_measured_and_error():
    out = compare_features({"a_mm": 10.0, "b_mm": 5.0}, {"a_mm": 10.01, "b_mm": 5.0})
    assert out["a_mm"] == pytest.approx((10.0, 10.01, 0.01))
    assert out["b_mm"] == (5.0, 5.0, 0.0)


def test_assert_features_within_names_every_feature_out_of_tolerance():
    with pytest.raises(MeasureError) as exc:
        assert_features_within({"a_mm": 10.0, "b_mm": 5.0}, {"a_mm": 10.2, "b_mm": 4.7}, tol_mm=0.05)
    assert "a_mm" in str(exc.value) and "b_mm" in str(exc.value)


def test_assert_features_within_refuses_a_missing_measurement():
    with pytest.raises(MeasureError):
        assert_features_within({"a_mm": 10.0}, {}, tol_mm=0.05)


from pythonsrc.organizer.spec import (  # noqa: E402
    ARCHETYPE_WALL_MM,
    CardStack,
    Compartment,
    Constraints,
    Divider,
    Lid,
    OrganizerSpec,
    Process,
    SpecError,
    canonical_json,
    wall_floor_mm,
)
from pythonsrc.organizer.archetypes import compile_spec, example_spec, get_archetype  # noqa: E402
from pythonsrc.organizer.archetypes import card_divider, deck_box  # noqa: E402


def deck(count=100, sleeving="double", **overrides):
    base = dict(
        archetype="deck_box",
        compartments=(Compartment(CardStack(count=count, sleeving=sleeving)),),
        lid=Lid(),
    )
    base.update(overrides)
    return OrganizerSpec(**base)


def bodies_on_plate(mesh):
    parts = mesh.split(only_watertight=False)
    return parts, all(abs(p.bounds[0][2]) < 1e-6 for p in parts)


# ── derive: the arithmetic the geometry is built from ──────────────────────────

def test_a_hundred_double_sleeved_cards_derive_the_expected_box():
    d = deck_box.derive(deck())
    assert d.cavity_w == pytest.approx(67.0 + 1.5)
    assert d.cavity_d == pytest.approx(100 * 0.70 + 1.0)
    assert d.cavity_h == pytest.approx(92.0 + 1.5)
    assert d.external_w == pytest.approx(68.5 + 2 * 2.4)
    assert d.external_d == pytest.approx(71.0 + 2 * 2.4)
    assert d.body_h == pytest.approx(93.5 + 2.0)
    assert d.lip_inset == pytest.approx(1.2 + 0.2)
    # 2,4 mm of wall less a 1,4 mm lip inset is a 1,0 mm lip — exactly
    # `process.min_feature_mm`, which is where the default came from (issue #72).
    assert d.lip_wall == pytest.approx(2.4 - 1.4)
    assert d.lid_cavity_w == pytest.approx(d.lip_outer_w + 2 * 0.2)
    assert d.external_h == pytest.approx(d.body_h + 2.0)


def test_an_easy_fit_widens_the_cavity_by_the_sourced_figure_on_both_axes():
    """`docs/dimension-kb-research.md` §3's easy-in/out convention, applied where a
    clearance applies: the cavity's width and height, not its depth (the stack has its
    own `stack_slack_mm`) and not the wall."""
    d = deck_box.derive(deck(process=Process(fit_intent="easy")))
    assert d.cavity_w == pytest.approx(67.0 + 4.0)
    assert d.cavity_h == pytest.approx(92.0 + 4.0)
    assert d.cavity_d == pytest.approx(100 * 0.70 + 1.0)
    snug = deck_box.derive(deck())
    assert d.external_w - snug.external_w == pytest.approx(2.5)
    assert d.external_h - snug.external_h == pytest.approx(2.5)


def test_an_easy_deck_box_compiles_and_measures_back_to_its_wider_cavity():
    """A loose deck box is a valid request, not a refusal — and the mesh carries it."""
    spec = deck(process=Process(fit_intent="easy"))
    result = compile_spec(spec)
    measured = measure_spec_mesh(spec, result.mesh)
    assert measured["cavity_width_mm"] == pytest.approx(71.0, abs=1e-4)
    assert measured["cavity_height_mm"] == pytest.approx(96.0, abs=1e-4)
    assert_features_within(result.features, measured, TOL_MM,
                           required=set(deck_box.MEASURED_FEATURES))


# ── archetype-level refusals, with the reason ──────────────────────────────────

def test_a_second_compartment_is_refused_by_name():
    spec = deck(compartments=(Compartment(CardStack(60)), Compartment(CardStack(40))))
    with pytest.raises(SpecError) as exc:
        compile_spec(spec)
    assert "one compartment" in str(exc.value)


def test_magnets_are_refused_not_ignored():
    with pytest.raises(SpecError) as exc:
        compile_spec(deck(lid=Lid(magnets=True)))
    assert "magnet" in str(exc.value)


def test_a_divider_section_is_refused_rather_than_ignored():
    """A section belonging to another archetype is a spec asking for a different part.
    Ignoring it would print a deck box for someone who asked for a plate."""
    from pythonsrc.organizer.spec import Divider
    with pytest.raises(SpecError) as exc:
        compile_spec(deck(divider=Divider()))
    assert "divider" in str(exc.value) and "card_divider" in str(exc.value)


def test_a_missing_lid_is_refused():
    with pytest.raises(SpecError) as exc:
        compile_spec(deck(lid=None))
    assert "lid" in str(exc.value)


def test_a_lip_thinner_than_the_minimum_feature_is_refused_with_the_remedy():
    """wall 2.4 − lid wall 1.2 − clearance 0.2 = 1.0 lip; a 1.2 mm minimum refuses it."""
    spec = deck(process=Process(wall_mm=2.4, min_feature_mm=1.2))
    with pytest.raises(SpecError) as exc:
        compile_spec(spec)
    message = str(exc.value)
    assert "lip" in message and "1.000" in message and "wall" in message


# ── the wall: the archetype's default, and the nozzle's floor (issue #72) ──────

def test_the_deck_boxs_default_wall_is_the_lids_own_arithmetic():
    """2,4 mm is not a taste figure: it is lid wall + lid clearance + minimum feature,
    the thinnest body wall that still leaves this archetype's own lift-off lid a valid
    lip. Bound to the numbers it is derived from, so changing `Lid`'s defaults without
    changing the wall fails here rather than producing a default that cannot compile."""
    assert ARCHETYPE_WALL_MM["deck_box"] == pytest.approx(
        Lid().wall_mm + Lid().clearance_mm + Process().min_feature_mm
    )
    assert ARCHETYPE_WALL_MM["deck_box"] > wall_floor_mm()


def test_a_spec_that_states_no_wall_builds_with_the_archetypes_default():
    """The canonical form carries it — the spec says what the geometry has — and the
    mesh is measured to prove the default reached the kernel, not just the dataclass."""
    spec = deck()
    assert spec.process.wall_mm == ARCHETYPE_WALL_MM["deck_box"]
    assert '"wall_mm":2.4' in canonical_json(spec)
    measured = measure_spec_mesh(spec, compile_spec(spec).mesh)
    assert measured["wall_mm"] == pytest.approx(2.4, abs=TOL_MM)


def test_an_explicit_null_wall_means_the_same_as_an_omitted_one():
    """`from_dict` must not treat "I wrote null" as different from "I wrote nothing",
    or two spec files that mean the same thing would hash differently."""
    d = deck().to_dict()
    d["process"]["wall_mm"] = None
    assert OrganizerSpec.from_dict(d) == deck()


def test_a_wall_below_the_nozzles_floor_is_refused_with_the_floor_and_the_nozzle():
    """1,2 mm is three perimeters at 0,4 and fine there; on a 0,6 mm nozzle it is two,
    and the refusal has to say which machine said so and what the limit was.

    The thin lid is what makes a 1,2 mm body wall a legal deck box at all — the lip
    has to fit inside it — so the only thing this spec is refused for is the floor."""
    thin = dict(lid=Lid(wall_mm=0.8, clearance_mm=0.1),
                process=Process(wall_mm=1.2, min_feature_mm=0.1))
    spec = deck(**thin)
    compile_spec(spec, nozzle_diameter_mm=0.4)  # three perimeters: allowed
    with pytest.raises(SpecError) as exc:
        compile_spec(spec, nozzle_diameter_mm=0.6)
    message = str(exc.value)
    assert "process.wall_mm 1.2" in message
    assert "1.8 mm wall floor" in message and "0.6 mm nozzle" in message
    assert exc.value.problems == [p for p in exc.value.problems if "wall floor" in p]


def test_the_floor_is_refused_together_with_the_archetypes_own_problems():
    """"It is refused whole" is a property of this schema, and a floor bolted on in
    front of the archetype would have broken it: the wall is too thin *and* the lid is
    taller than the cavity, and one attempt must report both."""
    spec = deck(process=Process(wall_mm=1.0, min_feature_mm=0.1),
                lid=Lid(height_mm=500.0, wall_mm=0.8, clearance_mm=0.1))
    with pytest.raises(SpecError) as exc:
        compile_spec(spec, nozzle_diameter_mm=0.4)
    assert any("wall floor" in p for p in exc.value.problems)
    assert any("height_mm" in p for p in exc.value.problems)


def test_the_divider_is_not_held_to_a_wall_it_does_not_build():
    """`process.wall_mm` builds nothing on a card divider, so a big nozzle must not
    refuse a perfectly good plate over it — the plate's own thickness is the feature
    that matters and `divider.thickness_mm` carries it."""
    assert deck_box.USES_PROCESS_WALL_MM is True
    assert card_divider.USES_PROCESS_WALL_MM is False
    spec = OrganizerSpec(
        archetype="card_divider",
        compartments=(Compartment(CardStack(count=100)),),
        divider=Divider(),
    )
    assert spec.process.wall_mm == ARCHETYPE_WALL_MM["card_divider"]
    assert compile_spec(spec, nozzle_diameter_mm=0.8).mesh.is_watertight


def test_a_lid_taller_than_the_cavity_is_refused():
    with pytest.raises(SpecError) as exc:
        compile_spec(deck(lid=Lid(height_mm=200.0)))
    assert "height_mm" in str(exc.value)


def test_an_easy_fit_that_busts_a_stated_limit_is_refused_with_both_remedies():
    """The 2,5 mm an `easy` intent adds is a number nobody typed. It may make a box
    loose; it may not silently make a box that does not fit the limit its spec names."""
    exact = (73.3, 75.8, 97.5)  # the snug example's own externals
    spec = deck(process=Process(fit_intent="easy"),
                constraints=Constraints(max_external_mm=exact, fit_margin_mm=0))
    with pytest.raises(SpecError) as exc:
        compile_spec(spec)
    message = str(exc.value)
    assert "fit_intent 'easy'" in message and "4 mm of clearance" in message
    assert "external width 75.8 mm exceeds 73.3 mm" in message
    assert "'snug'" in message and "cavity_clearance_mm" in message and "max_external_mm" in message


def test_an_easy_fit_inside_its_limit_compiles():
    spec = deck(process=Process(fit_intent="easy"),
                constraints=Constraints(max_external_mm=(90.0, 90.0, 110.0)))
    assert compile_spec(spec).mesh.is_watertight


def test_an_easy_fit_with_no_stated_limit_compiles():
    """There is nothing for the wider cavity to bust, so there is nothing to refuse."""
    assert compile_spec(deck(process=Process(fit_intent="easy"))).mesh.is_watertight


def test_an_explicit_clearance_is_never_refused_for_the_intent_beside_it():
    """The refusal is about millimetres the schema chose. `cavity_clearance_mm: 1,5`
    with `fit_intent: easy` is a contradiction in words only — the number is the
    person's, the geometry is snug, and it fits."""
    exact = (73.3, 75.8, 97.5)
    spec = deck(process=Process(fit_intent="easy", cavity_clearance_mm=1.5),
                constraints=Constraints(max_external_mm=exact, fit_margin_mm=0))
    assert compile_spec(spec).mesh.is_watertight


def test_a_snug_overshoot_is_still_reported_rather_than_refused():
    """The asymmetry is deliberate: `snug` is what every deck box here was built with,
    and `fits_check` already names the axis and the card count that would fit. Turning
    that report into a refusal would take a spec the UI can show a verdict for and make
    it uncompilable."""
    spec = deck(constraints=Constraints(max_external_mm=(80.0, 70.0, 100.0)))
    assert compile_spec(spec).mesh.is_watertight
    assert fits_for(spec).fits is False


def test_an_unknown_archetype_name_is_refused_by_the_registry():
    with pytest.raises(SpecError):
        get_archetype("dragon")


# ── compile: the plate ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("count", [40, 60, 100])
@pytest.mark.parametrize("sleeving", ["none", "single", "double"])
def test_the_plate_is_two_watertight_bodies_both_on_the_bed(count, sleeving):
    result = compile_spec(deck(count=count, sleeving=sleeving))
    assert result.mesh.is_watertight
    parts, grounded = bodies_on_plate(result.mesh)
    assert len(parts) == 2 and grounded
    assert set(result.parts) == {"body", "lid"}
    assert result.parts["body"].is_watertight and result.parts["lid"].is_watertight


def test_the_body_and_lid_do_not_overlap_on_the_plate():
    result = compile_spec(deck())
    body, lid = result.parts["body"], result.parts["lid"]
    assert lid.bounds[0][0] >= body.bounds[1][0] + deck_box.PLATE_GAP_MM - 1e-6


def test_the_result_carries_the_designed_features_and_the_spec_hash():
    from pythonsrc.organizer.spec import spec_hash
    spec = deck()
    result = compile_spec(spec)
    assert result.archetype == "deck_box" and result.archetype_version == "2"
    assert result.spec_hash == spec_hash(spec)
    for key in ("cavity_width_mm", "cavity_depth_mm", "cavity_height_mm",
                "external_width_mm", "external_depth_mm", "external_height_mm",
                "lip_wall_mm", "lid_clearance_mm", "stack_height_mm"):
        assert key in result.features
    doc = result.features_document()
    assert doc["parts"] == ["body", "lid"] and doc["spec_sha256"] == result.spec_hash


def test_the_same_spec_exports_the_same_bytes(tmp_path):
    """Frozen source, deterministic kernel: the STL is reproducible byte for byte."""
    from pythonsrc.organizer.compiler import export_stl
    a = export_stl(compile_spec(deck()).mesh, tmp_path / "a.stl").read_bytes()
    b = export_stl(compile_spec(deck()).mesh, tmp_path / "b.stl").read_bytes()
    assert hashlib.sha256(a).hexdigest() == hashlib.sha256(b).hexdigest()


def test_a_spec_that_states_every_default_exports_the_bytes_it_always_has(tmp_path):
    """A fixed vector for the *mesh* of a spec that says what it wants.

    This hash is the one the example deck box carried before issue #72, and the spec
    that produces it is the example plus `process.wall_mm: 2.8` — the number that used
    to be the schema's default — and, since issue #80, the three edge treatments stated
    at zero. **A spec that states what it wants compiles to the byte it always did**,
    which is the compatibility claim of every default this schema has retired or added:
    `rounded_rect_prism(…, 0)` is `Manifold.cube` vertex for vertex and a zero chamfer
    is the plain prism, so a square-cornered deck box runs the code path it always ran.
    Only specs that never said anything move.

    If this hash changes, either the kernel's output changed or something other than a
    default did, and both are answers somebody has to give deliberately.
    """
    from pythonsrc.organizer.compiler import export_stl
    spec = deck(process=Process(
        wall_mm=2.8, base_chamfer_mm=0.0, corner_radius_mm=0.0, cavity_corner_radius_mm=0.0,
    ))
    stl = export_stl(compile_spec(spec).mesh, tmp_path / "a.stl")
    assert hashlib.sha256(stl.read_bytes()).hexdigest() == (
        "c638fddc0d98f8823157ec99cd767be66ec30078ffb2be149072ef12eb4de785"
    )


def test_the_example_deck_box_exports_the_bytes_its_own_defaults_build(tmp_path):
    """The same fixed vector for the example as it stands: no wall and no edge
    treatments stated, so `spec.ARCHETYPE_WALL_MM["deck_box"]` — 2,4 mm — and
    `Process`'s own 0,6 mm chamfer and 1,0 mm corner round build it.

    It has moved twice. At issue #72, when the unsourced 2,8 mm wall default was
    replaced by the lid's own arithmetic; and at issue #80, when the edge treatments
    the audited insert standard calls mandatory became defaults. The test above keeps
    the old geometry reachable by naming every number it is built from, and the
    features are asserted below rather than only hashed — a byte pin says a mesh
    changed, not that it is the right one.
    """
    from pythonsrc.organizer.compiler import export_stl
    spec = example_spec("deck_box")
    result = compile_spec(spec)
    assert_features_within(
        result.features, measure_spec_mesh(spec, result.mesh), TOL_MM,
        required=set(deck_box.MEASURED_FEATURES),
    )
    stl = export_stl(result.mesh, tmp_path / "a.stl")
    assert hashlib.sha256(stl.read_bytes()).hexdigest() == (
        "4097c70c553c221e26818b7b4bb10b11e0524ded4ffa87a4756e0bb3b806c3a6"
    )


def test_the_example_spec_compiles():
    spec = example_spec("deck_box")
    assert spec.compartments[0].contents.count == 100
    assert compile_spec(spec).mesh.is_watertight


from pythonsrc.engineer import Engineer  # noqa: E402
from pythonsrc.organizer.archetypes import fits_for, measure_spec_mesh, view_for  # noqa: E402
from pythonsrc.organizer.compiler import export_stl  # noqa: E402
from pythonsrc.printability import ProcessProfile, evaluate_printability  # noqa: E402

TOL_MM = 0.05  # PRD N1: internal dimensions exact to spec within ≤ ±0,05 mm


# ── measure: designed features read back off the geometry ──────────────────────

@pytest.mark.parametrize("count", [40, 60, 100])
@pytest.mark.parametrize("sleeving", ["none", "single", "double"])
def test_every_designed_feature_is_on_the_compiled_mesh(count, sleeving):
    spec = deck(count=count, sleeving=sleeving)
    result = compile_spec(spec)
    measured = measure_spec_mesh(spec, result.mesh)
    assert_features_within(result.features, measured, TOL_MM, required=set(deck_box.MEASURED_FEATURES))


def test_the_lid_clears_the_lip_by_exactly_the_clearance():
    """The wall is stated because the default cannot take this clearance: 2,4 mm is
    exactly lid wall + clearance + `min_feature_mm` at the *default* 0,2 mm, so a
    0,25 mm clearance needs 0,05 mm more wall and `validate` says so."""
    spec = deck(lid=Lid(clearance_mm=0.25), process=Process(wall_mm=2.8))
    measured = measure_spec_mesh(spec, compile_spec(spec).mesh)
    assert measured["lid_clearance_mm"] == pytest.approx(0.25, abs=1e-4)


def test_measure_refuses_a_mesh_that_is_not_a_deck_box():
    with pytest.raises(MeasureError):
        deck_box.measure(trimesh.creation.box(extents=[10, 10, 10]))


def test_phase_3_hands_the_slicer_the_dimensions_that_were_designed(tmp_path):
    """The seam the roadmap names: --skip-visualizer --skip-sculptor --mesh --no-scale.
    Repair runs; scaling does not; every feature survives within tolerance."""
    spec = deck()
    result = compile_spec(spec)
    raw = export_stl(result.mesh, tmp_path / "compiled_mesh.stl")
    eng = Engineer()
    out = eng.process(input_path=raw, output_path=tmp_path / "engineered.obj", target_mm=None)
    engineered = trimesh.load(str(out), force="mesh")
    measured = measure_spec_mesh(spec, engineered)
    assert_features_within(result.features, measured, TOL_MM, required=set(deck_box.MEASURED_FEATURES))
    assert eng.last_report["scale_applied"] is False
    assert eng.last_report["scale_axis"] == "preserved"
    assert eng.last_report.get("faces_dropped", 0) == 0


def test_the_gate_does_not_fail_the_deck_box(tmp_path):
    spec = deck()
    result = compile_spec(spec)
    raw = export_stl(result.mesh, tmp_path / "compiled_mesh.stl")
    out = Engineer().process(input_path=raw, output_path=tmp_path / "engineered.obj", target_mm=None)
    report = evaluate_printability(
        trimesh.load(str(out), force="mesh"),
        ProcessProfile(build_volume_mm=[220.0, 220.0, 250.0]),
        expected_components=len(result.parts),
    )
    by_name = {c.check: c for c in report.checks}
    assert not any(c.status == "fail" for c in report.checks), [(c.check, c.detail) for c in report.checks if c.status == "fail"]
    assert by_name["floating_components"].status == "pass"
    assert by_name["watertight"].status == "pass"
    assert report.verdict != "unprintable"


# ── the edge treatments (issue #80) ────────────────────────────────────────────

def test_the_defaults_put_a_chamfer_and_a_corner_round_on_the_compiled_mesh():
    """Not "the spec says 0,6" — the mesh has a 0,6 mm 45° chamfer and a 1,0 mm corner,
    on both bodies, read off the geometry."""
    spec = deck()
    result = compile_spec(spec)
    assert result.features["base_chamfer_mm"] == 0.6
    assert result.features["corner_radius_mm"] == 1.0
    measured = measure_spec_mesh(spec, result.mesh)
    for name in ("base_chamfer_mm", "lid_base_chamfer_mm"):
        assert measured[name] == pytest.approx(0.6, abs=1e-4), name
    for name in ("corner_radius_mm", "lid_corner_radius_mm"):
        assert measured[name] == pytest.approx(1.0, abs=1e-4), name
    # And the closure stays square-cornered at the defaults: 1,0 mm is under the
    # 1,4 mm lip inset, so both derived radii clamp to 0.
    assert result.features["lip_corner_radius_mm"] == 0.0
    assert result.features["lid_cavity_corner_radius_mm"] == 0.0


def test_the_derived_radii_keep_the_lid_clearance_exact_around_the_corner():
    """A radius wider than the lip inset rounds the closure too, and the arcs share the
    external corner's centre — so the gap between the lip and the lid cavity is
    `lid.clearance_mm` at the corner exactly as it is along the side."""
    spec = deck(process=Process(wall_mm=4.0, corner_radius_mm=2.4))
    result = compile_spec(spec)
    assert result.features["lip_corner_radius_mm"] == pytest.approx(2.4 - 1.4, abs=1e-9)
    assert result.features["lid_cavity_corner_radius_mm"] == pytest.approx(2.4 - 1.2, abs=1e-9)
    measured = measure_spec_mesh(spec, result.mesh)
    assert_features_within(result.features, measured, TOL_MM,
                           required=set(deck_box.MEASURED_FEATURES))
    assert measured["lid_clearance_mm"] == pytest.approx(0.2, abs=1e-4)


def test_an_internal_round_reaches_the_cavity_wall():
    spec = deck(process=Process(cavity_corner_radius_mm=0.75))
    result = compile_spec(spec)
    measured = measure_spec_mesh(spec, result.mesh)
    assert measured["cavity_corner_radius_mm"] == pytest.approx(0.75, abs=1e-4)
    assert_features_within(result.features, measured, TOL_MM,
                           required=set(deck_box.MEASURED_FEATURES))


def test_a_spec_that_zeroes_the_edge_treatments_measures_them_as_zero():
    """The other end of the range, and the one that keeps the pre-#80 geometry
    reachable: no chamfer, square corners, and `measure` says so rather than failing to
    find a feature."""
    spec = deck(process=Process(
        base_chamfer_mm=0.0, corner_radius_mm=0.0, cavity_corner_radius_mm=0.0))
    result = compile_spec(spec)
    measured = measure_spec_mesh(spec, result.mesh)
    assert measured["base_chamfer_mm"] == 0.0 and measured["corner_radius_mm"] == 0.0
    assert_features_within(result.features, measured, TOL_MM,
                           required=set(deck_box.MEASURED_FEATURES))


def test_the_edge_measurements_bite_when_the_mesh_does_not_match_the_design():
    """A check that cannot fail is not a check. Measure a square-cornered, unchamfered
    mesh against a design that asks for both, and the two features are named."""
    designed = compile_spec(deck()).features
    plain = deck(process=Process(
        base_chamfer_mm=0.0, corner_radius_mm=0.0, cavity_corner_radius_mm=0.0))
    measured = measure_spec_mesh(plain, compile_spec(plain).mesh)
    with pytest.raises(MeasureError) as exc:
        assert_features_within(designed, measured, TOL_MM,
                               required=set(deck_box.MEASURED_FEATURES))
    for name in ("base_chamfer_mm", "lid_base_chamfer_mm",
                 "corner_radius_mm", "lid_corner_radius_mm"):
        assert name in str(exc.value), name


def test_a_corner_round_wider_than_the_wall_is_refused_with_the_wall_it_would_leave():
    with pytest.raises(SpecError) as exc:
        compile_spec(deck(process=Process(corner_radius_mm=3.0)))
    message = "; ".join(exc.value.problems)
    assert "process.corner_radius_mm 3 mm is larger than process.wall_mm 2.4" in message
    assert "thin the wall to" in message and "thicken the wall" in message


@pytest.mark.parametrize(
    "process, lid_kwargs, names",
    [
        (Process(base_chamfer_mm=2.0), {}, ["process.floor_mm 2", "lid.top_mm 2"]),
        (Process(base_chamfer_mm=1.5, floor_mm=3.0), {"top_mm": 1.0}, ["lid.top_mm 1"]),
    ],
)
def test_a_chamfer_that_would_cut_into_a_cavity_is_refused(process, lid_kwargs, names):
    with pytest.raises(SpecError) as exc:
        compile_spec(deck(process=process, lid=Lid(**lid_kwargs)))
    message = "; ".join(exc.value.problems)
    for name in names:
        assert name in message, message
    assert "cuts into the cavity above it" in message


def test_an_internal_round_that_intrudes_on_the_contents_is_refused():
    """`ρ·(√2 − 1)` back along the diagonal against the `cc·√2/2` the clearance leaves
    there: at the default 1,5 mm clearance the ceiling is 2,56 mm."""
    assert compile_spec(deck(process=Process(cavity_corner_radius_mm=2.5))).mesh.is_watertight
    with pytest.raises(SpecError) as exc:
        compile_spec(deck(process=Process(cavity_corner_radius_mm=3.0)))
    message = "; ".join(exc.value.problems)
    assert "process.cavity_corner_radius_mm 3 mm sets the cavity's corner" in message
    assert "process.cavity_clearance_mm 1.5 mm leaves there" in message


def test_a_chamfered_plate_survives_the_export_as_two_watertight_bodies(tmp_path):
    """The regression `base_chamfer`'s docstring is about. A chamfer generated by any
    boolean leaves zero-area triangles along the seam; float32 merges their corners on
    export, and the plate comes back with non-manifold edges and 45 loose bodies. The
    compiled mesh being watertight does not catch it — only the round trip does."""
    spec = deck()
    plate = compile_spec(spec).mesh
    assert (plate.area_faces < 1e-9).sum() == 0
    reloaded = trimesh.load(str(export_stl(plate, tmp_path / "plate.stl")))
    assert reloaded.is_watertight
    assert len(reloaded.split(only_watertight=False)) == 2


def test_the_chamfer_is_measured_off_phase_3s_output_too(tmp_path):
    """Assert mode does not decimate, and `orient_for_print` re-centres in X and Y —
    both features here are differences, so both survive."""
    spec = deck(process=Process(corner_radius_mm=2.0, cavity_corner_radius_mm=0.75))
    result = compile_spec(spec)
    raw = export_stl(result.mesh, tmp_path / "compiled_mesh.stl")
    eng = Engineer()
    out = eng.process(input_path=raw, output_path=tmp_path / "engineered.obj", target_mm=None)
    measured = measure_spec_mesh(spec, trimesh.load(str(out), force="mesh"))
    assert_features_within(result.features, measured, TOL_MM,
                           required=set(deck_box.MEASURED_FEATURES))
    assert eng.last_report.get("faces_dropped", 0) == 0


def test_a_sloping_face_that_is_not_45_degrees_is_a_finding_not_a_height():
    """`measure` reads the chamfer's *angle* off the mesh rather than trusting it. A
    face at 30° would otherwise report a plausible height for a part nobody designed —
    so a body with one is refused, and one with a real chamfer measures it."""
    from pythonsrc.organizer.compiler import manifold_to_trimesh, rounded_rect_prism

    chamfered = manifold_to_trimesh(rounded_rect_prism(60.0, 40.0, 20.0, 1.0, chamfer_mm=0.6))
    assert deck_box._chamfer(chamfered, "body") == pytest.approx(0.6, abs=1e-4)

    wedge = manifold_to_trimesh(
        rounded_rect_prism(60.0, 40.0, 20.0).rotate([0.0, 30.0, 0.0])
    )
    with pytest.raises(MeasureError) as exc:
        deck_box._chamfer(wedge, "body")
    assert "the body's base chamfer is" in str(exc.value)
    assert "where a deck box v2 cuts 45°" in str(exc.value)


def test_the_view_names_the_edge_treatments_and_says_they_are_unsourced():
    view = view_for(deck(), compile_spec(deck()))
    rows = {d["key"]: d for d in view["dimensions"]}
    assert rows["base_chamfer_mm"]["value"] == 0.6
    assert "45°" in rows["base_chamfer_mm"]["note"]
    assert "design default, unsourced" in rows["base_chamfer_mm"]["note"]
    assert "design default, unsourced" in rows["corner_radius_mm"]["note"]
    assert rows["cavity_corner_radius_mm"]["value"] == 0.0
    assert all(rows[k]["editable"] for k in
               ("base_chamfer_mm", "corner_radius_mm", "cavity_corner_radius_mm"))


def test_the_chamfered_deck_box_still_passes_the_printability_gate(tmp_path):
    """A 45° face counts as an overhang by `printability`'s own inclusive threshold, so
    the chamfer adds overhang area by definition. It has to stay a rounding error
    against the warn threshold, and the gate has to stay free of failures."""
    spec = deck()
    result = compile_spec(spec)
    raw = export_stl(result.mesh, tmp_path / "compiled_mesh.stl")
    out = Engineer().process(input_path=raw, output_path=tmp_path / "engineered.obj", target_mm=None)
    report = evaluate_printability(
        trimesh.load(str(out), force="mesh"),
        ProcessProfile(build_volume_mm=[220.0, 220.0, 250.0]),
        expected_components=len(result.parts),
    )
    by_name = {c.check: c for c in report.checks}
    assert not any(c.status == "fail" for c in report.checks), [
        (c.check, c.detail) for c in report.checks if c.status == "fail"]
    assert by_name["overhang_area"].status == "pass", by_name["overhang_area"].detail
    assert report.verdict != "unprintable"


# ── fits check and the UI view ─────────────────────────────────────────────────

def test_the_fits_line_shows_the_arithmetic():
    fits = fits_for(deck())
    assert fits.fits is True
    assert fits.line.startswith("100 × 0.7 mm = 70 mm stack")
    assert "internal 71 mm" in fits.line
    assert "external 73.3 × 75.8 × 97.5 mm" in fits.line
    assert "0.70 mm/card" in fits.basis
    assert fits.remedy is None


def test_an_external_constraint_that_fails_names_the_axis_and_a_card_count():
    spec = deck(constraints=Constraints(max_external_mm=(80.0, 70.0, 100.0)))
    fits = fits_for(spec)
    assert fits.fits is False
    assert "depth" in fits.remedy and "75.8" in fits.remedy and "68" in fits.remedy
    # (70 − 2 margin − 2·2.4 − 1.0) / 0.70 = 88.86 → 88 cards. Derived from the
    # *effective* limit, or the remedy names a count that busts the margin again.
    assert "88 cards" in fits.remedy


def test_an_external_constraint_that_holds_passes():
    spec = deck(constraints=Constraints(max_external_mm=(80.0, 80.0, 100.0)))
    assert fits_for(spec).fits is True


# ── the −2 mm safety margin (issue #70) ────────────────────────────────────────

def test_the_default_margin_refuses_a_box_that_fitted_the_stated_limit_exactly():
    """The whole point: a box internal is one person's measurement of one copy, and
    the same copy next door is 1–2 mm smaller. 75,8 mm of depth "fits" a 75,8 mm
    limit and splits the box; against the effective 73,8 mm it does not fit, and the
    remedy says where the two millimetres came from."""
    exact = (73.3, 75.8, 97.5)  # the example deck box's own external dimensions
    fits = fits_for(deck(constraints=Constraints(max_external_mm=exact)))
    assert fits.fits is False
    assert "external width 73.3 mm exceeds 71.3 mm (max_external 73.3 − 2 margin)" in fits.remedy
    assert "external depth 75.8 mm exceeds 73.8 mm (max_external 75.8 − 2 margin)" in fits.remedy
    assert "external height 97.5 mm exceeds 95.5 mm (max_external 97.5 − 2 margin)" in fits.remedy


def test_a_zero_margin_restores_the_old_comparison_and_the_old_sentence():
    """`fit_margin_mm: 0` is for a person who measured the box they are filling. It
    must read exactly as this project read before the margin existed — no
    parenthetical explaining an arithmetic that did not happen."""
    exact = (73.3, 75.8, 97.5)
    spec = deck(constraints=Constraints(max_external_mm=exact, fit_margin_mm=0))
    assert fits_for(spec).fits is True
    over = deck(constraints=Constraints(max_external_mm=(80.0, 70.0, 100.0), fit_margin_mm=0))
    fits = fits_for(over)
    assert fits.fits is False
    assert fits.remedy == (
        "external depth 75.8 mm exceeds 70 mm by 5.8 mm; "
        "91 cards would fit the depth limit. "
        "Reduce the card count, the wall or the slack, or relax the constraint."
    )


def test_the_margin_does_nothing_without_a_stated_limit():
    """A spec with no `max_external_mm` has nothing to subtract from, so the margin
    must not invent a limit — a deck box with no constraint fits by construction."""
    assert fits_for(deck(constraints=Constraints(fit_margin_mm=2.0))).fits is True


def test_the_view_has_the_shape_the_ui_declares():
    spec = deck()
    result = compile_spec(spec)
    view = view_for(spec, result)
    assert view["archetype"] == "deck_box"
    assert view["archetypeVersion"] == "v2"
    assert view["hash"] == result.spec_hash
    assert view["fits"]["fits"] is True and "stack" in view["fits"]["line"]
    keys = [d["key"] for d in view["dimensions"]]
    assert keys[0] == "card_count"
    for row in view["dimensions"]:
        assert set(row) >= {"key", "label", "value", "unit", "editable"}
        assert isinstance(row["value"], (int, float)) and isinstance(row["editable"], bool)
    editable = {d["key"] for d in view["dimensions"] if d["editable"]}
    derived = {d["key"] for d in view["dimensions"] if not d["editable"]}
    assert {"card_count", "wall_mm", "lid_clearance_mm"} <= editable
    assert {"stack_height_mm", "cavity_depth_mm", "external_height_mm"} <= derived
    pitch = next(d for d in view["dimensions"] if d["key"] == "pitch_mm")
    assert "0.70 mm/card" in pitch["note"]


def test_the_view_says_which_fit_intent_chose_the_clearance():
    """`fit_intent` is a word and a `SpecDimension` value is a number, so it rides as
    the note of the row it decides — the same way the divider's tab position does. A
    clearance shown with no hint of where it came from is a number on screen nobody
    can trace."""
    def clearance_note(spec):
        view = view_for(spec, compile_spec(spec))
        return next(d for d in view["dimensions"] if d["key"] == "cavity_clearance_mm")

    snug = clearance_note(deck())
    assert snug["value"] == 1.5 and "snug fit" in snug["note"]
    easy = clearance_note(deck(process=Process(fit_intent="easy")))
    assert easy["value"] == 4.0 and "easy fit" in easy["note"]
