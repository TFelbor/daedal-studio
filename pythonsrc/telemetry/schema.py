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
    
    started_at: datetime
    """The timestamp when the print job started."""
    
    completed_at: datetime | None
    """The timestamp when the print job completed or None if incomplete."""
    
    outcome: Literal["success", "failure", "cancelled", "unknown"]
    """The final outcome of the print job."""

    def to_dict(self) -> Dict[str, Any]:
        """Convert the PrintJob to a JSON-serializable dictionary."""
        d = dataclasses.asdict(self)
        d['started_at'] = self.started_at.isoformat()
        if self.completed_at:
            d['completed_at'] = self.completed_at.isoformat()
        return d

    @classmethod
    def from_dict(cls: Type[PrintJob], data: Dict[str, Any]) -> PrintJob:
        """Create a PrintJob instance from a dictionary."""
        d = data.copy()
        if d.get('started_at'):
            s = d['started_at']
            if s.endswith('Z'): s = s[:-1] + '+00:00'
            d['started_at'] = datetime.fromisoformat(s)
        if d.get('completed_at'):
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
        """Convert the TelemetrySample to a JSON-serializable dictionary."""
        d = dataclasses.asdict(self)
        d['sampled_at'] = self.sampled_at.isoformat()
        return d

    @classmethod
    def from_dict(cls: Type[TelemetrySample], data: Dict[str, Any]) -> TelemetrySample:
        """Create a TelemetrySample instance from a dictionary."""
        d = data.copy()
        if d.get('sampled_at'):
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
    
    failure_type: Literal["thermal_runaway", "layer_shift", "clog", "adhesion", "user_cancelled", "unknown"]
    """The categorized type of failure."""
    
    source: Literal["manual", "automated"]
    """Whether the failure was flagged manually or by an automated system."""
    
    notes: str | None
    """Optional human-readable notes regarding the failure."""
    
    snapshot: dict
    """The last N TelemetrySample records serialized as JSON."""

    def to_dict(self) -> Dict[str, Any]:
        """Convert the FailureEvent to a JSON-serializable dictionary."""
        d = dataclasses.asdict(self)
        d['detected_at'] = self.detected_at.isoformat()
        return d

    @classmethod
    def from_dict(cls: Type[FailureEvent], data: Dict[str, Any]) -> FailureEvent:
        """Create a FailureEvent instance from a dictionary."""
        d = data.copy()
        if d.get('detected_at'):
            s = d['detected_at']
            if s.endswith('Z'): s = s[:-1] + '+00:00'
            d['detected_at'] = datetime.fromisoformat(s)
        return cls(**d)
