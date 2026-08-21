"""One vocabulary of symbols for the server's own log, and a live feed of it.

Two problems this solves.

**The log was not readable.** Every line looked the same, so a wall of INFO gave no
shape: a one-word event and a twelve-field job submission were rendered identically
and neither could be found by eye. The pipeline already had a grammar for this — the
`[P2P] ═══ PHASE 2 START ═══` banners the server parses — and it worked, so it is
extended here rather than replaced.

**The log was not reactive.** The interesting things the server does happen in
background tasks — a collector claiming a job, a detector firing, a simulator coming
up — and none of them said anything. What survived was mostly request lines, which
describe HTTP rather than the system.

## The grammar

Shape carries meaning, so a glance sorts the stream without reading it:

    · 15:04:02  one-liner: a single event with nothing to expand

    ┌─ JOB CREATED ────────────────────────────────
    │ job        a7f3c2e1
    │ prompt     a low poly planter box
    │ strategy   mps_native
    └─ → queued, pipeline starting
                            a block: an action and its fields, closed by its
                            consequence, so cause and effect cannot drift apart

    ════════════ PHASE 2 · SCULPTOR ═══════════════
                            heavy rule: a pipeline-level boundary

    ──────────── printability ─────────────────────
                            light rule: a sub-step inside a phase

The four openers (`·`, `┌`, `═`, `─`) are deliberately distinct in the first column,
which is the only column the eye scans when skimming. Everything else is alignment.

Severity keeps its own marks inside a block — `▲` warn, `✖` fail, `✔` ok — rather
than a colour, because the log is read as often in a file as in a terminal.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Sequence

logger = logging.getLogger("p2p.activity")

#: Total width of a rule or a block's top edge. 62 fits an 80-column terminal with
#: room for the timestamp and level prefix the formatter puts in front of it.
WIDTH = 62

#: The first column is the only thing the eye reads when skimming, so each kind of
#: line gets its own opener and no two share one.
GLYPH = {
    "one": "·",
    "open": "┌─",
    "mid": "│",
    "close": "└─",
    "heavy": "═",
    "light": "─",
    "warn": "▲",
    "fail": "✖",
    "ok": "✔",
    "to": "→",
}

#: Width the key column in a block is padded to, so values line up down the block.
KEY_WIDTH = 12


def _fit(text: str, limit: int) -> str:
    """Trim to `limit` characters with an ellipsis, so a block edge never wraps.

    A wrapped block edge is worse than a truncated value: it breaks the one property
    the grammar relies on, which is that the first column identifies the line.
    """
    if len(text) <= limit:
        return text
    if limit <= 1:
        return text[:limit]
    return text[: limit - 1] + "…"


def rule(title: str = "", *, heavy: bool = False) -> str:
    """A horizontal rule, optionally titled and centred.

    Heavy (`═`) marks a phase-level boundary; light (`─`) marks a sub-step inside one.
    """
    char = GLYPH["heavy"] if heavy else GLYPH["light"]
    if not title:
        return char * WIDTH
    label = f" {_fit(title.upper() if heavy else title, WIDTH - 8)} "
    side = max(2, (WIDTH - len(label)) // 2)
    line = f"{char * side}{label}{char * side}"
    return line[:WIDTH] if len(line) > WIDTH else line + char * (WIDTH - len(line))


def one(message: str) -> str:
    """A single-line event: something happened and there is nothing to expand."""
    return f"{GLYPH['one']} {message}"


def block(
    title: str,
    rows: Sequence[tuple[str, Any]] | None = None,
    *,
    outcome: str | None = None,
    status: str | None = None,
) -> str:
    """An action, its fields, and the consequence that closes it.

    The consequence is rendered on the block's own bottom edge rather than as a
    separate line, because the two used to be logged independently and drifted apart
    under concurrency — a request's result would appear three lines below somebody
    else's action and read as belonging to it.

    Args:
        title: What happened, as a short upper-cased phrase.
        rows: `(key, value)` pairs. A None value renders as `—`, not as "None".
        outcome: The consequence. Rendered after `→` on the closing edge.
        status: `ok`, `warn` or `fail`. Marks the outcome with its glyph.
    """
    head = f" {_fit(title.upper(), WIDTH - 6)} "
    top = f"{GLYPH['open']}{head}"
    top += GLYPH["light"] * max(0, WIDTH - len(top))

    lines = [top]
    for key, value in rows or ():
        shown = "—" if value is None or value == "" else str(value)
        # The key is trimmed to the column, not allowed to overflow it. Alignment is
        # the only reason the block form is easier to read than four separate lines,
        # so one long key must not shift every value on the row below it.
        label = _fit(str(key), KEY_WIDTH)
        lines.append(f"{GLYPH['mid']} {label:<{KEY_WIDTH}} {_fit(shown, WIDTH - KEY_WIDTH - 4)}")

    if outcome:
        mark = GLYPH.get(status or "", "")
        tail = f" {GLYPH['to']} {mark + ' ' if mark else ''}{_fit(outcome, WIDTH - 8)}"
        lines.append(f"{GLYPH['close']}{tail}")
    else:
        lines.append(GLYPH["close"] + GLYPH["light"] * (WIDTH - 2))

    return "\n".join(lines)


# ── The live feed ────────────────────────────────────────────────────────────────

@dataclass
class ActivityRecord:
    """One entry in the feed. `text` is already rendered in the grammar above."""

    seq: int
    at: str
    level: str
    source: str
    text: str

    def as_dict(self) -> dict:
        return {
            "seq": self.seq,
            "at": self.at,
            "level": self.level,
            "source": self.source,
            "text": self.text,
        }


@dataclass
class ActivityLog:
    """A bounded history of what the server did, plus a live fan-out of it.

    Bounded because this is a debugging aid, not the record: the durable copy is
    whatever the handler in `logging_config` writes. Kept in memory so reading it
    cannot touch the telemetry database, which is the one file in this project that
    must not gain a second reader for the sake of a log panel.
    """

    capacity: int = 500
    _entries: deque[ActivityRecord] = field(default_factory=deque)
    _seq: int = 0
    _listeners: list[Callable[[ActivityRecord], None]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._entries = deque(maxlen=self.capacity)

    def subscribe(self, listener: Callable[[ActivityRecord], None]) -> Callable[[], None]:
        """Register a listener and return the function that removes it again."""
        self._listeners.append(listener)

        def unsubscribe() -> None:
            try:
                self._listeners.remove(listener)
            except ValueError:
                pass

        return unsubscribe

    def recent(self, limit: int | None = None) -> list[dict]:
        entries = list(self._entries)
        if limit is not None and limit < len(entries):
            entries = entries[-limit:]
        return [e.as_dict() for e in entries]

    def emit(self, text: str, *, level: str = "INFO", source: str = "server") -> ActivityRecord:
        """Record a rendered line, log it, and hand it to every listener.

        A listener that raises is dropped rather than allowed to break the caller: the
        callers are request handlers and background tasks doing real work, and a
        broken log panel must not take a print job down with it.
        """
        self._seq += 1
        record = ActivityRecord(
            seq=self._seq,
            at=datetime.now(timezone.utc).isoformat(),
            level=level,
            source=source,
            text=text,
        )
        self._entries.append(record)

        logger.log(getattr(logging, level, logging.INFO), "%s", text)

        for listener in list(self._listeners):
            try:
                listener(record)
            except Exception:
                logger.debug("Activity listener failed; dropping it", exc_info=True)
                self._listeners.remove(listener)
        return record

    # ── Convenience wrappers, so call sites read as intent ──────────────────────

    def event(self, message: str, *, level: str = "INFO", source: str = "server") -> None:
        """A one-liner."""
        self.emit(one(message), level=level, source=source)

    def action(
        self,
        title: str,
        rows: Iterable[tuple[str, Any]] | None = None,
        *,
        outcome: str | None = None,
        status: str | None = None,
        level: str = "INFO",
        source: str = "user",
    ) -> None:
        """A block: something a person did, or a background task's decision."""
        self.emit(
            block(title, list(rows or ()), outcome=outcome, status=status),
            level=level,
            source=source,
        )

    def boundary(self, title: str, *, heavy: bool = True, source: str = "pipeline") -> None:
        """A rule marking a phase or sub-step boundary."""
        self.emit(rule(title, heavy=heavy), source=source)


#: The process-wide feed. One instance so a WebSocket subscriber sees everything.
activity = ActivityLog()
