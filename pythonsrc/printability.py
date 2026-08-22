"""Deterministic printability scoring — Phase 3.5, between Engineer and Slicer.

The Engineer repairs and orients a mesh but never *judges* it, so a mesh that cannot
physically print (open shell, 0.3mm walls, a sealed internal void, geometry hanging in
mid-air) reaches the slicer indistinguishable from a good one. This module scores it
first and records the result, so every print has a structured, pre-print quality signal
attached to its telemetry row.

Deterministic checks only — classical geometry, no learned model. Every check reports its
own value, threshold and tolerance so the score can be audited rather than trusted.

Checks are parameterised by a `ProcessProfile`; FDM is the only profile today, but the
thresholds that differ for resin (SLA) are all in that dataclass rather than in the check
bodies.

Deliberate limitation: exact self-intersection testing needs a collision engine
(`manifold3d`, `python-fcl`) or `rtree` for trimesh's broad phase. None are installed, so
that check reports `not_checked` with the reason instead of silently passing.
"""
from __future__ import annotations

import dataclasses
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Type, TypeVar

import numpy as np
import trimesh
from scipy import ndimage
from trimesh import grouping

try:  # Apache-2.0; present in every image, but the check degrades if absent.
    import manifold3d

    HAVE_MANIFOLD3D = True
except ImportError:  # pragma: no cover — exercised only on a broken install
    manifold3d = None
    HAVE_MANIFOLD3D = False

logger = logging.getLogger("p2p.printability")

CheckStatus = Literal["pass", "warn", "fail", "not_checked"]
Verdict = Literal["ready", "risky", "unprintable"]

# Upper bound on voxels for the wall-thickness grid. Beyond this the pitch is coarsened,
# which widens the tolerance rather than hanging the pipeline on a huge mesh.
MAX_THICKNESS_VOXELS = 2_000_000

# Cells allowed along the longest axis. trimesh's subdivide voxeliser costs grow with mesh
# extent divided by pitch, so a large object refined to a fine pitch takes tens of seconds.
# Capping the axis keeps big meshes fast; small meshes are unaffected and keep their
# precision, which is where thin-wall judgements actually happen.
MAX_CELLS_PER_AXIS = 256


@dataclasses.dataclass
class ProcessProfile:
    """Printing-process limits that the checks are evaluated against."""

    name: str = "fdm"
    """Target process identifier, e.g. "fdm" or "sla"."""

    nozzle_diameter_mm: float = 0.4
    """Nozzle diameter; drives the minimum printable wall."""

    layer_height_mm: float = 0.2
    """Layer height, used as the bed-contact tolerance."""

    min_wall_mm: float = 0.8
    """Thinnest wall that can be extruded reliably (two nozzle widths by default)."""

    max_overhang_deg: float = 45.0
    """Steepest unsupported overhang, measured from vertical."""

    max_overhang_area_frac: float = 0.35
    """Fraction of surface area allowed to overhang before the check warns."""

    min_bed_contact_mm2: float = 25.0
    """Minimum first-layer footprint; below this, adhesion failures dominate."""

    build_volume_mm: Optional[List[float]] = None
    """Printer build volume as [width, depth, height], or None if unknown."""

    @classmethod
    def from_printer_profile(cls, profile: Dict[str, Any]) -> "ProcessProfile":
        """Build a ProcessProfile from a printer profile JSON.

        Args:
            profile: Parsed contents of a `pythonsrc/profiles/*.json` file.

        Returns:
            A ProcessProfile using the profile's machine limits where present, and FDM
            defaults elsewhere. Nozzle diameter is absent from the bundled profiles, so
            it falls back to 0.4mm — the CuraEngine default.
        """
        nozzle = float(profile.get("machine_nozzle_size", 0.4) or 0.4)
        layer_height = float(profile.get("layer_height", 0.2) or 0.2)

        build_volume = None
        if all(k in profile for k in ("machine_width", "machine_depth", "machine_height")):
            build_volume = [
                float(profile["machine_width"]),
                float(profile["machine_depth"]),
                float(profile["machine_height"]),
            ]

        return cls(
            nozzle_diameter_mm=nozzle,
            layer_height_mm=layer_height,
            min_wall_mm=round(nozzle * 2, 3),
            build_volume_mm=build_volume,
        )


@dataclasses.dataclass
class CheckResult:
    """Outcome of a single printability check."""

    check: str
    """Stable check identifier, e.g. "min_wall_thickness"."""

    status: CheckStatus
    """Whether the check passed, warned, failed, or could not run."""

    detail: str
    """Human-readable explanation, including tolerance where relevant."""

    value: Any = None
    """The measured value, JSON-serialisable."""

    threshold: Any = None
    """The limit the value was compared against, if any."""

    weight: float = 1.0
    """Relative contribution to the composite score."""

    critical: bool = False
    """Whether failing this check alone makes the mesh unprintable."""

    def to_dict(self) -> Dict[str, Any]:
        """Convert the CheckResult to a JSON-serialisable dictionary.

        Returns:
            A dictionary representation of the CheckResult.
        """
        return dataclasses.asdict(self)


T = TypeVar("T", bound="PrintabilityReport")


@dataclasses.dataclass
class PrintabilityReport:
    """Scored, per-check printability assessment of one mesh."""

    job_id: Optional[str]
    """The job this mesh belongs to, or None for ad-hoc evaluation."""

    evaluated_at: datetime
    """When the evaluation ran."""

    process: str
    """The ProcessProfile name the mesh was scored against."""

    score: float
    """Composite score from 0 (unprintable) to 100 (no issues found)."""

    verdict: Verdict
    """Summary label derived from the score and any critical failures."""

    checks: List[CheckResult]
    """Per-check results, in evaluation order."""

    features: Dict[str, Any]
    """Mesh feature snapshot — the inputs a print-outcome model would train on."""

    def failed(self) -> List[CheckResult]:
        """Return the checks that failed.

        Returns:
            Every CheckResult whose status is "fail".
        """
        return [c for c in self.checks if c.status == "fail"]

    def warnings(self) -> List[CheckResult]:
        """Return the checks that warned.

        Returns:
            Every CheckResult whose status is "warn".
        """
        return [c for c in self.checks if c.status == "warn"]

    def to_dict(self) -> Dict[str, Any]:
        """Convert the report to a JSON-serialisable dictionary.

        Returns:
            A dictionary representation of the report.
        """
        return {
            "job_id": self.job_id,
            "evaluated_at": self.evaluated_at.isoformat() if self.evaluated_at else None,
            "process": self.process,
            "score": self.score,
            "verdict": self.verdict,
            "checks": [c.to_dict() for c in self.checks],
            "features": self.features,
        }

    @classmethod
    def from_dict(cls: Type[T], data: Dict[str, Any]) -> T:
        """Create a report from a dictionary.

        Args:
            data: A dictionary as produced by `to_dict()`.

        Returns:
            An initialised PrintabilityReport.
        """
        evaluated_at = data.get("evaluated_at")
        if isinstance(evaluated_at, str):
            s = evaluated_at[:-1] + "+00:00" if evaluated_at.endswith("Z") else evaluated_at
            evaluated_at = datetime.fromisoformat(s)
        return cls(
            job_id=data.get("job_id"),
            evaluated_at=evaluated_at,
            process=data.get("process", "fdm"),
            score=data.get("score", 0.0),
            verdict=data.get("verdict", "unprintable"),
            checks=[CheckResult(**c) for c in data.get("checks", [])],
            features=data.get("features", {}),
        )


# ── Individual checks ─────────────────────────────────────────────────────────────


def _edge_counts(mesh: trimesh.Trimesh) -> tuple[int, int]:
    """Count open and non-manifold edges.

    Args:
        mesh: The mesh to inspect.

    Returns:
        A (boundary_edges, non_manifold_edges) tuple, where boundary edges belong to a
        single face (a hole) and non-manifold edges belong to three or more.
    """
    groups = grouping.group_rows(mesh.edges_sorted, require_count=None)
    counts = np.array([len(g) for g in groups]) if len(groups) else np.array([])
    if counts.size == 0:
        return 0, 0
    return int((counts == 1).sum()), int((counts > 2).sum())


def _overhang_area_fraction(mesh: trimesh.Trimesh, profile: ProcessProfile) -> float:
    """Fraction of surface area that overhangs beyond the process limit.

    Faces are measured against the +Z build direction. Downward-facing faces resting on
    the build plate are excluded — they are supported by the bed, not by air.

    Args:
        mesh: An oriented mesh whose lowest point is the first layer.
        profile: Process limits supplying the maximum overhang angle.

    Returns:
        Overhanging area divided by total area, in [0, 1].
    """
    normals = mesh.face_normals
    areas = mesh.area_faces
    total = float(areas.sum())
    if total <= 0:
        return 0.0

    # Angle between the face normal and straight down; 0° is a fully horizontal roof.
    tilt_deg = np.degrees(np.arccos(np.clip(-normals[:, 2], -1.0, 1.0)))
    face_min_z = mesh.vertices[mesh.faces][:, :, 2].min(axis=1)
    on_bed = face_min_z <= (mesh.bounds[0][2] + profile.layer_height_mm)

    overhanging = (normals[:, 2] < 0) & (tilt_deg <= (90.0 - profile.max_overhang_deg)) & ~on_bed
    return float(areas[overhanging].sum() / total)


def _bed_contact_area(mesh: trimesh.Trimesh, profile: ProcessProfile) -> float:
    """Area of the faces forming the first layer.

    Args:
        mesh: An oriented mesh whose lowest point is the first layer.
        profile: Process limits supplying the height tolerance.

    Returns:
        First-layer contact area in mm².
    """
    face_z = mesh.vertices[mesh.faces][:, :, 2]
    flat_on_bed = face_z.max(axis=1) <= (mesh.bounds[0][2] + profile.layer_height_mm)
    return float(mesh.area_faces[flat_on_bed].sum())


def _component_analysis(mesh: trimesh.Trimesh, profile: ProcessProfile) -> tuple[int, int, int]:
    """Split the mesh and classify its parts.

    Args:
        mesh: The mesh to split.
        profile: Process limits supplying the bed tolerance.

    Returns:
        A (component_count, floating_count, enclosed_void_count) tuple. Floating parts do
        not touch the build plate; enclosed voids are components whose bounding box lies
        entirely inside another component's, which is what the Engineer's voxel hollowing
        produces — a sealed cavity with no escape hole.
    """
    try:
        parts = mesh.split(only_watertight=False)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not split mesh into components: %s", exc)
        return 1, 0, 0

    if len(parts) <= 1:
        return max(len(parts), 1), 0, 0

    bed_z = mesh.bounds[0][2]
    floating = 0
    enclosed = 0

    for i, part in enumerate(parts):
        nested = any(
            (part.bounds[0] > other.bounds[0]).all() and (part.bounds[1] < other.bounds[1]).all()
            for j, other in enumerate(parts)
            if i != j
        )
        if nested:
            # An inner shell is an enclosed cavity, not a part hanging in mid-air —
            # counting it as both would penalise the same defect twice.
            enclosed += 1
            continue
        if part.bounds[0][2] > bed_z + max(profile.layer_height_mm, 0.5):
            floating += 1

    return len(parts), floating, enclosed


def _thickness_pitch(extents, profile: ProcessProfile) -> float:
    """Voxel pitch the wall measurement would use for a mesh of these extents.

    Shared with `size_feasibility` rather than copied, because the pitch *is* the
    measurement tolerance: a predictor using its own formula would quote a
    confidence interval the real check does not have. Two terms compete —
    `min_wall/4` is absolute and `max_extent/256` is proportional — so which one
    dominates flips as the part is scaled, and a prediction that assumed the
    tolerance simply scales with size would be wrong on both sides of that crossover.

    Args:
        extents: The mesh's bounding-box extents, in millimetres.
        profile: Process limits supplying the wall threshold.

    Returns:
        The pitch in millimetres, after coarsening to stay under the voxel budget.
    """
    extents = np.asarray(extents, dtype=float)
    # Resolve walls to a quarter of the threshold — and, for plate-like meshes, to a
    # quarter of the thinnest bounding-box extent, so a 0.5mm plate is not measured with
    # a 0.2mm ruler. Grid size is bounded below.
    thinnest_extent = float(np.min(extents[extents > 0])) if (extents > 0).any() else profile.min_wall_mm
    pitch = max(
        min(profile.min_wall_mm / 4.0, thinnest_extent / 4.0),
        float(extents.max()) / MAX_CELLS_PER_AXIS,
        1e-3,
    )
    while np.prod(np.ceil(extents / pitch) + 2) > MAX_THICKNESS_VOXELS:
        pitch *= 1.5
    return pitch


def _wall_status(
    thickness: Optional[float], tolerance: float, profile: ProcessProfile,
) -> tuple[str, str]:
    """Band a wall measurement into pass / warn / fail, with the sentence to show.

    One implementation, used by `evaluate_printability` and by `size_feasibility`, so
    a predicted verdict and the real one cannot disagree about where the boundaries
    are. The middle band exists because the measurement is quantised: a wall within
    one voxel of the minimum is a warning, not a failure, and the report states its
    own tolerance so the reader can see why.

    Args:
        thickness: Measured thinnest wall in millimetres, or None if unmeasured.
        tolerance: The measurement's uncertainty — one voxel pitch.
        profile: Process limits supplying the minimum wall.

    Returns:
        A (status, detail) tuple.
    """
    if thickness is None:
        return "not_checked", "Mesh could not be voxelised, so wall thickness is unknown."
    if thickness + tolerance < profile.min_wall_mm:
        return "fail", (
            f"Thinnest wall about {thickness:.2f}mm (±{tolerance:.2f}mm), below the "
            f"{profile.min_wall_mm:.2f}mm minimum for a {profile.nozzle_diameter_mm:.2f}mm nozzle. "
            "It will extrude as gaps or not at all."
        )
    if thickness - tolerance < profile.min_wall_mm:
        return "warn", (
            f"Thinnest wall about {thickness:.2f}mm (±{tolerance:.2f}mm) — within measurement "
            f"tolerance of the {profile.min_wall_mm:.2f}mm minimum."
        )
    return "pass", f"Thinnest wall about {thickness:.2f}mm (±{tolerance:.2f}mm)."


def _min_wall_thickness(mesh: trimesh.Trimesh, profile: ProcessProfile) -> tuple[Optional[float], float]:
    """Estimate the thinnest wall in the mesh.

    Voxelises the solid and takes a Euclidean distance transform; the local maxima of that
    transform lie on the medial axis, where twice the distance is the local thickness.
    This avoids ray casting, which needs `rtree` — not installed — and works on meshes
    that are not perfectly watertight.

    Args:
        mesh: The mesh to measure, in millimetres.
        profile: Process limits supplying the wall threshold that sets the resolution.

    Returns:
        A (thickness_mm, tolerance_mm) tuple. Thickness is None when the mesh is too thin
        to voxelise at all. Tolerance is one voxel pitch — the measurement is quantised.
    """
    extents = mesh.bounds[1] - mesh.bounds[0]
    if float(extents.max()) <= 0:
        return None, 0.0

    pitch = _thickness_pitch(extents, profile)

    # trimesh's subdivide voxeliser gives up ("max_iter exceeded") when a large mesh has
    # to be refined to a fine pitch, so raise its iteration budget and fall back to
    # coarser grids rather than silently reporting no measurement at all.
    solid = None
    for attempt in range(3):
        try:
            voxels = mesh.voxelized(pitch=pitch, max_iter=200).fill()
            solid = np.pad(np.asarray(voxels.matrix, dtype=bool), 1)
            break
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Voxelisation failed at pitch %.3fmm (%s); retrying coarser.", pitch, exc
            )
            pitch *= 2.0

    if solid is None:
        logger.warning("Wall thickness unavailable — voxelisation failed at every pitch.")
        return None, pitch

    if not solid.any():
        return None, pitch

    distance = ndimage.distance_transform_edt(solid) * pitch
    local_max = ndimage.maximum_filter(distance, size=3)
    medial = solid & (distance >= local_max - 1e-9) & (distance > 0)
    if not medial.any():
        return None, pitch

    # The distance transform measures centre-to-centre, overshooting the true surface by
    # about half a voxel on each side; subtract it back off rather than over-reporting.
    thickness = 2.0 * distance[medial] - pitch
    return float(max(thickness.min(), 0.0)), pitch


def _check_self_intersections(mesh: trimesh.Trimesh) -> CheckResult:
    """
    Detect interpenetrating shells using the manifold3d kernel (Apache-2.0).

    Two things are asked of the kernel, and they fail differently:

    * Constructing a ``Manifold`` is a hard topological test. Rejection means
      the surface is not a valid solid at all — a fatal condition for slicing.
    * Unioning the decomposed components resolves interpenetration. If the
      union's volume is *less* than the sum of the parts, the parts were
      overlapping and the overlap was being counted twice. A slicer fed that
      mesh sees contradictory inside/outside tests in the overlap region.

    Reports ``not_checked`` rather than guessing when the kernel is absent, so
    the score denominator excludes it instead of rewarding an untested mesh.
    """
    if not HAVE_MANIFOLD3D:
        return CheckResult(
            check="self_intersections",
            status="not_checked",
            detail="manifold3d is not installed; exact self-intersection testing is unavailable.",
            value=None,
            threshold=0,
            weight=2.0,
        )

    try:
        gl = manifold3d.Mesh(
            vert_properties=np.asarray(mesh.vertices, dtype=np.float32),
            tri_verts=np.asarray(mesh.faces, dtype=np.uint32),
        )
        gl.merge()
        man = manifold3d.Manifold(gl)

        if man.status() != manifold3d.Error.NoError:
            return CheckResult(
                check="self_intersections",
                status="fail",
                detail=(
                    f"manifold3d rejected the mesh as a solid ({man.status()}). "
                    "The surface does not bound a well-defined volume, so slicing is unreliable."
                ),
                value=None,
                threshold=0,
                weight=2.0,
                critical=True,
            )

        parts = man.decompose()
        if len(parts) <= 1:
            return CheckResult(
                check="self_intersections",
                status="pass",
                detail="Single closed solid; no interpenetrating shells.",
                value=0,
                threshold=0,
                weight=2.0,
            )

        part_volume = sum(p.volume() for p in parts)
        union = manifold3d.Manifold.batch_boolean(parts, manifold3d.OpType.Add)
        if union.status() != manifold3d.Error.NoError:
            return CheckResult(
                check="self_intersections",
                status="not_checked",
                detail=f"manifold3d could not union the {len(parts)} components ({union.status()}).",
                value=None,
                threshold=0,
                weight=2.0,
            )

        overlap = part_volume - union.volume()
        # Below a millionth of the total volume this is float noise, not geometry.
        if overlap <= max(part_volume * 1e-6, 1e-9):
            return CheckResult(
                check="self_intersections",
                status="pass",
                detail=f"{len(parts)} separate components, none interpenetrating.",
                value=0.0,
                threshold=0,
                weight=2.0,
            )

        pct = 100.0 * overlap / part_volume
        return CheckResult(
            check="self_intersections",
            status="warn",
            detail=(
                f"{len(parts)} components overlap by {overlap:.2f}mm³ ({pct:.1f}% of total volume). "
                "Engineer.repair_mesh unions these, so this is a warning about the input mesh, "
                "not the sliced result."
            ),
            value=round(overlap, 3),
            threshold=0,
            weight=2.0,
        )

    except Exception as exc:  # noqa: BLE001 — scoring must never fail the job
        logger.warning("Self-intersection check failed: %s", exc)
        return CheckResult(
            check="self_intersections",
            status="not_checked",
            detail=f"Self-intersection check raised {type(exc).__name__}: {exc}",
            value=None,
            threshold=0,
            weight=2.0,
        )


# ── Evaluation ────────────────────────────────────────────────────────────────────


def _build_features(
    mesh: trimesh.Trimesh,
    *,
    extents,
    components,
    floating,
    enclosed,
    boundary_edges,
    non_manifold_edges,
    degenerate_faces,
    thickness,
    thickness_tol,
    overhang_frac,
    bed_contact,
) -> Dict[str, Any]:
    """Assemble the mesh feature snapshot from already-computed measurements.

    Split out so `evaluate_printability` and `extract_features` produce an identical
    dictionary, and a full report's `features` can be compared field-for-field against
    a cheap pre-repair snapshot.

    Args:
        mesh: The mesh being described.
        extents: Bounding-box extents in millimetres.
        components: Total connected component count.
        floating: Components not touching the bed.
        enclosed: Components nested inside another (sealed cavities).
        boundary_edges: Edges belonging to exactly one face.
        non_manifold_edges: Edges shared by three or more faces.
        degenerate_faces: Zero-area face count.
        thickness: Measured minimum wall thickness, or None.
        thickness_tol: Measurement tolerance for `thickness`.
        overhang_frac: Fraction of surface area overhanging past the profile limit.
        bed_contact: First-layer footprint in square millimetres.

    Returns:
        The feature dictionary stored on the telemetry row.
    """
    return {
        "face_count": int(len(mesh.faces)),
        "vertex_count": int(len(mesh.vertices)),
        "is_watertight": bool(mesh.is_watertight),
        "is_winding_consistent": bool(mesh.is_winding_consistent),
        "volume_mm3": round(float(mesh.volume), 3) if mesh.is_volume else None,
        "surface_area_mm2": round(float(mesh.area), 3),
        "extent_mm": [round(float(e), 3) for e in extents],
        "euler_number": int(mesh.euler_number),
        "component_count": components,
        "floating_component_count": floating,
        "enclosed_void_count": enclosed,
        "boundary_edge_count": boundary_edges,
        "non_manifold_edge_count": non_manifold_edges,
        "degenerate_face_count": degenerate_faces,
        "min_wall_thickness_mm": round(thickness, 3) if thickness is not None else None,
        "min_wall_tolerance_mm": round(thickness_tol, 3),
        "overhang_area_fraction": round(overhang_frac, 4),
        "bed_contact_mm2": round(bed_contact, 2),
    }


def extract_features(
    mesh: trimesh.Trimesh,
    profile: Optional[ProcessProfile] = None,
    *,
    thickness: bool = True,
) -> Dict[str, Any]:
    """Measure a mesh without scoring it.

    `evaluate_printability` only makes sense for a mesh that has been oriented and
    scaled, but the raw mesh coming out of the sculptor is neither, and it still needs
    describing — a before/after pair is the only way to tell a mesh that was already
    sound from one that repair rescued.

    Args:
        mesh: Any mesh, oriented or not.
        profile: Process limits; defaults to the FDM profile.
        thickness: Whether to measure minimum wall thickness. This is the expensive
            measurement (voxelisation plus a distance transform) and is meaningless on
            an unscaled mesh, so callers describing a raw mesh should pass False.

    Returns:
        The same feature dictionary shape `evaluate_printability` reports, with
        thickness fields None when `thickness` is False.
    """
    profile = profile or ProcessProfile()

    boundary_edges, non_manifold_edges = _edge_counts(mesh)
    degenerate_faces = int((~mesh.nondegenerate_faces()).sum())
    components, floating, enclosed = _component_analysis(mesh, profile)
    overhang_frac = _overhang_area_fraction(mesh, profile)
    bed_contact = _bed_contact_area(mesh, profile)
    if thickness:
        thickness_mm, thickness_tol = _min_wall_thickness(mesh, profile)
    else:
        thickness_mm, thickness_tol = None, 0.0
    extents = (mesh.bounds[1] - mesh.bounds[0]).tolist()

    return _build_features(
        mesh,
        extents=extents,
        components=components,
        floating=floating,
        enclosed=enclosed,
        boundary_edges=boundary_edges,
        non_manifold_edges=non_manifold_edges,
        degenerate_faces=degenerate_faces,
        thickness=thickness_mm,
        thickness_tol=thickness_tol,
        overhang_frac=overhang_frac,
        bed_contact=bed_contact,
    )


#: Axes a target size can be measured along. Mirrors `Engineer.SCALE_AXES` — a
#: feasibility figure quoted along one axis and applied along the other is the
#: silent-wrong-size bug with extra steps.
FEASIBILITY_AXES = ("height", "longest")


def size_feasibility(
    mesh: trimesh.Trimesh,
    profile: Optional[ProcessProfile] = None,
    *,
    candidate_mm: Optional[float] = None,
    scale_axis: str = "height",
) -> Dict[str, Any]:
    """Ask at what size this geometry becomes printable, before it is scaled.

    The wall check runs after scaling, so a thin-walled part is reported as
    unprintable once the size is already fixed, and the one remedy — print it
    bigger — is never offered. This runs the same measurement and inverts it.

    **It is a prediction, and the returned sizes must be treated as one.** Wall
    thickness in the geometry is exactly linear in a uniform scale factor, but the
    measurement is quantised to a voxel pitch (`_thickness_pitch`) whose dominant
    term switches from absolute to proportional as the part grows. Measured against a
    10x10x0.3mm plate, the linear estimate tracks the real measurement to within one
    pitch across a 20x range — enough to choose a size, not enough to report as
    measured. A caller that acts on `smallest_viable_mm` should re-measure there.

    Three sizes are returned rather than one because the tolerance band is real:
    `nofail_mm` is where the check stops saying *fail*, `smallest_viable_mm` is where
    it clears the band entirely and also satisfies bed adhesion, and `max_size_mm` is
    the machine's own ceiling. A suggestion above the ceiling is not a suggestion,
    which is what `fits` reports.

    Args:
        mesh: The repaired, oriented mesh, in millimetres.
        profile: Process limits; defaults to the FDM profile.
        candidate_mm: A size to predict the wall verdict at. Defaults to the mesh's
            current size, i.e. "what would the check say right now".
        scale_axis: Which extent every returned size is measured along — "height"
            (Z, after the part is seated) or "longest".

    Returns:
        A dict with `scale_axis`, `reference_extent_mm`, the measured wall and its
        tolerance, `nominal_mm` / `nofail_mm` / `smallest_viable_mm` /
        `bed_limited_mm` / `max_size_mm`, `fits`, `predicted_status`,
        `predicted_wall_mm`, and `reason` — a sentence whenever a size could not be
        computed, or the ceiling was exceeded, and None otherwise.

    Raises:
        ValueError: If `scale_axis` is not one of `FEASIBILITY_AXES`.
    """
    if scale_axis not in FEASIBILITY_AXES:
        raise ValueError(
            f"Unknown scale_axis {scale_axis!r}; expected one of {FEASIBILITY_AXES}"
        )

    profile = profile or ProcessProfile()
    extents = np.asarray(mesh.bounds[1] - mesh.bounds[0], dtype=float)
    reference = float(extents[2]) if scale_axis == "height" else float(extents.max())

    result: Dict[str, Any] = {
        "scale_axis": scale_axis,
        "reference_extent_mm": round(reference, 4) if np.isfinite(reference) else None,
        "measured_wall_mm": None,
        "measured_tolerance_mm": None,
        "nominal_mm": None,
        "nofail_mm": None,
        "bed_limited_mm": None,
        "smallest_viable_mm": None,
        "max_size_mm": None,
        "fits": True,
        "predicted_status": "not_checked",
        "predicted_wall_mm": None,
        "reason": None,
    }

    if not np.isfinite(reference) or reference <= 0:
        result["reason"] = (
            f"The mesh has no {scale_axis} extent to scale, so no size can be derived."
        )
        return result

    # The machine ceiling is independent of the wall measurement, so it is worth
    # reporting even when the wall measurement abstains. Positional: no rotation
    # search, matching the build_volume_fit check.
    if profile.build_volume_mm and (extents > 0).all():
        ratios = [
            limit / float(extent)
            for limit, extent in zip(profile.build_volume_mm, extents)
        ]
        result["max_size_mm"] = round(reference * min(ratios), 4)

    features = extract_features(mesh, profile)

    # Same gate `evaluate_printability` applies, and for the same reason: voxel
    # filling cannot tell inside from outside on an open surface, so any thickness
    # read off one is meaningless rather than merely imprecise.
    if not features["is_watertight"]:
        result["reason"] = (
            "Wall thickness needs a closed volume — the mesh is open, so no size can "
            "be derived from it. Fix watertightness first."
        )
        return result

    measured = features["min_wall_thickness_mm"]
    tolerance = float(features["min_wall_tolerance_mm"] or 0.0)
    if measured is None:
        result["reason"] = (
            "The mesh could not be voxelised, so its thinnest wall is unknown and no "
            "size can be derived from it."
        )
        return result
    if measured <= 0:
        result["reason"] = (
            "The measured wall thickness is zero, which no amount of scaling changes."
        )
        return result

    result["measured_wall_mm"] = measured
    result["measured_tolerance_mm"] = round(tolerance, 4)

    minimum = profile.min_wall_mm
    result["nominal_mm"] = round(reference * minimum / measured, 4)
    result["nofail_mm"] = round(reference * minimum / (measured + tolerance), 4)

    # Clearing the tolerance band, not merely the nominal threshold: a size chosen at
    # the nominal figure lands in the warn band about half the time, and being told
    # "print it at 27mm" only to be warned at 27mm is worse than not being told.
    clear = measured - tolerance
    pass_mm = reference * minimum / clear if clear > 0 else float("inf")

    # Bed contact scales with the square of the factor, so adhesion can set a higher
    # floor than the walls do on a small-footprint part.
    bed_contact = float(features.get("bed_contact_mm2") or 0.0)
    if bed_contact > 0:
        result["bed_limited_mm"] = round(
            reference * float(np.sqrt(profile.min_bed_contact_mm2 / bed_contact)), 4,
        )

    floor = max(pass_mm, result["bed_limited_mm"] or 0.0)
    result["smallest_viable_mm"] = round(floor, 4) if np.isfinite(floor) else None

    # The prediction: geometry is linear, the ruler is re-derived at the new size.
    target = float(candidate_mm) if candidate_mm is not None else reference
    factor = target / reference
    predicted_wall = measured * factor
    status, _ = _wall_status(
        predicted_wall, _thickness_pitch(extents * factor, profile), profile,
    )
    result["predicted_wall_mm"] = round(predicted_wall, 4)
    result["predicted_status"] = status

    ceiling = result["max_size_mm"]
    if ceiling is not None and result["smallest_viable_mm"] is not None:
        result["fits"] = result["smallest_viable_mm"] <= ceiling
        if not result["fits"]:
            result["reason"] = (
                f"This geometry needs about {result['smallest_viable_mm']:.1f}mm along "
                f"its {scale_axis} to print its thinnest wall, but the build volume "
                f"allows at most {ceiling:.1f}mm. It cannot be printed at any size on "
                "this machine without thickening the model itself."
            )
    elif result["smallest_viable_mm"] is None:
        result["fits"] = False
        result["reason"] = (
            "No finite size clears the wall tolerance for this geometry."
        )

    return result


def evaluate_printability(
    mesh: trimesh.Trimesh,
    profile: Optional[ProcessProfile] = None,
    job_id: Optional[str] = None,
    was_hollowed: bool = False,
) -> PrintabilityReport:
    """Score a mesh for printability.

    Args:
        mesh: The engineered mesh, already oriented so its first layer is at the bottom
            and scaled to millimetres.
        profile: Process limits; defaults to the FDM profile.
        job_id: Job to associate the report with.
        was_hollowed: Whether the Engineer hollowed the mesh. Enclosed voids are expected
            in that case and are reported as a missing escape hole rather than stray
            geometry.

    Returns:
        A PrintabilityReport with per-check results, a composite score and the mesh
        feature snapshot.
    """
    profile = profile or ProcessProfile()
    checks: List[CheckResult] = []

    boundary_edges, non_manifold_edges = _edge_counts(mesh)
    degenerate_faces = int((~mesh.nondegenerate_faces()).sum())
    components, floating, enclosed = _component_analysis(mesh, profile)
    overhang_frac = _overhang_area_fraction(mesh, profile)
    bed_contact = _bed_contact_area(mesh, profile)
    thickness, thickness_tol = _min_wall_thickness(mesh, profile)
    extents = (mesh.bounds[1] - mesh.bounds[0]).tolist()

    checks.append(CheckResult(
        check="watertight",
        status="pass" if mesh.is_watertight else "fail",
        detail=(
            "Mesh is a closed volume."
            if mesh.is_watertight
            else f"Mesh is open: {boundary_edges} boundary edge(s) form holes the slicer cannot fill."
        ),
        value=bool(mesh.is_watertight),
        threshold=True,
        weight=3.0,
        critical=True,
    ))

    checks.append(CheckResult(
        check="winding_consistent",
        status="pass" if mesh.is_winding_consistent else "fail",
        detail=(
            "Face winding is consistent."
            if mesh.is_winding_consistent
            else "Inconsistent winding — inside/outside is ambiguous, so infill may invert."
        ),
        value=bool(mesh.is_winding_consistent),
        threshold=True,
        weight=1.0,
    ))

    checks.append(CheckResult(
        check="non_manifold_edges",
        status="pass" if non_manifold_edges == 0 else "fail",
        detail=(
            "No non-manifold edges."
            if non_manifold_edges == 0
            else f"{non_manifold_edges} edge(s) shared by three or more faces."
        ),
        value=non_manifold_edges,
        threshold=0,
        weight=2.0,
    ))

    checks.append(CheckResult(
        check="degenerate_faces",
        status="pass" if degenerate_faces == 0 else "warn",
        detail=(
            "No zero-area faces."
            if degenerate_faces == 0
            else f"{degenerate_faces} zero-area face(s); harmless to slice but a sign of a poor mesh."
        ),
        value=degenerate_faces,
        threshold=0,
        weight=1.0,
    ))

    if floating:
        floating_status, floating_detail = "fail", (
            f"{floating} component(s) float above the build plate and will print in mid-air. "
            "Flagged, not removed — they may be intended parts needing support or a raft."
        )
    elif components > 1:
        floating_status, floating_detail = "warn", (
            f"{components} separate components, all touching the plate. Printable, but check "
            "whether the split is intentional."
        )
    else:
        floating_status, floating_detail = "pass", "Single connected body resting on the plate."

    checks.append(CheckResult(
        check="floating_components",
        status=floating_status,
        detail=floating_detail,
        value={"components": components, "floating": floating},
        threshold=0,
        weight=2.0,
        critical=True,
    ))

    if enclosed and was_hollowed:
        void_status = "fail"
        void_detail = (
            f"{enclosed} sealed internal cavity from hollowing, with no escape hole. "
            "Add a drain/escape hole before printing."
        )
    elif enclosed:
        void_status = "warn"
        void_detail = f"{enclosed} fully enclosed internal cavity detected; it cannot be drained or vented."
    else:
        void_status = "pass"
        void_detail = "No fully enclosed internal cavities."

    checks.append(CheckResult(
        check="escape_hole",
        status=void_status,
        detail=void_detail,
        value=enclosed,
        threshold=0,
        weight=2.0,
        # A cavity the Engineer created by hollowing has no drain path at all; that is a
        # defect we introduced, not an artistic choice, so it is fatal.
        critical=bool(enclosed and was_hollowed),
    ))

    if not mesh.is_watertight:
        wall_status = "not_checked"
        wall_detail = (
            "Wall thickness needs a closed volume — the mesh is open, so voxel filling "
            "cannot distinguish inside from outside. Fix watertightness first."
        )
        thickness = None
    else:
        wall_status, wall_detail = _wall_status(thickness, thickness_tol, profile)

    checks.append(CheckResult(
        check="min_wall_thickness",
        status=wall_status,
        detail=wall_detail,
        value=thickness,
        threshold=profile.min_wall_mm,
        weight=3.0,
        critical=True,
    ))

    if overhang_frac > profile.max_overhang_area_frac:
        overhang_status = "warn"
        overhang_detail = (
            f"{overhang_frac * 100:.1f}% of the surface overhangs beyond "
            f"{profile.max_overhang_deg:.0f}° — enable supports or reorient."
        )
    else:
        overhang_status = "pass"
        overhang_detail = (
            f"{overhang_frac * 100:.1f}% of the surface overhangs beyond "
            f"{profile.max_overhang_deg:.0f}°, within limits."
        )

    checks.append(CheckResult(
        check="overhang_area",
        status=overhang_status,
        detail=overhang_detail,
        value=round(overhang_frac, 4),
        threshold=profile.max_overhang_area_frac,
        weight=2.0,
    ))

    checks.append(CheckResult(
        check="bed_contact",
        status="pass" if bed_contact >= profile.min_bed_contact_mm2 else "warn",
        detail=(
            f"First-layer footprint {bed_contact:.1f}mm²."
            if bed_contact >= profile.min_bed_contact_mm2
            else f"First-layer footprint only {bed_contact:.1f}mm² (want ≥{profile.min_bed_contact_mm2:.0f}mm²); "
                 "adhesion failure is the most likely outcome."
        ),
        value=round(bed_contact, 2),
        threshold=profile.min_bed_contact_mm2,
        weight=1.0,
    ))

    if profile.build_volume_mm:
        fits = all(e <= limit for e, limit in zip(extents, profile.build_volume_mm))
        checks.append(CheckResult(
            check="build_volume_fit",
            status="pass" if fits else "fail",
            detail=(
                f"Fits the build volume ({', '.join(f'{e:.0f}' for e in extents)}mm)."
                if fits
                else f"Exceeds the build volume: {', '.join(f'{e:.0f}' for e in extents)}mm "
                     f"vs {', '.join(f'{v:.0f}' for v in profile.build_volume_mm)}mm."
            ),
            value=[round(e, 2) for e in extents],
            threshold=profile.build_volume_mm,
            weight=2.0,
            critical=True,
        ))

    checks.append(_check_self_intersections(mesh))

    features = _build_features(
        mesh,
        extents=extents,
        components=components,
        floating=floating,
        enclosed=enclosed,
        boundary_edges=boundary_edges,
        non_manifold_edges=non_manifold_edges,
        degenerate_faces=degenerate_faces,
        thickness=thickness,
        thickness_tol=thickness_tol,
        overhang_frac=overhang_frac,
        bed_contact=bed_contact,
    )

    score = _composite_score(checks)
    return PrintabilityReport(
        job_id=job_id,
        evaluated_at=datetime.now(timezone.utc),
        process=profile.name,
        score=score,
        verdict=_verdict(score, checks),
        checks=checks,
        features=features,
    )


def _composite_score(checks: List[CheckResult]) -> float:
    """Combine check results into a 0–100 score.

    Checks that could not run are excluded from the denominator, so an unavailable check
    neither rewards nor penalises the mesh.

    Args:
        checks: The evaluated checks.

    Returns:
        The weighted score, rounded to one decimal place.
    """
    points = {"pass": 1.0, "warn": 0.5, "fail": 0.0}
    scored = [c for c in checks if c.status in points]
    total_weight = sum(c.weight for c in scored)
    if total_weight <= 0:
        return 0.0
    earned = sum(points[c.status] * c.weight for c in scored)
    return round(100.0 * earned / total_weight, 1)


def _verdict(score: float, checks: List[CheckResult]) -> Verdict:
    """Label a score, accounting for critical failures.

    A mesh with one fatal defect is unprintable even if everything else passes, so the
    critical flag overrides the numeric score.

    Args:
        score: The composite score.
        checks: The evaluated checks.

    Returns:
        "unprintable", "risky" or "ready".
    """
    if any(c.critical and c.status == "fail" for c in checks):
        return "unprintable"
    if score < 60.0:
        return "unprintable"
    if score < 85.0:
        return "risky"
    if any(c.critical and c.status == "warn" for c in checks):
        # e.g. a wall within measurement tolerance of the minimum — not provably bad,
        # but not something to call ready either.
        return "risky"
    if any(c.critical and c.status == "not_checked" for c in checks):
        # A critical check that could not run leaves a hole in the assessment. Excluding
        # it from the score keeps the arithmetic fair, but calling the mesh "ready" on the
        # strength of the checks that did run would be a false assurance.
        return "risky"
    return "ready"


def evaluate_mesh_file(
    mesh_path: str,
    profile: Optional[ProcessProfile] = None,
    job_id: Optional[str] = None,
    was_hollowed: bool = False,
) -> PrintabilityReport:
    """Load a mesh from disk and score it.

    Args:
        mesh_path: Path to a mesh file trimesh can load.
        profile: Process limits; defaults to the FDM profile.
        job_id: Job to associate the report with.
        was_hollowed: Whether the Engineer hollowed the mesh.

    Returns:
        The PrintabilityReport for the loaded mesh.
    """
    mesh = trimesh.load(str(mesh_path), force="mesh")
    return evaluate_printability(mesh, profile=profile, job_id=job_id, was_hollowed=was_hollowed)
