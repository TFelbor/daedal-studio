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
    """
    from pythonsrc.ip_screen import load_blocklist

    entries = load_blocklist()
    assert entries, "the blocklist is empty"
    for entry in entries:
        assert set(entry) <= {"term", "category", "aliases", "strength"}, entry
        assert entry.get("strength", "strong") in {"strong", "ambiguous"}, entry
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
