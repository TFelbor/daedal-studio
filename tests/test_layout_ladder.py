"""One breakpoint ladder, two steps, and nothing else.

The app narrows at exactly two widths: **900px**, where every split becomes a stack,
and **720px**, the phone. `global.css` already stepped `--gutter` at those two; the
pages did not, and collapsed at 900, 1000, 820, 700, 640, 560 and 540 instead. The
effect was not a subtle one — a tablet at 960px got `JobDetail`'s single column and
`JobList`'s six, and `PrintabilityCard` kept three 24px figures side by side for 180px
after the page around it had folded.

375px is a *test* viewport, not a step: the phone layout is whatever 720 produced, and
if it needs its own rule at 375 the rule belongs at 720.

There is no frontend test runner here, so this is a source assertion over the
stylesheets. It reads `@media` preludes only — `max-width` is also an ordinary property
(`.page { max-width: 1440px }`) and those are measures, not breakpoints.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_SRC = REPO_ROOT / "web" / "src"

#: The two steps. Split → stack, then phone.
LADDER = {900, 720}

#: `@media` up to its opening brace. Enough to find every width in the prelude,
#: including the `and`-joined ones.
MEDIA_PRELUDE = re.compile(r"@media([^{]*)\{")

#: A width inside a prelude, in px. `em`/`rem` preludes would not match and there are
#: none; a new one should join the ladder rather than invent a unit.
WIDTH = re.compile(r"(max|min)-width:\s*([\d.]+)px")

#: Breakpoints that are deliberately off the ladder, each with the reason it is.
#: A new entry is a decision, not a formality: it means one scene folds at a width no
#: other scene does, and someone will find that on a device rather than in a diff.
EXCEPTIONS: dict[tuple[str, int], str] = {}


def _stylesheets():
    return sorted(WEB_SRC.rglob("*.css"))


def _breakpoints():
    """Every (file, kind, width) a media query in `web/src` narrows at."""
    for path in _stylesheets():
        rel = str(path.relative_to(REPO_ROOT))
        text = path.read_text()
        for prelude in MEDIA_PRELUDE.findall(text):
            for kind, width in WIDTH.findall(prelude):
                yield rel, kind, int(float(width))


def test_every_breakpoint_is_on_the_ladder():
    """Two steps. A third is a scene that folds where nothing else does."""
    strays = [
        f"{rel} @media ({kind}-width: {width}px)"
        for rel, kind, width in _breakpoints()
        if width not in LADDER and EXCEPTIONS.get((rel, width)) is None
    ]

    assert not strays, (
        "these narrow at a width the rest of the app does not: "
        + ", ".join(sorted(strays))
        + f" — the ladder is {sorted(LADDER, reverse=True)}px (900 split → stack, "
        "720 phone). Move the rule onto a step, or add it to EXCEPTIONS with the "
        "reason it is one."
    )


def test_the_gutter_ladder_is_the_ladder():
    """`global.css` owns the two steps; nothing may add a third to `--gutter`.

    The gutter is the symmetry line every full-width edge stands on
    (`docs/SYSTEM-AS-BUILT.md` § Frontend), so a step in it is a step for the whole
    app whether or not a page asked for one.
    """
    text = (WEB_SRC / "global.css").read_text()
    steps = {
        int(float(width))
        for prelude in MEDIA_PRELUDE.findall(text)
        for kind, width in WIDTH.findall(prelude)
    }

    assert steps == LADDER, (
        f"global.css narrows at {sorted(steps, reverse=True)}px; the ladder is "
        f"{sorted(LADDER, reverse=True)}px"
    )


def test_the_ladder_is_documented_where_a_reader_looks():
    """The two steps are named in the architecture notes, not only in a test."""
    frontend = (REPO_ROOT / "docs" / "SYSTEM-AS-BUILT.md").read_text()
    assert "900" in frontend and "720" in frontend
