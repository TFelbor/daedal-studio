"""The box-insert archetype — the fourth, and the one PRD §1's composition claim is about.

Same discipline as `tests/test_token_tray.py`: nothing is asserted from the spec's own
arithmetic, every feature is read off the mesh and compared, on the compiled mesh *and*
on what Phase 3 hands the slicer. What is new is what a **ragged** layout makes new, and
there are four of them:

- **One shell, several differently shaped regions.** A card well resolved from the
  dimension table beside pockets whose millimetres somebody typed, each its own
  footprint and its own depth, in one manifold body.
- **Positions are features.** In a regular grid a misplaced divider moves a plane count;
  in a ragged layout it does not, so `c{i}_x_mm` and `c{i}_y_mm` are measured and are the
  only things that catch a right-sized well built in the wrong place.
- **The measurement is regional.** `token_tray` says in as many words that a ragged
  layout "would put a Y plane at the top of one pocket and nowhere else" and that a global
  read could not tell it from an artefact. `compiler.face_planes_within` is the answer:
  the design supplies the region, the mesh supplies the numbers.
- **Slack is shared equally**, so `process.wall_mm` is the minimum wall and
  `row{r}_wall_mm` is what a narrower row actually got.
"""
import hashlib

import pytest
import trimesh

from pythonsrc.organizer.archetypes import (
    box_insert,
    compile_spec,
    example_spec,
    fits_for,
    get_archetype,
    measure_spec_mesh,
    required_measurements,
    verify_spec_mesh,
    view_for,
)
from pythonsrc.organizer.compiler import MeasureError, export_stl
from pythonsrc.organizer.dimensions import resolve_stack
from pythonsrc.organizer.spec import (
    ARCHETYPE_WALL_MM,
    CardStack,
    Compartment,
    Constraints,
    Divider,
    Insert,
    Lid,
    OrganizerSpec,
    Pocket,
    Process,
    SpecError,
    Tray,
    spec_hash,
)

TOL_MM = 0.05  # PRD N1: dimensions exact to spec within ≤ ±0,05 mm


def pocket(w, d, h, source=None):
    return Compartment(Pocket(width_mm=w, depth_mm=d, height_mm=h, source=source))


def cards(count=60, sleeving="double"):
    return Compartment(CardStack(count=count, sleeving=sleeving))


def insert(compartments=None, rows=(1, 2), **overrides):
    """An insert spec. Every figure is stated, not derived from the archetype's own sums."""
    if compartments is None:
        compartments = (
            pocket(60.0, 40.0, 20.0), pocket(20.0, 20.0, 15.0), pocket(25.0, 30.0, 18.0),
        )
    base = dict(
        archetype="box_insert",
        compartments=tuple(compartments),
        insert=Insert(rows=tuple(rows)),
    )
    base.update(overrides)
    return OrganizerSpec(**base)


# ── derive: the arithmetic the geometry is built from ──────────────────────────

def test_the_externals_are_the_widest_row_the_deepest_stack_and_the_deepest_well():
    """Stated rather than recomputed from the archetype's own expression.

    Front row: one 60 mm well between two 1,6 mm walls → 63,2 mm.
    Back row: 20 + 25 mm between three walls → 49,8 mm. The widest wins, so 63,2 mm.
    Depth: 40 + 30 mm of rows plus three 1,6 mm walls → 74,8 mm.
    Height: the deepest well (20 mm) over the 2 mm floor → 22,0 mm.
    """
    d = box_insert.derive(insert())
    assert (d.external_w, d.external_d, d.external_h) == pytest.approx((63.2, 74.8, 22.0))


def test_a_narrower_row_shares_its_slack_equally_over_its_own_walls():
    """The decision the module docstring argues for, as arithmetic. The back row is
    13,4 mm narrower than the front, over three walls: 1,6 + 13,4/3 = 6,067 mm each."""
    d = box_insert.derive(insert())
    assert d.row_walls[0] == pytest.approx(1.6)
    assert d.row_walls[1] == pytest.approx(1.6 + 13.4 / 3, abs=1e-3)
    # And the row still ends exactly on the shell, which is the point of sharing it.
    last = d.wells[-1]
    assert last.x + last.width + d.row_walls[1] == pytest.approx(d.external_w, abs=2e-3)


def test_the_widest_row_carries_no_slack_and_gets_the_wall_that_was_asked_for():
    d = box_insert.derive(insert(rows=(2,), compartments=(
        pocket(20.0, 20.0, 10.0), pocket(30.0, 20.0, 10.0),
    )))
    assert d.row_walls == (pytest.approx(1.6),)


def test_the_compartments_are_dealt_along_the_rows_in_order():
    d = box_insert.derive(insert())
    assert [(w.index, w.row, w.column) for w in d.wells] == [
        (0, 0, 0), (1, 1, 0), (2, 1, 1),
    ]
    # Row 0 starts one wall in; row 1 starts behind row 0's depth and a second wall.
    assert d.wells[0].y == pytest.approx(1.6)
    assert d.wells[1].y == pytest.approx(1.6 + 40.0 + 1.6)
    assert d.wells[1].y == d.wells[2].y


def test_a_shallower_compartment_gets_a_floor_that_has_risen_under_it():
    """The feature `token_tray` deferred: one rim, several floors. The deepest well sits
    on `process.floor_mm`; every other sits that much higher."""
    d = box_insert.derive(insert())
    deepest = max(d.wells, key=lambda w: w.height)
    assert deepest.z_floor == pytest.approx(2.0)
    for well in d.wells:
        assert well.z_floor == pytest.approx(22.0 - well.height)
    assert len({w.z_floor for w in d.wells}) == 3


def test_a_card_stack_lies_flat_and_resolves_against_the_dimension_table():
    """Footprint from `resolve_stack` plus the cavity clearance on both axes; depth from
    the pitch and the stack slack. Asserted against the table, not against `derive`."""
    stack = resolve_stack(60, "standard", "double")
    d = box_insert.derive(insert(rows=(1,), compartments=(cards(60),)))
    well = d.wells[0]
    p = Process()
    assert well.width == pytest.approx(stack.footprint_w_mm + p.cavity_clearance_mm)
    assert well.depth == pytest.approx(stack.footprint_h_mm + p.cavity_clearance_mm)
    assert well.height == pytest.approx(stack.stack_height_mm + p.stack_slack_mm)
    # Flat: the footprint's long side runs in Y, not in Z. A sleeved card stands 92 mm
    # and the interiors this fills run 70–75 mm.
    assert well.depth > well.height


def test_the_default_wall_is_the_top_of_the_audited_insert_band():
    """A spec that names no wall gets 1,6 mm, and every wall on the mesh is built from
    it — the minimum, since a narrower row's are thicker."""
    spec = insert()
    assert spec.process.wall_mm == ARCHETYPE_WALL_MM["box_insert"] == 1.6
    assert box_insert.derive(spec).wall == 1.6


# ── validation: refused by name, with the remedy ───────────────────────────────

def test_a_missing_insert_section_is_refused_not_defaulted():
    with pytest.raises(SpecError) as exc:
        compile_spec(OrganizerSpec(
            archetype="box_insert", compartments=(pocket(20.0, 20.0, 15.0),),
        ))
    assert "insert is null" in str(exc.value) and "insert.rows" in str(exc.value)


@pytest.mark.parametrize("rows,count", [((1, 2), 2), ((1,), 3), ((2, 2), 3), ((5,), 3)])
def test_a_row_grouping_that_does_not_account_for_every_compartment_is_refused(rows, count):
    with pytest.raises(SpecError) as exc:
        compile_spec(insert(rows=rows, compartments=tuple(
            pocket(20.0, 20.0, 15.0) for _ in range(count)
        )))
    message = str(exc.value)
    assert f"accounts for {sum(rows)} compartments" in message
    assert f"the spec has {count}" in message


@pytest.mark.parametrize("section,value", [
    ("lid", Lid()), ("divider", Divider()), ("tray", Tray(columns=2)),
])
def test_another_archetypes_section_is_refused_rather_than_ignored(section, value):
    """Ignoring one prints a different part in silence, which is every archetype's rule."""
    with pytest.raises(SpecError) as exc:
        compile_spec(insert(**{section: value}))
    assert f"does not lay out a {section}" in str(exc.value)


@pytest.mark.parametrize("archetype,extra", [
    ("deck_box", {"lid": Lid()}),
    ("card_divider", {"divider": Divider()}),
    ("token_tray", {"tray": Tray(columns=1)}),
])
def test_the_other_archetypes_refuse_a_stray_insert_section(archetype, extra):
    """The other half of the section rule, and the half a new section usually forgets: a
    deck box handed an `insert` must refuse it rather than build a deck box."""
    contents = (
        pocket(20.0, 20.0, 15.0) if archetype == "token_tray" else cards(100)
    )
    with pytest.raises(SpecError) as exc:
        compile_spec(OrganizerSpec(
            archetype=archetype, compartments=(contents,),
            insert=Insert(rows=(1,)), **extra,
        ))
    message = str(exc.value)
    assert "does not lay out a insert" in message and "'box_insert'" in message


@pytest.mark.parametrize("index,bad", [(0, (0.2, 40.0, 20.0)), (2, (25.0, 30.0, 0.5))])
def test_a_compartment_below_the_process_minimum_is_refused_by_name(index, bad):
    compartments = [
        pocket(60.0, 40.0, 20.0), pocket(20.0, 20.0, 15.0), pocket(25.0, 30.0, 18.0),
    ]
    compartments[index] = pocket(*bad)
    with pytest.raises(SpecError) as exc:
        compile_spec(insert(compartments=tuple(compartments)))
    assert f"compartments[{index}]" in str(exc.value)
    assert "process.min_feature_mm" in str(exc.value)


def test_a_wall_below_the_process_minimum_is_refused_because_it_is_every_divider():
    with pytest.raises(SpecError) as exc:
        compile_spec(insert(process=Process(wall_mm=1.2, min_feature_mm=1.5)))
    assert "process.wall_mm 1.2 mm is below process.min_feature_mm" in str(exc.value)


def test_a_wall_under_the_nozzles_floor_is_refused_with_both_numbers():
    with pytest.raises(SpecError) as exc:
        compile_spec(insert(process=Process(wall_mm=1.0)))
    assert "1.2 mm wall floor" in str(exc.value) and "0.4 mm nozzle" in str(exc.value)


def test_a_corner_round_larger_than_the_wall_it_is_cut_from_is_refused():
    with pytest.raises(SpecError) as exc:
        compile_spec(insert(process=Process(wall_mm=1.2, corner_radius_mm=2.0)))
    assert "process.corner_radius_mm 2 mm is larger than process.wall_mm" in str(exc.value)


def test_a_chamfer_that_reaches_the_floor_above_it_is_refused():
    with pytest.raises(SpecError) as exc:
        compile_spec(insert(process=Process(floor_mm=1.2, base_chamfer_mm=1.2)))
    assert "must be less than process.floor_mm" in str(exc.value)


def test_the_archetype_refuses_a_spec_for_another_shape():
    with pytest.raises(SpecError) as exc:
        box_insert.validate(OrganizerSpec(
            archetype="token_tray", compartments=(pocket(20.0, 20.0, 15.0),),
            tray=Tray(columns=1),
        ))
    assert "is not 'box_insert'" in str(exc.value)


# ── compile: one manifold body, and the features it designed ───────────────────

def test_the_insert_is_one_watertight_body_on_the_bed():
    """The acceptance criterion in one assertion: three differently shaped compartments,
    one manifold mesh, one part."""
    result = compile_spec(insert(compartments=(
        cards(60), pocket(40.0, 40.0, 15.0), pocket(20.0, 20.0, 18.0),
    )))
    assert len(result.parts) == 1
    assert result.mesh.is_watertight
    assert len(result.mesh.split(only_watertight=False)) == 1
    assert result.mesh.bounds[0] == pytest.approx([0.0, 0.0, 0.0], abs=1e-9)


def test_the_result_carries_the_designed_features_and_the_spec_hash():
    spec = insert()
    result = compile_spec(spec)
    assert result.archetype == "box_insert" and result.archetype_version == "1"
    assert result.spec_hash == spec_hash(spec)
    assert set(box_insert.MEASURED_FEATURES) <= set(result.features)


def test_the_feature_list_grows_with_the_compartment_list():
    """The acceptance criterion `measured_features` exists for. Five per compartment,
    one wall per row, one per row boundary, plus the seven fixed ones."""
    for rows, count in (((1,), 1), ((1, 2), 3), ((2, 2, 1), 5)):
        spec = insert(rows=rows, compartments=tuple(
            pocket(20.0 + i, 20.0, 15.0) for i in range(count)
        ))
        promised = required_measurements(spec)
        assert len(promised) == 7 + 5 * count + len(rows) + (len(rows) + 1)
        assert len(set(promised)) == len(promised)


def test_a_card_wells_stack_height_is_designed_and_deliberately_not_measured():
    """The `deck_box.stack_height_mm` precedent: a stack of cards is not on the mesh, so
    promising to measure it would report a feature missing on a perfect part."""
    spec = insert(rows=(1,), compartments=(cards(60),))
    designed = compile_spec(spec).features
    assert "c0_stack_height_mm" in designed
    assert "c0_stack_height_mm" not in required_measurements(spec)
    assert set(required_measurements(spec)) < set(designed)


def test_the_same_spec_exports_the_same_bytes(tmp_path):
    """Determinism is the property the whole schema exists for."""
    digests = []
    for i in range(2):
        path = export_stl(compile_spec(insert()).mesh, tmp_path / f"{i}.stl")
        digests.append(hashlib.sha256(path.read_bytes()).hexdigest())
    assert digests[0] == digests[1]


def test_the_example_is_three_shapes_in_two_rows_and_compiles():
    spec = example_spec("box_insert")
    assert spec.archetype == "box_insert"
    assert spec.insert == Insert(rows=(1, 2))
    assert len(spec.compartments) == 3
    assert isinstance(spec.compartments[0].contents, CardStack)
    assert {c.contents.width_mm for c in spec.compartments[1:]} == {40.0, 20.0}
    d = box_insert.derive(spec)
    assert (d.external_w, d.external_d, d.external_h) == pytest.approx((71.7, 138.3, 45.0))
    assert compile_spec(spec).mesh.is_watertight


def test_the_registry_knows_the_archetype_by_name():
    assert get_archetype("box_insert") is box_insert
    assert box_insert.ARCHETYPE == "box_insert"


# ── measure: region by region, off the exported mesh ───────────────────────────

def exported(spec, path):
    """The mesh as a slicer would receive it: float32 STL, written and read back."""
    result = compile_spec(spec)
    export_stl(result.mesh, path)
    return result, trimesh.load(str(path), force="mesh")


def test_every_designed_feature_is_on_the_exported_mesh(tmp_path):
    spec = insert(compartments=(
        cards(60), pocket(40.0, 40.0, 15.0), pocket(20.0, 20.0, 18.0),
    ))
    result, mesh = exported(spec, tmp_path / "insert.stl")
    report = verify_spec_mesh(spec, result.features, mesh)
    assert report.within_tolerance, report.problems()
    assert set(report.features) == set(required_measurements(spec))
    assert report.max_abs_error_mm < 1e-4


def test_a_card_wells_millimetres_are_measured_against_the_dimension_table(tmp_path):
    """Not against `derive`'s own sum: the footprint comes from `resolve_stack` and the
    clearances from `Process`, and what is compared is the mesh."""
    spec = insert(rows=(1,), compartments=(cards(60),))
    _, mesh = exported(spec, tmp_path / "insert.stl")
    measured = measure_spec_mesh(spec, mesh)
    stack = resolve_stack(60, "standard", "double")
    p = Process()
    assert measured["c0_width_mm"] == pytest.approx(
        stack.footprint_w_mm + p.cavity_clearance_mm, abs=TOL_MM)
    assert measured["c0_depth_mm"] == pytest.approx(
        stack.footprint_h_mm + p.cavity_clearance_mm, abs=TOL_MM)
    assert measured["c0_height_mm"] == pytest.approx(
        60 * stack.pitch_mm + p.stack_slack_mm, abs=TOL_MM)


def test_the_slack_a_narrower_row_absorbed_is_measured_as_that_rows_wall(tmp_path):
    spec = insert()
    _, mesh = exported(spec, tmp_path / "insert.stl")
    measured = measure_spec_mesh(spec, mesh)
    assert measured["row0_wall_mm"] == pytest.approx(1.6, abs=TOL_MM)
    assert measured["row1_wall_mm"] == pytest.approx(1.6 + 13.4 / 3, abs=TOL_MM)
    # The Y walls are *not* shared out — every row boundary is exactly the stated wall.
    for j in range(3):
        assert measured[f"wall_y{j}_mm"] == pytest.approx(1.6, abs=TOL_MM)
    assert measured["wall_mm"] == pytest.approx(measured["wall_y0_mm"])


def test_the_floor_is_the_one_under_the_deepest_compartment(tmp_path):
    """Three wells, three floor planes, one `floor_mm`: the lowest. The other two are
    that floor plus the depth those compartments gave up, and are read back as their own
    heights rather than as floors."""
    spec = insert()
    _, mesh = exported(spec, tmp_path / "insert.stl")
    measured = measure_spec_mesh(spec, mesh)
    assert measured["floor_mm"] == pytest.approx(2.0, abs=TOL_MM)
    assert measured["c0_height_mm"] == pytest.approx(20.0, abs=TOL_MM)
    assert measured["c1_height_mm"] == pytest.approx(15.0, abs=TOL_MM)
    assert measured["c2_height_mm"] == pytest.approx(18.0, abs=TOL_MM)


def test_a_compartment_half_a_millimetre_out_of_position_is_caught_by_its_own_x(tmp_path):
    """What a plane count would have missed, and what a regular grid does not need.

    Move one well 0,5 mm along X: every external stays exactly right, every *size* stays
    exactly right, and the only thing that moved is where it is. In a ragged layout
    nothing else would notice.
    """
    spec = insert()
    result, mesh = exported(spec, tmp_path / "insert.stl")
    designed = dict(result.features)
    designed["c1_x_mm"] += 0.5
    report = verify_spec_mesh(spec, designed, mesh)
    assert report.within_tolerance is False
    assert set(report.out_of_tolerance) == {"c1_x_mm"}
    assert "external_width_mm" not in report.out_of_tolerance
    assert "c1_width_mm" not in report.out_of_tolerance


def test_a_compartment_half_a_millimetre_shallow_is_caught_by_its_own_height(tmp_path):
    """Per-compartment depth is per-compartment measurement: a global Z read would see
    three floor planes and have no way to say which one had moved."""
    spec = insert()
    result, mesh = exported(spec, tmp_path / "insert.stl")
    designed = dict(result.features)
    designed["c2_height_mm"] -= 0.5
    report = verify_spec_mesh(spec, designed, mesh)
    assert report.within_tolerance is False
    assert set(report.out_of_tolerance) == {"c2_height_mm"}
    assert "external_height_mm" not in report.out_of_tolerance


def test_a_missing_compartment_is_a_finding_that_names_it(tmp_path):
    """A well the geometry does not have is not an out-of-tolerance number — there is no
    number. The refusal names the compartment, because "the insert has the wrong plane
    count" identifies nothing a person can go and look at."""
    spec = insert()
    solids, d = box_insert.build(spec)
    # Compile a two-compartment insert and measure it against the three-compartment spec.
    thinner = insert(rows=(1, 1), compartments=(
        pocket(60.0, 40.0, 20.0), pocket(20.0, 20.0, 15.0),
    ))
    with pytest.raises(MeasureError) as exc:
        measure_spec_mesh(spec, compile_spec(thinner).mesh)
    assert "compartment" in str(exc.value)
    assert solids and d.wells  # the real one builds; the mismatch is the finding


def test_measure_refuses_a_mesh_that_is_not_one_body():
    spec = insert()
    plate = trimesh.util.concatenate([
        trimesh.creation.box(extents=[10, 10, 10]),
        trimesh.creation.box(extents=[10, 10, 10]).apply_translation([40, 0, 0]),
    ])
    with pytest.raises(MeasureError) as exc:
        measure_spec_mesh(spec, plate)
    assert "expected 1 body" in str(exc.value)


def test_a_scaled_insert_is_caught_and_a_feature_named(tmp_path):
    spec = insert()
    result, mesh = exported(spec, tmp_path / "insert.stl")
    drifted = mesh.copy()
    drifted.apply_scale(1.002)
    report = verify_spec_mesh(spec, result.features, drifted)
    assert report.within_tolerance is False
    assert "external_width_mm" in report.out_of_tolerance
    assert report.max_abs_error_mm > TOL_MM


# ── through Phase 3, and the printability gate ────────────────────────────────

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


@pytest.mark.parametrize("compartments,rows", [
    ((pocket(20.0, 20.0, 15.0),), (1,)),
    ((cards(60), pocket(40.0, 40.0, 15.0), pocket(20.0, 20.0, 18.0)), (1, 2)),
    ((pocket(15.0, 15.0, 10.0), pocket(15.0, 15.0, 12.0), pocket(30.0, 20.0, 20.0)), (2, 1)),
])
def test_phase_3_asserts_an_insert_and_hands_the_slicer_the_designed_dimensions(
    tmp_path, compartments, rows,
):
    spec = insert(compartments=compartments, rows=rows)
    result, eng, mesh = _engineered(spec, tmp_path)
    report = verify_spec_mesh(spec, result.features, mesh)
    assert report.within_tolerance, report.problems()
    assert set(report.features) == set(required_measurements(spec))
    assert eng.last_report["repair_method"] == "asserted"
    assert eng.last_report["scale_applied"] is False
    assert eng.last_report.get("faces_dropped", 0) == 0


def test_the_gate_does_not_fail_the_insert_and_it_is_one_component(tmp_path):
    """The acceptance criterion: `expected_components=1`, verdict `ready`."""
    spec = insert(compartments=(
        cards(60), pocket(40.0, 40.0, 15.0), pocket(20.0, 20.0, 18.0),
    ))
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


# ── fits check and the UI view ─────────────────────────────────────────────────

def test_the_fits_line_names_every_compartment_and_the_externals():
    fits = fits_for(insert())
    assert fits.fits is True
    assert "3 compartments in 2 rows (1/2)" in fits.line
    assert "60 × 40 × 20 mm" in fits.line
    assert "external 63.2 × 74.8 × 22 mm" in fits.line


def test_the_basis_names_both_provenances_when_the_insert_holds_both():
    """A card well resolves against a sourced table and a pocket does not. One sentence
    implying one source for both is the fabrication this engine exists to refuse."""
    fits = fits_for(insert(compartments=(
        cards(60), pocket(40.0, 40.0, 15.0), pocket(20.0, 20.0, 18.0),
    )))
    assert "double-sleeved envelope" in fits.basis
    assert "user-given millimetres for the pockets" in fits.basis
    assert "no token or dice size is sourced" in fits.basis


def test_an_external_constraint_that_fails_is_a_verdict_and_not_a_refusal():
    """Every millimetre in an insert was typed or resolved from a sourced table, so the
    honest answer is "it does not fit, by this much, on this axis" — `token_tray`'s rule."""
    spec = insert(constraints=Constraints(max_external_mm=(60.0, 100.0, 40.0)))
    fits = fits_for(spec)
    assert fits.fits is False
    assert "external width 63.2 mm exceeds 58 mm (max_external 60 − 2 margin)" in fits.remedy
    assert "move one to another row" in fits.remedy
    # And it still compiles: a verdict, not a refusal.
    assert compile_spec(spec).mesh.is_watertight


def test_an_insert_that_rattles_says_how_much_room_is_left():
    """The line the whole undershoot exists for. An insert 11,8 mm narrower than the box
    slides under the lid and tips its contents out, and nothing here fills the gap."""
    spec = insert(constraints=Constraints(max_external_mm=(77.0, 90.0, 40.0)))
    fits = fits_for(spec)
    assert fits.fits is True
    assert "11.8 mm short of the box on width" in fits.line
    assert "13.2 mm short of the box on depth" in fits.line
    assert "an insert that rattles" in fits.line


def test_an_insert_that_fills_its_limit_exactly_reports_no_gap():
    """The effective limit is `stated − fit_margin_mm`, and the margin is room the insert
    is not allowed to use. Counting it as a gap would report two deliberate millimetres
    as a fault on every part that fits perfectly."""
    d = box_insert.derive(insert())
    spec = insert(constraints=Constraints(max_external_mm=(
        d.external_w + 2.0, d.external_d + 2.0, d.external_h + 2.0,
    )))
    fits = fits_for(spec)
    assert fits.fits is True and "short of the box" not in fits.line


def test_an_easy_fit_that_busts_a_limit_is_named_rather_than_refused():
    """The deck box refuses this case because a closure has a right answer; an insert
    does not, so the clearance the *word* chose is named in the remedy instead."""
    spec = insert(
        rows=(1,), compartments=(cards(60),),
        process=Process(fit_intent="easy"),
        constraints=Constraints(max_external_mm=(60.0, 60.0, 60.0)),
    )
    fits = fits_for(spec)
    assert fits.fits is False
    assert "process.fit_intent 'easy' puts 4 mm of clearance" in fits.remedy


def test_the_view_has_the_shape_the_ui_declares():
    spec = insert()
    result = compile_spec(spec)
    view = view_for(spec, result)
    assert view["archetype"] == "box_insert"
    assert view["archetypeVersion"] == "v1"
    assert view["hash"] == result.spec_hash
    for row in view["dimensions"]:
        assert set(row) >= {"key", "label", "value", "unit", "editable"}
        assert isinstance(row["value"], (int, float)) and isinstance(row["editable"], bool)
    keys = [d["key"] for d in view["dimensions"]]
    assert keys.count("c0_width_mm") == 1 and "c2_height_mm" in keys
    derived = {d["key"] for d in view["dimensions"] if not d["editable"]}
    assert {"compartments", "external_width_mm", "row0_wall_mm"} <= derived


def test_the_view_says_what_this_archetype_does_not_do():
    """Stated rather than implied. The wells are square, the cards lie flat, and nothing
    fills the box — all three are things a preview would otherwise let a person assume."""
    spec = insert()
    view = view_for(spec, compile_spec(spec))
    assert "square compartments" in view["note"]
    assert "cards lie flat" in view["note"] and "nothing fills the box" in view["note"]
    wall = next(d for d in view["dimensions"] if d["key"] == "wall_mm")
    assert "the minimum" in wall["note"]
    untyped = next(d for d in view["dimensions"] if d["key"] == "c0_width_mm")
    assert untyped["note"] == "user-given mm — no token or dice size is sourced"
    # A stated provenance replaces the disclaimer rather than joining it.
    sourced = insert(rows=(1,), compartments=(
        pocket(20.0, 20.0, 15.0, source="16 mm d6, +2 mm, measured"),
    ))
    row = next(
        d for d in view_for(sourced, compile_spec(sourced))["dimensions"]
        if d["key"] == "c0_width_mm"
    )
    assert row["note"] == "16 mm d6, +2 mm, measured"


def test_a_card_wells_rows_say_where_the_millimetres_came_from():
    spec = insert(rows=(1,), compartments=(cards(60),))
    view = view_for(spec, compile_spec(spec))
    width = next(d for d in view["dimensions"] if d["key"] == "c0_width_mm")
    assert "double-sleeved envelope" in width["note"]
    assert "clearance" in width["note"]
    stack = next(d for d in view["dimensions"] if d["key"] == "c0_stack_height_mm")
    assert stack["editable"] is False and "lying flat" in stack["note"]


def test_the_tier_1_callouts_are_the_first_compartments_size_and_its_place():
    """Five, and two of them are positions — which no other archetype draws, because no
    other archetype has a compartment whose place is not implied by the grid."""
    tier_1 = [
        c["feature"] for c in box_insert.callouts(example_spec("box_insert"))
        if c["tier"] == 1
    ]
    assert tier_1 == list(box_insert.TIER_1_FEATURES)
    assert set(tier_1) == {"c0_width_mm", "c0_depth_mm", "c0_height_mm",
                           "c0_x_mm", "c0_y_mm"}
