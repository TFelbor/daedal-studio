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
