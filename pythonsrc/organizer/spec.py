"""The organizer spec — the structured description an archetype compiles into geometry.

This object is the boundary the pivot is built on: *the LLM interprets words; it never
produces geometry.* Everything to the left of a spec (a prompt, an extraction call, a
form) is allowed to be probabilistic. Everything to the right (the archetype compilers,
Phase 3, the slicer) is deterministic, and the same spec must compile to the same mesh
byte for byte. Five roadmap features are functions of this object — extraction (F2),
the template engine (F5), iterate-by-prompt as a spec *diff* (F8), saved designs (F11),
the test-fit coupon (F12) — and `web/src/organizer/spec.ts` already declares the view
the UI expects of it.

Three properties follow, and each is enforced here rather than hoped for:

- **It round-trips exactly.** Every millimetre float is rounded to 1 µm on
  construction, so `from_dict(to_dict(s)) == s` holds and the canonical form carries
  no float noise. `from_dict` refuses unknown keys — a typo in a field name must not
  silently become the default.
- **It is refused whole.** Validation collects every problem with its dotted field
  path and raises one `SpecError`, so a bad spec is rejected once with the full list
  rather than one field per attempt. Field-level rules live in each class's
  `__post_init__`; rules that belong to a *shape* (a lip too thin, a second
  compartment, a tab wider than its plate) live in the archetype, because they are
  facts about one shape rather than about specs.
- **It is one thing.** `canonical_json` sorts keys and strips whitespace, `spec_hash`
  is its sha256, `spec_diff` compares two specs path by path. The hash is what the
  UI's `OrganizerSpec.hash` carries and what a future gate approval binds to.

Stdlib only, on purpose: the api-server image installs neither trimesh nor
manifold3d, and the schema must be importable there when the request model grows a
spec field. Mirrors the `telemetry/schema.py` dataclass pattern.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import math
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Mapping, Optional, Tuple

from .dimensions import CARD_KINDS, SLEEVINGS

#: Bumped when a field's meaning changes. A spec written under another version is
#: refused rather than reinterpreted.
SCHEMA_VERSION = 1

#: Archetypes a spec may name. The registry in `archetypes/` must cover each, and
#: `web/src/organizer/spec.ts`'s `ARCHETYPES` must be the same set — a strip offering a
#: shape the engine cannot compile is the same fabrication as an unmeasured fits badge.
#: `tests/test_archetype_registry.py` binds the three lists.
ARCHETYPES: tuple[str, ...] = ("deck_box", "card_divider")

#: Lid mechanisms the schema knows. Slide, hinged and magnetic lids are later
#: archetype variants (roadmap M1/M3) and are not accepted until they exist.
LID_KINDS: tuple[str, ...] = ("lift_off",)

#: Where a divider's label tab sits along the plate's top edge.
TAB_POSITIONS: tuple[str, ...] = ("left", "centre", "right")

#: Decimal places kept on every millimetre value: 3 → 1 µm.
MM_DECIMALS = 3


class SpecError(ValueError):
    """A spec that cannot be compiled, with every problem listed.

    Attributes:
        problems: One human-readable sentence per problem, each naming the field.
    """

    def __init__(self, problems: list[str]):
        self.problems = list(problems)
        super().__init__("invalid spec: " + "; ".join(self.problems))


def _mm(value: Any, name: str, problems: list[str], *, minimum: float = 0.0,
        inclusive: bool = False) -> Any:
    """Validate one millimetre value and return it rounded to `MM_DECIMALS`.

    Appends to `problems` rather than raising, so a caller can report every bad field
    at once. Returns the input unchanged when it is not a number, so the dataclass
    still holds *something* until the collected error is raised.
    """
    if isinstance(value, bool):
        problems.append(f"{name} must be a number in mm, got {value!r}")
        return value
    try:
        number = float(value)
    except (TypeError, ValueError):
        problems.append(f"{name} must be a number in mm, got {value!r}")
        return value
    if not math.isfinite(number):
        problems.append(f"{name} must be finite, got {value!r}")
        return number
    too_small = number < minimum if inclusive else number <= minimum
    if too_small:
        bound = "≥" if inclusive else ">"
        problems.append(f"{name} must be {bound} {minimum:g} mm, got {number:g}")
    return round(number, MM_DECIMALS)


def _set(obj: Any, name: str, value: Any) -> None:
    """Assign on a frozen dataclass — only ever used inside `__post_init__`."""
    object.__setattr__(obj, name, value)


def _raise_if(problems: list[str]) -> None:
    if problems:
        raise SpecError(problems)


# ── leaf objects ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CardStack:
    """A stack of cards: how many, which size, how sleeved."""

    count: int
    card: str = "standard"
    sleeving: str = "double"

    def __post_init__(self) -> None:
        problems: list[str] = []
        if isinstance(self.count, bool) or not isinstance(self.count, int) or self.count < 1:
            problems.append(f"count must be an integer ≥ 1, got {self.count!r}")
        if self.card not in CARD_KINDS:
            problems.append(f"card must be one of {sorted(CARD_KINDS)}, got {self.card!r}")
        if self.sleeving not in SLEEVINGS:
            problems.append(f"sleeving must be one of {list(SLEEVINGS)}, got {self.sleeving!r}")
        _raise_if(problems)


@dataclass(frozen=True)
class Compartment:
    """One pocket of the organizer and what it holds. v1 holds card stacks only."""

    contents: CardStack

    def __post_init__(self) -> None:
        if not isinstance(self.contents, CardStack):
            raise SpecError([f"contents must be a CardStack, got {type(self.contents).__name__}"])


@dataclass(frozen=True)
class Lid:
    """The closure. `height_mm` is how far the lid engages over the body's lip."""

    kind: str = "lift_off"
    magnets: bool = False
    height_mm: float = 15.0
    wall_mm: float = 1.2
    clearance_mm: float = 0.2
    top_mm: float = 2.0

    def __post_init__(self) -> None:
        problems: list[str] = []
        if self.kind not in LID_KINDS:
            problems.append(f"kind must be one of {list(LID_KINDS)}, got {self.kind!r}")
        if not isinstance(self.magnets, bool):
            problems.append(f"magnets must be true or false, got {self.magnets!r}")
        _set(self, "height_mm", _mm(self.height_mm, "height_mm", problems))
        _set(self, "wall_mm", _mm(self.wall_mm, "wall_mm", problems))
        _set(self, "clearance_mm", _mm(self.clearance_mm, "clearance_mm", problems, inclusive=True))
        _set(self, "top_mm", _mm(self.top_mm, "top_mm", problems))
        _raise_if(problems)


@dataclass(frozen=True)
class Divider:
    """The plate and label tab of a card divider.

    A section on the spec rather than constants inside `card_divider.py` for two
    reasons that are the same reason: F8 iterates a design by spec *diff*, so "make the
    tab wider" must be a path (`divider.tab_width_mm`) rather than an archetype's
    private habit, and the deck box's closure numbers already live in `Lid` for exactly
    that. Only `card_divider` reads it; every other archetype refuses a spec that
    carries one, because ignoring a section prints a different part in silence.

    `thickness_mm` defaults to the middle of the 1,2–1,6 mm band the audited insert
    document gives (roadmap §0.5 — one practitioner's practice, not a standard), which
    is also seven 0,2 mm layers. **The tab figures are design defaults, not
    measurements**: nothing in `docs/dimension-kb-research.md` sources a divider tab,
    and `to_view` says so on the row rather than presenting them as sourced.
    """

    thickness_mm: float = 1.4
    tab_width_mm: float = 20.0
    tab_height_mm: float = 10.0
    tab_position: str = "centre"

    def __post_init__(self) -> None:
        problems: list[str] = []
        _set(self, "thickness_mm", _mm(self.thickness_mm, "thickness_mm", problems))
        _set(self, "tab_width_mm", _mm(self.tab_width_mm, "tab_width_mm", problems))
        _set(self, "tab_height_mm", _mm(self.tab_height_mm, "tab_height_mm", problems))
        if self.tab_position not in TAB_POSITIONS:
            problems.append(
                f"tab_position must be one of {list(TAB_POSITIONS)}, got {self.tab_position!r}"
            )
        _raise_if(problems)


@dataclass(frozen=True)
class Constraints:
    """External limits the finished part must fit within: (W, D, H) in mm, or None.

    `max_external_mm` is a number somebody measured off *one* copy of a box, and
    `docs/dimension-kb-research.md` §7 is why that is not the number to build to:
    there is no public database of game-box internals, the community measurements
    that exist are per-game, and boxes flare and vary ±1–2 mm between copies of the
    same title. The audited insert standard (roadmap §0.5) therefore makes a 2 mm
    reduction on total dimensions **mandatory** — an insert that presses outward
    splits the cardboard at the corners and lifts the lid, which is its named
    catastrophic failure — and BIT's leave-3/3/2 rule says the same.

    So the limit an archetype compares against is never the stated one:
    `effective_max_external_mm()` takes `fit_margin_mm` off every axis first.
    """

    max_external_mm: Optional[Tuple[float, float, float]] = None
    #: Taken off `max_external_mm` on **every** axis before any archetype compares its
    #: envelope against it. The default is `docs/dimension-kb-research.md` §7's "ship
    #: internal dims as user input with a −2 mm safety default". Set it to **0** when
    #: you measured the actual box you are filling and want the number you measured
    #: honoured verbatim; that restores the pre-margin comparison exactly, message and
    #: all. It has no effect without a `max_external_mm` to subtract it from.
    fit_margin_mm: float = 2.0

    def __post_init__(self) -> None:
        problems: list[str] = []
        _set(self, "fit_margin_mm",
             _mm(self.fit_margin_mm, "fit_margin_mm", problems, inclusive=True))
        if self.max_external_mm is not None:
            values = self.max_external_mm
            if not isinstance(values, (list, tuple)) or len(values) != 3:
                problems.append(
                    f"max_external_mm must be three numbers (W, D, H), got {values!r}"
                )
                _raise_if(problems)
            rounded = tuple(
                _mm(v, f"max_external_mm[{i}]", problems) for i, v in enumerate(values)
            )
            _raise_if(problems)
            _set(self, "max_external_mm", rounded)
        _raise_if(problems)

    def effective_max_external_mm(self) -> Optional[Tuple[float, float, float]]:
        """`max_external_mm` with `fit_margin_mm` taken off every axis, or None.

        The one place the subtraction happens, so two archetypes cannot disagree about
        what the limit is. A margin larger than the limit yields a negative one rather
        than being clamped: that is a limit nothing can satisfy, and saying so with the
        arithmetic visible beats silently comparing against zero.
        """
        if self.max_external_mm is None:
            return None
        return tuple(  # type: ignore[return-value]
            round(v - self.fit_margin_mm, MM_DECIMALS) for v in self.max_external_mm
        )


@dataclass(frozen=True)
class Process:
    """Printing-process parameters the archetype applies. Fit offsets per printer
    profile (roadmap M1) will join these; today they are spec-level."""

    wall_mm: float = 2.8
    floor_mm: float = 2.0
    cavity_clearance_mm: float = 1.5
    stack_slack_mm: float = 1.0
    min_feature_mm: float = 1.0

    def __post_init__(self) -> None:
        problems: list[str] = []
        _set(self, "wall_mm", _mm(self.wall_mm, "wall_mm", problems))
        _set(self, "floor_mm", _mm(self.floor_mm, "floor_mm", problems))
        _set(self, "cavity_clearance_mm",
             _mm(self.cavity_clearance_mm, "cavity_clearance_mm", problems, inclusive=True))
        _set(self, "stack_slack_mm",
             _mm(self.stack_slack_mm, "stack_slack_mm", problems, inclusive=True))
        _set(self, "min_feature_mm", _mm(self.min_feature_mm, "min_feature_mm", problems))
        _raise_if(problems)


# ── the spec ───────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class OrganizerSpec:
    """Everything an archetype needs to compile one organizer."""

    archetype: str
    compartments: Tuple[Compartment, ...]
    lid: Optional[Lid] = None
    divider: Optional[Divider] = None
    constraints: Constraints = field(default_factory=Constraints)
    process: Process = field(default_factory=Process)
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        problems: list[str] = []
        if self.archetype not in ARCHETYPES:
            problems.append(f"archetype must be one of {list(ARCHETYPES)}, got {self.archetype!r}")
        compartments = self.compartments
        if isinstance(compartments, list):
            compartments = tuple(compartments)
            _set(self, "compartments", compartments)
        if not isinstance(compartments, tuple) or not compartments:
            problems.append("compartments must hold at least one compartment")
        else:
            for i, c in enumerate(compartments):
                if not isinstance(c, Compartment):
                    problems.append(f"compartments[{i}] must be a Compartment, got {type(c).__name__}")
        if self.lid is not None and not isinstance(self.lid, Lid):
            problems.append(f"lid must be a Lid or null, got {type(self.lid).__name__}")
        if self.divider is not None and not isinstance(self.divider, Divider):
            problems.append(
                f"divider must be a Divider or null, got {type(self.divider).__name__}"
            )
        if not isinstance(self.constraints, Constraints):
            problems.append("constraints must be a Constraints object")
        if not isinstance(self.process, Process):
            problems.append("process must be a Process object")
        if self.schema_version != SCHEMA_VERSION:
            problems.append(
                f"schema_version must be {SCHEMA_VERSION}, got {self.schema_version!r}"
            )
        _raise_if(problems)

    # ── serialisation ──────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """The spec as plain JSON types (tuples become lists).

        An absent optional *section* is omitted rather than written as null. That is
        what keeps `spec_hash` an additive-safe identity: `dataclasses.asdict` would put
        `"divider":null` into every deck box spec ever written, moving every stored hash
        for a field those specs do not mention — and the next archetype's section would
        move them all again. `from_dict` defaults each of them to None, so the round
        trip is unaffected.
        """
        data = json.loads(json.dumps(dataclasses.asdict(self)))
        for name in _OPTIONAL_SECTIONS:
            if data.get(name, "keep") is None:
                del data[name]
        return data

    def to_json(self, indent: Optional[int] = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "OrganizerSpec":
        """Build a spec from JSON types, refusing unknown keys and naming every problem.

        Raises:
            SpecError: Listing every problem with its dotted path from `spec`.
        """
        problems: list[str] = []
        spec = _from_mapping(cls, data, "spec", problems)
        if problems or spec is None:
            raise SpecError(problems or ["spec could not be built"])
        return spec

    @classmethod
    def from_json(cls, text: str) -> "OrganizerSpec":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise SpecError([f"spec is not valid JSON: {exc}"]) from exc
        return cls.from_dict(data)


#: Which fields hold nested objects, so `_from_mapping` can descend with a path.
_NESTED: dict[tuple[type, str], Any] = {
    (Compartment, "contents"): CardStack,
    (OrganizerSpec, "lid"): Lid,
    (OrganizerSpec, "divider"): Divider,
    (OrganizerSpec, "constraints"): Constraints,
    (OrganizerSpec, "process"): Process,
}

#: Optional sections `to_dict` omits when absent — one per archetype family. Each is
#: `Optional[...] = None` on `OrganizerSpec` and read by one archetype only.
_OPTIONAL_SECTIONS: tuple[str, ...] = ("lid", "divider")
_LIST_FIELDS: dict[tuple[type, str], type] = {
    (OrganizerSpec, "compartments"): Compartment,
}


def _from_mapping(cls: type, data: Any, path: str, problems: list[str]) -> Any:
    """Build `cls` from a mapping, collecting problems with `path` prefixes.

    Returns None when anything under this node was wrong; the caller decides whether
    that is fatal (it always is — a spec with one bad field is not a spec).
    """
    if not isinstance(data, Mapping):
        problems.append(f"{path} must be an object, got {type(data).__name__}")
        return None
    known = {f.name for f in fields(cls)}
    unknown = sorted(set(data) - known)
    if unknown:
        problems.append(f"{path} has unknown field(s): {', '.join(unknown)}")
    kwargs: dict[str, Any] = {}
    before = len(problems)
    for f in fields(cls):
        if f.name not in data:
            continue
        value = data[f.name]
        child_path = f"{path}.{f.name}"
        if (cls, f.name) in _LIST_FIELDS:
            item_cls = _LIST_FIELDS[(cls, f.name)]
            if not isinstance(value, (list, tuple)):
                problems.append(f"{child_path} must be a list, got {type(value).__name__}")
                continue
            items = [
                _from_mapping(item_cls, item, f"{child_path}[{i}]", problems)
                for i, item in enumerate(value)
            ]
            kwargs[f.name] = tuple(items)
        elif (cls, f.name) in _NESTED:
            if value is None:
                kwargs[f.name] = None
            else:
                kwargs[f.name] = _from_mapping(_NESTED[(cls, f.name)], value, child_path, problems)
        else:
            kwargs[f.name] = value
    if len(problems) > before:
        return None
    try:
        return cls(**kwargs)
    except SpecError as exc:
        problems.extend(f"{path}.{p}" for p in exc.problems)
    except TypeError as exc:
        # A missing required argument is the only TypeError a keyword-only build raises.
        problems.append(f"{path} is missing a required field ({exc})")
    return None


# ── canonical form, hash, diff ─────────────────────────────────────────────────

def canonical_json(spec: OrganizerSpec) -> str:
    """One string per spec: sorted keys, no whitespace, UTF-8 kept as is."""
    return json.dumps(spec.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def spec_hash(spec: OrganizerSpec) -> str:
    """sha256 of the canonical form. Two specs with equal hashes compile identically."""
    return hashlib.sha256(canonical_json(spec).encode("utf-8")).hexdigest()


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    """`{"a": {"b": [1]}}` → `{"a.b[0]": 1}`. Leaves keep their JSON value."""
    out: dict[str, Any] = {}
    if isinstance(value, Mapping):
        for key in sorted(value):
            out.update(_flatten(value[key], f"{prefix}.{key}" if prefix else key))
    elif isinstance(value, list):
        for i, item in enumerate(value):
            out.update(_flatten(item, f"{prefix}[{i}]"))
    else:
        out[prefix] = value
    return out


def spec_diff(a: OrganizerSpec, b: OrganizerSpec) -> dict[str, tuple[Any, Any]]:
    """Every dotted path whose value differs, as (old, new); None on a missing side.

    This is F8 — "make the lid deeper" → spec diff → regenerate — made mechanical,
    and what a saved design's history is made of.
    """
    fa, fb = _flatten(a.to_dict()), _flatten(b.to_dict())
    return {
        path: (fa.get(path), fb.get(path))
        for path in sorted(set(fa) | set(fb))
        if fa.get(path) != fb.get(path)
    }


# ── files ──────────────────────────────────────────────────────────────────────

def load_spec(path: str | Path) -> OrganizerSpec:
    """Read and validate a spec file.

    Raises:
        SpecError: With every problem, if the file is not a valid spec.
        OSError: If the file cannot be read.
    """
    return OrganizerSpec.from_json(Path(path).read_text(encoding="utf-8"))


def dump_spec(spec: OrganizerSpec, path: str | Path) -> Path:
    """Write a spec as sorted, indented JSON with a trailing newline (diff-friendly)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(spec.to_dict(), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path
