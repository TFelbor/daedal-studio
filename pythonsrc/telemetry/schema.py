"""Data schemas for telemetry and job tracking.

This module provides data structures to define print jobs, telemetry samples,
and failure events, including JSON serialization methods.
"""
from __future__ import annotations
import dataclasses
from datetime import datetime
from typing import Literal, Dict, Any, Type, TypeVar

@dataclasses.dataclass
class PrintJob:
    """Represents a print job in the telemetry system."""
    
    job_id: str
    """UUID string uniquely identifying the print job."""
    
    prompt: str
    """The prompt used to generate or describe the print job."""
    
    printer_id: str
    """The ID of the printer assigned to this job."""
    
    printer_firmware: Literal["klipper", "octoprint", "bambu"]
    """The firmware running on the printer."""
    
    slicer: str
    """The slicer software used (e.g. Cura, PrusaSlicer)."""
    
    profile_name: str
    """The print profile name used for slicing."""
    
    started_at: datetime | None
    """The timestamp when the print job started, or None if not yet started."""
    
    completed_at: datetime | None
    """The timestamp when the print job completed or None if incomplete."""
    
    outcome: Literal["success", "failure", "cancelled", "unknown"]
    """The final outcome of the print job."""

    # ── Generation provenance ─────────────────────────────────────────────────
    # Which model produced the mesh, and what it cost. Retro-labelling this is
    # impossible: once a print is done, nothing records whether its mesh came from
    # TripoSR locally or a hosted TRELLIS.2 call, so a model swap silently mixes two
    # populations in the same dataset. All fields are optional so old rows stay valid.

    generation_model: str | None = None
    """Image-to-3D model that produced the mesh, e.g. "TripoSR" or "TRELLIS.2"."""

    generation_model_version: str | None = None
    """Model version, revision or endpoint id, e.g. "fal-ai/trellis-2"."""

    generation_backend: Literal["local", "hosted_api", "unknown"] | None = None
    """Where inference ran — locally, or behind a paid hosted API."""

    generation_params: Dict[str, Any] | None = None
    """Generation settings (steps, target faces, resolution, target size, hollow…)."""

    generation_cost_usd: float | None = None
    """Cost of this generation, for pay-per-generation endpoints. None when self-hosted."""

    generation_duration_s: float | None = None
    """Wall-clock seconds spent generating the mesh."""

    # ── Pre-print quality ─────────────────────────────────────────────────────
    # The printability gate's output, stored alongside the eventual outcome so that
    # (features → predicted score → actual result) is one row.

    mesh_features: Dict[str, Any] | None = None
    """Geometry feature snapshot of the printed mesh (face count, volume, walls…)."""

    printability_score: float | None = None
    """Composite printability score 0–100, or None if never evaluated."""

    printability_verdict: str | None = None
    """Printability label: "ready", "risky" or "unprintable"."""

    printability_report: Dict[str, Any] | None = None
    """Full per-check printability report as produced by `PrintabilityReport.to_dict()`."""

    def __post_init__(self):
        """Validate the instantiated PrintJob fields.

        Raises:
            ValueError: If the outcome field is not a valid predefined state.
        """
        valid_outcomes = {"success", "failure", "cancelled", "unknown"}
        if self.outcome not in valid_outcomes:
            raise ValueError(f"Invalid outcome: {self.outcome}")

    def to_dict(self) -> Dict[str, Any]:
        """Convert the PrintJob to a JSON-serializable dictionary.

        Returns:
            Dict[str, Any]: A dictionary representation of the PrintJob.
        """
        d = dataclasses.asdict(self)
        if self.started_at:
            d['started_at'] = self.started_at.isoformat()
        if self.completed_at:
            d['completed_at'] = self.completed_at.isoformat()
        return d

    @classmethod
    def from_dict(cls: Type[PrintJob], data: Dict[str, Any]) -> PrintJob:
        """Create a PrintJob instance from a dictionary.

        Args:
            data: A dictionary containing PrintJob properties.

        Returns:
            PrintJob: An initialized PrintJob object.
        """
        d = {}
        for f in dataclasses.fields(cls):
            if f.name in data:
                d[f.name] = data[f.name]
            else:
                d[f.name] = None
                
        if d.get('started_at') and isinstance(d['started_at'], str):
            s = d['started_at']
            if s.endswith('Z'): s = s[:-1] + '+00:00'
            d['started_at'] = datetime.fromisoformat(s)
        if d.get('completed_at') and isinstance(d['completed_at'], str):
            c = d['completed_at']
            if c.endswith('Z'): c = c[:-1] + '+00:00'
            d['completed_at'] = datetime.fromisoformat(c)
        return cls(**d)
@dataclasses.dataclass
class TelemetrySample:
    """Represents a single telemetry sample from a print job."""
    
    job_id: str
    """Foreign key linking to the PrintJob."""
    
    sampled_at: datetime
    """The timestamp when this telemetry sample was recorded."""
    
    gcode_line: int | None
    """The current G-code line being executed, if available."""
    
    z_height_mm: float | None
    """The current Z height of the print head in millimeters."""
    
    hotend_actual_c: float | None
    """The actual hotend temperature in Celsius."""
    
    hotend_target_c: float | None
    """The target hotend temperature in Celsius."""
    
    bed_actual_c: float | None
    """The actual bed temperature in Celsius."""
    
    bed_target_c: float | None
    """The target bed temperature in Celsius."""
    
    print_speed_pct: float | None
    """The print speed modifier percentage."""
    
    extrusion_factor_pct: float | None
    """The extrusion factor modifier percentage."""
    
    fan_speed_pct: float | None
    """The part cooling fan speed percentage."""

    def to_dict(self) -> Dict[str, Any]:
        """Convert the TelemetrySample to a JSON-serializable dictionary.

        Returns:
            Dict[str, Any]: A dictionary representation of the TelemetrySample.
        """
        d = dataclasses.asdict(self)
        d['sampled_at'] = self.sampled_at.isoformat()
        return d

    @classmethod
    def from_dict(cls: Type[TelemetrySample], data: Dict[str, Any]) -> TelemetrySample:
        """Create a TelemetrySample instance from a dictionary.

        Args:
            data: A dictionary containing TelemetrySample properties.

        Returns:
            TelemetrySample: An initialized TelemetrySample object.
        """
        d = {}
        for f in dataclasses.fields(cls):
            if f.name in data:
                d[f.name] = data[f.name]
            else:
                d[f.name] = None
                
        if d.get('sampled_at') and isinstance(d['sampled_at'], str):
            s = d['sampled_at']
            if s.endswith('Z'): s = s[:-1] + '+00:00'
            d['sampled_at'] = datetime.fromisoformat(s)
        return cls(**d)
@dataclasses.dataclass
class FailureEvent:
    """Represents a failure event detected during a print job."""
    
    event_id: str
    """UUID string uniquely identifying this failure event."""
    
    job_id: str
    """Foreign key linking to the PrintJob that failed."""
    
    detected_at: datetime
    """The timestamp when the failure was detected."""
    
    gcode_line: int | None
    """The G-code line at which the failure was detected, if known."""
    
    z_height_mm: float | None
    """The Z height at which the failure occurred."""
    
    failure_type: Literal["thermal_runaway", "layer_shift", "clog", "adhesion", "extrusion_issue", "user_cancelled", "unknown"]
    """The categorized type of failure."""
    
    source: Literal["manual", "automated"]
    """Whether the failure was flagged manually or by an automated system."""
    
    notes: str | None
    """Optional human-readable notes regarding the failure."""

    snapshot: list[Dict[str, Any]] | dict
    """The last N TelemetrySample records serialized as JSON.

    Written as a list of ``TelemetrySample.to_dict()`` rows by both the automated
    detector and the manual ``POST /jobs/{id}/failure`` endpoint; ``dict`` is
    accepted for backwards compatibility with older rows.
    """

    def __post_init__(self):
        """Validate FailureEvent fields.

        Raises:
            ValueError: If failure_type or source is not a valid value.
        """
        valid_types = {"thermal_runaway", "layer_shift", "clog", "adhesion", "extrusion_issue", "user_cancelled", "unknown"}
        if self.failure_type not in valid_types:
            raise ValueError(f"Invalid failure_type: {self.failure_type}")
        valid_sources = {"manual", "automated"}
        if self.source not in valid_sources:
            raise ValueError(f"Invalid source: {self.source}")

    def to_dict(self) -> Dict[str, Any]:
        """Convert the FailureEvent to a JSON-serializable dictionary.

        Returns:
            Dict[str, Any]: A dictionary representation of the FailureEvent.
        """
        d = dataclasses.asdict(self)
        d['detected_at'] = self.detected_at.isoformat()
        return d

    @classmethod
    def from_dict(cls: Type[FailureEvent], data: Dict[str, Any]) -> FailureEvent:
        """Create a FailureEvent instance from a dictionary.

        Args:
            data: A dictionary containing FailureEvent properties.

        Returns:
            FailureEvent: An initialized FailureEvent object.
        """
        d = {}
        for f in dataclasses.fields(cls):
            if f.name in data:
                d[f.name] = data[f.name]
            else:
                d[f.name] = None
                
        if d.get('detected_at') and isinstance(d['detected_at'], str):
            s = d['detected_at']
            if s.endswith('Z'): s = s[:-1] + '+00:00'
            d['detected_at'] = datetime.fromisoformat(s)
        return cls(**d)
