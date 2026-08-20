"""Printability checks, tested against geometry whose defects are known by construction.

Each fixture is built to fail exactly one check, so a regression points at one rule
rather than at "the score moved".
"""

import json

import numpy as np
import pytest
import trimesh

from pythonsrc.printability import (
    CheckResult,
    PrintabilityReport,
    ProcessProfile,
    evaluate_printability,
)


def on_bed(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """Drop a mesh so its lowest point is the first layer, as the Engineer leaves it."""
    m = mesh.copy()
    m.apply_translation([0, 0, -m.bounds[0][2]])
    return m


@pytest.fixture(scope="module")
def fdm() -> ProcessProfile:
    return ProcessProfile()


@pytest.fixture(scope="module")
def clean_box_report(fdm) -> PrintabilityReport:
    """One evaluation of a defect-free box, shared by the assertions that only read it."""
    return evaluate_printability(on_bed(trimesh.creation.box(extents=[30, 30, 20])), fdm)


def check(report: PrintabilityReport, name: str) -> CheckResult:
    """Pull one check out of a report by name."""
    matches = [c for c in report.checks if c.check == name]
    assert matches, f"report has no check named {name}"
    return matches[0]


# ── Clean geometry ────────────────────────────────────────────────────────────


def test_solid_box_is_ready(clean_box_report):
    report = clean_box_report
    assert report.verdict == "ready"
    assert report.score == 100.0
    assert report.failed() == []


def test_features_snapshot_is_populated(clean_box_report):
    """The feature snapshot is the Bet-2 training input; every field must be filled."""
    report = clean_box_report
    f = report.features
    assert f["face_count"] == 12
    assert f["is_watertight"] is True
    assert f["volume_mm3"] == pytest.approx(30 * 30 * 20, rel=1e-3)
    assert f["component_count"] == 1
    assert f["min_wall_thickness_mm"] is not None
    assert f["overhang_area_fraction"] == 0.0
    assert f["bed_contact_mm2"] == pytest.approx(900.0, rel=1e-3)


# ── Topology ──────────────────────────────────────────────────────────────────


def test_open_shell_fails_watertight(fdm):
    box = trimesh.creation.box(extents=[20, 20, 20])
    box.update_faces(np.arange(len(box.faces)) > 1)          # cut two faces = a hole
    report = evaluate_printability(on_bed(box), fdm)

    assert check(report, "watertight").status == "fail"
    assert report.verdict == "unprintable"
    assert report.features["boundary_edge_count"] > 0


def test_open_shell_does_not_report_a_wall_thickness(fdm):
    """Voxel filling cannot tell inside from outside on an open mesh, so it must abstain."""
    box = trimesh.creation.box(extents=[20, 20, 20])
    box.update_faces(np.arange(len(box.faces)) > 1)
    report = evaluate_printability(on_bed(box), fdm)

    wall = check(report, "min_wall_thickness")
    assert wall.status == "not_checked"
    assert wall.value is None
    assert "closed volume" in wall.detail


def test_non_manifold_edge_is_counted(fdm):
    """Three faces sharing one edge — geometry no slicer can interpret."""
    fan = trimesh.Trimesh(
        vertices=np.array([[0, 0, 0], [10, 0, 0], [0, 10, 0], [0, 0, 10], [10, 10, 10]], dtype=float),
        faces=np.array([[0, 1, 2], [0, 1, 3], [0, 1, 4]]),
        process=False,
    )
    report = evaluate_printability(fan, fdm)
    assert check(report, "non_manifold_edges").status == "fail"
    assert report.features["non_manifold_edge_count"] == 1


# ── Wall thickness ────────────────────────────────────────────────────────────


def test_wall_below_nozzle_minimum_fails(fdm):
    """A 0.5mm plate cannot be extruded by a 0.4mm nozzle needing 0.8mm walls."""
    report = evaluate_printability(on_bed(trimesh.creation.box(extents=[12, 12, 0.5])), fdm)

    wall = check(report, "min_wall_thickness")
    assert wall.status == "fail"
    assert wall.value < fdm.min_wall_mm
    assert report.verdict == "unprintable"


def test_thick_enough_wall_passes(fdm):
    report = evaluate_printability(on_bed(trimesh.creation.box(extents=[12, 12, 1.2])), fdm)
    assert check(report, "min_wall_thickness").status == "pass"


def test_thickness_reports_its_tolerance(fdm):
    """The measurement is voxel-quantised; the report must say so rather than imply exactness."""
    report = evaluate_printability(on_bed(trimesh.creation.box(extents=[20, 20, 20])), fdm)
    assert report.features["min_wall_tolerance_mm"] > 0
    assert "±" in check(report, "min_wall_thickness").detail


# ── Components, voids, overhangs ──────────────────────────────────────────────


def test_floating_component_fails(fdm):
    parts = trimesh.util.concatenate([
        trimesh.creation.box(extents=[20, 20, 20]),
        trimesh.creation.box(extents=[6, 6, 6]).apply_translation([0, 0, 40]),
    ])
    report = evaluate_printability(on_bed(parts), fdm)

    floating = check(report, "floating_components")
    assert floating.status == "fail"
    assert floating.value["floating"] == 1
    assert report.verdict == "unprintable"


def test_sealed_void_from_hollowing_is_fatal(fdm):
    """The Engineer's voxel hollowing leaves a cavity with no drain path."""
    nested = trimesh.util.concatenate([
        trimesh.creation.icosphere(subdivisions=3, radius=15),
        trimesh.creation.icosphere(subdivisions=3, radius=8),
    ])
    report = evaluate_printability(on_bed(nested), fdm, was_hollowed=True)

    escape = check(report, "escape_hole")
    assert escape.status == "fail"
    assert escape.critical is True
    assert report.verdict == "unprintable"


def test_enclosed_void_is_not_also_counted_as_floating(fdm):
    """One defect, one penalty — an inner shell is a cavity, not a part in mid-air."""
    nested = trimesh.util.concatenate([
        trimesh.creation.icosphere(subdivisions=3, radius=15),
        trimesh.creation.icosphere(subdivisions=3, radius=8),
    ])
    report = evaluate_printability(on_bed(nested), fdm, was_hollowed=True)

    assert check(report, "floating_components").value["floating"] == 0
    assert report.features["enclosed_void_count"] == 1


def test_sphere_reports_overhang_area(fdm):
    """A sphere's lower cap overhangs; the analytic 45° cap is about 14.6% of the area."""
    report = evaluate_printability(on_bed(trimesh.creation.icosphere(subdivisions=4, radius=15)), fdm)
    assert 0.10 < report.features["overhang_area_fraction"] < 0.18


def test_flat_bottom_has_no_overhang(fdm):
    """Downward faces resting on the plate are supported by the bed, not by air."""
    report = evaluate_printability(on_bed(trimesh.creation.box(extents=[20, 20, 20])), fdm)
    assert report.features["overhang_area_fraction"] == 0.0
    assert check(report, "overhang_area").status == "pass"


def test_point_contact_warns_on_adhesion(fdm):
    report = evaluate_printability(on_bed(trimesh.creation.icosphere(subdivisions=4, radius=15)), fdm)
    assert check(report, "bed_contact").status == "warn"


# ── Process profile ───────────────────────────────────────────────────────────


def test_oversized_mesh_fails_build_volume():
    profile = ProcessProfile.from_printer_profile(json.load(open("pythonsrc/profiles/ender3.json")))
    report = evaluate_printability(on_bed(trimesh.creation.box(extents=[400, 400, 400])), profile)

    assert check(report, "build_volume_fit").status == "fail"
    assert report.verdict == "unprintable"


def test_profile_derives_limits_from_printer_profile():
    profile = ProcessProfile.from_printer_profile(json.load(open("pythonsrc/profiles/ender3.json")))
    assert profile.build_volume_mm == [220.0, 220.0, 250.0]
    assert profile.layer_height_mm == 0.2
    assert profile.min_wall_mm == pytest.approx(0.8)     # two nozzle widths


def test_profile_without_machine_keys_skips_volume_check():
    """anycubic_mega.json has no machine dimensions; the check must be omitted, not failed."""
    profile = ProcessProfile.from_printer_profile({"layer_height": 0.3})
    report = evaluate_printability(on_bed(trimesh.creation.box(extents=[400, 400, 400])), profile)
    assert [c for c in report.checks if c.check == "build_volume_fit"] == []


def test_sla_style_profile_tightens_the_wall_threshold():
    """Thresholds live in the profile, so a finer process is a config change, not a code change."""
    resin = ProcessProfile(name="sla", nozzle_diameter_mm=0.05, min_wall_mm=0.3, layer_height_mm=0.05)
    plate = on_bed(trimesh.creation.box(extents=[12, 12, 0.5]))

    assert check(evaluate_printability(plate, ProcessProfile()), "min_wall_thickness").status == "fail"
    assert check(evaluate_printability(plate, resin), "min_wall_thickness").status == "pass"


# ── Scoring and serialisation ─────────────────────────────────────────────────


def test_unavailable_check_does_not_affect_the_score(clean_box_report):
    """self_intersections cannot run without a collision engine; it must not count either way."""
    report = clean_box_report
    unavailable = check(report, "self_intersections")

    assert unavailable.status == "not_checked"
    assert report.score == 100.0          # a clean mesh still scores full marks


def test_critical_warning_is_never_ready(fdm):
    """A wall inside measurement tolerance of the limit is not something to call ready."""
    report = evaluate_printability(on_bed(trimesh.creation.box(extents=[12, 12, 0.9])), fdm)
    wall = check(report, "min_wall_thickness")
    if wall.status == "warn":
        assert report.verdict != "ready"


def test_report_round_trips_through_json(fdm):
    report = evaluate_printability(on_bed(trimesh.creation.box(extents=[30, 30, 20])), fdm, job_id="job-1")
    restored = PrintabilityReport.from_dict(json.loads(json.dumps(report.to_dict())))

    assert restored.job_id == "job-1"
    assert restored.score == report.score
    assert restored.verdict == report.verdict
    assert len(restored.checks) == len(report.checks)
    assert restored.features == report.features
    assert restored.evaluated_at == report.evaluated_at
