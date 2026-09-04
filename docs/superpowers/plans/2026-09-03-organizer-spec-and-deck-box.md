# Organizer Spec Schema + Deck Box Archetype Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `pythonsrc/organizer/` package — a JSON-serialisable, diffable spec schema and a `manifold3d` deck-box archetype — and route a compiled spec through Phases 3–5 with `pipeline.py --spec`.

**Architecture:** Stdlib frozen dataclasses define the spec; `dimensions.py` resolves card/sleeve numbers; `archetypes/deck_box.py` compiles a spec into a two-part plate mesh via box CSG and can measure its designed features back off any mesh. `pipeline.py --spec` compiles inside real Phase 2 banners, writes the mesh into the real job namespace, records the compiler as the generation model, and continues through the existing `--no-scale` Phase 3 path. The printability gate learns how many parts were intended.

**Tech Stack:** Python 3.10, `dataclasses`, `manifold3d` 3.5.2, `trimesh` 4.11.2, `numpy`, `pytest`. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-03-organizer-spec-and-deck-box-design.md`

## Global Constraints

- Python 3.10 syntax only (`X | None` is fine with `from __future__ import annotations`; no `match`, no 3.11 stdlib).
- No new dependency anywhere. `pythonsrc/organizer/spec.py` and `dimensions.py` must import nothing outside the stdlib and each other.
- Never import `trimesh`/`manifold3d`/`numpy` from `spec.py` or `dimensions.py`.
- Millimetre floats round to 3 decimals (1 µm) on construction.
- Every designed feature must measure within **0.05 mm** on the compiled mesh and on Phase 3's output.
- A spec run writes to `data/outputs/{job_id}`, never `dev-`, and installs no reference blueprint.
- Phase banners are emitted only through `_phase_start` / `_phase_pass` / `_phase_fail`.
- Commit messages: descriptive sentence in the repo's style, ending with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`. Local commits only; do not push.
- Run tests from the repo root with the `ds-mvp` conda env's `python3` / `pytest`.

## File Structure

| File | Responsibility |
|---|---|
| `pythonsrc/organizer/__init__.py` | Exports the schema only (`OrganizerSpec`, parts, `SpecError`, `load_spec`, `spec_hash`, `spec_diff`). Never imports trimesh. |
| `pythonsrc/organizer/dimensions.py` | Seed card/sleeve constants with sources; `resolve_stack`. |
| `pythonsrc/organizer/spec.py` | Dataclasses, validation, `to_dict`/`from_dict`/JSON, canonical form, hash, diff, `load_spec`/`dump_spec`. |
| `pythonsrc/organizer/compiler.py` | Kernel-facing helpers and result types: `CompileResult`, `FitsResult`, `MeasureError`, `manifold_to_trimesh`, `plane_set`, `compare_features`, `export_stl`. |
| `pythonsrc/organizer/archetypes/__init__.py` | Registry + dispatch: `compile_spec`, `measure_spec_mesh`, `fits_for`, `view_for`, `example_spec`. |
| `pythonsrc/organizer/archetypes/deck_box.py` | v1 deck box: `validate`, `derive`, `build`, `compile`, `measure`, `fits_check`, `to_view`, `example`. |
| `pythonsrc/organizer/__main__.py` | CLI: `example`, `compile`, `measure`. |
| `pythonsrc/printability.py` | `expected_components` on `evaluate_printability` / `evaluate_mesh_file`. |
| `pythonsrc/pipeline.py` | `--spec` flag, `_apply_spec_mode`, spec clauses in the two fixture predicates, `_compile_spec_phase`, Phase 2 branch, gate argument. |
| `tests/test_organizer_dimensions.py`, `tests/test_organizer_spec.py`, `tests/test_deck_box.py`, `tests/test_organizer_cli.py`, `tests/test_pipeline_spec.py` | New suites. `tests/test_printability.py` gains three tests. |
| `CLAUDE.md`, `ARCHITECTURE.md`, `docs/ds-mvp-roadmap.md`, `README.md`, `web/src/pipeline.ts` | Docs. |

---

### Task 1: Seed dimensions

**Files:**
- Create: `pythonsrc/organizer/__init__.py` (empty for now, filled in Task 3)
- Create: `pythonsrc/organizer/dimensions.py`
- Test: `tests/test_organizer_dimensions.py`

**Interfaces:**
- Produces: `CARD_KINDS: dict[str, CardSize]`, `SLEEVINGS: tuple[str, ...]`, `SLEEVED_FOOTPRINT_MM`, `PITCH_MM_PER_CARD`, `ResolvedStack(count, card, sleeving, footprint_w_mm, footprint_h_mm, pitch_mm, stack_height_mm, basis)`, `resolve_stack(count: int, card: str, sleeving: str) -> ResolvedStack`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_organizer_dimensions.py
"""The seed numbers a spec resolves against, and where each one came from.

`pythonsrc/organizer/dimensions.py` is the M0 stand-in for the dimension KB (PRD F4,
seeded from `docs/dimension-kb-research.md`). These tests pin the design rules that
research settled — the 0,70 mm/card double-sleeved pitch above all, because the folk
0,72–0,80 figure is what every wrong deck box on the internet was designed to — and the
shape of `resolve_stack`, which the archetypes and the UI's fits line both read.
"""
import pytest

from pythonsrc.organizer.dimensions import (
    CARD_KINDS,
    PITCH_MM_PER_CARD,
    SLEEVED_FOOTPRINT_MM,
    SLEEVINGS,
    resolve_stack,
)


def test_the_double_sleeved_design_pitch_is_the_measured_one_not_the_folk_one():
    assert PITCH_MM_PER_CARD["double"] == pytest.approx(0.70)
    assert PITCH_MM_PER_CARD["single"] == pytest.approx(0.60)
    assert PITCH_MM_PER_CARD["none"] == pytest.approx(0.305)


def test_every_sleeving_has_a_pitch_and_a_footprint_entry():
    assert set(SLEEVINGS) == set(PITCH_MM_PER_CARD) == set(SLEEVED_FOOTPRINT_MM)


def test_only_the_standard_card_is_offered_in_v1():
    """The Japanese size is researched but has no sourced sleeve envelope; inventing
    one would be the fabricated number this module exists to refuse."""
    assert set(CARD_KINDS) == {"standard"}
    assert (CARD_KINDS["standard"].width_mm, CARD_KINDS["standard"].height_mm) == (63.5, 88.9)


def test_a_hundred_double_sleeved_cards_resolve_to_a_seventy_mm_stack():
    stack = resolve_stack(100, "standard", "double")
    assert stack.stack_height_mm == pytest.approx(70.0)
    assert (stack.footprint_w_mm, stack.footprint_h_mm) == (67.0, 92.0)
    assert stack.pitch_mm == 0.70


def test_an_unsleeved_stack_uses_the_bare_card_footprint():
    stack = resolve_stack(60, "standard", "none")
    assert (stack.footprint_w_mm, stack.footprint_h_mm) == (63.5, 88.9)
    assert stack.stack_height_mm == pytest.approx(18.3)


def test_the_basis_names_the_card_the_sleeving_and_the_pitch_rule():
    basis = resolve_stack(100, "standard", "double").basis
    assert "63.5" in basis and "88.9" in basis
    assert "double" in basis and "67" in basis and "92" in basis
    assert "0.70" in basis


def test_every_source_is_named():
    for size in CARD_KINDS.values():
        assert size.source
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_organizer_dimensions.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'pythonsrc.organizer'`

- [ ] **Step 3: Create the package and the module**

```bash
mkdir -p pythonsrc/organizer/archetypes && : > pythonsrc/organizer/__init__.py
```

```python
# pythonsrc/organizer/dimensions.py
"""Seed dimensions the organizer archetypes resolve a spec against.

This is the M0 stand-in for the dimension KB (PRD F4; roadmap M2; sourced research in
`docs/dimension-kb-research.md`). Every number below names its source in the comment
beside it, because the promise this product makes to a community that distrusts AI
output is that the millimetres are checkable against their own callipers. When the KB
lands (`pythonsrc/data/dimension_kb.v1.json`) `resolve_stack` reads it instead and
nothing downstream changes shape.

Deliberately dependency-free: the schema imports this, and the schema must be
importable where trimesh and manifold3d are not (the api-server image installs neither).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CardSize:
    width_mm: float
    height_mm: float
    thickness_mm: float
    source: str


#: Card kinds a spec may name. ``standard`` is the footprint the four target games share
#: (MTG 63,5 × 88,9 spec; Pokémon, Lorcana, Flesh and Blood and One Piece within
#: ±0,5 mm — Draftsim, folio.fyi, Card Fit Lab, CardShellz). The Japanese size
#: (59 × 86, Yu-Gi-Oh) is in the research but has **no sourced sleeve envelope**, and a
#: footprint invented to fill that gap is exactly the fabricated number this module
#: exists to refuse. It arrives with the KB.
CARD_KINDS: dict[str, CardSize] = {
    "standard": CardSize(
        width_mm=63.5,
        height_mm=88.9,
        thickness_mm=0.305,
        source="MTG spec (Draftsim); Pokémon / Lorcana / FaB / One Piece within ±0,5 mm",
    ),
}

#: How the cards are sleeved. Keys of the two tables below.
SLEEVINGS: tuple[str, ...] = ("none", "single", "double")

#: Outside W × H of one sleeved card, mm. ``None`` means the bare card footprint.
#: single — Dragon Shield / Ultra Pro Eclipse / Gamegenic outer sleeves: 66 × 91.
#: double — measured double-sleeved deck width 67 mm (MTG Salvation thread 572115);
#: the outer sleeve's 91–92 mm height governs.
SLEEVED_FOOTPRINT_MM: dict[str, tuple[float, float] | None] = {
    "none": None,
    "single": (66.0, 91.0),
    "double": (67.0, 92.0),
}

#: Design pitch per card in the stack direction, mm. These are *design rules*, not
#: nominal sums. The double-sleeved figure rests on two independent caliper
#: measurements of 100-card Commander stacks (KMC Hyper Matte + Perfect Fit = 66 mm;
#: Dragon Shield + Perfect Fit = 66,7 mm) plus an air margin. The folk 0,72–0,80 mm is
#: unsupported by any measured stack — those were box depths designers *chose*.
PITCH_MM_PER_CARD: dict[str, float] = {
    "none": 0.305,
    "single": 0.60,
    "double": 0.70,
}

#: One sentence per pitch saying where it came from, for the UI's fits line.
PITCH_BASIS: dict[str, str] = {
    "none": "0.305 mm/card (bare card thickness, spec)",
    "single": "0.60 mm/card design pitch (derived + air margin)",
    "double": "0.70 mm/card design pitch (two measured 100-card stacks at 66–67 mm)",
}


@dataclass(frozen=True)
class ResolvedStack:
    """A card stack with every number the geometry needs, and its provenance."""

    count: int
    card: str
    sleeving: str
    footprint_w_mm: float
    footprint_h_mm: float
    pitch_mm: float
    stack_height_mm: float
    basis: str


def resolve_stack(count: int, card: str, sleeving: str) -> ResolvedStack:
    """Resolve a card stack to its sleeved footprint and stack height.

    Args:
        count: Number of cards.
        card: A key of `CARD_KINDS`.
        sleeving: A member of `SLEEVINGS`.

    Returns:
        The resolved stack, with a `basis` sentence naming every source used.

    Raises:
        KeyError: For an unknown card kind or sleeving. The schema validates both
            before this is reached; the KeyError is for callers that bypass it.
    """
    size = CARD_KINDS[card]
    footprint = SLEEVED_FOOTPRINT_MM[sleeving]
    fw, fh = footprint if footprint is not None else (size.width_mm, size.height_mm)
    pitch = PITCH_MM_PER_CARD[sleeving]
    sleeve_note = (
        "unsleeved"
        if sleeving == "none"
        else f"{sleeving}-sleeved envelope {fw:g} × {fh:g} mm"
    )
    basis = (
        f"{card} card {size.width_mm:g} × {size.height_mm:g} mm, {sleeve_note}; "
        f"{PITCH_BASIS[sleeving]}"
    )
    return ResolvedStack(
        count=count,
        card=card,
        sleeving=sleeving,
        footprint_w_mm=fw,
        footprint_h_mm=fh,
        pitch_mm=pitch,
        stack_height_mm=round(count * pitch, 3),
        basis=basis,
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_organizer_dimensions.py -q`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add pythonsrc/organizer/__init__.py pythonsrc/organizer/dimensions.py tests/test_organizer_dimensions.py
git commit -m "Seed the organizer's card and sleeve dimensions with their sources

The M0 stand-in for the dimension KB: the standard card footprint, the single and
double sleeved envelopes, and the three design pitches, each carrying the source
the research settled on. Only the standard card is offered — the Japanese size has
no sourced sleeve envelope, and an invented one is the fabricated number this
module exists to refuse.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: Spec schema — dataclasses, validation, JSON round-trip

**Files:**
- Create: `pythonsrc/organizer/spec.py`
- Test: `tests/test_organizer_spec.py`

**Interfaces:**
- Consumes: `dimensions.CARD_KINDS`, `dimensions.SLEEVINGS`.
- Produces: `SCHEMA_VERSION = 1`, `ARCHETYPES = ("deck_box",)`, `LID_KINDS = ("lift_off",)`, `SpecError(ValueError)` with `.problems: list[str]`, frozen dataclasses `CardStack(count, card="standard", sleeving="double")`, `Compartment(contents)`, `Lid(kind="lift_off", magnets=False, height_mm=15.0, wall_mm=1.2, clearance_mm=0.2, top_mm=2.0)`, `Constraints(max_external_mm=None)`, `Process(wall_mm=2.8, floor_mm=2.0, cavity_clearance_mm=1.5, stack_slack_mm=1.0, min_feature_mm=1.0)`, `OrganizerSpec(archetype, compartments, lid=None, constraints=Constraints(), process=Process(), schema_version=1)` with `.to_dict()`, `.to_json(indent=2)`, `OrganizerSpec.from_dict(d)`, `OrganizerSpec.from_json(text)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_organizer_spec.py
"""The organizer spec: the object everything in the pivot is a function of.

The governing rule is *the LLM interprets words; it never produces geometry*, and this
schema is the boundary that rule describes. Left of it is probabilistic, right of it
deterministic. So the tests here are about the properties a boundary object needs:
it round-trips exactly, it refuses anything malformed with every problem named at once,
two specs can be compared line by line, and one spec has one hash.
"""
import json

import pytest

from pythonsrc.organizer.spec import (
    ARCHETYPES,
    CardStack,
    Compartment,
    Constraints,
    Lid,
    OrganizerSpec,
    Process,
    SpecError,
)


def deck(count=100, sleeving="double", **overrides):
    """A valid deck-box spec with sensible defaults, overridable per test."""
    base = dict(
        archetype="deck_box",
        compartments=(Compartment(CardStack(count=count, sleeving=sleeving)),),
        lid=Lid(),
    )
    base.update(overrides)
    return OrganizerSpec(**base)


# ── round trip ─────────────────────────────────────────────────────────────────

def test_dict_round_trip_is_exact():
    spec = deck()
    assert OrganizerSpec.from_dict(spec.to_dict()) == spec


def test_json_round_trip_is_exact():
    spec = deck(constraints=Constraints(max_external_mm=(80.0, 80.0, 100.0)))
    assert OrganizerSpec.from_json(spec.to_json()) == spec


def test_to_dict_is_pure_json_types():
    """Tuples become lists so the dict equals what `json.loads(to_json())` returns —
    one shape for the file and the in-memory view."""
    spec = deck(constraints=Constraints(max_external_mm=(80.0, 80.0, 100.0)))
    d = spec.to_dict()
    assert d == json.loads(spec.to_json())
    assert isinstance(d["compartments"], list)
    assert isinstance(d["constraints"]["max_external_mm"], list)


def test_millimetres_round_to_one_micron_on_construction():
    """Float noise must not reach the canonical form, so the schema rounds once, on
    the way in — three orders of magnitude below N1's ±0,05 mm."""
    p = Process(wall_mm=2.80000004, floor_mm=2.0004)
    assert p.wall_mm == 2.8
    assert p.floor_mm == 2.0


def test_the_deck_box_is_a_known_archetype():
    assert "deck_box" in ARCHETYPES


# ── validation: every rule, with the field named ───────────────────────────────

@pytest.mark.parametrize("bad, field", [
    (dict(count=0), "count"),
    (dict(count=-3), "count"),
    (dict(count=2.5), "count"),
    (dict(count=True), "count"),
    (dict(count=10, card="japanese"), "card"),
    (dict(count=10, sleeving="triple"), "sleeving"),
])
def test_card_stack_refuses_bad_fields_by_name(bad, field):
    with pytest.raises(SpecError) as exc:
        CardStack(**bad)
    assert field in str(exc.value)


@pytest.mark.parametrize("bad, field", [
    (dict(kind="hinged"), "kind"),
    (dict(height_mm=0), "height_mm"),
    (dict(wall_mm=-1), "wall_mm"),
    (dict(clearance_mm=-0.1), "clearance_mm"),
    (dict(top_mm=float("nan")), "top_mm"),
])
def test_lid_refuses_bad_fields_by_name(bad, field):
    with pytest.raises(SpecError) as exc:
        Lid(**bad)
    assert field in str(exc.value)


def test_lid_clearance_may_be_zero():
    """Zero clearance is a real (very tight) design; only negatives are nonsense."""
    assert Lid(clearance_mm=0).clearance_mm == 0.0


@pytest.mark.parametrize("bad, field", [
    (dict(wall_mm=0), "wall_mm"),
    (dict(floor_mm="thick"), "floor_mm"),
    (dict(cavity_clearance_mm=-1), "cavity_clearance_mm"),
    (dict(stack_slack_mm=-1), "stack_slack_mm"),
    (dict(min_feature_mm=0), "min_feature_mm"),
])
def test_process_refuses_bad_fields_by_name(bad, field):
    with pytest.raises(SpecError) as exc:
        Process(**bad)
    assert field in str(exc.value)


def test_constraints_need_three_positive_numbers_or_nothing():
    assert Constraints().max_external_mm is None
    assert Constraints(max_external_mm=[80, 80, 100]).max_external_mm == (80.0, 80.0, 100.0)
    with pytest.raises(SpecError):
        Constraints(max_external_mm=(80, 80))
    with pytest.raises(SpecError):
        Constraints(max_external_mm=(80, -1, 100))


def test_spec_refuses_an_unknown_archetype_and_an_empty_compartment_list():
    with pytest.raises(SpecError) as exc:
        OrganizerSpec(archetype="dragon", compartments=())
    message = str(exc.value)
    assert "archetype" in message and "compartments" in message


def test_spec_refuses_a_foreign_schema_version():
    with pytest.raises(SpecError) as exc:
        deck(schema_version=2)
    assert "schema_version" in str(exc.value)


def test_several_problems_are_reported_together():
    """A bad spec is refused once with the whole list, not one field per attempt."""
    with pytest.raises(SpecError) as exc:
        Process(wall_mm=0, floor_mm=-1, min_feature_mm=0)
    assert len(exc.value.problems) == 3


# ── from_dict: strict, path-annotated ──────────────────────────────────────────

def test_from_dict_refuses_unknown_keys():
    """A typo in a field name must not silently become the default."""
    d = deck().to_dict()
    d["process"]["wal_mm"] = 3.0
    with pytest.raises(SpecError) as exc:
        OrganizerSpec.from_dict(d)
    assert "wal_mm" in str(exc.value)


def test_from_dict_names_the_path_of_a_nested_problem():
    d = deck().to_dict()
    d["compartments"][0]["contents"]["count"] = 0
    with pytest.raises(SpecError) as exc:
        OrganizerSpec.from_dict(d)
    assert "compartments[0].contents.count" in str(exc.value)


def test_from_dict_collects_problems_across_branches():
    d = deck().to_dict()
    d["compartments"][0]["contents"]["count"] = 0
    d["lid"]["wall_mm"] = -1
    d["process"]["floor_mm"] = 0
    with pytest.raises(SpecError) as exc:
        OrganizerSpec.from_dict(d)
    assert len(exc.value.problems) == 3


def test_from_dict_reports_a_missing_required_field():
    d = deck().to_dict()
    del d["compartments"][0]["contents"]["count"]
    with pytest.raises(SpecError) as exc:
        OrganizerSpec.from_dict(d)
    assert "count" in str(exc.value)


def test_from_dict_accepts_a_missing_optional_lid_as_none():
    d = deck().to_dict()
    del d["lid"]
    assert OrganizerSpec.from_dict(d).lid is None


def test_from_json_refuses_text_that_is_not_json():
    with pytest.raises(SpecError) as exc:
        OrganizerSpec.from_json("{not json")
    assert "JSON" in str(exc.value)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_organizer_spec.py -q`
Expected: FAIL — `ImportError: cannot import name 'ARCHETYPES' from 'pythonsrc.organizer.spec'` (module missing)

- [ ] **Step 3: Write the schema module**

```python
# pythonsrc/organizer/spec.py
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
  compartment) live in the archetype, because they are facts about deck boxes.
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

#: Archetypes a spec may name. The registry in `archetypes/` must cover each.
ARCHETYPES: tuple[str, ...] = ("deck_box",)

#: Lid mechanisms the schema knows. Slide, hinged and magnetic lids are later
#: archetype variants (roadmap M1/M3) and are not accepted until they exist.
LID_KINDS: tuple[str, ...] = ("lift_off",)

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
class Constraints:
    """External limits the finished part must fit within: (W, D, H) in mm, or None."""

    max_external_mm: Optional[Tuple[float, float, float]] = None

    def __post_init__(self) -> None:
        if self.max_external_mm is None:
            return
        problems: list[str] = []
        values = self.max_external_mm
        if not isinstance(values, (list, tuple)) or len(values) != 3:
            raise SpecError([f"max_external_mm must be three numbers (W, D, H), got {values!r}"])
        rounded = tuple(
            _mm(v, f"max_external_mm[{i}]", problems) for i, v in enumerate(values)
        )
        _raise_if(problems)
        _set(self, "max_external_mm", rounded)


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
        """The spec as plain JSON types (tuples become lists)."""
        return json.loads(json.dumps(dataclasses.asdict(self)))

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
    (OrganizerSpec, "constraints"): Constraints,
    (OrganizerSpec, "process"): Process,
}
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_organizer_spec.py -q`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add pythonsrc/organizer/spec.py tests/test_organizer_spec.py
git commit -m "Add the organizer spec schema: frozen dataclasses that round-trip exactly

Frozen stdlib dataclasses for the archetype, compartments, lid, external
constraints and process parameters. Millimetre values round to 1 µm on
construction so from_dict(to_dict(s)) == s holds without float noise. Validation
collects every problem with its dotted path and raises one SpecError; from_dict
refuses unknown keys so a typo cannot become a default.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: Canonical form, hash, diff, file I/O, package exports

**Files:**
- Modify: `pythonsrc/organizer/spec.py` (append functions)
- Modify: `pythonsrc/organizer/__init__.py`
- Test: `tests/test_organizer_spec.py` (append)

**Interfaces:**
- Produces: `canonical_json(spec) -> str`, `spec_hash(spec) -> str` (64 hex), `spec_diff(a, b) -> dict[str, tuple[Any, Any]]`, `load_spec(path) -> OrganizerSpec`, `dump_spec(spec, path) -> Path`. `pythonsrc.organizer` re-exports `OrganizerSpec, CardStack, Compartment, Lid, Constraints, Process, SpecError, ARCHETYPES, SCHEMA_VERSION, canonical_json, spec_hash, spec_diff, load_spec, dump_spec`.

- [ ] **Step 1: Append the failing tests**

```python
# append to tests/test_organizer_spec.py
from pythonsrc.organizer.spec import canonical_json, dump_spec, load_spec, spec_diff, spec_hash


# ── canonical form and hash ────────────────────────────────────────────────────

def test_canonical_json_ignores_key_order():
    d = deck().to_dict()
    shuffled = {k: d[k] for k in reversed(list(d))}
    assert canonical_json(OrganizerSpec.from_dict(shuffled)) == canonical_json(OrganizerSpec.from_dict(d))


def test_canonical_json_is_compact_and_sorted():
    text = canonical_json(deck())
    assert " " not in text.replace("standard", "").replace("deck_box", "").replace("lift_off", "")
    keys = list(json.loads(text))
    assert keys == sorted(keys)


def test_the_hash_is_sha256_of_the_canonical_form():
    import hashlib
    spec = deck()
    assert spec_hash(spec) == hashlib.sha256(canonical_json(spec).encode("utf-8")).hexdigest()
    assert len(spec_hash(spec)) == 64


def test_any_field_change_changes_the_hash():
    base = spec_hash(deck())
    assert spec_hash(deck(count=99)) != base
    assert spec_hash(deck(lid=Lid(clearance_mm=0.25))) != base
    assert spec_hash(deck(process=Process(wall_mm=2.4))) != base


def test_the_hash_is_stable_across_processes():
    """A fixed vector: if this changes, every stored hash in the world changes with it,
    which is a schema-version bump, not a refactor."""
    spec = OrganizerSpec(
        archetype="deck_box",
        compartments=(Compartment(CardStack(count=100)),),
        lid=Lid(),
    )
    assert canonical_json(spec) == (
        '{"archetype":"deck_box","compartments":[{"contents":{"card":"standard",'
        '"count":100,"sleeving":"double"}}],"constraints":{"max_external_mm":null},'
        '"lid":{"clearance_mm":0.2,"height_mm":15.0,"kind":"lift_off","magnets":false,'
        '"top_mm":2.0,"wall_mm":1.2},"process":{"cavity_clearance_mm":1.5,"floor_mm":2.0,'
        '"min_feature_mm":1.0,"stack_slack_mm":1.0,"wall_mm":2.8},"schema_version":1}'
    )


# ── diff ───────────────────────────────────────────────────────────────────────

def test_diff_reports_a_changed_path_with_old_and_new():
    a, b = deck(), deck(lid=Lid(height_mm=20.0))
    assert spec_diff(a, b) == {"lid.height_mm": (15.0, 20.0)}


def test_diff_reports_added_and_removed_paths_with_none():
    a = deck()
    b = deck(constraints=Constraints(max_external_mm=(80.0, 80.0, 100.0)))
    d = spec_diff(a, b)
    assert d["constraints.max_external_mm[0]"] == (None, 80.0)
    assert spec_diff(b, a)["constraints.max_external_mm[0]"] == (80.0, None)


def test_diff_of_identical_specs_is_empty():
    assert spec_diff(deck(), deck()) == {}


def test_diff_indexes_into_lists():
    a, b = deck(count=100), deck(count=60)
    assert spec_diff(a, b) == {"compartments[0].contents.count": (100, 60)}


# ── files ──────────────────────────────────────────────────────────────────────

def test_dump_then_load_round_trips(tmp_path):
    spec = deck()
    path = dump_spec(spec, tmp_path / "deck.json")
    assert load_spec(path) == spec
    assert path.read_text().endswith("\n")


def test_load_refuses_a_bad_file_with_the_problems(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text('{"archetype": "deck_box", "compartments": []}')
    with pytest.raises(SpecError) as exc:
        load_spec(path)
    assert "compartments" in str(exc.value)


def test_the_package_exports_the_schema_without_the_kernel():
    """`pythonsrc.organizer` must stay importable where trimesh is not installed, so its
    `__init__` may import the schema and nothing else."""
    import ast, importlib.util
    import pythonsrc.organizer as pkg
    assert pkg.OrganizerSpec is OrganizerSpec and pkg.spec_hash is spec_hash
    tree = ast.parse(open(importlib.util.find_spec("pythonsrc.organizer").origin).read())
    imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    imported |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert imported == {"spec"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_organizer_spec.py -q`
Expected: FAIL — `ImportError: cannot import name 'canonical_json'`

- [ ] **Step 3: Append the functions and fill the package `__init__`**

```python
# append to pythonsrc/organizer/spec.py

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
```

```python
# pythonsrc/organizer/__init__.py
"""The parametric organizer engine — spec schema, seed dimensions, archetype compilers.

This package exports the **schema only**. It imports nothing outside the stdlib, so the
api-server image (which installs neither trimesh nor manifold3d) can import it the day
the request model grows a spec field. The compilers live behind explicit imports:

    from pythonsrc.organizer.archetypes import compile_spec, measure_spec_mesh
    from pythonsrc.organizer.compiler import export_stl

`pipeline.py --spec` is the entry that runs them.
"""
from .spec import (  # noqa: F401
    ARCHETYPES,
    SCHEMA_VERSION,
    CardStack,
    Compartment,
    Constraints,
    Lid,
    OrganizerSpec,
    Process,
    SpecError,
    canonical_json,
    dump_spec,
    load_spec,
    spec_diff,
    spec_hash,
)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_organizer_spec.py tests/test_organizer_dimensions.py -q`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add pythonsrc/organizer/spec.py pythonsrc/organizer/__init__.py tests/test_organizer_spec.py
git commit -m "Give the spec a canonical form, a hash, a diff and a file format

canonical_json sorts keys and strips whitespace so one spec is one string;
spec_hash is its sha256, the value the UI's OrganizerSpec.hash carries and a
future gate approval binds to; spec_diff compares two specs path by path, which
is iterate-by-prompt (F8) made mechanical. The package exports the schema only
and stays importable without the kernel.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: Compiler helpers — kernel bridge, plane sets, result types

**Files:**
- Create: `pythonsrc/organizer/compiler.py`
- Test: `tests/test_deck_box.py` (first section)

**Interfaces:**
- Produces: `MeasureError(RuntimeError)`; `FitsResult(fits: bool, line: str, basis: str, remedy: str | None = None)` with `.to_dict()`; `CompileResult(archetype, archetype_version, spec_hash, mesh: trimesh.Trimesh, parts: dict[str, trimesh.Trimesh], features: dict[str, float])` with `.features_document() -> dict`; `manifold_to_trimesh(man) -> trimesh.Trimesh`; `plane_set(coords, tol_mm=1e-3) -> list[float]`; `compare_features(designed, measured, tol_mm=0.05) -> dict[str, tuple[float, float, float]]`; `assert_features_within(designed, measured, tol_mm=0.05) -> None`; `export_stl(mesh, path) -> Path`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_deck_box.py
"""The deck box archetype and the helpers every archetype shares.

The thesis of the pivot in one testable artifact: a spec compiles to a mesh whose
every designed dimension can be read back off the geometry — on the compiled mesh
*and* on what Phase 3 hands the slicer. Nothing here is asserted from the spec's
numbers alone; each feature is measured from the mesh's own planes and compared.
"""
import hashlib

import numpy as np
import pytest
import trimesh
import manifold3d

from pythonsrc.organizer.compiler import (
    MeasureError,
    assert_features_within,
    compare_features,
    manifold_to_trimesh,
    plane_set,
)


# ── helpers ────────────────────────────────────────────────────────────────────

def test_manifold_to_trimesh_keeps_the_kernels_vertices_untouched():
    box = manifold3d.Manifold.cube([70.0, 95.0, 100.0], False)
    mesh = manifold_to_trimesh(box)
    assert mesh.is_watertight
    assert mesh.extents == pytest.approx([70.0, 95.0, 100.0], abs=1e-6)
    assert mesh.volume == pytest.approx(70.0 * 95.0 * 100.0, rel=1e-9)


def test_manifold_to_trimesh_refuses_an_empty_solid():
    empty = manifold3d.Manifold.cube([1.0, 1.0, 1.0], False) - manifold3d.Manifold.cube([2.0, 2.0, 2.0], True)
    with pytest.raises(MeasureError):
        manifold_to_trimesh(empty)


def test_plane_set_clusters_float_noise_into_one_plane():
    coords = np.array([0.0, 70.89999, 70.90001, 70.9, 156.6, 156.6000061])
    assert plane_set(coords) == pytest.approx([0.0, 70.9, 156.6], abs=1e-4)


def test_plane_set_keeps_planes_a_micron_apart_distinct():
    assert len(plane_set(np.array([0.0, 0.002, 0.004]))) == 3


def test_compare_features_reports_designed_measured_and_error():
    out = compare_features({"a_mm": 10.0, "b_mm": 5.0}, {"a_mm": 10.01, "b_mm": 5.0})
    assert out["a_mm"] == pytest.approx((10.0, 10.01, 0.01))
    assert out["b_mm"] == (5.0, 5.0, 0.0)


def test_assert_features_within_names_every_feature_out_of_tolerance():
    with pytest.raises(MeasureError) as exc:
        assert_features_within({"a_mm": 10.0, "b_mm": 5.0}, {"a_mm": 10.2, "b_mm": 4.7}, tol_mm=0.05)
    assert "a_mm" in str(exc.value) and "b_mm" in str(exc.value)


def test_assert_features_within_refuses_a_missing_measurement():
    with pytest.raises(MeasureError):
        assert_features_within({"a_mm": 10.0}, {}, tol_mm=0.05)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_deck_box.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'pythonsrc.organizer.compiler'`

- [ ] **Step 3: Write the module**

```python
# pythonsrc/organizer/compiler.py
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

import json
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
        d = {"fits": self.fits, "line": self.line, "basis": self.basis}
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_deck_box.py -q`
Expected: 7 passed. If `to_mesh64` returns a type whose `vert_properties` is not indexable as `[:, :3]`, drop back to `to_mesh()` — the STL is float32 anyway.

- [ ] **Step 5: Commit**

```bash
git add pythonsrc/organizer/compiler.py tests/test_deck_box.py
git commit -m "Add the compiler helpers the archetypes share: kernel bridge, plane sets, results

manifold_to_trimesh exports the kernel's vertices untouched (process=False) so a
plane designed at 2.8 mm is at 2.8 mm in the file; plane_set reads the distinct
axis-aligned planes off a mesh, clustering float32 export noise; compare_features
and assert_features_within put designed and measured side by side — the shape of
text-to-cad's measure/align checkers, run on the geometry rather than the spec.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: Deck box archetype — validate, derive, build, compile; registry

**Files:**
- Create: `pythonsrc/organizer/archetypes/deck_box.py`
- Create: `pythonsrc/organizer/archetypes/__init__.py`
- Test: `tests/test_deck_box.py` (append)

**Interfaces:**
- Consumes: `OrganizerSpec`, `SpecError`, `spec_hash` (Task 2/3); `resolve_stack` (Task 1); `CompileResult`, `manifold_to_trimesh`, `MeasureError` (Task 4).
- Produces in `deck_box.py`: `ARCHETYPE = "deck_box"`, `ARCHETYPE_VERSION = "1"`, `PLATE_GAP_MM = 10.0`, `DeckBoxDimensions` (frozen dataclass: `stack, cavity_w, cavity_d, cavity_h, external_w, external_d, body_h, lip_inset, lip_wall, lip_outer_w, lip_outer_d, lid_cavity_w, lid_cavity_d, lid_h, external_h`) with `.features(spec) -> dict[str, float]`; `validate(spec) -> None`; `derive(spec) -> DeckBoxDimensions`; `build(spec) -> tuple[dict[str, Manifold], DeckBoxDimensions]`; `compile(spec) -> CompileResult`; `example() -> OrganizerSpec`.
- Produces in `archetypes/__init__.py`: `REGISTRY: dict[str, module]`, `get_archetype(name)`, `compile_spec(spec) -> CompileResult`, `example_spec(name) -> OrganizerSpec`. (`measure_spec_mesh`, `fits_for`, `view_for` are added in Tasks 6–7.)

- [ ] **Step 1: Append the failing tests**

```python
# append to tests/test_deck_box.py
from pythonsrc.organizer.spec import CardStack, Compartment, Constraints, Lid, OrganizerSpec, Process, SpecError
from pythonsrc.organizer.archetypes import compile_spec, example_spec, get_archetype
from pythonsrc.organizer.archetypes import deck_box


def deck(count=100, sleeving="double", **overrides):
    base = dict(
        archetype="deck_box",
        compartments=(Compartment(CardStack(count=count, sleeving=sleeving)),),
        lid=Lid(),
    )
    base.update(overrides)
    return OrganizerSpec(**base)


def bodies_on_plate(mesh):
    parts = mesh.split(only_watertight=False)
    return parts, all(abs(p.bounds[0][2]) < 1e-6 for p in parts)


# ── derive: the arithmetic the geometry is built from ──────────────────────────

def test_a_hundred_double_sleeved_cards_derive_the_expected_box():
    d = deck_box.derive(deck())
    assert d.cavity_w == pytest.approx(67.0 + 1.5)
    assert d.cavity_d == pytest.approx(100 * 0.70 + 1.0)
    assert d.cavity_h == pytest.approx(92.0 + 1.5)
    assert d.external_w == pytest.approx(68.5 + 2 * 2.8)
    assert d.external_d == pytest.approx(71.0 + 2 * 2.8)
    assert d.body_h == pytest.approx(93.5 + 2.0)
    assert d.lip_inset == pytest.approx(1.2 + 0.2)
    assert d.lip_wall == pytest.approx(2.8 - 1.4)
    assert d.lid_cavity_w == pytest.approx(d.lip_outer_w + 2 * 0.2)
    assert d.external_h == pytest.approx(d.body_h + 2.0)


# ── archetype-level refusals, with the reason ──────────────────────────────────

def test_a_second_compartment_is_refused_by_name():
    spec = deck(compartments=(Compartment(CardStack(60)), Compartment(CardStack(40))))
    with pytest.raises(SpecError) as exc:
        compile_spec(spec)
    assert "one compartment" in str(exc.value)


def test_magnets_are_refused_not_ignored():
    with pytest.raises(SpecError) as exc:
        compile_spec(deck(lid=Lid(magnets=True)))
    assert "magnet" in str(exc.value)


def test_a_missing_lid_is_refused():
    with pytest.raises(SpecError) as exc:
        compile_spec(deck(lid=None))
    assert "lid" in str(exc.value)


def test_a_lip_thinner_than_the_minimum_feature_is_refused_with_the_remedy():
    """wall 2.4 − lid wall 1.2 − clearance 0.2 = 1.0 lip; a 1.2 mm minimum refuses it."""
    spec = deck(process=Process(wall_mm=2.4, min_feature_mm=1.2))
    with pytest.raises(SpecError) as exc:
        compile_spec(spec)
    message = str(exc.value)
    assert "lip" in message and "1.000" in message and "wall" in message


def test_a_lid_taller_than_the_cavity_is_refused():
    with pytest.raises(SpecError) as exc:
        compile_spec(deck(lid=Lid(height_mm=200.0)))
    assert "height_mm" in str(exc.value)


def test_an_unknown_archetype_name_is_refused_by_the_registry():
    with pytest.raises(SpecError):
        get_archetype("dragon")


# ── compile: the plate ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("count", [40, 60, 100])
@pytest.mark.parametrize("sleeving", ["none", "single", "double"])
def test_the_plate_is_two_watertight_bodies_both_on_the_bed(count, sleeving):
    result = compile_spec(deck(count=count, sleeving=sleeving))
    assert result.mesh.is_watertight
    parts, grounded = bodies_on_plate(result.mesh)
    assert len(parts) == 2 and grounded
    assert set(result.parts) == {"body", "lid"}
    assert result.parts["body"].is_watertight and result.parts["lid"].is_watertight


def test_the_body_and_lid_do_not_overlap_on_the_plate():
    result = compile_spec(deck())
    body, lid = result.parts["body"], result.parts["lid"]
    assert lid.bounds[0][0] >= body.bounds[1][0] + deck_box.PLATE_GAP_MM - 1e-6


def test_the_result_carries_the_designed_features_and_the_spec_hash():
    from pythonsrc.organizer.spec import spec_hash
    spec = deck()
    result = compile_spec(spec)
    assert result.archetype == "deck_box" and result.archetype_version == "1"
    assert result.spec_hash == spec_hash(spec)
    for key in ("cavity_width_mm", "cavity_depth_mm", "cavity_height_mm",
                "external_width_mm", "external_depth_mm", "external_height_mm",
                "lip_wall_mm", "lid_clearance_mm", "stack_height_mm"):
        assert key in result.features
    doc = result.features_document()
    assert doc["parts"] == ["body", "lid"] and doc["spec_sha256"] == result.spec_hash


def test_the_same_spec_exports_the_same_bytes(tmp_path):
    """Frozen source, deterministic kernel: the STL is reproducible byte for byte."""
    from pythonsrc.organizer.compiler import export_stl
    a = export_stl(compile_spec(deck()).mesh, tmp_path / "a.stl").read_bytes()
    b = export_stl(compile_spec(deck()).mesh, tmp_path / "b.stl").read_bytes()
    assert hashlib.sha256(a).hexdigest() == hashlib.sha256(b).hexdigest()


def test_the_example_spec_compiles():
    spec = example_spec("deck_box")
    assert spec.compartments[0].contents.count == 100
    assert compile_spec(spec).mesh.is_watertight
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_deck_box.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'pythonsrc.organizer.archetypes'`

- [ ] **Step 3: Write the archetype (compile half) and the registry**

```python
# pythonsrc/organizer/archetypes/deck_box.py
"""Deck box, version 1: a body with a lip and a lift-off lid, from box CSG.

The first archetype, and the product thesis in one testable artifact: a spec compiles
to a mesh whose every dimension is *designed*, and every one of those dimensions can
be read back off the geometry by `measure()`. Nothing after this module scales the
part — it enters Phase 3 with `--no-scale` because these millimetres are the deliverable.

Two parts on one plate, both flat on Z = 0, no overhangs anywhere:

- **Body** — an open-top box with a floor. Its top `lid.height_mm` is a **lip**: the
  outer wall steps in by `lid.wall_mm + lid.clearance_mm` per side, so the lid sits
  flush with the body below it.
- **Lid** — an inverted tray printed open side up, `PLATE_GAP_MM` to +X of the body.

Cards stand upright: width along X, stack along Y, height along Z. With `n, pitch,
(fw, fh)` from `resolve_stack`, `w, f, cc, ss` from `process`, `lh, lw, lc, lt` from `lid`:

    cavity_w   = fw + cc            cavity_d   = n·pitch + ss        cavity_h = fh + cc
    external_w = cavity_w + 2w      external_d = cavity_d + 2w       body_h   = cavity_h + f
    lip_inset  = lw + lc            lip_wall   = w − lip_inset
    lip_outer  = external − 2·lip_inset          lid_cavity = external − 2·lw = lip_outer + 2·lc
    lid_h      = lh + lt            external_h (assembled) = body_h + lt

The one tolerance-critical surface is the lid cavity over the lip: `lid.clearance_mm`
per side. That is the number a test-fit coupon (F12) will print first.

Rules that belong to this *shape* rather than to specs in general — exactly one
compartment, a lift-off lid without magnets, a lip no thinner than
`process.min_feature_mm`, a lid shorter than the cavity — are checked here and refused
with the remedy named. Ignoring an unsupported field would print a different box than
the one asked for, silently.

Authored in Claude Code against `manifold3d` directly (roadmap §0.2's "authored with
text-to-cad, source frozen"): text-to-cad drives build123d on OCCT, which the kernel
decision defers; what is borrowed is its measure/align discipline.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import manifold3d

from ..compiler import CompileResult, FitsResult, MeasureError, manifold_to_trimesh, plane_set
from ..dimensions import ResolvedStack, resolve_stack
from ..spec import CardStack, Compartment, Lid, OrganizerSpec, SpecError, spec_hash

ARCHETYPE = "deck_box"
#: Bumped when the geometry a given spec produces changes. Recorded on every job.
ARCHETYPE_VERSION = "1"
#: Clear space between the body and the lid on the plate, mm.
PLATE_GAP_MM = 10.0


@dataclass(frozen=True)
class DeckBoxDimensions:
    """Every derived dimension, in mm, from one spec. Pure arithmetic — no kernel."""

    stack: ResolvedStack
    cavity_w: float
    cavity_d: float
    cavity_h: float
    external_w: float
    external_d: float
    body_h: float
    lip_inset: float
    lip_wall: float
    lip_outer_w: float
    lip_outer_d: float
    lid_cavity_w: float
    lid_cavity_d: float
    lid_h: float
    external_h: float

    def features(self, spec: OrganizerSpec) -> dict[str, float]:
        """The designed features by name. `measure()` reads the same names back."""
        lid = spec.lid
        p = spec.process
        assert lid is not None  # validated before derive() is reached
        raw = {
            "cavity_width_mm": self.cavity_w,
            "cavity_depth_mm": self.cavity_d,
            "cavity_height_mm": self.cavity_h,
            "external_width_mm": self.external_w,
            "external_depth_mm": self.external_d,
            "external_height_mm": self.external_h,
            "body_height_mm": self.body_h,
            "floor_mm": p.floor_mm,
            "wall_mm": p.wall_mm,
            "lip_height_mm": lid.height_mm,
            "lip_wall_mm": self.lip_wall,
            "lip_outer_width_mm": self.lip_outer_w,
            "lip_outer_depth_mm": self.lip_outer_d,
            "lid_cavity_width_mm": self.lid_cavity_w,
            "lid_cavity_depth_mm": self.lid_cavity_d,
            "lid_cavity_height_mm": lid.height_mm,
            "lid_height_mm": self.lid_h,
            "lid_wall_mm": lid.wall_mm,
            "lid_clearance_mm": lid.clearance_mm,
            "stack_height_mm": self.stack.stack_height_mm,
        }
        return {k: round(float(v), 3) for k, v in raw.items()}


def _structural_problems(spec: OrganizerSpec) -> list[str]:
    problems: list[str] = []
    if spec.archetype != ARCHETYPE:
        problems.append(f"archetype {spec.archetype!r} is not {ARCHETYPE!r}")
    if len(spec.compartments) != 1:
        problems.append(
            f"deck_box v{ARCHETYPE_VERSION} holds exactly one compartment (the deck); "
            f"got {len(spec.compartments)}"
        )
    if spec.lid is None:
        problems.append(f"deck_box v{ARCHETYPE_VERSION} needs a lid (lid is null)")
    else:
        if spec.lid.kind != "lift_off":
            problems.append(f"deck_box v{ARCHETYPE_VERSION} supports lid.kind 'lift_off' only, got {spec.lid.kind!r}")
        if spec.lid.magnets:
            problems.append(
                f"deck_box v{ARCHETYPE_VERSION} has no magnet pockets; a magnetic lid is a "
                "later archetype variant — set lid.magnets to false"
            )
    return problems


def derive(spec: OrganizerSpec) -> DeckBoxDimensions:
    """Every dimension the geometry is built from. Assumes `_structural_problems` is empty."""
    stack_spec: CardStack = spec.compartments[0].contents
    stack = resolve_stack(stack_spec.count, stack_spec.card, stack_spec.sleeving)
    p = spec.process
    lid = spec.lid
    assert lid is not None
    cavity_w = stack.footprint_w_mm + p.cavity_clearance_mm
    cavity_d = stack.stack_height_mm + p.stack_slack_mm
    cavity_h = stack.footprint_h_mm + p.cavity_clearance_mm
    external_w = cavity_w + 2 * p.wall_mm
    external_d = cavity_d + 2 * p.wall_mm
    body_h = cavity_h + p.floor_mm
    lip_inset = lid.wall_mm + lid.clearance_mm
    lip_wall = p.wall_mm - lip_inset
    lip_outer_w = external_w - 2 * lip_inset
    lip_outer_d = external_d - 2 * lip_inset
    lid_cavity_w = external_w - 2 * lid.wall_mm
    lid_cavity_d = external_d - 2 * lid.wall_mm
    lid_h = lid.height_mm + lid.top_mm
    external_h = body_h + lid.top_mm
    r = lambda x: round(float(x), 3)  # noqa: E731 — every value to 1 µm, like the schema
    return DeckBoxDimensions(
        stack=stack,
        cavity_w=r(cavity_w), cavity_d=r(cavity_d), cavity_h=r(cavity_h),
        external_w=r(external_w), external_d=r(external_d), body_h=r(body_h),
        lip_inset=r(lip_inset), lip_wall=r(lip_wall),
        lip_outer_w=r(lip_outer_w), lip_outer_d=r(lip_outer_d),
        lid_cavity_w=r(lid_cavity_w), lid_cavity_d=r(lid_cavity_d),
        lid_h=r(lid_h), external_h=r(external_h),
    )


def validate(spec: OrganizerSpec) -> None:
    """Refuse a spec this archetype cannot honour, naming every problem and its remedy.

    Raises:
        SpecError: With every archetype-level problem.
    """
    problems = _structural_problems(spec)
    if problems:
        raise SpecError(problems)
    d = derive(spec)
    lid = spec.lid
    assert lid is not None
    if d.lip_wall < spec.process.min_feature_mm:
        problems.append(
            f"the lip wall would be {d.lip_wall:.3f} mm (process.wall_mm {spec.process.wall_mm:g} − "
            f"lid.wall_mm {lid.wall_mm:g} − lid.clearance_mm {lid.clearance_mm:g}), below "
            f"process.min_feature_mm {spec.process.min_feature_mm:g}; thicken the body wall, "
            "thin the lid wall, or reduce the clearance"
        )
    if lid.height_mm >= d.cavity_h:
        problems.append(
            f"lid.height_mm {lid.height_mm:g} must be less than the cavity height "
            f"{d.cavity_h:.3f} mm, or the lip would cut into the floor"
        )
    if problems:
        raise SpecError(problems)


def build(spec: OrganizerSpec) -> tuple[dict[str, "manifold3d.Manifold"], DeckBoxDimensions]:
    """Validate, derive, and build the two solids in plate position."""
    validate(spec)
    d = derive(spec)
    p = spec.process
    lid = spec.lid
    assert lid is not None

    def cube(x: float, y: float, z: float) -> "manifold3d.Manifold":
        return manifold3d.Manifold.cube([x, y, z], False)

    W, D = d.external_w, d.external_d
    # Body: the outer block minus the cavity (open through the top: +1 mm overshoot).
    body = cube(W, D, d.body_h) - cube(d.cavity_w, d.cavity_d, d.cavity_h + 1.0).translate(
        [p.wall_mm, p.wall_mm, p.floor_mm]
    )
    # Lip: remove the outer band of the top `lid.height_mm`. The band is a slab over
    # the lip height (overshooting the top) minus the lip's own outline (overshooting
    # both ways), so exactly the perimeter strip of width `lip_inset` is cut.
    band = cube(W, D, lid.height_mm + 1.0).translate([0.0, 0.0, d.body_h - lid.height_mm]) - cube(
        d.lip_outer_w, d.lip_outer_d, lid.height_mm + 3.0
    ).translate([d.lip_inset, d.lip_inset, d.body_h - lid.height_mm - 1.0])
    body = body - band
    # Lid: an inverted tray. Its cavity is the lip outline plus the clearance per side,
    # `lid.height_mm` deep (open through the top when printed open side up).
    lid_part = cube(W, D, d.lid_h) - cube(d.lid_cavity_w, d.lid_cavity_d, lid.height_mm + 1.0).translate(
        [lid.wall_mm, lid.wall_mm, lid.top_mm]
    )
    lid_part = lid_part.translate([W + PLATE_GAP_MM, 0.0, 0.0])
    return {"body": body, "lid": lid_part}, d


def compile(spec: OrganizerSpec) -> CompileResult:  # noqa: A001 — the registry's verb
    """Spec → plate mesh, parts, designed features."""
    solids, d = build(spec)
    parts = {name: manifold_to_trimesh(solid) for name, solid in solids.items()}
    plate = manifold_to_trimesh(solids["body"] + solids["lid"])
    return CompileResult(
        archetype=ARCHETYPE,
        archetype_version=ARCHETYPE_VERSION,
        spec_hash=spec_hash(spec),
        mesh=plate,
        parts=parts,
        features=d.features(spec),
    )


def example() -> OrganizerSpec:
    """A 100-card double-sleeved Commander deck box with the default process."""
    return OrganizerSpec(
        archetype=ARCHETYPE,
        compartments=(Compartment(CardStack(count=100, card="standard", sleeving="double")),),
        lid=Lid(),
    )
```

```python
# pythonsrc/organizer/archetypes/__init__.py
"""The archetype registry and the dispatch functions the pipeline and CLI call.

One module per archetype, each exposing the same verbs (`validate`, `derive`, `build`,
`compile`, `measure`, `fits_check`, `to_view`, `example`) plus `ARCHETYPE` and
`ARCHETYPE_VERSION`. The registry maps a spec's `archetype` string to its module;
adding an archetype is adding a module and a line here, and `spec.ARCHETYPES` must
name it too or the schema refuses it before this is reached.
"""
from __future__ import annotations

from types import ModuleType

from ..compiler import CompileResult
from ..spec import ARCHETYPES, OrganizerSpec, SpecError
from . import deck_box

REGISTRY: dict[str, ModuleType] = {
    deck_box.ARCHETYPE: deck_box,
}

# The schema's list and the registry must agree, or a spec the schema accepts has
# nothing to compile it. Checked at import so the disagreement fails loudly.
_unregistered = sorted(set(ARCHETYPES) - set(REGISTRY))
if _unregistered:  # pragma: no cover
    raise ImportError(f"spec.ARCHETYPES names archetypes with no compiler: {_unregistered}")


def get_archetype(name: str) -> ModuleType:
    """The module for an archetype name.

    Raises:
        SpecError: For a name the registry does not know.
    """
    try:
        return REGISTRY[name]
    except KeyError:
        raise SpecError([f"unknown archetype {name!r}; known: {sorted(REGISTRY)}"]) from None


def compile_spec(spec: OrganizerSpec) -> CompileResult:
    """Compile a spec with its archetype. Raises `SpecError` if the archetype refuses it."""
    return get_archetype(spec.archetype).compile(spec)


def example_spec(name: str) -> OrganizerSpec:
    return get_archetype(name).example()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_deck_box.py -q`
Expected: all passed (the parametrised plate test runs 9 times)

- [ ] **Step 5: Commit**

```bash
git add pythonsrc/organizer/archetypes/ tests/test_deck_box.py
git commit -m "Add the first archetype: a deck box with a lip and a lift-off lid, from box CSG

Two parts on one plate, both flat on the bed, built with manifold3d.Manifold.cube and
translations only. Every dimension is derived from the resolved card stack and the
spec's process and lid parameters, rounded to 1 µm, and returned as named features.
Rules that belong to this shape — one compartment, a lift-off lid without magnets, a
lip no thinner than the minimum feature — are refused with the remedy named rather
than ignored, because ignoring a field prints a different box than the one asked for.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: Measuring the deck box back off the mesh, before and after Phase 3

**Files:**
- Modify: `pythonsrc/organizer/archetypes/deck_box.py` (append `measure`)
- Modify: `pythonsrc/organizer/archetypes/__init__.py` (add `measure_spec_mesh`)
- Test: `tests/test_deck_box.py` (append)

**Interfaces:**
- Produces: `deck_box.MEASURED_FEATURES: tuple[str, ...]`, `deck_box.measure(mesh: trimesh.Trimesh) -> dict[str, float]`; `archetypes.measure_spec_mesh(spec, mesh) -> dict[str, float]`.

- [ ] **Step 1: Append the failing tests**

```python
# append to tests/test_deck_box.py
from pythonsrc.engineer import Engineer
from pythonsrc.organizer.archetypes import measure_spec_mesh
from pythonsrc.organizer.compiler import export_stl
from pythonsrc.printability import ProcessProfile, evaluate_printability

TOL_MM = 0.05  # PRD N1: internal dimensions exact to spec within ≤ ±0,05 mm


@pytest.mark.parametrize("count", [40, 60, 100])
@pytest.mark.parametrize("sleeving", ["none", "single", "double"])
def test_every_designed_feature_is_on_the_compiled_mesh(count, sleeving):
    spec = deck(count=count, sleeving=sleeving)
    result = compile_spec(spec)
    measured = measure_spec_mesh(spec, result.mesh)
    assert_features_within(result.features, measured, TOL_MM, required=set(deck_box.MEASURED_FEATURES))


def test_the_lid_clears_the_lip_by_exactly_the_clearance():
    spec = deck(lid=Lid(clearance_mm=0.25))
    measured = measure_spec_mesh(spec, compile_spec(spec).mesh)
    assert measured["lid_clearance_mm"] == pytest.approx(0.25, abs=1e-4)


def test_measure_refuses_a_mesh_that_is_not_a_deck_box():
    with pytest.raises(MeasureError):
        deck_box.measure(trimesh.creation.box(extents=[10, 10, 10]))


def test_phase_3_hands_the_slicer_the_dimensions_that_were_designed(tmp_path):
    """The seam the roadmap names: --skip-visualizer --skip-sculptor --mesh --no-scale.
    Repair runs; scaling does not; every feature survives within tolerance."""
    spec = deck()
    result = compile_spec(spec)
    raw = export_stl(result.mesh, tmp_path / "compiled_mesh.stl")
    eng = Engineer()
    out = eng.process(input_path=raw, output_path=tmp_path / "engineered.obj", target_mm=None)
    engineered = trimesh.load(str(out), force="mesh")
    measured = measure_spec_mesh(spec, engineered)
    assert_features_within(result.features, measured, TOL_MM, required=set(deck_box.MEASURED_FEATURES))
    assert eng.last_report["scale_applied"] is False
    assert eng.last_report["scale_axis"] == "preserved"
    assert eng.last_report.get("faces_dropped", 0) == 0


def test_the_gate_does_not_fail_the_deck_box(tmp_path):
    spec = deck()
    result = compile_spec(spec)
    raw = export_stl(result.mesh, tmp_path / "compiled_mesh.stl")
    out = Engineer().process(input_path=raw, output_path=tmp_path / "engineered.obj", target_mm=None)
    report = evaluate_printability(
        trimesh.load(str(out), force="mesh"),
        ProcessProfile(build_volume_mm=[220.0, 220.0, 250.0]),
        expected_components=len(result.parts),
    )
    by_name = {c.check: c for c in report.checks}
    assert not any(c.status == "fail" for c in report.checks), [(c.check, c.detail) for c in report.checks if c.status == "fail"]
    assert by_name["floating_components"].status == "pass"
    assert by_name["watertight"].status == "pass"
    assert report.verdict != "unprintable"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_deck_box.py -q -k "measure or phase_3 or gate or clears"`
Expected: FAIL — `ImportError: cannot import name 'measure_spec_mesh'`. (The gate test also needs Task 9; it fails with `TypeError: unexpected keyword argument 'expected_components'` until then — leave it red and finish it in Task 9.)

- [ ] **Step 3: Append `measure` and the dispatch function**

```python
# append to pythonsrc/organizer/archetypes/deck_box.py

#: Features `measure()` reads off geometry. `stack_height_mm` is designed only — a card
#: stack is not on the mesh — so it is the one designed feature deliberately absent here.
MEASURED_FEATURES: tuple[str, ...] = (
    "cavity_width_mm", "cavity_depth_mm", "cavity_height_mm",
    "external_width_mm", "external_depth_mm", "external_height_mm",
    "body_height_mm", "floor_mm", "wall_mm",
    "lip_height_mm", "lip_wall_mm", "lip_outer_width_mm", "lip_outer_depth_mm",
    "lid_cavity_width_mm", "lid_cavity_depth_mm", "lid_cavity_height_mm",
    "lid_height_mm", "lid_wall_mm", "lid_clearance_mm",
)


def _planes(part: Any, axis: int, expected: int, what: str) -> list[float]:
    planes = plane_set(part.vertices[:, axis])
    if len(planes) != expected:
        raise MeasureError(
            f"the {what} has {len(planes)} distinct {'XYZ'[axis]} planes where a deck box "
            f"v{ARCHETYPE_VERSION} has {expected}: {[round(v, 3) for v in planes]}"
        )
    return planes


def measure(mesh: Any) -> dict[str, float]:
    """Read the designed features back off a deck-box mesh — compiled or post-Phase-3.

    Splits the plate into its two bodies (the body is the larger by volume), takes the
    distinct axis-aligned planes of each, and reads every feature as a difference of
    planes. A plane count that does not match the design is a `MeasureError`: geometry
    that does not have the planes the design says it has *is* the finding.

    Raises:
        MeasureError: If the mesh is not two bodies with the deck box's plane structure.
    """
    parts = mesh.split(only_watertight=False)
    if len(parts) != 2:
        raise MeasureError(f"expected 2 bodies (body and lid), found {len(parts)}")
    body, lid = sorted(parts, key=lambda p: p.volume, reverse=True)
    # Body planes: X and Y each {0, lip_inset, wall, wall + cavity, W − lip_inset, W};
    # Z {0, floor, body_h − lip_height, body_h}.
    bx = _planes(body, 0, 6, "body")
    by = _planes(body, 1, 6, "body")
    bz = _planes(body, 2, 4, "body")
    # Lid planes: X and Y each {0, lid_wall, W − lid_wall, W}; Z {0, top, top + height}.
    lx = _planes(lid, 0, 4, "lid")
    ly = _planes(lid, 1, 4, "lid")
    lz = _planes(lid, 2, 3, "lid")
    lid_cavity_w = lx[2] - lx[1]
    lip_outer_w = bx[4] - bx[1]
    measured = {
        "external_width_mm": bx[5] - bx[0],
        "external_depth_mm": by[5] - by[0],
        "body_height_mm": bz[3] - bz[0],
        "floor_mm": bz[1] - bz[0],
        "lip_height_mm": bz[3] - bz[2],
        "cavity_width_mm": bx[3] - bx[2],
        "cavity_depth_mm": by[3] - by[2],
        "cavity_height_mm": bz[3] - bz[1],
        "lip_outer_width_mm": lip_outer_w,
        "lip_outer_depth_mm": by[4] - by[1],
        "wall_mm": bx[2] - bx[0],
        "lip_wall_mm": bx[2] - bx[1],
        "lid_cavity_width_mm": lid_cavity_w,
        "lid_cavity_depth_mm": ly[2] - ly[1],
        "lid_cavity_height_mm": lz[2] - lz[1],
        "lid_height_mm": lz[2] - lz[0],
        "lid_wall_mm": lx[1] - lx[0],
        "lid_clearance_mm": (lid_cavity_w - lip_outer_w) / 2.0,
        "external_height_mm": (bz[3] - bz[0]) + (lz[1] - lz[0]),
    }
    return {k: float(v) for k, v in measured.items()}
```

```python
# append to pythonsrc/organizer/archetypes/__init__.py

def measure_spec_mesh(spec: OrganizerSpec, mesh) -> dict[str, float]:
    """Read a spec's designed features off a mesh with the spec's own archetype."""
    return get_archetype(spec.archetype).measure(mesh)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_deck_box.py -q -k "measure or phase_3 or clears"`
Expected: all passed; `test_the_gate_does_not_fail_the_deck_box` still fails on the keyword until Task 9.

- [ ] **Step 5: Commit**

```bash
git add pythonsrc/organizer/archetypes/ tests/test_deck_box.py
git commit -m "Measure the deck box's designed features back off the mesh, before and after Phase 3

measure() splits the plate into body and lid, reads their distinct axis-aligned
planes and returns every designed feature as a difference of planes — on the
compiled mesh and on what Phase 3 hands the slicer. A plane count that does not
match the design is itself the finding. The Phase 3 round trip through the
--no-scale seam keeps every feature within 0.05 mm with no faces dropped.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: Fits check and the UI view

**Files:**
- Modify: `pythonsrc/organizer/archetypes/deck_box.py` (append `fits_check`, `to_view`)
- Modify: `pythonsrc/organizer/archetypes/__init__.py` (add `fits_for`, `view_for`)
- Test: `tests/test_deck_box.py` (append)

**Interfaces:**
- Produces: `deck_box.fits_check(spec) -> FitsResult`; `deck_box.to_view(spec, result: CompileResult) -> dict`; `archetypes.fits_for(spec) -> FitsResult`; `archetypes.view_for(spec, result) -> dict`. The view dict has keys `archetype`, `archetypeVersion`, `hash`, `dimensions` (list of `{key, label, value, unit, editable, note?}`), `fits` (`FitsResult.to_dict()`), matching `web/src/organizer/spec.ts`.

- [ ] **Step 1: Append the failing tests**

```python
# append to tests/test_deck_box.py
from pythonsrc.organizer.archetypes import fits_for, view_for


def test_the_fits_line_shows_the_arithmetic():
    fits = fits_for(deck())
    assert fits.fits is True
    assert fits.line.startswith("100 × 0.7 mm = 70 mm stack")
    assert "internal 71 mm" in fits.line
    assert "external 74.1 × 76.6 × 97.5 mm" in fits.line
    assert "0.70 mm/card" in fits.basis
    assert fits.remedy is None


def test_an_external_constraint_that_fails_names_the_axis_and_a_card_count():
    spec = deck(constraints=Constraints(max_external_mm=(80.0, 70.0, 100.0)))
    fits = fits_for(spec)
    assert fits.fits is False
    assert "depth" in fits.remedy and "76.6" in fits.remedy and "70" in fits.remedy
    # (70 − 2·2.8 − 1.0) / 0.70 = 90.57 → 90 cards
    assert "90 cards" in fits.remedy


def test_an_external_constraint_that_holds_passes():
    spec = deck(constraints=Constraints(max_external_mm=(80.0, 80.0, 100.0)))
    assert fits_for(spec).fits is True


def test_the_view_has_the_shape_the_ui_declares():
    spec = deck()
    result = compile_spec(spec)
    view = view_for(spec, result)
    assert view["archetype"] == "deck_box"
    assert view["archetypeVersion"] == "v1"
    assert view["hash"] == result.spec_hash
    assert view["fits"]["fits"] is True and "stack" in view["fits"]["line"]
    keys = [d["key"] for d in view["dimensions"]]
    assert keys[0] == "card_count"
    for row in view["dimensions"]:
        assert set(row) >= {"key", "label", "value", "unit", "editable"}
        assert isinstance(row["value"], (int, float)) and isinstance(row["editable"], bool)
    editable = {d["key"] for d in view["dimensions"] if d["editable"]}
    derived = {d["key"] for d in view["dimensions"] if not d["editable"]}
    assert {"card_count", "wall_mm", "lid_clearance_mm"} <= editable
    assert {"stack_height_mm", "cavity_depth_mm", "external_height_mm"} <= derived
    pitch = next(d for d in view["dimensions"] if d["key"] == "pitch_mm")
    assert "0.70 mm/card" in pitch["note"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_deck_box.py -q -k "fits or view"`
Expected: FAIL — `ImportError: cannot import name 'fits_for'`

- [ ] **Step 3: Append the functions**

```python
# append to pythonsrc/organizer/archetypes/deck_box.py

def fits_check(spec: OrganizerSpec) -> FitsResult:
    """The millimetre arithmetic, and whether the result fits its external constraint.

    Without a constraint the deck fits its own cavity by construction — the cavity is
    derived from the stack — and the sum is still returned, because the sum *is* the
    value: it is what a person checks against their own callipers. With
    `constraints.max_external_mm`, each assembled external dimension is compared and a
    failing remedy names the axis, the overshoot and the card count that would fit.
    """
    validate(spec)
    d = derive(spec)
    s = d.stack
    line = (
        f"{s.count} × {s.pitch_mm:g} mm = {s.stack_height_mm:g} mm stack · "
        f"internal {d.cavity_d:g} mm · "
        f"external {d.external_w:g} × {d.external_d:g} × {d.external_h:g} mm"
    )
    fits = s.stack_height_mm <= d.cavity_d
    remedy = None
    limit = spec.constraints.max_external_mm
    if limit is not None:
        over = [
            (axis, extent, maximum)
            for axis, extent, maximum in zip(
                ("width", "depth", "height"), (d.external_w, d.external_d, d.external_h), limit
            )
            if extent > maximum + 1e-9
        ]
        if over:
            fits = False
            notes = [
                f"external {axis} {extent:g} mm exceeds {maximum:g} mm by {extent - maximum:.1f} mm"
                for axis, extent, maximum in over
            ]
            if any(axis == "depth" for axis, _, _ in over):
                room = limit[1] - 2 * spec.process.wall_mm - spec.process.stack_slack_mm
                fitting = max(0, int(math.floor(room / s.pitch_mm + 1e-9)))
                notes.append(f"{fitting} cards would fit the depth limit")
            remedy = "; ".join(notes) + ". Reduce the card count, the wall or the slack, or relax the constraint."
    return FitsResult(fits=fits, line=line, basis=s.basis, remedy=remedy)


def to_view(spec: OrganizerSpec, result: CompileResult) -> dict[str, Any]:
    """The spec as `web/src/organizer/spec.ts` declares it: labelled millimetres, a fits
    verdict, and the hash the gate binds to. Not wired to the server in M0; it exists so
    that wiring is one field rather than a second derivation."""
    d = derive(spec)
    s = d.stack
    p = spec.process
    lid = spec.lid
    assert lid is not None

    def row(key: str, label: str, value: float, unit: str, editable: bool, note: str | None = None) -> dict[str, Any]:
        out: dict[str, Any] = {"key": key, "label": label, "value": value, "unit": unit, "editable": editable}
        if note:
            out["note"] = note
        return out

    dimensions = [
        row("card_count", "Cards", s.count, "cards", True),
        row("pitch_mm", "Pitch per card", s.pitch_mm, "mm", False, s.basis),
        row("stack_height_mm", "Stack height", s.stack_height_mm, "mm", False, f"{s.count} × {s.pitch_mm:g} mm"),
        row("cavity_width_mm", "Internal width", d.cavity_w, "mm", False,
            f"{s.footprint_w_mm:g} mm envelope + {p.cavity_clearance_mm:g} mm clearance"),
        row("cavity_depth_mm", "Internal depth", d.cavity_d, "mm", False,
            f"{s.stack_height_mm:g} mm stack + {p.stack_slack_mm:g} mm slack"),
        row("cavity_height_mm", "Internal height", d.cavity_h, "mm", False,
            f"{s.footprint_h_mm:g} mm envelope + {p.cavity_clearance_mm:g} mm clearance"),
        row("external_width_mm", "External width", d.external_w, "mm", False),
        row("external_depth_mm", "External depth", d.external_d, "mm", False),
        row("external_height_mm", "External height", d.external_h, "mm", False, "assembled, lid on"),
        row("wall_mm", "Wall", p.wall_mm, "mm", True),
        row("floor_mm", "Floor", p.floor_mm, "mm", True),
        row("cavity_clearance_mm", "Cavity clearance", p.cavity_clearance_mm, "mm", True,
            "total per axis over the sleeve envelope"),
        row("stack_slack_mm", "Stack slack", p.stack_slack_mm, "mm", True),
        row("lid_clearance_mm", "Lid clearance", lid.clearance_mm, "mm", True,
            "per side; the fit tolerance a test coupon prints first"),
        row("lid_height_mm", "Lid engagement", lid.height_mm, "mm", True),
    ]
    return {
        "archetype": ARCHETYPE,
        "archetypeVersion": f"v{ARCHETYPE_VERSION}",
        "hash": result.spec_hash,
        "dimensions": dimensions,
        "fits": fits_check(spec).to_dict(),
    }
```

```python
# append to pythonsrc/organizer/archetypes/__init__.py
from ..compiler import FitsResult  # noqa: E402 — keep the import block at the top in practice


def fits_for(spec: OrganizerSpec) -> FitsResult:
    return get_archetype(spec.archetype).fits_check(spec)


def view_for(spec: OrganizerSpec, result: CompileResult) -> dict:
    return get_archetype(spec.archetype).to_view(spec, result)
```

(Move the `FitsResult` import up into the existing `from ..compiler import CompileResult` line.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_deck_box.py -q -k "fits or view"`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add pythonsrc/organizer/archetypes/ tests/test_deck_box.py
git commit -m "Give the deck box a fits check and the view the UI already declares

fits_check returns the arithmetic — count × pitch, internal depth, assembled
external size — and, with an external constraint, names the axis that overshoots
and the card count that would fit. to_view emits exactly the OrganizerSpec shape
in web/src/organizer/spec.ts: labelled millimetres with editable flags, the fits
verdict and the spec hash, so wiring the server later is one field.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: CLI — `python -m pythonsrc.organizer example|compile|measure`

**Files:**
- Create: `pythonsrc/organizer/__main__.py`
- Test: `tests/test_organizer_cli.py`

**Interfaces:**
- Produces: `main(argv: list[str] | None = None) -> int`. Subcommands: `example ARCHETYPE` (prints spec JSON), `compile SPEC --out MESH.stl [--features FEATURES.json] [--spec-out SPEC.json]`, `measure SPEC MESH [--tol 0.05]` (prints a table; exit 1 when out of tolerance).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_organizer_cli.py
"""The organizer's own command line: what a developer runs before `pipeline.py --spec`.

Called in-process through `main(argv)` rather than as a subprocess so the suite needs
no interpreter path and the exit codes are asserted directly.
"""
import json

import pytest

from pythonsrc.organizer.__main__ import main
from pythonsrc.organizer.spec import OrganizerSpec, dump_spec


def test_example_prints_a_valid_spec(capsys):
    assert main(["example", "deck_box"]) == 0
    spec = OrganizerSpec.from_json(capsys.readouterr().out)
    assert spec.archetype == "deck_box"


def test_example_refuses_an_unknown_archetype(capsys):
    assert main(["example", "dragon"]) == 2
    assert "dragon" in capsys.readouterr().err


def test_compile_writes_the_mesh_the_features_and_the_canonical_spec(tmp_path, capsys):
    main(["example", "deck_box"])
    spec_path = tmp_path / "deck.json"
    spec_path.write_text(capsys.readouterr().out)
    out = tmp_path / "deck.stl"
    features = tmp_path / "features.json"
    spec_out = tmp_path / "spec.canonical.json"
    assert main(["compile", str(spec_path), "--out", str(out), "--features", str(features), "--spec-out", str(spec_out)]) == 0
    assert out.stat().st_size > 84
    doc = json.loads(features.read_text())
    assert doc["archetype"] == "deck_box" and doc["parts"] == ["body", "lid"]
    assert OrganizerSpec.from_json(spec_out.read_text()).archetype == "deck_box"


def test_compile_refuses_a_bad_spec_with_exit_2_and_the_problems(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text('{"archetype": "deck_box", "compartments": [], "schema_version": 1}')
    assert main(["compile", str(bad), "--out", str(tmp_path / "x.stl")]) == 2
    assert "compartments" in capsys.readouterr().err


def test_measure_passes_a_compiled_mesh_and_prints_a_table(tmp_path, capsys):
    from pythonsrc.organizer.archetypes import example_spec
    spec_path = dump_spec(example_spec("deck_box"), tmp_path / "deck.json")
    out = tmp_path / "deck.stl"
    assert main(["compile", str(spec_path), "--out", str(out)]) == 0
    capsys.readouterr()
    assert main(["measure", str(spec_path), str(out)]) == 0
    table = capsys.readouterr().out
    assert "cavity_width_mm" in table and "OK" in table


def test_measure_fails_a_mesh_that_is_not_the_spec(tmp_path, capsys):
    import trimesh
    from pythonsrc.organizer.archetypes import example_spec
    spec_path = dump_spec(example_spec("deck_box"), tmp_path / "deck.json")
    wrong = tmp_path / "cube.stl"
    trimesh.creation.box(extents=[10, 10, 10]).export(str(wrong))
    assert main(["measure", str(spec_path), str(wrong)]) == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_organizer_cli.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'pythonsrc.organizer.__main__'`

- [ ] **Step 3: Write the CLI**

```python
# pythonsrc/organizer/__main__.py
"""Command line for the organizer engine — the developer loop before `pipeline.py --spec`.

    python -m pythonsrc.organizer example deck_box > deck.json
    python -m pythonsrc.organizer compile deck.json --out deck.stl --features features.json
    python -m pythonsrc.organizer measure deck.json deck.stl

In the pipeline image (`PYTHONPATH=/app/pythonsrc`) the module is `organizer`. Exit codes:
0 ok, 1 measurement out of tolerance, 2 a spec or usage problem.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import trimesh

from .archetypes import compile_spec, example_spec, get_archetype, measure_spec_mesh
from .compiler import DEFAULT_TOLERANCE_MM, MeasureError, compare_features, export_stl
from .spec import SpecError, dump_spec, load_spec


def _cmd_example(args: argparse.Namespace) -> int:
    print(example_spec(args.archetype).to_json())
    return 0


def _cmd_compile(args: argparse.Namespace) -> int:
    spec = load_spec(args.spec)
    result = compile_spec(spec)
    out = export_stl(result.mesh, args.out)
    if args.features:
        Path(args.features).write_text(json.dumps(result.features_document(), indent=2, sort_keys=True) + "\n")
    if args.spec_out:
        dump_spec(spec, args.spec_out)
    print(f"compiled {result.archetype} v{result.archetype_version} (spec {result.spec_hash[:12]}) → {out}")
    return 0


def _cmd_measure(args: argparse.Namespace) -> int:
    spec = load_spec(args.spec)
    result = compile_spec(spec)
    mesh = trimesh.load(str(args.mesh), force="mesh")
    try:
        measured = measure_spec_mesh(spec, mesh)
    except MeasureError as exc:
        print(f"cannot measure {args.mesh}: {exc}", file=sys.stderr)
        return 1
    rows = compare_features(result.features, measured, args.tol)
    width = max(len(name) for name in rows)
    failed = 0
    for name, (designed, got, err) in rows.items():
        ok = abs(err) <= args.tol
        failed += not ok
        print(f"{name:<{width}}  designed {designed:9.3f}  measured {got:9.3f}  error {err:+.3f}  {'OK' if ok else 'OUT'}")
    print(f"{len(rows) - failed}/{len(rows)} features within ±{args.tol:g} mm")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m pythonsrc.organizer", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p_example = sub.add_parser("example", help="print an example spec for an archetype")
    p_example.add_argument("archetype")
    p_example.set_defaults(func=_cmd_example)

    p_compile = sub.add_parser("compile", help="compile a spec file to an STL")
    p_compile.add_argument("spec", help="spec JSON file")
    p_compile.add_argument("--out", required=True, help="mesh path to write (.stl)")
    p_compile.add_argument("--features", help="also write the designed features as JSON")
    p_compile.add_argument("--spec-out", dest="spec_out", help="also write the spec in canonical, sorted form")
    p_compile.set_defaults(func=_cmd_compile)

    p_measure = sub.add_parser("measure", help="measure a mesh against the spec it claims to implement")
    p_measure.add_argument("spec")
    p_measure.add_argument("mesh")
    p_measure.add_argument("--tol", type=float, default=DEFAULT_TOLERANCE_MM, help="allowed error per feature, mm")
    p_measure.set_defaults(func=_cmd_measure)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except SpecError as exc:
        print("\n".join(f"spec: {p}" for p in exc.problems), file=sys.stderr)
        return 2
    except (OSError, MeasureError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_organizer_cli.py -q`
Expected: 6 passed. Also try it by hand: `python -m pythonsrc.organizer example deck_box | head -5`.

- [ ] **Step 5: Commit**

```bash
git add pythonsrc/organizer/__main__.py tests/test_organizer_cli.py
git commit -m "Add the organizer command line: example, compile, measure

The developer loop before pipeline.py --spec: print an example spec, compile a
spec file to an STL with its features document, and measure any mesh against the
spec it claims to implement, exiting non-zero when a feature is out of tolerance.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 9: Printability gate learns how many parts were intended

**Files:**
- Modify: `pythonsrc/printability.py` — `evaluate_printability` signature (~line 864), the `floating_components` branch (~lines 949–961), `evaluate_mesh_file` (~line 1151)
- Test: `tests/test_printability.py` (append)

**Interfaces:**
- Produces: `evaluate_printability(mesh, profile=None, job_id=None, was_hollowed=False, expected_components: int | None = None)`; `evaluate_mesh_file(mesh_path, profile=None, job_id=None, was_hollowed=False, expected_components=None)`. The `floating_components` `value` dict gains `"expected"`.

- [ ] **Step 1: Append the failing tests**

```python
# append to tests/test_printability.py

def _two_parts_on_the_bed():
    return on_bed(trimesh.util.concatenate([
        trimesh.creation.box(extents=[20, 20, 20]),
        trimesh.creation.box(extents=[20, 20, 6]).apply_translation([40, 0, -7]),
    ]))


def test_two_grounded_parts_still_warn_when_nobody_said_how_many(fdm):
    report = evaluate_printability(_two_parts_on_the_bed(), fdm)
    check = next(c for c in report.checks if c.check == "floating_components")
    assert check.status == "warn"


def test_two_grounded_parts_pass_when_two_were_designed(fdm):
    """A deck box is a body and a lid. A risk badge on every intended two-part plate is
    the mirror image of a fits badge with no measurement behind it."""
    report = evaluate_printability(_two_parts_on_the_bed(), fdm, expected_components=2)
    check = next(c for c in report.checks if c.check == "floating_components")
    assert check.status == "pass"
    assert "as designed" in check.detail
    assert check.value["expected"] == 2


def test_a_part_count_that_does_not_match_the_design_still_warns(fdm):
    report = evaluate_printability(_two_parts_on_the_bed(), fdm, expected_components=3)
    check = next(c for c in report.checks if c.check == "floating_components")
    assert check.status == "warn"


def test_a_floating_part_fails_even_when_it_was_expected(fdm):
    parts = trimesh.util.concatenate([
        trimesh.creation.box(extents=[20, 20, 20]),
        trimesh.creation.box(extents=[6, 6, 6]).apply_translation([0, 0, 40]),
    ])
    report = evaluate_printability(on_bed(parts), fdm, expected_components=2)
    check = next(c for c in report.checks if c.check == "floating_components")
    assert check.status == "fail"
```

(Confirm `on_bed` and `fdm` exist at the top of `tests/test_printability.py` — they do, used at lines 37 and 73 — and that `_two_parts_on_the_bed` lands both bodies at Z = 0 after `on_bed`; adjust the −7 translation if `on_bed` shifts by the global minimum only: the second box's bottom is at −10 vs the first's −10, so both are on the bed.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_printability.py -q -k "grounded or match or expected"`
Expected: FAIL — `TypeError: evaluate_printability() got an unexpected keyword argument 'expected_components'`

- [ ] **Step 3: Implement**

In `evaluate_printability`, add the parameter and document it:

```python
def evaluate_printability(
    mesh: trimesh.Trimesh,
    profile: Optional[ProcessProfile] = None,
    job_id: Optional[str] = None,
    was_hollowed: bool = False,
    expected_components: Optional[int] = None,
) -> PrintabilityReport:
    """...existing docstring...

    Args:
        ...
        expected_components: How many separate bodies the mesh was *designed* to have,
            when the caller knows — a compiled deck box is a body and a lid. With no
            expectation, more than one body warns (the split may be an accident); with
            a matching expectation it passes. A floating body fails regardless: an
            intended part in mid-air is still in mid-air.
    """
```

Replace the `floating_components` status block with:

```python
    if floating:
        floating_status, floating_detail = "fail", (
            f"{floating} component(s) float above the build plate and will print in mid-air. "
            "Flagged, not removed — they may be intended parts needing support or a raft."
        )
    elif components > 1 and expected_components is not None and components == expected_components:
        floating_status, floating_detail = "pass", (
            f"{components} separate parts as designed, all resting on the plate."
        )
    elif components > 1:
        floating_status, floating_detail = "warn", (
            f"{components} separate components, all touching the plate. Printable, but check "
            "whether the split is intentional."
        )
    else:
        floating_status, floating_detail = "pass", "Single connected body resting on the plate."
```

and in the `CheckResult` for it: `value={"components": components, "floating": floating, "expected": expected_components},`.

Thread it through `evaluate_mesh_file`:

```python
def evaluate_mesh_file(
    mesh_path: str,
    profile: Optional[ProcessProfile] = None,
    job_id: Optional[str] = None,
    was_hollowed: bool = False,
    expected_components: Optional[int] = None,
) -> PrintabilityReport:
    mesh = trimesh.load(str(mesh_path), force="mesh")
    return evaluate_printability(
        mesh, profile=profile, job_id=job_id, was_hollowed=was_hollowed,
        expected_components=expected_components,
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_printability.py tests/test_deck_box.py -q`
Expected: all passed — including `test_the_gate_does_not_fail_the_deck_box` left red in Task 6.

- [ ] **Step 5: Commit**

```bash
git add pythonsrc/printability.py tests/test_printability.py tests/test_deck_box.py
git commit -m "Let the printability gate be told how many parts a plate was designed to have

A compiled deck box is a body and a lid on one plate. The floating_components check
read that as a possible unintended split and scored every deck box \"risky\" for it.
evaluate_printability gains expected_components: a matching count passes with \"as
designed\", a mismatch still warns, and a floating body still fails regardless.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 10: `pipeline.py --spec` — flag, spec mode, fixture predicates

**Files:**
- Modify: `pythonsrc/pipeline.py` — `_build_parser` paths group (~line 1468), new `_apply_spec_mode`, `_will_use_reference_assets` (~line 699), `_should_install_reference_blueprint` (~line 130–162), `__main__` block (~line 1603)
- Test: `tests/test_pipeline_spec.py`

**Interfaces:**
- Produces: `_apply_spec_mode(args: argparse.Namespace) -> argparse.Namespace` (raises `ValueError` on `--mesh`/`--hollow` conflicts; sets `skip_visualizer`, `skip_sculptor`, `no_scale` True); both predicates return False when `args.spec` is truthy.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_pipeline_spec.py
"""`pipeline.py --spec`: a compiled spec enters Phases 3–5 as a real run.

The seam already existed — `--skip-visualizer --skip-sculptor --mesh box.stl --no-scale`
— and `--spec` is that seam with the compile step in front of it. Three things must be
true of it, and each was once false of a neighbouring path: it must not land in the
`dev-` namespace (nothing in it is a fixture), it must not get an invented blueprint
(there was never an image), and it must not be combinable with a second source of
geometry or with hollowing (which cannot honour authored dimensions).
"""
import argparse
from pathlib import Path

import pytest

from pythonsrc.pipeline import (
    _apply_spec_mode,
    _build_parser,
    _job_outputs_dir,
    _should_install_reference_blueprint,
    _will_use_reference_assets,
)


def parse(*argv):
    return _apply_spec_mode(_build_parser().parse_args(list(argv)))


def test_spec_implies_the_three_flags_the_seam_is_made_of():
    args = parse("--spec", "deck.json")
    assert args.skip_visualizer and args.skip_sculptor and args.no_scale


def test_spec_needs_no_prompt():
    assert parse("--spec", "deck.json").prompt is None


def test_spec_refuses_a_second_source_of_geometry():
    with pytest.raises(ValueError) as exc:
        parse("--spec", "deck.json", "--mesh", "other.stl")
    assert "--mesh" in str(exc.value)


def test_spec_refuses_hollowing():
    with pytest.raises(ValueError) as exc:
        parse("--spec", "deck.json", "--hollow")
    assert "--hollow" in str(exc.value)


def test_without_spec_nothing_changes():
    args = parse("a vase")
    assert not args.skip_visualizer and not args.skip_sculptor and not args.no_scale


def _ns(**kw):
    base = dict(spec=None, mesh=None, skip_visualizer=False, skip_sculptor=False, job_id="j1", stop_after_phase=None)
    base.update(kw)
    return argparse.Namespace(**base)


def test_a_spec_run_never_uses_reference_assets(tmp_path):
    args = _ns(spec="deck.json", skip_visualizer=True, skip_sculptor=True)
    assert _will_use_reference_assets(args, tmp_path / "missing.png", [tmp_path / "missing.obj"]) is False


def test_a_spec_run_gets_no_invented_blueprint(tmp_path):
    args = _ns(spec="deck.json", skip_visualizer=True, skip_sculptor=True)
    assert _should_install_reference_blueprint(args, tmp_path / "missing.png") is False


def test_a_spec_run_writes_to_the_real_namespace(tmp_path):
    args = _ns(spec="deck.json", skip_visualizer=True, skip_sculptor=True)
    assert _job_outputs_dir(args, tmp_path, tmp_path / "missing.png") == tmp_path / "j1"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_pipeline_spec.py -q`
Expected: FAIL — `ImportError: cannot import name '_apply_spec_mode'`

- [ ] **Step 3: Implement**

In `_build_parser`, after the `--mesh` argument in the paths group:

```python
    paths.add_argument(
        "--spec",
        metavar="PATH",
        help="Compile an organizer spec (pythonsrc/organizer) into the mesh instead of "
             "running Phases 1-2. Implies --skip-visualizer --skip-sculptor --no-scale; "
             "refuses --mesh and --hollow",
    )
```

New function next to `_will_use_reference_assets`:

```python
def _apply_spec_mode(args: argparse.Namespace) -> argparse.Namespace:
    """Make `--spec` mean what it says, and refuse what it cannot mean.

    A spec run *is* the documented `--skip-visualizer --skip-sculptor --mesh --no-scale`
    seam with the compile step in front of it, so the three flags are implied rather than
    required — asking a person to type them is asking for the run that forgets
    `--no-scale` and prints a 50 mm deck box. Two combinations are refused rather than
    resolved: `--mesh` is a second source of geometry, and `--hollow` voxelises at a
    pitch and re-scales, which cannot honour authored dimensions (`Engineer.process`
    refuses it too; refusing here names the reason before anything runs).

    Raises:
        ValueError: Naming the offending flag.
    """
    if not getattr(args, "spec", None):
        return args
    if args.mesh:
        raise ValueError("--spec and --mesh both supply the geometry; pass one of them")
    if args.hollow:
        raise ValueError(
            "--spec refuses --hollow: a compiled spec's dimensions are final, and "
            "hollowing voxelises then re-scales. Model the cavity in the spec instead."
        )
    args.skip_visualizer = True
    args.skip_sculptor = True
    args.no_scale = True
    return args
```

At the top of `_will_use_reference_assets`'s body (before the two `if` checks):

```python
    if getattr(args, "spec", None):
        # A spec run compiles its own geometry and substitutes nothing. Its outputs
        # belong in the real namespace: nothing in them came from a fixture.
        return False
```

At the top of `_should_install_reference_blueprint`'s body:

```python
    if getattr(args, "spec", None):
        # There was never an image. Inventing one would stamp a fixture's hash as this
        # job's Phase 1 provenance.
        return False
```

In the `__main__` block:

```python
if __name__ == "__main__":
    parser = _build_parser()
    args = parser.parse_args()
    try:
        _apply_spec_mode(args)
    except ValueError as exc:
        parser.error(str(exc))

    if args.job_id:
        CURRENT_JOB_ID = args.job_id
    _setup_logging(args.verbose)
    run(args)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_pipeline_spec.py tests/test_pipeline_blueprint.py -q`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add pythonsrc/pipeline.py tests/test_pipeline_spec.py
git commit -m "Add --spec to the pipeline: the compile seam, with the flags it implies

--spec is the documented --skip-visualizer --skip-sculptor --mesh --no-scale seam
with a compile step in front, so those flags are implied rather than typed — the
run that forgets --no-scale prints a 50 mm deck box. It refuses --mesh (two sources
of geometry) and --hollow (cannot honour authored dimensions), never uses a
reference asset and never gets an invented blueprint.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 11: The compile step inside Phase 2, recorded as the generation model

**Files:**
- Modify: `pythonsrc/pipeline.py` — `run()`: `raw_mesh_path` (~line 825), the no-blueprint warning (~line 890), the Phase 2 branch (~lines 993–1093), the printability call (~line 1180); new `_compile_spec_phase`
- Test: `tests/test_pipeline_spec.py` (append)

**Interfaces:**
- Consumes: `organizer.spec.load_spec`, `organizer.spec.dump_spec`, `organizer.archetypes.compile_spec`, `organizer.compiler.export_stl`, `_record_generation`, `_phase_start/_pass/_fail`, `evaluate_mesh_file(..., expected_components=)`.
- Produces: `_compile_spec_phase(args, outputs_dir: Path) -> tuple[Path, CompileResult]` writing `compiled_mesh.stl`, `spec.json`, `compile_features.json` into `outputs_dir`.

- [ ] **Step 1: Append the failing tests**

```python
# append to tests/test_pipeline_spec.py
import json

from pythonsrc.organizer.archetypes import example_spec
from pythonsrc.organizer.spec import SpecError, dump_spec, spec_hash
from pythonsrc.pipeline import _compile_spec_phase


def test_the_compile_step_writes_the_three_artifacts_and_returns_the_mesh(tmp_path):
    spec = example_spec("deck_box")
    spec_path = dump_spec(spec, tmp_path / "in" / "deck.json")
    outputs = tmp_path / "out"
    mesh_path, result = _compile_spec_phase(_ns(spec=str(spec_path)), outputs)
    assert mesh_path == outputs / "compiled_mesh.stl" and mesh_path.stat().st_size > 84
    written = json.loads((outputs / "spec.json").read_text())
    assert written["archetype"] == "deck_box"
    features = json.loads((outputs / "compile_features.json").read_text())
    assert features["spec_sha256"] == spec_hash(spec) == result.spec_hash
    assert features["parts"] == ["body", "lid"]
    assert features["features"]["cavity_width_mm"] == 68.5


def test_a_bad_spec_is_a_spec_error_not_a_crash(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text('{"archetype": "deck_box", "compartments": [], "schema_version": 1}')
    with pytest.raises(SpecError):
        _compile_spec_phase(_ns(spec=str(bad)), tmp_path / "out")


def test_the_generation_record_names_the_compiler(tmp_path, monkeypatch):
    """`generation_model` records what actually made the mesh — here, the archetype."""
    import pythonsrc.pipeline as pipeline
    recorded = {}
    monkeypatch.setattr(pipeline, "_record_generation",
                        lambda args, **kw: recorded.update(kw))
    spec_path = dump_spec(example_spec("deck_box"), tmp_path / "deck.json")
    mesh_path, result = _compile_spec_phase(_ns(spec=str(spec_path)), tmp_path / "out")
    pipeline._record_spec_generation(_ns(spec=str(spec_path)), result, duration_s=0.01)
    assert recorded["model"] == "organizer/deck_box"
    assert recorded["model_version"] == "1"
    assert recorded["backend"] == "local"
    assert recorded["params"]["spec_sha256"] == result.spec_hash
    assert recorded["cost_eur"] is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_pipeline_spec.py -q`
Expected: FAIL — `ImportError: cannot import name '_compile_spec_phase'`

- [ ] **Step 3: Implement**

Two new functions beside `_record_generation`:

```python
def _compile_spec_phase(args, outputs_dir: Path):
    """Phase 2 for a spec run: compile the spec into the job directory.

    Writes three files beside each other so the job directory explains itself:
    `compiled_mesh.stl` (what Phase 3 receives), `spec.json` (the spec in canonical,
    sorted form — the saved object, F11) and `compile_features.json` (every designed
    dimension, the part list, the archetype and version, the spec hash). Nothing here
    is a fixture, so the caller's `outputs_dir` is the real namespace.

    Args:
        args: Parsed CLI arguments; `args.spec` names the spec file.
        outputs_dir: The job's output directory.

    Returns:
        The compiled mesh path and the `CompileResult`.

    Raises:
        SpecError: If the file is not a spec, or the archetype refuses it.
    """
    try:
        from organizer.spec import load_spec, dump_spec
        from organizer.archetypes import compile_spec
        from organizer.compiler import export_stl
    except ImportError:
        from pythonsrc.organizer.spec import load_spec, dump_spec
        from pythonsrc.organizer.archetypes import compile_spec
        from pythonsrc.organizer.compiler import export_stl

    spec = load_spec(args.spec)
    result = compile_spec(spec)
    outputs_dir.mkdir(parents=True, exist_ok=True)
    mesh_path = export_stl(result.mesh, outputs_dir / "compiled_mesh.stl")
    dump_spec(spec, outputs_dir / "spec.json")
    (outputs_dir / "compile_features.json").write_text(
        json.dumps(result.features_document(), indent=2, sort_keys=True) + "\n"
    )
    print(
        f"[DS] Compiled {result.archetype} v{result.archetype_version} "
        f"(spec {result.spec_hash[:12]}, {len(result.parts)} parts, "
        f"{len(result.mesh.faces)} faces) → {mesh_path}",
        flush=True,
    )
    return mesh_path, result


def _record_spec_generation(args, result, duration_s: float) -> None:
    """Record the compiler as this job's generation model.

    `generation_model` records what actually made the mesh, and for a spec run that is
    the archetype — no weights, no cost, `local` backend. The spec hash rides in
    `generation_params` so the row can be joined back to the exact spec without a new
    column; `blueprint_*` stay NULL, which is correct, because no image ever existed.
    """
    _record_generation(
        args,
        model=f"organizer/{result.archetype}",
        model_version=result.archetype_version,
        backend="local",
        params={"schema_version": 1, **result.features_document()},
        cost_eur=None,
        duration_s=round(duration_s, 3),
    )
```

In `run()`, replace the `raw_mesh_path` line:

```python
    if args.spec:
        raw_mesh_path = outputs_dir / "compiled_mesh.stl"
    else:
        raw_mesh_path = Path(args.mesh) if args.mesh else outputs_dir / "raw_mesh.obj"
```

In the Phase 1 skip path, the `elif not blueprint_path.exists():` warning becomes:

```python
        elif not blueprint_path.exists():
            if args.spec:
                # Not a gap: a compiled spec has no image stage. Said at INFO so the
                # running view's empty first stage has an explanation in the log.
                logger.info(
                    "Phase 1 does not apply — the geometry is compiled from %s, so there "
                    "is no blueprint to show or hash.", args.spec,
                )
            else:
                logger.warning(
                    "No blueprint at %s and none will be installed — the mesh came from "
                    "--mesh, so there is no Phase 1 output to show or hash.",
                    blueprint_path,
                )
```

The Phase 2 block becomes a three-way branch. Insert before the existing `if not args.skip_sculptor:`, and turn that `if` into `elif`:

```python
    # ── Phase 2: Sculptor, or the Compiler for a spec run ─────────────────────
    compile_result = None
    if args.spec:
        # The parametric path. Same phase number and the same banner emitters as the
        # sculptor — the UI names this phase "Compiler" and keys off the number — so a
        # spec run's rail moves truthfully and the banner contract is untouched.
        t0 = _phase_start(2)
        try:
            raw_mesh_path, compile_result = _compile_spec_phase(args, outputs_dir)
            _record_spec_generation(args, compile_result, time.time() - t0)
            _phase_pass(2, t0, str(raw_mesh_path))
        except Exception as exc:  # noqa: BLE001 — a SpecError is a Phase 2 failure
            _phase_fail(2, t0, exc)
    elif not args.skip_sculptor:
        t0 = _phase_start(2)
        ...  # existing sculptor body, unchanged
    else:
        ...  # existing "Skipping Phase 2 — using existing mesh" body, unchanged
```

In the printability call:

```python
        report = evaluate_mesh_file(
            str(final_mesh_path),
            profile=process_profile,
            job_id=args.job_id,
            was_hollowed=args.hollow,
            expected_components=len(compile_result.parts) if compile_result else None,
        )
```

- [ ] **Step 4: Run the tests, then the whole suite**

Run: `pytest tests/test_pipeline_spec.py -q` → all passed.
Run: `pytest tests/test_phase_banners.py tests/test_pipeline_blueprint.py tests/test_module_integrity.py -q` → all passed.
Run: `pytest tests/test_licensing_guards.py -q` then `pytest tests/ -q` → all passed (the two commands CI runs).

- [ ] **Step 5: Smoke the seam natively (Phase 3 only; CuraEngine is Docker-only)**

```bash
python -m pythonsrc.organizer example deck_box > data/inputs/deck_box.spec.json
python pythonsrc/pipeline.py --spec data/inputs/deck_box.spec.json --stop-after-phase 3
python -m pythonsrc.organizer measure data/inputs/deck_box.spec.json data/outputs/engineered_mesh.obj
```

Expected: `PHASE 2 START/PASS`, `PHASE 3 START/PASS`, "Preserving authored dimensions — not scaling", and the measure table all `OK`. Without `--job-id` the run uses the flat `data/outputs/` layout and writes nothing to the telemetry database.

- [ ] **Step 6: Commit**

```bash
git add pythonsrc/pipeline.py tests/test_pipeline_spec.py
git commit -m "Run the spec compile inside Phase 2 and record the archetype as the generation model

A spec run compiles into the job directory — compiled_mesh.stl, spec.json in
canonical form, compile_features.json — between the real Phase 2 banners, so the
UI's Compiler phase moves truthfully and the banner contract is untouched. The
archetype and version are recorded as generation_model/_version with the spec hash
in generation_params; no new column. The gate is told how many parts were designed.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 12: Documentation — CLAUDE.md, ARCHITECTURE.md, roadmap and README ticks, pipeline.ts

**Files:**
- Modify: `CLAUDE.md` (the "Project Overview" note; new section after **Sculptor — Phase 2**)
- Modify: `ARCHITECTURE.md` (new `## Phase 2 — Compiler: spec → geometry (parametric path)` before `## Phase 3`)
- Modify: `docs/ds-mvp-roadmap.md` lines 209–210 and `README.md` lines 264–265 (the two tick-boxes)
- Modify: `web/src/pipeline.ts` lines 12–27 (header comment)
- Modify: `docs/superpowers/specs/2026-09-03-organizer-spec-and-deck-box-design.md` (package layout: registry lives in `archetypes/__init__.py`)

- [ ] **Step 1: CLAUDE.md — update the overview note**

Replace, in the first paragraph, the sentence `The parametric engine (\`pythonsrc/organizer/\` — spec schema, archetypes, dimension KB) does not exist yet; do not treat generative-path tuning as roadmap work.` with:

```
The parametric engine has its first two pieces (2026-09-03): the spec schema
(`pythonsrc/organizer/spec.py`) and the deck box archetype
(`pythonsrc/organizer/archetypes/deck_box.py`), entered through `pipeline.py --spec` —
see **Organizer — the parametric path** below. The dimension KB, LLM extraction and
the server wiring do not exist yet; do not treat generative-path tuning as roadmap work.
```

- [ ] **Step 2: CLAUDE.md — add the section** (after the **Sculptor worker** subsection, before **Server**)

```markdown
### Organizer — the parametric path (pythonsrc/organizer/)

The pivot's engine, as far as M0 built it: a **spec schema** and one **archetype**,
entered through `pipeline.py --spec PATH`. *The LLM interprets words; it never produces
geometry* — and the spec is the boundary that rule describes. Everything left of it may
be probabilistic; everything right of it is deterministic, and the same spec compiles to
the same STL byte for byte (`tests/test_deck_box.py` pins that).

- **`spec.py` is stdlib-only, on purpose.** Frozen dataclasses (`OrganizerSpec`,
  `Compartment`, `CardStack`, `Lid`, `Constraints`, `Process`), millimetres rounded to
  1 µm on construction so `from_dict(to_dict(s)) == s` holds exactly, `from_dict`
  refusing unknown keys, and one `SpecError` listing *every* problem with its dotted
  path. `canonical_json` / `spec_hash` / `spec_diff` make one spec one string, one
  hash, and two specs a path-by-path diff (F8). `pythonsrc.organizer` exports the schema
  and nothing else, so the api-server image — no trimesh, no manifold3d — can import it
  when the request model grows a spec field. Do not add pydantic here; it is not in the
  pipeline image.
- **`dimensions.py` is a seed, not the KB.** The standard card footprint, the single and
  double sleeved envelopes and the three design pitches (0.305 / 0.60 / 0.70 mm per
  card), each with its source from `docs/dimension-kb-research.md`. Only `standard` is
  offered: the Japanese size has no sourced sleeve envelope and an invented one is
  exactly the fabricated number the schema exists to refuse. The M2 KB replaces this
  file; `resolve_stack`'s `basis` string is what the UI's fits line shows.
- **Archetype rules live in the archetype.** A lip thinner than `min_feature_mm`, a
  second compartment, magnets, a lid taller than the cavity — `deck_box.validate`
  refuses each with the remedy named. Ignoring an unsupported field prints a different
  box than the one asked for, silently.
- **Every designed feature is measured back off the mesh** (`deck_box.measure`, the
  shape of text-to-cad's measure/align checkers): the plate is split into body and lid,
  their distinct axis-aligned planes are read, and each feature is a difference of
  planes. It runs on the compiled mesh *and on Phase 3's output*, which is what makes the
  ±0.05 mm assertion honest — it measures what the slicer receives. A plane count that
  does not match the design is itself the finding (`MeasureError`).
- **`--spec` is the `--skip-visualizer --skip-sculptor --mesh --no-scale` seam with a
  compile step in front.** The three flags are implied (`_apply_spec_mode`) — the run
  that forgets `--no-scale` prints a 50 mm deck box. `--mesh` and `--hollow` are refused.
  The compile runs inside the **real Phase 2 banners**, so the UI's "Compiler" moves
  truthfully and the banner contract is untouched. A spec run substitutes nothing:
  `_will_use_reference_assets` and `_should_install_reference_blueprint` both return
  False, so it lands in `data/outputs/{job_id}` and gets no invented blueprint. The job
  directory holds `compiled_mesh.stl`, `spec.json` (canonical) and
  `compile_features.json`.
- **The compiler is the generation model.** `generation_model = "organizer/deck_box"`,
  `generation_model_version = "1"`, `generation_backend = "local"`, the spec hash and
  features in `generation_params`. No new column — this is exactly what those columns
  record. `blueprint_*` stay NULL, correctly. `size_source="spec"` is *not* written yet;
  that is the repair-assertion tick-box and needs the request model.
- **The gate is told the part count.** `evaluate_printability(expected_components=)`:
  a body and a lid are two grounded bodies as designed, and used to score every deck
  box "risky" for a possible unintended split. A mismatch still warns; a floating body
  still fails.
- **Not built, and where it is:** the repair-assertion path and `size_source="spec"`
  (roadmap §0.3 Phase 1, tick-box 4), the envelope sweep CI (tick-box 5), the server and
  UI wiring (`specFromJob` is the seam; `NO_SPEC_REASON` is still true), LLM extraction
  and the KB (M2). `python -m pythonsrc.organizer example|compile|measure` is the
  developer loop.
```

- [ ] **Step 3: ARCHITECTURE.md — add the parametric Phase 2 entry** before `## Phase 3 — Engineer`:

```markdown
## Phase 2 — Compiler: spec → geometry (parametric path)

The pivot's engine (`docs/PRD_daedal_tcg_organizers.md` F5; roadmap §0.3 Phase 1). Runs
under the same phase number and banners as the sculptor; `pipeline.py --spec` selects it
and Phases 1–2 above are then not run at all.

| | |
|---|---|
| **Code** | `pythonsrc/organizer/` — `spec.py` (schema), `dimensions.py` (seed numbers), `archetypes/deck_box.py` (v1) |
| **Model** | None. Deterministic CSG; the same spec compiles to the same STL byte for byte |
| **Kernel** | `manifold3d` 3.5.2 (Apache-2.0) — the decision recorded under *The geometry kernel* above, exercised |
| **Recorded as** | `generation_model = organizer/deck_box`, `generation_model_version = 1`, `generation_backend = local`, spec sha256 in `generation_params` |
| **Licence delta** | None — no new dependency, no weights |
| **Measured** | Compile of a 100-card deck box: 72 faces, < 0.1 s. Every designed feature within 0.05 mm on the compiled mesh and on Phase 3's output (`tests/test_deck_box.py`) |
| **Not yet** | Repair-assertion path, `size_source="spec"`, envelope sweep, server/UI wiring, dimension KB, LLM extraction |
```

- [ ] **Step 4: Tick the two boxes in both places**

In `docs/ds-mvp-roadmap.md` and `README.md`, change the two lines to:

```
- [x] Spec schema — `pythonsrc/organizer/spec.py`, JSON-serialisable, diffable (2026-09-03)
- [x] First archetype: deck box, spec → mesh → Phases 3–5 via the `--skip… --mesh --no-scale` seam (authored with text-to-cad, source frozen) — `pipeline.py --spec`, kernel `manifold3d` (2026-09-03)
```

- [ ] **Step 5: `web/src/pipeline.ts` — bring the header note up to date**

Replace the paragraph beginning `These names describe the parametric pipeline the product is pivoting to` through `…because the `.status` protocol and every historical status file key off phases 1–5.` with:

```
 * These names describe the parametric pipeline (`docs/PRD_daedal_tcg_organizers.md`,
 * roadmap §§0.1–7A). As of 2026-09-03 the engine exists for one archetype:
 * `pythonsrc/organizer/` compiles a deck-box spec and `pipeline.py --spec` runs that
 * compile as phase 2, so "Compiler" is literal on that path. On the generative path
 * phase 1 still renders a blueprint with FLUX.2 and phase 2 reconstructs it with
 * TRELLIS.2. The server does not yet carry a spec on `JobStatusResponse`, so
 * `specFromJob` still returns null and `NO_SPEC_REASON` is still true. Phase 3 is the
 * Engineer — watertight repair and scaling — and the printability gate it is named for
 * actually runs *between* phases 3 and 4, deliberately unnumbered, because the
 * `.status` protocol and every historical status file key off phases 1–5.
```

- [ ] **Step 6: Spec doc — package layout line**

In the design doc's *Package layout* block, change `compiler.py            compile_spec() → CompileResult; archetype registry` to `compiler.py            CompileResult, FitsResult, MeasureError, kernel bridge, plane sets` and `archetypes/__init__.py` to `archetypes/__init__.py  registry + dispatch: compile_spec, measure_spec_mesh, fits_for, view_for, example_spec`.

- [ ] **Step 7: Check the web build and the doc-facing tests**

Run: `cd web && npm run build` → passes (comment-only change).
Run: `pytest tests/test_licence_data.py tests/test_licensing_guards.py -q` → all passed.

- [ ] **Step 8: Commit**

```bash
git add CLAUDE.md ARCHITECTURE.md docs/ds-mvp-roadmap.md README.md web/src/pipeline.ts docs/superpowers/specs/2026-09-03-organizer-spec-and-deck-box-design.md
git commit -m "Document the parametric path: organizer package, --spec seam, what is not built

CLAUDE.md gains the Organizer section and the overview note says what exists after
M0; ARCHITECTURE.md gains the parametric Phase 2 entry with no licence delta; the
roadmap and its README mirror tick the spec-schema and deck-box boxes; the
pipeline.ts header stops saying the engine does not exist.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 13: End-to-end verification through Phases 3–5 in Docker

**Files:** none modified. This task produces evidence, and the final report must say exactly which phases ran.

- [ ] **Step 1: The suite, the way CI runs it**

```bash
pytest tests/test_licensing_guards.py -q
pytest tests/ -q
```

Expected: all passed, no new warnings about the organizer.

- [ ] **Step 2: Native Phase 3 smoke** (already done in Task 11 Step 5; repeat if anything changed)

- [ ] **Step 3: Phases 3–4 in the pipeline image**

```bash
python -m pythonsrc.organizer example deck_box > data/inputs/deck_box.spec.json
docker compose -f infra/docker-compose.yml build pipeline-runner
docker compose -f infra/docker-compose.yml run --rm pipeline-runner \
  python pythonsrc/pipeline.py --spec /app/data/inputs/deck_box.spec.json --slice
```

Expected in the output: `PHASE 2 START/PASS` with the `[DS] Compiled deck_box v1 …` line, `PHASE 3 PASS` with "Preserving authored dimensions", `PRINTABILITY` with `floating_components` passing, `PHASE 4 PASS` writing `data/outputs/engineered_mesh.gcode`. Then:

```bash
python -m pythonsrc.organizer measure data/inputs/deck_box.spec.json data/outputs/engineered_mesh.obj
grep -c "^G1" data/outputs/engineered_mesh.gcode
```

Expected: every feature `OK`; a G-code file with thousands of moves.

- [ ] **Step 4: Phase 5 against the OctoPrint simulator**

```bash
docker compose -f infra/docker-compose.yml --profile simulator up -d octoprint-simulator
sleep 20 && curl -s -o /dev/null -w "%{http_code}\n" http://localhost:5001/api/version
KEY=$(python3 -c "import sys; sys.path.insert(0,'server'); from simulator_manager import SimulatorManager; print(SimulatorManager().octoprint_api_key() or '')")
docker compose -f infra/docker-compose.yml run --rm -e OCTOPRINT_API_KEY="$KEY" pipeline-runner \
  python pythonsrc/pipeline.py --spec /app/data/inputs/deck_box.spec.json --print --start-print \
  --octoprint-url http://localhost:5001
```

Expected: `PHASE 5 PASS`, the simulator's job list (`curl -H "X-Api-Key: $KEY" http://localhost:5001/api/job`) showing `engineered_mesh.gcode` printing. If the api-key lookup returns empty, read it from `data/octoprint/octoprint/config.yaml` (`api: key:`). If the simulator cannot be reached from the container, the fallback route is documented in CLAUDE.md under *Printer readiness* (`host.docker.internal`); report what happened rather than forcing it.

- [ ] **Step 5: Leave the tree clean**

`git status --short` shows nothing but the intentional `data/` runtime files (gitignored). Remove `data/inputs/deck_box.spec.json` only if it was not useful to keep as the documented example path; otherwise leave it.

- [ ] **Step 6: Report**

State which phases ran where (native: 2–3; Docker: 2–4, and 5 if the simulator accepted the print), the measured tolerance results, the gate score and verdict, and the two tick-boxes closed. Name explicitly what was left out: tick-boxes 4 and 5, server/UI wiring, KB, extraction.
