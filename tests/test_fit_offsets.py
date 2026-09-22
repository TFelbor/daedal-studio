"""Per-printer fit offsets — the decision they implement, asserted rather than trusted.

Issue #89. The decision the issue was filed to unblock was taken by the owner on
2026-09-17 and it is **(b): fit offsets stay in the spec**; a printer profile is the
source the composer pre-fills a form from, never an input to the compiler. Every claim
that decision makes is something a future change could break silently, so each one is a
test here:

- **the geometry is not a function of a printer.** `pythonsrc/organizer/` does not import
  `fit_offsets`, transitively or otherwise — under (a) it would have had to, and the
  difference between "we chose not to" and "it cannot reach it" is this assertion;
- **no `spec_hash` moves.** (b) adds no field to any spec class, so the pinned example
  hashes stand. That is `tests/test_organizer_spec.py`'s job and it keeps it; what is
  asserted here is the thing that would make it false — that nothing in this change put a
  field on `Process` or `Lid`;
- **a profile that says nothing about fit changes nothing.** The fallbacks are today's
  schema numbers, checked against the schema itself rather than against literals copied
  out of it;
- **the bundled profiles' numbers are the sourced table's.** A millimetre in a JSON file
  carries no citation, so the file names its class and this binds the class to
  `FIT_OFFSET_CLASSES`, which is where the sources are written down;
- **the offer is recorded.** Under (b) nothing else in a finished job says which machine's
  figures were on screen, so `generation_params` has to carry it deliberately.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from pythonsrc.fit_offsets import (
    CLASS_KEY,
    DEFAULT_FIT_OFFSETS,
    FIT_OFFSET_CLASSES,
    FIT_OFFSETS_VERSION,
    PROFILE_KEYS,
    FitOffsets,
    fit_offsets_from_profile,
    fit_offsets_record,
)
from pythonsrc.organizer.spec import FIT_INTENT_CLEARANCE_MM, Lid, Process
from pythonsrc.printability import ProcessProfile

PROFILES_DIR = Path(__file__).resolve().parent.parent / "pythonsrc" / "profiles"

#: Every bundled profile that is a printer rather than a CuraEngine definition.
BUNDLED_PROFILES = sorted(p for p in PROFILES_DIR.glob("*.json"))


def _profile(name: str) -> dict:
    return json.loads((PROFILES_DIR / name).read_text())


# ── the decision, structurally ─────────────────────────────────────────────────


def test_the_compiler_cannot_reach_a_fit_offset():
    """The structural half of decision (b), and the only assertion here that is about
    something *not* happening.

    Under (a) the offsets would be a compile input and `pythonsrc/organizer/` would
    import this module. Under (b) it must not, because an import is all it would take for
    a well-meant change to start applying a machine's millimetres inside `compile_spec` —
    at which point the same spec exports different bytes on two printers, `spec_hash`
    silently means less than it says, and nothing in the suite notices.

    Grepped over the source rather than checked with `sys.modules`: an import that only
    happens on one branch would not show up in a loaded-module check, and the claim is
    about the code, not about one run of it.
    """
    organizer = Path(__file__).resolve().parent.parent / "pythonsrc" / "organizer"
    offenders = [
        path.relative_to(organizer.parent)
        for path in organizer.rglob("*.py")
        if "fit_offsets" in path.read_text()
    ]
    assert offenders == [], (
        "The organizer package reached pythonsrc/fit_offsets.py in "
        f"{offenders}. Issue #89 decided (b): fit offsets pre-fill the composer and are "
        "not a compile input, so the geometry must not be able to see one."
    )


def test_no_fit_field_was_added_to_the_schema():
    """(b) is additive-free on the spec side, which is why no stored hash moves.

    `tests/test_organizer_spec.py` pins the example hashes and would go red if this were
    violated — but it would go red for *any* schema change, naming none of them. This
    says which change was not made, so a reviewer reading a future diff that adds
    `Process.fit_offset_mm` gets a failure that quotes issue #89 at them.

    The fields below are the three the composer pre-fills. They existed before #89 and
    are unchanged by it; the profile supplies *values* for them, never new fields.
    """
    assert set(Lid.__dataclass_fields__) == {
        "kind", "magnets", "height_mm", "wall_mm", "clearance_mm", "top_mm",
    }
    assert "cavity_clearance_mm" in Process.__dataclass_fields__
    assert "stack_slack_mm" in Process.__dataclass_fields__
    assert not [
        name for name in Process.__dataclass_fields__ if name.startswith("fit_offset")
    ]


# ── a profile that says nothing ────────────────────────────────────────────────


def test_a_profile_with_no_fit_keys_resolves_to_the_schemas_own_numbers():
    """The explicit answer to "what happens when no printer is configured" (the
    decision's fourth open point), and it is *nothing happens*.

    Checked against `Lid` and `Process` themselves rather than against 0,2 and 1,0
    written out here. A literal would let the two drift: someone changing the schema
    default would move what a spec compiles to and leave this file asserting the old
    number was still the fallback, which is the one thing this test exists to deny.
    """
    offsets = fit_offsets_from_profile({})
    assert offsets == DEFAULT_FIT_OFFSETS
    assert offsets.lid_clearance_mm == Lid().clearance_mm
    assert offsets.stack_slack_mm == Process().stack_slack_mm
    # No allowance, so the cavity a `snug` spec gets is the intent's own figure.
    assert offsets.cavity_clearance_offset_mm == 0.0


def test_each_key_falls_back_on_its_own():
    """A profile may state one figure and say nothing about the others.

    Not a hypothetical: the calibration loop measures one fit at a time, so a profile
    carrying only the lid clearance a coupon produced is the ordinary shape of a
    half-calibrated machine.
    """
    offsets = fit_offsets_from_profile({"fit_lid_clearance_mm": 0.35})
    assert offsets.lid_clearance_mm == 0.35
    assert offsets.cavity_clearance_offset_mm == DEFAULT_FIT_OFFSETS.cavity_clearance_offset_mm
    assert offsets.stack_slack_mm == DEFAULT_FIT_OFFSETS.stack_slack_mm


@pytest.mark.parametrize("bad", ["", "wide", None, [], {}])
def test_an_unparseable_fit_value_falls_back_rather_than_raising(bad):
    """A profile is hand-edited through the Settings UI, and a typo in a fit key is not
    a reason to refuse to slice.

    The figure this file offers is printed on the composer beside the profile it came
    from, which is where a wrong number is visible and fixable — unlike an exception
    thrown four phases into a run.
    """
    assert fit_offsets_from_profile({"fit_stack_slack_mm": bad}) == DEFAULT_FIT_OFFSETS


# ── the bundled profiles ───────────────────────────────────────────────────────


@pytest.mark.parametrize("path", BUNDLED_PROFILES, ids=lambda p: p.name)
def test_every_bundled_profile_declares_a_known_class_and_its_numbers(path):
    """The binding that makes `fit_offsets_class` more than a label.

    A JSON file cannot carry a comment, so a bare `0.3` in a machine definition is
    exactly the unsourced millimetre this repository refuses everywhere else. The profile
    names the row of `FIT_OFFSET_CLASSES` it came from, the table is where the citations
    live, and this asserts the three numbers really are that row's — so they cannot drift
    from the sources without a test going red.
    """
    profile = json.loads(path.read_text())
    declared = profile.get(CLASS_KEY)
    assert declared in FIT_OFFSET_CLASSES, (
        f"{path.name} declares fit_offsets_class {declared!r}, which is not a row of "
        f"FIT_OFFSET_CLASSES ({sorted(FIT_OFFSET_CLASSES)})."
    )
    assert fit_offsets_from_profile(profile) == FIT_OFFSET_CLASSES[declared], (
        f"{path.name}'s fit numbers are not class {declared!r}'s. The class names where "
        "the numbers came from; if they need to differ, the profile needs its own "
        "sourced row in pythonsrc/fit_offsets.py, not a quiet edit here."
    )
    assert all(key in profile for key in PROFILE_KEYS)


def test_the_bambu_profile_records_where_its_fit_numbers_came_from():
    """`bambu_p1s.json` is the one bundled profile that carries `_sources`, and #73's
    finding was that where a number came from is the difference between a profile
    somebody can check and one somebody has to guess at. The fit numbers join that.
    """
    sources = _profile("bambu_p1s.json")["_sources"]
    assert "fit_offsets" in sources
    assert "fit_offsets.py" in sources["fit_offsets"]


def test_the_two_classes_differ_in_the_field_that_is_about_the_machine():
    """The table earns its two rows, or it should be one row.

    `lid_clearance_mm` is a fit between two printed parts and is the field a machine's
    dimensional accuracy actually governs, so the classes must differ there. If they ever
    do not, the per-printer story has collapsed into a single default and the profile
    plumbing is carrying no information.
    """
    tuned = FIT_OFFSET_CLASSES["tuned"]
    desktop = FIT_OFFSET_CLASSES["desktop"]
    assert desktop.lid_clearance_mm > tuned.lid_clearance_mm
    # And the one that is deliberately uniform stays uniform, because nothing sources a
    # per-machine figure for it. This fails the day somebody invents one.
    assert desktop.stack_slack_mm == tuned.stack_slack_mm == DEFAULT_FIT_OFFSETS.stack_slack_mm


def test_every_offered_lid_clearance_is_inside_the_sourced_band():
    """0,2–0,4 mm of friction-lip engagement — `docs/dimension-kb-research.md` §5, the
    GreatLight deck-box guide. The placement of each class inside the band is this
    project's reasoning and says so; leaving the band would be inventing a number.
    """
    for name, offsets in FIT_OFFSET_CLASSES.items():
        assert 0.2 <= offsets.lid_clearance_mm <= 0.4, name


@pytest.mark.parametrize("intent", sorted(FIT_INTENT_CLEARANCE_MM))
@pytest.mark.parametrize("cls", sorted(FIT_OFFSET_CLASSES))
def test_every_offered_cavity_clearance_is_inside_its_own_sourced_band(cls, intent):
    """The cross-check that makes `cavity_clearance_offset_mm` more than a plausible
    number, and the strongest thing in the table.

    The allowance is §6's desktop accuracy floor — a figure from the *tolerance* research.
    Added to the intents it has to land inside §3's *clearance* bands, which were gathered
    from commercial deck boxes and have nothing to do with §6. Two independent sections
    agreeing is what a sourced number looks like; one section and a round figure is not.

    §3: +1,5–2 mm over the sleeve envelope for a snug commercial-style fit, +4–6 mm for
    easy-in/out printed boxes.
    """
    bands = {"snug": (1.5, 2.0), "easy": (4.0, 6.0)}
    low, high = bands[intent]
    resolved = FIT_INTENT_CLEARANCE_MM[intent] + FIT_OFFSET_CLASSES[cls].cavity_clearance_offset_mm
    assert low <= resolved <= high, (
        f"{cls} + {intent} resolves to {resolved} mm, outside §3's {low}–{high} mm band."
    )


# ── ProcessProfile, and the single reader ──────────────────────────────────────


@pytest.mark.parametrize("path", BUNDLED_PROFILES, ids=lambda p: p.name)
def test_process_profile_reads_the_same_figures_as_the_shared_reader(path):
    """One reader, which is the whole reason the table is a standalone module.

    `server/app.py` cannot import `printability` — the api-server image installs no numpy,
    trimesh or scipy — so it calls `fit_offsets_from_profile` directly. If `ProcessProfile`
    parsed the keys itself the composer and the scorer would be two opinions about what
    four keys in a profile file mean, which is the divergence `_profile_build_volume` was
    made single-implementation to prevent.
    """
    profile = json.loads(path.read_text())
    assert ProcessProfile.from_printer_profile(profile).fit_offsets == (
        fit_offsets_from_profile(profile)
    )


def test_a_bare_process_profile_carries_the_defaults():
    """Nothing constructs a `ProcessProfile` with fit in mind, so the default must be the
    do-nothing one rather than a class's."""
    assert ProcessProfile().fit_offsets == DEFAULT_FIT_OFFSETS


def test_no_printability_check_reads_a_fit_offset():
    """The field is on `ProcessProfile` because that is what "what the profile says about
    this printer" means, **not** because anything scores against it.

    A check that read one would be judging geometry against a number that is by
    construction already baked into the geometry — the clearance is in the spec the mesh
    was built from — so it would double-count, and it would make the printability verdict
    a function of the machine's *suggested* offsets rather than of the part.
    """
    import pythonsrc.printability as printability

    source = Path(printability.__file__).read_text()
    # The dataclass field, its docstring and the constructor read are the only mentions.
    body = source.split("@dataclasses.dataclass", 1)[1].split("def evaluate_printability", 1)[0]
    after = source.split("def evaluate_printability", 1)[1]
    assert "fit_offsets" not in after, (
        "A printability check reads fit_offsets. It must not: the clearance is already "
        "in the geometry being scored (issue #89, decision (b))."
    )
    assert "fit_offsets" in body


# ── the record ─────────────────────────────────────────────────────────────────


def test_the_record_says_which_profile_and_which_version():
    """Issue #89's fourth acceptance criterion. Under (b) the mesh is not a function of a
    printer, so nothing else in a finished row says which machine's figures a person was
    shown — and "this box does not close" is a complaint about a printer.
    """
    record = fit_offsets_record("ender3.json", _profile("ender3.json"))
    assert record["profile"] == "ender3.json"
    assert record["fit_offsets_version"] == FIT_OFFSETS_VERSION
    assert record["declared"] is True
    assert record["offsets"] == FIT_OFFSET_CLASSES["desktop"].to_dict()


def test_the_record_tells_a_silent_profile_from_a_suggesting_one():
    """`declared` is the difference between "this machine suggested the schema's own
    numbers" and "nothing was asked". They are the same millimetres and different facts,
    and only one of them is evidence about a printer.
    """
    silent = fit_offsets_record("legacy.json", {"machine_name": "Legacy"})
    assert silent["declared"] is False
    assert silent["offsets"] == DEFAULT_FIT_OFFSETS.to_dict()

    missing = fit_offsets_record(None, None)
    assert missing["profile"] is None
    assert missing["declared"] is False


def test_the_record_carries_what_was_offered_not_what_was_chosen():
    """It records the *offer*. The spec is the record of what was accepted — in
    millimetres, written beside this one — and a second copy here could disagree with it,
    which is the failure `game_box_record` avoids by being one function.
    """
    record = fit_offsets_record("bambu_p1s.json", _profile("bambu_p1s.json"))
    assert set(record) == {"profile", "fit_offsets_version", "offsets", "declared"}
    assert set(record["offsets"]) == set(PROFILE_KEYS)


def test_the_record_is_json_serialisable():
    """It goes on `generation_params`, which is a JSON column."""
    record = fit_offsets_record("ender3.json", _profile("ender3.json"))
    assert json.loads(json.dumps(record)) == record


def test_to_dict_keys_the_figures_the_way_a_profile_keys_them():
    """One vocabulary. The record, the profile file and the reader all say
    `fit_lid_clearance_mm`, so a figure can be traced from a database row to the line in
    the JSON file it came from without a mapping table in between.
    """
    assert set(FitOffsets(1.0, 2.0, 3.0).to_dict()) == set(PROFILE_KEYS)
