"""The token tray archetype — the third one, and the first that is genuinely plural.

Same discipline as `tests/test_deck_box.py` and `tests/test_card_divider.py`: nothing is
asserted from the spec's own numbers, every feature is read off the mesh's planes and
compared, on the compiled mesh *and* on what Phase 3 hands the slicer. What is new here
is what a grid makes new, and there are three of them:

- **A compartment is no longer always a card stack.** `Compartment.contents` is a
  `CardStack | Pocket` union, told apart by the keys it carries rather than by a `kind`
  discriminator — which would have moved the `spec_hash` of every spec ever stored. The
  chooser is exercised here for both shapes, for a mapping that is both, and for one
  that is neither.
- **The feature list is a function of the spec.** A 2 × 3 tray promises 30 measurements
  and a 4 × 2 promises 37, so `archetypes.required_measurements` prefers the module's
  own `measured_features(spec)`. A fixed tuple would have said *within tolerance* while
  every pocket in the grid went unchecked.
- **The grid is regular by rule, not by habit.** One width per column, one depth per
  row, one height overall, because that is what makes every pocket wall a plane shared
  across the grid and therefore measurable. An irregular one is refused by name, per
  offending compartment.
"""
import hashlib
import itertools

import pytest
import trimesh

from pythonsrc.organizer.archetypes import (
    compile_spec,
    example_spec,
    fits_for,
    get_archetype,
    measure_spec_mesh,
    required_measurements,
    token_tray,
    verify_spec_mesh,
    view_for,
)
from pythonsrc.organizer.compiler import MeasureError, assert_features_within, export_stl, plane_set
from pythonsrc.organizer.spec import (
    ARCHETYPE_WALL_MM,
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
    wall_floor_mm,
)

TOL_MM = 0.05  # PRD N1: dimensions exact to spec within ≤ ±0,05 mm


def tray(rows=2, columns=3, pocket=(20.0, 20.0, 15.0), source=None, **overrides):
    """A tray of `rows × columns` identical pockets. Every figure is stated, not derived."""
    cell = Pocket(width_mm=pocket[0], depth_mm=pocket[1], height_mm=pocket[2], source=source)
    base = dict(
        archetype="token_tray",
        compartments=tuple(Compartment(cell) for _ in range(rows * columns)),
        tray=Tray(columns=columns),
    )
    base.update(overrides)
    return OrganizerSpec(**base)


# ── derive: the arithmetic the geometry is built from ──────────────────────────

@pytest.mark.parametrize("rows,columns,wall,expected", [
    # Σ pockets + (n + 1) walls, on each axis. Stated rather than computed from the
    # same expression the archetype uses, which would prove nothing.
    (1, 1, 1.6, (23.2, 23.2)),
    (2, 3, 1.6, (66.4, 44.8)),
    (3, 3, 1.6, (66.4, 66.4)),
    (4, 2, 2.4, (47.2, 92.0)),
])
def test_the_externals_are_the_pockets_plus_one_more_wall_than_pockets(rows, columns, wall, expected):
    d = token_tray.derive(tray(rows, columns, process=Process(wall_mm=wall)))
    assert d.rows == rows and d.columns == columns
    assert (d.external_w, d.external_d) == pytest.approx(expected)
    assert d.external_h == pytest.approx(15.0 + 2.0)  # pocket + the default floor


def test_the_rows_are_the_compartment_count_divided_by_the_columns():
    """`tray.columns` is the only layout field: stating both would let a spec name a
    grid its compartment list cannot fill."""
    spec = tray(rows=4, columns=2)
    assert len(spec.compartments) == 8
    assert token_tray.derive(spec).rows == 4


def test_the_pocket_origins_walk_the_grid_row_major_from_the_minimum_corner():
    d = token_tray.derive(tray(2, 3, process=Process(wall_mm=1.6)))
    assert d.pocket_origin(0, 0) == (1.6, 1.6)
    assert d.pocket_origin(0, 2) == pytest.approx((3 * 1.6 + 2 * 20.0, 1.6))
    assert d.pocket_origin(1, 0) == pytest.approx((1.6, 2 * 1.6 + 20.0))


def test_the_default_wall_is_the_top_of_the_audited_insert_band():
    """1,6 mm: four perimeters at 0,4 mm, thinner than the deck box's 2,4 mm (which is
    the lift-off lid's arithmetic and this archetype has no lid) and above the floor."""
    assert ARCHETYPE_WALL_MM["token_tray"] == 1.6
    assert ARCHETYPE_WALL_MM["token_tray"] < ARCHETYPE_WALL_MM["deck_box"]
    assert ARCHETYPE_WALL_MM["token_tray"] >= wall_floor_mm()
    assert tray().process.wall_mm == 1.6


# ── archetype-level refusals, with the reason ──────────────────────────────────

def test_a_card_stack_compartment_is_refused_by_name_with_the_archetype_that_holds_one():
    spec = tray(1, 1, compartments=(Compartment(CardStack(100)),))
    with pytest.raises(SpecError) as exc:
        compile_spec(spec)
    message = str(exc.value)
    assert "compartments[0]" in message and "card stack" in message
    assert "deck_box" in message


def test_a_missing_tray_section_is_refused_not_defaulted():
    """A spec that never mentioned the grid must not get a one-column one silently."""
    spec = OrganizerSpec(
        archetype="token_tray",
        compartments=(Compartment(Pocket(20.0, 20.0, 15.0)),),
    )
    with pytest.raises(SpecError) as exc:
        compile_spec(spec)
    assert "tray" in str(exc.value) and "null" in str(exc.value)


@pytest.mark.parametrize("section, value", [("lid", Lid()), ("divider", Divider())])
def test_another_archetypes_section_is_refused_rather_than_ignored(section, value):
    with pytest.raises(SpecError) as exc:
        compile_spec(tray(**{section: value}))
    assert section in str(exc.value)


def test_a_column_count_that_does_not_divide_the_compartments_is_refused():
    spec = OrganizerSpec(
        archetype="token_tray",
        compartments=tuple(Compartment(Pocket(20.0, 20.0, 15.0)) for _ in range(5)),
        tray=Tray(columns=3),
    )
    with pytest.raises(SpecError) as exc:
        compile_spec(spec)
    message = str(exc.value)
    assert "tray.columns 3" in message and "5 compartments" in message
    assert "rectangular grid" in message


@pytest.mark.parametrize("field, other, axis", [
    ("width_mm", 18.0, "column"),
    ("depth_mm", 18.0, "row"),
    ("height_mm", 12.0, "one pocket depth"),
])
def test_an_irregular_grid_is_refused_naming_the_compartment_and_the_rule(field, other, axis):
    """v1 is one width per column, one depth per row, one height overall — which is what
    makes every pocket wall a plane shared across the grid and therefore measurable."""
    cells = [Compartment(Pocket(20.0, 20.0, 15.0)) for _ in range(6)]
    odd = {"width_mm": 20.0, "depth_mm": 20.0, "height_mm": 15.0, field: other}
    cells[4] = Compartment(Pocket(**odd))
    spec = OrganizerSpec(
        archetype="token_tray", compartments=tuple(cells), tray=Tray(columns=3),
    )
    with pytest.raises(SpecError) as exc:
        compile_spec(spec)
    message = str(exc.value)
    assert f"compartments[4].contents.{field}" in message
    assert axis in message


@pytest.mark.parametrize("index", [0, 1, 2])
def test_a_pocket_dimension_below_the_process_minimum_is_refused_by_name(index):
    pocket = [20.0, 20.0, 15.0]
    pocket[index] = 0.4
    field = ("width_mm", "depth_mm", "height_mm")[index]
    spec = tray(1, 1, pocket=tuple(pocket), process=Process(min_feature_mm=1.0))
    with pytest.raises(SpecError) as exc:
        compile_spec(spec)
    assert field in str(exc.value) and "min_feature_mm" in str(exc.value)


def test_a_wall_below_the_process_minimum_is_refused_because_it_is_every_divider():
    spec = tray(1, 2, process=Process(wall_mm=1.3, min_feature_mm=2.0))
    with pytest.raises(SpecError) as exc:
        compile_spec(spec)
    assert "process.wall_mm" in str(exc.value) and "divider" in str(exc.value)


def test_a_wall_under_the_nozzles_floor_is_refused_with_both_numbers():
    """The floor is the nozzle's, enforced by `compile_spec` before this module runs —
    and the tray builds with `process.wall_mm`, so it is held to it."""
    assert token_tray.USES_PROCESS_WALL_MM is True
    with pytest.raises(SpecError) as exc:
        compile_spec(tray(process=Process(wall_mm=1.1)), nozzle_diameter_mm=0.4)
    assert "1.2 mm wall floor" in str(exc.value) and "0.4 mm nozzle" in str(exc.value)


def test_the_archetype_refuses_a_spec_for_another_shape():
    deck = OrganizerSpec(
        archetype="deck_box", compartments=(Compartment(CardStack(100)),), lid=Lid(),
    )
    with pytest.raises(SpecError) as exc:
        token_tray.validate(deck)
    assert "token_tray" in str(exc.value)


def test_the_card_archetypes_refuse_a_pocket_compartment_by_name():
    """The other direction: `derive()` would have reached for `contents.count` and
    raised an `AttributeError` three frames in."""
    pocket = (Compartment(Pocket(20.0, 20.0, 15.0)),)
    for archetype, extra in (("deck_box", {"lid": Lid()}), ("card_divider", {"divider": Divider()})):
        spec = OrganizerSpec(archetype=archetype, compartments=pocket, **extra)
        with pytest.raises(SpecError) as exc:
            compile_spec(spec)
        assert "pocket" in str(exc.value) and "token_tray" in str(exc.value)


def test_the_card_archetypes_refuse_a_stray_tray_section():
    for archetype, extra in (("deck_box", {"lid": Lid()}), ("card_divider", {"divider": Divider()})):
        spec = OrganizerSpec(
            archetype=archetype, compartments=(Compartment(CardStack(100)),),
            tray=Tray(columns=1), **extra,
        )
        with pytest.raises(SpecError) as exc:
            compile_spec(spec)
        assert "tray" in str(exc.value) and "token_tray" in str(exc.value)


# ── compile: one body on the bed ───────────────────────────────────────────────

@pytest.mark.parametrize("rows,columns", [(1, 1), (1, 3), (2, 3), (3, 3), (4, 2)])
def test_the_tray_is_one_watertight_body_on_the_bed(rows, columns):
    result = compile_spec(tray(rows, columns))
    assert result.mesh.is_watertight
    assert len(result.mesh.split(only_watertight=False)) == 1
    assert abs(result.mesh.bounds[0][2]) < 1e-6
    assert set(result.parts) == {"tray"}


def test_the_result_carries_the_designed_features_and_the_spec_hash():
    from pythonsrc.organizer.spec import spec_hash
    spec = tray()
    result = compile_spec(spec)
    assert result.archetype == "token_tray" and result.archetype_version == "1"
    assert result.spec_hash == spec_hash(spec)
    doc = result.features_document()
    assert doc["parts"] == ["tray"] and doc["spec_sha256"] == result.spec_hash


def test_every_designed_feature_is_measured_none_is_designed_only():
    """Unlike the deck box, which designs a stack height no geometry carries."""
    spec = tray()
    assert set(required_measurements(spec)) == set(compile_spec(spec).features)


def test_the_registry_prefers_the_spec_dependent_feature_list():
    """The one registry change this archetype cost. A fixed tuple could only promise
    the five names that do not move, leaving every pocket in the grid unmeasured while
    the report still said *within tolerance*."""
    small = set(required_measurements(tray(1, 1)))
    big = set(required_measurements(tray(4, 2)))
    assert set(token_tray.MEASURED_FEATURES) < small < big
    assert "pocket_r3c1_width_mm" in big and "pocket_r3c1_width_mm" not in small
    assert len(big) == len(compile_spec(tray(4, 2)).features)
    # The two counts the docs state in five places, pinned rather than recomputed by
    # each reader: `5 + 3·rows·columns + (columns + 1) + (rows + 1)`, which is *not*
    # symmetric in rows and columns, so a 2 × 3 and a 4 × 2 do not differ by the two
    # pockets alone. Both were written down wrong once.
    assert len(required_measurements(example_spec("token_tray"))) == 30  # 2 × 3
    assert len(big) == 37  # 4 × 2
    # The two card archetypes declare one too, since lettering landed (issue #157) — a
    # relief is a feature only a decorated spec has. What is asserted is therefore not
    # that they have no hook but that an **undecorated** spec still gets exactly the
    # fixed tuple, which is the property the fallback existed to guarantee.
    from pythonsrc.organizer.archetypes import card_divider, deck_box
    assert required_measurements(example_spec("deck_box")) == deck_box.MEASURED_FEATURES
    assert required_measurements(example_spec("card_divider")) == card_divider.MEASURED_FEATURES


def test_the_same_spec_exports_the_same_bytes(tmp_path):
    a = export_stl(compile_spec(tray()).mesh, tmp_path / "a.stl").read_bytes()
    b = export_stl(compile_spec(tray()).mesh, tmp_path / "b.stl").read_bytes()
    assert hashlib.sha256(a).hexdigest() == hashlib.sha256(b).hexdigest()


def test_the_example_spec_is_a_2_by_3_grid_of_20_mm_pockets_and_compiles():
    spec = example_spec("token_tray")
    assert spec.archetype == "token_tray"
    assert spec.tray is not None and spec.tray.columns == 3
    assert len(spec.compartments) == 6
    assert spec.lid is None and spec.divider is None
    pocket = spec.compartments[0].contents
    assert (pocket.width_mm, pocket.depth_mm, pocket.height_mm) == (20.0, 20.0, 15.0)
    # The example says its own 20 mm is a design figure and not a sourced token size.
    assert pocket.source and "not a sourced size" in pocket.source
    result = compile_spec(spec)
    assert result.mesh.is_watertight
    assert result.features["external_width_mm"] == pytest.approx(66.4)
    assert result.features["external_depth_mm"] == pytest.approx(44.8)
    assert result.features["external_height_mm"] == pytest.approx(17.0)


def test_the_registry_knows_the_archetype_by_name():
    assert get_archetype("token_tray") is token_tray


# ── measure: designed features read back off the geometry ──────────────────────

@pytest.mark.parametrize("rows,columns", [(1, 1), (1, 3), (2, 3), (3, 3), (4, 2)])
def test_every_designed_feature_is_on_the_compiled_mesh(rows, columns):
    spec = tray(rows, columns)
    result = compile_spec(spec)
    measured = measure_spec_mesh(spec, result.mesh)
    assert_features_within(
        result.features, measured, TOL_MM, required=set(required_measurements(spec)),
    )


def test_every_pocket_and_every_wall_is_a_named_measurement():
    """The acceptance criterion, stated: a 2 × 3 grid measures six pockets in three
    dimensions each, four X walls and three Y walls, off the mesh's own planes."""
    spec = tray(2, 3)
    measured = measure_spec_mesh(spec, compile_spec(spec).mesh)
    for row in range(2):
        for column in range(3):
            for axis in ("width", "depth", "height"):
                key = f"pocket_r{row}c{column}_{axis}_mm"
                assert measured[key] == pytest.approx(20.0 if axis != "height" else 15.0, abs=TOL_MM)
    for i in range(4):
        assert measured[f"wall_x{i}_mm"] == pytest.approx(1.6, abs=TOL_MM)
    for j in range(3):
        assert measured[f"wall_y{j}_mm"] == pytest.approx(1.6, abs=TOL_MM)


def test_the_mesh_carries_only_the_designs_planes():
    """2n + 2 per axis, and exactly three on Z — the bed, the floor and the rim. A
    fourth would mean pockets of different depths, which this archetype does not build."""
    spec = tray(2, 3)
    result = compile_spec(spec)
    assert len(plane_set(result.mesh.vertices[:, 0])) == 2 * 3 + 2
    assert len(plane_set(result.mesh.vertices[:, 1])) == 2 * 2 + 2
    assert plane_set(result.mesh.vertices[:, 2]) == pytest.approx([0.0, 2.0, 17.0], abs=1e-4)


def test_measure_reads_the_grid_off_the_mesh_rather_than_taking_it_from_the_spec():
    """Which is what lets it refuse a mesh that is not a tray instead of quietly
    measuring one — the archetype's `measure(mesh)` takes no spec at all."""
    measured = token_tray.measure(compile_spec(tray(4, 2)).mesh)
    assert "pocket_r3c1_height_mm" in measured
    assert "pocket_r0c2_height_mm" not in measured


def test_measure_refuses_a_mesh_that_is_not_a_tray():
    with pytest.raises(MeasureError) as exc:
        token_tray.measure(trimesh.creation.box(extents=[10, 10, 10]))
    assert "2n + 2" in str(exc.value)


def test_measure_refuses_a_deck_box_mesh_rather_than_reporting_a_grid():
    """A deck box is two bodies; a tray is one. The body count is the first thing that
    does not match, and it is the finding rather than a per-feature error."""
    deck = OrganizerSpec(
        archetype="deck_box", compartments=(Compartment(CardStack(100)),), lid=Lid(),
    )
    with pytest.raises(MeasureError) as exc:
        token_tray.measure(compile_spec(deck).mesh)
    assert "1 body" in str(exc.value)


def test_measure_refuses_a_second_pocket_depth_on_z():
    """A tray with two pocket depths would put four Z planes on the mesh. The archetype
    refuses such a spec, so this proves the *measurer* would name it if one ever got
    through — built here by hand rather than through a spec, on purpose."""
    import manifold3d
    body = manifold3d.Manifold.cube([40.0, 20.0, 17.0], False)
    body = body - manifold3d.Manifold.cube([15.0, 15.0, 20.0], False).translate([2.0, 2.0, 2.0])
    body = body - manifold3d.Manifold.cube([15.0, 15.0, 20.0], False).translate([22.0, 2.0, 6.0])
    from pythonsrc.organizer.compiler import manifold_to_trimesh
    with pytest.raises(MeasureError) as exc:
        token_tray.measure(manifold_to_trimesh(body))
    assert "Z planes" in str(exc.value)


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


@pytest.mark.parametrize("rows,columns", [(1, 1), (2, 3), (4, 2)])
def test_phase_3_asserts_a_tray_and_hands_the_slicer_the_designed_dimensions(tmp_path, rows, columns):
    spec = tray(rows, columns)
    result, eng, mesh = _engineered(spec, tmp_path)
    report = verify_spec_mesh(spec, result.features, mesh)
    assert report.within_tolerance, report.problems()
    assert set(report.features) == set(required_measurements(spec))
    assert eng.last_report["repair_method"] == "asserted"
    assert eng.last_report["scale_applied"] is False
    assert eng.last_report["scale_axis"] == "preserved"


def test_the_gate_does_not_fail_the_tray_and_it_is_one_component(tmp_path):
    spec = tray()
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
    assert report.verdict == "ready"


def test_what_the_wall_check_says_about_a_1_6_mm_divider(tmp_path):
    """Recorded rather than assumed either way. The gate's wall measurement is a
    voxel-pitch estimate — the deck box's 1,4 mm lip reads *risky* from quantisation —
    and a 1,6 mm divider is close enough to that floor that a later change to the pitch
    must be visible here rather than inferred. At a 0,4 mm nozzle the two-nozzle minimum
    is 0,8 mm, which 1,6 mm clears twice over."""
    _, _, mesh = _engineered(tray(), tmp_path)
    check = {c.check: c for c in evaluate_printability(mesh, ProcessProfile()).checks}[
        "min_wall_thickness"
    ]
    assert check.status in ("pass", "warn"), check.detail
    assert check.status != "fail"


# ── fits check and the UI view ─────────────────────────────────────────────────

def test_the_fits_line_shows_the_grid_the_pockets_and_the_externals():
    fits = fits_for(tray())
    assert fits.fits is True
    assert "2 × 3 grid of square pockets" in fits.line
    assert "20 × 20 × 15 mm internal" in fits.line
    assert "1.6 mm walls and dividers" in fits.line
    assert "external 66.4 × 44.8 × 17 mm" in fits.line
    assert fits.remedy is None


def test_the_basis_says_the_millimetres_were_typed_and_not_resolved():
    """No token or dice size is sourced anywhere, so there is no table behind these
    figures — and a `basis` that implied one would be the fabrication the whole engine
    exists to refuse."""
    assert "user-given millimetres" in fits_for(tray()).basis
    assert "no token or dice size is sourced" in fits_for(tray()).basis
    with_source = fits_for(tray(source="16 mm d6, +2 mm, measured"))
    assert "16 mm d6, +2 mm, measured" in with_source.basis


def test_an_external_constraint_that_fails_is_a_verdict_and_not_a_refusal():
    """Every millimetre in a tray was typed by the person asking, so the honest answer
    is "it does not fit, by this much, on this axis" — not a spec the composer cannot
    even show. The deck box refuses an `easy` overshoot because *there* the clearance
    that pushed it over is a number nobody typed."""
    spec = tray(constraints=Constraints(max_external_mm=(60.0, 100.0, 100.0), fit_margin_mm=0))
    compile_spec(spec)  # compiles: the overshoot is a verdict, not a refusal
    fits = fits_for(spec)
    assert fits.fits is False
    assert "external width 66.4 mm exceeds 60 mm" in fits.remedy
    assert "drop a row or a column" in fits.remedy


def test_the_margin_applies_to_the_tray_too_and_names_itself():
    spec = tray(constraints=Constraints(max_external_mm=(67.0, 100.0, 100.0)))
    fits = fits_for(spec)
    assert fits.fits is False
    assert "exceeds 65 mm (max_external 67 − 2 margin) by 1.4 mm" in fits.remedy


def test_an_external_constraint_that_holds_passes():
    assert fits_for(tray(constraints=Constraints(max_external_mm=(80.0, 60.0, 30.0)))).fits is True


def test_the_view_has_the_shape_the_ui_declares():
    spec = tray()
    result = compile_spec(spec)
    view = view_for(spec, result)
    assert view["archetype"] == "token_tray"
    assert view["archetypeVersion"] == "v1"
    assert view["hash"] == result.spec_hash
    assert view["fits"]["fits"] is True
    for row in view["dimensions"]:
        assert set(row) >= {"key", "label", "value", "unit", "editable"}
        assert isinstance(row["value"], (int, float)) and isinstance(row["editable"], bool)
    editable = {d["key"] for d in view["dimensions"] if d["editable"]}
    derived = {d["key"] for d in view["dimensions"] if not d["editable"]}
    assert {"columns", "pocket_height_mm", "wall_mm", "floor_mm"} <= editable
    assert {"rows", "external_width_mm", "external_depth_mm", "external_height_mm"} <= derived


def test_the_view_says_the_pockets_are_not_sourced_and_the_corners_are_square():
    view = view_for(tray(), compile_spec(tray()))
    width = next(d for d in view["dimensions"] if d["key"] == "pocket_c0_width_mm")
    assert width["note"] == "user-given mm — no token or dice size is sourced"
    assert "square pockets, square corners" in view["note"]
    # And a stated provenance replaces the disclaimer rather than joining it.
    sourced = tray(source="16 mm d6, +2 mm, measured")
    row = next(
        d for d in view_for(sourced, compile_spec(sourced))["dimensions"]
        if d["key"] == "pocket_c0_width_mm"
    )
    assert row["note"] == "16 mm d6, +2 mm, measured"


# ── the envelope, exported and reloaded ────────────────────────────────────────

GRIDS = ((1, 1), (1, 3), (2, 3), (3, 3), (4, 2))
POCKETS = ((12.0, 12.0, 10.0), (16.0, 16.0, 14.0), (20.0, 20.0, 15.0), (30.0, 45.0, 20.0))
#: `None` states no wall at all and takes the archetype's own default (1,6 mm), which
#: is what every spec that does not mention one compiles with.
WALLS = (None, 1.2, 1.6, 2.4)

ENVELOPE = list(itertools.product(GRIDS, POCKETS, WALLS))


@pytest.mark.parametrize("grid,pocket,wall", ENVELOPE)
def test_every_measured_feature_of_an_exported_tray_is_within_tolerance(tmp_path, grid, pocket, wall):
    rows, columns = grid
    spec = tray(rows, columns, pocket=pocket, process=Process(wall_mm=wall))
    result = compile_spec(spec)
    path = export_stl(result.mesh, tmp_path / "tray.stl")
    report = verify_spec_mesh(spec, result.features, trimesh.load(str(path), force="mesh"))
    assert report.within_tolerance, report.problems()
    assert set(report.features) == set(required_measurements(spec))


def test_the_tray_envelope_is_wide_enough_to_mean_something():
    """Guards the sweep against being quietly narrowed to the one example spec, and in
    particular against losing the unstated wall — `None` is what almost every real spec
    is, and it is the case a changed archetype default moves — and the 1 × 1 grid, which
    is the only one with no divider at all."""
    assert len(ENVELOPE) >= 60
    assert None in WALLS
    assert (1, 1) in GRIDS and (4, 2) in GRIDS
    assert max(r for r, _ in GRIDS) >= 3 and max(c for _, c in GRIDS) >= 3
    assert len({p[0] for p in POCKETS}) >= 4
    assert any(p[0] != p[1] for p in POCKETS), "every pocket is square, so W and D cannot swap"


def test_the_wall_the_archetype_chose_is_on_the_exported_mesh(tmp_path):
    """A spec that states no wall gets 1,6 mm, and the mesh has to carry it — not the
    dataclass, the geometry — on every divider as well as the outer faces."""
    spec = tray(2, 3, process=Process(wall_mm=None))
    assert spec.process.wall_mm == ARCHETYPE_WALL_MM["token_tray"]
    result = compile_spec(spec)
    path = export_stl(result.mesh, tmp_path / "tray.stl")
    report = verify_spec_mesh(spec, result.features, trimesh.load(str(path), force="mesh"))
    assert report.within_tolerance, report.problems()
    for i in range(4):
        assert report.features[f"wall_x{i}_mm"][1] == pytest.approx(1.6, abs=TOL_MM)


def test_a_tray_scaled_by_a_fifth_of_a_percent_is_caught_and_the_feature_named(tmp_path):
    """The check bites on the third archetype too: 0,2 % of a 66,4 mm envelope is
    0,133 mm, well over the 0,05 mm bound, and the report names which feature moved."""
    spec = tray()
    result = compile_spec(spec)
    mesh = trimesh.load(str(export_stl(result.mesh, tmp_path / "tray.stl")), force="mesh")
    drifted = mesh.copy()
    drifted.apply_scale(1.002)
    report = verify_spec_mesh(spec, result.features, drifted)
    assert report.within_tolerance is False
    assert "external_width_mm" in report.out_of_tolerance
    assert report.max_abs_error_mm > TOL_MM


def test_the_example_tray_has_sub_micron_error_on_the_exported_mesh(tmp_path):
    """The headline number, stated as an assertion: float32 STL noise, not geometry."""
    spec = example_spec("token_tray")
    result = compile_spec(spec)
    mesh = trimesh.load(str(export_stl(result.mesh, tmp_path / "tray.stl")), force="mesh")
    assert verify_spec_mesh(spec, result.features, mesh).max_abs_error_mm < 1e-4
