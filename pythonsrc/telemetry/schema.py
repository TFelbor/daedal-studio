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
    
    outcome: Literal["success", "failure", "cancelled", "unknown", "awaiting_verdict"]
    """The final outcome of the print job.

    ``awaiting_verdict`` means the printer reported the job finished but no human has
    confirmed whether the part actually came off the bed. See ``outcome_source``.
    """

    # ── Generation provenance ─────────────────────────────────────────────────
    # Which model produced the mesh, and what it cost. Retro-labelling this is
    # impossible: once a print is done, nothing records which model made its mesh or
    # where that model ran, so a model swap silently mixes two populations in the
    # same dataset. All fields are optional so old rows stay valid.

    generation_model: str | None = None
    """Image-to-3D model that produced the mesh, e.g. "TRELLIS.2"."""

    generation_model_version: str | None = None
    """Model version, revision or endpoint id, e.g. "fal-ai/trellis-2"."""

    generation_backend: (
        Literal["local", "remote_worker", "hosted_api", "unknown"] | None
    ) = None
    """Where inference ran.

    ``local`` is in-process. ``remote_worker`` is a self-hosted GPU worker reached
    over HTTP (`services/trellis2_worker`) — distinct from ``hosted_api`` because
    nothing is billed per call, so ``generation_cost_eur`` stays None while
    ``generation_duration_s`` legitimately includes upload and queueing. Folding the
    two together would make both numbers unreadable.
    """

    generation_params: Dict[str, Any] | None = None
    """Generation settings (steps, target faces, resolution, target size, hollow…)."""

    generation_cost_eur: float | None = None
    """Charge for this generation in **euro**, for pay-per-generation endpoints.

    None when self-hosted — `local` and `remote_worker` runs cost nothing per call.
    Recorded in EUR because that is the currency the hosted endpoints bill in; a
    figure stored in one currency and named for another cannot be summed later.
    """

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

    # ── Blueprint provenance (Phase 1) ────────────────────────────────────────
    # Kept under a `blueprint_` prefix rather than folded into `generation_*`, which is
    # documented and read elsewhere as the *sculptor's* provenance. Without these a run
    # cannot be reproduced at all: the seed was previously derived from the wall clock
    # and thrown away, and the prompt actually sent to FLUX is not the user's prompt.

    blueprint_model: str | None = None
    """Text-to-image model that produced the blueprint, e.g. "FLUX.1-schnell"."""

    blueprint_model_version: str | None = None
    """Model revision or HuggingFace repo id."""

    blueprint_seed: int | None = None
    """The RNG seed actually used. Required to reproduce a blueprint."""

    blueprint_prompt_engineered: str | None = None
    """The full string fed to the model, including the clay-render suffix the
    visualizer appends. Differs from `prompt`, which is what the user typed."""

    blueprint_params: Dict[str, Any] | None = None
    """Conditioning settings: steps, guidance_scale, width, height."""

    blueprint_sha256: str | None = None
    """SHA-256 of the blueprint PNG. Identifies user-supplied images under
    `--skip-visualizer`, where no seed or prompt exists."""

    blueprint_duration_s: float | None = None
    """Wall-clock seconds spent generating the blueprint."""

    # ── Mesh lineage ──────────────────────────────────────────────────────────
    # `mesh_features` above stays the *printed* mesh. These two make repair's effect
    # measurable: without a before/after pair there is no way to tell a mesh that was
    # fine from one that repair rescued.

    raw_mesh_sha256: str | None = None
    """SHA-256 of the sculptor's raw mesh, before any repair."""

    raw_mesh_features: Dict[str, Any] | None = None
    """Geometry features of the raw mesh, as produced by `printability.extract_features`."""

    repaired_mesh_sha256: str | None = None
    """SHA-256 of the engineered mesh, after repair, scaling and optional hollowing."""

    repaired_mesh_features: Dict[str, Any] | None = None
    """Geometry features of the repaired mesh."""

    # ── Slicing ───────────────────────────────────────────────────────────────

    slice_status: Literal["success", "failed", "skipped"] | None = None
    """Whether CuraEngine produced G-code for this job."""

    slice_error: str | None = None
    """Slicer error text when `slice_status` is "failed"."""

    slice_duration_s: float | None = None
    """Wall-clock seconds spent slicing."""

    estimated_print_time_s: int | None = None
    """Slicer's print time estimate in seconds."""

    filament_used_mm: float | None = None
    """Total filament length extruded, in millimetres."""

    filament_used_mm3: float | None = None
    """Total filament volume extruded, in cubic millimetres."""

    filament_used_g: float | None = None
    """Total filament mass, derived from volume and material density. None when the
    material is unknown."""

    support_filament_mm3: float | None = None
    """Filament volume spent on support structures, in cubic millimetres."""

    layer_count: int | None = None
    """Number of layers in the sliced G-code."""

    slice_stats: Dict[str, Any] | None = None
    """Full slice statistics: per-feature-type extrusion breakdown and the raw
    G-code header, as produced by `gcode_stats.SliceStats.to_dict()`."""

    # ── Target process and material ───────────────────────────────────────────

    material_type: str | None = None
    """Filament type: PLA, PETG, ABS, TPU, ASA, other."""

    material_brand: str | None = None
    """Filament brand, free text."""

    material_colour: str | None = None
    """Filament colour, free text."""

    nozzle_diameter_mm: float | None = None
    """Nozzle diameter used, in millimetres."""

    process_params: Dict[str, Any] | None = None
    """Snapshot of the resolved printer profile, frozen when the job was created.

    Read this rather than the profile file: profiles are edited in place, so resolving
    them at query time makes a historical job silently claim settings it never used.
    """

    # ── Lineage and engagement ────────────────────────────────────────────────

    parent_job_id: str | None = None
    """The job this one was regenerated from, forming a lineage chain."""

    regeneration_reason: str | None = None
    """Why the user regenerated, when they said."""

    download_count: int = 0
    """How many times this job's G-code has been downloaded. Individual events with
    timestamps live in the `job_event` table."""

    # ── Human-reported outcome ────────────────────────────────────────────────

    outcome_source: Literal["machine", "user"] | None = None
    """Who decided `outcome`. "machine" means the printer reported the job finished,
    which is not the same as the part surviving. Only "user" is ground truth."""

    outcome_reported_at: datetime | None = None
    """When a human recorded their verdict."""

    def __post_init__(self):
        """Validate the instantiated PrintJob fields.

        Raises:
            ValueError: If the outcome field is not a valid predefined state.
        """
        valid_outcomes = {"success", "failure", "cancelled", "unknown", "awaiting_verdict"}
        if self.outcome not in valid_outcomes:
            raise ValueError(f"Invalid outcome: {self.outcome}")
        if self.outcome_source is not None and self.outcome_source not in {"machine", "user"}:
            raise ValueError(f"Invalid outcome_source: {self.outcome_source}")
        if self.slice_status is not None and self.slice_status not in {"success", "failed", "skipped"}:
            raise ValueError(f"Invalid slice_status: {self.slice_status}")

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
        if self.outcome_reported_at:
            d['outcome_reported_at'] = self.outcome_reported_at.isoformat()
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
            elif f.default is not dataclasses.MISSING:
                # Fields with a non-None default (download_count) must keep it rather
                # than being coerced to None, which would violate their declared type.
                d[f.name] = f.default
            else:
                d[f.name] = None

        for key in ('started_at', 'completed_at', 'outcome_reported_at'):
            value = d.get(key)
            if value and isinstance(value, str):
                if value.endswith('Z'):
                    value = value[:-1] + '+00:00'
                d[key] = datetime.fromisoformat(value)
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


JOB_EVENT_KINDS = (
    "download",
    "regenerate",
    "outcome_prompt_shown",
    "outcome_prompt_dismissed",
    "outcome_reported",
)
"""Recognised `JobEvent.kind` values.

These are the user-engagement signals that cannot be reconstructed after the fact:
nothing else records that someone downloaded a result, asked for another one, or was
shown a feedback prompt and chose not to answer it.
"""


@dataclasses.dataclass
class JobEvent:
    """A timestamped user-engagement event attached to a print job.

    One table rather than a column per signal, because the pilot's central question —
    will people report print outcomes — is answered by comparing the counts of
    ``outcome_prompt_shown`` and ``outcome_reported``, and new signals should not each
    require a schema migration.
    """

    event_id: str
    """UUID string uniquely identifying this event."""

    job_id: str
    """Foreign key linking to the PrintJob."""

    occurred_at: datetime
    """When the event happened."""

    kind: str
    """One of `JOB_EVENT_KINDS`."""

    detail: Dict[str, Any] | None = None
    """Event-specific payload, e.g. the artifact name for a download."""

    def __post_init__(self):
        """Validate the event kind.

        Raises:
            ValueError: If `kind` is not a recognised event kind.
        """
        if self.kind not in JOB_EVENT_KINDS:
            raise ValueError(f"Invalid job event kind: {self.kind}")

    def to_dict(self) -> Dict[str, Any]:
        """Convert the JobEvent to a JSON-serializable dictionary.

        Returns:
            Dict[str, Any]: A dictionary representation of the JobEvent.
        """
        d = dataclasses.asdict(self)
        d['occurred_at'] = self.occurred_at.isoformat()
        return d

    @classmethod
    def from_dict(cls: Type[JobEvent], data: Dict[str, Any]) -> JobEvent:
        """Create a JobEvent instance from a dictionary.

        Args:
            data: A dictionary containing JobEvent properties.

        Returns:
            JobEvent: An initialized JobEvent object.
        """
        occurred_at = data.get('occurred_at')
        if isinstance(occurred_at, str):
            if occurred_at.endswith('Z'):
                occurred_at = occurred_at[:-1] + '+00:00'
            occurred_at = datetime.fromisoformat(occurred_at)
        return cls(
            event_id=data['event_id'],
            job_id=data['job_id'],
            occurred_at=occurred_at,
            kind=data['kind'],
            detail=data.get('detail'),
        )
