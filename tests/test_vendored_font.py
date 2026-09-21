"""The lettering font is the one it says it is, and it is attributed.

`tests/test_vendored_skills.py` binds the vendored skills table to the tree in both
directions — a row with no directory attributes something this project does not ship, a
directory with no row ships something it does not attribute. A font is the same kind of
thing and carries the same two failures, plus one the skills do not have: **a font file
is opaque**. Swapping `DejaVuSans-Bold.ttf` for another face is a diff nobody can read,
and the only thing that makes it visible is a digest.

So four facts are tied together here, and the point is that they are *four*:

- the file is present, and so is the `LICENSE` beside it;
- its sha256 is the one `lettering.FONT_SHA256` pins;
- its sha256 is also the one `THIRD-PARTY-NOTICES.md` § 2 attributes;
- its own `name` table says it is the family and weight that row claims.

Any three without the fourth is a hole. The digest alone would not catch a file
attributed to the wrong upstream; the name table alone would not catch a re-cut of the
same family; the notices row alone is prose.
"""
import hashlib
import re
from pathlib import Path

import pytest
from fontTools.ttLib import TTFont

from pythonsrc.organizer import lettering

REPO_ROOT = Path(__file__).resolve().parents[1]
NOTICES = REPO_ROOT / "THIRD-PARTY-NOTICES.md"


@pytest.fixture(scope="module")
def digest() -> str:
    return hashlib.sha256(lettering.FONT_PATH.read_bytes()).hexdigest()


def test_the_font_and_its_licence_are_both_in_the_tree():
    """Redistribution without the notice is the licence violation; the file without the
    font is nothing. Both, or neither."""
    assert lettering.FONT_PATH.is_file(), f"{lettering.FONT_PATH} is missing"
    licence = lettering.FONT_DIR / "LICENSE"
    assert licence.is_file(), "the vendored font ships without its upstream LICENSE"
    text = licence.read_text(encoding="utf-8")
    # The three grants the upstream notice actually carries. Named rather than counted,
    # because "a LICENSE file exists" is satisfied by an empty one.
    assert "Bitstream Vera" in text
    assert "public domain" in text
    assert "Tavmjong Bah" in text, "the Arev grant is part of this notice too"


def test_the_code_pins_the_bytes_that_are_in_the_tree(digest):
    """A font swap has to be a *visible* diff, and a digest is the only thing that makes
    one visible: every lettered STL this project has shipped is a function of these
    bytes."""
    assert lettering.FONT_SHA256 == digest


def test_the_notices_row_attributes_the_bytes_that_are_in_the_tree(digest):
    """The § 2 row abbreviates the digest — a 64-character hash in a table cell is a
    table nobody reads — so both halves of the abbreviation are checked against the real
    one rather than the string being eyeballed."""
    text = NOTICES.read_text(encoding="utf-8")
    row = next((line for line in text.splitlines() if lettering.FONT_FILE in line), None)
    assert row is not None, f"{lettering.FONT_FILE} has no THIRD-PARTY-NOTICES.md § 2 row"
    abbreviated = re.search(r"`([0-9a-f]+)…([0-9a-f]+)`", row)
    assert abbreviated, f"the {lettering.FONT_FILE} row states no sha256: {row}"
    head, tail = abbreviated.groups()
    assert digest.startswith(head) and digest.endswith(tail), row
    assert "Bitstream Vera" in row, "the row must name the licence it is attributing"


def test_the_file_is_the_face_the_notices_claim():
    """A digest catches a swapped file; this catches a *wrong* one attributed correctly —
    the name table is the font's own claim about itself, and it is what a person reading
    the § 2 row is being told."""
    font = TTFont(str(lettering.FONT_PATH), lazy=True)
    names = font["name"]
    assert names.getDebugName(1) == lettering.FONT_FAMILY
    assert names.getDebugName(2) == lettering.FONT_SUBFAMILY
    row = next(
        line for line in NOTICES.read_text(encoding="utf-8").splitlines()
        if lettering.FONT_FILE in line
    )
    assert "DejaVu" in row


def test_the_outlines_are_quadratic_and_the_font_downloads_nothing():
    """`glyf`, not `CFF `: the flattening pen implements both curve kinds, but a font that
    swapped one for the other would change every glyph's vertex count and therefore every
    lettered STL's bytes. And nothing here is resolved at runtime — the path is a
    constant under this package, not a lookup."""
    font = TTFont(str(lettering.FONT_PATH), lazy=True)
    assert "glyf" in font and "CFF " not in font
    assert lettering.FONT_PATH.parent == lettering.FONT_DIR
    assert lettering.FONT_DIR.parent == Path(lettering.__file__).resolve().parent


def test_nothing_reads_matplotlib_s_private_font_directory():
    """The font would otherwise move with a matplotlib upgrade, and so would every
    lettered STL already shipped — which is the whole reason it is vendored. Asserted as
    a grep over the organizer package rather than trusted to review.

    The patterns are the *reaches*, not the word: `lettering.py`'s own docstring names
    matplotlib in order to say it is not used, and a test that failed on the explanation
    of a rule would get the explanation deleted rather than the rule kept.
    """
    package = REPO_ROOT / "pythonsrc" / "organizer"
    forbidden = ("import matplotlib", "from matplotlib", "mpl-data", "font_manager", "findfont")
    for path in package.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        for pattern in forbidden:
            assert pattern not in source, f"{path} resolves a font at runtime ({pattern})"
