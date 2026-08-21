"""
base.py — Sculptor backend contract and the post-processing shared by all backends.

A *sculptor backend* turns one blueprint image into one raw mesh. Everything that
happens after reconstruction — orientation, component pruning, smoothing,
decimation, export — is identical no matter where the geometry came from, so it
lives here rather than in each backend.

Backends implement `reconstruct()`, returning a `trimesh.Trimesh` in the network's
own coordinate frame. `generate_mesh()` does the rest.

The split matters most for the `remote` backend: the GPU worker returns geometry
*before* post-processing and this module runs on the client, so orientation,
pruning and decimation have exactly one implementation regardless of which side of
the network inference happened on.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path

import numpy as np
import trimesh

logger = logging.getLogger("p2p.sculptor")


class SculptorError(RuntimeError):
    """Raised when a backend cannot produce a mesh."""


class SculptorBackend(ABC):
    """Turns a single blueprint image into a print-ready raw mesh.

    Attributes:
        name: Registry key for the backend (e.g. "trellis2", "remote").
        up_axis: The up-axis the backend's raw output uses. Meshes are rotated to
            Z-up (the convention the Engineer and CuraEngine expect) in
            `generate_mesh`.
        default_smooth_iterations: Taubin smoothing passes to apply when the caller
            does not ask for a specific number. Marching-cubes backends need
            smoothing to hide stair-stepping; TRELLIS.2 does not, and smoothing its
            output destroys the sharp features that are the reason to use it.
    """

    name: str = "base"
    up_axis: str = "z"
    default_smooth_iterations: int = 0

    # ── Provenance, read off the instance by `pipeline._record_generation` ────
    # Set by subclasses so a backend swap needs no pipeline change to be recorded.
    MODEL_NAME: str = "unknown"
    MODEL_VERSION: str | None = None
    BACKEND: str = "local"

    #: Where the current job's artifacts belong, set by `generate_mesh` before
    #: `reconstruct` runs. A backend that *pays* for its geometry should write the raw
    #: response here the moment it arrives: post-processing can fail, and an artifact
    #: that only ever existed in memory has to be bought a second time. None when the
    #: caller drives `reconstruct` directly.
    artifact_dir: Path | None = None
    #: Charge for the most recent generation, in **euro**. Left None by backends
    #: that are not billed per call; a hosted backend sets it after each request.
    last_generation_cost_eur: float | None = None

    @abstractmethod
    def reconstruct(self, image_path: str | Path) -> trimesh.Trimesh:
        """Reconstruct raw geometry from a blueprint image.

        Args:
            image_path: Path to the blueprint image.

        Returns:
            The raw mesh, in the backend's native coordinate frame and scale.
        """

    def describe(self) -> str:
        """Return a short human-readable identifier used in logs."""
        return self.name

    def generation_params(self) -> dict:
        """Return the settings that determined this backend's geometry.

        Recorded onto the job's telemetry row. Each backend reports its own knobs so
        the pipeline never has to know which ones a given backend has — two jobs
        from the same blueprint at different resolutions are different experiments,
        and after the fact nothing else says which was which.

        Returns:
            A JSON-serialisable dict of generation settings.
        """
        return {"sculptor_backend": self.name}

    # ── Shared post-processing ────────────────────────────────────────────────

    def generate_mesh(
        self,
        image_path: str | Path,
        output_path: str | Path,
        *,
        target_faces: int = 5_000,
        smooth_iterations: int | None = None,
    ) -> Path:
        """Reconstruct, post-process for printing, and export a mesh.

        Args:
            image_path: Path to the input blueprint image.
            output_path: Path for the exported mesh. The suffix picks the format.
            target_faces: Face budget after decimation. Pass 0 to skip decimation.
            smooth_iterations: Taubin smoothing passes. None uses the backend's
                default; 0 disables smoothing.

        Returns:
            The path the mesh was written to.

        Raises:
            SculptorError: If the image is missing or the backend returns nothing.
        """
        image_path = Path(image_path)
        output_path = Path(output_path)
        if not image_path.exists():
            raise SculptorError(f"Blueprint image not found: {image_path}")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        self.artifact_dir = output_path.parent

        logger.info("Sculptor backend '%s' — processing %s", self.describe(), image_path)
        mesh = self.reconstruct(image_path)
        if mesh is None or len(mesh.faces) == 0:
            raise SculptorError(f"Backend '{self.describe()}' returned an empty mesh")

        mesh = self.postprocess(
            mesh,
            target_faces=target_faces,
            smooth_iterations=smooth_iterations,
        )

        mesh.export(str(output_path))
        logger.info(
            "Final mesh saved to: %s  (faces: %d, watertight: %s)",
            output_path,
            len(mesh.faces),
            mesh.is_watertight,
        )
        return output_path

    def postprocess(
        self,
        mesh: trimesh.Trimesh,
        *,
        target_faces: int = 5_000,
        smooth_iterations: int | None = None,
    ) -> trimesh.Trimesh:
        """Make raw network output printable: Z-up, single body, smooth, decimated.

        Args:
            mesh: Raw mesh from `reconstruct`.
            target_faces: Face budget after decimation. 0 disables decimation.
            smooth_iterations: Taubin smoothing passes; None uses the backend
                default, 0 disables smoothing.

        Returns:
            The post-processed mesh.
        """
        if smooth_iterations is None:
            smooth_iterations = self.default_smooth_iterations

        logger.info("Optimising mesh topology…")
        mesh = self._to_z_up(mesh)
        mesh = self._largest_component(mesh)
        if smooth_iterations:
            mesh = self._smooth(mesh, smooth_iterations)
        if target_faces:
            mesh = self._decimate(mesh, target_faces)
        return mesh

    def _to_z_up(self, mesh: trimesh.Trimesh) -> trimesh.Trimesh:
        """Rotate the mesh so its up-axis is +Z, the convention downstream expects."""
        axis = self.up_axis.lower()
        if axis == "z":
            return mesh
        if axis == "y":
            # +π/2 about X maps glTF's +Y (up) onto +Z. The sign is load-bearing:
            # −π/2 yields identical extents but puts +Y at −Z — upside-down prints.
            mesh.apply_transform(
                trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0])
            )
            return mesh
        raise SculptorError(
            f"Unsupported up_axis '{self.up_axis}' for backend '{self.describe()}'"
        )

    @staticmethod
    def _largest_component(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
        """Keep only the largest connected component, discarding floating debris."""
        components = mesh.split(only_watertight=False)
        if len(components) <= 1:
            return mesh
        kept = max(components, key=lambda m: m.extents.max())
        logger.debug(
            "Discarded %d disconnected component(s) — kept %d faces",
            len(components) - 1,
            len(kept.faces),
        )
        return kept

    @staticmethod
    def _smooth(mesh: trimesh.Trimesh, iterations: int) -> trimesh.Trimesh:
        """Subdivide once and apply Taubin smoothing (shrink-free Laplacian)."""
        mesh = mesh.subdivide()
        trimesh.smoothing.filter_taubin(mesh, iterations=iterations)
        logger.debug("After smoothing — faces: %d", len(mesh.faces))
        return mesh

    @staticmethod
    def _decimate(mesh: trimesh.Trimesh, target_faces: int) -> trimesh.Trimesh:
        """Quadric-decimate down to the face budget, if the mesh exceeds it.

        Requires the optional `fast-simplification` package. If absent the mesh is
        returned at full resolution — functional but slower in the Engineer step.
        Install with: pip install fast-simplification
        """
        if len(mesh.faces) <= target_faces:
            return mesh
        logger.info("Decimating %d → %d faces…", len(mesh.faces), target_faces)
        try:
            mesh = mesh.simplify_quadric_decimation(face_count=target_faces)
        except (ImportError, ModuleNotFoundError):
            logger.warning(
                "fast-simplification not installed — skipping decimation. "
                "Run: pip install fast-simplification"
            )
            return mesh
        logger.debug("After decimation — faces: %d", len(mesh.faces))
        return mesh
