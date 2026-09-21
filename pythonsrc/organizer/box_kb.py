"""The game-box dimension KB: curated box **interiors**, one sourced number at a time.

This is the "Interior-First" input the board-gamer segment is founded on (roadmap §0.5,
issue #154). An insert compiled against a box nobody measured is the failure mode the
whole practice is about, and `Constraints.max_external_mm` — the field an insert is sized
against — is documented as *a number somebody measured off one copy of a box*. Until now
that number could only be typed. This module is where a curated one comes from.

Four rules hold, and each is enforced at load rather than hoped for:

- **Provenance is per value, not per entry.** Each of the three interior axes is its own
  `Measurement` carrying its own basis, source, capture date and the units it was
  captured in — the shape `Pocket.source` established (issue #84's finding) and the shape
  `docs/dimension-kb-research.md` §8 sketched. A box whose width came off a caliper and
  whose height came off a product page is two different claims, and one `source` string
  on the entry would flatten them into one.
- **An entry with no source cannot be added.** A blank or missing `source` is a
  `BoxKBError` at import, so the file cannot acquire an unsourced row by inattention.
  `folk` — the research document's word for a rule of thumb — is not an accepted basis at
  all: a rule of thumb is not a measurement of a box.
- **A derived interior says what it was derived from.** The issue's constraint verbatim:
  *do not infer an interior from an exterior without saying so in the data.* A
  measurement with `basis: "derived"` must carry a `note`, because the number's whole
  meaning is the subtraction that produced it.
- **The number in the file is the number the source stated.** A source giving inches is
  stored in inches, with `units: "in"`, and `Measurement.value_mm` does the conversion in
  code where a test can read it. BoardGameGeek carries external dimensions only, in
  inches, user-entered, behind a registration-gated commercial licence (issue #154, §0.4)
  — **there is no BGG client here and there must not be one**; this is curation, and the
  inch path exists for the day somebody transcribes an inch source by hand.

**Nothing in this module reaches the network.** It reads one committed JSON file.

Stdlib only, for `dimensions.py`'s reason verbatim: `spec.py` imports this, and the
schema must stay importable in the api-server image, which installs neither trimesh nor
manifold3d.
"""
from __future__ import annotations

import functools
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, Tuple

#: Where the curated file lives. In-tree data beside `data/ip_blocklist.json`, for that
#: file's reasons: reviewable in a diff, testable, and not something `ConfigStore.set`
#: could ever be talked into writing.
KB_PATH = Path(__file__).resolve().parent.parent / "data" / "game_boxes.v1.json"

#: Millimetres per inch, exactly. The only unit conversion this project does.
MM_PER_INCH = 25.4

#: Decimal places kept on a converted millimetre value: 3 → 1 µm, as `spec.MM_DECIMALS`.
#: Imported from nowhere on purpose — `spec.py` imports *this* module, and a cycle for a
#: literal 3 would be a worse trade than repeating it. `tests/test_game_box_kb.py` binds
#: the two.
MM_DECIMALS = 3

#: Units a measurement may be captured in.
UNITS: Tuple[str, ...] = ("mm", "in")

#: How a number was arrived at, in `docs/dimension-kb-research.md`'s own vocabulary:
#: **spec** (the manufacturer states it), **measured** (somebody put a caliper on one),
#: **derived** (computed from another number, which the `note` must name).
#:
#: The research document's fourth word, **folk** (a rule of thumb), is deliberately not
#: here. A rule of thumb about box walls is not a measurement of a box, and an insert
#: compiled against one is exactly the failure this KB exists to prevent.
BASES: Tuple[str, ...] = ("spec", "measured", "derived")

#: What kind of box an entry describes. A `game_box` is a publisher's board-game box —
#: the thing the box insert archetype is about. A `card_case` is a commercial deck box or
#: storage case, which a divider or a small insert is compiled against just the same.
#: Both are "a box interior somebody measured", which is the only property this KB claims.
BOX_KINDS: Tuple[str, ...] = ("game_box", "card_case")

#: `YYYY-MM-DD`. A capture date is the date **this project** took the number off its
#: source, which is not the date the source measured it — nobody knows that, and claiming
#: to would be the fabrication this file exists to refuse.
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

#: An entry id: lowercase, digits, hyphens. It goes into a spec's canonical form and
#: therefore into every `spec_hash`, so it may not carry whitespace or case that a
#: second transcription would get differently.
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class BoxKBError(ValueError):
    """The KB file is not a KB: a missing source, an unknown basis, a bad date.

    A `ValueError` rather than a `SpecError`, because it is a fact about the curated file
    and not about anybody's spec. It is raised at load time, so a file that acquires an
    unsourced row fails the whole suite rather than one test.
    """


def _text(data: Mapping[str, Any], key: str, where: str, *, required: bool = True) -> Optional[str]:
    value = data.get(key)
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip():
        raise BoxKBError(
            f"{where}.{key} must be a non-empty string, got {value!r}"
        )
    return value.strip()


@dataclass(frozen=True)
class Measurement:
    """One interior dimension, with everything needed to audit it.

    `value` and `units` are what the source said; `value_mm` is the conversion. Keeping
    the source's own number in the file is what makes a transcription checkable against
    the page it came from — a file holding 285,75 mm where the source says 11¼ inches
    cannot be diffed against anything.
    """

    value: float
    units: str
    basis: str
    #: Where the number came from: a URL, or a citation specific enough to find again.
    #: **Required.** An entry with no source cannot be added.
    source: str
    #: `YYYY-MM-DD`, the date this project took the number off that source.
    captured_on: str
    #: Free text. **Required when `basis` is `derived`** — see the module docstring.
    note: Optional[str] = None

    @property
    def value_mm(self) -> float:
        """The value in millimetres, rounded to 1 µm like every other mm in the engine."""
        mm = self.value * MM_PER_INCH if self.units == "in" else self.value
        return round(float(mm), MM_DECIMALS)

    def provenance(self) -> str:
        """One sentence naming the number, how it was arrived at, its source and when.

        What the UI prints under a dimension row, and the reason the KB is worth having:
        a millimetre with this sentence beside it is checkable, and one without it is an
        assertion.
        """
        stated = (
            f"{self.value:g} {self.units}"
            if self.units != "mm"
            else f"{self.value_mm:g} mm"
        )
        sentence = f"{stated} ({self.basis}), {self.source}, captured {self.captured_on}"
        return f"{sentence} — {self.note}" if self.note else sentence

    @classmethod
    def from_dict(cls, data: Any, where: str) -> "Measurement":
        if not isinstance(data, Mapping):
            raise BoxKBError(f"{where} must be an object, got {type(data).__name__}")
        unknown = sorted(set(data) - {"value", "units", "basis", "source", "captured_on", "note"})
        if unknown:
            raise BoxKBError(f"{where} has unknown field(s): {', '.join(unknown)}")
        value = data.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise BoxKBError(f"{where}.value must be a positive number, got {value!r}")
        units = _text(data, "units", where)
        if units not in UNITS:
            raise BoxKBError(f"{where}.units must be one of {list(UNITS)}, got {units!r}")
        basis = _text(data, "basis", where)
        if basis not in BASES:
            raise BoxKBError(
                f"{where}.basis must be one of {list(BASES)}, got {basis!r}; a rule of "
                "thumb ('folk') is not a measurement of a box"
            )
        source = _text(data, "source", where)
        captured_on = _text(data, "captured_on", where)
        if not _DATE_RE.match(captured_on or ""):
            raise BoxKBError(
                f"{where}.captured_on must be a YYYY-MM-DD date, got {captured_on!r}"
            )
        note = _text(data, "note", where, required=False)
        if basis == "derived" and not note:
            raise BoxKBError(
                f"{where} is derived and carries no note; a derived interior must say "
                "what it was derived from — inferring an interior from an exterior "
                "without saying so in the data is the one thing this KB may not do"
            )
        return cls(
            value=float(value), units=units, basis=basis, source=source,
            captured_on=captured_on, note=note,
        )

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "value": self.value,
            "units": self.units,
            "basis": self.basis,
            "source": self.source,
            "captured_on": self.captured_on,
        }
        if self.note:
            data["note"] = self.note
        return data


#: The three interior axes, in the order `Constraints.max_external_mm` writes them.
AXES: Tuple[str, ...] = ("width", "depth", "height")


@dataclass(frozen=True)
class BoxEntry:
    """One curated box, and the three sourced numbers that are its interior.

    `interior_mm` is `(W, D, H)` — the same order and the same meaning as
    `Constraints.max_external_mm`, which is what a spec naming this entry gets filled
    with. It is a **limit**, not a target: `Constraints.fit_margin_mm` still comes off
    every axis of it (`effective_max_external_mm`), because boxes flare and vary ±1–2 mm
    between copies of the same title (`docs/dimension-kb-research.md` §7) and a curated
    number is a measurement of one copy exactly as a typed one is.
    """

    id: str
    name: str
    kind: str
    width: Measurement
    depth: Measurement
    height: Measurement
    publisher: Optional[str] = None
    note: Optional[str] = None

    @property
    def interior_mm(self) -> Tuple[float, float, float]:
        """`(W, D, H)` in mm, ready for `Constraints.max_external_mm`."""
        return (self.width.value_mm, self.depth.value_mm, self.height.value_mm)

    @property
    def measurements(self) -> Tuple[Measurement, Measurement, Measurement]:
        """The three axes in `AXES` order, so a caller can zip them against it."""
        return (self.width, self.depth, self.height)

    def provenance(self) -> dict[str, str]:
        """`{axis: sentence}` — what the UI prints under each interior row."""
        return dict(zip(AXES, (m.provenance() for m in self.measurements), strict=True))

    @classmethod
    def from_dict(cls, data: Any, where: str) -> "BoxEntry":
        if not isinstance(data, Mapping):
            raise BoxKBError(f"{where} must be an object, got {type(data).__name__}")
        known = {"id", "name", "kind", "publisher", "note", "interior"}
        unknown = sorted(set(data) - known)
        if unknown:
            raise BoxKBError(f"{where} has unknown field(s): {', '.join(unknown)}")
        entry_id = _text(data, "id", where)
        if not _ID_RE.match(entry_id or ""):
            raise BoxKBError(
                f"{where}.id must be lowercase letters, digits and hyphens, got "
                f"{entry_id!r}; it travels in every spec_hash that names it"
            )
        kind = _text(data, "kind", where)
        if kind not in BOX_KINDS:
            raise BoxKBError(f"{where}.kind must be one of {list(BOX_KINDS)}, got {kind!r}")
        interior = data.get("interior")
        if not isinstance(interior, Mapping):
            raise BoxKBError(f"{where}.interior must be an object, got {interior!r}")
        missing = [axis for axis in AXES if axis not in interior]
        if missing:
            raise BoxKBError(
                f"{where}.interior is missing {', '.join(missing)}; an interior is three "
                "numbers and a partial one sizes nothing"
            )
        extra = sorted(set(interior) - set(AXES))
        if extra:
            raise BoxKBError(f"{where}.interior has unknown field(s): {', '.join(extra)}")
        return cls(
            id=entry_id,
            name=_text(data, "name", where),
            kind=kind,
            width=Measurement.from_dict(interior["width"], f"{where}.interior.width"),
            depth=Measurement.from_dict(interior["depth"], f"{where}.interior.depth"),
            height=Measurement.from_dict(interior["height"], f"{where}.interior.height"),
            publisher=_text(data, "publisher", where, required=False),
            note=_text(data, "note", where, required=False),
        )

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"id": self.id, "name": self.name, "kind": self.kind}
        if self.publisher:
            data["publisher"] = self.publisher
        if self.note:
            data["note"] = self.note
        data["interior"] = {
            axis: m.to_dict() for axis, m in zip(AXES, self.measurements, strict=True)
        }
        return data


@dataclass(frozen=True)
class BoxKB:
    """The curated file, loaded: a version and the entries, keyed by id."""

    version: str
    entries: Tuple[BoxEntry, ...]

    def get(self, entry_id: Any) -> Optional[BoxEntry]:
        """The entry with that id, or None. Not a `KeyError`: an unknown game is the
        **degraded mode** this KB is designed around, not an exception."""
        if not isinstance(entry_id, str):
            return None
        return self._by_id.get(entry_id)

    @functools.cached_property
    def _by_id(self) -> dict[str, BoxEntry]:
        return {entry.id: entry for entry in self.entries}

    @property
    def ids(self) -> Tuple[str, ...]:
        return tuple(entry.id for entry in self.entries)

    def content_sha256(self) -> str:
        """sha256 of the entries' canonical JSON, **without** the version.

        What binds `version` to the numbers under it. A declared version nobody has to
        bump is a version that stops meaning anything the first time a measurement is
        corrected in place, and a spec recording `kb_version` would then name a version
        whose numbers are not the ones it was built from.
        `tests/test_game_box_kb.py` pins this digest beside the version, so editing an
        entry without bumping the version fails the suite — the
        `tests/test_supabase_migration.py` idiom, for the same reason.
        """
        canonical = json.dumps(
            [entry.to_dict() for entry in self.entries],
            sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_kb(path: Path | str = KB_PATH) -> BoxKB:
    """Read and validate the curated file. Uncached — `kb()` is the cached accessor.

    Raises:
        BoxKBError: For any problem with the file's shape or with an entry.
        OSError: If the file cannot be read.
    """
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BoxKBError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(data, Mapping):
        raise BoxKBError(f"{path} must hold an object, got {type(data).__name__}")
    version = _text(data, "version", "kb")
    raw = data.get("boxes")
    if not isinstance(raw, list) or not raw:
        raise BoxKBError("kb.boxes must be a non-empty list of box entries")
    entries = tuple(
        BoxEntry.from_dict(item, f"kb.boxes[{i}]") for i, item in enumerate(raw)
    )
    seen: set[str] = set()
    for entry in entries:
        if entry.id in seen:
            raise BoxKBError(f"kb.boxes has two entries with id {entry.id!r}")
        seen.add(entry.id)
    return BoxKB(version=version, entries=entries)


@functools.lru_cache(maxsize=1)
def kb() -> BoxKB:
    """The curated KB, loaded once per process.

    Cached because `OrganizerSpec.__post_init__` consults it on every spec built, and a
    spec is built per keystroke by `POST /organizer/resolve`.
    """
    return load_kb()
