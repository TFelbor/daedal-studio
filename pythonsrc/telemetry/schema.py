"""Data schemas for telemetry and job tracking.

This module provides data structures to define print jobs, telemetry samples,
and failure events, including JSON serialization methods.
"""
from __future__ import annotations
import dataclasses
from datetime import datetime
from typing import Literal, Dict, Any, Type

#: Every value `PrintJob.outcome` may hold.
#:
#: Most describe what happened to the part. Four do not, and the distinction matters
#: when querying:
#:
#: - ``unknown`` — the pipeline has not finished. This is a *sentinel*, not a verdict:
#:   the API maps it back to "running", so nothing settled may ever be written as
#:   ``unknown``.
#: - ``awaiting_verdict`` — the printer reached the end of the file and no human has
#:   said whether the part survived.
#: - ``dev`` — a developer's test run. Settled, and deliberately **excluded from
#:   analysis**: verifying a pipeline change by printing a cube must not land in the
#:   column the pilot's success rate is computed from.
#: - ``declined`` — the user was asked, asked again, and does not want to be asked
#:   about this print. Distinct from never being asked (no ``outcome_prompt_shown``
#:   event) and from a single skip (``outcome_prompt_dismissed``).
VALID_OUTCOMES = frozenset({
    "success",
    "failure",
    "cancelled",
    "unknown",
    "awaiting_verdict",
    "dev",
    "declined",
})

#: Outcomes that are not evidence about a printed part, and must be filtered out of
#: any success-rate or failure-mode query.
NON_EVIDENCE_OUTCOMES = frozenset({"unknown", "awaiting_verdict", "dev", "declined"})


#: Where a job's target size came from. Three values, because two of them would
#: collapse the only question this column exists to answer:
#:
#: - ``default`` — nobody chose. The pipeline's own 50 mm applied.
#: - ``user`` — a person set it in the composer or on the CLI.
#: - ``prompt_hint`` — a size was parsed out of the prompt and the user *accepted*
#:   the suggestion. Never written for a hint that was merely offered: a size the
#:   software inferred and applied by itself is not a size anyone asked for.
VALID_SIZE_SOURCES = frozenset({"default", "user", "prompt_hint", "spec"})

#: Which bounding-box extent a target size describes. Mirrors `Engineer.SCALE_AXES`;
#: "height" is the Z extent after the part is seated on the plate, "longest" is the
#: longest edge, which is what the code did before anyone asked a person what they
#: meant by "how big".
VALID_SCALE_AXES = frozenset({"height", "longest"})


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

    request_params: Dict[str, Any] | None = None
    """The submitted job request, as it arrived. Captured because the pipeline runs in
    a different process and the blueprint approval gate resumes it in a *third* one,
    minutes later — `_run_pipeline` holds the request in memory only, so a gate that
    parked by awaiting would lose the job on a server restart. Rebuilding it from the
    individual columns is not equivalent: `pipeline_type` and `mesh_seed` both change
    the geometry and exist nowhere else until Phase 2 has already run."""

    # ── Requested size ────────────────────────────────────────────────────────
    # What the person asked for, which is not what the mesh can tell you. The
    # *applied* size and axis are recoverable from `repair_report`; the request is
    # recoverable from nothing once the row is written, and every job before this
    # column existed silently used 50 mm because nothing forwarded the flag.

    requested_size_mm: float | None = None
    """The target size the requester chose, in millimetres, or None when nobody
    chose one. Deliberately NULL rather than 50.0 in that case: a stored default is
    indistinguishable from a user who typed the default, and "did anyone care about
    size" is the question the pilot needs answered."""

    requested_scale_axis: Literal["height", "longest"] | None = None
    """Which extent `requested_size_mm` was understood to describe, as presented to
    the requester. None when they did not choose. This is the *promise*; the axis
    actually applied is `repair_report["scale_axis"]`, written by Phase 3. They are
    separate columns precisely so they can be compared — a control labelled "Height"
    that produced a longest-edge part is a bug this pairing makes visible."""

    size_source: Literal["default", "user", "prompt_hint", "spec"] | None = None
    """Who decided `requested_size_mm`. See `VALID_SIZE_SOURCES`. None only on rows
    written before this column existed — a live job always has a source, because
    "the default applied" is itself a fact worth recording. `spec` means the job was
    compiled from an organizer spec: every dimension is the spec's, there is no single
    size to record, and `requested_size_mm` and `requested_scale_axis` stay NULL."""

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

    # ── Run context and dispatch provenance ───────────────────────────────────
    # Which code produced this row, whether the inputs were real, and which machine
    # actually received the G-code. None can be recovered after the fact: the working
    # tree moves on, the fixture flag lives only in the pipeline's own head, and the
    # printer URL is resolved from a profile someone will edit next week.

    git_sha: str | None = None
    """Short git commit of the code that ran this job. A change to the prompt
    template, the repair kernel or the scoring weights silently mixes populations
    in the dataset unless rows can be split by code version."""

    used_reference_assets: int | None = None
    """1 when the pipeline substituted the bundled dev-reference blueprint/mesh
    (see `_will_use_reference_assets`), 0 when it confirmed real inputs, None on
    rows from before this column existed. A fixture run must be excludable from
    any training query without comparing hashes by hand."""

    dispatched_printer_url: str | None = None
    """The printer base URL the G-code was actually sent to, captured at the moment
    of dispatch. This is what distinguishes a simulator print (localhost:5001) from
    real hardware — `printer_id` is a constant and profiles are resolved on read."""

    repair_report: Dict[str, Any] | None = None
    """What Phase 3 actually did to the mesh: which repair path ran, how many close
    rounds, whether the volumetric remesh fired, and the scale factor applied.
    Without it, "did voxel remeshing hurt outcomes" is unanswerable."""

    print_duration_s: float | None = None
    """Actual wall-clock print duration as reported by the printer at its terminal
    event. The slicer's `estimated_print_time_s` is a prediction; this is the
    measurement it must be judged against."""

    def __post_init__(self):
        """Validate the instantiated PrintJob fields.

        Raises:
            ValueError: If the outcome field is not a valid predefined state.
        """
        if self.outcome not in VALID_OUTCOMES:
            raise ValueError(f"Invalid outcome: {self.outcome}")
        if self.outcome_source is not None and self.outcome_source not in {"machine", "user"}:
            raise ValueError(f"Invalid outcome_source: {self.outcome_source}")
        if self.slice_status is not None and self.slice_status not in {"success", "failed", "skipped"}:
            raise ValueError(f"Invalid slice_status: {self.slice_status}")
        # None-tolerant on purpose: `__post_init__` runs for every row read back
        # through `_row_to_job`, so rejecting None here would make every
        # pre-migration job unreadable via get_job() and the trace tool.
        if self.size_source is not None and self.size_source not in VALID_SIZE_SOURCES:
            raise ValueError(f"Invalid size_source: {self.size_source}")
        if (self.requested_scale_axis is not None
                and self.requested_scale_axis not in VALID_SCALE_AXES):
            raise ValueError(f"Invalid requested_scale_axis: {self.requested_scale_axis}")

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
#: Every value `FailureEvent.failure_type` may hold.
#:
#: The first five are the `AnomalyDetector`'s own rule names, and the human-reported
#: list in the UI reuses them deliberately: when the detector fires and a person
#: agrees, both records must use the same word, or "how often is the detector right"
#: cannot be answered with a query.
#:
#: The rest are reported by people only. ``other`` is the escape hatch, and it is the
#: one value that means nothing on its own — a report carrying it is expected to carry
#: ``notes`` as well, which is where the actual failure mode is written.
VALID_FAILURE_TYPES = frozenset({
    # Detector rules
    "thermal_runaway",
    "layer_shift",
    "clog",
    "adhesion",
    "extrusion_issue",
    # Human-reported only
    "detached",
    "supports",
    "surface",
    "dimensional",
    "filament_out",
    "user_cancelled",
    "other",
    "unknown",
})


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
        if self.failure_type not in VALID_FAILURE_TYPES:
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
    "dispatch_confirmed",
    # The prompt screen recognised something, but not clearly enough to refuse. There
    # is deliberately no `ip_screen_blocked` counterpart: a block happens before
    # `insert_job`, foreign keys are enforced, and an event for a job row that does
    # not exist cannot be written. Blocks go to the activity feed instead.
    "ip_screen_flagged",
    # The blueprint approval gate. Phase 2 does not run until `blueprint_approved`
    # exists for the job, and `blueprint_rejected` records that a person looked and
    # said no — which is a different fact from never having been asked, and the only
    # thing that stops the gate asking again forever.
    # Recorded when a run actually stops and waits. Without it the gate state was
    # inferred from "a per-job blueprint.png exists", which `pipeline.py` writes on
    # *every* run with a --job-id — so an ungated run reported itself as awaiting
    # approval, and approving it launched a second pipeline for the same job.
    "blueprint_gate_parked",
    "blueprint_approved",
    "blueprint_rejected",
    # Printer lifecycle, written by the collector as the events arrive on the
    # socket. Sparse and discrete, so rows rather than sample columns: a pause is
    # a fact about the print ("someone intervened at layer 40") that no success
    # metric can reconstruct later, and the terminal event's detail carries the
    # firmware's own reason string, which exists only in that one payload.
    "print_paused",
    "print_resumed",
    "printer_terminal",
    # The activation metric's numerator (PRD §7: "≥ 60 % of prompt submitters reach a
    # preview"). Written once per job, by the UI, when the mesh or the toolpath is
    # actually on the stage — not when the artifact appears on disk, which is a fact
    # about the pipeline and not about anyone looking. The denominator is the jobs
    # themselves, so this is the only half that needed an instrument. `download` and
    # `?preview=1` already keep the *export* half of the metric separate: a person
    # rotating a mesh has not kept it.
    "preview_reached",
)
"""Recognised `JobEvent.kind` values.

These are the user-engagement signals that cannot be reconstructed after the fact:
nothing else records that someone downloaded a result, asked for another one, or was
shown a feedback prompt and chose not to answer it.

`dispatch_confirmed` is the newest and the only one that gates an action rather than
describing one: a print reaches a machine because a person looked at the target and
said yes, and the row carries what they were shown. It lives here rather than in a
`print_job` column for the same reason as the others — one table absorbs a new signal
without a migration — and because "who authorised this print" is a decision record,
which is not what the outcome column is for.
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
