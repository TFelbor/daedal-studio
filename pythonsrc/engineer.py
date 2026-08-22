"""
engineer.py — Phase 3: Mesh repair, orientation, scaling, and optional hollowing.

Usage:
    python pythonsrc/engineer.py [input] [output] [target_mm] [--hollow] [--wall MM] [--verbose]
"""

import logging
import os
import sys
from pathlib import Path

try:
    from config import OUTPUTS_DIR
except ImportError:  # pragma: no cover - depends on how the caller set sys.path
    from pythonsrc.config import OUTPUTS_DIR  # type: ignore[no-redef]

import numpy as np
import manifold3d  # Apache-2.0 — guaranteed-manifold kernel; version 3.5.x
import trimesh
import trimesh.repair
import trimesh.util

# ── Repair tuning ────────────────────────────────────────────────────────────
# Closing a surface is iterative: dropping a non-manifold fin opens a hole, and
# stitching a hole can leave a non-manifold seam behind. Both converge in two or
# three passes on real meshes; the cap is a runaway guard, not a target.
MAX_CLOSE_ROUNDS = 8

# Voxel grid resolution for the last-resort remesh, as a divisor of the mesh's
# longest extent. Scale-invariant on purpose — repair runs before Phase 3 scales
# the part, so an absolute pitch would mean a different fidelity for every model.
VOXEL_REMESH_RESOLUTION = int(os.environ.get("P2P_REPAIR_VOXEL_RESOLUTION", "128"))

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
        # What the last `process` call actually did — which repair path ran, how
        # hard it had to work, and the scale factor applied. Everything in it was
        # previously visible only in the log, which made "did voxel remeshing hurt
        # outcomes" unanswerable from the dataset. Read it after process(); the
        # pipeline persists it to `print_job.repair_report`.
        self.last_report: dict | None = None
        self._repair_stats: dict | None = None
        self._fallback_stats: dict = {}
        self._last_scale_factor: float | None = None
        # Which axis the last scale actually used — "height", "longest", or "none"
        # when there was nothing to scale. Recorded rather than assumed: two
        # conventions now exist, and a bare `target_mm` in a historical row cannot
        # say which one produced it.
        self._last_scale_axis: str | None = None

    # ── Repair ────────────────────────────────────────────────────────────────
    @staticmethod
    def _to_manifold(mesh: trimesh.Trimesh) -> "manifold3d.Manifold":
        """
        Hand a trimesh over to the manifold3d kernel.

        ``Mesh.merge()`` welds near-coincident vertices, which is what turns a
        surface that is *visually* closed but has duplicated boundary vertices
        into one the kernel will accept. The returned Manifold may still be in
        an error state — callers must check ``.status()``.
        """
        gl = manifold3d.Mesh(
            vert_properties=np.asarray(mesh.vertices, dtype=np.float32),
            tri_verts=np.asarray(mesh.faces, dtype=np.uint32),
        )
        gl.merge()
        return manifold3d.Manifold(gl)

    @staticmethod
    def _from_manifold(man: "manifold3d.Manifold") -> trimesh.Trimesh:
        """Convert a manifold3d Manifold back into a trimesh.Trimesh."""
        gl = man.to_mesh()
        verts = np.asarray(gl.vert_properties)
        # vert_properties is (n, stride); the first three columns are XYZ.
        verts = verts.reshape(-1, gl.vert_properties.shape[-1])[:, :3]
        return trimesh.Trimesh(
            vertices=verts,
            faces=np.asarray(gl.tri_verts).reshape(-1, 3),
            process=False,
        )

    def repair_mesh(self, mesh: trimesh.Trimesh) -> trimesh.Trimesh:
        """
        Repair mesh topology with trimesh (MIT) + manifold3d (Apache-2.0).

        Replaces the previous pymeshfix implementation, which was unusable
        commercially: pymeshfix wraps MeshFix (Attene 2010), published under
        GPL/AGPL with an explicit requirement that commercial use be licensed
        separately from IMATI-GE/CNR. Linking it in-process would have made
        this pipeline a derivative work.

        The two libraries do different jobs and are used accordingly:

        * trimesh *closes* the surface — degenerate/duplicate face removal,
          winding and normal consistency, hole filling. manifold3d cannot do
          this; handed an open surface it returns ``Error.NotManifold`` and an
          empty result.
        * manifold3d *guarantees* the result — constructing a Manifold is a
          hard topological check, and a boolean union over the decomposed
          components resolves self-intersections and interpenetrating shells
          into a single well-formed solid. This is strictly what a slicer
          needs, and it is something MeshFix did not do reliably.

        Falls back to the trimesh-only result if the kernel rejects the mesh,
        so a pathological input degrades instead of failing the job.
        """
        before_faces = len(mesh.faces)
        before_watertight = mesh.is_watertight
        logger.debug(
            "Before repair — watertight: %s, faces: %d",
            before_watertight,
            before_faces,
        )

        self._fallback_stats = {}

        def note(method: str, result: trimesh.Trimesh, unioned: int = 0) -> trimesh.Trimesh:
            # One record per repair, written at whichever exit actually ships a
            # mesh — the log already says all of this, but a log line cannot be
            # joined against a print outcome.
            self._repair_stats = {
                "repair_method": method,
                "watertight_before": bool(before_watertight),
                "watertight_after": bool(result.is_watertight),
                "faces_before": before_faces,
                "faces_after": len(result.faces),
                "unioned_components": unioned,
                **self._fallback_stats,
            }
            return result

        try:
            # ── Stage 1: close the surface with trimesh ───────────────────────
            # manifold3d validates topology, it does not create it. Anything
            # still open here will be rejected by the kernel below.
            closed = self._repair_mesh_fallback(mesh)

            # ── Stage 2: hand to the manifold3d kernel ────────────────────────
            man = self._to_manifold(closed)
            if man.status() != manifold3d.Error.NoError:
                # Stage 1 could not close this surface by editing its topology.
                # Shipping the reject is what made repair look like a no-op: the
                # slicer gets a mesh with no consistent inside, and printability
                # scores it as unprintable no matter what face count it is asked
                # for. Rebuild the surface volumetrically instead.
                logger.warning(
                    "manifold3d rejected the repaired surface (%s) — escalating to "
                    "a volumetric remesh.",
                    man.status(),
                )
                remeshed = self._voxel_remesh(closed)
                if remeshed is None:
                    return note("trimesh_fallback", closed)
                man = self._to_manifold(remeshed)
                if man.status() != manifold3d.Error.NoError:
                    logger.warning(
                        "manifold3d rejected the remesh too (%s) — keeping "
                        "trimesh-only repair.",
                        man.status(),
                    )
                    return note("trimesh_fallback", closed)
                closed = remeshed
                via_remesh = True
            else:
                via_remesh = False

            # ── Stage 3: union the components ─────────────────────────────────
            # Interpenetrating shells are common in generated meshes and are a
            # slicing hazard: overlapping volume gets counted twice and the
            # slicer sees contradictory inside/outside tests. A boolean union
            # collapses them into one solid.
            parts = man.decompose()
            unioned = 0
            if len(parts) > 1:
                man = manifold3d.Manifold.batch_boolean(parts, manifold3d.OpType.Add)
                if man.status() != manifold3d.Error.NoError:
                    logger.warning(
                        "manifold3d union failed (%s) — keeping trimesh-only repair.",
                        man.status(),
                    )
                    return note("voxel_remesh" if via_remesh else "trimesh_fallback", closed)
                logger.debug("Unioned %d interpenetrating components into one solid.", len(parts))
                unioned = len(parts)

            if man.is_empty():
                logger.warning("manifold3d produced an empty solid — keeping trimesh-only repair.")
                return note("voxel_remesh" if via_remesh else "trimesh_fallback", closed)

            repaired = self._from_manifold(man)

            after_watertight = repaired.is_watertight
            improved = after_watertight and not before_watertight
            logger.debug(
                "After manifold3d repair — watertight: %s, faces: %d, genus: %d (improved: %s)",
                after_watertight,
                len(repaired.faces),
                man.genus(),
                improved,
            )
            return note("voxel_remesh" if via_remesh else "manifold", repaired, unioned)

        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "manifold3d repair failed (%s) — falling back to trimesh-only repair.",
                exc,
            )
            return note("trimesh_fallback", self._repair_mesh_fallback(mesh))

    @staticmethod
    def _edge_face_counts(mesh: trimesh.Trimesh) -> tuple[np.ndarray, np.ndarray]:
        """Map every per-face edge to its shared edge, and count the sharers.

        Vertex pairs are folded into one int64 key rather than passed to
        ``np.unique(axis=0)``, which sorts rows through an object-dtype view and
        costs 16x more on an 80k-face mesh — measured 0.216s against 0.014s.
        This runs once per repair round, so the difference is the difference
        between a repair that is free and one that is felt.

        Returns:
            ``(inverse, counts)`` where ``inverse[i]`` is the shared-edge id of
            per-face edge ``i`` and ``counts[j]`` is how many faces touch shared
            edge ``j``. A closed manifold surface has every count exactly 2:
            1 is a boundary edge (a hole), 3+ is a non-manifold edge (a fin,
            a flap, or two shells fused along a seam).
        """
        edges = mesh.edges_sorted.astype(np.int64)
        stride = int(mesh.vertices.shape[0]) + 1
        keys = edges[:, 0] * stride + edges[:, 1]
        _, inverse, counts = np.unique(keys, return_inverse=True, return_counts=True)
        return inverse, counts

    @classmethod
    def _drop_nonmanifold_faces(cls, mesh: trimesh.Trimesh) -> int:
        """Delete the faces that make an edge non-manifold. Mutates *mesh*.

        Nothing else in this chain could do this, which is why repair used to
        fail outright on generated meshes. ``fix_normals`` and ``fix_winding``
        reorder faces, ``fill_holes`` adds them, and ``merge_vertices`` welds
        coincident ones — none of them can remove a third face hanging off an
        edge, so a mesh with non-manifold edges came out of "repair" with the
        same count it went in with and the manifold3d kernel rejected it.

        For an edge carrying more than two faces, two are kept and the rest
        dropped. *Which* two decides whether this repairs the mesh or destroys
        it, and area alone is the wrong answer: a fin sticking out of the
        surface is often the larger triangle, so ranking by area keeps the fin
        and deletes the surface under it. Measured on an 80k-face sphere with
        200 fins, area dropped 440 faces and left 322 boundary edges that no
        later round could close; the mesh then had to be rebuilt volumetrically,
        losing all its detail.

        Faces are therefore ranked by **how many of their own three edges are
        cleanly manifold** — a face embedded in the surface scores 3, a fin
        hanging off it scores 0 or 1 — with area only as a tie-break. Same mesh,
        same budget: 198 faces dropped, closed in one round, detail intact.

        Returns:
            How many faces were dropped.
        """
        inverse, counts = cls._edge_face_counts(mesh)
        over_shared = (counts > 2)[inverse]
        if not over_shared.any():
            return 0

        # How many cleanly-shared edges each face sits on. `edges_face` maps
        # per-face edges back to their face, so this is a weighted bincount.
        clean_edges = np.bincount(
            mesh.edges_face,
            weights=(counts == 2)[inverse].astype(np.float64),
            minlength=len(mesh.faces),
        )

        # Rank within each over-shared edge and drop everything past the first
        # two. lexsort applies keys last-first: group by edge, then most-embedded
        # first, then largest first.
        edge_ids = inverse[over_shared]
        faces = mesh.edges_face[over_shared]
        order = np.lexsort((-mesh.area_faces[faces], -clean_edges[faces], edge_ids))
        edge_ids, faces = edge_ids[order], faces[order]
        group_starts = np.r_[True, edge_ids[1:] != edge_ids[:-1]]
        positions = np.arange(len(edge_ids))
        rank_in_group = positions - np.maximum.accumulate(
            np.where(group_starts, positions, 0)
        )
        doomed = np.unique(faces[rank_in_group >= 2])

        keep = np.ones(len(mesh.faces), dtype=bool)
        keep[doomed] = False
        mesh.update_faces(keep)
        mesh.remove_unreferenced_vertices()
        return int(len(doomed))

    def _repair_mesh_fallback(self, mesh: trimesh.Trimesh) -> trimesh.Trimesh:
        """
        trimesh-only repair: clean degeneracies, then close the surface.

        This is both stage 1 of :meth:`repair_mesh` and its fallback — the
        manifold3d kernel needs a closed surface as input, and if the kernel
        then rejects the result this is what ships. Pure MIT, no copyleft.

        Closing is a *loop*, not a sequence. Dropping a non-manifold fin opens
        a hole where it was attached; filling a hole, or stitching a boundary
        loop too large for ``fill_holes`` to fan over, can fuse two faces onto
        one edge and create a fresh non-manifold seam. Running each step once —
        which is what this method used to do — leaves whichever defect the
        other step created. Both converge in two or three rounds on real
        meshes.

        Compatible with trimesh 4.x, where remove_degenerate_faces /
        remove_duplicate_faces are no longer instance methods.
        """
        repaired = mesh.copy()

        # ── Weld coincident vertices ───────────────────────────────────────
        # An exporter that splits vertices at normal or UV seams turns one
        # closed surface into a pile of disconnected triangles that merely look
        # closed. Every count below is meaningless until this has run.
        repaired.merge_vertices()

        # ── Remove degenerate faces (trimesh 4.x API) ──────────────────────
        valid_mask = repaired.nondegenerate_faces()
        repaired.update_faces(valid_mask)

        # ── Remove duplicate faces ─────────────────────────────────────────
        sorted_faces = np.sort(repaired.faces, axis=1)
        _, unique_idx = np.unique(sorted_faces, axis=0, return_index=True)
        repaired.update_faces(unique_idx)

        # ── Remove unreferenced vertices (still present in 4.x) ───────────
        repaired.remove_unreferenced_vertices()

        # ── Close the surface ──────────────────────────────────────────────
        # Winding is deliberately *not* fixed first. It is the most expensive
        # call in this file — trimesh walks the face-adjacency graph in Python,
        # ~10s on an 80k-face mesh — and the loop below grafts stitched patches
        # whose own winding is arbitrary, so a pass before it is a pass that has
        # to be repeated. `fill_holes` and `stitch` orient each patch from the
        # boundary loop they close, which is a local decision and survives a
        # globally inconsistent mesh. One traversal at the end therefore does
        # the work that two used to.

        total_dropped = total_stitched = rounds_used = 0
        for round_index in range(MAX_CLOSE_ROUNDS):
            rounds_used = round_index + 1
            dropped = self._drop_nonmanifold_faces(repaired)
            total_dropped += dropped
            trimesh.repair.fill_holes(repaired)

            _, counts = self._edge_face_counts(repaired)
            boundary = int((counts == 1).sum())
            nonmanifold = int((counts > 2).sum())
            logger.debug(
                "Close round %d — dropped %d face(s), boundary edges: %d, "
                "non-manifold edges: %d",
                round_index + 1,
                dropped,
                boundary,
                nonmanifold,
            )
            if boundary == 0 and nonmanifold == 0:
                break

            stitched = 0
            if boundary:
                # fill_holes only fans over triangle and quad holes. A larger
                # boundary loop needs stitching, which trimesh returns as loose
                # faces for the caller to graft on.
                patch = self._stitch_boundaries(repaired)
                stitched = len(patch)
                if stitched:
                    repaired = self._graft(repaired, patch)
            total_stitched += stitched
            if not dropped and not stitched:
                logger.warning(
                    "Surface still open after %d round(s) — %d boundary edge(s), "
                    "%d non-manifold edge(s) and no further progress possible.",
                    round_index + 1,
                    boundary,
                    nonmanifold,
                )
                break

        # Winding and normals, once, at the end: which side is "out" is only
        # meaningful on a closed surface, and manifold3d rejects a mesh whose
        # faces disagree about it. `is_winding_consistent` is a vectorised
        # comparison over the edge list, so the mesh that arrives already
        # consistent — the normal case off an isosurface — pays for the check
        # and skips the graph traversal, needing only a sign test on its volume
        # to turn it right side out.
        if repaired.is_winding_consistent:
            trimesh.repair.fix_inversion(repaired)
        else:
            trimesh.repair.fix_normals(repaired, multibody=True)

        self._fallback_stats = {
            "close_rounds": rounds_used,
            "faces_dropped": total_dropped,
            "faces_stitched": total_stitched,
        }
        logger.debug(
            "After fallback repair — watertight: %s, faces: %d",
            repaired.is_watertight,
            len(repaired.faces),
        )
        return repaired

    @staticmethod
    def _stitch_boundaries(mesh: trimesh.Trimesh) -> np.ndarray:
        """Triangulate the boundary loops ``fill_holes`` is too small-minded for.

        Returns the new faces rather than applying them, matching trimesh's own
        signature. An empty array means stitching found nothing to do, which is
        the caller's signal that this defect is beyond topological repair.
        """
        try:
            patch = trimesh.repair.stitch(mesh)
        except Exception as exc:  # noqa: BLE001 - a failed stitch is not fatal
            logger.debug("Boundary stitching failed: %s", exc)
            return np.zeros((0, 3), dtype=np.int64)
        return np.asarray(patch).reshape(-1, 3)

    @staticmethod
    def _graft(mesh: trimesh.Trimesh, faces: np.ndarray) -> trimesh.Trimesh:
        """Add faces to a mesh and re-weld, returning the combined mesh."""
        grafted = trimesh.Trimesh(
            vertices=mesh.vertices,
            faces=np.vstack([mesh.faces, faces]),
            process=False,
        )
        grafted.merge_vertices()
        grafted.update_faces(grafted.nondegenerate_faces())
        grafted.remove_unreferenced_vertices()
        return grafted

    def _voxel_remesh(self, mesh: trimesh.Trimesh) -> trimesh.Trimesh | None:
        """Rebuild the surface volumetrically. The last resort, and it shows.

        A filled voxel grid has an unambiguous inside, so marching cubes over it
        cannot produce a boundary or a non-manifold edge — which is exactly the
        guarantee the kernel wants and exactly what a torn reconstruction cannot
        provide by editing its own topology. The cost is real and is logged: the
        surface is resampled at ``VOXEL_REMESH_RESOLUTION`` of its longest
        extent, so sharp features round off and the face count rises steeply.

        The result is deliberately **not** decimated back to the input budget.
        Quadric decimation of a marching-cubes surface at the ratios involved
        (measured: 100k faces down to 2.4k) reintroduces hundreds of
        non-manifold edges — trading the defect this method exists to remove for
        a smaller file. Phase 4 slices geometry, not vertices, and CuraEngine is
        untroubled by a six-figure face count.

        Returns:
            The remeshed surface, or None if it could not be built.
        """
        extent = float(mesh.extents.max())
        if not np.isfinite(extent) or extent <= 0:
            logger.warning("Cannot remesh a mesh with zero extent.")
            return None

        pitch = extent / VOXEL_REMESH_RESOLUTION
        try:
            remeshed = mesh.voxelized(pitch=pitch).fill().marching_cubes
            remeshed.merge_vertices()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Volumetric remesh failed: %s", exc)
            return None

        if len(remeshed.faces) == 0:
            logger.warning("Volumetric remesh produced an empty surface.")
            return None

        logger.warning(
            "Rebuilt the surface volumetrically at pitch %.4f (1/%d of %.2f) — "
            "%d faces became %d, and sharp detail below the pitch is gone.",
            pitch,
            VOXEL_REMESH_RESOLUTION,
            extent,
            len(mesh.faces),
            len(remeshed.faces),
        )
        return remeshed

    # ── Scale ─────────────────────────────────────────────────────────────────
    #: The axes `scale_to_dimensions` can size against.
    SCALE_AXES = ("height", "longest")

    def scale_to_dimensions(
        self,
        mesh: trimesh.Trimesh,
        target_mm: float,
        scale_axis: str = "height",
    ) -> trimesh.Trimesh:
        """Uniformly scale so one bounding-box extent equals *target_mm* mm.

        Which extent is the whole question. This scaled the **longest** edge, which
        is defensible for a machine and wrong for a person: "how big is it" means
        height. A figurine with its arms out is wider than it is tall, so a request
        for 50 mm produced a part 50 mm across and 38 mm high — smaller than asked
        in the only dimension the requester was picturing.

        Height is the Z extent, and that is only true *after* `orient_for_print`,
        which translates the part onto Z = 0 without rotating (Phase 2 already
        established Z-up from the backend's declared `up_axis`). Scaling is
        origin-based, so calling this after orienting preserves both the seating and
        the X/Y centring; calling it before would scale the offset too.

        Args:
            mesh: The mesh to scale. Not modified.
            target_mm: Desired size of the reference extent, in millimetres.
            scale_axis: "height" to size the Z extent, "longest" to size the longest
                bounding-box edge.

        Returns:
            A scaled copy, or the mesh unchanged when the reference extent is zero.

        Raises:
            ValueError: If `scale_axis` is not one of `SCALE_AXES`. Deliberately not
                a silent fallback: a typo would otherwise pick a convention nobody
                chose, and the result differs by whatever the aspect ratio is.
        """
        if scale_axis not in self.SCALE_AXES:
            raise ValueError(
                f"Unknown scale_axis {scale_axis!r}; expected one of {self.SCALE_AXES}"
            )

        current_size = mesh.bounds[1] - mesh.bounds[0]
        reference = float(current_size[2]) if scale_axis == "height" else float(current_size.max())

        # A nameplate or coaster lying in XY has a legitimately zero Z extent, so
        # height mode needs the same guard `_voxel_remesh` uses rather than the old
        # "no extent at all" test.
        if not np.isfinite(reference) or reference <= 0:
            logger.warning(
                "Mesh has no %s extent to scale (%r) — leaving it at its own size.",
                scale_axis, reference,
            )
            self._last_scale_factor = None
            self._last_scale_axis = "none"
            return mesh

        scale_factor = target_mm / reference
        self._last_scale_factor = float(scale_factor)
        self._last_scale_axis = scale_axis
        scaled = mesh.copy()
        scaled.apply_scale(scale_factor)
        logger.debug(
            "Scaled by %.4f (%s extent %.2f → %.2f mm)",
            scale_factor, scale_axis, reference, target_mm,
        )
        return scaled

    # ── Orient ────────────────────────────────────────────────────────────────
    def orient_for_print(self, mesh: trimesh.Trimesh) -> trimesh.Trimesh:
        """
        Centre the mesh over the origin in X/Y and sit it on the build plate.

        **It deliberately does not rotate.** It used to: it took the axis with the
        *smallest* extent to be the "flat" one and rotated that onto Z. For anything
        that stands up — a figurine, a bust, a raccoon on a skateboard — the
        thinnest axis is left-to-right, so every such model was laid on its side.
        The docstring claimed the opposite of the code ("the axis with the greatest
        extent"), which is how it went unnoticed; a real job produced a raw mesh
        with its widest cross-section at the bottom and an engineered mesh with the
        widest cross-section at the top.

        The rotation was not merely inverted, it was unnecessary. Phase 2 already
        knows which way is up: every sculptor backend declares an ``up_axis`` and
        ``SculptorBackend.postprocess`` rotates the raw output to Z-up on the
        strength of it. A bounding box cannot recover that — a sphere has no up, and
        a figurine's tallest axis is only *usually* its vertical one — so
        re-deriving orientation here could only ever discard information that was
        already correct.

        Choosing a better *print* orientation (minimising overhangs or support
        volume) is a real optimisation, but it is a search over candidate rotations
        scored against the process profile, not an argmin over three numbers. Until
        that exists, the honest thing is to keep the orientation the model was
        generated in.
        """
        oriented = mesh.copy()

        # Centre in X/Y only. Z is not centred: Z=0 is the build plate, not the
        # middle of the part.
        centre = oriented.bounds.mean(axis=0)
        oriented.apply_translation([-centre[0], -centre[1], -oriented.bounds[0][2]])
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
        # Edge counts are reported because "not watertight" on its own does not
        # say which repair is needed: a boundary edge is a hole to fill, a
        # non-manifold edge is a face to remove, and the two are fixed by
        # different code. They are also the numbers that show whether repair did
        # anything, logged either side of it by `process`.
        _, edge_counts = self._edge_face_counts(mesh)
        return {
            "vertices": len(mesh.vertices),
            "faces": len(mesh.faces),
            "is_watertight": mesh.is_watertight,
            "boundary_edges": int((edge_counts == 1).sum()),
            "nonmanifold_edges": int((edge_counts > 2).sum()),
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
        scale_axis: str = "height",
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
        logger.info("Scaling to %.1f mm (%s)…", scale_target, scale_axis)
        mesh = self.scale_to_dimensions(mesh, scale_target, scale_axis=scale_axis)

        if hollow:
            logger.info("Hollowing mesh…")
            mesh = self.hollow_mesh(mesh, wall_thickness)

        mesh.export(str(output_path))

        # Also export as .stl for the Slicer (CuraEngine)
        stl_output_path = output_path.with_suffix(".stl")
        mesh.export(str(stl_output_path))

        final_analysis = self.analyze_mesh(mesh)
        logger.info("Engineering complete → %s (and .stl)", output_path)
        logger.info("Output analysis: %s", final_analysis)

        self.last_report = {
            **(self._repair_stats or {}),
            "scale_factor": self._last_scale_factor,
            "target_mm": float(scale_target),
            # What the scale was measured against, and what came out. Written
            # unconditionally — including "none" — because an absent key in an
            # unschematised blob cannot be told apart from a pre-change row, and
            # the extents are of the *exported* mesh, so hollowing (which rebuilds
            # from a voxel grid and shrinks the part) is visible rather than hidden.
            "scale_axis": self._last_scale_axis or scale_axis,
            "achieved_extent_mm": final_analysis.get("extent_mm"),
            "hollowed": bool(hollow),
            "wall_thickness_mm": float(wall_thickness) if hollow else None,
        }
        return output_path


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="p2p-mesh Phase 3 — Engineer")
    parser.add_argument("input", nargs="?", default=os.path.join(OUTPUTS_DIR, "test_mesh.obj"), help="Input .obj path")
    parser.add_argument("output", nargs="?", default=os.path.join(OUTPUTS_DIR, "engineered_mesh.obj"), help="Output .obj path")
    parser.add_argument("target_mm", nargs="?", type=float, default=50.0, help="Target size in mm, measured along --scale-axis")
    parser.add_argument("--scale-axis", choices=Engineer.SCALE_AXES, default="height", help="Which extent target_mm describes (default: height)")
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
        scale_axis=args.scale_axis,
    )