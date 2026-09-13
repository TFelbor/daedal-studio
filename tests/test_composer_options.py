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

Four bindings:

- every vocabulary the form offers is its Python counterpart, in order;
- every dotted path the form routes a refusal by is a path the schema really emits —
  poked, not assumed;
- the one input the schema *cannot* name — a tray's row count, which is derived from the
  compartment list rather than sent — is refused by the form itself, on its own control,
  and blocks the resolve and the submit;
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
#: Both card-archetype sections at once: the *schema* type-checks them and the
#: archetypes are what refuse the wrong one, and the archetypes need the kernel.
BASE = {
    "archetype": "deck_box",
    "compartments": [{"contents": {"count": 100, "card": "standard", "sleeving": "double"}}],
    "lid": {"kind": "lift_off", "height_mm": 15.0},
    "divider": {"thickness_mm": 1.4, "tab_width_mm": 20.0, "tab_height_mm": 10.0,
                "tab_position": "centre"},
    "process": {"fit_intent": "snug", "wall_mm": 2.4},
    "schema_version": 1,
}

#: The same, for the paths a token tray sends. It has to be a second base rather than
#: another section on the first: `Compartment.contents` is a `CardStack | Pocket` union
#: and the schema refuses a mapping carrying both, on purpose — so no single spec can
#: carry `contents.count` and `contents.width_mm` for one poke to reach.
TRAY_BASE = {
    "archetype": "token_tray",
    "compartments": [{"contents": {"width_mm": 20.0, "depth_mm": 20.0, "height_mm": 15.0}}],
    "tray": {"columns": 1},
    "process": {"wall_mm": 1.6},
    "schema_version": 1,
}

BASES = (BASE, TRAY_BASE)


def poke(base: dict, path: str, value):
    """`base` with one dotted path set to `value`, or None if it has no such path.

    None rather than a `KeyError`, because there are two bases and a caller sweeps both:
    `spec.lid.height_mm` does not exist in a tray and `spec.tray.columns` does not exist
    in a deck box, and *that* is a fact about the archetypes rather than a test failure.
    """
    node = copy.deepcopy(base)
    assert path.startswith("spec."), path
    cursor = node
    parts = path[len("spec."):].split(".")
    for part in parts[:-1]:
        indexed = re.fullmatch(r"(\w+)\[(\d+)\]", part)
        key, index = (indexed.group(1), int(indexed.group(2))) if indexed else (part, None)
        if key not in cursor:
            return None
        cursor = cursor[key][index] if index is not None else cursor[key]
    if parts[-1] not in cursor:
        return None
    cursor[parts[-1]] = value
    return node


def poked_problems(path: str, value) -> dict[str, str]:
    """`{path: message}` for every problem either base produces at `path` with `value`."""
    named: dict[str, str] = {}
    for base in BASES:
        node = poke(base, path, value)
        if node is None:
            continue
        try:
            OrganizerSpec.from_dict(node)
        except SpecError as exc:
            named.update({p["path"]: p["message"] for p in problems_with_paths(exc.problems)})
    return named


def test_every_path_the_form_routes_by_is_one_the_schema_really_names():
    """The mapping is `{dotted path: control}`, and a key the schema never emits is a
    control that silently never shows its own refusal. Poked rather than eyeballed:
    each path is given a bad value and the problem has to come back naming it."""
    for path in field_by_path():
        named = any(path in poked_problems(path, bad) for bad in (-1, "nope", 0))
        assert named, f"{path} is routed to a control but the schema never names it"


def test_every_routed_path_exists_in_one_of_the_bases():
    """The bases are what makes the test above mean anything: a path in neither of them
    is never poked at all, so it would pass by never being asked."""
    for path in field_by_path():
        assert any(poke(base, path, 1) is not None for base in BASES), (
            f"{path} is in no base spec, so nothing above ever pokes it"
        )


def test_an_explicit_null_wall_is_the_archetypes_default_and_stays_that_way():
    """The schema rule that made sending `null` the wrong client behaviour.

    `Process.wall_mm` documents explicit null as meaning the same as omitted — take
    `ARCHETYPE_WALL_MM[archetype]` — and that is deliberate: a spec file may state a
    wall or leave the archetype to choose. It is pinned here because it is the reason
    the form must not map an unparseable entry onto null, and a later "fix" that made
    null a refusal would silently make this the other kind of wrong.
    """
    for base in BASES:
        spec = OrganizerSpec.from_dict(poke(base, "spec.process.wall_mm", None))
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
        named = poked_problems(path, "2,4")
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
    assert re.search(r"FIELD_BY_PATH\[path\] \?\?.*\?\? 'form'", source, re.S), (
        "fieldForPath no longer ends in a 'form' fallback"
    )


def test_a_tray_routes_every_compartments_refusal_to_the_pocket_control():
    """A tray sends one identical pocket per cell, so the schema names the same problem
    once per compartment. Routing only `[0]` would put the other five on `form`, which
    is the panel's catch-all for *rules about the spec as a whole* — a legible place for
    one unrecognised sentence and a wall of noise for five copies of a recognised one.

    Read off the source rather than run, like everything else in this file: the index is
    flattened before the lookup, and the flattened message is what de-duplicates.
    """
    source = WEB_FORM.read_text(encoding="utf-8")
    assert "compartments\\[\\d+\\]" in source, (
        "nothing flattens a compartment index, so refusals about compartments[1..n] "
        "fall to `form` one by one"
    )
    assert "flattenCompartment(path)" in source
    # And the schema really does name every compartment, which is what makes it needed.
    spec = {**TRAY_BASE, "compartments": [{"contents": {"width_mm": None, "depth_mm": 20.0,
                                                       "height_mm": 15.0}}] * 2}
    with pytest.raises(SpecError) as exc:
        OrganizerSpec.from_dict(spec)
    paths = [p["path"] for p in problems_with_paths(exc.value.problems)]
    assert "spec.compartments[0].contents.width_mm" in paths
    assert "spec.compartments[1].contents.width_mm" in paths


# ── the one refusal the browser has to make itself ────────────────────────────

def local_field_by_path() -> dict[str, str]:
    """`LOCAL_FIELD_BY_PATH`: the paths only the form emits, and their controls."""
    return object_map(WEB_FORM.read_text(encoding="utf-8"), "LOCAL_FIELD_BY_PATH")


def function_body(source: str, signature: str) -> str:
    """One top-level TypeScript function, from its signature to the closing brace."""
    start = source.index(signature)
    return source[start:source.index("\n}", start)]


def test_no_dotted_path_can_ever_name_a_trays_row_count():
    """Why the form has to judge the grid itself, stated as the fact it rests on.

    `Tray` carries `columns` and nothing else — the rows are `len(compartments) //
    columns`, deliberately, so that a spec cannot state a grid its compartment list
    fails to fill. The consequence is that no 422 can ever name the row count, so a bad
    one has no server refusal coming and the control would sit there with nothing to
    show. If a `rows` field is ever added to the schema, this test is where to start.
    """
    from pythonsrc.organizer.spec import Tray

    assert not hasattr(Tray(columns=2), "rows")
    assert "rows" not in field_by_path().values(), (
        "a schema path now routes to the rows control; the local refusal may be "
        "redundant, but check which of the two the person sees before removing it"
    )


def test_a_blank_or_zero_row_count_is_refused_on_its_own_control():
    """The hole this closes: a blank, `0` or `2.5` row count used to become *one*
    compartment. With three columns that is a spec the schema accepts, the resolve
    reports clean and `token_tray.validate` refuses ten seconds into Phase 2; with one
    column it is a 1 × 1 tray, built and printed, for a grid nobody typed.

    Read off the source like everything else here, and in two halves: `wholeCount` is
    what makes blank, zero, negative and fractional all fail, and `localProblems` is
    what turns that into a problem on the control for *both* sides of the grid.
    """
    source = WEB_FORM.read_text(encoding="utf-8")

    counter = function_body(source, "function wholeCount(raw: string)")
    assert "if (!trimmed) return null;" in counter, "a blank row count is not refused"
    assert "Number.isInteger(value) && value >= 1" in counter, (
        "wholeCount no longer refuses 0, -1 and 2.5 as a grid side"
    )

    local = function_body(source, "export function localProblems(state: SpecFormState)")
    assert "['rows', 'Rows', state.rows]" in local
    assert "['columns', 'Columns', state.columns]" in local
    assert "if (wholeCount(raw) !== null) continue;" in local, (
        "localProblems no longer refuses every grid side wholeCount rejects"
    )
    assert "state.archetype !== 'token_tray'" in local, (
        "the grid refusal is not scoped to the archetype that has a grid"
    )


def test_a_refused_grid_sends_no_compartments_rather_than_one():
    """And if such a spec ever did reach the server, it is refused rather than built.

    Belt and braces, and the braces are the point: the composer neither resolves nor
    submits a locally refused spec, so this is about every *other* path to `POST /jobs`
    — the zoomed prompt, a future one. Zero compartments is a spec the schema stops;
    one compartment is a spec it accepts and is not the one that was asked for.
    """
    body = function_body(
        WEB_FORM.read_text(encoding="utf-8"), "function gridCells(rows: string",
    )
    assert "? 0 : r * c" in body, f"gridCells no longer collapses to no compartments: {body!r}"

    with pytest.raises(SpecError) as exc:
        OrganizerSpec.from_dict({**TRAY_BASE, "compartments": []})
    assert "at least one compartment" in str(exc.value)


def test_every_local_refusal_reaches_a_control_and_cannot_shadow_a_schema_path():
    """A local path is `form.<control>`, which no schema path can ever be, and it lands
    on a control the form renders — the same two promises `FIELD_BY_PATH` is held to,
    kept separately so that the poke test above stays a statement about the schema."""
    local = local_field_by_path()
    assert local, "the local map is empty; then it should not exist"
    routed = field_by_path()
    for path, field in local.items():
        assert path.startswith("form."), f"{path} is not in the local namespace"
        assert path not in routed, f"{path} is in both maps, so the routing is a coin flip"
        assert field == path[len("form."):], f"{path} routes to {field}, which it does not name"

    rendered = set(re.findall(r"byField\.(\w+)", WEB_FORM_TSX.read_text(encoding="utf-8")))
    assert set(local.values()) <= rendered, (
        f"not rendered: {sorted(set(local.values()) - rendered)}"
    )
    assert "LOCAL_FIELD_BY_PATH[path]" in WEB_FORM.read_text(encoding="utf-8"), (
        "fieldForPath does not consult the local map, so every local refusal is `form`"
    )


def test_a_locally_refused_spec_is_neither_resolved_nor_submitted():
    """The three doors, because a guard on two of three is none: the submit button, the
    Enter key, and `startJob`, which is the single `createJob` path and is what the
    zoomed prompt calls directly. Plus the resolve, which must not run either — asking
    the server what a grid nobody typed means would put its answer on screen."""
    source = WEB_NEW_JOB.read_text(encoding="utf-8")
    assert "localProblems({ ...specForm, archetype })" in source
    assert re.search(
        r"composedSpecJson = composedSpec === null \|\| localSpecProblems\.length", source,
    ), "a locally refused spec is still sent to /organizer/resolve"
    assert "localSpecProblems.length > 0 || resolved?.schema_valid === false" in source, (
        "the submit button is not disabled by a local refusal"
    )
    assert "&& !localSpecProblems.length" in source, (
        "the Enter key still submits a locally refused spec"
    )
    assert "if (spec && localSpecProblems.length) return;" in source, (
        "startJob, the single createJob path, does not refuse a locally refused spec"
    )
    assert re.search(r"mergeProblems\(\s*localSpecProblems", source), (
        "the local problems are not merged into what the form shows, so nothing appears"
    )


# ── no number the browser made up ─────────────────────────────────────────────

def test_the_card_footprint_the_form_prints_is_the_dimension_tables():
    """The one millimetre figure the configurator states as prose. Everything else on
    screen arrives from `POST /organizer/resolve`; this note says what a `standard`
    card is, and it has to be what `CARD_KINDS` says it is."""
    card = CARD_KINDS["standard"]
    printed = f"{card.width_mm:g} × {card.height_mm:g} mm".replace(".", ",")
    assert printed in WEB_FORM_TSX.read_text(encoding="utf-8")


def default_spec_form() -> dict[str, str]:
    """`DEFAULT_SPEC_FORM` as `{field: opening value}`, read off the source."""
    block = re.search(
        r"export const DEFAULT_SPEC_FORM: SpecFormState = \{(.*?)\n\};",
        WEB_FORM.read_text(encoding="utf-8"), re.S,
    )
    assert block, "could not find DEFAULT_SPEC_FORM"
    return dict(re.findall(r"(\w+):\s*'([^']*)'", block.group(1)))


def required_content_mm() -> list[str]:
    """The `REQUIRED_CONTENT_MM` literal: the mm fields the schema has no default for."""
    block = re.search(
        r"export const REQUIRED_CONTENT_MM: SpecField\[\] = \[(.*?)\];",
        WEB_FORM.read_text(encoding="utf-8"), re.S,
    )
    assert block, "could not find REQUIRED_CONTENT_MM"
    return re.findall(r"'([^']+)'", block.group(1))


def test_the_form_carries_no_millimetre_defaults():
    """A blank field is sent *absent*, so the schema's own default is what comes back
    and appears. A default copied into the browser would be a second figure for the
    archetype's wall, drifting from the one the geometry is built with.

    `REQUIRED_CONTENT_MM` is exempt, and the test below is what stops that being an
    escape hatch: the schema has no default for those, so a blank one is a missing
    value rather than "take yours", and opening blank would mean a token tray that
    cannot compile until somebody types three numbers — which the test after it forbids.
    """
    exempt = set(required_content_mm())
    for field, value in default_spec_form().items():
        if field.endswith("Mm") and field not in exempt:
            assert value == "", f"{field} carries a millimetre default: {value!r}"


def test_every_exempt_millimetre_field_is_one_the_schema_truly_requires():
    """The other half: a field may only open on a number if the schema refuses the spec
    without it. `process.wall_mm` could not be added to the list — the schema reads an
    omitted one as *take the archetype's default* — and that is the whole distinction.

    Poked rather than asserted from the field names: each one is removed from a tray's
    pocket and the schema has to call it missing.
    """
    exempt = required_content_mm()
    assert exempt, "the exemption list is empty; then it should not exist"
    for field in exempt:
        # `pocketWidthMm` → `width_mm`, the key the pocket carries.
        key = re.sub(r"^pocket", "", field)
        key = re.sub(r"(?<!^)(?=[A-Z])", "_", key).lower().replace("_mm", "") + "_mm"
        contents = {k: v for k, v in TRAY_BASE["compartments"][0]["contents"].items() if k != key}
        assert len(contents) == 2, f"{field} does not map onto a pocket key ({key!r})"
        with pytest.raises(SpecError) as exc:
            OrganizerSpec.from_dict({**TRAY_BASE, "compartments": [{"contents": contents}]})
        assert "missing a required field" in str(exc.value), (
            f"{field} is exempt from the blank rule but the schema defaults {key}"
        )


def test_every_archetype_gets_the_section_its_compiler_requires():
    """`deck_box.validate` refuses a spec with no `lid`, `card_divider.validate` one
    with no `divider` or a stray lid, and `token_tray.validate` one with no `tray` or a
    card-stack compartment — and none of those rules can run on the API server, because
    all three modules import the geometry kernel. So a section the builder left out
    would not be a 422 the composer could show; it would be a failed Phase 2, ten
    seconds into a run that has already written a row.

    Read as three branch bodies rather than by splitting on `} else {`, which stopped
    identifying anything the moment there were three of them.
    """
    source = WEB_FORM.read_text(encoding="utf-8")
    body = source.split("export function specFromForm(", 1)[1]
    tray, rest = body.split("if (state.archetype === 'token_tray') {", 1)[1].split(
        "spec.compartments = [", 1
    )
    deck, divider = rest.split("} else {", 1)
    deck = deck.rsplit("if (state.archetype === 'deck_box') {", 1)[1]

    assert "spec.tray =" in tray and "contents: { ...pocket }" in tray
    assert "count:" not in tray, "the tray branch sends a card stack"
    assert "spec.lid =" not in tray and "spec.divider =" not in tray

    assert "spec.lid =" in deck and "spec.process =" in deck
    assert "spec.divider =" in divider
    assert "spec.lid =" not in divider
    assert "spec.tray =" not in deck and "spec.tray =" not in divider


def test_the_forms_opening_spec_compiles_for_every_archetype():
    """Pick an archetype, touch nothing, press send: that has to produce a part.

    The values come out of `DEFAULT_SPEC_FORM` rather than being written here, so the
    day somebody opens the form on 500 unsleeved cards this test compiles *that*. The
    shape is the one `specFromForm` is asserted to build above — every *process*
    millimetre field blank, which means absent, which means the schema's own default,
    and the tray's pocket sent as the three numbers it opens on.
    """
    from pythonsrc.organizer.archetypes import compile_spec  # needs the kernel

    form = default_spec_form()
    stack = {"count": int(form["count"]), "card": form["card"], "sleeving": form["sleeving"]}
    pocket = {
        "width_mm": float(form["pocketWidthMm"]),
        "depth_mm": float(form["pocketDepthMm"]),
        "height_mm": float(form["pocketHeightMm"]),
    }
    cells = int(form["rows"]) * int(form["columns"])
    openings = {
        "deck_box": {
            "compartments": [{"contents": stack}],
            "lid": {"kind": "lift_off"},
            "process": {"fit_intent": form["fitIntent"]},
        },
        "card_divider": {
            "compartments": [{"contents": stack}],
            "divider": {"tab_position": form["tabPosition"]},
        },
        "token_tray": {
            "compartments": [{"contents": dict(pocket)} for _ in range(cells)],
            "tray": {"columns": int(form["columns"])},
        },
    }
    # Every archetype the engine has, so a fourth one cannot land without the form
    # being told which section and which compartments it needs.
    assert set(openings) == set(ARCHETYPES)
    for archetype, extra in openings.items():
        spec = OrganizerSpec.from_dict({
            "archetype": archetype, "schema_version": 1, **extra,
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
