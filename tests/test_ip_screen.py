"""The prompt screen: what it refuses, what it merely flags, and what it must not do.

Two behaviours, because one would be wrong either way. A screen that only warns
protects nobody; a screen that refuses everything it half-recognises refuses paying
pilot users for asking about fan art. So:

- a **curated** name — a character or franchise on the list — is refused outright,
  before a job row exists;
- a **weak** signal is allowed through and *flagged*, so the human blueprint gate
  decides rather than a string comparison.

The refusal has to happen before `job_id` is minted, and specifically before the
artifact-cleanup loop in `create_job`, which unconditionally deletes the shared
`data/inputs/blueprint.png` and the flat mesh and G-code. A refusal after that point
destroys the previous job's artifacts to reject a job that never existed.
"""

import pytest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from pythonsrc.ip_screen import screen_prompt
from pythonsrc.telemetry.db import TelemetryDB
from server.app import app

client = TestClient(app)


# ── What the screener decides ─────────────────────────────────────────────────

@pytest.mark.parametrize("prompt", [
    "a small pikachu figurine",
    "PIKACHU",
    "a darth vader bust",
    "mario riding a kart",
    "an elsa figurine from frozen",
    "a space marine from warhammer 40k",
])
def test_a_named_character_or_franchise_is_refused(prompt):
    verdict = screen_prompt(prompt)

    assert verdict.action == "block", f"{prompt!r} was not blocked"
    assert verdict.term, "a block must name what it matched"


@pytest.mark.parametrize("prompt", [
    "a low-poly fox",
    "a hex bolt, M8",
    "a vase with a spiral pattern",
    "a chess knight",
    "a desk organiser with three slots",
])
def test_ordinary_prompts_are_allowed(prompt):
    """False positives cost more than a missed one here: the human gate is downstream."""
    assert screen_prompt(prompt).action == "allow"


@pytest.mark.parametrize("prompt", [
    "a pikchu figurine",         # one character dropped
    "a  P I K A C H U  toy",     # spaced out
    "a Pika-chu figurine",       # hyphenated
    "a pikachú figurine",        # accented
])
def test_obvious_evasions_are_still_caught(prompt):
    """A raw string comparison was already defeated once in this repo, by a
    `repo@sha` pin in the licensing guard. Normalise, then compare."""
    assert screen_prompt(prompt).action == "block", f"{prompt!r} slipped through"


def test_a_weak_signal_is_flagged_rather_than_refused():
    """"in the style of" is not a reproduction, and refusing it refuses a customer.

    It is recorded and shown at the blueprint gate, where a person decides — which is
    the whole reason that gate exists.
    """
    verdict = screen_prompt("a chunky yellow lightning-mouse figurine, anime style")

    assert verdict.action in {"allow", "flag"}
    if verdict.action == "flag":
        assert verdict.term


def test_a_refusal_explains_itself_and_offers_a_way_forward():
    """A bare 400 sends someone to support. A named term plus an alternative does not."""
    verdict = screen_prompt("a small pikachu figurine")

    assert "pikachu" in verdict.detail.lower()
    assert verdict.suggestion
    assert "pikachu" not in verdict.suggestion.lower()


def test_the_colour_field_is_screened_too():
    """`material_colour` is free text that reaches the model via the prompt wrapper.

    A screen that reads only `prompt` cannot see it, which makes the colour box a
    second, unwatched prompt channel.
    """
    assert screen_prompt("a vase", "red, official pikachu yellow").action == "block"


# ── Where the refusal happens ─────────────────────────────────────────────────

@patch("server.app._run_pipeline", new_callable=AsyncMock)
def test_a_blocked_prompt_never_creates_a_job(mock_run, printer_configured):
    db = TelemetryDB()
    before = db.query_one("SELECT COUNT(*) AS n FROM print_job")["n"]
    db.close()

    resp = client.post(
        "/jobs", json={"prompt": "a small pikachu figurine", "printer_id": "default"},
    )

    assert resp.status_code == 400
    assert "pikachu" in resp.json()["detail"].lower()

    db = TelemetryDB()
    after = db.query_one("SELECT COUNT(*) AS n FROM print_job")["n"]
    db.close()

    assert after == before
    mock_run.assert_not_called()


@patch("server.app._run_pipeline", new_callable=AsyncMock)
def test_a_refusal_does_not_delete_the_previous_jobs_artifacts(
    mock_run, printer_configured, tmp_path, monkeypatch,
):
    """`create_job` unconditionally unlinks the shared blueprint and flat artifacts.

    Refusing after that loop would destroy a previous job's output in order to reject
    a job that was never created — so the screen has to run before it.
    """
    from pathlib import Path

    import server.app as app_module

    repo_root = Path(app_module.__file__).parent.parent
    blueprint = repo_root / "data" / "inputs" / "blueprint.png"
    blueprint.parent.mkdir(parents=True, exist_ok=True)
    blueprint.write_bytes(b"previous job's blueprint")

    resp = client.post(
        "/jobs", json={"prompt": "a darth vader bust", "printer_id": "default"},
    )

    assert resp.status_code == 400
    assert blueprint.exists(), "the refusal ran after the artifact cleanup"
    assert blueprint.read_bytes() == b"previous job's blueprint"
    blueprint.unlink()


@patch("server.app._run_pipeline", new_callable=AsyncMock)
def test_a_flagged_prompt_is_recorded_against_the_job(mock_run, printer_configured, monkeypatch):
    """A flag has to be queryable, or "how often does this fire" is not a question.

    Recorded as a `job_event` rather than a column so the pilot's rate query needs no
    migration — and a *block* deliberately cannot be recorded that way, because
    foreign keys are enforced and no job row exists to attach it to.
    """
    import server.app as app_module
    from pythonsrc.ip_screen import ScreenVerdict

    monkeypatch.setattr(
        app_module, "screen_prompt",
        lambda *a, **k: ScreenVerdict(
            action="flag", term="lightning-mouse", score=0.7,
            detail="Weak resemblance signal.", suggestion=None,
        ),
    )

    resp = client.post("/jobs", json={"prompt": "a yellow mouse", "printer_id": "default"})
    assert resp.status_code == 202

    db = TelemetryDB()
    events = db.get_job_events(resp.json()["job_id"])
    db.close()

    assert any(e.kind == "ip_screen_flagged" for e in events), (
        f"no ip_screen_flagged event; got {[e.kind for e in events]}"
    )


def test_the_blocklist_is_data_and_carries_no_legal_advice():
    """It is a list of other people's trademarks living in a public repo.

    Descriptive only: names and a category, no assertions about what is or is not
    infringing. That judgement is not a JSON file's to make.

    The category is read by the usage rule now, not only by a person — an attributive
    `character` is refused and an attributive `franchise` is flagged — so a typo in it
    is a behaviour change and the vocabulary is closed.
    """
    from pythonsrc.ip_screen import load_blocklist

    entries = load_blocklist()
    assert entries, "the blocklist is empty"
    for entry in entries:
        assert set(entry) <= {"term", "category", "aliases", "strength"}, entry
        assert entry.get("strength", "strong") in {"strong", "ambiguous"}, entry
        assert entry.get("category") in {"brand", "character", "franchise"}, entry
        assert isinstance(entry["term"], str) and entry["term"]


# ── False positives are the expensive mistake ─────────────────────────────────
#
# A missed name is caught by the image screen and then by a person at the blueprint
# gate. A wrongly refused prompt is a paying pilot user told no, with no appeal and no
# explanation that makes sense to them. So the matcher has to be right about two
# separate things.
#
# **Word boundaries.** The first implementation used `term in normalised_prompt`, which
# is substring matching: "a marionette puppet" matched "mario", "a hulking stone golem"
# matched "hulk", "a wooden stitch marker" matched "stitch". Every one of those is an
# ordinary object someone would plausibly want printed.
#
# **Ambiguity is a property of the word, not of the match.** Some entries are also
# common English — a joker is a playing card, frozen is a temperature, a creeper is a
# vine. No amount of boundary precision fixes those, because the match is *correct* and
# the inference is wrong. They are marked ambiguous and flag for a human instead of
# refusing.

@pytest.mark.parametrize("prompt", [
    "a marionette puppet",          # contains "mario"
    "a hulking stone golem",        # contains "hulk"
    "a stitch pattern coaster",     # contains "stitch"
    "a wooden stitch marker",
    "a lego-compatible brick",      # a real, widely used descriptor
    "a creeper vine planter",       # a plant
    "a frozen yogurt cup holder",   # a temperature
    "a joker playing card holder",  # a playing card
    "a woody owl carving",          # an adjective
    "a sonic screwdriver",          # "sonic" alone is not the entry
    "a d20 dice holder",
])
def test_ordinary_objects_are_not_refused(prompt):
    """None of these may be blocked. Flagging is acceptable; refusing is not."""
    assert screen_prompt(prompt).action != "block", f"{prompt!r} was refused"


@pytest.mark.parametrize("prompt,term", [
    ("a bowser planter", "bowser"),
    ("a groot-shaped pot", "groot"),
    ("a totoro-like forest spirit", "totoro"),
    ("an optimus prime bust", "optimus prime"),
    ("a spongebob squarepants figure", "spongebob"),
])
def test_unambiguous_names_are_still_refused(prompt, term):
    """Fixing the false positives must not blunt the actual purpose."""
    verdict = screen_prompt(prompt)
    assert verdict.action == "block", f"{prompt!r} was not refused"
    assert verdict.term == term


@pytest.mark.parametrize("prompt", [
    "a joker playing card holder",
    "a frozen yogurt cup holder",
    "a creeper vine planter",
])
def test_an_ambiguous_word_is_flagged_for_a_person(prompt):
    """Correct match, wrong inference — so a human decides at the blueprint gate."""
    assert screen_prompt(prompt).action == "flag"


def test_an_ambiguous_word_with_a_franchise_cue_is_still_refused():
    """"joker" alone is a card; "the joker from batman" is not ambiguous at all."""
    assert screen_prompt("the joker from batman").action == "block"


# ── A functional article is not a reproduction ────────────────────────────────
#
# The screen was written for the figurine product, where a curated name meant "print
# me Pikachu". The parametric product's users name a franchise as the *contents* of
# the part they are ordering: "deck box for Pokémon cards" is the primary persona's
# literal prompt, and it was refused with score 1,0 while MTG, Yu-Gi-Oh!, Lorcana and
# One Piece passed by omission from the list — inconsistent, and worse than either
# consistent answer.
#
# So a match is classified on a second axis, *how* the name is used, and only for
# strong hits. A purpose cue governing the name ("for … cards", "fits 60 sleeved …")
# makes it functional and flags; a depiction cue in the same construction ("emblem",
# "figurine", "pokemon themed") blocks; neither leaves the category to decide, because
# "a Pikachu deck box" names its subject and "a Pokémon deck box" names its contents —
# and a franchise in front of something we do not make ("a star wars x-wing") names the
# subject too.
#
# A cue is scoped to its construction rather than to a window, and the tables below
# carry the counterexample for each direction: "for my son, a pikachu" is not a purpose
# (a bare "for" within six tokens governed the son, not the name) and "deck box for
# pokemon cards, lid on top" is not a depiction (a locational phrase within four tokens
# described the box, not a likeness).
#
# Both classes reach the human blueprint gate. Only one of them is refused there and
# then, with no appeal.

@pytest.mark.parametrize("prompt,term", [
    # The three prompts the issue names.
    ("deck box for Pokémon cards", "pokemon"),
    ("holds my Magic commander deck", "magic"),
    ("fits 60 sleeved Lorcana cards", "lorcana"),
    # The same rule, every franchise.
    ("a box that holds my yu-gi-oh deck", "yu-gi-oh"),
    ("card divider for my one piece collection", "one piece"),
    ("storage for flesh and blood boosters", "flesh and blood"),
    ("a tray that fits my warhammer tokens", "warhammer"),
    ("dividers for my star wars unlimited deck", "star wars"),
    ("a deck box for digimon cards", "digimon"),
    ("a binder page for my magic the gathering collection", "magic the gathering"),
    # A purpose cue five tokens ahead of the name still reaches it.
    ("fits 60 double sleeved standard lorcana cards", "lorcana"),
    # A depiction cue has to be part of the construction, not merely nearby: both of
    # these describe the *box's* own geometry, four words from the franchise name.
    ("deck box for pokemon cards, lid on top", "pokemon"),
    ("a box for pokemon cards shaped like a cube", "pokemon"),
    ("a tray for pokemon cards, cutout on the front", "pokemon"),
    # And the normaliser is the same normaliser.
    ("deck box for pokmon cards", "pokemon"),          # one character dropped
    ("deck box for P O K E M O N cards", "pokemon"),    # spaced out
    ("deck box for pokémon cards", "pokemon"),          # accented
    ("a deck box for Yu-Gi-Oh! cards", "yu-gi-oh"),     # punctuation
])
def test_a_name_used_for_what_the_part_holds_is_flagged_not_refused(prompt, term):
    """Flagged, never blocked: the job proceeds and a person sees the term."""
    verdict = screen_prompt(prompt)

    assert verdict.action == "flag", f"{prompt!r} was {verdict.action}ed"
    assert verdict.term == term
    assert verdict.usage == "functional", f"{prompt!r} read as {verdict.usage}"
    assert verdict.suggestion is None, "a flag is not a refusal and needs no rephrasing"


@pytest.mark.parametrize("prompt,term", [
    ("a pokemon deck box", "pokemon"),
    ("MTG commander deck box", "magic the gathering"),
    ("a lorcana card divider", "lorcana"),
])
def test_a_franchise_naming_the_contents_attributively_is_flagged(prompt, term):
    """"a Pokémon deck box" is the same order as "a deck box for Pokémon cards".

    A franchise or a brand in front of the article names what goes in it. A character
    in the same position names the subject, which is the test below.
    """
    verdict = screen_prompt(prompt)

    assert verdict.action == "flag", f"{prompt!r} was {verdict.action}ed"
    assert verdict.term == term
    assert verdict.usage == "attributive"


@pytest.mark.parametrize("prompt", [
    "a Pikachu figurine",
    "Charizard emblem on the lid",
    "a pikachu deck box",                                   # the subject, not the contents
    "eevee embossed on the front",
    "a charizard silhouette engraved on a deck box",
    "a deck box with a pikachu logo",
    "a box for pokemon cards with a pikachu figure on top",  # depiction beats purpose
    "a pikchu deck box",                                    # one character dropped
    "a P I K A C H U deck box",                             # spaced out
    "a bulbasaur shaped card holder",
    "a pokemon themed deck box",                            # livery, not contents
    # A purpose cue governs what follows *it*, not whatever name is within six
    # tokens. Both of these are a character as the subject with a "for" in front of
    # something else entirely, and `_normalise` has already deleted the comma that
    # separated the clauses — so proximity alone would have demoted every character
    # block to a flag, and any prompt could have been prefixed past this screen.
    "for my son, a pikachu",
    "print for me a darth vader",
    "a stand for my desk, an elsa figurine",
])
def test_a_name_used_for_what_the_part_depicts_is_still_refused(prompt):
    """The functional rule must not blunt the screen's actual purpose.

    Every one of these asks for a likeness of someone else's character, whether or
    not the object carrying it is a deck box.
    """
    verdict = screen_prompt(prompt)

    assert verdict.action == "block", f"{prompt!r} was not refused"
    assert verdict.term, "a block must name what it matched"
    assert verdict.usage in {"depiction", "attributive"}


@pytest.mark.parametrize("prompt,term", [
    ("a star wars x-wing", "star wars"),
    ("the mandalorian helmet", "mandalorian"),
    ("a hogwarts castle", "hogwarts"),
    ("a transformers robot", "transformers"),
    ("a zelda master sword", "zelda"),
    ("a warhammer 40k tank", "warhammer"),
    ("a minecraft pickaxe", "minecraft"),
    ("a nintendo switch dock", "nintendo"),
])
def test_a_franchise_naming_the_subject_is_still_refused(prompt, term):
    """A franchise is flagged for naming *contents*, not for being a franchise.

    "A Pokémon deck box" names what goes in the box. "A star wars x-wing" names the
    object itself, and that is a reproduction of someone else's design however the
    sentence is arranged — so the head noun after the name is what decides, and
    without one of ours the answer is the refusal it was before this rule existed.

    The appeal path is a rephrasing that says what the part is for, which the test
    below pins: "a dock for a Nintendo Switch" is flagged, not refused.
    """
    verdict = screen_prompt(prompt)

    assert verdict.action == "block", f"{prompt!r} was not refused"
    assert verdict.term == term
    assert verdict.usage == "attributive"


@pytest.mark.parametrize("prompt", [
    "a dock for a nintendo switch",
    "a stand for my star wars minis",
    "a tray for warhammer miniatures",
])
def test_the_same_subject_named_as_a_purpose_is_flagged(prompt):
    """The counterpart of the test above, and the reason it is not a dead end.

    The refusal text asks for the request in the person's own words; saying what the
    part is *for* is the rephrasing that gets there, and it reaches the human gate.
    """
    verdict = screen_prompt(prompt)

    assert verdict.action == "flag", f"{prompt!r} was {verdict.action}ed"
    assert verdict.usage == "functional"


@pytest.mark.parametrize("prompt,term", [
    ("a deck box for pokemon cards with a hulk-green lid", "pokemon"),
    ("a deck box for pokemon cards with a creeper vine engraved on the lid", "pokemon"),
])
def test_an_ambiguous_word_beside_a_functional_hit_is_not_promoted(prompt, term):
    """The promotion rule exists for "the joker from batman", not for this.

    An ambiguous word next to a strong hit is refused because the strong hit is
    itself a refusal — that is what makes the surrounding words unambiguous. A
    *functional* franchise is the one construction this screen accepts, so promoting
    on it refused a prompt over a colour name and a plant.
    """
    verdict = screen_prompt(prompt)

    assert verdict.action == "flag", f"{prompt!r} was {verdict.action}ed"
    assert verdict.term == term
    assert verdict.usage == "functional"


def test_promotion_still_fires_on_a_refusing_hit():
    """The other half: narrowing the trigger must not disarm it."""
    assert screen_prompt("the joker from batman").action == "block"
    assert screen_prompt("a space marine from warhammer 40k").action == "block"
    assert screen_prompt("a hulk figurine beside a pikachu").action == "block"


def test_every_franchise_on_the_list_gets_the_same_answer():
    """Consistency is the half of this the issue calls worse than either extreme.

    Pokémon was blocked and four comparable franchises passed unlisted. Whatever the
    verdict is for "deck box for X cards", it must be the same X by X — and it must
    not be a refusal, because that phrasing describes contents.
    """
    from pythonsrc.ip_screen import load_blocklist

    franchises = [e["term"] for e in load_blocklist() if e.get("category") == "franchise"]
    assert len(franchises) >= 20, "the franchise list shrank; this test is measuring nothing"

    refused = [t for t in franchises if screen_prompt(f"deck box for {t} cards").action == "block"]
    assert not refused, f"functional use of these franchises is refused: {refused}"


@pytest.mark.parametrize("prompt", [
    "a magic wand holder",       # magic is ordinary English
    "a one-piece lid",           # and so is a one-piece anything
    "a flesh coloured vase",
    "a deck box, 60 cards, three compartments",
])
def test_the_new_entries_do_not_refuse_ordinary_prompts(prompt):
    """The TCG names are on the list *for the flag*. Two of them are ordinary English
    and carry `strength: ambiguous` for exactly that reason."""
    assert screen_prompt(prompt).action != "block", f"{prompt!r} was refused"


def test_a_functional_flag_says_what_it_decided():
    """The detail is what a person reads at the gate, so it has to name the reason.

    "This prompt names X, which belongs to someone else" is the refusal's wording and
    would be a lie here — the job is going ahead.
    """
    verdict = screen_prompt("a deck box for pokemon cards")

    assert "pokemon" in verdict.detail.lower()
    assert "for" in verdict.detail.lower()
    assert "cannot" not in verdict.detail.lower()


def test_the_cues_are_already_normalised():
    """A cue with an accent, a capital or a hyphen in it can never match.

    The tokens they are compared against have been through `_normalise`; a cue that
    has not is dead weight nothing would report.
    """
    from pythonsrc import ip_screen

    cues = (
        ip_screen.DEPICTION_CUES + ip_screen.PURPOSE_CUES
        + ip_screen.POSSESSIVE_CUES + ip_screen.CONTENTS_NOUNS
        + ip_screen.ARTICLE_NOUNS + ip_screen.BRIDGE_TOKENS
    )
    for cue in cues:
        assert ip_screen._normalise(cue) == cue, cue


def test_the_cues_read_as_single_tokens_are_single_tokens():
    """Three of the cue sets are compared by token membership, not as phrases.

    A depiction noun is looked for anywhere in the window, a trailing cue is the one
    token after the name, and a bridge is one token at a time — so a multi-word entry
    in any of them would never match anything and nothing would report it. The
    phrase-matched sets (`DEPICTION_LEADING`, `PURPOSE_CUES`) are deliberately not
    here: those go through `_find_phrases` and may be multi-word.
    """
    from pythonsrc import ip_screen

    single = (
        ip_screen.DEPICTION_NOUNS + ip_screen.DEPICTION_TRAILING
        + ip_screen.BRIDGE_TOKENS + ip_screen.ARTICLE_NOUNS
        + ip_screen.CONTENTS_NOUNS + ip_screen.POSSESSIVE_CUES
    )
    for cue in single:
        assert " " not in cue, f"{cue!r} is read as one token and can never match"


@patch("server.app._run_pipeline", new_callable=AsyncMock)
def test_the_primary_personas_prompt_reaches_the_gate(mock_run, printer_configured):
    """End to end through the real screen: the job is created, and the flag is on it.

    The whole point of the re-scope is that this prompt produces a job. The event is
    the appeal path — it carries the term and now the usage, so "how often does the
    functional rule fire" is a query rather than a log grep.
    """
    resp = client.post(
        "/jobs", json={"prompt": "deck box for Pokémon cards", "printer_id": "default"},
    )
    assert resp.status_code == 202, resp.text

    db = TelemetryDB()
    events = db.get_job_events(resp.json()["job_id"])
    db.close()

    flagged = [e for e in events if e.kind == "ip_screen_flagged"]
    assert flagged, f"no ip_screen_flagged event; got {[e.kind for e in events]}"
    assert flagged[0].detail["term"] == "pokemon"
    assert flagged[0].detail["usage"] == "functional"


@patch("server.app._run_pipeline", new_callable=AsyncMock)
def test_a_depiction_is_still_refused_at_the_boundary(mock_run, printer_configured):
    """The other half: a franchise in a for-phrase is not a licence for the rest."""
    resp = client.post(
        "/jobs",
        json={
            "prompt": "a deck box for pokemon cards with a charizard emblem on the lid",
            "printer_id": "default",
        },
    )

    assert resp.status_code == 400
    assert "charizard" in resp.json()["detail"].lower()
    mock_run.assert_not_called()
