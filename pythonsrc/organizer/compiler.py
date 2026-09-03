"""What every archetype compiler shares: the kernel bridge, plane reading, result types.

The archetypes build solids with `manifold3d` (Apache-2.0, already the project's CSG
and manifoldness kernel — see `ARCHITECTURE.md`, "The geometry kernel") and hand them
to trimesh for export. Two rules hold across all of them:

- **The kernel's vertices are exported untouched.** `manifold_to_trimesh` builds the
  Trimesh with `process=False`: no merging, no re-indexing, so the planes the design
  put at 2.8 mm are at 2.8 mm in the file. (STL itself is float32, so a 156.6 mm
  extent reads back as 156.6000061 — six millionths of a millimetre, four orders of
  magnitude under N1's ±0,05 mm.)
- **Designed features are measured, never assumed.** `plane_set` reads the distinct
  axis-aligned planes off a mesh; an archetype's `measure()` turns those into the same
  feature names its `compile()` designed, and `compare_features` puts the two side by
  side. This is the shape of text-to-cad's `measure`/`align` checkers, and it is what
  lets the dimensional assertion run on Phase 3's *output* rather than on the input.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import numpy as np
import trimesh

try:  # the kernel is a hard dependency; the guard only makes the error readable
    import manifold3d
except ImportError as exc:  # pragma: no cover
    raise ImportError("manifold3d is required to compile organizer specs") from exc


#: Widest a measured feature may sit from its designed value, in mm (PRD N1).
DEFAULT_TOLERANCE_MM = 0.05


class MeasureError(RuntimeError):
    """The geometry does not have the planes the design says it has, or a feature is
    out of tolerance. Either way the finding is the message."""


@dataclass(frozen=True)
class FitsResult:
    """The verdict the millimetre arithmetic returns, with the sum that produced it.

    Mirrors `FitsResult` in `web/src/organizer/spec.ts` field for field.
    """

    fits: bool
    line: str
    basis: str
    remedy: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"fits": self.fits, "line": self.line, "basis": self.basis}
        if self.remedy:
            d["remedy"] = self.remedy
        return d


@dataclass
class CompileResult:
    """What compiling a spec produced: the plate, its parts, and the designed features."""

    archetype: str
    archetype_version: str
    spec_hash: str
    mesh: trimesh.Trimesh
    parts: dict[str, trimesh.Trimesh]
    features: dict[str, float] = field(default_factory=dict)

    def features_document(self) -> dict[str, Any]:
        """The JSON written beside the mesh, and recorded as `generation_params`."""
        return {
            "archetype": self.archetype,
            "archetype_version": self.archetype_version,
            "spec_sha256": self.spec_hash,
            "parts": sorted(self.parts),
            "features": {k: self.features[k] for k in sorted(self.features)},
        }


def manifold_to_trimesh(man: "manifold3d.Manifold") -> trimesh.Trimesh:
    """Export a Manifold's geometry as a Trimesh with its vertices untouched.

    Raises:
        MeasureError: If the solid is empty or the kernel reports an error status.
    """
    status = man.status()
    if status != manifold3d.Error.NoError:
        raise MeasureError(f"the kernel rejected the solid: {status}")
    if man.is_empty():
        raise MeasureError("the solid is empty — the CSG subtracted everything")
    mesh = man.to_mesh64() if hasattr(man, "to_mesh64") else man.to_mesh()
    vertices = np.asarray(mesh.vert_properties, dtype=np.float64)[:, :3]
    faces = np.asarray(mesh.tri_verts, dtype=np.int64)
    return trimesh.Trimesh(vertices, faces, process=False)


def plane_set(coords: np.ndarray, tol_mm: float = 1e-3) -> list[float]:
    """The distinct axis-aligned planes in one coordinate column, sorted.

    Values closer than `tol_mm` are one plane (float32 export noise is ~1e-5 mm on a
    100 mm part); values a micron or more apart are two. Returns cluster means.
    """
    values = np.sort(np.asarray(coords, dtype=np.float64).ravel())
    if values.size == 0:
        return []
    planes: list[float] = []
    cluster = [values[0]]
    for v in values[1:]:
        if v - cluster[-1] > tol_mm:
            planes.append(float(np.mean(cluster)))
            cluster = [v]
        else:
            cluster.append(v)
    planes.append(float(np.mean(cluster)))
    return planes


def compare_features(
    designed: dict[str, float],
    measured: dict[str, float],
    tol_mm: float = DEFAULT_TOLERANCE_MM,
) -> dict[str, tuple[float, float, float]]:
    """`{feature: (designed, measured, measured − designed)}` for every designed
    feature that was measured. Features the archetype cannot read off geometry (a
    stack height, say) are simply absent from `measured` and skipped here."""
    return {
        name: (float(designed[name]), float(measured[name]), float(measured[name] - designed[name]))
        for name in sorted(designed)
        if name in measured
    }


def assert_features_within(
    designed: dict[str, float],
    measured: dict[str, float],
    tol_mm: float = DEFAULT_TOLERANCE_MM,
    required: Optional[set[str]] = None,
) -> None:
    """Raise `MeasureError` naming every feature outside `tol_mm`, or missing.

    Args:
        designed: Feature → designed mm.
        measured: Feature → measured mm.
        tol_mm: Allowed absolute error.
        required: Features that must be present in `measured`; defaults to all of
            `designed`.
    """
    required = set(designed) if required is None else required
    problems = [f"{name}: not measured" for name in sorted(required - set(measured))]
    for name, (want, got, err) in compare_features(designed, measured, tol_mm).items():
        if abs(err) > tol_mm:
            problems.append(f"{name}: designed {want:.3f} mm, measured {got:.3f} mm (error {err:+.3f} mm)")
    if problems:
        raise MeasureError("features out of tolerance: " + "; ".join(problems))


def export_stl(mesh: trimesh.Trimesh, path: str | Path) -> Path:
    """Write a binary STL. Deterministic for the same vertices and faces."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    mesh.export(str(path), file_type="stl")
    return path
