"""Sizes written in a prompt are offered to the requester, never applied for them.

"a 10cm tall vase" contains the answer to the question the composer is asking, and
retyping it is friction. But parsing it and applying it silently would make `prompt`
and `requested_size_mm` disagree about who decided — the same class of lie as a
fabricated capture. So the parser is a *prefill*: it proposes, the person accepts,
and only then does the row record `size_source="prompt_hint"`.

The unit is millimetres at the parser boundary, always. An imperial value is
converted where it is read and never stored, so no column downstream has to know
which unit it is in.
"""

import pytest

from pythonsrc.size_hint import parse_size_hint, strip_size_phrase

# ── Reading a size out of prose ───────────────────────────────────────────────

@pytest.mark.parametrize("prompt,mm", [
    ("a 10cm tall vase", 100.0),
    ("a 10 cm tall vase", 100.0),
    ("an 80mm dragon", 80.0),
    ("an 80 mm dragon", 80.0),
    ("a 0.15m bust", 150.0),
    ("a 2 inch figurine", 50.8),
    ("a 2in figurine", 50.8),
    ('a 2" figurine', 50.8),
    ("a 12 centimetre tower", 120.0),
    ("a 5 centimeters cube", 50.0),
])
def test_a_written_size_is_read_in_millimetres(prompt, mm):
    """Every recognised spelling lands on the same unit."""
    hint = parse_size_hint(prompt)
    assert hint is not None, f"no hint found in {prompt!r}"
    assert hint.mm == pytest.approx(mm, rel=1e-6)


@pytest.mark.parametrize("prompt", [
    "a low-poly fox",
    "a vase",
    "a dragon with 3 heads",          # a count, not a size
    "a d20 dice",                     # a name containing digits
    "a 1950s radio",                  # a year
])
def test_prose_without_a_size_yields_no_hint(prompt):
    """A number is not a size. A false prefill is worse than none, because the
    person has to notice and undo it."""
    assert parse_size_hint(prompt) is None


def test_the_matched_text_and_span_come_back_so_the_ui_can_show_them():
    """The composer highlights what it matched; a bare number is not reviewable."""
    hint = parse_size_hint("a 10cm tall vase")

    assert hint.text == "10cm"
    assert "a 10cm tall vase"[hint.span[0]:hint.span[1]] == hint.text


@pytest.mark.parametrize("prompt,axis", [
    ("a 10cm tall vase", "height"),
    ("a 10cm high tower", "height"),
    ("a 10cm wide plate", "longest"),
    ("a 10cm long bridge", "longest"),
    ("a 10cm vase", None),
])
def test_the_phrasing_says_which_axis_was_meant(prompt, axis):
    """"10cm tall" and "10cm wide" are different requests, and the words say which.

    None when the prose does not say — the caller then uses its own default rather
    than inventing an intent the sentence does not contain.
    """
    assert parse_size_hint(prompt).axis == axis


def test_an_absurd_size_is_not_offered():
    """Out-of-range values are dropped rather than proposed and then refused.

    The request model rejects anything above 1000mm, so offering 40m would prefill a
    control that cannot be submitted.
    """
    assert parse_size_hint("a 40m statue") is None
    assert parse_size_hint("a 0mm dot") is None


# ── Removing the phrase once it has become a parameter ────────────────────────

def test_the_size_phrase_is_removed_once_it_is_a_number_elsewhere():
    """A size expressed twice makes the render worse, not better.

    FLUX renders scale cues: asked for something small it will often add a hand or a
    coin for reference, and Phase 2's background remover then has two subjects and
    `_largest_component` picks by face count. Once the size is a parameter the phrase
    is redundant, so it is dropped from the text the model sees.
    """
    prompt = "a 10cm tall vase"
    hint = parse_size_hint(prompt)

    assert strip_size_phrase(prompt, hint) == "a tall vase"


def test_stripping_leaves_the_prompt_alone_when_there_was_no_hint():
    assert strip_size_phrase("a low-poly fox", None) == "a low-poly fox"


def test_vague_size_words_are_deliberately_left_in_place():
    """"small" is style, not measurement, and removing it edits the person's intent.

    A chibi figurine and a scaled-down realistic one are different models. The scale
    cue that "small" provokes is countered positively in the wrapper instead — see
    `test_blueprint_prompt.py` — because this checkpoint accepts no negative prompt.
    """
    assert strip_size_phrase("a small pikachu figurine", None) == "a small pikachu figurine"


# ── The server offers it and nothing more ─────────────────────────────────────

from unittest.mock import AsyncMock, patch  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from pythonsrc.telemetry.db import TelemetryDB  # noqa: E402
from server.app import app  # noqa: E402

client = TestClient(app)


def test_the_endpoint_offers_the_hint_it_found():
    """A dedicated endpoint, because a hint returned after submission is too late.

    The composer calls this as the person types, so the prefill happens before they
    press anything. Returning it in the POST /jobs response could only ever explain
    what already happened.
    """
    resp = client.post("/prompt/size-hint", json={"prompt": "a 10cm tall vase"})
    assert resp.status_code == 200

    hint = resp.json()["hint"]
    assert hint["mm"] == pytest.approx(100.0)
    assert hint["axis"] == "height"
    assert hint["text"] == "10cm"


def test_the_endpoint_says_nothing_when_there_is_nothing_to_say():
    resp = client.post("/prompt/size-hint", json={"prompt": "a low-poly fox"})

    assert resp.status_code == 200
    assert resp.json()["hint"] is None


@patch("server.app._run_pipeline", new_callable=AsyncMock)
def test_a_size_in_the_prompt_is_never_applied_by_itself(mock_run, printer_configured):
    """The one thing this feature must not do.

    Submitting a prompt that contains a size, with no size chosen, must record no
    size and no `prompt_hint` source. If this ever goes green the other way round,
    `prompt` and `requested_size_mm` have started disagreeing about who decided.
    """
    resp = client.post(
        "/jobs", json={"prompt": "a 10cm tall vase", "printer_id": "default"},
    )
    assert resp.status_code == 202

    db = TelemetryDB()
    job = db.get_job(resp.json()["job_id"])
    db.close()

    assert job.requested_size_mm is None
    assert job.size_source == "default"


@patch("server.app._run_pipeline", new_callable=AsyncMock)
def test_an_accepted_hint_is_recorded_as_a_hint(mock_run, printer_configured):
    """Accepting a suggestion is a third thing, distinct from typing and from neither."""
    resp = client.post("/jobs", json={
        "prompt": "a 10cm tall vase", "printer_id": "default",
        "target_mm": 100.0, "scale_axis": "height", "size_source": "prompt_hint",
    })
    assert resp.status_code == 202

    db = TelemetryDB()
    job = db.get_job(resp.json()["job_id"])
    db.close()

    assert job.requested_size_mm == pytest.approx(100.0)
    assert job.size_source == "prompt_hint"


@patch("server.app._run_pipeline", new_callable=AsyncMock)
def test_a_client_cannot_claim_a_source_for_a_size_it_did_not_send(mock_run, printer_configured):
    """`size_source` describes a value; with no value there is nothing to describe.

    The client is trusted to say whether a person typed the number or accepted a
    suggestion — it is the only party that knows. It is not trusted to assert
    provenance for a size that is absent.
    """
    resp = client.post("/jobs", json={
        "prompt": "a vase", "printer_id": "default", "size_source": "prompt_hint",
    })
    assert resp.status_code == 202

    db = TelemetryDB()
    job = db.get_job(resp.json()["job_id"])
    db.close()

    assert job.size_source == "default"
