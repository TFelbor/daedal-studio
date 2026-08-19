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


# ── Evaluation ────────────────────────────────────────────────────────────────────


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
    elif thickness is None:
        wall_status = "not_checked"
        wall_detail = "Mesh could not be voxelised, so wall thickness is unknown."
    elif thickness + thickness_tol < profile.min_wall_mm:
        wall_status = "fail"
        wall_detail = (
            f"Thinnest wall about {thickness:.2f}mm (±{thickness_tol:.2f}mm), below the "
            f"{profile.min_wall_mm:.2f}mm minimum for a {profile.nozzle_diameter_mm:.2f}mm nozzle. "
            "It will extrude as gaps or not at all."
        )
    elif thickness - thickness_tol < profile.min_wall_mm:
        wall_status = "warn"
        wall_detail = (
            f"Thinnest wall about {thickness:.2f}mm (±{thickness_tol:.2f}mm) — within measurement "
            f"tolerance of the {profile.min_wall_mm:.2f}mm minimum."
        )
    else:
        wall_status = "pass"
        wall_detail = f"Thinnest wall about {thickness:.2f}mm (±{thickness_tol:.2f}mm)."

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

    checks.append(CheckResult(
        check="self_intersections",
        status="not_checked",
        detail=(
            "Exact self-intersection testing needs a collision engine; none of manifold3d, "
            "python-fcl or rtree is installed. Install manifold3d to enable this check."
        ),
        value=None,
        threshold=0,
        weight=2.0,
    ))

    features = {
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
