#!/usr/bin/env python3
"""Draw the home-screen icons from the same geometry as `web/public/favicon.svg`.

Run it when the mark changes:

    python infra/scripts/make_pwa_icons.py

Why a script rather than an export. There was no bitmap of the mark above 180px in this
repository — `apple-touch-icon.png` is the largest — and a 512px launcher icon upsampled
from 180 is visibly soft on exactly the screen that shows it biggest. There is also no
SVG rasteriser in the dependency tree, and adding one to draw four rectangles and two
quadrilaterals would be a licence decision (`docs/SYSTEM-AS-BUILT.md` § Licensing
Constraints) taken for no reason. Pillow is already a dependency, and the mark is
straight edges and mitred corners by design — "no curve anywhere in this identity" — so
it can simply be drawn.

The numbers below are the SVG's, on its own 64-unit grid, so the two cannot drift
without someone editing both. `tests/test_pwa_shell.py` checks the outputs exist at the
sizes the manifest claims.

**The maskable cut is a different drawing, not a different size.** Android composites a
launcher icon through a mask it chooses — circle, squircle, teardrop — and guarantees
only the central 80% circle survives it. The mark reaches 84% of the grid vertically, so
the "any" cut loses the filament feed and the bottom layer under a circular mask. The
maskable cut draws the same geometry at 0.72 scale on a full-bleed ground, which puts
every lit pixel inside the safe circle and lets the ground take the crop — which is what
it is for.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

REPO_ROOT = Path(__file__).resolve().parents[2]
PUBLIC = REPO_ROOT / "web" / "public" / "icons"

#: The favicon's ground and its one orange, copied from `web/public/favicon.svg`.
GROUND = (13, 13, 13, 255)
ACCENT = (235, 135, 36, 255)

#: The SVG's viewBox. Every coordinate below is on this grid.
GRID = 64.0

#: Supersampling factor. The mark is all straight edges, and a mitred corner rendered at
#: 1× has a visibly ragged diagonal; drawing at 8× and resampling down is cheaper to
#: write than anti-aliasing each polygon by hand.
SUPERSAMPLE = 8

Point = tuple[float, float]


def _offset_polygon(points: list[Point], distance: float) -> list[Point]:
    """Offset a closed polygon by `distance`, mitring the corners.

    Positive is one side and negative the other; which is which depends on the winding,
    so callers ask for both and keep the one they wanted. Each edge is moved along its
    normal and consecutive edges are intersected, which is what a mitre join is.
    """
    count = len(points)
    lines = []
    for index in range(count):
        (x1, y1), (x2, y2) = points[index], points[(index + 1) % count]
        dx, dy = x2 - x1, y2 - y1
        length = (dx * dx + dy * dy) ** 0.5
        nx, ny = -dy / length, dx / length
        lines.append((x1 + nx * distance, y1 + ny * distance, x2 + nx * distance, y2 + ny * distance))

    out: list[Point] = []
    for index in range(count):
        ax1, ay1, ax2, ay2 = lines[index - 1]
        bx1, by1, bx2, by2 = lines[index]
        adx, ady = ax2 - ax1, ay2 - ay1
        bdx, bdy = bx2 - bx1, by2 - by1
        denominator = adx * bdy - ady * bdx
        if abs(denominator) < 1e-9:  # collinear edges have no corner to mitre
            out.append((bx1, by1))
            continue
        t = ((bx1 - ax1) * bdy - (by1 - ay1) * bdx) / denominator
        out.append((ax1 + adx * t, ay1 + ady * t))
    return out


def _area(points: list[Point]) -> float:
    total = 0.0
    for index, (x1, y1) in enumerate(points):
        x2, y2 = points[(index + 1) % len(points)]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2


def _stroked_polygon(draw: ImageDraw.ImageDraw, points: list[Point], width: float, scale) -> None:
    """A closed polygon outline of `width`, centred on the path, drawn as a filled ring.

    Pillow's `polygon(outline=…, width=…)` does not mitre, and this identity has no
    curve in it: a rounded corner on the nozzle would be the one in the whole product.
    So the ring is drawn instead — the outer offset filled in the accent, the inner
    offset filled back to the ground.
    """
    first = _offset_polygon(points, width / 2)
    second = _offset_polygon(points, -width / 2)
    outer, inner = (first, second) if _area(first) > _area(second) else (second, first)
    draw.polygon([scale(p) for p in outer], fill=ACCENT)
    draw.polygon([scale(p) for p in inner], fill=GROUND)


def draw_mark(size: int, *, inset: float = 1.0) -> Image.Image:
    """The mark at `size` px. `inset` shrinks the drawing inside a full-bleed ground."""
    canvas = size * SUPERSAMPLE
    image = Image.new("RGBA", (canvas, canvas), GROUND)
    draw = ImageDraw.Draw(image)

    unit = canvas / GRID * inset
    origin = (canvas - GRID * unit) / 2

    def scale(point: Point) -> Point:
        return (origin + point[0] * unit, origin + point[1] * unit)

    def rect(x: float, y: float, w: float, h: float, fill=ACCENT) -> None:
        draw.rectangle([scale((x, y)), scale((x + w, y + h))], fill=fill)

    # Filament feeding in — a 4-wide butt-capped line from (32,8) to (32,15).
    rect(30, 8, 4, 7)

    # Nozzle body, squared off, stroked 4 with mitre joins.
    _stroked_polygon(draw, [(22, 15), (42, 15), (36, 27), (28, 27)], 4, scale)

    # The bead leaving the tip — filled, not stroked.
    draw.polygon([scale(p) for p in [(28, 28), (36, 28), (34, 33), (30, 33)]], fill=ACCENT)

    # Three laid layers. The top one is being written now; the two under it have cooled,
    # which is what the stepped opacity says. Composited here rather than left as alpha:
    # a launcher icon is pasted onto a wallpaper, and a translucent hole in it would show
    # the wallpaper through the print.
    for y, opacity in ((38, 1.0), (47, 0.72), (56, 0.5)):
        blend = tuple(
            round(g + (a - g) * opacity) for g, a in zip(GROUND, ACCENT, strict=True)
        )
        rect(17, y, 30, 6, fill=blend)

    return image.resize((size, size), Image.LANCZOS)


def main() -> int:
    PUBLIC.mkdir(parents=True, exist_ok=True)
    written = []
    for size in (192, 512):
        path = PUBLIC / f"icon-{size}.png"
        draw_mark(size).save(path)
        written.append(path)
    # 0.72 of the grid: the mark's own bounding box is then 0.34 x 0.61 of the icon,
    # whose half-diagonal is 0.35 — inside the 0.40 radius Android guarantees.
    maskable = PUBLIC / "icon-maskable-512.png"
    draw_mark(512, inset=0.72).save(maskable)
    written.append(maskable)

    for path in written:
        print(path.relative_to(REPO_ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
