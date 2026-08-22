"""The activity log's shape is load-bearing, so it is tested like an interface.

The whole point of the grammar is that the first column identifies the kind of line
without reading it: `·` one-liner, `┌` block, `═` phase boundary, `─` sub-step. If a
block edge wraps, or a long value pushes a rule past its width, that property is gone
and the log is back to being an undifferentiated wall.
"""

import pytest
from fastapi.testclient import TestClient

from server.activity import (
    GLYPH,
    WIDTH,
    ActivityLog,
    block,
    one,
    rule,
)
from server.app import app

client = TestClient(app)


# ── Shape ─────────────────────────────────────────────────────────────────────

def test_the_four_kinds_have_four_different_first_columns():
    """This is the property everything else rests on."""
    openers = {
        one("x")[0],
        block("t", [("k", "v")]).splitlines()[0][0],
        rule("t", heavy=True)[0],
        rule("t")[0],
    }
    assert len(openers) == 4


def test_a_rule_is_exactly_the_declared_width():
    assert len(rule()) == WIDTH
    assert len(rule("printability")) == WIDTH
    assert len(rule("phase 02 · sculptor", heavy=True)) == WIDTH


def test_a_long_title_cannot_push_a_rule_past_its_width():
    wide = rule("x" * 200, heavy=True)
    assert len(wide) == WIDTH
    assert "…" in wide


def test_a_block_never_wraps_however_long_the_value():
    rendered = block("job created", [("prompt", "y" * 500)])
    for line in rendered.splitlines():
        assert len(line) <= WIDTH, line


def test_block_rows_align_on_one_key_column():
    rendered = block("t", [("job", "a"), ("a much longer key", "b")]).splitlines()
    body = [ln for ln in rendered if ln.startswith(GLYPH["mid"])]
    assert len(body) == 2
    # The value column starts at the same offset on both rows.
    assert body[0].index("a") == body[1].rindex("b")


def test_a_none_value_reads_as_a_dash_not_as_the_word_none():
    rendered = block("t", [("seed", None), ("brand", "")])
    assert "None" not in rendered
    assert rendered.count("—") == 2


def test_the_outcome_closes_the_block_rather_than_following_it():
    """Cause and effect on one object, so concurrency cannot separate them."""
    rendered = block("t", [("k", "v")], outcome="queued", status="ok").splitlines()
    assert rendered[-1].startswith(GLYPH["close"])
    assert GLYPH["to"] in rendered[-1]
    assert GLYPH["ok"] in rendered[-1]


def test_a_block_with_no_outcome_still_closes():
    rendered = block("t", [("k", "v")]).splitlines()
    assert rendered[-1].startswith(GLYPH["close"])
    assert len(rendered[-1]) == WIDTH


@pytest.mark.parametrize("status,glyph", [("ok", "✔"), ("warn", "▲"), ("fail", "✖")])
def test_each_severity_has_its_own_mark(status, glyph):
    assert glyph in block("t", [], outcome="done", status=status)


# ── The feed ──────────────────────────────────────────────────────────────────

def test_the_feed_is_bounded():
    log = ActivityLog(capacity=3)
    for i in range(10):
        log.event(str(i))
    entries = log.recent()
    assert len(entries) == 3
    assert [e["text"] for e in entries] == [one("7"), one("8"), one("9")]


def test_sequence_numbers_keep_counting_past_the_capacity():
    """A client uses these to tell a quiet server from a dropped frame."""
    log = ActivityLog(capacity=2)
    for i in range(5):
        log.event(str(i))
    assert [e["seq"] for e in log.recent()] == [4, 5]


def test_subscribers_receive_records_and_can_unsubscribe():
    log = ActivityLog()
    seen = []
    stop = log.subscribe(seen.append)
    log.event("first")
    stop()
    log.event("second")
    assert [r.text for r in seen] == [one("first")]


def test_a_broken_subscriber_is_dropped_rather_than_raising():
    """A failed log panel must not be able to take a print job down."""
    log = ActivityLog()
    calls = []

    def bad(record):
        calls.append(record)
        raise RuntimeError("boom")

    log.subscribe(bad)
    log.event("one")   # raises internally, swallowed
    log.event("two")   # listener already removed
    assert len(calls) == 1
    assert len(log.recent()) == 2


# ── The endpoints ─────────────────────────────────────────────────────────────

def test_ui_events_reach_the_feed():
    res = client.post(
        "/activity/ui",
        json={"events": [{"action": "stage tab", "detail": "blueprint → mesh"}]},
    )
    assert res.status_code == 202
    assert res.json()["accepted"] == 1

    texts = [e["text"] for e in client.get("/activity").json()["entries"]]
    assert any("stage tab" in t and "blueprint → mesh" in t for t in texts)


def test_a_ui_batch_is_capped():
    res = client.post(
        "/activity/ui",
        json={"events": [{"action": f"a{i}"} for i in range(50)]},
    )
    assert res.status_code == 202
    assert res.json()["accepted"] == 50


def test_an_oversized_ui_batch_is_rejected_not_truncated_silently():
    res = client.post(
        "/activity/ui",
        json={"events": [{"action": f"a{i}"} for i in range(80)]},
    )
    assert res.status_code == 422


def test_the_activity_limit_is_clamped():
    assert client.get("/activity?limit=100000").status_code == 200
    assert client.get("/activity?limit=0").status_code == 200


def test_the_activity_socket_opens_with_a_backlog():
    client.post("/activity/ui", json={"events": [{"action": "backlog marker"}]})
    with client.websocket_connect("/ws/activity") as ws:
        first = ws.receive_json()
    assert first["type"] == "activity_batch"
    assert any("backlog marker" in e["text"] for e in first["data"])


def test_a_failed_mutation_is_never_suppressed_as_a_poll():
    """`/jobs/{id}` matches the polled-path heuristic; a DELETE against it is not a poll."""
    res = client.delete("/jobs/00000000-0000-0000-0000-000000000000")
    assert res.status_code == 404

    texts = [e["text"] for e in client.get("/activity").json()["entries"]]
    assert any("DELETE" in t and "404" in t for t in texts)


def test_a_polled_get_is_still_kept_out_of_the_feed():
    """The demotion must survive: the detail page polls this every second."""
    before = len(client.get("/activity").json()["entries"])
    client.get("/jobs/00000000-0000-0000-0000-000000000000")
    after = client.get("/activity").json()["entries"]
    assert not any("GET /jobs/00000000" in e["text"] for e in after)
    assert len(after) == before
