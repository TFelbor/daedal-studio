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


from pythonsrc.organizer.spec import CardStack, Compartment, Constraints, Lid, OrganizerSpec, Process, SpecError  # noqa: E402
from pythonsrc.organizer.archetypes import compile_spec, example_spec, get_archetype  # noqa: E402
from pythonsrc.organizer.archetypes import deck_box  # noqa: E402


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
    assert d.external_w == pytest.approx(68.5 + 2 * 2.8)
    assert d.external_d == pytest.approx(71.0 + 2 * 2.8)
    assert d.body_h == pytest.approx(93.5 + 2.0)
    assert d.lip_inset == pytest.approx(1.2 + 0.2)
    assert d.lip_wall == pytest.approx(2.8 - 1.4)
    assert d.lid_cavity_w == pytest.approx(d.lip_outer_w + 2 * 0.2)
    assert d.external_h == pytest.approx(d.body_h + 2.0)


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


def test_a_lid_taller_than_the_cavity_is_refused():
    with pytest.raises(SpecError) as exc:
        compile_spec(deck(lid=Lid(height_mm=200.0)))
    assert "height_mm" in str(exc.value)


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
    assert result.archetype == "deck_box" and result.archetype_version == "1"
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
    spec = deck(lid=Lid(clearance_mm=0.25))
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


# ── fits check and the UI view ─────────────────────────────────────────────────

def test_the_fits_line_shows_the_arithmetic():
    fits = fits_for(deck())
    assert fits.fits is True
    assert fits.line.startswith("100 × 0.7 mm = 70 mm stack")
    assert "internal 71 mm" in fits.line
    assert "external 74.1 × 76.6 × 97.5 mm" in fits.line
    assert "0.70 mm/card" in fits.basis
    assert fits.remedy is None


def test_an_external_constraint_that_fails_names_the_axis_and_a_card_count():
    spec = deck(constraints=Constraints(max_external_mm=(80.0, 70.0, 100.0)))
    fits = fits_for(spec)
    assert fits.fits is False
    assert "depth" in fits.remedy and "76.6" in fits.remedy and "70" in fits.remedy
    # (70 − 2·2.8 − 1.0) / 0.70 = 90.57 → 90 cards
    assert "90 cards" in fits.remedy


def test_an_external_constraint_that_holds_passes():
    spec = deck(constraints=Constraints(max_external_mm=(80.0, 80.0, 100.0)))
    assert fits_for(spec).fits is True


def test_the_view_has_the_shape_the_ui_declares():
    spec = deck()
    result = compile_spec(spec)
    view = view_for(spec, result)
    assert view["archetype"] == "deck_box"
    assert view["archetypeVersion"] == "v1"
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
