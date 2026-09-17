"""`view.json`'s callouts: a number on a preview is a *designed* number, in its place.

The mm-annotated preview (issue #88, PRD F7) is the primary mitigation against a
misparse costing an eight-hour print — so the whole of its value is that the millimetres
drawn over the mesh are the ones the part was built from. Four ways that could fail
silently, and one test each:

- **A fabricated figure.** A callout naming a feature the archetype never measures would
  put a number on screen that Phase 3 has no verdict for. Every `feature` must be in
  `required_measurements(spec)`, which is the set the dimension report covers.
- **A re-derived figure.** `value_mm` must be `result.features[feature]` verbatim. A
  callout that recomputed `cavity_w` from the spec would keep agreeing with itself while
  disagreeing with the mesh.
- **A line in the wrong place.** The number would be right and the picture wrong, which
  is the failure a person cannot see: a cavity width drawn across the outer wall reads as
  a box 4,8 mm wider than it is. Both ends of every line must lie on face planes the
  named part actually has — the same planes `measure()` reads the feature off.
- **A frame the mesh is not in.** The viewer translates callouts by the difference
  between the served mesh's minimum and `frame.bounds_mm.min`, which is only valid
  because Phase 3's assert path translates and never rotates or scales. `frame` must be
  the compiled plate's own bounds, and `tests/test_pipeline_spec.py` asserts the
  engineered mesh still matches its extents.

Driven over each archetype's **Phase 3 corner set** rather than its whole envelope: the
plane assertions need a compiled mesh, the corners are already the subset chosen to be
worth a kernel round (`common.SweepCase`), and the pure-arithmetic assertions run over
every case in the envelope, where they cost nothing.
"""
import pytest

from pythonsrc.organizer.archetypes import (
    REGISTRY,
    compile_spec,
    deck_box,
    envelope_for,
    example_spec,
    get_archetype,
    required_measurements,
    view_for,
)
from pythonsrc.organizer.archetypes.common import (
    CALLOUT_TIER_EXTERNAL,
    CALLOUT_TIER_INTERNAL,
    callout,
)
from pythonsrc.organizer.compiler import MeasureError, face_planes

#: How close an anchor has to sit to a plane the part has. Four orders below the ±0,05 mm
#: dimensional claim: these are the *same* floats the geometry was built from, so anything
#: but an exact match is a wrong anchor rather than a tolerance question.
ANCHOR_TOL_MM = 1e-6


def corner_cases(name: str):
    """The archetype's Phase 3 corner set, as (id, spec) pairs."""
    return [(case.id, case.spec) for case in envelope_for(name) if case.phase_3]


def all_cases(name: str):
    """Every spec the archetype declares an envelope for."""
    return [(case.id, case.spec) for case in envelope_for(name)]


def _corner_params():
    """One node per corner, because each one compiles and a failure names the spec."""
    return [
        pytest.param(name, spec, id=f"{name}-{case_id}")
        for name in sorted(REGISTRY)
        for case_id, spec in corner_cases(name)
    ]


# ── the registry API ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", sorted(REGISTRY))
def test_every_archetype_annotates_its_own_example(name):
    """An archetype that draws no callouts has an unannotated preview, which is the
    thing this issue exists to remove. The verb is part of the API for all three."""
    spec = example_spec(name)
    view = view_for(spec, compile_spec(spec))
    assert view["frame"]["units"] == "mm" and view["frame"]["up"] == "z"
    assert view["callouts"], f"{name} draws no callouts"


@pytest.mark.parametrize("name", sorted(REGISTRY))
def test_every_archetype_puts_at_least_one_internal_figure_on_the_preview(name):
    """Tier 1 is the point: the externals are what a person can measure with callipers,
    the internals are what they cannot, and the internals are what a misparse costs."""
    tiers = {c["tier"] for c in get_archetype(name).callouts(example_spec(name))}
    assert CALLOUT_TIER_INTERNAL in tiers
    assert tiers <= {CALLOUT_TIER_INTERNAL, CALLOUT_TIER_EXTERNAL}


# ── the anti-fabrication contract ─────────────────────────────────────────────

@pytest.mark.parametrize("name", sorted(REGISTRY))
def test_every_callout_names_a_feature_phase_3_measures(name):
    """The whole contract in one assertion, over the archetype's **whole** envelope —
    callouts are pure arithmetic, so the sweep costs no kernel and there is no reason to
    ask less of it than the dimensional claim does.

    A callout naming an unmeasured feature is a number the dimension report has no
    verdict for, and the preview would present it exactly as confidently as one it does.
    """
    for case_id, spec in all_cases(name):
        required = set(required_measurements(spec))
        for c in get_archetype(name).callouts(spec):
            assert c["feature"] in required, (
                f"{name}/{case_id} draws {c['feature']!r}, which required_measurements "
                "does not promise"
            )


@pytest.mark.parametrize("name", sorted(REGISTRY))
def test_every_line_is_as_long_as_the_number_printed_on_it(name):
    """`common.callout` refuses the disagreement where it is built; this is the sweep
    that says no spec in the envelope ever provokes it."""
    for case_id, spec in all_cases(name):
        for c in get_archetype(name).callouts(spec):
            span = [b - a for a, b in zip(c["from"], c["to"], strict=True)]
            moved = [v for v in span if abs(v) > 1e-9]
            assert len(moved) == 1, f"{name}/{case_id}/{c['feature']} is not axis-aligned"
            # 1 µm looser than the builder's own check: both ends are rounded to the
            # schema's three decimals on the way into the document.
            assert abs(abs(moved[0]) - c["value_mm"]) <= 1e-3


@pytest.mark.parametrize("name,spec", _corner_params())
def test_every_value_is_the_designed_feature_verbatim(name, spec):
    """Never re-derived. A second derivation agrees with itself and drifts from the
    mesh, which is precisely the failure a preview cannot show."""
    result = compile_spec(spec)
    for c in get_archetype(name).callouts(spec):
        assert c["value_mm"] == pytest.approx(result.features[c["feature"]], abs=1e-9)


@pytest.mark.parametrize("name,spec", _corner_params())
def test_both_ends_of_every_line_sit_on_planes_the_part_has(name, spec):
    """The assertion that catches a cavity width drawn across the outer wall.

    Only the axis the line runs along is checked, and that is deliberate: the other two
    coordinates place the line on a face for legibility and carry no claim, while the two
    that *are* the measurement have to be planes `measure()` could read the feature off.
    """
    result = compile_spec(spec)
    for c in get_archetype(name).callouts(spec):
        part = result.parts[c["part"]]
        axis = next(i for i in range(3) if abs(c["to"][i] - c["from"][i]) > 1e-9)
        planes = face_planes(part, axis)
        for end in (c["from"][axis], c["to"][axis]):
            assert any(abs(end - plane) <= ANCHOR_TOL_MM for plane in planes), (
                f"{name}/{c['feature']}: {'XYZ'[axis]} = {end} is not a plane of "
                f"{c['part']}; it has {[round(p, 3) for p in planes]}"
            )


@pytest.mark.parametrize("name,spec", _corner_params())
def test_the_offset_points_across_the_line_rather_than_along_it(name, spec):
    """The viewer nudges the line along `offset` and fades the label when it faces away
    from the camera. An offset parallel to the line would shorten the thing it labels."""
    for c in get_archetype(name).callouts(spec):
        axis = next(i for i in range(3) if abs(c["to"][i] - c["from"][i]) > 1e-9)
        assert c["offset"][axis] == 0.0, f"{name}/{c['feature']} is nudged along itself"
        assert any(v for v in c["offset"]), f"{name}/{c['feature']} has no offset"


@pytest.mark.parametrize("name,spec", _corner_params())
def test_the_frame_is_the_compiled_plates_own_bounds(name, spec):
    """What the viewer reconciles the served mesh against before it draws anything."""
    result = compile_spec(spec)
    frame = view_for(spec, result)["frame"]
    low, high = result.mesh.bounds
    assert frame["bounds_mm"]["min"] == pytest.approx(list(low), abs=5e-4)
    assert frame["bounds_mm"]["max"] == pytest.approx(list(high), abs=5e-4)


@pytest.mark.parametrize("name,spec", _corner_params())
def test_every_line_lies_inside_the_frame_it_is_stated_in(name, spec):
    """A callout outside the bounding box the viewer frames the camera from would be
    drawn off screen, which is the one failure that looks like no callout at all."""
    result = compile_spec(spec)
    view = view_for(spec, result)
    low = view["frame"]["bounds_mm"]["min"]
    high = view["frame"]["bounds_mm"]["max"]
    for c in view["callouts"]:
        for point in (c["from"], c["to"]):
            for i, value in enumerate(point):
                assert low[i] - 1e-6 <= value <= high[i] + 1e-6, (
                    f"{name}/{c['feature']} leaves the frame on {'XYZ'[i]}"
                )


# ── the deck box, which is the acceptance criterion ───────────────────────────

def test_the_deck_boxs_tier_1_is_the_five_figures_the_issue_names():
    """Cavity width, depth and height; the lip; the lid's engagement. These are what the
    720 px step shows, and what a person cannot check by looking at the outside."""
    tier_1 = [
        c["feature"] for c in deck_box.callouts(example_spec("deck_box"))
        if c["tier"] == CALLOUT_TIER_INTERNAL
    ]
    assert tier_1 == list(deck_box.TIER_1_FEATURES)
    assert set(tier_1) == {
        "cavity_width_mm", "cavity_depth_mm", "cavity_height_mm",
        "lip_height_mm", "lid_cavity_height_mm",
    }


def test_the_deck_boxs_lid_callouts_carry_the_plate_offset():
    """The lid is compiled `PLATE_GAP_MM` to +X of the body, not on top of it. A lid
    callout anchored in lid-local coordinates would land inside the body."""
    spec = example_spec("deck_box")
    d = deck_box.derive(spec)
    edge = d.external_w + deck_box.PLATE_GAP_MM
    lid_callouts = [c for c in deck_box.callouts(spec) if c["part"] == "lid"]
    assert lid_callouts
    for c in lid_callouts:
        assert min(c["from"][0], c["to"][0]) >= edge - 1e-9, c["feature"]


def test_the_cavity_width_runs_between_the_two_planes_measure_reads_it_between():
    """Named rather than swept, because it is the one anchor the whole feature is for."""
    spec = example_spec("deck_box")
    d = deck_box.derive(spec)
    width = next(
        c for c in deck_box.callouts(spec) if c["feature"] == "cavity_width_mm"
    )
    assert width["from"][0] == pytest.approx(spec.process.wall_mm)
    assert width["to"][0] == pytest.approx(spec.process.wall_mm + d.cavity_w)
    assert width["part"] == "body"


# ── the helper's own refusals ─────────────────────────────────────────────────

def test_a_line_that_disagrees_with_its_label_is_refused():
    with pytest.raises(MeasureError) as exc:
        callout("wall_mm", "Wall", 2.4, part="body",
                frm=(0.0, 0.0, 0.0), to=(3.0, 0.0, 0.0), offset=(0.0, 0.0, 1.0))
    assert "labelled 2.4 mm and drawn 3.000000 mm" in str(exc.value)


def test_a_diagonal_line_is_refused():
    with pytest.raises(MeasureError) as exc:
        callout("wall_mm", "Wall", 2.4, part="body",
                frm=(0.0, 0.0, 0.0), to=(2.4, 2.4, 0.0), offset=(0.0, 0.0, 1.0))
    assert "axis-aligned" in str(exc.value)
