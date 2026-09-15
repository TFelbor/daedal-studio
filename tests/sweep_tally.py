"""The dimensional sweep's one-line-per-archetype summary (issue #85).

The sweep is ~1000 parametrized cases across every registered archetype, and pytest's
own output says `979 passed` — one number for all of them. What a reviewer needs from
the CI job list is *which* archetype was swept and how far, because the failure this
guards against is not a red test: it is a new archetype quietly contributing nothing,
which looks exactly like a green run. `deck_box: 495/495` on its own line says the
envelope was declared, collected and driven; a missing line says it was not.

The counting lives here rather than inside `conftest.py` so it can be tested as a
function rather than through a nested pytest run: the hooks there are four lines that
record an outcome and print these lines, and everything that could be wrong about the
figures is below.
"""
from __future__ import annotations

from collections import Counter


class SweepTally:
    """Per-archetype outcome counts for the cases pytest actually ran.

    Counts *reports*, not envelope sizes: a figure derived from the envelope would say
    `495/495` for a run that collected nothing (`-k` on the command line, a collection
    error, a crashed case). The denominator is therefore how many cases reached their
    call phase, which is the only number the summary can honestly claim.
    """

    def __init__(self) -> None:
        self._by_archetype: dict[str, Counter[str]] = {}

    def record(self, archetype: str, outcome: str) -> None:
        """Record one case's outcome — pytest's `"passed"`, `"failed"` or `"skipped"`."""
        self._by_archetype.setdefault(archetype, Counter())[outcome] += 1

    def __bool__(self) -> bool:
        return bool(self._by_archetype)

    def lines(self) -> list[str]:
        """One line per archetype swept, in name order.

        `deck_box: 495/495` when every case passed; anything else names the shortfall
        (`deck_box: 493/495 (2 failed)`) rather than leaving a reader to subtract, and
        the counts are in outcome order so two runs of the same shape read the same.
        """
        lines = []
        for archetype in sorted(self._by_archetype):
            counts = self._by_archetype[archetype]
            total = sum(counts.values())
            line = f"{archetype}: {counts['passed']}/{total}"
            others = sorted(
                (outcome, n) for outcome, n in counts.items() if outcome != "passed"
            )
            if others:
                line += " (" + ", ".join(f"{n} {outcome}" for outcome, n in others) + ")"
            lines.append(line)
        return lines
