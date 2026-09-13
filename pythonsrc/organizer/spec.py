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

#: How much room the contents get, in mm of clearance *total per axis* over the sleeve
#: envelope, per fit intent. `docs/dimension-kb-research.md` §3's working convention:
#: "+1,5–2 mm over the sleeve envelope for a snug commercial-style fit; +4–6 mm for
#: easy-in/out printed boxes." One number cannot serve both — a deck box you close and a
#: tray you lift cards out of are different objects, and the roadmap's own finding
#: (§"Numbers refused") is that applying the tray figure universally makes every deck box
#: larger than every commercial reference in the KB, while applying the box figure
#: universally builds a tray nobody can get cards out of.
#:
#: The **low end** of each band is the default, for two different reasons that agree:
#: `snug` at 1,5 mm is what this project has built since the deck box was written and
#: what its measured boxes were checked against, and `easy` at 4,0 mm is the least
#: material a "+4–6 mm" convention can ask for — a clearance is cheap to increase by
#: hand and expensive to discover as an oversized part. An explicit
#: `Process.cavity_clearance_mm` overrides either.
FIT_INTENT_CLEARANCE_MM: dict[str, float] = {"snug": 1.5, "easy": 4.0}

#: The fit intents a spec may name, in the order they widen the cavity.
FIT_INTENTS: tuple[str, ...] = tuple(FIT_INTENT_CLEARANCE_MM)

#: Decimal places kept on every millimetre value: 3 → 1 µm.
MM_DECIMALS = 3

#: The nozzle a wall floor is derived from when nobody hands one in. CuraEngine's own
#: default, and what `printability.ProcessProfile.from_printer_profile` falls back to
#: for a profile with no `machine_nozzle_size` — the same number, on purpose, so the
#: floor a spec is judged against off-pipeline is the floor the pipeline uses.
DEFAULT_NOZZLE_DIAMETER_MM = 0.4

#: Extrusion widths in the thinnest body wall an archetype may build with.
#:
#: Three, because three perimeters at a 0,4 mm nozzle is 1,2 mm, and 1,2 mm is the
#: bottom of the audited insert document's 1,2–1,6 mm band (roadmap §0.5 — one
#: practitioner's practice, not a standard), which calls anything under 1,2 mm flimsy.
#: Expressing it as a multiple of the nozzle rather than as 1,2 mm is the point of
#: issue #72: a 0,6 mm nozzle cannot lay a 1,2 mm wall as three passes, so the floor
#: is a property of the machine and has to move with it. `printability.min_wall_mm`
#: is two nozzle widths — what the extruder can *physically* put down — and this is
#: three, what a wall that carries load wants; they are different numbers answering
#: different questions, and neither is the other's default.
WALL_FLOOR_NOZZLE_MULTIPLE = 3.0

#: The wall each archetype builds with when a spec does not state `process.wall_mm`.
#: One constant per archetype rather than one for the schema, because 2,8 mm — seven
#: perimeters at a 0,4 mm nozzle, sourced by nobody — was defensible for a box you
#: carry and drop and indefensible for a flat insert, and one number cannot be both.
#: Every entry sits above `wall_floor_mm()` at the default nozzle, and
#: `tests/test_archetype_registry.py` binds this map to the registry so a new
#: archetype cannot arrive without choosing.
ARCHETYPE_WALL_MM: dict[str, float] = {
    # 2,4 mm = `Lid.wall_mm` 1,2 + `Lid.clearance_mm` 0,2 + `Process.min_feature_mm`
    # 1,0: the thinnest body wall that still leaves this archetype's own lift-off lid
    # a lip at the minimum feature size, which `deck_box.validate` refuses below. So
    # it is not a taste figure — it is the closure's arithmetic, read off the lid
    # defaults it has to mate with, and `tests/test_deck_box.py` binds it to them. At
    # six perimeters it is double the audited floor, which is the margin a hand-carried
    # box that gets dropped is worth; the insert band is for parts that sit in a box.
    "deck_box": 2.4,
    # The divider reads `divider.thickness_mm` and never `process.wall_mm` — see that
    # module's "Process fields this archetype does not read still hash" — so this
    # number builds nothing. It is the floor at the default nozzle rather than an
    # invented figure, so a spec that carries it claims no wall the plate does not
    # have. `card_divider.USES_PROCESS_WALL_MM` is False and the floor check skips it.
    "card_divider": 1.2,
}


def wall_floor_mm(nozzle_diameter_mm: float = DEFAULT_NOZZLE_DIAMETER_MM) -> float:
    """The thinnest body wall a spec may ask for on this nozzle, in mm.

    `WALL_FLOOR_NOZZLE_MULTIPLE × nozzle`, rounded to 1 µm like every other millimetre
    here: 1,2 mm at 0,4 mm, 1,8 mm at 0,6 mm.
    """
    return round(WALL_FLOOR_NOZZLE_MULTIPLE * float(nozzle_diameter_mm), MM_DECIMALS)


class SpecError(ValueError):
    """A spec that cannot be compiled, with every problem listed.

    Attributes:
        problems: One human-readable sentence per problem, each naming the field.
    """

    def __init__(self, problems: list[str]):
        self.problems = list(problems)
        super().__init__("invalid spec: " + "; ".join(self.problems))


def problem_path(problem: str) -> str:
    """The dotted path a problem sentence names, e.g. `spec.lid.clearance_mm`.

    Every message this module produces begins with the path it is about and nothing
    else: `_from_mapping` writes `f"{path} …"` for its own findings and prefixes
    `f"{path}.{p}"` onto each problem a `__post_init__` raised, and every
    `__post_init__` opens its sentence with the field name. So the first
    whitespace-delimited token *is* the path, and this function is the one place that
    says so — a form that puts a refusal on the field it names needs the path as data
    rather than as prose, and the alternative (splitting the joined sentence in the
    client) would put the convention in a language that cannot test it.

    A problem with no space — there is none today — yields the whole string, which is
    still the most specific thing that can honestly be claimed about it.
    """
    return problem.split(" ", 1)[0]


def problems_with_paths(problems: list[str]) -> list[dict[str, str]]:
    """`SpecError.problems` as `{"path", "message"}` pairs, order preserved.

    What `POST /jobs`'s 422 and `POST /organizer/resolve` both carry, so a refusal
    arrives at the field it is about instead of as one sentence nobody can route.
    """
    return [{"path": problem_path(p), "message": p} for p in problems]


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
    profile (roadmap M1) will join these; today they are spec-level.

    `fit_intent` is how much room the contents get, and it exists because
    `cavity_clearance_mm` was one number serving two objects — see
    `FIT_INTENT_CLEARANCE_MM`. It is a *word* rather than a number because it is the
    thing a person actually decides ("a box I close" / "a tray I lift cards out of");
    the millimetres are the KB's, and the KB is what will refine them.

    **`cavity_clearance_mm` is resolved on construction, never at compile time.**
    Passing None (or omitting it) means "take the intent's figure"; passing a number
    means that number, whatever the intent says. Either way the field holds a float
    once the object exists, so the canonical form always carries the clearance the
    geometry is built from and `from_dict(to_dict(s))` compiles to the same mesh as
    `s`. Deriving it later — or remembering *how* it was arrived at — would make two
    specs with identical canonical forms compile differently, which is the one
    property this schema exists to guarantee.

    **`wall_mm` is resolved the same way, one level up.** It defaults to None, and
    `OrganizerSpec.__post_init__` replaces None with `ARCHETYPE_WALL_MM[archetype]` —
    up there rather than here because only the spec knows which archetype is going to
    build the wall. A `Process` built on its own therefore holds None until a spec
    wraps it; inside a spec it is always a float, and the canonical form always states
    the wall the geometry has, for the clearance's reasons verbatim. Explicit null in
    a spec file means the same as omitted: take the archetype's default.

    A *stated* wall is checked against the printer's nozzle — `wall_floor_mm()`, three
    extrusion widths — by `archetypes.compile_spec`, not here: this dataclass has no
    printer and inventing one would either refuse a spec on a machine nobody named or
    pass a wall the machine cannot lay down.

    **The three edge treatments are process parameters, not closure ones.** A base
    chamfer fights warping and a corner round fights elephant-foot flare; both are facts
    about laying plastic on a bed, which is what every archetype here does, so they
    belong beside `floor_mm` rather than on `Lid`. They are on the spec rather than
    constants inside an archetype because F8 iterates a design by spec *diff* — "no
    chamfer" has to be a path somebody can set — and because the canonical form must
    state what the geometry has, which is `wall_mm`'s rule verbatim. **Zero is a valid
    value for all three and means the feature is absent**, so they are validated
    inclusive of their minimum, and a spec that zeroes all three compiles the
    square-cornered geometry this project built before they existed.
    """

    wall_mm: Optional[float] = None
    floor_mm: float = 2.0
    #: `snug` (a box you close) or `easy` (a tray you lift cards out of).
    fit_intent: str = "snug"
    #: None means "derive from `fit_intent`"; it is never None after construction.
    cavity_clearance_mm: Optional[float] = None
    stack_slack_mm: float = 1.0
    min_feature_mm: float = 1.0
    #: 45° chamfer cut into the bottom of every part, mm of height (and therefore mm of
    #: horizontal setback). **A design default, unsourced** — the audited insert
    #: document calls the feature mandatory and names no size (roadmap §0.5), and
    #: nothing in `docs/dimension-kb-research.md` sources one either. 0,6 mm is three
    #: 0,2 mm layers, which is the band an elephant foot forms in; `to_view` says so on
    #: the row rather than presenting it as measured. 0 is no chamfer.
    base_chamfer_mm: float = 0.6
    #: Radius of the four external **vertical** corners, mm. A design default on the
    #: same footing: the feature is mandatory in the audited document, the millimetre is
    #: this project's. 1,0 mm is under the deck box's own lip inset (1,4 mm at the lid
    #: defaults), so the closure stays square-cornered and only the outside is rounded.
    #: 0 is a square corner.
    corner_radius_mm: float = 1.0
    #: Radius of a cavity's internal vertical corners, mm. **0 by default**, because the
    #: audited document wants an internal round where a thumb has to scoop small parts
    #: out of a bin, and a deck box's cavity holds one sleeved deck that lifts out
    #: whole. The token tray is the archetype that will turn it up.
    cavity_corner_radius_mm: float = 0.0

    def __post_init__(self) -> None:
        problems: list[str] = []
        if self.wall_mm is not None:
            _set(self, "wall_mm", _mm(self.wall_mm, "wall_mm", problems))
        _set(self, "floor_mm", _mm(self.floor_mm, "floor_mm", problems))
        intent_ok = isinstance(self.fit_intent, str) and self.fit_intent in FIT_INTENTS
        if not intent_ok:
            problems.append(
                f"fit_intent must be one of {list(FIT_INTENTS)}, got {self.fit_intent!r}"
            )
        if self.cavity_clearance_mm is None:
            # A bad intent has already been collected above; fall back to the snug
            # figure so the frozen object holds a float until the error is raised.
            _set(self, "cavity_clearance_mm",
                 FIT_INTENT_CLEARANCE_MM[self.fit_intent] if intent_ok
                 else FIT_INTENT_CLEARANCE_MM["snug"])
        else:
            _set(self, "cavity_clearance_mm",
                 _mm(self.cavity_clearance_mm, "cavity_clearance_mm", problems, inclusive=True))
        _set(self, "stack_slack_mm",
             _mm(self.stack_slack_mm, "stack_slack_mm", problems, inclusive=True))
        _set(self, "min_feature_mm", _mm(self.min_feature_mm, "min_feature_mm", problems))
        for name in ("base_chamfer_mm", "corner_radius_mm", "cavity_corner_radius_mm"):
            _set(self, name, _mm(getattr(self, name), name, problems, inclusive=True))
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
        elif self.process.wall_mm is None:
            # The one place an archetype's wall default is applied. Done here because
            # `Process` does not know the archetype, and done *now* rather than at
            # compile time so the canonical form states the wall the geometry has —
            # `Process`'s docstring, and `cavity_clearance_mm`'s before it. An unknown
            # archetype leaves it None and is already refused above.
            default = ARCHETYPE_WALL_MM.get(self.archetype) if isinstance(self.archetype, str) else None
            if default is not None:
                _set(self, "process", dataclasses.replace(self.process, wall_mm=default))
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


# ── the wall floor ─────────────────────────────────────────────────────────────

def wall_floor_problems(
    spec: OrganizerSpec, nozzle_diameter_mm: float = DEFAULT_NOZZLE_DIAMETER_MM
) -> list[str]:
    """The refusal for a `process.wall_mm` the printer's nozzle cannot lay down, or [].

    A list rather than a raise so the caller can report it beside the archetype's own
    findings — a spec is refused whole, with every problem named at once.

    The message names both numbers on purpose. "1,2 mm minimum" alone is unactionable
    on a machine that is not the one the reader has; "3 × the 0,4 mm nozzle from the
    printer profile" says where the limit came from and what would move it.

    Args:
        spec: The spec, with `process.wall_mm` already resolved to a float.
        nozzle_diameter_mm: The printer profile's `machine_nozzle_size`.
    """
    wall = spec.process.wall_mm
    if wall is None:
        return []
    floor = wall_floor_mm(nozzle_diameter_mm)
    if wall + 1e-9 >= floor:
        return []
    return [
        f"process.wall_mm {wall:g} mm is below the {floor:g} mm wall floor "
        f"({WALL_FLOOR_NOZZLE_MULTIPLE:g} × the {float(nozzle_diameter_mm):g} mm nozzle "
        "this printer profile declares). Three extrusion widths is the least a wall "
        "that carries anything is built from — at a 0,4 mm nozzle that is 1,2 mm, the "
        "bottom of the audited insert band. Thicken the wall, or fit a finer nozzle"
    ]


def check_wall_floor(
    spec: OrganizerSpec, nozzle_diameter_mm: float = DEFAULT_NOZZLE_DIAMETER_MM
) -> None:
    """Raise `SpecError` if the spec's wall is below this nozzle's floor.

    The raising form of `wall_floor_problems`, for callers with nothing else to add.
    """
    _raise_if(wall_floor_problems(spec, nozzle_diameter_mm))


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
