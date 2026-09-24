"""The card divider archetype — the second one, and therefore the API test.

Same discipline as `tests/test_deck_box.py`: nothing is asserted from the spec's own
numbers, every feature is read off the mesh's planes and compared, on the compiled
mesh *and* on what Phase 3 hands the slicer. What is new here is that the archetype
API had to hold: this module exercises the registry's dispatch functions rather than
`card_divider`'s own, so a verb the second archetype forgot to expose fails here and
not in a stack trace three phases later.

The two things that are easy to get wrong and silent when they are:

- **`tab_offset_mm` for `left` and `right`.** Both put three X planes on the body,
  because the tab's outer edge *is* the plate's, so a plane count cannot tell them
  apart — and `orient_for_print` then re-centres the part in X and Y, so an offset read
  from absolute coordinates is wrong by half the plate. Measured per region, relative
  to the plate's own left plane, and asserted for all three positions after the
  Engineer has moved the part.
- **The plate is one body.** A deck box is two, so `expected_components` and the
  printability gate's `floating_components` check both have to be told, and a divider
  that came back as two bodies would still be watertight and still slice.
"""
import hashlib
import itertools

import pytest
import trimesh

from pythonsrc.organizer.archetypes import (
    card_divider,
    compile_spec,
    example_spec,
    fits_for,
    get_archetype,
    measure_spec_mesh,
    required_measurements,
    verify_spec_mesh,
    view_for,
)
from pythonsrc.organizer.compiler import MeasureError, assert_features_within, export_stl
from pythonsrc.organizer.spec import (
    CardStack,
    Compartment,
    Constraints,
    Divider,
    Lid,
    OrganizerSpec,
    Process,
    SpecError,
)

TOL_MM = 0.05  # PRD N1: dimensions exact to spec within ≤ ±0,05 mm

#: The sleeved envelopes, so the expected plate size is stated rather than derived.
ENVELOPES = {"none": (63.5, 88.9), "single": (66.0, 91.0), "double": (67.0, 92.0)}


def divider(count=100, sleeving="double", **overrides):
    div = overrides.pop("divider", Divider())
    base = dict(
        archetype="card_divider",
        compartments=(Compartment(CardStack(count=count, sleeving=sleeving)),),
        divider=div,
    )
    base.update(overrides)
    return OrganizerSpec(**base)


# ── derive: the arithmetic the geometry is built from ──────────────────────────

@pytest.mark.parametrize("sleeving", ["none", "single", "double"])
def test_the_plate_is_the_sleeved_envelope_with_no_margin(sleeving):
    """No divider margin is sourced anywhere, and the only candidate (1,5 mm cavity
    clearance) would make the plate exactly as wide as our own deck box's cavity."""
    d = card_divider.derive(divider(sleeving=sleeving))
    fw, fh = ENVELOPES[sleeving]
    assert d.plate_w == pytest.approx(fw)
    assert d.plate_h == pytest.approx(fh)


@pytest.mark.parametrize("position, expected", [
    ("left", 0.0),
    ("centre", (67.0 - 20.0) / 2.0),
    ("right", 67.0 - 20.0),
])
def test_the_tab_offset_follows_the_position(position, expected):
    d = card_divider.derive(divider(divider=Divider(tab_position=position)))
    assert d.tab_offset == pytest.approx(expected)
    assert d.total_h == pytest.approx(92.0 + 10.0)


def test_the_default_thickness_is_the_middle_of_the_audited_insert_band():
    """1,2–1,6 mm (roadmap §0.5), and seven layers at 0,2 mm."""
    assert Divider().thickness_mm == 1.4


# ── archetype-level refusals, with the reason ──────────────────────────────────

def test_a_second_compartment_is_refused_by_name():
    spec = divider(compartments=(Compartment(CardStack(60)), Compartment(CardStack(40))))
    with pytest.raises(SpecError) as exc:
        compile_spec(spec)
    assert "one compartment" in str(exc.value)


def test_a_missing_divider_section_is_refused_not_defaulted():
    """A spec that never mentioned the plate must not get one silently."""
    spec = OrganizerSpec(
        archetype="card_divider", compartments=(Compartment(CardStack(100)),),
    )
    with pytest.raises(SpecError) as exc:
        compile_spec(spec)
    assert "divider" in str(exc.value) and "null" in str(exc.value)


def test_a_lid_is_refused_rather_than_ignored():
    with pytest.raises(SpecError) as exc:
        compile_spec(divider(lid=Lid()))
    assert "lid" in str(exc.value)


@pytest.mark.parametrize("tab_width", [67.0, 80.0])
def test_a_tab_as_wide_as_the_plate_is_refused_with_the_remedy(tab_width):
    """It would erase the plate's own top plane: that is a taller plate, not a tab."""
    with pytest.raises(SpecError) as exc:
        compile_spec(divider(divider=Divider(tab_width_mm=tab_width)))
    message = str(exc.value)
    assert "tab_width_mm" in message and "67" in message and "narrow the tab" in message


@pytest.mark.parametrize("field, bad", [
    ("thickness_mm", 0.8),
    ("tab_width_mm", 0.9),
    ("tab_height_mm", 0.5),
])
def test_a_feature_below_the_process_minimum_is_refused_by_name(field, bad):
    spec = divider(divider=Divider(**{field: bad}), process=Process(min_feature_mm=1.0))
    with pytest.raises(SpecError) as exc:
        compile_spec(spec)
    assert field in str(exc.value) and "min_feature_mm" in str(exc.value)


def test_the_archetype_refuses_a_spec_for_another_shape():
    deck = OrganizerSpec(
        archetype="deck_box", compartments=(Compartment(CardStack(100)),), lid=Lid(),
    )
    with pytest.raises(SpecError) as exc:
        card_divider.validate(deck)
    assert "card_divider" in str(exc.value)


# ── compile: one body on the bed ───────────────────────────────────────────────

@pytest.mark.parametrize("sleeving", ["none", "single", "double"])
@pytest.mark.parametrize("position", ["left", "centre", "right"])
def test_the_plate_is_one_watertight_body_on_the_bed(sleeving, position):
    spec = divider(sleeving=sleeving, divider=Divider(tab_position=position))
    result = compile_spec(spec)
    assert result.mesh.is_watertight
    parts = result.mesh.split(only_watertight=False)
    assert len(parts) == 1
    assert abs(result.mesh.bounds[0][2]) < 1e-6
    assert set(result.parts) == {"divider"}
    assert result.parts["divider"].is_watertight


def test_the_result_carries_the_designed_features_and_the_spec_hash():
    from pythonsrc.organizer.spec import spec_hash
    spec = divider()
    result = compile_spec(spec)
    assert result.archetype == "card_divider" and result.archetype_version == "1"
    assert result.spec_hash == spec_hash(spec)
    assert set(result.features) == set(card_divider.MEASURED_FEATURES)
    doc = result.features_document()
    assert doc["parts"] == ["divider"] and doc["spec_sha256"] == result.spec_hash


def test_every_designed_feature_is_measured_none_is_designed_only():
    """Unlike the deck box, which designs a stack height no geometry carries."""
    spec = divider()
    assert set(required_measurements(spec)) == set(compile_spec(spec).features)


def test_the_same_spec_exports_the_same_bytes(tmp_path):
    a = export_stl(compile_spec(divider()).mesh, tmp_path / "a.stl").read_bytes()
    b = export_stl(compile_spec(divider()).mesh, tmp_path / "b.stl").read_bytes()
    assert hashlib.sha256(a).hexdigest() == hashlib.sha256(b).hexdigest()


def test_the_example_spec_compiles():
    spec = example_spec("card_divider")
    assert spec.archetype == "card_divider"
    assert spec.divider is not None and spec.lid is None
    assert compile_spec(spec).mesh.is_watertight


def test_the_registry_knows_the_archetype_by_name():
    assert get_archetype("card_divider") is card_divider


# ── measure: designed features read back off the geometry ──────────────────────

@pytest.mark.parametrize("sleeving", ["none", "single", "double"])
@pytest.mark.parametrize("position", ["left", "centre", "right"])
def test_every_designed_feature_is_on_the_compiled_mesh(sleeving, position):
    spec = divider(sleeving=sleeving, divider=Divider(tab_position=position))
    result = compile_spec(spec)
    measured = measure_spec_mesh(spec, result.mesh)
    assert_features_within(
        result.features, measured, TOL_MM, required=set(card_divider.MEASURED_FEATURES)
    )


def test_measure_refuses_a_mesh_that_is_not_a_divider():
    with pytest.raises(MeasureError):
        card_divider.measure(trimesh.creation.box(extents=[10, 10, 10]), divider())


def test_measure_refuses_two_bodies():
    a = trimesh.creation.box(extents=[10, 10, 1])
    b = trimesh.creation.box(extents=[10, 10, 1])
    b.apply_translation([50, 0, 0])
    with pytest.raises(MeasureError) as exc:
        card_divider.measure(trimesh.util.concatenate([a, b]), divider())
    assert "1 body" in str(exc.value)


# ── through Phase 3 ────────────────────────────────────────────────────────────

from pythonsrc.engineer import Engineer  # noqa: E402
from pythonsrc.printability import ProcessProfile, evaluate_printability  # noqa: E402


def _engineered(spec, tmp_path):
    result = compile_spec(spec)
    raw = export_stl(result.mesh, tmp_path / "compiled_mesh.stl")
    eng = Engineer()
    out = eng.process(
        input_path=raw, output_path=tmp_path / "engineered.obj",
        target_mm=None, repair_mode="assert",
    )
    return result, eng, trimesh.load(str(out), force="mesh")


def test_phase_3_asserts_a_divider_and_hands_the_slicer_the_designed_dimensions(tmp_path):
    spec = divider()
    result, eng, mesh = _engineered(spec, tmp_path)
    report = verify_spec_mesh(spec, result.features, mesh)
    assert report.within_tolerance, report.problems()
    assert eng.last_report["repair_method"] == "asserted"
    assert eng.last_report["scale_applied"] is False
    assert eng.last_report["scale_axis"] == "preserved"


@pytest.mark.parametrize("position, expected_offset", [
    ("left", 0.0),
    ("centre", 23.5),
    ("right", 47.0),
])
def test_the_tab_offset_survives_the_engineers_recentring(tmp_path, position, expected_offset):
    """`orient_for_print` centres in X and Y, so an offset read from absolute
    coordinates would be wrong by half the plate — and `left` and `right` are the two
    cases a plane *count* cannot distinguish."""
    spec = divider(divider=Divider(tab_position=position))
    _, _, mesh = _engineered(spec, tmp_path)
    assert mesh.bounds[0][0] == pytest.approx(-67.0 / 2, abs=1e-3)  # re-centred
    measured = measure_spec_mesh(spec, mesh)
    assert measured["tab_offset_mm"] == pytest.approx(expected_offset, abs=TOL_MM)


def test_the_gate_does_not_fail_the_divider_and_it_is_one_component(tmp_path):
    spec = divider()
    result, _, mesh = _engineered(spec, tmp_path)
    assert len(result.parts) == 1
    report = evaluate_printability(
        mesh,
        ProcessProfile(build_volume_mm=[220.0, 220.0, 250.0]),
        expected_components=len(result.parts),
    )
    by_name = {c.check: c for c in report.checks}
    assert not any(c.status == "fail" for c in report.checks), [
        (c.check, c.detail) for c in report.checks if c.status == "fail"
    ]
    assert by_name["floating_components"].status == "pass"
    assert by_name["watertight"].status == "pass"
    assert by_name["escape_hole"].status == "pass"
    assert report.verdict == "ready"


def test_a_1_4_mm_plate_passes_the_wall_check_at_a_0_4_mm_nozzle(tmp_path):
    """Stated so a later change to the measurement pitch is visible rather than
    inferred: the pitch on a ~102 mm plate is ~0,4 mm, and 1,4 mm clears the 0,8 mm
    two-nozzle floor with a voxel to spare. At a 0,8 mm nozzle (min wall 1,6 mm) the
    same plate would warn or fail, correctly — that is a thin plate, not a bad check."""
    _, _, mesh = _engineered(divider(), tmp_path)
    check = {
        c.check: c
        for c in evaluate_printability(mesh, ProcessProfile()).checks
    }["min_wall_thickness"]
    assert check.status == "pass", check.detail


# ── fits check and the UI view ─────────────────────────────────────────────────

def test_the_fits_line_shows_the_arithmetic_and_how_far_the_tab_stands_proud():
    fits = fits_for(divider())
    assert fits.fits is True
    assert "67 × 92 mm double-sleeved envelope" in fits.line
    assert "plate 67 × 92 × 1.4 mm" in fits.line
    assert "tab 20 × 10 mm centre" in fits.line
    # A tabbed divider does not fit the same-stack deck box with its lid on; the line
    # must say how far the tab stands proud so "fits" is not read as claiming it does.
    assert "stands 10 mm proud" in fits.line
    assert "0.70 mm/card" in fits.basis
    assert fits.remedy is None


def test_a_thick_inner_divider_names_its_envelope_in_words():
    """The divider's plate is the sleeve envelope, which thick inners do not change. The
    caption must say so in words and not print the ``double_thick`` key."""
    fits = fits_for(divider(sleeving="double_thick"))
    assert "67 × 92 mm thick-inner double-sleeved envelope" in fits.line
    assert "double_thick" not in fits.line


def test_the_card_count_is_named_as_not_geometric():
    """It is required by the schema and does not enter the geometry — a divider labels
    a group of any size — so the line says so rather than the archetype refusing it."""
    assert "not a geometric input" in fits_for(divider(count=7)).line
    assert compile_spec(divider(count=7)).features == compile_spec(divider(count=500)).features


def test_an_external_constraint_that_fails_names_the_axis_and_the_overshoot():
    spec = divider(constraints=Constraints(max_external_mm=(67.0, 1.0, 95.0), fit_margin_mm=0))
    fits = fits_for(spec)
    assert fits.fits is False
    assert "depth 1.4 mm exceeds 1 mm" in fits.remedy
    assert "height 102 mm exceeds 95 mm" in fits.remedy
    assert "Thin the plate" in fits.remedy


def test_an_external_constraint_that_holds_passes():
    spec = divider(constraints=Constraints(max_external_mm=(70.0, 4.0, 110.0)))
    assert fits_for(spec).fits is True


def test_the_margin_applies_to_the_divider_too_and_names_itself():
    """The margin is a property of the *measurement*, not of the shape: it is the
    ±1–2 mm a box internal varies by, so it comes off every axis of every archetype.
    A plate that presses on the box walls splits them exactly as an insert does."""
    spec = divider(constraints=Constraints(max_external_mm=(67.0, 4.0, 110.0)))
    fits = fits_for(spec)
    assert fits.fits is False
    assert "width 67 mm exceeds 65 mm (max_external 67 − 2 margin) by 2.0 mm" in fits.remedy


def test_a_zero_margin_restores_the_old_comparison_for_the_divider():
    """Byte for byte: the sentence carries no parenthetical when no subtraction
    happened, and a plate that filled its stated limit exactly still fits."""
    spec = divider(constraints=Constraints(max_external_mm=(67.0, 1.4, 102.0), fit_margin_mm=0))
    assert fits_for(spec).fits is True
    over = divider(constraints=Constraints(max_external_mm=(66.0, 4.0, 110.0), fit_margin_mm=0))
    assert fits_for(over).remedy == (
        "width 67 mm exceeds 66 mm by 1.0 mm. Thin the plate, shorten the tab, "
        "choose a lighter sleeving, or relax the constraint."
    )


def test_the_view_has_the_shape_the_ui_declares():
    spec = divider(divider=Divider(tab_position="right"))
    result = compile_spec(spec)
    view = view_for(spec, result)
    assert view["archetype"] == "card_divider"
    assert view["archetypeVersion"] == "v1"
    assert view["hash"] == result.spec_hash
    assert view["fits"]["fits"] is True
    for row in view["dimensions"]:
        assert set(row) >= {"key", "label", "value", "unit", "editable"}
        assert isinstance(row["value"], (int, float)) and isinstance(row["editable"], bool)
    editable = {d["key"] for d in view["dimensions"] if d["editable"]}
    derived = {d["key"] for d in view["dimensions"] if not d["editable"]}
    assert {"thickness_mm", "tab_width_mm", "tab_height_mm"} <= editable
    assert {"plate_width_mm", "tab_offset_mm", "total_height_mm"} <= derived
    offset = next(d for d in view["dimensions"] if d["key"] == "tab_offset_mm")
    assert "right" in offset["note"]


def test_the_view_says_the_tab_defaults_are_not_sourced():
    """Nothing in `docs/dimension-kb-research.md` gives a divider tab. A default a
    person can edit is a parameter; a default presented as sourced is a fabrication."""
    view = view_for(divider(), compile_spec(divider()))
    tab = next(d for d in view["dimensions"] if d["key"] == "tab_width_mm")
    assert "unsourced" in tab["note"]
    thickness = next(d for d in view["dimensions"] if d["key"] == "thickness_mm")
    assert "1,2–1,6" in thickness["note"] and "practitioner" in thickness["note"]


# ── the outline, which is what replaced the union ──────────────────────────────

@pytest.mark.parametrize("position", ["left", "centre", "right"])
def test_the_outline_carries_no_zero_length_edge(position):
    """At `left` the tab's own left corner *is* the plate's, so the naive point list
    repeats a vertex — a zero-length edge, which is not a polygon."""
    d = card_divider.derive(divider(divider=Divider(tab_position=position)))
    points = card_divider.outline(d)
    assert len(points) == (8 if position == "centre" else 7)
    for a, b in zip(points, points[1:] + points[:1], strict=True):
        assert a != b


@pytest.mark.parametrize("position", ["left", "centre", "right"])
def test_the_mesh_carries_only_the_designs_planes(position):
    """Why the outline is extruded rather than two boxes unioned: an edge tab's side
    face is coplanar with the plate's, and the kernel kept vertices from that
    intersection — a Y plane at `plate_height − overlap` that no dimension accounts
    for, indistinguishable from a real one."""
    from pythonsrc.organizer.compiler import plane_set
    spec = divider(divider=Divider(tab_position=position))
    result = compile_spec(spec)
    d = card_divider.derive(spec)
    y = plane_set(result.mesh.vertices[:, 1])
    z = plane_set(result.mesh.vertices[:, 2])
    assert y == pytest.approx([0.0, d.plate_h, d.total_h], abs=1e-4)
    assert z == pytest.approx([0.0, d.thickness], abs=1e-4)
    assert len(plane_set(result.mesh.vertices[:, 0])) == (4 if position == "centre" else 3)


# ── the envelope, exported and reloaded ────────────────────────────────────────

SLEEVINGS = ("none", "single", "double")
POSITIONS = ("left", "centre", "right")


@pytest.mark.parametrize("sleeving,position", list(itertools.product(SLEEVINGS, POSITIONS)))
def test_the_exported_stl_measures_within_tolerance(tmp_path, sleeving, position):
    spec = divider(sleeving=sleeving, divider=Divider(tab_position=position))
    result = compile_spec(spec)
    path = export_stl(result.mesh, tmp_path / "divider.stl")
    report = verify_spec_mesh(spec, result.features, trimesh.load(str(path), force="mesh"))
    assert report.within_tolerance, report.problems()
    assert set(report.features) == set(card_divider.MEASURED_FEATURES)
