"""Screening a prompt for names that would make the printed part someone else's.

The exposure this exists for is specific: this project does not host files, it
**manufactures and hands over a physical object**. If that object reproduces a
protected character, the analysis is direct infringement — the hosting-provider
shelters do not apply to making goods, and the private/non-commercial-use exception
(Art. 20(1)(a) Community Design Regulation) covers a person printing at home for
themselves, expressly not a paid service printing on their behalf.

So the screen has two settings rather than one, because a single setting is wrong
either way:

- **block** — a curated name is in the prompt. Refused before a job row exists, and
  therefore before Phase 2 is billed and before a nozzle heats. The refusal names the
  term it matched and offers an original-design alternative, because a bare rejection
  just sends someone to support.
- **flag** — something weaker: a phrase like "screen accurate", or a name that is
  close to a curated one without matching it. Allowed through and recorded, so the
  human blueprint gate decides. Refusing everything half-recognised would refuse
  paying pilot users for asking about fan art, and this is a pilot.

Two design notes worth keeping.

**Normalise, then compare.** A raw string comparison has already been defeated once in
this repo — the licensing guard was beaten by a `repo@sha` revision pin — so accents,
spacing, hyphens and case are folded away before anything is matched, and a bounded
edit distance covers typos.

**Every field that reaches the model is screened, not just `prompt`.** `material_colour`
is free text from the composer that `blueprint_spec.engineer_prompt` interpolates into
the string sent to FLUX. A screen reading `prompt` alone leaves the colour box as a
second, unwatched prompt channel.

Deliberately torch-free and dependency-free (`difflib` is stdlib): the API server image
is `python:3.10-slim` with no torch, no transformers and no numpy, and a screen that
cannot be imported there is a screen that cannot refuse a job.
"""

from __future__ import annotations

import dataclasses
import difflib
import functools
import json
import logging
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("p2p.ip_screen")

#: Where the curated list lives. In-tree data rather than the encrypted config store:
#: reviewable in a diff, testable, and `ConfigStore.set` refuses unregistered keys.
BLOCKLIST_PATH = Path(__file__).parent / "data" / "ip_blocklist.json"

#: How close a token has to be to a curated term to count as that term. 0.86 catches a
#: dropped or swapped character in a name of eight or more letters ("pikchu") without
#: pulling in ordinary words. Tightening this lets evasions through; loosening it
#: starts refusing real prompts, which is the more expensive mistake here because the
#: blueprint gate is downstream and a refusal has no appeal.
FUZZY_THRESHOLD = 0.86

#: Curated terms shorter than this are matched exactly, never fuzzily. At four or five
#: characters an edit distance of one reaches too many unrelated English words —
#: "hulk"/"bulk", "elsa"/"else".
MIN_FUZZY_LENGTH = 6


@dataclasses.dataclass(frozen=True)
class ScreenVerdict:
    """What the screen decided, and everything needed to act on it."""

    action: str
    """"allow", "flag" or "block"."""

    term: Optional[str]
    """The curated term or weak signal that matched, or None when nothing did."""

    score: float
    """Match confidence, 1.0 for an exact hit. 0.0 when nothing matched."""

    detail: str
    """A full sentence for a person: what was matched and what happens now."""

    suggestion: Optional[str]
    """A way forward for a blocked prompt — an original-design rephrasing. None for
    an allow, and None for a flag, which is not a refusal and needs no alternative."""


def _normalise(text: str) -> str:
    """Fold away everything an evasion can vary without changing what a person reads.

    Accents are decomposed and stripped, case is folded, and every run of
    non-alphanumeric characters becomes a single space — which is what collapses
    "Pika-chu", "P I K A C H U" and "pikachú" onto one string.

    Args:
        text: Any user-supplied text.

    Returns:
        The normalised form, or "" for empty input.
    """
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", stripped.casefold()).strip()


@functools.lru_cache(maxsize=1)
def _blocklist_document() -> Dict[str, Any]:
    """Read and cache the blocklist file.

    Cached because this is called on every job submission and the file does not change
    at runtime. A missing or malformed file is logged and treated as empty rather than
    raising: a screen that cannot load must not take `POST /jobs` down with it, and the
    human blueprint gate is still downstream. It is loud about it, because a silently
    disabled screen is worse than no screen.
    """
    try:
        with open(BLOCKLIST_PATH, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "IP blocklist could not be read from %s (%s) — the prompt screen is "
            "inactive for this process.", BLOCKLIST_PATH, exc,
        )
        return {"entries": [], "weak_signals": []}


def load_blocklist() -> List[Dict[str, Any]]:
    """The curated entries, as data.

    Returns:
        A list of `{"term", "category"}` dicts, optionally with `"aliases"`.
    """
    return list(_blocklist_document().get("entries", []))


@functools.lru_cache(maxsize=1)
def _match_table() -> tuple[tuple[str, str, str], ...]:
    """Every normalised spelling, with the term it belongs to and its strength.

    Returns:
        Tuples of (normalised spelling, canonical term, "strong" | "ambiguous").
    """
    table: list[tuple[str, str, str]] = []
    for entry in load_blocklist():
        term = entry.get("term")
        if not term:
            continue
        strength = entry.get("strength", "strong")
        for spelling in [term, *entry.get("aliases", [])]:
            normalised = _normalise(spelling)
            if normalised:
                table.append((normalised, term, strength))
    return tuple(table)


def _contains_phrase(tokens: List[str], phrase: str) -> bool:
    """Whether *phrase* appears in *tokens* as whole words.

    Two ways a window can match, and both are needed:

    - the tokens equal the phrase's words exactly; or
    - the window's characters, concatenated, equal the phrase's characters with spaces
      removed — which is what catches "Pika-chu" (normalised to two tokens) and
      "P I K A C H U" (normalised to eight).

    The concatenation is over a **window of whole tokens**, never over the whole prompt.
    That distinction is the entire fix for the original implementation, which was
    `phrase in " ".join(tokens)` — a substring test that refused "a marionette puppet"
    for containing "mario", "a hulking stone golem" for "hulk" and "a wooden stitch
    marker" for "stitch". Concatenating a window cannot match inside a longer word,
    because "marionette" is one token and its concatenation is "marionette".

    Args:
        tokens: The normalised prompt, split on spaces.
        phrase: A normalised spelling, possibly multi-word.

    Returns:
        True when some window of whole tokens is that phrase.
    """
    needle = phrase.split()
    if not needle:
        return False

    bare = "".join(needle)
    # Wide enough for a fully spelled-out name; beyond that the window would start
    # spanning unrelated words.
    max_width = max(len(needle), len(bare))

    for width in range(1, max_width + 1):
        for i in range(len(tokens) - width + 1):
            window = tokens[i:i + width]
            if window == needle:
                return True
            if "".join(window) == bare:
                return True
    return False


@functools.lru_cache(maxsize=1)
def _weak_signals() -> tuple[str, ...]:
    """Phrases that suggest a reproduction without naming one.

    "screen accurate", "official", "licensed" — none of these is a character name, and
    all of them describe an intent to copy something specific. They flag rather than
    refuse, because the phrase alone is not evidence of what is being copied.
    """
    return tuple(
        _normalise(s) for s in _blocklist_document().get("weak_signals", []) if _normalise(s)
    )


def _fuzzy_hit(haystack_tokens: List[str], needle: str) -> float:
    """Best similarity between a curated term and any window of the prompt.

    Multi-word terms are compared against windows of the same word count, so
    "darth vader" is looked for as a pair rather than as two unrelated tokens.

    Args:
        haystack_tokens: The normalised prompt, split on spaces.
        needle: One normalised curated spelling.

    Returns:
        The best ratio found, or 0.0 when the term is too short to fuzzy-match.
    """
    width = len(needle.split())
    if len(needle.replace(" ", "")) < MIN_FUZZY_LENGTH:
        return 0.0

    best = 0.0
    for i in range(len(haystack_tokens) - width + 1):
        window = " ".join(haystack_tokens[i:i + width])
        ratio = difflib.SequenceMatcher(None, window, needle).ratio()
        if ratio > best:
            best = ratio
    return best


def screen_prompt(prompt: str, *args: Optional[str]) -> ScreenVerdict:
    """Decide whether a submission may proceed.

    Args:
        prompt: The user's prompt.
        *args: Any other free-text field that reaches the model — currently
            `material_colour`, which the blueprint wrapper interpolates. Passed
            positionally so a new field is one call-site change and cannot be
            forgotten in a signature.

    Returns:
        A `ScreenVerdict`. "block" means refuse the submission; "flag" means proceed
        and record it for the blueprint gate; "allow" means nothing was recognised.
    """
    combined = " ".join(part for part in (prompt, *args) if part)
    normalised = _normalise(combined)
    if not normalised:
        return ScreenVerdict("allow", None, 0.0, "Nothing to screen.", None)

    tokens = normalised.split()

    exact_strong: Optional[str] = None
    exact_ambiguous: Optional[str] = None
    best_term, best_score, best_strength = None, 0.0, "strong"

    for spelling, term, strength in _match_table():
        if _contains_phrase(tokens, spelling):
            if strength == "strong":
                exact_strong = exact_strong or term
            else:
                exact_ambiguous = exact_ambiguous or term
            continue
        ratio = _fuzzy_hit(tokens, spelling)
        if ratio > best_score:
            best_term, best_score, best_strength = term, ratio, strength

    # An ambiguous word standing next to an unambiguous one is not ambiguous: "the
    # joker from batman" is not a playing card.
    if exact_strong:
        best_term, best_score, best_strength = exact_strong, 1.0, "strong"
    elif exact_ambiguous:
        best_term, best_score, best_strength = exact_ambiguous, 1.0, "ambiguous"

    # A correct match on a word that is also ordinary English is a question for a
    # person, not a refusal. The image screen and the blueprint gate are both
    # downstream; a wrongly refused prompt has nothing downstream at all.
    if best_score >= FUZZY_THRESHOLD and best_term and best_strength == "ambiguous":
        return ScreenVerdict(
            action="flag",
            term=best_term,
            score=round(best_score, 3),
            detail=(
                f"This prompt uses the word \"{best_term}\", which is also the name of "
                "a protected character. It will be reviewed before anything is "
                "reconstructed."
            ),
            suggestion=None,
        )

    if best_score >= FUZZY_THRESHOLD and best_term:
        return ScreenVerdict(
            action="block",
            term=best_term,
            score=round(best_score, 3),
            detail=(
                f"This prompt names \"{best_term}\", which belongs to someone else. "
                "We only print original designs, so we cannot make this one. Describe "
                "the shape and character you want in your own words instead and we "
                "will design something original for you."
            ),
            suggestion=(
                "Try describing the form rather than the name — proportions, pose, "
                "silhouette, style. For example: \"a chunky, round-cheeked creature "
                "figurine with big ears and a lightning-bolt tail, chibi proportions\"."
            ),
        )

    for signal in _weak_signals():
        if signal in normalised:
            return ScreenVerdict(
                action="flag",
                term=signal,
                score=0.5,
                detail=(
                    f"This prompt says \"{signal}\", which often means a reproduction "
                    "of an existing product. It will be reviewed before anything is "
                    "reconstructed."
                ),
                suggestion=None,
            )

    # A near miss that did not clear the threshold is still worth surfacing to the
    # person who approves the blueprint — it is exactly the band where the string
    # comparison should not be the one deciding.
    if best_score >= 0.72 and best_term:
        return ScreenVerdict(
            action="flag",
            term=best_term,
            score=round(best_score, 3),
            detail=(
                f"This prompt resembles \"{best_term}\". It will be reviewed before "
                "anything is reconstructed."
            ),
            suggestion=None,
        )

    return ScreenVerdict("allow", None, 0.0, "No protected name recognised.", None)
