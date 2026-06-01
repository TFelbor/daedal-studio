"""
engineer.py — Phase 3: Mesh repair, orientation, scaling, and optional hollowing.

Usage:
    python pythonsrc/engineer.py [input] [output] [target_mm] [--hollow] [--wall MM] [--verbose]
"""

import logging
import os
import sys
from pathlib import Path

import numpy as np
import pymeshfix  # MeshFix algorithm — Attene 2010; version 0.18.1
import trimesh
import trimesh.repair
import trimesh.util

# ── Logging ──────────────────────────────────────────────────────────────────
logger = logging.getLogger("p2p.engineer")


def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        format="[%(levelname)s] %(name)s — %(message)s",
        level=level,
    )


# ── Engineer ──────────────────────────────────────────────────────────────────
class Engineer:
    """Post-processes a raw mesh into a print-ready file."""

    def __init__(self, target_dimensions: float | None = None, layer_height: float = 0.2) -> None:
        self.target_dimensions = target_dimensions
        self.layer_height = layer_height

    # ── Repair ────────────────────────────────────────────────────────────────
    def repair_mesh(self, mesh: trimesh.Trimesh) -> trimesh.Trimesh:
        """
        Repair mesh topology using pymeshfix (MeshFix algorithm, Attene 2010).

        Handles self-intersections, non-manifold edges, and topological holes
        that trimesh's built-in repair cannot fix. Falls back to trimesh-only
        repair if pymeshfix raises an exception.

        pymeshfix version: 0.18.1
        """
        before_faces = len(mesh.faces)
        before_watertight = mesh.is_watertight
        logger.debug(
            "Before repair — watertight: %s, faces: %d",
            before_watertight,
            before_faces,
        )

        try:
            # ── Pre-clean: remove degeneracies before passing to pymeshfix ────
            # pymeshfix performs better on pre-cleaned input.
            pre = mesh.copy()

            # Remove degenerate faces (trimesh 4.x API)
            valid_mask = pre.nondegenerate_faces()
            pre.update_faces(valid_mask)

            # Remove duplicate faces via np.unique on sorted face rows
            sorted_faces = np.sort(pre.faces, axis=1)
            _, unique_idx = np.unique(sorted_faces, axis=0, return_index=True)
            pre.update_faces(unique_idx)

            # Remove unreferenced vertices
            pre.remove_unreferenced_vertices()

            # ── pymeshfix repair (MeshFix algorithm) ──────────────────────────
            # Note: pymeshfix 0.18.1 repair() takes no verbose kwarg;
            # repaired arrays are available as .points and .faces.
            meshfix = pymeshfix.MeshFix(pre.vertices, pre.faces)
            meshfix.repair()
            clean_vertices, clean_faces = meshfix.points, meshfix.faces

            # ── Reconstruct trimesh from repaired arrays ───────────────────────
            repaired = trimesh.Trimesh(
                vertices=clean_vertices,
                faces=clean_faces,
                process=False,
            )

            # ── Final winding-consistency pass ────────────────────────────────
            trimesh.repair.fix_normals(repaired, multibody=True)

            after_faces = len(repaired.faces)
            after_watertight = repaired.is_watertight
            improved = (not before_watertight and after_watertight) or (before_watertight and after_watertight)
            logger.debug(
                "After pymeshfix repair — watertight: %s, faces: %d (improved: %s)",
                after_watertight,
                after_faces,
                improved,
            )
            return repaired

        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "pymeshfix repair failed (%s) — falling back to trimesh-only repair.",
                exc,
            )
            return self._repair_mesh_fallback(mesh)

    def _repair_mesh_fallback(self, mesh: trimesh.Trimesh) -> trimesh.Trimesh:
        """
        Original trimesh-only repair logic, preserved as a fallback.

        Called automatically when pymeshfix raises an exception.
        Compatible with trimesh 4.x, where remove_degenerate_faces /
        remove_duplicate_faces are no longer instance methods.
        """
        repaired = mesh.copy()

        # ── Remove degenerate faces (trimesh 4.x API) ──────────────────────
        valid_mask = repaired.nondegenerate_faces()
        repaired.update_faces(valid_mask)

        # ── Remove duplicate faces ─────────────────────────────────────────
        sorted_faces = np.sort(repaired.faces, axis=1)
        _, unique_idx = np.unique(sorted_faces, axis=0, return_index=True)
        repaired.update_faces(unique_idx)

        # ── Remove unreferenced vertices (still present in 4.x) ───────────
        repaired.remove_unreferenced_vertices()

        # ── Normals, winding, holes ────────────────────────────────────────
        trimesh.repair.fix_normals(repaired, multibody=True)
        trimesh.repair.fix_winding(repaired)
        trimesh.repair.fill_holes(repaired)

        logger.debug(
            "After fallback repair — watertight: %s, faces: %d",
            repaired.is_watertight,
            len(repaired.faces),
        )
        return repaired

    # ── Scale ─────────────────────────────────────────────────────────────────
    def scale_to_dimensions(self, mesh: trimesh.Trimesh, target_mm: float) -> trimesh.Trimesh:
        """Uniformly scale so the longest bounding-box edge equals *target_mm* mm."""
        current_size = mesh.bounds[1] - mesh.bounds[0]
        max_dim = current_size.max()
        if max_dim == 0:
            logger.warning("Mesh has zero extent — skipping scale.")
            return mesh
        scale_factor = target_mm / max_dim
        scaled = mesh.copy()
        scaled.apply_scale(scale_factor)
        logger.debug("Scaled by %.4f (max dim %.2f → %.2f mm)", scale_factor, max_dim, target_mm)
        return scaled

    # ── Orient ────────────────────────────────────────────────────────────────
    def orient_for_print(self, mesh: trimesh.Trimesh) -> trimesh.Trimesh:
        """
        Centre the mesh at the origin and orient it so that the *largest flat
        face* (i.e. the axis with the greatest extent) sits on the build plate
        (Z = 0 after centring).

        Strategy:
        1. Find which axis (X/Y/Z) has the *smallest* extent — that is the
           natural "up" or "flat" axis.
        2. If that axis is already Z, nothing to do.
        3. Otherwise rotate so the smallest-extent axis maps to Z, keeping
           handedness intact via a proper rotation matrix.
        4. Translate so the bottom of the mesh sits on Z = 0.
        """
        oriented = mesh.copy()

        # Centre at origin first
        centroid = oriented.bounds.mean(axis=0)
        oriented.apply_translation(-centroid)

        extents = oriented.bounds[1] - oriented.bounds[0]  # (dx, dy, dz)
        flat_axis = int(np.argmin(extents))  # axis with smallest extent → the "flat" face

        if flat_axis != 2:
            # Build a rotation that maps flat_axis → Z (axis 2)
            # We use the cross-product to construct an orthonormal frame.
            src = np.eye(3)[flat_axis]   # e.g. [1,0,0] or [0,1,0]
            dst = np.array([0.0, 0.0, 1.0])
            axis = np.cross(src, dst)
            axis_norm = np.linalg.norm(axis)
            if axis_norm < 1e-8:
                # src and dst are anti-parallel (flat_axis==2 already handled)
                axis = np.array([1.0, 0.0, 0.0])
                angle = np.pi
            else:
                axis = axis / axis_norm
                angle = np.arccos(np.clip(np.dot(src, dst), -1.0, 1.0))
            R = trimesh.transformations.rotation_matrix(angle, axis)
            oriented.apply_transform(R)
            logger.debug("Rotated %.1f° around %s to align flat axis to Z", np.degrees(angle), axis)

        # Translate so the bottom sits on Z = 0
        z_min = oriented.bounds[0][2]
        oriented.apply_translation([0.0, 0.0, -z_min])
        return oriented

    # ── Hollow (voxel-based shell, Strategy A) ────────────────────────────────
    def hollow_mesh(self, mesh: trimesh.Trimesh, wall_thickness: float = 1.2) -> trimesh.Trimesh:
        """
        Create a hollow shell using voxelisation.

        Strategy A:
        - Voxelise the mesh at a pitch equal to *wall_thickness*.
        - Erode the voxel grid by one voxel layer inward to get the interior volume.
        - Subtract the interior from the original voxel grid to get the shell.
        - Convert back to a mesh.

        This approach requires no external boolean engine (no Blender dependency).
        """
        logger.info("Hollowing mesh with voxel strategy (wall=%.2f mm)…", wall_thickness)
        try:
            # Pitch determines voxel size = wall thickness
            pitch = wall_thickness
            vox = mesh.voxelized(pitch=pitch)
            vox_filled = vox.fill()  # ensure interior is fully filled

            # Erode by 1 voxel (= 1 wall layer) to get the inner void
            matrix = vox_filled.matrix.copy()
            from scipy.ndimage import binary_erosion
            inner = binary_erosion(matrix, iterations=1)

            # Shell = filled minus inner
            shell_matrix = matrix & ~inner

            # Reconstruct mesh from shell voxels
            shell_vox = trimesh.voxel.VoxelGrid(shell_matrix, vox_filled.transform)
            hollow = shell_vox.marching_cubes
            logger.info(
                "Hollow mesh — faces: %d, watertight: %s",
                len(hollow.faces),
                hollow.is_watertight,
            )
            return hollow
        except Exception as exc:
            logger.warning("Hollowing failed (%s) — returning solid mesh.", exc)
            return mesh

    # ── Analysis ──────────────────────────────────────────────────────────────
    def analyze_mesh(self, mesh: trimesh.Trimesh) -> dict:
        return {
            "vertices": len(mesh.vertices),
            "faces": len(mesh.faces),
            "is_watertight": mesh.is_watertight,
            "is_convex": mesh.is_convex,
            "volume_mm3": round(mesh.volume, 2) if mesh.is_volume else 0,
            "bounds": mesh.bounds.tolist() if mesh.bounds is not None else None,
            "extent_mm": (mesh.bounds[1] - mesh.bounds[0]).tolist() if mesh.bounds is not None else None,
            "euler_number": mesh.euler_number if hasattr(mesh, "euler_number") else None,
        }

    # ── Main process ──────────────────────────────────────────────────────────
    def process(
        self,
        input_path: str | Path,
        output_path: str | Path,
        target_mm: float = 50.0,
        hollow: bool = False,
        wall_thickness: float = 1.2,
    ) -> Path:
        input_path = Path(input_path)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        logger.info("Loading mesh: %s", input_path)
        mesh = trimesh.load(str(input_path), force="mesh")
        logger.info("Input analysis: %s", self.analyze_mesh(mesh))

        logger.info("Repairing mesh…")
        mesh = self.repair_mesh(mesh)

        logger.info("Orienting for print…")
        mesh = self.orient_for_print(mesh)

        scale_target = self.target_dimensions if self.target_dimensions else target_mm
        logger.info("Scaling to %.1f mm…", scale_target)
        mesh = self.scale_to_dimensions(mesh, scale_target)

        if hollow:
            logger.info("Hollowing mesh…")
            mesh = self.hollow_mesh(mesh, wall_thickness)

        mesh.export(str(output_path))
        logger.info("Engineering complete → %s", output_path)
        logger.info("Output analysis: %s", self.analyze_mesh(mesh))
        return output_path


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="p2p-mesh Phase 3 — Engineer")
    parser.add_argument("input", nargs="?", default="outputs/test_mesh.obj", help="Input .obj path")
    parser.add_argument("output", nargs="?", default="outputs/engineered_mesh.obj", help="Output .obj path")
    parser.add_argument("target_mm", nargs="?", type=float, default=50.0, help="Target longest dimension in mm")
    parser.add_argument("--hollow", action="store_true", help="Apply voxel-based hollowing")
    parser.add_argument("--wall", type=float, default=1.2, metavar="MM", help="Wall thickness in mm (default: 1.2)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    _setup_logging(args.verbose)

    eng = Engineer()
    eng.process(
        input_path=args.input,
        output_path=args.output,
        target_mm=args.target_mm,
        hollow=args.hollow,
        wall_thickness=args.wall,
    )