"""The game-box dimension KB — the curated interiors, and the rules that keep them honest.

Issue #154. The claim this file exists to defend is narrow and load-bearing: **every
millimetre in `pythonsrc/data/game_boxes.v1.json` is checkable against the page it came
from, and a millimetre that is not cannot get in.** Everything below is one of the four
halves of that — the schema refuses an unsourced value, the launch set really carries
sources and dates, a compiled part records which entry and which version it was built
against, and a box nobody has measured degrades to typed millimetres that are *labelled*
as typed rather than quietly presented as sourced.

The fifth is the constraint the issue put on the whole task, and it is asserted rather
than remembered: **no network call to BoardGameGeek anywhere.** BGG carries external
dimensions only, user-entered, in inches, and its API is registration-gated under a
commercial licence. A forum thread in which somebody reports measuring their own copy is
a citation; the API is not touched.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from pythonsrc.organizer import box_kb
from pythonsrc.organizer.archetypes import compile_spec, example_spec
from pythonsrc.organizer.box_kb import (
    BASES,
    BOX_KINDS,
    KB_PATH,
    UNITS,
    BoxKB,
    BoxKBError,
    Measurement,
    kb,
    load_kb,
)
from pythonsrc.organizer.spec import (
    MM_DECIMALS,
    Constraints,
    GameBox,
    OrganizerSpec,
    SpecError,
    game_box_record,
)

ROOT = Path(__file__).resolve().parents[1]


# ── the version, pinned to the numbers under it ───────────────────────────────

#: The KB's content version and a digest of the entries beneath it, pinned together.
#:
#: A declared version nobody has to bump stops meaning anything the first time a
#: measurement is corrected in place — and a spec recording `box.kb_version` would then
#: name a version whose numbers are not the ones it was built from. So editing any entry
#: fails here until the version moves with it. The `tests/test_supabase_migration.py`
#: idiom: two things that must agree, and a test that is the only thing holding them.
KB_VERSION = "1"
KB_DIGEST = "96e30dd457eeeb66871d7e70b42407274e346c47094d61a36242968acd1e2ff3"


def test_the_declared_version_still_describes_the_entries_under_it():
    current = kb()
    assert current.version == KB_VERSION, (
        "the KB's content version moved; update KB_VERSION and KB_DIGEST here together"
    )
    assert current.content_sha256() == KB_DIGEST, (
        "an entry's numbers, sources or ids changed without the content version moving. "
        "Bump `version` in pythonsrc/data/game_boxes.v1.json and re-pin KB_DIGEST: a "
        "spec that recorded kb_version "
        f"{KB_VERSION!r} was built against the old numbers, and the version is the only "
        "thing that says so"
    )


# ── per-value provenance ──────────────────────────────────────────────────────

def test_every_axis_of_every_entry_carries_its_own_source_and_date():
    """Provenance is per *value*. A box whose width came off a caliper and whose height
    came off a product page is two claims, and one `source` on the entry would flatten
    them into one — the finding `Pocket.source` is already built on (issue #84)."""
    for entry in kb().entries:
        for axis, measurement in zip(box_kb.AXES, entry.measurements, strict=True):
            where = f"{entry.id}.{axis}"
            assert measurement.source.strip(), f"{where} has no source"
            assert measurement.basis in BASES, where
            assert measurement.units in UNITS, where
            assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", measurement.captured_on), where
            assert measurement.value_mm > 0, where


def test_every_source_is_a_citation_somebody_can_open():
    """"Somewhere on the internet" is not a source. Every launch entry cites a URL, which
    is what makes "checkable against the page it came from" true rather than aspirational."""
    for entry in kb().entries:
        for axis, measurement in zip(box_kb.AXES, entry.measurements, strict=True):
            assert measurement.source.startswith("https://"), (
                f"{entry.id}.{axis} cites {measurement.source!r}, which is not a URL"
            )


def test_every_entry_says_what_kind_of_box_it_is_and_who_makes_it():
    for entry in kb().entries:
        assert entry.kind in BOX_KINDS
        assert entry.name.strip()
        assert entry.publisher and entry.publisher.strip()


def test_the_launch_set_is_the_three_this_repository_can_source():
    """Small and defensible beats broad and unsourced (issue #154).

    Every number in the file is transcribed from a row of `docs/dimension-kb-research.md`
    that already names where it came from, and the rows that were *refused* — the
    Cloudflare-gated Printables listing §8 says to re-verify before shipping, and every
    BGG box-dimension row, which is external and in inches — are recorded in the data
    file rather than left as silent omissions. This pins the set so that broadening it is
    a decision somebody makes, not a drift.
    """
    assert kb().ids == (
        "wingspan", "ultimate-guard-boulder-100-plus", "decksmith-commander-box",
    )
    research = (ROOT / "docs" / "dimension-kb-research.md").read_text(encoding="utf-8")
    for entry in kb().entries:
        assert str(int(entry.height.value)) in research or f"{entry.height.value:g}" in research, (
            f"{entry.id}'s height is in no row of the research document"
        )


def test_the_refused_rows_are_recorded_where_somebody_would_look_for_them():
    """A row left out for a reason is a decision, and a decision nobody wrote down gets
    rediscovered as an omission. Both live in the data file's own comment."""
    comment = " ".join(json.loads(KB_PATH.read_text(encoding="utf-8"))["_comment"])
    assert "245516" in comment and "Cloudflare" in comment
    assert "BoardGameGeek" in comment or "BGG" in comment


# ── an entry with no source cannot be added ───────────────────────────────────

def one_measurement(**overrides) -> dict:
    base = {
        "value": 100.0,
        "units": "mm",
        "basis": "measured",
        "source": "https://example.invalid/thread",
        "captured_on": "2026-09-21",
    }
    base.update(overrides)
    return {k: v for k, v in base.items() if v is not ...}


def one_file(tmp_path: Path, **interior_overrides) -> Path:
    interior = {axis: one_measurement() for axis in box_kb.AXES}
    for axis, override in interior_overrides.items():
        interior[axis] = override
    path = tmp_path / "kb.json"
    path.write_text(json.dumps({
        "version": "test",
        "boxes": [{
            "id": "a-box", "name": "A box", "kind": "game_box",
            "publisher": "Nobody", "interior": interior,
        }],
    }), encoding="utf-8")
    return path


@pytest.mark.parametrize("bad", [
    pytest.param(one_measurement(source=...), id="source-missing"),
    pytest.param(one_measurement(source=""), id="source-blank"),
    pytest.param(one_measurement(source="   "), id="source-whitespace"),
])
def test_a_value_with_no_source_cannot_be_added(tmp_path, bad):
    """The acceptance criterion, as a refusal at load rather than as a review habit."""
    with pytest.raises(BoxKBError, match="source"):
        load_kb(one_file(tmp_path, depth=bad))


def test_a_rule_of_thumb_is_not_an_accepted_basis(tmp_path):
    """`folk` is the research document's fourth confidence word and is deliberately not a
    basis here: a rule of thumb about box walls is not a measurement of a box, and an
    insert compiled against one is the failure this KB exists to prevent."""
    with pytest.raises(BoxKBError, match="rule of thumb"):
        load_kb(one_file(tmp_path, width=one_measurement(basis="folk")))


def test_a_derived_interior_must_say_what_it_was_derived_from(tmp_path):
    """The issue's constraint verbatim: do not infer an interior from an exterior without
    saying so in the data. A derived value's whole meaning is the subtraction behind it."""
    with pytest.raises(BoxKBError, match="derived"):
        load_kb(one_file(tmp_path, height=one_measurement(basis="derived")))
    # And with the note it is accepted, so the rule is about the note and not about the
    # basis — deriving is supported, doing it silently is not.
    derived = one_measurement(basis="derived", note="exterior 300 mm less 2 × 7 mm wall")
    assert load_kb(one_file(tmp_path, height=derived)).entries[0].height.basis == "derived"


@pytest.mark.parametrize("bad, match", [
    ({"captured_on": "31-08-2026"}, "captured_on"),
    ({"captured_on": ...}, "captured_on"),
    ({"units": "cm"}, "units"),
    ({"value": 0}, "value"),
    ({"value": -3}, "value"),
    ({"value": "286"}, "value"),
])
def test_a_measurement_is_refused_field_by_field(tmp_path, bad, match):
    with pytest.raises(BoxKBError, match=match):
        load_kb(one_file(tmp_path, width=one_measurement(**bad)))


def test_an_unknown_field_is_refused_rather_than_ignored(tmp_path):
    """A typo in a field name must not silently become nothing — `from_dict`'s rule on
    the spec side, here for the same reason: `sourc` would be a row with no source."""
    with pytest.raises(BoxKBError, match="unknown field"):
        load_kb(one_file(tmp_path, width={**one_measurement(), "sourc": "x"}))


def test_the_source_units_are_kept_and_converted_in_code(tmp_path):
    """The number in the file is the number the source stated.

    A file holding 285,75 mm where the source says 11¼ inches cannot be diffed against
    anything, and the inch path exists because the box dimensions that are public are in
    inches — which is also why no entry may reach for them over the network.
    """
    inches = one_measurement(value=11.25, units="in")
    entry = load_kb(one_file(tmp_path, width=inches)).entries[0]
    assert entry.width.value == 11.25 and entry.width.units == "in"
    assert entry.width.value_mm == round(11.25 * 25.4, MM_DECIMALS) == 285.75
    assert "11.25 in" in entry.width.provenance()


def test_the_millimetre_precision_is_the_engines(tmp_path):
    """One place decides what "a millimetre" is worth, and `box_kb` must not be a second."""
    from pythonsrc.organizer import spec as spec_module

    assert box_kb.MM_DECIMALS == spec_module.MM_DECIMALS


def test_two_entries_cannot_share_an_id(tmp_path):
    path = tmp_path / "kb.json"
    one = {"id": "a-box", "name": "A", "kind": "game_box",
           "interior": {axis: one_measurement() for axis in box_kb.AXES}}
    path.write_text(json.dumps({"version": "t", "boxes": [one, dict(one)]}), encoding="utf-8")
    with pytest.raises(BoxKBError, match="two entries"):
        load_kb(path)


def test_an_id_that_would_not_survive_a_second_transcription_is_refused(tmp_path):
    """The id travels in every `spec_hash` that names it, so it may carry no case or
    whitespace a second person would get differently."""
    path = tmp_path / "kb.json"
    path.write_text(json.dumps({"version": "t", "boxes": [{
        "id": "A Box", "name": "A", "kind": "game_box",
        "interior": {axis: one_measurement() for axis in box_kb.AXES},
    }]}), encoding="utf-8")
    with pytest.raises(BoxKBError, match="lowercase"):
        load_kb(path)


def test_a_partial_interior_is_refused(tmp_path):
    path = tmp_path / "kb.json"
    path.write_text(json.dumps({"version": "t", "boxes": [{
        "id": "a-box", "name": "A", "kind": "game_box",
        "interior": {"width": one_measurement(), "depth": one_measurement()},
    }]}), encoding="utf-8")
    with pytest.raises(BoxKBError, match="height"):
        load_kb(path)


# ── the spec that names one ───────────────────────────────────────────────────

INSERT = {
    "archetype": "box_insert",
    "compartments": [{"contents": {"width_mm": 40.0, "depth_mm": 40.0, "height_mm": 15.0}}],
    "insert": {"rows": [1]},
    "schema_version": 1,
}


def test_naming_a_box_fills_the_limit_from_the_kb_and_records_the_version():
    spec = OrganizerSpec.from_dict({**INSERT, "box": {"id": "wingspan"}})
    assert spec.constraints.max_external_mm == kb().get("wingspan").interior_mm
    assert spec.box == GameBox(id="wingspan", kb_version=KB_VERSION)


def test_a_spec_naming_a_box_round_trips_exactly():
    """The property the whole schema is built on, through the new section: the canonical
    form states the millimetres the geometry is built from, so a KB correction produces a
    *different* spec rather than quietly reinterpreting a stored one."""
    spec = OrganizerSpec.from_dict({**INSERT, "box": {"id": "wingspan"}})
    assert OrganizerSpec.from_dict(spec.to_dict()) == spec


def test_an_unknown_game_is_refused_with_the_typed_path_named():
    with pytest.raises(SpecError) as exc:
        OrganizerSpec.from_dict({**INSERT, "box": {"id": "catan"}})
    message = "; ".join(exc.value.problems)
    assert message.startswith("spec.box.id")
    assert "max_external_mm" in message, (
        "the refusal for a box nobody has curated must name the typed path, which is the "
        "thing the person is meant to do instead"
    )


def test_a_spec_that_disagrees_with_the_entry_it_names_is_refused():
    with pytest.raises(SpecError, match="disagrees"):
        OrganizerSpec.from_dict({
            **INSERT, "box": {"id": "wingspan"},
            "constraints": {"max_external_mm": [280.0, 286.0, 72.0]},
        })


def test_a_spec_recorded_against_another_kb_version_still_loads():
    """A job compiled last month against an entry since corrected is a *record*. A schema
    that refused to load it would take the job page down with the correction."""
    spec = OrganizerSpec.from_dict({
        **INSERT, "box": {"id": "wingspan", "kb_version": "0"},
        "constraints": {"max_external_mm": [286.0, 286.0, 72.0]},
    })
    assert spec.box.kb_version == "0"
    assert spec.game_box_entry() is None, "no provenance may be claimed for a version we lack"
    assert game_box_record(spec) == {"id": "wingspan", "kb_version": "0", "resolved": False}


def test_a_spec_recorded_against_another_version_with_no_limit_is_refused():
    """The one case that cannot stand: nothing to build to, and nothing here can resolve it."""
    with pytest.raises(SpecError, match="kb_version"):
        OrganizerSpec.from_dict({**INSERT, "box": {"id": "wingspan", "kb_version": "0"}})


def test_the_box_section_moves_no_hash_of_a_spec_that_has_none():
    """`box` is an optional *section*, which is the only additive-safe change this schema
    has: an absent one is omitted from the canonical form rather than written as null."""
    plain = OrganizerSpec.from_dict(INSERT)
    assert "box" not in plain.to_dict()
    assert plain.box is None


@pytest.mark.parametrize("archetype", ["deck_box", "card_divider", "token_tray", "box_insert"])
def test_every_archetype_accepts_a_curated_box(archetype):
    """`spec.box` is archetype-agnostic and no archetype may refuse it. A deck box built
    to stand inside a commercial card case is the same claim as an insert built to fill a
    publisher's box, and the composer offers the control to all four on that basis."""
    example = example_spec(archetype)
    spec = OrganizerSpec.from_dict({
        **example.to_dict(),
        "box": {"id": "wingspan"},
        "constraints": {**example.to_dict()["constraints"], "max_external_mm": None},
    })
    assert spec.constraints.max_external_mm == kb().get("wingspan").interior_mm
    compile_spec(spec)


# ── what a compiled part records ──────────────────────────────────────────────

def test_a_compiled_part_records_which_entry_and_which_version():
    """The acceptance criterion. `features_document()` is what `pipeline.py` writes to
    `generation_params`, so this is the row in the database."""
    spec = OrganizerSpec.from_dict({**INSERT, "box": {"id": "wingspan"}})
    document = compile_spec(spec).features_document()
    recorded = document["game_box"]
    assert recorded["id"] == "wingspan"
    assert recorded["kb_version"] == KB_VERSION
    assert recorded["interior_mm"] == list(kb().get("wingspan").interior_mm)
    # And the provenance rides along, so a finished part can be audited back to the page
    # the measurement came from without the KB being consulted again.
    for axis in box_kb.AXES:
        assert "captured 2026-08-31" in recorded["provenance"][axis]


def test_a_part_built_to_typed_millimetres_records_no_box_at_all():
    """The omission is the point: a key implying a curated source on a part that has none
    would be the fabrication this KB exists to refuse, and every `compile_features.json`
    written before the KB existed stays byte-identical."""
    document = compile_spec(OrganizerSpec.from_dict(INSERT)).features_document()
    assert "game_box" not in document


# ── the degraded mode, and that it is the same arithmetic ─────────────────────

def test_an_unknown_game_falls_back_to_typed_dimensions_with_the_fit_margin():
    """The acceptance criterion: a box nobody has measured is typed, and
    `fit_margin_mm` still comes off every axis."""
    spec = OrganizerSpec.from_dict({
        **INSERT, "constraints": {"max_external_mm": [300.0, 200.0, 80.0]},
    })
    assert spec.box is None
    assert spec.constraints.fit_margin_mm == 2.0
    assert spec.constraints.effective_max_external_mm() == (298.0, 198.0, 78.0)


def test_the_fit_margin_comes_off_a_curated_interior_exactly_the_same():
    """A curated interior is still one copy of one box, measured once, and boxes flare
    ±1–2 mm between copies (`docs/dimension-kb-research.md` §7). The KB buys provenance,
    not permission to skip the margin — and a reading of this that quietly zeroed it for
    "measured" entries is the one that splits cardboard at the corners."""
    curated = OrganizerSpec.from_dict({**INSERT, "box": {"id": "wingspan"}})
    interior = kb().get("wingspan").interior_mm
    typed = OrganizerSpec.from_dict({
        **INSERT, "constraints": {"max_external_mm": list(interior)},
    })
    assert curated.constraints.effective_max_external_mm() == (
        typed.constraints.effective_max_external_mm()
    )
    assert curated.constraints.effective_max_external_mm() == tuple(
        round(v - 2.0, MM_DECIMALS) for v in interior
    )


def test_a_measured_box_can_still_be_taken_at_its_word():
    """`fit_margin_mm: 0` is documented as "I measured the box I am filling", and naming
    a KB entry must not take that away — the margin is the spec's decision either way."""
    spec = OrganizerSpec.from_dict({
        **INSERT, "box": {"id": "wingspan"}, "constraints": {"fit_margin_mm": 0},
    })
    assert spec.constraints.effective_max_external_mm() == kb().get("wingspan").interior_mm


# ── and the UI says which of the two it used ──────────────────────────────────

WEB_SPEC = ROOT / "web" / "src" / "organizer" / "spec.ts"
WEB_FORM = ROOT / "web" / "src" / "organizer" / "specForm.ts"
WEB_FORM_TSX = ROOT / "web" / "src" / "components" / "SpecForm.tsx"


def test_the_spec_table_names_the_source_or_says_the_number_was_typed():
    """The acceptance criterion's second half, read off the source the way every other
    UI-copy claim in this suite is.

    Two numbers that look identical in a table and are not the same kind of claim is the
    habit this product exists to break. `interiorNote` is the one place the distinction
    is drawn, and it is drawn per axis because provenance here is per value.
    """
    source = WEB_SPEC.read_text(encoding="utf-8")
    note = source[source.index("export function interiorNote("):]
    note = note[:note.index("\n}")]
    assert "typed interior" in note, "a typed interior is not labelled as typed"
    assert "provenance?.[axis]" in note, (
        "the curated branch does not reach the per-axis provenance sentence, so a KB row "
        "would show no more than a typed one"
    )
    assert "fit margin" in note, (
        "the interior row no longer says the margin comes off it — which it does whether "
        "the number was curated or typed"
    )
    # And every interior row goes through it, rather than one row at the top of three.
    assert source.count("interiorNote(") >= 2
    assert "'the finished part must fit inside this'" not in source.replace(note, ""), (
        "an interior row is still built with a hardcoded note, bypassing interiorNote"
    )


def test_the_composer_offers_both_paths_and_calls_the_unmeasured_one_normal():
    """A game not in the KB is the ordinary case, not an error: three curated boxes will
    never be every box that exists. So the typed fields are reachable without a failure
    first, and the option that leads to them is worded as a choice."""
    source = WEB_FORM_TSX.read_text(encoding="utf-8")
    assert "A box nobody has measured" in source
    for field in ("boxWidthMm", "boxDepthMm", "boxHeightMm", "boxId"):
        assert f"byField.{field}" in source, f"{field} has nowhere to show its refusal"
    assert "could not be loaded" in source, (
        "a missing curated list must say so on the control, not fail silently"
    )


def test_the_form_sends_the_entry_or_the_millimetres_and_never_both():
    """Exclusive by construction rather than by a rule somebody has to remember: the
    schema refuses a spec whose stated limit disagrees with the entry it names, and a
    form that sent both would be computing millimetres, which it does not do."""
    source = WEB_FORM.read_text(encoding="utf-8")
    body = source[source.index("function boxFromForm("):]
    body = body[:body.index("\n}")]
    assert "return { box: { id } }" in body
    assert "max_external_mm" in body
    # One `return` per branch, and the curated one returns before the typed one is built.
    assert body.index("return { box: { id } }") < body.index("max_external_mm")


# ── no BoardGameGeek client, anywhere ─────────────────────────────────────────

#: Every way this repository could reach the network, by import name.
_NETWORK_MODULES = {
    "requests", "httpx", "urllib", "urllib.request", "http", "http.client",
    "aiohttp", "socket", "ftplib", "xmlrpc",
}


def test_the_kb_reaches_no_network_at_all():
    """Curation, not a scrape. The KB reads one committed file and nothing else.

    Asserted off the import graph rather than by reading the code, because "it does not
    call anything today" is a weaker claim than "it cannot": a module that imports no
    HTTP client cannot acquire a BGG call in a later edit without this test seeing it.
    """
    tree = ast.parse(Path(box_kb.__file__).read_text(encoding="utf-8"))
    imported = {n.module.split(".")[0] for n in ast.walk(tree)
                if isinstance(n, ast.ImportFrom) and n.module}
    imported |= {a.name.split(".")[0] for n in ast.walk(tree)
                 if isinstance(n, ast.Import) for a in n.names}
    assert not imported & _NETWORK_MODULES, f"box_kb imports {imported & _NETWORK_MODULES}"


def test_nothing_in_the_tree_talks_to_the_boardgamegeek_api():
    """BGG carries external dimensions only, user-entered, in inches, and its API is
    registration-gated under a commercial licence (issue #154 §0.4). A *forum thread* in
    which somebody reports measuring their own copy is a citation like any other and is
    cited by the launch set; the API is what must not be touched.

    So the check is about the API's own endpoints and about *fetching* — not about the
    hostname, which would refuse the very sources this KB is built on, and not about the
    words "BGG API", which the research document uses to explain why there is no client.
    """
    endpoints = re.compile(r"boardgamegeek\.com/xmlapi2?|api\.geekdo\.com", re.I)
    fetching = re.compile(
        r"(requests\.|httpx\.|urlopen|aiohttp|fetch\(|curl\s)[^\n]*boardgamegeek"
        r"|boardgamegeek[^\n]*(requests\.|httpx\.|urlopen|aiohttp|fetch\()", re.I
    )
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in {".py", ".ts", ".tsx", ".json", ".md"}:
            continue
        if any(part in {".git", "node_modules", "dist", ".venv"} for part in path.parts):
            continue
        if path == Path(__file__):
            continue  # this file has to spell the endpoints out to look for them
        text = path.read_text(encoding="utf-8", errors="ignore")
        hit = endpoints.search(text)
        assert hit is None, f"{path.relative_to(ROOT)} names a BGG API endpoint: {hit.group(0)}"
        hit = fetching.search(text)
        assert hit is None, f"{path.relative_to(ROOT)} fetches BoardGameGeek: {hit.group(0)}"


# ── the loader's own edges ────────────────────────────────────────────────────

def test_an_unknown_id_is_none_rather_than_a_keyerror():
    """An unknown game is the degraded mode this KB is designed around, not an exception."""
    assert kb().get("no-such-box") is None
    assert kb().get(None) is None
    assert kb().get(7) is None


def test_the_file_is_read_once_per_process():
    assert kb() is kb()


def test_a_file_that_is_not_a_kb_is_refused(tmp_path):
    bad = tmp_path / "kb.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(BoxKBError, match="valid JSON"):
        load_kb(bad)
    bad.write_text(json.dumps({"version": "t", "boxes": []}), encoding="utf-8")
    with pytest.raises(BoxKBError, match="non-empty list"):
        load_kb(bad)
    bad.write_text(json.dumps({"boxes": [{}]}), encoding="utf-8")
    with pytest.raises(BoxKBError, match="version"):
        load_kb(bad)


def test_an_entry_serialises_back_to_what_it_was_read_from():
    """`to_dict` is what the content digest is taken over, so a field it dropped would be
    a field the version could stop describing."""
    raw = json.loads(KB_PATH.read_text(encoding="utf-8"))["boxes"]
    assert [entry.to_dict() for entry in kb().entries] == raw


def test_the_digest_ignores_the_version_and_notices_a_number(tmp_path):
    """Both halves of what the pin above promises."""
    one = BoxKB(version="a", entries=kb().entries)
    assert one.content_sha256() == BoxKB(version="b", entries=kb().entries).content_sha256()
    moved = load_kb(one_file(tmp_path))
    assert moved.content_sha256() != one.content_sha256()


def test_a_measurement_states_its_own_provenance_in_one_sentence():
    m = Measurement(value=72.0, units="mm", basis="measured",
                    source="https://example.invalid/t", captured_on="2026-08-31",
                    note="one copy")
    sentence = m.provenance()
    assert "72 mm" in sentence and "measured" in sentence
    assert "https://example.invalid/t" in sentence and "2026-08-31" in sentence
    assert "one copy" in sentence


def test_a_constraints_with_no_box_is_the_shape_this_schema_shipped_with():
    """The degraded mode is not a new code path — it is the old one, untouched."""
    assert Constraints().max_external_mm is None
    assert Constraints().fit_margin_mm == 2.0
