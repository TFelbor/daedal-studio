"""The phase-banner protocol: the pipeline's only channel to the UI.

`pipeline.py` runs as a subprocess. It has no import relationship with the server, no
shared types and no RPC — it prints `[P2P] ═══ PHASE n START|PASS|FAIL … ═══` on stdout
and `server.app._stream_output` recognises those lines with a regular expression. Every
phase update the browser receives, the progress rail, the stage that advances from
blueprint to mesh to toolpath, and the Phase 5 hook that attaches the telemetry
collector, all hang off that match.

Which makes it the most fragile contract in the project and, until this file existed,
the only completely untested one. Reword a banner, drop the trailing `═══`, renumber a
phase, and the pipeline still runs to completion, still exits 0, still writes every
artifact — while the UI sits at "phase 01 pending" for the entire run and no test
anywhere goes red. The failure is invisible in a diff and total at runtime.

So these tests bind the two halves together: they generate banners with the real
emitters and parse them with the real parser. Neither side carries a copy of the other's
format, which is the only way the assertion means anything.
"""

import json
import re

import pytest

from pythonsrc import pipeline
from server.app import (
    PHASE_BANNER_RE,
    PHASE_BANNER_STATUS,
    PHASE_NAMES,
    _read_current_phase,
)

ALL_PHASES = (1, 2, 3, 4, 5)


def _banner_lines(capsys) -> list[str]:
    """Every `[P2P]` line the emitter under test just printed."""
    return [
        line for line in capsys.readouterr().out.splitlines() if line.startswith("[P2P]")
    ]


def _parse(line: str):
    """What the server would make of one line, or None if it ignores it."""
    match = PHASE_BANNER_RE.search(line)
    if match is None:
        return None
    return int(match.group(1)), match.group(2)


# ── The emitters produce what the parser recognises ──────────────────────────


@pytest.mark.parametrize("phase", ALL_PHASES)
def test_a_start_banner_is_parsed_as_that_phase_running(phase, capsys):
    pipeline._phase_start(phase)

    parsed = [_parse(line) for line in _banner_lines(capsys)]
    assert (phase, "START") in parsed, "the START banner did not match the server's regex"
    assert PHASE_BANNER_STATUS["START"] == "running"


@pytest.mark.parametrize("phase", ALL_PHASES)
def test_a_pass_banner_is_parsed_as_that_phase_complete(phase, capsys):
    pipeline._phase_pass(phase, start_time=0.0)

    parsed = [_parse(line) for line in _banner_lines(capsys)]
    assert (phase, "PASS") in parsed
    assert PHASE_BANNER_STATUS["PASS"] == "complete"


@pytest.mark.parametrize("phase", ALL_PHASES)
def test_a_fail_banner_is_parsed_as_that_phase_errored(phase, capsys):
    with pytest.raises(SystemExit):
        pipeline._phase_fail(phase, start_time=0.0, exc=RuntimeError("boom"))

    parsed = [_parse(line) for line in _banner_lines(capsys)]
    assert (phase, "FAIL") in parsed
    assert PHASE_BANNER_STATUS["FAIL"] == "error"


def test_a_pass_banner_survives_an_output_path(capsys):
    """`_phase_pass` interpolates the artifact path into the banner.

    Paths contain `/`, `.`, `-` and on a dev run the `dev-` prefix — the regex has to
    keep matching around whatever is spliced in, because this is the banner the UI
    reads to advance the stage.
    """
    pipeline._phase_pass(3, start_time=0.0, output_path="data/outputs/dev-abc123/engineered_mesh.obj")

    parsed = [_parse(line) for line in _banner_lines(capsys)]
    assert (3, "PASS") in parsed


def test_the_fail_banner_still_parses_when_the_exception_carries_banner_text(capsys):
    """A failure message is arbitrary text and must not be read as a second banner.

    Phase 2 raises with the blueprint path and backend name in the message; nothing
    stops one from containing the delimiter. The FAIL banner is printed before the
    ERROR line, so the phase the UI settles on has to be the real one.
    """
    with pytest.raises(SystemExit):
        pipeline._phase_fail(
            2, start_time=0.0, exc=RuntimeError("[P2P] ═══ PHASE 9 PASS  ✓ ═══")
        )

    parsed = [p for p in (_parse(line) for line in _banner_lines(capsys)) if p]
    assert parsed[0] == (2, "FAIL"), "the genuine banner must be the first match"


# ── Lines that must NOT be read as phase updates ─────────────────────────────


@pytest.mark.parametrize(
    "line",
    [
        "[P2P] ─── PRINTABILITY START ───",
        "[P2P] ─── PRINTABILITY DONE (1.2s) → data/outputs/j/printability.json ───",
        "[P2P] ─── PRINTABILITY SKIPPED (evaluation error) ───",
    ],
)
def test_the_printability_gate_is_not_a_phase(line):
    """It runs between Phases 3 and 4 and is deliberately not numbered.

    The `.status` protocol, the WebSocket phase updates and the progress bar all key
    off phases 1-5, so giving the gate a number would change what every historical
    `.status` file means. Its banners use a different rule (`───`, not `═══`) and must
    stay invisible to this parser — a match here would drive the rail to a phase that
    does not exist.
    """
    assert PHASE_BANNER_RE.search(line) is None


@pytest.mark.parametrize(
    "line",
    [
        "[P2P] Phase 3 duration: 6.1s",
        "[P2P] ERROR: something went wrong in PHASE 4 START",
        "[P2P] Blueprint seed: 12345",
        "[P2P] Sculptor backend: pixazo",
        "[P2P] TRACEBACK:",
    ],
)
def test_ordinary_pipeline_chatter_is_not_a_phase_update(line):
    """The pipeline prints far more `[P2P]` lines than banners.

    `Phase 3 duration:` follows every PASS and FAIL. If it matched, every completed
    phase would immediately be followed by a second, contradictory update.
    """
    assert PHASE_BANNER_RE.search(line) is None


def test_every_p2p_line_a_phase_emits_is_either_a_banner_or_inert(capsys):
    """No emitter may print a line whose status the server would guess at.

    The parser takes the *first* match in a line and applies it. A line that half
    matches is worse than one that does not match at all.
    """
    pipeline._phase_start(4)
    pipeline._phase_pass(4, start_time=0.0, output_path="data/outputs/j/engineered_mesh.gcode")

    matched = [line for line in _banner_lines(capsys) if PHASE_BANNER_RE.search(line)]
    assert len(matched) == 2, f"unexpected banner-shaped lines: {matched}"


# ── The two halves agree on names and statuses ───────────────────────────────


def test_the_server_and_the_pipeline_name_the_phases_identically():
    """Both sides carry their own map and the UI shows whichever arrives first.

    `pipeline._PHASE_NAMES` names the phase in the `.status` file the running view
    polls; `server.app.PHASE_NAMES` names it in the WebSocket message. They cannot be
    shared — importing the pipeline into the server would drag in the Phase 1 stack —
    so the only thing keeping them equal is this test.
    """
    assert PHASE_NAMES == pipeline._PHASE_NAMES


def test_the_parser_handles_every_phase_the_pipeline_knows_about():
    assert set(PHASE_NAMES) == set(ALL_PHASES)


def test_the_banner_verbs_and_the_status_words_are_closed_sets():
    """The regex alternation and the status map must name the same three verbs.

    A verb in one and not the other is either a banner nothing recognises or a
    `KeyError` in the middle of the log stream.
    """
    alternation = re.search(r"\(([A-Z|]+)\)", PHASE_BANNER_RE.pattern).group(1)
    assert set(alternation.split("|")) == set(PHASE_BANNER_STATUS)
    assert set(PHASE_BANNER_STATUS.values()) == {"running", "complete", "error"}


# ── The `.status` file is the same protocol, written down ────────────────────


def test_the_status_file_the_pipeline_writes_is_the_one_the_server_reads(tmp_path, monkeypatch):
    """A banner drives the live socket; `.status` is what survives a page reload.

    They have to agree: `GET /jobs/{id}` reports the last `.status` line as the current
    phase, so a status record the server cannot parse leaves a finished job showing a
    phase that never closed.
    """
    job_id = "banner-status-job"
    monkeypatch.setattr(pipeline, "CURRENT_JOB_ID", job_id)
    monkeypatch.setenv("P2P_LOGS_DIR", str(tmp_path))

    pipeline._write_status(2, "complete")

    record = json.loads((tmp_path / f"{job_id}.status").read_text().strip())
    assert record["phase"] == 2
    assert record["status"] == PHASE_BANNER_STATUS["PASS"]
    assert record["name"] == PHASE_NAMES[2].lower()
    assert "ts" in record


def test_a_failed_phase_records_its_reason_in_the_status_file(tmp_path, monkeypatch):
    job_id = "banner-status-fail"
    monkeypatch.setattr(pipeline, "CURRENT_JOB_ID", job_id)
    monkeypatch.setenv("P2P_LOGS_DIR", str(tmp_path))

    pipeline._write_status(4, "error", "CuraEngine exited 1")

    record = json.loads((tmp_path / f"{job_id}.status").read_text().strip())
    assert record["status"] == PHASE_BANNER_STATUS["FAIL"]
    assert record["error"] == "CuraEngine exited 1"


def test_the_status_file_is_append_only_and_the_last_line_wins(tmp_path, monkeypatch):
    """`_read_current_phase` takes the final line, so the file must accumulate.

    Truncating instead of appending would still make the endpoint work, and would
    quietly destroy the only per-phase timing record a finished job leaves behind.
    """
    job_id = "banner-status-append"
    monkeypatch.setattr(pipeline, "CURRENT_JOB_ID", job_id)
    monkeypatch.setenv("P2P_LOGS_DIR", str(tmp_path))

    pipeline._write_status(1, "complete")
    pipeline._write_status(2, "complete")
    pipeline._write_status(3, "running")

    lines = (tmp_path / f"{job_id}.status").read_text().strip().splitlines()
    assert len(lines) == 3
    assert json.loads(lines[-1])["phase"] == 3


def test_the_server_reads_the_last_record_the_pipeline_wrote(tmp_path, monkeypatch):
    """End to end across the two implementations, on the real reader.

    `_write_status` writes into `$P2P_LOGS_DIR`; `_read_current_phase` reads
    `data/logs/` relative to the repo. Pointing the writer at the reader's directory is
    what makes this a test of the format rather than of two unrelated files.
    """
    # `_read_current_phase` resolves `data/logs` relative to `server/app.py`.
    logs = tmp_path / "data" / "logs"
    logs.mkdir(parents=True)
    monkeypatch.setattr(pipeline, "CURRENT_JOB_ID", "banner-roundtrip")
    monkeypatch.setenv("P2P_LOGS_DIR", str(logs))

    pipeline._write_status(3, "running")
    pipeline._write_status(3, "complete")

    import server.app as app_module

    monkeypatch.setattr(app_module, "__file__", str(tmp_path / "server" / "app.py"))
    current = _read_current_phase("banner-roundtrip")

    assert current == {
        "phase": 3,
        "name": PHASE_NAMES[3].lower(),
        "status": "complete",
        "ts": current["ts"],
    }
