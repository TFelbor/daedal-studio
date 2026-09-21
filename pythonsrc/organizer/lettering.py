"""Glyph outlines from the vendored font: where an emboss gets its shape.

The decorative tier (F13, issue #157) raises or recesses text on a face of an
organizer, and this is the half of it that has no kernel in it. Text becomes a **2D
outline** — the glyph contours of a font file, flattened to straight segments and laid
out along a baseline — and `compiler.text_outline` turns that outline into a
`manifold3d.CrossSection` which is extruded and unioned on or subtracted out. Same
kernel, same `CrossSection → extrude` idiom `card_divider` and `base_chamfer` already
build with, and **no horizontal fillet anywhere**, so the OCCT trigger in
`ARCHITECTURE.md` § The geometry kernel is not met: text did not reopen it.

The split is deliberate and it is the api-server's. This module imports `fontTools` and
the standard library and nothing else — no numpy, no `manifold3d` — because
`POST /organizer/resolve` has to tell a person their text does not fit *while they are
typing it*, and the api-server image has no geometry kernel. Width and height are font
metric arithmetic, so they live here; the stroke floor needs the kernel and lives in
`compiler.py`, which is Phase 2.

Three properties this module is built to have, each for the same reason the spec schema
has its own three: **the same spec must compile to the same mesh, byte for byte.**

- **The font is committed, not resolved.** A system font is not reproducible across two
  machines and a downloaded one is not reproducible across two days. The file sits in
  `fonts/` beside this module, is pinned by `FONT_SHA256`, and `tests/test_vendored_font.py`
  binds that hash to the file, to the `LICENSE` beside it and to the
  `THIRD-PARTY-NOTICES.md` row — so a font swap is a visible diff and never a silent one.
  **Not `matplotlib.textpath`**, which reads the same outlines out of a plotting
  library's private data directory: the font would then move with a matplotlib upgrade,
  and so would every lettered STL this project has shipped.
- **Curves are flattened at a fixed segment count.** `GLYPH_CURVE_SEGMENTS`, passed
  nowhere and read from here, for `compiler.CIRCULAR_SEGMENTS`' reason: a count that
  varied with the glyph, the size or the interpreter's global state would make one spec
  compile to two meshes.
- **There is no kerning, and no fallback font.** Glyphs are placed on their `hmtx`
  advances, which is very slightly loose between an A and a V and is the same width
  every time. A character the font has no glyph for is **refused by name** rather than
  substituted: a box that came out with a hollow rectangle where a person's name should
  be is worse than a box that was never printed.

The cap height is read from the `H` glyph rather than from `OS/2.sCapHeight`, because
this font declares `OS/2` version 1 and that field does not exist in it. `H` is flat
topped and flat bottomed in every Latin face, so its ink bounding box *is* the cap
height by definition — a measurement rather than a table lookup, which is this
repository's habit anyway.
"""
from __future__ import annotations

import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Optional, Tuple

from fontTools.pens.basePen import BasePen
from fontTools.ttLib import TTFont

#: One contour as (x, y) pairs, closed implicitly (the last point joins the first).
Contour = Tuple[Tuple[float, float], ...]

#: The vendored face. Unmodified and unsubsetted — a subset is a Modified Version under
#: the Bitstream Vera licence and would have to be renamed, so the file here is the file
#: upstream ships. See `THIRD-PARTY-NOTICES.md` § 2 for why this one and not the app's
#: own Barlow.
FONT_DIR = Path(__file__).resolve().parent / "fonts"
FONT_FILE = "DejaVuSans-Bold.ttf"
FONT_PATH = FONT_DIR / FONT_FILE
#: sha256 of `FONT_PATH`. The same digest is in `THIRD-PARTY-NOTICES.md` § 2, and
#: `tests/test_vendored_font.py` fails when the three disagree.
FONT_SHA256 = "b184b89e3c1075f22f6b71575b6fc20d4972b3cfd3b23322ca6fd596dcaef167"
#: What the font's own `name` table says it is. Asserted, not assumed: a file swapped
#: under this path would otherwise letter every part in a typeface nobody chose.
FONT_FAMILY = "DejaVu Sans"
FONT_SUBFAMILY = "Bold"

#: Straight segments each quadratic or cubic curve of a glyph is flattened into.
#:
#: Chosen from the chord error, like `compiler.CIRCULAR_SEGMENTS`. A TrueType glyph is
#: made of many short quadratics — DejaVu's `O` uses a dozen per side — so the second
#: difference of one segment is well under a quarter of the cap height. The sagitta of a
#: quadratic split into `n` chords is `|P₀ − 2P₁ + P₂| / (8n²)`, which at `n = 16` and a
#: 6 mm cap height is under 0,4 µm: two orders inside N1's ±0,05 mm, and four inside the
#: float32 STL noise floor. Doubling it would buy nothing measurable and cost vertices.
GLYPH_CURVE_SEGMENTS = 16

#: Longest text an emboss may carry, in characters. Bounded for `JobRequest.prompt`'s
#: reason — an unbounded string is an unbounded prompt channel — and because no face of
#: any archetype here is long enough for more. Exported so `server/app.py` and
#: `web/src/organizer/spec.ts` bound the same box; `tests/test_composer_options.py`
#: binds the three.
EMBOSS_TEXT_MAX_CHARS = 64


class LetteringError(ValueError):
    """The font cannot set this text. The finding is the message."""


@lru_cache(maxsize=1)
def font() -> TTFont:
    """The vendored font, parsed once.

    Cached because a `TTFont` is immutable as this module uses it — contours are read
    and never written — and reparsing a 688 KiB file per glyph would put a tenth of a
    second into every compile for nothing.
    """
    if not FONT_PATH.is_file():
        raise LetteringError(
            f"the lettering font is missing from {FONT_PATH}; it is vendored in this "
            "repository on purpose — see THIRD-PARTY-NOTICES.md § 2"
        )
    return TTFont(str(FONT_PATH), lazy=True)


@lru_cache(maxsize=1)
def units_per_em() -> int:
    """The font's design grid. 2048 for this file; read rather than assumed."""
    return int(font()["head"].unitsPerEm)


@lru_cache(maxsize=1)
def cap_height_units() -> float:
    """The cap height, in font units, measured off the `H` glyph's ink.

    Not `OS/2.sCapHeight`: this font declares `OS/2` version 1, which has no such field,
    and a table lookup that silently falls back to the ascender would set every part's
    lettering a sixth too tall. `H` is flat topped and flat bottomed, so its ink top *is*
    the cap height.
    """
    top = _glyph_bounds("H")
    if top is None:
        raise LetteringError("the lettering font has no 'H' to read a cap height from")
    return float(top[3])


@lru_cache(maxsize=1)
def _cmap() -> dict:
    return font().getBestCmap()


@lru_cache(maxsize=1)
def _glyph_set():
    return font().getGlyphSet()


class _FlattenPen(BasePen):
    """A pen that records one glyph as closed polygons of straight segments.

    `BasePen` does the two things a glyph reader must not get wrong by hand: it
    decomposes composite glyphs (every accented character in this font is one) against
    the glyph set it was given, and it resolves TrueType's implied on-curve points, so
    `_qCurveToOne` always arrives as a plain (control, end) pair.
    """

    def __init__(self, glyph_set) -> None:
        super().__init__(glyph_set)
        self.contours: list[list[tuple[float, float]]] = []
        self._current: list[tuple[float, float]] = []

    def _moveTo(self, pt) -> None:
        self._flush()
        self._current = [(float(pt[0]), float(pt[1]))]

    def _lineTo(self, pt) -> None:
        self._current.append((float(pt[0]), float(pt[1])))

    def _qCurveToOne(self, control, end) -> None:
        ax, ay = self._current[-1]
        bx, by = control
        cx, cy = end
        for i in range(1, GLYPH_CURVE_SEGMENTS + 1):
            t = i / GLYPH_CURVE_SEGMENTS
            s = 1.0 - t
            self._current.append(
                (s * s * ax + 2 * s * t * bx + t * t * cx,
                 s * s * ay + 2 * s * t * by + t * t * cy)
            )

    def _curveToOne(self, c1, c2, end) -> None:
        ax, ay = self._current[-1]
        bx, by = c1
        cx, cy = c2
        dx, dy = end
        for i in range(1, GLYPH_CURVE_SEGMENTS + 1):
            t = i / GLYPH_CURVE_SEGMENTS
            s = 1.0 - t
            self._current.append(
                (s ** 3 * ax + 3 * s * s * t * bx + 3 * s * t * t * cx + t ** 3 * dx,
                 s ** 3 * ay + 3 * s * s * t * by + 3 * s * t * t * cy + t ** 3 * dy)
            )

    def _closePath(self) -> None:
        self._flush()

    def _endPath(self) -> None:
        self._flush()

    def _flush(self) -> None:
        points = self._current
        self._current = []
        # Drop the closing duplicate the outline may carry: a contour is closed
        # implicitly here, and a repeated vertex is a zero-length edge the kernel then
        # has to collapse. `card_divider.outline` drops them for the same reason.
        while len(points) > 1 and _same(points[0], points[-1]):
            points.pop()
        if len(points) > 2:
            self.contours.append(points)


def _same(a: tuple[float, float], b: tuple[float, float]) -> bool:
    return abs(a[0] - b[0]) < 1e-9 and abs(a[1] - b[1]) < 1e-9


def has_glyph(character: str) -> bool:
    """Whether the font can set this character at all."""
    return ord(character) in _cmap()


def missing_characters(text: str) -> tuple[str, ...]:
    """Every character of `text` the font has no glyph for, in order, deduplicated.

    Refused rather than substituted — see this module's docstring. A space is a glyph
    like any other and is present; a character that is not is named.
    """
    seen: list[str] = []
    for character in text:
        if not has_glyph(character) and character not in seen:
            seen.append(character)
    return tuple(seen)


@lru_cache(maxsize=256)
def glyph_contours(character: str) -> tuple[Contour, ...]:
    """One character's closed contours, in **font units**, on its own baseline.

    Cached per character: the contours are a property of the pinned font, so the work is
    done once per interpreter however many times a word repeats a letter. A space — or
    any glyph with no ink — yields an empty tuple.

    Raises:
        LetteringError: If the font has no glyph for the character.
    """
    if not has_glyph(character):
        raise LetteringError(
            f"the lettering font has no glyph for {character!r} "
            f"(U+{ord(character):04X}, {unicodedata.name(character, 'unnamed')})"
        )
    glyph_set = _glyph_set()
    pen = _FlattenPen(glyph_set)
    glyph_set[_cmap()[ord(character)]].draw(pen)
    pen._flush()
    return tuple(tuple(contour) for contour in pen.contours)


@lru_cache(maxsize=256)
def advance_units(character: str) -> float:
    """The character's advance width in font units — how far the pen moves after it."""
    if not has_glyph(character):
        raise LetteringError(f"the lettering font has no glyph for {character!r}")
    return float(_glyph_set()[_cmap()[ord(character)]].width)


@lru_cache(maxsize=256)
def _glyph_bounds(character: str) -> Optional[tuple[float, float, float, float]]:
    """`(x_min, y_min, x_max, y_max)` of the character's ink, or None when it has none."""
    contours = glyph_contours(character)
    if not contours:
        return None
    xs = [x for contour in contours for x, _ in contour]
    ys = [y for contour in contours for _, y in contour]
    return min(xs), min(ys), max(xs), max(ys)


def scale_for(cap_height_mm: float) -> float:
    """Font units → mm, for text set at this cap height."""
    height = float(cap_height_mm)
    if not (height > 0.0):
        raise LetteringError(f"the cap height must be a positive number of mm, got {cap_height_mm!r}")
    return height / cap_height_units()


def _laid_out_units(text: str) -> list[tuple[float, Contour]]:
    """Every contour of `text`, shifted onto its glyph's pen position, in font units.

    The layout, and the whole of it: each glyph is drawn where the pen stands and the pen
    then moves by the glyph's own advance. **No kerning** — see the module docstring —
    so an `AV` pair is a hair loose and is the same width on every machine that compiles
    the spec.
    """
    pen_x = 0.0
    out: list[tuple[float, Contour]] = []
    for character in text:
        for contour in glyph_contours(character):
            out.append((pen_x, contour))
        pen_x += advance_units(character)
    return out


def ink_bounds_units(text: str) -> Optional[tuple[float, float, float, float]]:
    """`(x_min, y_min, x_max, y_max)` of the whole string's ink, in font units.

    The **ink** box rather than the advance box, and both halves of the layout agree on
    it: the block is centred on this rectangle and it is this rectangle that has to fit
    the face. Centring on the advance box instead would balance the side bearings and
    put a single `I` visibly off-centre on a tab, which is the one case a person checks
    by eye. Returns None for text with no ink at all (a space, or nothing).
    """
    xs: list[float] = []
    ys: list[float] = []
    for offset, contour in _laid_out_units(text):
        for x, y in contour:
            xs.append(x + offset)
            ys.append(y)
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def ink_extent_mm(text: str, cap_height_mm: float) -> tuple[float, float]:
    """`(width, height)` of the string's ink at this cap height, in mm.

    `(0, 0)` for text with no ink. What `lettering_problems` compares against the face's
    usable rectangle, and what `POST /organizer/resolve` can answer with while somebody
    is still typing — it is font metric arithmetic and needs no kernel.
    """
    bounds = ink_bounds_units(text)
    if bounds is None:
        return 0.0, 0.0
    scale = scale_for(cap_height_mm)
    x0, y0, x1, y1 = bounds
    return (x1 - x0) * scale, (y1 - y0) * scale


def largest_cap_height_mm(text: str, width_mm: float, height_mm: float) -> float:
    """The tallest cap height at which `text` still fits `width_mm × height_mm`, in mm.

    The remedy a fit refusal names, and it is **computed rather than applied**: the
    engine refuses with a measurement and lets a person decide, because silently
    shrinking a part's lettering is the same fabrication as silently shrinking the part.
    Zero when the text has no ink or the rectangle has no room.
    """
    width, height = ink_extent_mm(text, 1.0)
    if width <= 0.0 and height <= 0.0:
        return 0.0
    limits = [float(width_mm) / width] if width > 0.0 else []
    if height > 0.0:
        limits.append(float(height_mm) / height)
    return max(0.0, min(limits)) if limits else 0.0


def text_contours(text: str, cap_height_mm: float) -> list[Contour]:
    """Every contour of `text` at this cap height, in mm, **centred on the origin**.

    Centred rather than set from a corner because every caller places it on the middle of
    a face: `Emboss` carries no position field — as `Insert` carries none — so there is
    exactly one place the text goes, and returning it already there means no archetype
    re-derives the centring and gets it half a millimetre different from the next one.

    Raises:
        LetteringError: If the font has no glyph for some character, or the cap height
            is not positive.
    """
    scale = scale_for(cap_height_mm)
    bounds = ink_bounds_units(text)
    if bounds is None:
        return []
    x0, y0, x1, y1 = bounds
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    return [
        tuple(((x + offset - cx) * scale, (y - cy) * scale) for x, y in contour)
        for offset, contour in _laid_out_units(text)
    ]


def distinct_inked_characters(text: str) -> tuple[str, ...]:
    """The characters of `text` that carry ink, deduplicated, in first-seen order.

    What the stroke floor is measured over. A space has no stroke and no thinnest one,
    and measuring it would return infinity or zero depending on which mistake was made.
    """
    seen: list[str] = []
    for character in text:
        if character not in seen and glyph_contours(character):
            seen.append(character)
    return tuple(seen)


def text_problems(text: object, field: str) -> list[str]:
    """Schema-level findings about an emboss string, each naming `field`.

    Here rather than in `spec.py` so that the rules about *this font* stay with the font.
    `Emboss.__post_init__` owns the shape rules (a string, bounded, no control
    characters), which are true of any font; whether a glyph exists is true of this one.
    """
    if not isinstance(text, str):
        return [f"{field} must be a string, got {type(text).__name__}"]
    missing = missing_characters(text)
    if not missing:
        return []
    named = ", ".join(f"{c!r} (U+{ord(c):04X})" for c in missing)
    return [
        f"{field} uses {named}, which the lettering font "
        f"({FONT_FAMILY} {FONT_SUBFAMILY}) has no glyph for. Use characters the font "
        "can set — a part with a hollow box where a name should be is worse than one "
        "that was never printed"
    ]
