"""Guards on Phase 3 actually closing a surface rather than reporting on one.

`repair_mesh` composes trimesh (surface closing) with manifold3d (the manifold
guarantee), and the trimesh half had a hole in it: nothing in the chain could
remove a **non-manifold edge**. `fix_normals` and `fix_winding` reorder faces,
`fill_holes` adds them, `merge_vertices` welds coincident ones — none of them can
delete a third face hanging off an edge. So a mesh that arrived with non-manifold
edges left "repair" with exactly the same count, the kernel answered
`Error.NotManifold`, and the code shipped the unrepaired surface. Downstream that
reads as repair failing outright: the slicer gets a mesh with no consistent
inside and printability scores it unprintable at every face count.

The second half of the hole was hole-shaped. `trimesh.repair.fill_holes` only
fans over triangle and quad boundary loops, so anything larger stayed open.

These tests are built from primitives rather than fixtures on disk, so they run
without a sculptor, a GPU, or a paid API call.
"""

import numpy as np
import pytest
import trimesh

from pythonsrc.engineer import Engineer

manifold3d = pytest.importorskip("manifold3d")


# ── Broken-mesh builders ──────────────────────────────────────────────────────
def _edge_counts(mesh: trimesh.Trimesh) -> np.ndarray:
    edges = mesh.edges_sorted.astype(np.int64)
    keys = edges[:, 0] * (len(mesh.vertices) + 1) + edges[:, 1]
    return np.unique(keys, return_counts=True)[1]


def _boundary_edges(mesh: trimesh.Trimesh) -> int:
    return int((_edge_counts(mesh) == 1).sum())


def _nonmanifold_edges(mesh: trimesh.Trimesh) -> int:
    return int((_edge_counts(mesh) > 2).sum())


def _kernel_accepts(mesh: trimesh.Trimesh) -> bool:
    """Whether manifold3d will take this mesh — the gate Phase 4 depends on."""
    gl = manifold3d.Mesh(
        vert_properties=np.asarray(mesh.vertices, dtype=np.float32),
        tri_verts=np.asarray(mesh.faces, dtype=np.uint32),
    )
    gl.merge()
    return manifold3d.Manifold(gl).status() == manifold3d.Error.NoError


def _with_fins(subdivisions: int = 3, count: int = 1, seed: int = 0) -> trimesh.Trimesh:
    """A closed sphere with tetrahedral fins glued onto faces.

    Each fin shares all three edges of the face it covers, so every one of those
    edges carries three faces. This is what an isosurface leaves behind, and the
    fin triangles are *larger* than the face beneath them — which is why ranking
    candidates by area picks the wrong two to keep.
    """
    sphere = trimesh.creation.icosphere(subdivisions=subdivisions)
    vertices, faces = sphere.vertices.copy(), sphere.faces.copy()
    picks = np.random.default_rng(seed).choice(len(faces), count, replace=False)
    apex_start = len(vertices)
    vertices = np.vstack([vertices, vertices[faces[picks]].mean(axis=1) * 1.4])
    fins = []
    for offset, face_index in enumerate(picks):
        a, b, c = faces[face_index]
        apex = apex_start + offset
        fins += [[a, b, apex], [b, c, apex], [c, a, apex]]
    return trimesh.Trimesh(
        vertices=vertices, faces=np.vstack([faces, np.array(fins)]), process=False
    )


def _with_hole(faces_removed: int, subdivisions: int = 3) -> trimesh.Trimesh:
    """A sphere with a contiguous patch of faces deleted."""
    sphere = trimesh.creation.icosphere(subdivisions=subdivisions)
    keep = np.ones(len(sphere.faces), dtype=bool)
    keep[np.arange(faces_removed)] = False
    return trimesh.Trimesh(
        vertices=sphere.vertices, faces=sphere.faces[keep], process=False
    )


# ── The defect that made repair a no-op ───────────────────────────────────────
def test_nonmanifold_edges_are_removed():
    broken = _with_fins(count=1)
    assert _nonmanifold_edges(broken) == 3, "builder must produce the defect"

    repaired = Engineer().repair_mesh(broken)

    assert _nonmanifold_edges(repaired) == 0
    assert _boundary_edges(repaired) == 0
    assert repaired.is_watertight
    assert _kernel_accepts(repaired)


def test_many_fins_are_removed_without_destroying_the_surface():
    """The whole point of the connectivity heuristic.

    Ranked by area, the fin triangles beat the surface underneath them: 200 fins
    cost 440 faces and left 322 boundary edges no later round could close, and
    the mesh had to be rebuilt volumetrically — losing every sharp feature. Ranked
    by how embedded each face is, the fins go and the surface stays.
    """
    broken = _with_fins(subdivisions=4, count=200, seed=1)
    sphere_volume = trimesh.creation.icosphere(subdivisions=4).volume

    repaired = Engineer().repair_mesh(broken)

    assert repaired.is_watertight
    assert _kernel_accepts(repaired)
    # The fins are gone and the sphere is intact, so the volume is the sphere's.
    assert repaired.volume == pytest.approx(sphere_volume, rel=0.02)


def test_hole_too_large_for_fill_holes_is_still_closed():
    """`fill_holes` fans over triangles and quads only; this loop is 40 edges."""
    broken = _with_hole(faces_removed=60, subdivisions=3)
    assert _boundary_edges(broken) > 4

    only_fill = broken.copy()
    trimesh.repair.fill_holes(only_fill)
    assert not only_fill.is_watertight, "if trimesh closes this, the test is moot"

    repaired = Engineer().repair_mesh(broken)

    assert repaired.is_watertight
    assert _kernel_accepts(repaired)


def test_unwelded_surface_is_welded_before_topology_is_judged():
    """A mesh split at every seam looks like confetti to the edge counts."""
    sphere = trimesh.creation.icosphere(subdivisions=3)
    # Explode it: every face gets its own copy of its three vertices.
    exploded = trimesh.Trimesh(
        vertices=sphere.vertices[sphere.faces].reshape(-1, 3),
        faces=np.arange(len(sphere.faces) * 3).reshape(-1, 3),
        process=False,
    )
    assert _boundary_edges(exploded) == len(sphere.faces) * 3

    repaired = Engineer().repair_mesh(exploded)

    assert repaired.is_watertight
    assert repaired.volume == pytest.approx(sphere.volume, rel=1e-6)


# ── What repair must not do ───────────────────────────────────────────────────
def test_a_clean_mesh_is_left_alone():
    """Repair is not licensed to resample a mesh that was already printable.

    Not bit-exact: `_to_manifold` hands vertices to the kernel as float32, so a
    clean mesh still round-trips through single precision and its volume moves in
    the eighth significant digit. On a 50mm part that is well under a micron —
    two orders of magnitude below a 0.4mm nozzle — but it is not zero, and a
    tolerance of 1e-9 would be asserting something untrue.
    """
    clean = trimesh.creation.icosphere(subdivisions=4)

    repaired = Engineer().repair_mesh(clean)

    assert len(repaired.faces) == len(clean.faces)
    assert repaired.volume == pytest.approx(clean.volume, rel=1e-6)


def test_repair_is_idempotent():
    once = Engineer().repair_mesh(_with_fins(count=3, seed=2))
    twice = Engineer().repair_mesh(once)

    assert len(twice.faces) == len(once.faces)
    assert twice.volume == pytest.approx(once.volume, rel=1e-9)


# ── The last resort ───────────────────────────────────────────────────────────
def test_voxel_remesh_closes_a_surface_and_is_not_decimated():
    """The escalation's guarantee, and why it keeps its face count.

    Decimating a marching-cubes surface back to the input budget was measured
    reintroducing hundreds of non-manifold edges — trading the defect the remesh
    exists to remove for a smaller file.
    """
    broken = _with_hole(faces_removed=200, subdivisions=4)

    remeshed = Engineer()._voxel_remesh(broken)

    assert remeshed is not None
    assert remeshed.is_watertight
    assert _nonmanifold_edges(remeshed) == 0
    assert len(remeshed.faces) > len(broken.faces)


def test_kernel_rejection_escalates_to_a_remesh(monkeypatch):
    """A mesh the kernel refuses must not be shipped as "repaired"."""
    engineer = Engineer()
    calls = {"remesh": 0}
    real_remesh = engineer._voxel_remesh

    def counting_remesh(mesh):
        calls["remesh"] += 1
        return real_remesh(mesh)

    # Force the kernel to refuse the closed surface exactly once, the way a
    # genuinely non-orientable input would.
    real_to_manifold = engineer._to_manifold
    state = {"refused": False}

    def refuse_first(mesh):
        if not state["refused"]:
            state["refused"] = True
            return manifold3d.Manifold(manifold3d.Mesh(
                vert_properties=np.zeros((3, 3), dtype=np.float32),
                tri_verts=np.array([[0, 1, 2], [0, 1, 2]], dtype=np.uint32),
            ))
        return real_to_manifold(mesh)

    monkeypatch.setattr(engineer, "_voxel_remesh", counting_remesh)
    monkeypatch.setattr(engineer, "_to_manifold", refuse_first)

    repaired = engineer.repair_mesh(_with_fins(count=2, seed=3))

    assert calls["remesh"] == 1, "rejection must escalate, not return the reject"
    assert repaired.is_watertight


def test_analyze_mesh_reports_both_edge_defect_kinds():
    """"Not watertight" does not say which repair is needed; these numbers do."""
    report = Engineer().analyze_mesh(_with_fins(count=1))

    assert report["nonmanifold_edges"] == 3
    assert report["boundary_edges"] == 0
    assert report["is_watertight"] is False
