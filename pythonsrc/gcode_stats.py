"""Extract print statistics from sliced G-code.

CuraEngine's command-line interface does not populate its own G-code header. A real
artifact produced by this pipeline reads:

    ;FLAVOR:Marlin
    ;TIME:6666
    ;Filament used: 0m          <- wrong; the print extrudes several metres
    ;MINX:2.14748e+06           <- int32 sentinel, never overwritten

``;TIME:`` is trustworthy. The filament figure and the bounding box are not, because the
CLI path skips the pass that would fill them in. Reading the header alone would therefore
record "0 m of filament" for every job in the dataset.

So the numbers here are derived from the E axis instead, in one streaming pass: sum the
positive extruder deltas, attributing each to whichever ``;TYPE:`` section it falls in.
That also yields the support figure, which the header never carries in any Cura version.

Volume follows from length and filament diameter; mass follows from volume and material
density, and is left None when the material is unknown rather than guessed.
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, Iterable

logger = logging.getLogger(__name__)

DEFAULT_FILAMENT_DIAMETER_MM = 1.75

# Grams per cubic centimetre, from manufacturer spec sheets. Only types the UI offers
# are listed; an unrecognised material yields a null mass rather than a wrong one.
MATERIAL_DENSITY_G_CM3: Dict[str, float] = {
    "PLA": 1.24,
    "PETG": 1.27,
    "ABS": 1.04,
    "TPU": 1.21,
    "ASA": 1.07,
    "NYLON": 1.14,
}

# Cura marks support extrusion with these two feature types.
SUPPORT_TYPES = frozenset({"SUPPORT", "SUPPORT-INTERFACE"})

# Extrusion attributed before any ;TYPE: comment appears — priming lines, mostly.
UNTYPED = "UNTYPED"

# An unset bounding box comes back as MIN=+2.14748e+06 and MAX=-2.14748e+06 — the int32
# millimetre limits used as initial +INF/-INF. No real printer approaches a kilometre, so
# either an inverted range or a value this large means the field was never written.
_IMPLAUSIBLE_MM = 1.0e6

_WORD_RE = re.compile(r"([A-Za-z])\s*(-?\d*\.?\d+(?:[eE][-+]?\d+)?)")


@dataclass
class SliceStats:
    """Statistics derived from a sliced G-code file."""

    filament_used_mm: float = 0.0
    """Total filament length extruded, in millimetres."""

    filament_used_mm3: float = 0.0
    """Total filament volume extruded, in cubic millimetres."""

    filament_used_g: float | None = None
    """Total filament mass in grams, or None when the material is unknown."""

    support_filament_mm: float = 0.0
    """Filament length spent on support structures, in millimetres."""

    support_filament_mm3: float = 0.0
    """Filament volume spent on support structures, in cubic millimetres."""

    estimated_print_time_s: int | None = None
    """Print time estimate in seconds, from the header."""

    layer_count: int | None = None
    """Number of layers."""

    layer_height_mm: float | None = None
    """Layer height, from the header."""

    filament_diameter_mm: float = DEFAULT_FILAMENT_DIAMETER_MM
    """Filament diameter the volume figures were computed with."""

    material_type: str | None = None
    """Material the mass figure was computed for."""

    flavor: str | None = None
    """G-code flavour declared in the header, e.g. "Marlin"."""

    filament_mm_by_type: Dict[str, float] = field(default_factory=dict)
    """Filament length per ``;TYPE:`` feature, in millimetres."""

    header: Dict[str, str] = field(default_factory=dict)
    """The raw leading comment block, as key/value pairs."""

    header_filament_disagrees: bool = False
    """True when the header quotes a filament figure that contradicts the E axis.

    Expected against CuraEngine's CLI, which leaves the field at zero. Recorded rather
    than silenced so that a future CuraEngine that does fill it in is noticeable.
    """

    line_count: int = 0
    """Number of lines in the file."""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to a JSON-serializable dictionary.

        Returns:
            Dict[str, Any]: A dictionary representation of the statistics.
        """
        return asdict(self)


def filament_volume_mm3(length_mm: float, diameter_mm: float) -> float:
    """Convert an extruded filament length to a volume.

    Args:
        length_mm: Length of filament consumed.
        diameter_mm: Filament diameter.

    Returns:
        The volume in cubic millimetres.
    """
    radius = diameter_mm / 2.0
    return length_mm * math.pi * radius * radius


def _parse_words(line: str) -> Dict[str, float]:
    """Parse a G-code line into its letter/number word pairs.

    Args:
        line: A single line with any trailing comment already stripped.

    Returns:
        A mapping of upper-case address letter to value. Later occurrences win.
    """
    return {m.group(1).upper(): float(m.group(2)) for m in _WORD_RE.finditer(line)}


def _header_filament_mm(raw: str) -> float | None:
    """Parse the header's ``;Filament used:`` value into millimetres.

    The field is written in metres and may list one entry per extruder.

    Args:
        raw: The value portion of the header line, e.g. "1.234m" or "1.2m, 0.3m".

    Returns:
        The total length in millimetres, or None if nothing parseable was found.
    """
    values = re.findall(r"(-?\d*\.?\d+)\s*m", raw)
    if not values:
        return None
    try:
        return sum(float(v) for v in values) * 1000.0
    except ValueError:
        return None


def parse_gcode_lines(
    lines: Iterable[str],
    *,
    filament_diameter_mm: float = DEFAULT_FILAMENT_DIAMETER_MM,
    material_type: str | None = None,
) -> SliceStats:
    """Compute slice statistics from an iterable of G-code lines.

    Extrusion mode is tracked because the two modes mean opposite things by the same
    ``E`` word: under M82 it is an absolute axis position, under M83 it is a per-move
    delta. Reading one as the other inflates the total by orders of magnitude. ``G92 E``
    resets the datum without extruding, so it must move the reference point rather than
    register as a move.

    Negative deltas are retractions — filament pulled back, not consumed — and are
    excluded from the totals while still updating the reference position.

    Args:
        lines: G-code lines, with or without trailing newlines.
        filament_diameter_mm: Filament diameter used for the volume conversion.
        material_type: Material name used for the mass conversion; unknown names give
            a null mass.

    Returns:
        The computed SliceStats.
    """
    stats = SliceStats(
        filament_diameter_mm=filament_diameter_mm,
        material_type=material_type,
    )

    relative_extrusion = False
    last_e = 0.0
    current_type = UNTYPED
    by_type: Dict[str, float] = {}
    max_layer_index: int | None = None
    extruding_z: set[float] = set()
    current_z: float | None = None
    in_header = True
    total_mm = 0.0

    for raw_line in lines:
        stats.line_count += 1
        line = raw_line.strip()
        if not line:
            continue

        if line.startswith(";"):
            comment = line[1:].strip()

            if in_header and ":" in comment:
                key, _, value = comment.partition(":")
                stats.header.setdefault(key.strip(), value.strip())

            if comment.startswith("TYPE:"):
                current_type = comment[5:].strip().upper() or UNTYPED
            elif comment.startswith("LAYER:"):
                try:
                    index = int(comment[6:].strip())
                except ValueError:
                    pass
                else:
                    max_layer_index = index if max_layer_index is None else max(max_layer_index, index)
            continue

        in_header = False
        code = line.split(";", 1)[0].strip()
        if not code:
            continue

        upper = code.upper()

        if upper.startswith("M82"):
            relative_extrusion = False
            continue
        if upper.startswith("M83"):
            relative_extrusion = True
            continue

        if upper.startswith("G92"):
            words = _parse_words(code)
            if "E" in words:
                last_e = words["E"]
            continue

        if not (upper.startswith("G0 ") or upper.startswith("G1 ")
                or upper in ("G0", "G1")):
            continue

        words = _parse_words(code)
        if "Z" in words:
            current_z = words["Z"]
        if "E" not in words:
            continue

        e_value = words["E"]
        if relative_extrusion:
            delta = e_value
        else:
            delta = e_value - last_e
            last_e = e_value

        if delta <= 0:
            continue

        total_mm += delta
        by_type[current_type] = by_type.get(current_type, 0.0) + delta
        if current_z is not None:
            extruding_z.add(round(current_z, 3))

    stats.filament_used_mm = round(total_mm, 4)
    stats.filament_used_mm3 = round(filament_volume_mm3(total_mm, filament_diameter_mm), 4)
    stats.filament_mm_by_type = {k: round(v, 4) for k, v in sorted(by_type.items())}

    support_mm = sum(v for k, v in by_type.items() if k in SUPPORT_TYPES)
    stats.support_filament_mm = round(support_mm, 4)
    stats.support_filament_mm3 = round(
        filament_volume_mm3(support_mm, filament_diameter_mm), 4
    )

    density = MATERIAL_DENSITY_G_CM3.get((material_type or "").strip().upper())
    if density is not None:
        # mm3 → cm3 is a factor of 1000.
        stats.filament_used_g = round(stats.filament_used_mm3 / 1000.0 * density, 3)

    if max_layer_index is not None:
        stats.layer_count = max_layer_index + 1
    elif extruding_z:
        stats.layer_count = len(extruding_z)

    time_raw = stats.header.get("TIME")
    if time_raw:
        try:
            stats.estimated_print_time_s = int(float(time_raw))
        except ValueError:
            logger.warning("Unparseable ;TIME: header value %r", time_raw)

    height_raw = stats.header.get("Layer height")
    if height_raw:
        try:
            stats.layer_height_mm = float(height_raw)
        except ValueError:
            pass

    stats.flavor = stats.header.get("FLAVOR")

    header_mm = _header_filament_mm(stats.header.get("Filament used", ""))
    if header_mm is not None:
        if total_mm <= 0.0 and header_mm > 0.0:
            # Nothing derivable from the E axis, but the header has a figure: trust it.
            stats.filament_used_mm = round(header_mm, 4)
            stats.filament_used_mm3 = round(
                filament_volume_mm3(header_mm, filament_diameter_mm), 4
            )
            if density is not None:
                stats.filament_used_g = round(
                    stats.filament_used_mm3 / 1000.0 * density, 3
                )
        elif total_mm > 0.0 and not math.isclose(header_mm, total_mm, rel_tol=0.05):
            stats.header_filament_disagrees = True

    return stats


def parse_gcode_file(
    path: str | Path,
    *,
    filament_diameter_mm: float = DEFAULT_FILAMENT_DIAMETER_MM,
    material_type: str | None = None,
) -> SliceStats:
    """Compute slice statistics for a G-code file.

    Args:
        path: Path to the .gcode file.
        filament_diameter_mm: Filament diameter used for the volume conversion.
        material_type: Material name used for the mass conversion.

    Returns:
        The computed SliceStats.

    Raises:
        FileNotFoundError: If the file does not exist.
    """
    path = Path(path)
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        return parse_gcode_lines(
            handle,
            filament_diameter_mm=filament_diameter_mm,
            material_type=material_type,
        )


def header_bbox_is_populated(header: Dict[str, str]) -> bool:
    """Report whether a G-code header's bounding box holds real values.

    CuraEngine's CLI leaves MINX/MAXX at the int32 millimetre sentinel. Callers that
    want print dimensions should measure the mesh instead when this returns False.

    Args:
        header: The parsed header mapping.

    Returns:
        True if the bounding box looks like real geometry.
    """
    try:
        min_x, min_y = float(header["MINX"]), float(header["MINY"])
        max_x, max_y = float(header["MAXX"]), float(header["MAXY"])
    except (KeyError, ValueError):
        return False
    if max_x <= min_x or max_y <= min_y:
        return False
    return all(
        abs(v) < _IMPLAUSIBLE_MM for v in (min_x, min_y, max_x, max_y)
    )
