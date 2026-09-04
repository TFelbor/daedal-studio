"""Phase 3's assert path: a compiled mesh is checked, never repaired.

`Engineer.process` repairs unconditionally, and for a reconstruction that is the right
service. For a mesh compiled from a spec it is wrong in both directions. A compiled mesh
that is not watertight is a compiler bug, and repairing it hides the bug — through the
voxel escalation it ships a part whose dimensions are no longer the spec's while
`scale_applied: false` in the report says the dimensions were honoured. A compiled mesh
that is watertight gains nothing from repair and rounds through float32 for no reason.

`repair_mode="assert"` is the second half of the N1 fix (the scaling half is
`target_mm=None`, PR #40): check what repair would otherwise fix — watertight, no boundary
or non-manifold edges, consistent winding, kernel acceptance — and refuse, naming every
finding, instead of repairing toward it.
"""
import numpy as np
import pytest
import trimesh

from pythonsrc.engineer import Engineer, MeshAssertionError

BOX_MM = (62.0, 94.0, 31.5)
TOL_MM = 1e-3


def _write(mesh, path):
    mesh.export(str(path))
    return path


def _clean_box(tmp_path):
    return _write(trimesh.creation.box(extents=BOX_MM), tmp_path / "clean.stl")


def _open_box(tmp_path):
    """A box with one face removed: a boundary loop, not watertight."""
    box = trimesh.creation.box(extents=BOX_MM)
    box = trimesh.Trimesh(box.vertices, box.faces[1:], process=False)
    return _write(box, tmp_path / "open.stl")


def _finned_box(tmp_path):
    """A box with a third face hanging off one edge: a non-manifold edge."""
    box = trimesh.creation.box(extents=BOX_MM)
    v = np.vstack([box.vertices, [[0.0, 0.0, 200.0]]])
    a, b = box.faces[0][0], box.faces[0][1]
    faces = np.vstack([box.faces, [[a, b, len(v) - 1]]])
    return _write(trimesh.Trimesh(v, faces, process=False), tmp_path / "fin.obj")


def _extent(path):
    mesh = trimesh.load(str(path), force="mesh")
    return mesh.bounds[1] - mesh.bounds[0]


# ── the happy path ─────────────────────────────────────────────────────────────

def test_assert_mode_passes_a_clean_mesh_through_unchanged(tmp_path):
    eng = Engineer()
    out = eng.process(input_path=_clean_box(tmp_path), output_path=tmp_path / "out.obj",
                      target_mm=None, repair_mode="assert")
    assert _extent(out) == pytest.approx(np.array(BOX_MM), abs=TOL_MM)
    assert out.with_suffix(".stl").exists()


def test_assert_mode_is_recorded_as_its_own_repair_method(tmp_path):
    """`repair_method` already distinguishes manifold / trimesh_fallback / voxel_remesh;
    "asserted" is the fourth value, so "which path ran" stays one query."""
    eng = Engineer()
    eng.process(input_path=_clean_box(tmp_path), output_path=tmp_path / "out.obj",
                target_mm=None, repair_mode="assert")
    report = eng.last_report
    assert report["repair_method"] == "asserted"
    assert report["watertight_before"] is True and report["watertight_after"] is True
    assert report["faces_before"] == report["faces_after"] == 12
    assert report["scale_applied"] is False and report["scale_axis"] == "preserved"
    assertion = report["assertion"]
    assert assertion["boundary_edges"] == 0 and assertion["nonmanifold_edges"] == 0
    assert assertion["winding_consistent"] is True
    assert assertion["kernel_status"] == "NoError"
    assert assertion["components"] == 1


def test_assert_mode_still_seats_the_part_on_the_plate(tmp_path):
    """Orientation is a translation, not a repair, so it still runs."""
    box = trimesh.creation.box(extents=BOX_MM)
    box.apply_translation([40.0, -7.0, 12.0])
    path = _write(box, tmp_path / "offset.stl")
    out = Engineer().process(input_path=path, output_path=tmp_path / "out.obj",
                             target_mm=None, repair_mode="assert")
    mesh = trimesh.load(str(out), force="mesh")
    assert mesh.bounds[0][2] == pytest.approx(0.0, abs=TOL_MM)
    assert mesh.bounds.mean(axis=0)[:2] == pytest.approx([0.0, 0.0], abs=TOL_MM)


# ── refusals ───────────────────────────────────────────────────────────────────

def test_an_open_surface_is_refused_naming_the_boundary_edges(tmp_path):
    out = tmp_path / "out.obj"
    with pytest.raises(MeshAssertionError) as exc:
        Engineer().process(input_path=_open_box(tmp_path), output_path=out,
                           target_mm=None, repair_mode="assert")
    message = str(exc.value)
    assert "watertight" in message and "boundary edge" in message
    assert not out.exists() and not out.with_suffix(".stl").exists()


def test_a_non_manifold_edge_is_refused_by_name(tmp_path):
    with pytest.raises(MeshAssertionError) as exc:
        Engineer().process(input_path=_finned_box(tmp_path), output_path=tmp_path / "out.obj",
                           target_mm=None, repair_mode="assert")
    assert "non-manifold edge" in str(exc.value)


def test_every_finding_is_reported_not_just_the_first(tmp_path):
    """An open box with a fin has two defects; the message names both."""
    box = trimesh.creation.box(extents=BOX_MM)
    v = np.vstack([box.vertices, [[0.0, 0.0, 200.0]]])
    # The fin goes on a side the removed face does not border, so its edge is
    # shared by two faces plus the fin (non-manifold) rather than one plus the fin.
    a, b = box.faces[6][0], box.faces[6][1]
    faces = np.vstack([box.faces[1:], [[a, b, len(v) - 1]]])
    path = _write(trimesh.Trimesh(v, faces, process=False), tmp_path / "both.obj")
    with pytest.raises(MeshAssertionError) as exc:
        Engineer().process(input_path=path, output_path=tmp_path / "out.obj",
                           target_mm=None, repair_mode="assert")
    message = str(exc.value)
    assert "boundary edge" in message and "non-manifold edge" in message


def test_assert_mode_refuses_to_scale(tmp_path):
    """Asserting a mesh is exactly what was authored and then resizing it is a
    contradiction; refusing keeps "assert" meaning one thing."""
    with pytest.raises(ValueError, match="repair_mode"):
        Engineer().process(input_path=_clean_box(tmp_path), output_path=tmp_path / "out.obj",
                           target_mm=50.0, repair_mode="assert")


def test_an_unknown_repair_mode_is_refused(tmp_path):
    with pytest.raises(ValueError, match="repair_mode"):
        Engineer().process(input_path=_clean_box(tmp_path), output_path=tmp_path / "out.obj",
                           target_mm=None, repair_mode="fix")


# ── the default is untouched ───────────────────────────────────────────────────

def test_the_default_mode_still_repairs_the_open_box(tmp_path):
    """Every existing caller is a reconstruction and must keep getting repaired."""
    eng = Engineer()
    eng.process(input_path=_open_box(tmp_path), output_path=tmp_path / "out.obj")
    assert eng.last_report["repair_method"] != "asserted"
    assert eng.last_report["watertight_before"] is False
    assert eng.last_report["watertight_after"] is True


def test_assert_manifold_returns_the_findings_for_a_clean_mesh():
    findings = Engineer().assert_manifold(trimesh.creation.box(extents=BOX_MM))
    assert findings == {
        "watertight": True, "boundary_edges": 0, "nonmanifold_edges": 0,
        "winding_consistent": True, "positive_volume": True,
        "kernel_status": "NoError", "components": 1,
    }
