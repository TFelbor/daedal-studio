"""Guards on the API server's logging configuration.

The server had none. `server/app.py` created a module logger and never configured
a handler, a level or a format, so under `uvicorn server.app:app` it inherited a
root logger uvicorn does not configure — default level WARNING. Every `logger.info`
in the application was discarded, and the warnings that did survive carried no
timestamp, so nothing could be placed against a job.

These pin the three properties that made it useless: the level is applied and is
settable from the environment, uvicorn's loggers share one stream and one format
instead of printing everything twice, and each request leaves exactly one line
whose severity follows the status code.
"""

import logging

import pytest
from fastapi.testclient import TestClient

from server.logging_config import (
    DEFAULT_LEVEL,
    LEVEL_COLOURS,
    NOISY_LOGGERS,
    ConsoleFormatter,
    configure_logging,
    is_high_frequency_path,
    resolve_level,
    should_colour,
)


@pytest.fixture(autouse=True)
def restore_logging():
    """Logging is process-global; put it back so test order cannot matter."""
    root = logging.getLogger()
    access = logging.getLogger("uvicorn.access")
    saved_handlers, saved_level = list(root.handlers), root.level
    saved_disabled = access.disabled
    yield
    root.handlers = saved_handlers
    root.setLevel(saved_level)
    access.disabled = saved_disabled


# ── Level resolution ─────────────────────────────────────────────────────────


def test_the_default_level_is_info(monkeypatch):
    monkeypatch.delenv("DS_LOG_LEVEL", raising=False)
    assert resolve_level() == logging.INFO
    assert DEFAULT_LEVEL == "INFO"


def test_the_level_comes_from_the_environment(monkeypatch):
    """A deployment must be able to go verbose without a code change."""
    monkeypatch.setenv("DS_LOG_LEVEL", "debug")
    assert resolve_level() == logging.DEBUG


def test_an_unrecognised_level_falls_back_instead_of_raising(monkeypatch):
    """A typo in an env var must not stop the server from booting."""
    monkeypatch.setenv("DS_LOG_LEVEL", "chatty")
    assert resolve_level() == logging.INFO


def test_an_explicit_argument_beats_the_environment(monkeypatch):
    monkeypatch.setenv("DS_LOG_LEVEL", "ERROR")
    assert resolve_level("WARNING") == logging.WARNING


# ── Handler installation ─────────────────────────────────────────────────────


def test_configuring_installs_exactly_one_root_handler_with_the_format():
    configure_logging("INFO", force=True)
    root = logging.getLogger()
    assert len(root.handlers) == 1
    assert isinstance(root.handlers[0].formatter, ConsoleFormatter)
    assert root.level == logging.INFO


def test_info_actually_survives_after_configuring():
    """The bug in one line: before this, `logger.info` went nowhere.

    Captured with a handler of our own rather than `caplog`, because configuring
    deliberately clears the root handlers — pytest's included — and that clearing is
    the thing keeping uvicorn from printing every line a second time.
    """
    configure_logging("INFO", force=True)

    written = []

    class Capture(logging.Handler):
        def emit(self, record):
            written.append(record.getMessage())

    logging.getLogger().addHandler(Capture())
    logging.getLogger("server.app").info("strategy resolved")

    assert "strategy resolved" in written


def test_reconfiguring_does_not_stack_duplicate_handlers():
    """uvicorn installs its own handlers on start; two means every line twice."""
    configure_logging("INFO", force=True)
    configure_logging("DEBUG", force=True)
    assert len(logging.getLogger().handlers) == 1


def test_uvicorn_loggers_share_the_one_handler():
    configure_logging("INFO", force=True)
    root_handler = logging.getLogger().handlers[0]
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uv = logging.getLogger(name)
        assert uv.handlers == [root_handler]
        # Left propagating *and* handled, each line prints twice.
        assert uv.propagate is False


def test_noisy_third_party_loggers_are_pinned_at_warning():
    """At DEBUG, `docker` and `httpx` log per request and bury the signal."""
    configure_logging("DEBUG", force=True)
    for name in NOISY_LOGGERS:
        assert logging.getLogger(name).level >= logging.WARNING


# ── Which paths are noise ────────────────────────────────────────────────────


@pytest.mark.parametrize("path", ["/health", "/config", "/feedback/pending", "/jobs/abc123"])
def test_polled_paths_are_treated_as_high_frequency(path):
    assert is_high_frequency_path(path) is True


@pytest.mark.parametrize(
    "path",
    ["/jobs", "/jobs/abc123/download", "/jobs/abc123/provenance", "/simulators/octoprint/start"],
)
def test_one_off_paths_are_not(path):
    """A sub-resource of a polled job is not itself polled, and is worth seeing."""
    assert is_high_frequency_path(path) is False


# ── The request log ──────────────────────────────────────────────────────────


@pytest.fixture
def logging_app():
    """A minimal app carrying only the middleware, so routes cannot skew the test."""
    from fastapi import FastAPI

    from server.app import log_requests

    app = FastAPI()
    app.middleware("http")(log_requests)

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.get("/jobs")
    def jobs():
        return []

    @app.get("/boom")
    def boom():
        raise RuntimeError("exploded")

    return app


def test_a_request_logs_one_line_with_status_and_duration(logging_app, caplog):
    with caplog.at_level(logging.INFO, logger="server.app"):
        TestClient(logging_app).get("/jobs")

    lines = [r for r in caplog.records if r.name == "server.app"]
    assert len(lines) == 1
    rendered = lines[0].getMessage()
    assert "GET /jobs" in rendered and "200" in rendered and "ms" in rendered
    assert lines[0].levelno == logging.INFO


def test_polled_endpoints_do_not_log_at_info(logging_app, caplog):
    """The job detail page polls every second; at INFO that is the whole log."""
    with caplog.at_level(logging.INFO, logger="server.app"):
        TestClient(logging_app).get("/health")
    assert [r for r in caplog.records if r.name == "server.app"] == []


def test_polled_endpoints_still_log_at_debug(logging_app, caplog):
    with caplog.at_level(logging.DEBUG, logger="server.app"):
        TestClient(logging_app).get("/health")
    records = [r for r in caplog.records if r.name == "server.app"]
    assert len(records) == 1
    assert records[0].levelno == logging.DEBUG


def test_an_unhandled_exception_is_logged_with_its_path_and_traceback(logging_app, caplog):
    """Without this a failing UI action left no server-side trace at all."""
    with caplog.at_level(logging.ERROR, logger="server.app"):
        with pytest.raises(RuntimeError):
            TestClient(logging_app).get("/boom")

    records = [r for r in caplog.records if r.name == "server.app"]
    assert len(records) == 1
    assert records[0].levelno == logging.ERROR
    assert "/boom" in records[0].getMessage()
    assert records[0].exc_info is not None


# ── Formatting and colour ────────────────────────────────────────────────────


def _render(levelname: str, *, colour: bool, message: str = "hello") -> str:
    record = logging.LogRecord(
        name="server.app", level=getattr(logging, levelname), pathname=__file__,
        lineno=1, msg=message, args=(), exc_info=None,
    )
    return ConsoleFormatter(colour=colour).format(record)


@pytest.mark.parametrize("levelname", ["DEBUG", "INFO", "WARNING", "ERROR"])
def test_the_level_column_is_padded_outside_the_brackets(levelname):
    """`[INFO   ]` reads as a stray tab; `[INFO]   ` reads as alignment."""
    rendered = _render(levelname, colour=False)
    assert f"[{levelname}]" in rendered
    assert f"[{levelname} " not in rendered


@pytest.mark.parametrize("levelname", ["DEBUG", "INFO", "WARNING", "ERROR"])
def test_the_logger_name_starts_at_the_same_column_for_every_level(levelname):
    """The point of the padding: the message column does not wander."""
    assert _render(levelname, colour=False).index("server.app:") == _render(
        "WARNING", colour=False
    ).index("server.app:")


def test_colour_marks_the_level_and_leaves_the_message_alone():
    rendered = _render("WARNING", colour=True)
    assert LEVEL_COLOURS["WARNING"] + "[WARNING]" in rendered
    # A message carrying its own escapes must not be able to bleed into the line.
    assert rendered.endswith("hello")


def test_colour_off_is_the_same_layout_without_the_escapes():
    """A redirected log and a terminal log must stay diffable."""
    assert "\033[" not in _render("INFO", colour=False)


def test_colour_follows_the_terminal_by_default(monkeypatch):
    monkeypatch.delenv("DS_LOG_COLOR", raising=False)
    monkeypatch.delenv("NO_COLOR", raising=False)

    class Tty:
        def isatty(self):
            return True

    class Pipe:
        def isatty(self):
            return False

    assert should_colour(Tty()) is True
    assert should_colour(Pipe()) is False


def test_no_color_and_the_explicit_switch_win_over_the_terminal(monkeypatch):
    class Tty:
        def isatty(self):
            return True

    monkeypatch.delenv("DS_LOG_COLOR", raising=False)
    monkeypatch.setenv("NO_COLOR", "1")
    assert should_colour(Tty()) is False

    monkeypatch.setenv("DS_LOG_COLOR", "always")
    assert should_colour(Tty()) is True

    monkeypatch.setenv("DS_LOG_COLOR", "never")
    assert should_colour(Tty()) is False


def test_an_exception_still_prints_its_traceback():
    try:
        raise RuntimeError("exploded")
    except RuntimeError:
        import sys as _sys

        record = logging.LogRecord(
            name="server.app", level=logging.ERROR, pathname=__file__, lineno=1,
            msg="boom", args=(), exc_info=_sys.exc_info(),
        )
    rendered = ConsoleFormatter(colour=False).format(record)
    assert "RuntimeError: exploded" in rendered
    assert "Traceback" in rendered


# ── One line per request, not two ────────────────────────────────────────────


def test_uvicorns_access_log_is_off_so_requests_are_not_logged_twice(monkeypatch):
    """`log_requests` supersedes it, and uvicorn logged polled paths back at INFO.

    Every request appeared twice, and demoting the polled endpoints to DEBUG was
    cancelled out by uvicorn logging the same request unconditionally.
    """
    monkeypatch.delenv("DS_UVICORN_ACCESS_LOG", raising=False)
    configure_logging("INFO", force=True)
    assert logging.getLogger("uvicorn.access").disabled is True


def test_uvicorns_access_log_can_be_switched_back_on(monkeypatch):
    """It carries the client address and HTTP version, which ours leaves out."""
    monkeypatch.setenv("DS_UVICORN_ACCESS_LOG", "1")
    configure_logging("INFO", force=True)
    assert logging.getLogger("uvicorn.access").disabled is False


def test_the_printer_status_poll_is_treated_as_noise():
    """The app shell polls it every 5s; it was the loudest line in the log."""
    assert is_high_frequency_path("/system/printer/status") is True
