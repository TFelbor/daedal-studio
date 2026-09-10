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

Three design notes worth keeping.

**A functional article is not a reproduction, and the grammar says which one it is.**
This screen was written for the figurine product, where every curated name meant
"print me Pikachu". The parametric product's users name a franchise as the *contents*
of the part they are ordering — "deck box for Pokémon cards" is the primary persona's
literal prompt — and refusing that refuses the customer for describing their own use
case, with no appeal path. So a match is classified on a second axis, *how* the name
is used (`_classify_usage`), and only for strong hits:

- **depiction** — a depiction cue in the construction the name belongs to ("charizard
  emblem", "in the shape of pikachu", "a groot-shaped pot"). The name is what the part
  is meant to *look like*. Blocked, as before.
- **functional** — a purpose cue governing the name ("for pokemon cards", "fits 60
  double sleeved lorcana cards", "holds my … deck"). The name is what the part is
  *for*. Flagged, so the human gate still sees it.
- **attributive** — neither. A `character` is blocked ("a Pikachu deck box" names the
  subject). A `franchise` or `brand` is blocked too *unless* one of the parts this
  product makes follows it: "a Pokémon deck box" names the cards going in it and is
  flagged, "a star wars x-wing" names the object itself and is refused.

**A cue is scoped to its construction, never to a window**, and both loosenings were
reachable in one afternoon's review: a depiction cue that only had to be *nearby* read
"deck box for pokemon cards, lid on top" as a likeness and refused the primary persona
again by a second route; a purpose cue that only had to be nearby read "for my son, a
pikachu" as a purpose, which meant any prompt could be prefixed past this screen. So a
purpose cue has to reach the name across bridge tokens only (`BRIDGE_TOKENS` — articles,
possessives, numerals, sleeving words), a depiction *noun* is read in the window either
side, "in the shape of" only before the name, and "shaped"/"themed" only immediately
after it. There is no bare locational cue: "on the lid" locates a depiction noun, it is
not evidence of one, and the nouns already carry "charizard emblem on the lid" unaided.

Depiction wins when both fire, and across several matches the most severe verdict
wins, so "deck box for Pokémon cards with a Charizard emblem on the lid" is still
refused. The accepted false negative is stated rather than discovered: a character
named only as contents, with no depiction cue ("a stand for Pikachu"), is flagged
rather than blocked, and reaches the blueprint gate with the term named in the event.
The boundary the other way is a brand naming an accessory's subject — "a nintendo
switch dock" is refused and "a dock for a nintendo switch" is flagged, which is also
the appeal path the refusal's own wording asks for. This is a product decision about
where the line sits, not legal advice — see `docs/deferred-legal-tasks.md`, and note
that the human gate remains the last word.

The cues are English grammar the matcher reads, so they live here as module constants
rather than in the blocklist, which promises to be descriptive data about marks only.

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
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("ds.ip_screen")

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

#: Nouns that make the matched name a *likeness* — the thing the part is meant to look
#: like. Matched as whole tokens within `DEPICTION_WINDOW` either side of the name, so
#: "charizard emblem", "an elsa figurine" and "eevee embossed on the front" all read as
#: depiction wherever in the phrase the name sits.
DEPICTION_NOUNS: Tuple[str, ...] = (
    "emblem", "logo", "engraved", "embossed", "relief", "silhouette", "figure",
    "figurine", "statue", "bust", "portrait", "decal", "sticker", "motif", "mascot",
    "likeness", "effigy",
)

#: Depiction phrases that only mean depiction **before** the name: "in the shape of
#: pikachu". Read anywhere in the preceding `DEPICTION_WINDOW`, and deliberately not
#: after it — "a box for pokemon cards shaped like a cube" describes the *box's* shape,
#: and reading that as a likeness refused the primary persona's prompt by a second
#: route.
DEPICTION_LEADING: Tuple[str, ...] = (
    "in the shape of", "shaped like", "looks like", "modelled on", "modeled on",
)

#: Depiction words that only mean depiction **immediately after** the name:
#: "a groot-shaped pot", "a pokemon themed deck box". One token, not a window, for the
#: same reason — the word has to be modifying the name rather than merely nearby.
DEPICTION_TRAILING: Tuple[str, ...] = ("shaped", "themed", "styled")

#: Every depiction cue, in one tuple, for the guard that asserts each is already
#: normalised. There is deliberately no bare locational cue here ("on the lid",
#: "on top"): those phrases locate a depiction *noun*, they are not evidence of one on
#: their own, and the nouns above already carry "charizard emblem on the lid" unaided.
DEPICTION_CUES: Tuple[str, ...] = (
    DEPICTION_NOUNS + DEPICTION_LEADING + DEPICTION_TRAILING
)

#: How far from the name a depiction cue may sit. Four tokens reaches
#: "charizard emblem", "an elsa figurine", "pikachu, embossed on the front".
DEPICTION_WINDOW = 4

#: Cues that the matched name is what the part is *for*. Only counted **before** the
#: name: "a deck box for pokemon cards" is purpose, "a pokemon figurine for my desk"
#: is not, and the difference is which side of the name the preposition sits on.
PURPOSE_CUES: Tuple[str, ...] = (
    "for", "fit", "fits", "hold", "holds", "holding", "store", "stores", "storing",
    "storage", "organise", "organises", "organiser", "organize", "organizes",
    "organizer", "contains", "holder for", "houses", "carries", "sized for",
)

#: How far before the name a purpose cue may sit. Six tokens covers the measured
#: phrasings this product invites — "fits 60 double sleeved standard lorcana cards" is
#: five tokens from "fits" to the name.
PURPOSE_WINDOW = 6

#: "my" and "our" are purpose cues **only** with the contents named after the term, per
#: the issue's "my … deck/cards/collection". Alone they are possession of a figurine
#: just as easily as of a card collection.
POSSESSIVE_CUES: Tuple[str, ...] = ("my", "our")

#: What a functional article holds. Used to complete a possessive purpose cue and, with
#: `ARTICLE_NOUNS`, to decide whether an attributive franchise names contents — never
#: on its own before the name, because "a pikachu deck box" names its subject and would
#: otherwise read as functional on the strength of the word "deck".
CONTENTS_NOUNS: Tuple[str, ...] = (
    "card", "cards", "deck", "decks", "collection", "commander", "token", "tokens",
    "dice", "sleeve", "sleeves", "booster", "boosters", "pack", "packs", "binder",
    "set", "tcg", "ccg", "game", "minis", "miniatures",
)

#: The parts this product makes. A franchise in front of one of these names what goes
#: *in* it ("a pokemon deck box"); a franchise in front of anything else names the
#: subject ("a star wars x-wing"), which is a depiction by another route and stays
#: refused.
ARTICLE_NOUNS: Tuple[str, ...] = (
    "box", "boxes", "case", "cases", "tray", "trays", "divider", "dividers", "insert",
    "inserts", "holder", "holders", "organiser", "organizer", "rack", "racks",
    "storage", "stand", "stands", "bin", "caddy", "compartment", "compartments",
    "drawer", "drawers", "shelf", "tuckbox",
)

#: How far after the name the contents noun may sit for the possessive cue to count,
#: and for an attributive franchise to be reading as contents.
CONTENTS_WINDOW = 3

#: Tokens a purpose cue may reach the name *across*. "for pokemon cards" and "fits 60
#: double sleeved lorcana cards" are the same construction; "for my son, a pikachu" is
#: not, and proximity alone could not tell them apart — a bare "for" six tokens back
#: demoted every character block to a flag, so any prompt could be prefixed past this
#: screen. Digits are bridges too (`str.isdigit`), which is what carries "60".
BRIDGE_TOKENS: Tuple[str, ...] = (
    "a", "an", "the", "my", "our", "your", "their", "his", "her", "its", "of", "up",
    "to", "some", "one", "two", "three", "four", "six", "ten", "twelve", "twenty",
    "double", "single", "triple", "sleeved", "unsleeved", "standard", "japanese",
    "mini", "small", "large", "full", "loose", "each",
)

#: Severity order, so "the most severe verdict across every match wins" is one lookup.
_SEVERITY = {"allow": 0, "flag": 1, "block": 2}


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

    usage: Optional[str] = None
    """How the matched name was used: "depiction", "functional" or "attributive".
    None when nothing was matched, and None for a weak signal, which is a phrase
    rather than a name and so has no grammatical role to read. A trailing default so
    every existing constructor keeps working."""


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
def _match_table() -> tuple[tuple[str, str, str, str], ...]:
    """Every normalised spelling, with the term it belongs to, its strength and its
    category.

    The category is carried because the usage axis reads it: an attributive
    `character` is the subject of the prompt and is refused, an attributive
    `franchise` or `brand` names the contents and is flagged.

    Returns:
        Tuples of (normalised spelling, canonical term, "strong" | "ambiguous",
        category).
    """
    table: list[tuple[str, str, str, str]] = []
    for entry in load_blocklist():
        term = entry.get("term")
        if not term:
            continue
        strength = entry.get("strength", "strong")
        category = entry.get("category", "character")
        for spelling in [term, *entry.get("aliases", [])]:
            normalised = _normalise(spelling)
            if normalised:
                table.append((normalised, term, strength, category))
    return tuple(table)


def _find_phrases(tokens: List[str], phrase: str) -> Tuple[Tuple[int, int], ...]:
    """Every token span in *tokens* that is *phrase* as whole words.

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

    Every span is returned, not just the first: one name can be used two ways in one
    prompt ("deck box for pokemon cards, pokemon logo on the lid") and the second use
    is the one that decides.

    Args:
        tokens: The normalised prompt, split on spaces.
        phrase: A normalised spelling, possibly multi-word.

    Returns:
        `(start, end)` token indices, end exclusive, in order. Empty when the phrase
        does not appear.
    """
    needle = phrase.split()
    if not needle:
        return ()

    bare = "".join(needle)
    # Wide enough for a fully spelled-out name; beyond that the window would start
    # spanning unrelated words.
    max_width = max(len(needle), len(bare))

    spans: set[Tuple[int, int]] = set()
    for width in range(1, max_width + 1):
        for i in range(len(tokens) - width + 1):
            window = tokens[i:i + width]
            if window == needle or "".join(window) == bare:
                spans.add((i, i + width))
    return tuple(sorted(spans))


def _contains_phrase(tokens: List[str], phrase: str) -> bool:
    """Whether *phrase* appears in *tokens* as whole words. See `_find_phrases`."""
    return bool(_find_phrases(tokens, phrase))


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


def _fuzzy_hit(
    haystack_tokens: List[str], needle: str,
) -> Tuple[float, Optional[Tuple[int, int]]]:
    """Best similarity between a curated term and any window of the prompt.

    Multi-word terms are compared against windows of the same word count, so
    "darth vader" is looked for as a pair rather than as two unrelated tokens.

    Args:
        haystack_tokens: The normalised prompt, split on spaces.
        needle: One normalised curated spelling.

    Returns:
        `(best ratio, span)`, where the span is the window that scored it — the usage
        axis needs to know *where* the near-match sits, so that "deck box for pokmon
        cards" is read as functional rather than blocked. `(0.0, None)` when the term
        is too short to fuzzy-match or the prompt is shorter than the term.
    """
    width = len(needle.split())
    if len(needle.replace(" ", "")) < MIN_FUZZY_LENGTH:
        return 0.0, None

    best, best_span = 0.0, None
    for i in range(len(haystack_tokens) - width + 1):
        window = " ".join(haystack_tokens[i:i + width])
        ratio = difflib.SequenceMatcher(None, window, needle).ratio()
        if ratio > best:
            best, best_span = ratio, (i, i + width)
    return best, best_span


def _is_bridge(token: str) -> bool:
    """Whether a purpose cue may reach across *token* to the name beyond it."""
    return token.isdigit() or token in BRIDGE_TOKENS or token in CONTENTS_NOUNS


def _cue_reaches_name(window: List[str], cue: str) -> bool:
    """Whether *cue* appears in *window* and governs whatever follows the window.

    *window* is the tokens immediately before the name, so "reaches the name" is
    "every token between the end of the cue and the end of the window is a bridge".
    That is the difference between "for pokemon cards" and "for my son, a pikachu":
    the second has "son" in the way, so the "for" is governing the son, not the name.
    `_normalise` has already deleted the comma that would otherwise have separated
    the clauses, which is why punctuation cannot be relied on here.
    """
    return any(
        all(_is_bridge(token) for token in window[end:])
        for _, end in _find_phrases(window, cue)
    )


def _names_contents(tokens: List[str], span: Tuple[int, int]) -> bool:
    """Whether the name at *span* is followed by the part it goes in.

    "a pokemon deck box" and "a lorcana card divider" name their contents; "a star
    wars x-wing" and "the mandalorian helmet" name the subject. The head noun is the
    only thing that distinguishes them, since neither carries a cue.
    """
    after = tokens[span[1]:span[1] + CONTENTS_WINDOW]
    return any(token in CONTENTS_NOUNS or token in ARTICLE_NOUNS for token in after)


def _classify_usage(tokens: List[str], span: Tuple[int, int]) -> str:
    """How the name occupying *span* is being used.

    Args:
        tokens: The normalised prompt, split on spaces.
        span: `(start, end)` token indices of the matched name, end exclusive.

    Returns:
        "depiction", "functional" or "attributive". Depiction is checked first, so a
        prompt that both names its contents and asks for a likeness is read as asking
        for the likeness.

    Each cue is scoped to the construction it belongs to rather than to a window,
    because both loosenings were reachable: a depiction cue that is merely *nearby*
    read "deck box for pokemon cards, lid on top" as a likeness, and a purpose cue
    that is merely nearby read "for my son, a pikachu" as a purpose.
    """
    start, end = span

    around = tokens[max(0, start - DEPICTION_WINDOW):end + DEPICTION_WINDOW]
    if any(noun in around for noun in DEPICTION_NOUNS):
        return "depiction"

    leading = tokens[max(0, start - DEPICTION_WINDOW):start]
    if any(_contains_phrase(leading, cue) for cue in DEPICTION_LEADING):
        return "depiction"

    if end < len(tokens) and tokens[end] in DEPICTION_TRAILING:
        return "depiction"

    before = tokens[max(0, start - PURPOSE_WINDOW):start]
    if any(_cue_reaches_name(before, cue) for cue in PURPOSE_CUES):
        return "functional"

    after = tokens[end:end + CONTENTS_WINDOW]
    if (any(_cue_reaches_name(before, cue) for cue in POSSESSIVE_CUES)
            and any(noun in after for noun in CONTENTS_NOUNS)):
        return "functional"

    return "attributive"


@dataclasses.dataclass(frozen=True)
class _Hit:
    """One matched spelling, with everything the verdict turns on."""

    term: str
    category: str
    strength: str
    score: float
    usage: str
    names_contents: bool = False
    """Whether the part the name goes in follows it. Only read for an attributive
    `franchise` or `brand`, where it is the whole difference between "a pokemon deck
    box" and "a star wars x-wing"."""


def _hit_action(hit: _Hit) -> str:
    """What one match, on its own, would decide.

    An ambiguous term is flagged whatever its usage: the match is *correct* and the
    inference is not, which no amount of grammar fixes — "a joker figurine" is a
    jester as readily as the DC character. Usage only discriminates among strong
    matches, which is where this screen's refusals come from.

    An attributive `franchise` or `brand` is flagged only when it names the contents
    of an article ("a pokemon deck box"). Naming a franchise in front of anything
    else is naming the subject — "a star wars x-wing", "a hogwarts castle" — and that
    is a reproduction of someone else's design however the sentence is arranged, so
    it stays refused exactly as it was before the functional rule existed.
    """
    if hit.strength != "strong":
        return "flag"
    if hit.usage == "depiction":
        return "block"
    if hit.usage == "functional":
        return "flag"
    if hit.category == "character":
        return "block"
    return "flag" if hit.names_contents else "block"


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

    exact: list[_Hit] = []
    fuzzy: Optional[_Hit] = None
    best_score = 0.0

    for spelling, term, strength, category in _match_table():
        spans = _find_phrases(tokens, spelling)
        if spans:
            exact.extend(
                _Hit(
                    term, category, strength, 1.0,
                    _classify_usage(tokens, span), _names_contents(tokens, span),
                )
                for span in spans
            )
            continue
        ratio, span = _fuzzy_hit(tokens, spelling)
        if ratio > best_score and span is not None:
            best_score = ratio
            fuzzy = _Hit(
                term, category, strength, ratio,
                _classify_usage(tokens, span), _names_contents(tokens, span),
            )

    # An ambiguous word standing next to an unambiguous one is not ambiguous: "the
    # joker from batman" is not a playing card, and "a space marine from warhammer
    # 40k" is not a spaceman. The trigger is a strong hit that is itself a refusal,
    # not merely a strong hit: a *functional* franchise is the one construction this
    # screen now accepts, and promoting on it turned "a deck box for pokemon cards
    # with a creeper vine engraved on the lid" into a refusal over a plant.
    if any(_hit_action(hit) == "block" for hit in exact if hit.strength == "strong"):
        exact = [dataclasses.replace(hit, strength="strong") for hit in exact]

    # The best near-match is considered alongside the exact ones rather than only when
    # there are none: with usage in play, an exact functional hit no longer refuses the
    # whole prompt, so "deck box for pokemon cards with a pikchu emblem" must still be
    # decided by the near-match on "pikachu".
    candidates = list(exact)
    if fuzzy is not None and fuzzy.score >= FUZZY_THRESHOLD:
        candidates.append(fuzzy)

    if candidates:
        # The most severe verdict any one match would give, and then the first match
        # that gives it — blocklist order, so the term a person is shown is stable.
        action = max((_hit_action(hit) for hit in candidates), key=_SEVERITY.__getitem__)
        decisive = next(hit for hit in candidates if _hit_action(hit) == action)

        if action == "block":
            return ScreenVerdict(
                action="block",
                term=decisive.term,
                score=round(decisive.score, 3),
                detail=(
                    f"This prompt names \"{decisive.term}\", which belongs to someone "
                    "else. We only print original designs, so we cannot make this "
                    "one. Describe the shape and character you want in your own words "
                    "instead and we will design something original for you."
                ),
                suggestion=(
                    "Try describing the form rather than the name — proportions, pose, "
                    "silhouette, style. For example: \"a chunky, round-cheeked creature "
                    "figurine with big ears and a lightning-bolt tail, chibi "
                    "proportions\"."
                ),
                usage=decisive.usage,
            )

        # A name used for what the part *holds* describes purpose, not depiction. The
        # part is made; the flag is what the human gate reads.
        if decisive.usage == "functional":
            return ScreenVerdict(
                action="flag",
                term=decisive.term,
                score=round(decisive.score, 3),
                detail=(
                    f"This prompt mentions \"{decisive.term}\" as what the part is "
                    "for, not as what it depicts, so it goes ahead as a functional "
                    "article. It will be reviewed before anything is reconstructed."
                ),
                suggestion=None,
                usage=decisive.usage,
            )

        # A correct match on a word that is also ordinary English, or on a franchise
        # naming what goes in the part, is a question for a person rather than a
        # refusal. The image screen and the blueprint gate are both downstream; a
        # wrongly refused prompt has nothing downstream at all.
        return ScreenVerdict(
            action="flag",
            term=decisive.term,
            score=round(decisive.score, 3),
            detail=(
                f"This prompt uses the word \"{decisive.term}\", which is also the "
                "name of a protected character or franchise. It will be reviewed "
                "before anything is reconstructed."
            ),
            suggestion=None,
            usage=decisive.usage,
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
    if fuzzy is not None and fuzzy.score >= 0.72:
        return ScreenVerdict(
            action="flag",
            term=fuzzy.term,
            score=round(fuzzy.score, 3),
            detail=(
                f"This prompt resembles \"{fuzzy.term}\". It will be reviewed before "
                "anything is reconstructed."
            ),
            suggestion=None,
            usage=fuzzy.usage,
        )

    return ScreenVerdict("allow", None, 0.0, "No protected name recognised.", None)
