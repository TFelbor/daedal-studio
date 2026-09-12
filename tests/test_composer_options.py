"""The configurator offers exactly what the engine accepts, and routes every refusal.

`tests/test_archetype_registry.py` binds the archetype strip's list to the schema's,
after the strip spent a release offering `dice_tray`, `box_insert` and `dividers` —
none of which existed. The configurator (`web/src/components/SpecForm.tsx`) has five
more closed vocabularies and eleven editable fields, every one of them with the same
failure available to it: an option the form offers and the schema refuses is a person
picking something, submitting, and being told by a 422 that what they were shown does
not exist.

There is no test runner in `web/`, so these files are read as text — the
`test_archetype_registry.py` and `test_download_formats.py` precedent. Read as text
rather than imported on purpose: importing would need a bundler, and the point is the
literal a reviewer sees.

Three bindings:

- every vocabulary the form offers is its Python counterpart, in order;
- every dotted path the form routes a refusal by is a path the schema really emits —
  poked, not assumed;
- the one millimetre figure the form prints as prose is the dimension table's.
"""
import copy
import re
from pathlib import Path

import pytest

from pythonsrc.organizer.dimensions import CARD_KINDS, SLEEVINGS
from pythonsrc.organizer.spec import (
    ARCHETYPES,
    ARCHETYPE_WALL_MM,
    FIT_INTENTS,
    LID_KINDS,
    TAB_POSITIONS,
    OrganizerSpec,
    SpecError,
    problems_with_paths,
)
from server.app import SLEEVING_WORDS

REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_SPEC = REPO_ROOT / "web" / "src" / "organizer" / "spec.ts"
WEB_FORM = REPO_ROOT / "web" / "src" / "organizer" / "specForm.ts"
WEB_FORM_TSX = REPO_ROOT / "web" / "src" / "components" / "SpecForm.tsx"
WEB_NEW_JOB = REPO_ROOT / "web" / "src" / "pages" / "NewJob.tsx"


def string_list(text: str, name: str) -> list[str]:
    """The entries of `export const NAME = ['a', 'b'] as const;`, in order."""
    block = re.search(rf"export const {name} = \[(.*?)\] as const;", text, re.S)
    assert block, f"could not find the {name} literal"
    return re.findall(r"'([^']+)'", block.group(1))


def object_map(text: str, name: str) -> dict[str, str]:
    """The `key: 'value'` pairs of a `export const NAME…= {…};` object literal.

    The key may be quoted or not — a dotted path has to be, a field name need not.
    """
    block = re.search(rf"export const {name}[^=]*= \{{(.*?)\n\}};", text, re.S)
    assert block, f"could not find the {name} literal"
    return dict(re.findall(r"^\s*'?([\w.\[\]]+)'?:\s*'([^']+)'", block.group(1), re.M))


@pytest.fixture(scope="module")
def spec_ts() -> str:
    return WEB_SPEC.read_text(encoding="utf-8")


# ── the vocabularies ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("name, expected", [
    ("CARD_KINDS", sorted(CARD_KINDS)),
    ("SLEEVINGS", list(SLEEVINGS)),
    ("LID_KINDS", list(LID_KINDS)),
    ("FIT_INTENTS", list(FIT_INTENTS)),
    ("TAB_POSITIONS", list(TAB_POSITIONS)),
])
def test_the_composer_offers_exactly_what_the_schema_accepts(spec_ts, name, expected):
    assert string_list(spec_ts, name) == expected


def test_every_sleeving_reads_as_words_on_both_sides(spec_ts):
    """The spec table's caption and the label a spec job is titled with describe the
    same field, so neither may know a sleeving the other does not."""
    assert set(object_map(spec_ts, "SLEEVING_NOTE")) == set(SLEEVINGS)
    assert set(SLEEVING_WORDS) == set(SLEEVINGS)


def test_every_fit_intent_has_words_a_person_can_choose_by(spec_ts):
    """`fit_intent` is a word rather than a number because it is the thing somebody
    actually decides, which only holds if the strip says what each one means."""
    assert set(object_map(spec_ts, "FIT_INTENT_LABELS")) == set(FIT_INTENTS)


# ── the refusal routing ───────────────────────────────────────────────────────

def field_by_path() -> dict[str, str]:
    return object_map(WEB_FORM.read_text(encoding="utf-8"), "FIELD_BY_PATH")


#: A spec carrying every section the form can edit, so any path can be poked into it.
#: Both optional sections at once: the *schema* type-checks them and the archetypes
#: are what refuse the wrong one, and the archetypes need the kernel.
BASE = {
    "archetype": "deck_box",
    "compartments": [{"contents": {"count": 100, "card": "standard", "sleeving": "double"}}],
    "lid": {"kind": "lift_off", "height_mm": 15.0},
    "divider": {"thickness_mm": 1.4, "tab_width_mm": 20.0, "tab_height_mm": 10.0,
                "tab_position": "centre"},
    "process": {"fit_intent": "snug", "wall_mm": 2.4},
    "schema_version": 1,
}


def poke(path: str, value) -> dict:
    """`BASE` with one dotted path set to `value`."""
    assert path.startswith("spec."), path
    node = copy.deepcopy(BASE)
    cursor = node
    parts = path[len("spec."):].split(".")
    for part in parts[:-1]:
        indexed = re.fullmatch(r"(\w+)\[(\d+)\]", part)
        cursor = cursor[indexed.group(1)][int(indexed.group(2))] if indexed else cursor[part]
    cursor[parts[-1]] = value
    return node


def test_every_path_the_form_routes_by_is_one_the_schema_really_names():
    """The mapping is `{dotted path: control}`, and a key the schema never emits is a
    control that silently never shows its own refusal. Poked rather than eyeballed:
    each path is given a bad value and the problem has to come back naming it."""
    for path in field_by_path():
        named = False
        for bad in (-1, "nope", 0):
            try:
                OrganizerSpec.from_dict(poke(path, bad))
            except SpecError as exc:
                if path in {p["path"] for p in problems_with_paths(exc.problems)}:
                    named = True
                    break
        assert named, f"{path} is routed to a control but the schema never names it"


def test_an_explicit_null_wall_is_the_archetypes_default_and_stays_that_way():
    """The schema rule that made sending `null` the wrong client behaviour.

    `Process.wall_mm` documents explicit null as meaning the same as omitted — take
    `ARCHETYPE_WALL_MM[archetype]` — and that is deliberate: a spec file may state a
    wall or leave the archetype to choose. It is pinned here because it is the reason
    the form must not map an unparseable entry onto null, and a later "fix" that made
    null a refusal would silently make this the other kind of wrong.
    """
    spec = OrganizerSpec.from_dict(poke("spec.process.wall_mm", None))
    assert spec.process.wall_mm == ARCHETYPE_WALL_MM[spec.archetype]


def test_an_unparseable_millimetre_is_refused_by_name_on_every_field():
    """"2,4" is how a millimetre is written everywhere this product speaks.

    The form sends an entry it cannot parse as *the text that was typed*, so `_mm`
    answers `must be a number in mm, got '2,4'` against the field's own dotted path.
    It used to send `null`, which every mm field refused by name except
    `process.wall_mm`, where the schema reads null as "take the archetype default" —
    so that one keystroke resolved clean, showed a wall nobody asked for, and put no
    problem on the control that caused it.
    """
    for path in field_by_path():
        if not path.endswith("_mm"):
            continue
        with pytest.raises(SpecError) as caught:
            OrganizerSpec.from_dict(poke(path, "2,4"))
        named = {p["path"]: p["message"] for p in problems_with_paths(caught.value.problems)}
        assert path in named, f"{path} is not refused when it is sent as typed text"
        assert "2,4" in named[path], (
            f"{path} is refused as {named[path]!r}, which does not quote what was "
            "typed — the decimal separator is the thing the person has to see"
        )


def test_the_form_sends_unparseable_millimetres_as_typed():
    """The browser half of the rule above, read off the source.

    `optionalMm`/`requiredNumber` are the only two places a typed millimetre becomes
    JSON, and a `null` here is the behaviour that made `process.wall_mm` silent.
    """
    source = WEB_FORM.read_text(encoding="utf-8")
    for helper in ("optionalMm", "requiredNumber"):
        start = source.index(f"function {helper}(raw: string)")
        body = source[start:source.index("\n}", start)]
        decision = body.split("Number.isFinite")[-1]
        assert "raw.trim()" in decision, (
            f"{helper} no longer sends the typed text for an unparseable entry: "
            f"{decision.strip()!r}"
        )
        assert "null" not in decision, (
            f"{helper} sends null for an unparseable entry, which "
            "`Process.wall_mm` reads as 'take the archetype default'"
        )


def test_every_routed_control_exists_in_the_form():
    """The other direction: a path routed to a control the form does not render is a
    refusal with nowhere to appear."""
    tsx = WEB_FORM_TSX.read_text(encoding="utf-8")
    rendered = set(re.findall(r"byField\.(\w+)", tsx))
    routed = set(field_by_path().values())
    assert routed <= rendered, f"not rendered: {sorted(routed - rendered)}"
    # And the catch-all, without which an unrecognised path would be dropped in
    # silence and the submit button would just stop working.
    assert "form" in rendered


def test_an_unrouted_path_falls_to_the_form_rather_than_being_dropped():
    """The fallback is in the source, not in a reviewer's memory: `POST /jobs`
    validates more than the schema does, and a refusal only it can produce — a spec
    beside a requested size — must still reach the screen."""
    source = WEB_FORM.read_text(encoding="utf-8")
    assert "FIELD_BY_PATH[path] ?? 'form'" in source


# ── no number the browser made up ─────────────────────────────────────────────

def test_the_card_footprint_the_form_prints_is_the_dimension_tables():
    """The one millimetre figure the configurator states as prose. Everything else on
    screen arrives from `POST /organizer/resolve`; this note says what a `standard`
    card is, and it has to be what `CARD_KINDS` says it is."""
    card = CARD_KINDS["standard"]
    printed = f"{card.width_mm:g} × {card.height_mm:g} mm".replace(".", ",")
    assert printed in WEB_FORM_TSX.read_text(encoding="utf-8")


def test_the_form_carries_no_millimetre_defaults():
    """A blank field is sent *absent*, so the schema's own default is what comes back
    and appears. A default copied into the browser would be a second figure for the
    archetype's wall, drifting from the one the geometry is built with."""
    source = WEB_FORM.read_text(encoding="utf-8")
    block = re.search(r"export const DEFAULT_SPEC_FORM: SpecFormState = \{(.*?)\n\};", source, re.S)
    assert block, "could not find DEFAULT_SPEC_FORM"
    for field, value in re.findall(r"(\w+):\s*'([^']*)'", block.group(1)):
        if field.endswith("Mm"):
            assert value == "", f"{field} carries a millimetre default: {value!r}"


def test_every_archetype_gets_the_section_its_compiler_requires():
    """`deck_box.validate` refuses a spec with no `lid` and `card_divider.validate` one
    with no `divider` or a stray lid — and neither rule can run on the API server,
    because both modules import the geometry kernel. So a section the builder left out
    would not be a 422 the composer could show; it would be a failed Phase 2, ten
    seconds into a run that has already written a row."""
    source = WEB_FORM.read_text(encoding="utf-8")
    deck, divider = source.split("} else {", 1)
    deck = deck.rsplit("if (state.archetype === 'deck_box') {", 1)[1]
    assert "spec.lid =" in deck and "spec.process =" in deck
    assert "spec.divider =" in divider
    assert "spec.lid =" not in divider


def test_the_forms_opening_spec_compiles_for_every_archetype():
    """Pick an archetype, touch nothing, press send: that has to produce a part.

    The values come out of `DEFAULT_SPEC_FORM` rather than being written here, so the
    day somebody opens the form on 500 unsleeved cards this test compiles *that*. The
    shape is the one `specFromForm` is asserted to build above — every millimetre field
    blank, which means absent, which means the schema's own default.
    """
    from pythonsrc.organizer.archetypes import compile_spec  # needs the kernel

    form = dict(re.findall(
        r"(\w+):\s*'([^']*)'",
        re.search(
            r"export const DEFAULT_SPEC_FORM: SpecFormState = \{(.*?)\n\};",
            WEB_FORM.read_text(encoding="utf-8"), re.S,
        ).group(1),
    ))
    stack = {"count": int(form["count"]), "card": form["card"], "sleeving": form["sleeving"]}
    sections = {
        "deck_box": {"lid": {"kind": "lift_off"},
                     "process": {"fit_intent": form["fitIntent"]}},
        "card_divider": {"divider": {"tab_position": form["tabPosition"]}},
    }
    # Every archetype the engine has, so a third one cannot land without the form
    # being told which section it needs.
    assert set(sections) == set(ARCHETYPES)
    for archetype, extra in sections.items():
        spec = OrganizerSpec.from_dict({
            "archetype": archetype,
            "compartments": [{"contents": stack}],
            "schema_version": 1,
            **extra,
        })
        compile_spec(spec)  # raises SpecError if the archetype refuses it


def test_the_composer_submits_the_spec_it_composed():
    """The gap this whole issue is about: the strip reported its choice to UI
    telemetry and `createJob` had no `spec` field, so nothing a person did in the
    composer could ever reach `POST /jobs`."""
    source = WEB_NEW_JOB.read_text(encoding="utf-8")
    assert "specFromForm(" in source
    assert "startJob(prompt, composedSpec ?? undefined)" in source


def test_a_spec_is_never_submitted_beside_a_requested_size():
    """`POST /jobs` refuses the combination — `size_source` exists so the row can say
    who chose the size, and a request naming both makes it lie whichever way it
    answers — so the two are exclusive branches of one spread, not two optional keys."""
    source = WEB_NEW_JOB.read_text(encoding="utf-8")
    branch = re.search(r"\.\.\.\(spec\s*\n\s*\?\s*\{ spec \}\s*\n\s*:\s*\{(.*?)\n\s*\}\),", source, re.S)
    assert branch, "the spec and the size must be exclusive branches of one spread"
    for key in ("target_mm", "scale_axis", "size_source"):
        # Assignments only — the same words appear in the comments that explain them.
        sent = rf"^\s*{key}:"
        assert re.search(sent, branch.group(1), re.M), f"{key} is not sent in the no-spec branch"
        assert len(re.findall(sent, source, re.M)) == 1, (
            f"{key} is assigned somewhere a spec could be sent beside it"
        )


def test_the_composer_never_renders_a_fit_verdict():
    """`FitsCheck` takes a verdict or an explicit reason there is none, and before
    anything has been compiled the only honest argument is null. A composer that
    could pass a computed one would be computing it in a browser."""
    passed = set(re.findall(r"<FitsCheck\s+fits=\{([^}]*)\}", WEB_NEW_JOB.read_text(encoding="utf-8")))
    assert passed == {"null"}, f"the composer passes a fit verdict: {sorted(passed)}"
