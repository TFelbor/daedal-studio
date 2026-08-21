"""Logging configuration for the API server.

Before this module the server had none. `server/app.py` is ~1,900 lines with a
`logging.getLogger(__name__)` at the top and no handler, no level and no format
anywhere — so under `uvicorn server.app:app` the app's own logger inherited a root
logger uvicorn never configures, whose default level is WARNING. Every
`logger.info` in the codebase was discarded, including the one that reports which
execution strategy a job resolved to; the `logger.warning` calls that did survive
arrived without a timestamp, so nothing could be correlated with a job.

Four things are configured here:

- **A root handler with a real format**, so a line says when it happened, how bad
  it is and which module emitted it — with the severity carried in colour when the
  output is a terminal, because a warning buried in a wall of INFO is not findable
  by eye.
- **Uvicorn's own loggers reattached to it**, so its lines and the application's
  share one stream and one format instead of two.
- **Uvicorn's access log switched off**, because `log_requests` already logs every
  request and knows things uvicorn does not — how long it took, and which paths are
  polled and therefore noise. Left on, every request appeared twice and the demotion
  of polled endpoints to DEBUG was cancelled out by uvicorn logging them at INFO.
- **Noisy third-party loggers pinned to WARNING.** `docker`, `httpx` and
  `websockets` each log per-request at DEBUG/INFO; at DEBUG they bury the signal.

Levels come from `$P2P_LOG_LEVEL`, colour from `$P2P_LOG_COLOR` / `$NO_COLOR`, and
uvicorn's access log can be restored with `$P2P_UVICORN_ACCESS_LOG=1` — so a running
deployment can be made verbose, or plain, without a code change.
"""

from __future__ import annotations

import logging
import os
import sys

DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

DEFAULT_LEVEL = "INFO"

#: Width the bracketed level is padded to, so the logger-name column lines up.
#: The padding goes *outside* the brackets: `%(levelname)-7s` puts it inside, and
#: `[INFO   ]` reads as a stray tab rather than as alignment.
LEVEL_FIELD_WIDTH = len("[WARNING]")

#: SGR codes. INFO green and WARNING yellow follow uvicorn's own convention, so a
#: mixed stream does not change meaning halfway down.
RESET = "\033[0m"
DIM = "\033[2m"
LEVEL_COLOURS = {
    "DEBUG": "\033[90m",     # grey — present but recessive
    "INFO": "\033[32m",      # green
    "WARNING": "\033[33m",   # yellow
    "ERROR": "\033[31m",     # red
    "CRITICAL": "\033[1;97;41m",  # bold white on red
}


class ConsoleFormatter(logging.Formatter):
    """Renders one log line, optionally with colour.

    Colour carries the severity, so a warning is findable by eye in a stream that is
    otherwise all INFO. Only the level token is coloured; the timestamp and logger
    name are dimmed so the message itself stays the brightest thing on the line, and
    the message is left uncoloured so payloads containing their own escapes cannot
    bleed into it.

    With colour off the layout is byte-for-byte the same minus the escapes, so a
    redirected log and a terminal log stay diffable.
    """

    def __init__(self, *, colour: bool):
        super().__init__(datefmt=DATE_FORMAT)
        self.colour = colour

    def format(self, record: logging.LogRecord) -> str:
        stamp = self.formatTime(record, self.datefmt)
        level = f"[{record.levelname}]"
        pad = " " * max(1, LEVEL_FIELD_WIDTH - len(level) + 1)
        name = f"{record.name}:"
        message = record.getMessage()

        if self.colour:
            colour = LEVEL_COLOURS.get(record.levelname, "")
            stamp = f"{DIM}{stamp}{RESET}"
            level = f"{colour}{level}{RESET}"
            name = f"{DIM}{name}{RESET}"

        line = f"{stamp} {level}{pad}{name} {message}"

        if record.exc_info:
            line = f"{line}\n{self.formatException(record.exc_info)}"
        if record.stack_info:
            line = f"{line}\n{self.formatStack(record.stack_info)}"
        return line


def should_colour(stream=None) -> bool:
    """Decide whether to emit ANSI colour.

    `$NO_COLOR` (any value) and `$P2P_LOG_COLOR` are honoured before the terminal
    check, because the common case for wanting it off is a file or a CI log, where
    escapes are noise rather than information.

    Args:
        stream: The stream that will be written to. Defaults to stdout.

    Returns:
        Whether to colour output.
    """
    preference = os.environ.get("P2P_LOG_COLOR", "auto").strip().lower()
    if preference in ("never", "0", "off", "false", "no"):
        return False
    if preference in ("always", "1", "on", "true", "yes"):
        return True
    if os.environ.get("NO_COLOR") is not None:
        return False
    stream = stream if stream is not None else sys.stdout
    return bool(getattr(stream, "isatty", lambda: False)())

#: Third-party loggers that report per-request or per-frame. Left at the root level
#: they drown the application's own output, especially at DEBUG.
NOISY_LOGGERS = (
    "docker",
    "urllib3",
    "httpx",
    "httpcore",
    "websockets",
    "socketio",
    "engineio",
    "asyncio",
    "PIL",
)

#: Paths the UI polls on a timer. Logging each at INFO turns the log into a
#: heartbeat and hides everything else, so they are logged at DEBUG instead. The
#: job-detail poll is matched by prefix in `is_high_frequency_path`.
HIGH_FREQUENCY_PATHS = (
    "/health",
    "/config",
    "/feedback/pending",
    # Polled every 5s by the app shell's printer pill.
    "/system/printer/status",
)

_configured = False


def resolve_level(level: str | int | None = None) -> int:
    """Return the numeric log level to use.

    Args:
        level: An explicit level name or number. When None, `$P2P_LOG_LEVEL` is
            consulted, then `DEFAULT_LEVEL`.

    Returns:
        A `logging` level integer. An unrecognised name falls back to the default
        rather than raising — a typo in an environment variable must not stop the
        server from booting.
    """
    if level is None:
        level = os.environ.get("P2P_LOG_LEVEL", DEFAULT_LEVEL)
    if isinstance(level, int):
        return level
    return getattr(logging, str(level).strip().upper(), logging.INFO)


def is_high_frequency_path(path: str) -> bool:
    """True for endpoints the UI polls, which are logged at DEBUG.

    Args:
        path: The request path.

    Returns:
        Whether this path is polled often enough to be noise at INFO.
    """
    if path in HIGH_FREQUENCY_PATHS:
        return True
    # `GET /jobs/{id}` is polled on a timer by the job detail page; its sub-resources
    # (artifacts, provenance) are not, and are worth seeing.
    parts = [p for p in path.split("/") if p]
    return len(parts) == 2 and parts[0] == "jobs"


def configure_logging(level: str | int | None = None, *, force: bool = False) -> int:
    """Install the server's log handler and format. Safe to call more than once.

    Args:
        level: Explicit level; defaults to `$P2P_LOG_LEVEL`, then INFO.
        force: Reconfigure even if this ran already. Used by tests.

    Returns:
        The numeric level that was applied.
    """
    global _configured
    resolved = resolve_level(level)

    if _configured and not force:
        logging.getLogger().setLevel(resolved)
        return resolved

    # stdout, not stderr: these are ordinary operational lines, and under Docker
    # sending them to stderr marks every one of them as an error in log viewers.
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(ConsoleFormatter(colour=should_colour(sys.stdout)))

    root = logging.getLogger()
    # Replace rather than append. uvicorn installs its own handlers when it starts,
    # and leaving them attached prints every line twice in two different formats.
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(resolved)

    # uvicorn's loggers default to propagate=False with their own handlers, so they
    # bypass everything above. Hand them the same handler and let the root level rule.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi"):
        uv = logging.getLogger(name)
        uv.handlers = [handler]
        uv.propagate = False
        uv.setLevel(resolved)

    # Silence uvicorn's access log. `log_requests` already logs every request, with
    # the duration uvicorn does not have and with the polled endpoints demoted to
    # DEBUG — and uvicorn logs the same request again, at INFO, unconditionally. The
    # result was every line twice and the noise suppression cancelled out:
    #
    #   [INFO] server.app:     GET /system/printer/status → 200 (28 ms)
    #   [INFO] uvicorn.access: 127.0.0.1:55050 - "GET /system/printer/status ..." 200
    #
    # Set $P2P_UVICORN_ACCESS_LOG=1 to get uvicorn's version back — it carries the
    # client address and HTTP version, which ours deliberately leaves out.
    access = logging.getLogger("uvicorn.access")
    access.disabled = not _env_flag("P2P_UVICORN_ACCESS_LOG")

    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(max(resolved, logging.WARNING))

    _configured = True
    return resolved


def _env_flag(name: str) -> bool:
    """Read a boolean environment variable. Absent or unset-looking means False."""
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")
