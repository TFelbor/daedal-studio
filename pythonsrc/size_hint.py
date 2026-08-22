"""Reading a physical size out of a prompt, so the composer can offer it.

"a 10cm tall vase" already answers the question the size control is asking, and
making someone type it twice is friction for no gain. But parsing it and *applying*
it would put a number on the row that the person never chose, and `prompt` and
`requested_size_mm` would then disagree about who decided. That is the same class of
fabrication as a mesh built from a fixture sitting in the real output namespace.

So this module only ever produces a **suggestion**. The server offers it, the
composer prefills with it, and the row records `size_source="prompt_hint"` only once
a human has accepted it.

Deliberately torch-free, for the same reason `blueprint_spec` is: the API server
image has no torch, and the parser has to be importable from the server, the pipeline
and the tests alike.

Units are millimetres at the boundary. An imperial value is converted where it is
read and never stored, so nothing downstream has to know which unit it came in as.
"""

from __future__ import annotations

import dataclasses
import re
from typing import Optional

#: Widest size a hint may propose, in mm. Matches the request model's own ceiling —
#: prefilling a control with a value that cannot then be submitted is worse than
#: leaving it blank, because the person has to work out why it was refused.
MAX_HINT_MM = 1000.0

#: Narrowest size worth proposing. Below one nozzle width there is nothing to print.
MIN_HINT_MM = 1.0

#: Multiplier to millimetres for every unit spelling recognised.
_UNITS: dict[str, float] = {
    "mm": 1.0,
    "millimetre": 1.0, "millimetres": 1.0, "millimeter": 1.0, "millimeters": 1.0,
    "cm": 10.0,
    "centimetre": 10.0, "centimetres": 10.0, "centimeter": 10.0, "centimeters": 10.0,
    "m": 1000.0,
    "metre": 1000.0, "metres": 1000.0, "meter": 1000.0, "meters": 1000.0,
    "in": 25.4,
    "inch": 25.4, "inches": 25.4,
    '"': 25.4,
}

# A number, optional space, then a unit. The unit is required: a bare number in a
# prompt is far more often a count ("a dragon with 3 heads"), a year ("a 1950s
# radio") or part of a name ("a d20 dice") than a size, and a wrong prefill costs
# more than a missing one.
_PATTERN = re.compile(
    r"(?<![\w.])(\d+(?:[.,]\d+)?)\s*(" + "|".join(
        sorted((re.escape(u) for u in _UNITS), key=len, reverse=True)
    ) + r")(?![\w])",
    re.IGNORECASE,
)

#: Words that say which extent the number describes. "10cm tall" and "10cm wide" are
#: different requests and the sentence already distinguishes them.
_HEIGHT_WORDS = ("tall", "high", "height", "tall,")
_LONGEST_WORDS = ("wide", "width", "long", "length", "across", "diameter", "deep")

# How far past the number to look for one of those words. Wide enough for "10cm tall"
# and "10 cm in height", narrow enough that a "tall" three clauses later is not read
# as qualifying this number.
_AXIS_WINDOW = 24


@dataclasses.dataclass(frozen=True)
class SizeHint:
    """A size found in a prompt, with enough context for a person to check it."""

    mm: float
    """The size in millimetres."""

    text: str
    """The substring that was matched, so the UI can show what it read."""

    span: tuple[int, int]
    """Start and end offsets of `text` in the original prompt."""

    axis: Optional[str]
    """"height" or "longest" when the prose says which extent was meant, else None.
    None means the caller should apply its own default rather than infer an intent
    the sentence does not contain."""


def parse_size_hint(prompt: str) -> Optional[SizeHint]:
    """Find a physical size in a prompt, if it states one unambiguously.

    Args:
        prompt: The user's prompt, verbatim.

    Returns:
        A `SizeHint`, or None when the prompt states no size, states one in a unit
        that is not recognised, or states one outside `MIN_HINT_MM`..`MAX_HINT_MM`.
    """
    if not prompt:
        return None

    match = _PATTERN.search(prompt)
    if match is None:
        return None

    value = float(match.group(1).replace(",", "."))
    millimetres = value * _UNITS[match.group(2).lower()]
    if not (MIN_HINT_MM <= millimetres <= MAX_HINT_MM):
        return None

    tail = prompt[match.end():match.end() + _AXIS_WINDOW].lower()
    axis = None
    if any(word in tail for word in _HEIGHT_WORDS):
        axis = "height"
    elif any(word in tail for word in _LONGEST_WORDS):
        axis = "longest"

    return SizeHint(
        mm=millimetres,
        text=match.group(0),
        span=(match.start(), match.end()),
        axis=axis,
    )


def strip_size_phrase(prompt: str, hint: Optional[SizeHint]) -> str:
    """Remove the matched size phrase, once the size is carried as a parameter.

    Saying it twice makes the render worse rather than better. FLUX draws scale cues:
    asked for something with a size it will often add a hand or a coin for reference,
    and Phase 2 then has two subjects — the matte cuts out what it finds and
    `_largest_component` keeps whichever has more faces.

    Only the numeric phrase is removed. Vague size words ("small", "miniature",
    "giant") are deliberately left alone: those are style, not measurement, and a
    chibi figurine is a different model from a scaled-down realistic one. Editing
    them out would change what the person asked for.

    Args:
        prompt: The user's prompt.
        hint: The hint returned by `parse_size_hint`, or None.

    Returns:
        The prompt with the size phrase removed and whitespace tidied, or unchanged
        when there was no hint.
    """
    if hint is None:
        return prompt

    start, end = hint.span
    stripped = prompt[:start] + prompt[end:]
    return re.sub(r"\s{2,}", " ", stripped).strip()
