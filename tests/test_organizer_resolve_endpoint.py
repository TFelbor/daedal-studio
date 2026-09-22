"""`POST /organizer/resolve` — the composer's arithmetic, done where the KB lives.

The form that composes a spec has to show the person what they are asking for before
they commit to it: the resolved card stack, the millimetres the schema filled in, and
every problem with the field it belongs to. Every one of those is a function of
`pythonsrc/organizer`, and a second copy of it in TypeScript would be a second copy of
the dimension KB — drifting from the one the geometry is built from, which is the
"confident number nobody computed" this product exists to refuse.

So this endpoint is the only source of the composer's numbers, and these tests are
about the three properties that makes it need:

- it runs in the api-server image, which installs neither trimesh nor manifold3d;
- it answers a half-built spec rather than erroring at it;
- it claims only what it checked — `schema_valid`, not `valid`.
"""
import ast
from pathlib import Path

from fastapi.testclient import TestClient

from pythonsrc.fit_offsets import (
    DEFAULT_FIT_OFFSETS,
    FIT_OFFSET_CLASSES,
    FIT_OFFSETS_VERSION,
)
from pythonsrc.organizer.box_kb import kb
from pythonsrc.organizer.dimensions import PITCH_MM_PER_CARD, resolve_stack
from pythonsrc.organizer.spec import FIT_INTENT_CLEARANCE_MM, OrganizerSpec, spec_hash
from server import app as app_module
from server.app import app

client = TestClient(app)

SPEC = {
    "archetype": "deck_box",
    "compartments": [{"contents": {"count": 100, "card": "standard", "sleeving": "double"}}],
    "lid": {"kind": "lift_off", "magnets": False, "height_mm": 15.0, "wall_mm": 1.2,
            "clearance_mm": 0.2, "top_mm": 2.0},
    "schema_version": 1,
}


def resolve(spec):
    resp = client.post("/organizer/resolve", json={"spec": spec})
    assert resp.status_code == 200, resp.text
    return resp.json()


# ── what comes back for a spec the schema accepts ─────────────────────────────

def test_it_answers_with_the_canonical_spec_and_its_hash():
    """The same two values `POST /jobs` would store, so the table under the form shows
    the millimetres the compiler will use rather than the blanks that were typed."""
    body = resolve(SPEC)
    assert body["schema_valid"] is True
    assert body["problems"] == []
    assert body["spec"] == OrganizerSpec.from_dict(SPEC).to_dict()
    assert body["spec_hash"] == spec_hash(OrganizerSpec.from_dict(SPEC))


def test_the_defaults_the_schema_resolved_are_in_the_answer():
    """A request that names no wall and no clearance means the schema's own figures by
    it, and those are numbers the person is entitled to see *before* submitting —
    2,4 mm is `ARCHETYPE_WALL_MM["deck_box"]` and 1,5 mm is the `snug` intent's."""
    bare = {"archetype": "deck_box",
            "compartments": [{"contents": {"count": 100}}],
            "lid": {}}
    body = resolve(bare)
    assert body["spec"]["process"]["wall_mm"] == 2.4
    assert body["spec"]["process"]["cavity_clearance_mm"] == 1.5
    assert body["spec"]["process"]["fit_intent"] == "snug"


def test_the_resolved_stack_is_the_dimension_modules_own_answer_with_its_basis():
    body = resolve(SPEC)
    expected = resolve_stack(100, "standard", "double")
    assert body["stacks"] == [{
        "count": 100,
        "card": "standard",
        "sleeving": "double",
        "footprint_w_mm": expected.footprint_w_mm,
        "footprint_h_mm": expected.footprint_h_mm,
        "pitch_mm": expected.pitch_mm,
        "stack_height_mm": expected.stack_height_mm,
        "basis": expected.basis,
    }]
    # The sum the fits line shows, checkable against the table it came from.
    assert body["stacks"][0]["stack_height_mm"] == round(100 * PITCH_MM_PER_CARD["double"], 3)
    assert "two measured 100-card stacks" in body["stacks"][0]["basis"]


def test_a_divider_resolves_the_same_stack_and_carries_no_lid():
    body = resolve({
        "archetype": "card_divider",
        "compartments": [{"contents": {"count": 40, "card": "standard", "sleeving": "single"}}],
        "divider": {},
    })
    assert body["schema_valid"] is True
    assert "lid" not in body["spec"]
    assert body["stacks"][0]["sleeving"] == "single"


TRAY = {
    "archetype": "token_tray",
    "compartments": [
        {"contents": {"width_mm": 20.0, "depth_mm": 20.0, "height_mm": 15.0, "source": None}}
    ] * 6,
    "tray": {"columns": 3},
    "schema_version": 1,
}


def test_a_token_tray_resolves_and_carries_no_stack_at_all():
    """A pocket's millimetres were typed, so there is nothing for `resolve_stack` to
    resolve and no `basis` sentence to print under it. An invented row here would put a
    figure with no source behind it on the exact readout that exists to carry one."""
    body = resolve(TRAY)
    assert body["schema_valid"] is True
    assert body["stacks"] == []
    assert body["spec"]["tray"] == {"columns": 3}
    assert "lid" not in body["spec"] and "divider" not in body["spec"]
    # The schema's own defaults came back, including this archetype's own wall.
    assert body["spec"]["process"]["wall_mm"] == 1.6


def test_a_bad_pocket_is_named_on_the_compartment_that_carries_it():
    body = resolve({**TRAY, "compartments": [
        {"contents": {"width_mm": "2,4", "depth_mm": 20.0, "height_mm": 15.0}},
    ]})
    assert body["schema_valid"] is False
    named = {p["path"]: p["message"] for p in body["problems"]}
    assert "2,4" in named["spec.compartments[0].contents.width_mm"]


def test_contents_that_are_neither_shape_are_refused_naming_both():
    body = resolve({**TRAY, "compartments": [{"contents": {}}]})
    assert body["schema_valid"] is False
    named = {p["path"]: p["message"] for p in body["problems"]}
    message = named["spec.compartments[0].contents"]
    assert "count" in message and "width_mm" in message


def test_no_fit_verdict_is_returned():
    """`deck_box.fits_check` imports manifold3d, which this image does not install, so
    there is nothing here that could honestly answer "does it fit". The only verdict
    this product shows is Phase 3's measurement of the exported mesh."""
    body = resolve(SPEC)
    assert "fits" not in body


# ── what comes back for a spec the schema refuses ─────────────────────────────

def test_a_refused_spec_is_a_200_with_every_problem_and_its_path():
    """A composer calls this while somebody is still typing. A half-built spec is a
    question, not an error."""
    body = resolve({
        "archetype": "deck_box",
        "compartments": [{"contents": {"count": 0, "card": "standard", "sleeving": "double"}}],
        "lid": {"clearance_mm": -1},
    })
    assert body["schema_valid"] is False
    assert body["spec"] is None and body["spec_hash"] is None and body["stacks"] == []
    paths = {p["path"] for p in body["problems"]}
    assert "spec.compartments[0].contents.count" in paths
    assert "spec.lid.clearance_mm" in paths
    for problem in body["problems"]:
        assert problem["message"].startswith(problem["path"] + " ")


def test_an_unknown_archetype_is_named_on_the_archetype_field():
    body = resolve(dict(SPEC, archetype="dice_tray"))
    assert body["schema_valid"] is False
    assert [p["path"] for p in body["problems"]] == ["spec.archetype"]


def test_an_empty_body_is_answered_rather_than_refused():
    resp = client.post("/organizer/resolve", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body["schema_valid"] is False
    assert body["problems"], "an empty spec must say what it is missing"


def test_schema_valid_does_not_claim_the_archetype_looked():
    """A deck box with no lid section passes the schema and is refused by
    `deck_box.validate` in Phase 2, which needs the kernel and cannot run here. The
    field is `schema_valid` so the answer does not claim a check nobody made."""
    body = resolve({"archetype": "deck_box",
                    "compartments": [{"contents": {"count": 100}}]})
    assert body["schema_valid"] is True
    assert "valid" not in body


# ── the label a spec job is titled with ───────────────────────────────────────

def test_the_label_describes_the_spec_and_nothing_else():
    body = resolve(SPEC)
    assert body["label"] == "deck box · 100 double-sleeved standard cards"


def test_the_label_is_derived_not_stored():
    """Every word in it is a field of the spec, so it cannot describe a different
    part than the one that will be compiled."""
    body = resolve(dict(
        SPEC,
        compartments=[{"contents": {"count": 60, "card": "standard", "sleeving": "none"}}],
    ))
    assert body["label"] == "deck box · 60 unsleeved standard cards"


def test_a_tray_is_titled_by_its_grid_rather_than_by_a_card_count_it_has_not_got():
    """`spec_label` would have read `contents.count` and said "None cards"; a
    compartment now holds a card stack *or* a pocket, and there are two sentences."""
    assert resolve(TRAY)["label"] == "token tray · 2 × 3 pockets 20 × 20 × 15 mm"


def test_a_tray_whose_columns_do_not_divide_is_titled_by_its_count():
    """The schema accepts it — the rule is `token_tray.validate`'s, and that needs the
    kernel — so the label must still be honest rather than printing a fractional grid."""
    body = resolve({**TRAY, "compartments": TRAY["compartments"][:5]})
    assert body["schema_valid"] is True
    assert body["label"] == "token tray · 5 pockets 20 × 20 × 15 mm"


INSERT = {
    "archetype": "box_insert",
    "compartments": [
        {"contents": {"count": 60, "card": "standard", "sleeving": "double"}},
        {"contents": {"width_mm": 40.0, "depth_mm": 40.0, "height_mm": 15.0, "source": None}},
        {"contents": {"width_mm": 20.0, "depth_mm": 20.0, "height_mm": 18.0, "source": None}},
    ],
    "insert": {"rows": [1, 2]},
    "schema_version": 1,
}


def test_an_insert_is_titled_by_every_compartment_rather_than_by_the_first():
    """The assumption issue #152 had to remove. `spec_label` read `compartments[0]` and
    described the whole part with it, which for an insert is a true sentence about one
    third of it — in the column a person scans to tell two jobs apart."""
    assert resolve(INSERT)["label"] == (
        "box insert · 3 compartments: 60 double-sleeved standard cards, "
        "40 × 40 × 15 mm, 20 × 20 × 18 mm"
    )


def test_an_insert_resolves_only_its_card_compartments():
    """`stacks` is "the card compartments, resolved", not one entry per compartment: a
    pocket's millimetres were typed and there is no `basis` sentence to print under one.
    An insert is the first spec where both kinds arrive together, so the rule is asserted
    on the case that can actually get it wrong."""
    body = resolve(INSERT)
    assert body["schema_valid"] is True
    assert len(body["stacks"]) == 1
    assert body["stacks"][0]["count"] == 60
    assert body["spec"]["insert"] == {"rows": [1, 2]}
    assert "tray" not in body["spec"] and "lid" not in body["spec"]
    # The schema's own defaults came back, including this archetype's own wall.
    assert body["spec"]["process"]["wall_mm"] == 1.6


def test_an_inserts_row_grouping_is_refused_on_its_own_path():
    """A bad row count is the schema's to refuse and it names the entry, so the composer
    can route it onto the control that caused it rather than onto the form."""
    body = client.post(
        "/organizer/resolve", json={"spec": {**INSERT, "insert": {"rows": [1, 0]}}}
    ).json()
    assert body["schema_valid"] is False
    assert any(p["path"] == "spec.insert.rows[1]" for p in body["problems"]), body["problems"]


# ── the curated box interiors ─────────────────────────────────────────────────

def test_the_curated_boxes_are_served_with_the_source_behind_each_number():
    """`GET /organizer/boxes` — the composer's picker, and the whole of what the KB buys.

    An interior with no provenance is the number this product refuses; the list is worth
    fetching precisely because each of its three axes carries a source and a date.
    """
    resp = client.get("/organizer/boxes")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["version"] == kb().version
    assert [box["id"] for box in body["boxes"]] == list(kb().ids)
    for box in body["boxes"]:
        assert len(box["interior_mm"]) == 3
        for axis in ("width", "depth", "height"):
            assert "https://" in box["provenance"][axis]
            assert "captured" in box["provenance"][axis]


def test_a_spec_naming_a_curated_box_resolves_with_its_provenance():
    body = resolve({**SPEC, "box": {"id": kb().ids[0]}})
    assert body["schema_valid"] is True
    entry = kb().get(kb().ids[0])
    assert body["spec"]["constraints"]["max_external_mm"] == list(entry.interior_mm)
    assert body["game_box"]["id"] == entry.id
    assert body["game_box"]["kb_version"] == kb().version
    assert body["game_box"]["resolved"] is True
    assert body["game_box"]["provenance"]["width"] == entry.width.provenance()


def test_a_spec_with_no_box_says_so_rather_than_leaving_the_field_out():
    """Null is the answer, not an omission: the composer has to be able to tell "typed"
    from "curated" to say which it used, and an absent key is indistinguishable from an
    older server that did not know about boxes."""
    body = resolve({**SPEC, "constraints": {"max_external_mm": [80.0, 70.0, 110.0]}})
    assert body["schema_valid"] is True
    assert body["game_box"] is None
    # And the margin came off anyway, which is the degraded mode's whole contract.
    assert body["spec"]["constraints"]["fit_margin_mm"] == 2.0


def test_a_box_nobody_has_curated_is_refused_on_its_own_path():
    """So the composer can put it under the picker rather than on the form."""
    body = resolve({**SPEC, "box": {"id": "no-such-game"}})
    assert body["schema_valid"] is False
    assert any(p["path"] == "spec.box.id" for p in body["problems"]), body["problems"]
    assert body["game_box"] is None


# ── the fit offsets the configured printer suggests (issue #89) ───────────────


def _with_profile(monkeypatch, profile):
    """Point `DEFAULT_PROFILE` at one profile, or at nothing.

    The composer asks this endpoint what its printer suggests, and the printer it means
    is the one a job submitted right now would slice against — `printer_status`'s
    `_ceiling` rule verbatim. There is no second one to mean, so there is no parameter.
    """
    monkeypatch.setattr(
        app_module.config_store, "get",
        lambda key, *a, **k: (profile if key == "DEFAULT_PROFILE" else None),
    )


def test_the_answer_carries_what_the_configured_printer_suggests(monkeypatch):
    """Issue #89's pre-fill, and the whole of where decision (b) happens.

    The profile is the *source the form is filled from*, so the offer has to arrive
    somewhere a browser can put it in a field — and this endpoint is the only place it
    can come from, for `resolve_stack`'s reason: a second copy of the sourced table in
    TypeScript would drift from the one the profile carries.
    """
    _with_profile(monkeypatch, "pythonsrc/profiles/ender3.json")
    fit = resolve(SPEC)["fit_defaults"]
    assert fit["profile"] == "pythonsrc/profiles/ender3.json"
    assert fit["printer"] == "Ender 3"
    assert fit["declared"] is True
    assert fit["fit_offsets_version"] == FIT_OFFSETS_VERSION
    assert fit["lid_clearance_mm"] == FIT_OFFSET_CLASSES["desktop"].lid_clearance_mm
    assert fit["stack_slack_mm"] == FIT_OFFSET_CLASSES["desktop"].stack_slack_mm
    assert fit["basis"]


def test_the_cavity_figure_is_already_summed_so_no_browser_adds_it_up(monkeypatch):
    """The endpoint's founding rule reaching a second table.

    A cavity clearance is the fit intent's own figure plus the machine's allowance. A
    client adding those two would be holding a copy of `FIT_INTENT_CLEARANCE_MM`, which
    is the drift this endpoint exists to refuse — so the sum is done here and the offset
    is beside it to be *shown*, not applied.
    """
    _with_profile(monkeypatch, "pythonsrc/profiles/ender3.json")
    offset = FIT_OFFSET_CLASSES["desktop"].cavity_clearance_offset_mm

    snug = resolve({**SPEC, "process": {"fit_intent": "snug"}})["fit_defaults"]
    assert snug["cavity_clearance_offset_mm"] == offset
    assert snug["cavity_clearance_mm"] == FIT_INTENT_CLEARANCE_MM["snug"] + offset

    easy = resolve({**SPEC, "process": {"fit_intent": "easy"}})["fit_defaults"]
    assert easy["cavity_clearance_mm"] == FIT_INTENT_CLEARANCE_MM["easy"] + offset


def test_the_offer_follows_the_fit_intent_rather_than_overruling_it(monkeypatch):
    """Why the profile carries an *offset* and not a whole cavity clearance.

    `fit_intent` is the word a person chooses between "a box I close" and "a tray I lift
    cards out of". A profile stating the clearance outright would silently overrule that
    word and leave the composer with a control that changes nothing.
    """
    _with_profile(monkeypatch, "pythonsrc/profiles/ender3.json")
    snug = resolve({**SPEC, "process": {"fit_intent": "snug"}})["fit_defaults"]
    easy = resolve({**SPEC, "process": {"fit_intent": "easy"}})["fit_defaults"]
    assert easy["cavity_clearance_mm"] > snug["cavity_clearance_mm"]


def test_a_tuned_profile_offers_the_schemas_own_numbers(monkeypatch):
    """The Bambu P1S is the one bundled profile in the `tuned` class, and it moves
    nothing for anybody already printing on one: its lid clearance is the low end of the
    sourced band, which is also the schema's default, and it asks no cavity allowance."""
    _with_profile(monkeypatch, "pythonsrc/profiles/bambu_p1s.json")
    fit = resolve(SPEC)["fit_defaults"]
    assert fit["lid_clearance_mm"] == FIT_OFFSET_CLASSES["tuned"].lid_clearance_mm
    assert fit["cavity_clearance_mm"] == FIT_INTENT_CLEARANCE_MM["snug"]


def test_no_printer_configured_is_answered_rather_than_left_null(monkeypatch):
    """The decision's explicit fourth point, and the reason this is never None.

    A composer that got null would have to know the fallback itself, in a browser, which
    is the one thing this endpoint exists to stop. The answer is the schema's own
    defaults with `declared: false` saying nobody was asked — the same millimetres a
    `tuned` profile offers, and a different fact.
    """
    _with_profile(monkeypatch, None)
    fit = resolve(SPEC)["fit_defaults"]
    assert fit["profile"] is None
    assert fit["declared"] is False
    assert fit["lid_clearance_mm"] == DEFAULT_FIT_OFFSETS.lid_clearance_mm
    assert fit["cavity_clearance_mm"] == FIT_INTENT_CLEARANCE_MM["snug"]
    assert "No printer is configured" in fit["basis"]


def test_a_profile_that_cannot_be_read_degrades_to_the_defaults(monkeypatch):
    """A missing profile is an ordinary tolerated condition here, as it is everywhere
    else that reads one: `POST /jobs` answers 202 for a `profile` naming nothing."""
    _with_profile(monkeypatch, "pythonsrc/profiles/no_such_printer.json")
    fit = resolve(SPEC)["fit_defaults"]
    assert fit["declared"] is False
    assert fit["lid_clearance_mm"] == DEFAULT_FIT_OFFSETS.lid_clearance_mm


def test_an_escaping_profile_path_offers_nothing_rather_than_being_honoured(monkeypatch):
    """`_ceiling`'s posture, and for its reason: `DEFAULT_PROFILE` is set through
    `PUT /config`, so a path leaving `pythonsrc/profiles` is a boundary this endpoint
    holds rather than an unauthenticated read of arbitrary JSON."""
    _with_profile(monkeypatch, "../../../etc/passwd")
    fit = resolve(SPEC)["fit_defaults"]
    assert fit["declared"] is False


def test_the_offer_is_answered_for_a_spec_the_schema_refuses(monkeypatch):
    """A spec is invalid for most of the time somebody is composing one, so a pre-fill
    that arrived only once it parsed would arrive after the fields it fills had been
    filled by hand. Everything else on the refusal branch is None or empty; this is not.
    """
    _with_profile(monkeypatch, "pythonsrc/profiles/ender3.json")
    body = resolve({**SPEC, "archetype": "no_such_archetype"})
    assert body["schema_valid"] is False
    assert body["spec"] is None
    assert body["fit_defaults"]["lid_clearance_mm"] == (
        FIT_OFFSET_CLASSES["desktop"].lid_clearance_mm
    )


def test_the_offer_is_never_the_specs_own_values(monkeypatch):
    """It records what the printer offers, never what the spec ended up with — the spec
    is its own record of that, in `spec` above, and a second copy here could disagree.

    A spec that overrules the offer still gets the offer back, unchanged: the composer
    needs to keep showing what a blank field would mean.
    """
    _with_profile(monkeypatch, "pythonsrc/profiles/ender3.json")
    spec = {**SPEC, "lid": {**SPEC["lid"], "clearance_mm": 0.9}}
    body = resolve(spec)
    assert body["spec"]["lid"]["clearance_mm"] == 0.9
    assert body["fit_defaults"]["lid_clearance_mm"] == (
        FIT_OFFSET_CLASSES["desktop"].lid_clearance_mm
    )


# ── the import rule this endpoint exists under ────────────────────────────────

def test_the_server_still_imports_nothing_that_needs_the_kernel():
    """The api-server image installs neither trimesh nor manifold3d (see
    `infra/docker/server.Dockerfile`). This endpoint reaches further into
    `pythonsrc.organizer` than anything before it, so the rule is asserted rather
    than remembered: no import of `archetypes` or `compiler`, at any depth.

    `box_kb` joined the set with the game-box KB (issue #154), under the same rule and
    for `dimensions`' reason verbatim: it is a table of sourced millimetres read off one
    committed JSON file, and it imports nothing outside the stdlib — which is also what
    makes "no BoardGameGeek client anywhere" a property this test can see."""
    tree = ast.parse(Path(app_module.__file__).read_text(encoding="utf-8"))
    modules = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    modules |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    organizer = {m for m in modules if m.startswith("pythonsrc.organizer")}
    assert organizer == {
        "pythonsrc.organizer",
        "pythonsrc.organizer.box_kb",
        "pythonsrc.organizer.dimensions",
    }
