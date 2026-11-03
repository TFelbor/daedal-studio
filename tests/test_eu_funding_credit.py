"""The app carries the EU funding credit, and carries it the way the grant says to.

Daedal Studio is funded by the European Union through 28DIGITAL's Venture Incubation
Program, and on 2026-09-24 the MVP — this repository — was settled as a *major result
funded* by it. Under the Prize Agreement (Annex I, MGA Art. 17.2; Rules & Regulations
§7.10) that obliges the product to show **element B**, the EU emblem with "Funded by the
European Union", and the page that shows it names the program, so it carries
**disclaimer C** as well. **Element A**, 28DIGITAL's lock-up, is a website obligation;
the page carries it too, beside B, the way the landing page does. Skipping a required
mark lets 28DIGITAL reduce the prize.

The rules are the landing-page repository's `docs/eu-visibility-rules.md`; this file
pins the ones a later edit could break without anyone noticing in a diff:

*   the disclaimer is a quotation, so it is compared character for character;
*   the emblem and the lock-up are official artwork, shown whole and in their own
    colours, so the files are pinned by digest and the stylesheet may not filter, fade or
    clip them;
*   the emblem is at least as prominent as any logo next to it — the 28DGTL square in
    the lock-up beside it, and ours in the nav;
*   "Funded by", never "Co-funded by"; and "Initiated by the EIT" describes 28DIGITAL,
    not us, so it may appear only inside 28DIGITAL's own lock-up — the artwork, and the
    one text alternative that stands for it — and nowhere else in the app;
*   the page is reachable from every page, which means the footer;
*   and, from the founders' 22 September decisions, the page never says "AI".

There is no frontend test runner here, so like `tests/test_ui_product_copy.py` this
reads the sources as text. It catches a deletion or a reintroduction, not a rewording.
"""

import hashlib
import re
from pathlib import Path

import pytest

from tests.test_ui_product_copy import _sources, _visible_text

REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_SRC = REPO_ROOT / "web/src"
ABOUT = WEB_SRC / "pages/About.tsx"
ABOUT_CSS = WEB_SRC / "pages/About.module.css"
APP = WEB_SRC / "App.tsx"

#: Disclaimer C as the rules give it. Not reworded, not split, not shortened.
DISCLAIMER = (
    "Funded by the European Union. Views and opinions expressed are however those of "
    "the author(s) only and do not necessarily reflect those of the European Union or "
    "28DIGITAL. Neither the European Union nor 28DIGITAL can be held responsible for them."
)

#: The artwork, byte for byte as it sits in the landing-page repository's `public/`
#: (git blobs 78a4012f and 28f26961 for the emblem, d6c4dc7d and d28eb5f2 for the
#: lock-up). The 28DIGITAL Intranet, where the official files live, could not be logged
#: into, so this is the artwork the founders settled on. A re-export, a recolour or a
#: crop changes the digest — which is the point: the only legitimate reason to change
#: these is a newer official file.
ARTWORK_SHA256 = {
    "web/src/assets/funded_by_eu-dark.png": (
        "775f1018eb08dc6bc1d0b906d5bb4adbdc709d07b56b7b19872333abd382fc28"
    ),
    "web/src/assets/funded_by_eu-light.png": (
        "db6b23c1ab66f3af510c13363a58efab6da1b2877c162c1902fa272a32bb7a04"
    ),
    "web/src/assets/eit_dgtl_banner-dark.png": (
        "8a494d7eefdf835a47a7bf72771df9be6c2c53523632e0a3f9f9319fa260956f"
    ),
    "web/src/assets/eit_dgtl_banner-light.png": (
        "bd2f60dfa579e738edf677b3c1a067c830540c0aea00ba60d48299f16cffa1f6"
    ),
}

#: How much of each file's height the part that counts for prominence fills, measured
#: on the pinned files above (rows with alpha > 40): the EU flag in the emblem, and the
#: 28DGTL square in the lock-up. The digests are what make these facts rather than
#: estimates — a new file means measuring again.
FLAG_IN_EMBLEM = {"dark": 104 / 108, "light": 104 / 120}
LOGO_IN_LOCKUP = {"dark": 139 / 142, "light": 138 / 142}

#: The lock-up's text alternative: the one string in the app allowed to name the EIT.
LOCKUP_ALT = "28DIGITAL — Initiated by the European Institute of Innovation and Technology (EIT)"

#: What would recolour, fade, crop or distort the artwork. `object-fit: contain` is the
#: one sizing rule that can do none of those, and it is what both images use.
FORBIDDEN_ON_THE_EMBLEM = [
    "filter",
    "opacity",
    "mix-blend-mode",
    "clip-path",
    "mask",
    "overflow",
    "object-fit: cover",
    "object-fit: fill",
    "transform",
]


def _css_rule(text: str, selector: str) -> str:
    """The declarations of every `selector { ... }` block, joined.

    Includes the ones inside `@media`: a phone-only filter is still a recolour.
    """
    pattern = re.compile(rf"(?<![\w-]){re.escape(selector)}\s*\{{([^}}]*)\}}")
    return "\n".join(pattern.findall(text))


def _function_body(text: str, name: str) -> str:
    start = text.index(f"function {name}(")
    end = text.index("\n}\n", start)
    return text[start:end]


def test_the_disclaimer_is_quoted_verbatim():
    assert f"'{DISCLAIMER}'" in ABOUT.read_text(), (
        "About.tsx no longer carries disclaimer C word for word. It is a quotation the "
        "Prize Agreement asks for, not copy — restore it exactly."
    )


def test_the_disclaimer_is_rendered_beside_the_emblem():
    about = _visible_text(ABOUT)
    assert "{EU_DISCLAIMER}" in about
    assert 'alt="Funded by the European Union"' in about, (
        "The emblem's text alternative is the funding statement itself. Without it a "
        "screen reader is told nothing about element B."
    )


@pytest.mark.parametrize("path, digest", sorted(ARTWORK_SHA256.items()))
def test_the_emblem_is_the_official_artwork_unaltered(path, digest):
    actual = hashlib.sha256((REPO_ROOT / path).read_bytes()).hexdigest()
    assert actual == digest, (
        f"{path} is not the artwork it was. The EU emblem may not be recoloured, "
        "cropped or redrawn; replace it only with a newer official file, and update "
        "the digest here with where that file came from."
    )


@pytest.mark.parametrize("artwork", ["funded_by_eu", "eit_dgtl_banner"])
def test_both_grounds_get_their_own_artwork(artwork):
    """One file per theme, swapped by the theme — never one file tinted to fit.

    Each `-dark` file has white lettering and disappears on the light ground; each
    `-light` file has dark lettering for it. A CSS filter would make one file serve
    both, and that is recolouring the emblem.
    """
    about = ABOUT.read_text()
    assert f"../assets/{artwork}-dark.png" in about
    assert f"../assets/{artwork}-light.png" in about
    assert "useTheme()" in about


@pytest.mark.parametrize("selector", [".emblem", ".lockup"])
def test_nothing_recolours_or_crops_the_artwork(selector):
    declarations = _css_rule(ABOUT_CSS.read_text(), selector)
    assert declarations, f"About.module.css has no `{selector}` rule; the test cannot see it."
    for forbidden in FORBIDDEN_ON_THE_EMBLEM:
        assert forbidden not in declarations, (
            f"`{selector}` sets {forbidden!r}. Official artwork is shown whole and in its "
            "own colours — no filter, fade, blend, clip or stretch."
        )
    assert "style=" not in _visible_text(ABOUT), (
        "An inline style in About.tsx can do what the stylesheet is forbidden to."
    )


def _css_height(selector: str) -> int:
    match = re.search(r"height:\s*(\d+)px", _css_rule(ABOUT_CSS.read_text(), selector))
    assert match, f"`{selector}` states no height in px; the test cannot compare it."
    return int(match.group(1))


def test_the_emblem_is_at_least_as_prominent_as_our_logo():
    """The emblem may not be smaller than any logo on screen with it, ours included.

    The only Daedal mark on the page is the nav's wordmark, sized in `App.tsx`.
    """
    mark = re.search(r"<Wordmark size=\{(\d+)\}", APP.read_text())
    assert mark
    assert _css_height(".emblem") >= int(mark.group(1)), (
        f"The emblem is {_css_height('.emblem')}px and the Daedal mark {mark.group(1)}px. "
        "The EU emblem has to be at least as prominent as any logo beside it."
    )


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_the_emblem_is_at_least_as_prominent_as_the_28digital_logo(theme):
    """The logo beside the emblem is 28DIGITAL's, and the flag must not be the smaller.

    Compared as drawn, not as boxes: the lock-up is a wide strip whose 28DGTL square
    fills almost its whole height, while the emblem's flag sits inside some transparent
    margin — so equal CSS heights would put a bigger logo next to a smaller flag. Both
    files swap with the theme, so each pair is checked on its own.
    """
    flag = _css_height(".emblem") * FLAG_IN_EMBLEM[theme]
    logo = _css_height(".lockup") * LOGO_IN_LOCKUP[theme]
    assert flag >= logo, (
        f"On the {theme} ground the EU flag is drawn ~{flag:.0f}px tall and the 28DGTL "
        f"logo beside it ~{logo:.0f}px. Lower `.lockup` or raise `.emblem`."
    )


def test_the_eit_is_named_only_as_the_lockups_text_alternative():
    """The phrase lives in one constant, and that constant is only ever an `alt`.

    A second use — a caption, a heading, a sentence under our name — is exactly the
    misstatement the rules forbid, so the constant is counted rather than trusted.
    """
    about = _visible_text(ABOUT)
    assert f"const LOCKUP_ALT = '{LOCKUP_ALT}';" in about
    assert about.count("LOCKUP_ALT") == 2, (
        "LOCKUP_ALT is used somewhere other than its definition and the lock-up's alt."
    )
    assert "alt={LOCKUP_ALT}" in about
    lockup_img = about[about.rindex("<img", 0, about.index("alt={LOCKUP_ALT}")):]
    assert "src={lockup.src}" in lockup_img.split("/>", 1)[0], (
        "LOCKUP_ALT is the alt of an image that is not the lock-up."
    )


def test_the_page_is_routed_and_reachable_from_every_page():
    app = APP.read_text()
    assert '<Route path="/about" element={<About />} />' in app
    assert 'to="/about"' in _function_body(app, "Attribution"), (
        "The footer no longer links to /about. The footer is the one element on every "
        "page; without the link the funding credit is a page nobody can reach."
    )


@pytest.mark.parametrize(
    "phrase",
    [r"co-?funded", r"initiated by", r"\bEIT\b", r"European Institute of Innovation"],
)
def test_the_app_misstates_nothing_about_the_funding(phrase):
    """"Funded by", never "Co-funded by" — and the EIT is never credited under our name.

    "Initiated by the EIT" is 28DIGITAL's description, legitimate only inside 28DIGITAL's
    own lock-up (element A). The one place the app spells it out is the lock-up's text
    alternative, which is removed before the search — and pinned by the test above — so
    none of these may appear anywhere else the app renders. Comments are excluded, so a
    file may explain the rule without failing it.
    """
    pattern = re.compile(phrase, re.IGNORECASE if phrase.islower() else 0)
    offenders = [
        str(p.relative_to(REPO_ROOT))
        for p in _sources()
        if pattern.search(_visible_text(p).replace(f"'{LOCKUP_ALT}'", ""))
    ]
    assert offenders == [], f"{offenders} render {phrase!r}. See the docstring above."


def test_the_page_does_not_say_ai():
    """Public copy says what the product does — "calculated from your sleeves" — and
    never "AI" (founders' decision, 22 September 2026)."""
    assert not re.search(r"\bAI\b", _visible_text(ABOUT))
