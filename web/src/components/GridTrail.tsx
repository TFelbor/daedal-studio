import { useEffect, useRef, useState } from 'react';
import styles from './GridTrail.module.css';

interface TrailItem {
  id: string;
  col: number;
  row: number;
  opacity: number;
}

interface GridTrailProps {
  /** Module size, in px. Must match `--module`, which draws the surface grid. */
  module?: number;
}

/**
 * A region of the surface the trail must stay off. `edges` is null when the whole
 * box is painted; otherwise it holds the border widths, because an element that
 * draws nothing but a hairline rule is mostly open space the trail may cross.
 */
interface Obstacle {
  el: Element;
  edges: { top: number; right: number; bottom: number; left: number } | null;
}

interface Box {
  left: number;
  top: number;
  right: number;
  bottom: number;
}

const TRAIL_LIMIT = 14;
const FADE_STEP = 0.05;
const FADE_INTERVAL = 35;

const overlaps = (a: Box, b: Box) =>
  a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;

/** Alpha of a computed colour, so a fully transparent fill does not count as paint. */
function alphaOf(color: string): number {
  if (!color || color === 'transparent') return 0;

  const parsed = /rgba?\(([^)]+)\)/.exec(color);
  if (!parsed) return 1;

  // Both `rgba(r, g, b, a)` and the newer `rgb(r g b / a)` reach us here.
  const [channels, alpha] = parsed[1].split('/');
  if (alpha !== undefined) return parseFloat(alpha) || 0;

  const parts = channels.split(',');
  return parts.length >= 4 ? parseFloat(parts[3]) || 0 : 1;
}

function borderEdges(style: CSSStyleDeclaration) {
  const side = (width: string, borderStyle: string, color: string) =>
    borderStyle !== 'none' && borderStyle !== 'hidden' && alphaOf(color) > 0
      ? parseFloat(width) || 0
      : 0;

  const edges = {
    top: side(style.borderTopWidth, style.borderTopStyle, style.borderTopColor),
    right: side(style.borderRightWidth, style.borderRightStyle, style.borderRightColor),
    bottom: side(style.borderBottomWidth, style.borderBottomStyle, style.borderBottomColor),
    left: side(style.borderLeftWidth, style.borderLeftStyle, style.borderLeftColor),
  };

  return edges.top || edges.right || edges.bottom || edges.left ? edges : null;
}

/**
 * Decides what an element occupies. Anything that carries its own text, has no
 * children, or paints a background is a solid component; an element with only
 * borders contributes its edges and nothing more.
 */
function classify(el: Element): Obstacle | null {
  const style = getComputedStyle(el);
  if (style.display === 'none' || style.visibility === 'hidden') return null;

  const hasOwnText = Array.from(el.childNodes).some(
    (node) => node.nodeType === Node.TEXT_NODE && (node.textContent ?? '').trim() !== '',
  );

  if (hasOwnText || el.children.length === 0) return { el, edges: null };
  if (style.backgroundImage !== 'none' || alphaOf(style.backgroundColor) > 0) {
    return { el, edges: null };
  }

  const edges = borderEdges(style);
  return edges ? { el, edges } : null;
}

/**
 * Walks the page for everything the trail has to avoid. A solid box ends the walk
 * for that branch — its children sit behind it and cannot open space back up — so
 * the list stays short enough to test on every cell the pointer enters. This
 * layer and its ancestors are skipped: the surface they paint is exactly the open
 * space being looked for.
 */
function collectObstacles(layer: Element): Obstacle[] {
  const found: Obstacle[] = [];

  const walk = (el: Element) => {
    for (const child of Array.from(el.children)) {
      if (child === layer) continue;

      if (child.contains(layer)) {
        walk(child);
        continue;
      }

      const obstacle = classify(child);
      if (obstacle) found.push(obstacle);
      if (!obstacle || obstacle.edges) walk(child);
    }
  };

  walk(document.body);
  return found;
}

/** True when the cell, in viewport coordinates, clears every obstacle. */
function cellIsFree(cell: Box, obstacles: Obstacle[]): boolean {
  for (const { el, edges } of obstacles) {
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) continue;

    // A DOMRect carries its values on the prototype, so copy before spreading.
    const box: Box = { left: r.left, top: r.top, right: r.right, bottom: r.bottom };

    if (!edges) {
      if (overlaps(cell, box)) return false;
      continue;
    }

    if (edges.top && overlaps(cell, { ...box, bottom: box.top + edges.top })) return false;
    if (edges.bottom && overlaps(cell, { ...box, top: box.bottom - edges.bottom })) return false;
    if (edges.left && overlaps(cell, { ...box, right: box.left + edges.left })) return false;
    if (edges.right && overlaps(cell, { ...box, left: box.right - edges.right })) return false;
  }

  return true;
}

/**
 * Lights the module the pointer is in, but only where the surface is bare — the
 * margins beside a panel, the padding above a section, the space left of a short
 * row. A cell that would sit behind a control, a reading, a canvas or a rule stays
 * dark, so the trail reads as part of the bench rather than as a wash over the
 * instruments.
 */
export function GridTrail({ module = 56 }: GridTrailProps) {
  const layerRef = useRef<HTMLDivElement | null>(null);
  const [trail, setTrail] = useState<TrailItem[]>([]);

  useEffect(() => {
    const layer = layerRef.current;
    if (!layer) return;

    // A pointer trail is motion for its own sake; it is the first thing to go.
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

    // The obstacle list is cached, but their rectangles are read live, so
    // scrolling and the sticky header need no bookkeeping of their own.
    let obstacles: Obstacle[] | null = null;
    let lastCell: { id: string; free: boolean } | null = null;

    const invalidate = () => {
      obstacles = null;
      lastCell = null;
    };

    const handleMouseMove = (e: MouseEvent) => {
      // The layer spans the surface, so its own box is the grid's origin.
      const origin = layer.getBoundingClientRect();
      const col = Math.floor((e.clientX - origin.left) / module);
      const row = Math.floor((e.clientY - origin.top) / module);
      if (col < 0 || row < 0) return;

      const id = `${col}-${row}`;

      if (lastCell?.id !== id) {
        const left = origin.left + col * module;
        const top = origin.top + row * module;

        if (!obstacles) obstacles = collectObstacles(layer);
        lastCell = {
          id,
          free: cellIsFree(
            { left, top, right: left + module, bottom: top + module },
            obstacles,
          ),
        };
      }

      // Cells already lit keep fading on their own once the pointer moves onto
      // something drawn.
      if (!lastCell.free) return;

      setTrail((prev) => {
        const existing = prev.findIndex((item) => item.id === id);
        if (existing !== -1) {
          const updated = [...prev];
          updated[existing] = { id, col, row, opacity: 1 };
          return updated;
        }
        return [{ id, col, row, opacity: 1 }, ...prev.slice(0, TRAIL_LIMIT - 1)];
      });
    };

    // Routing swaps the whole page under the layer, and a breakpoint can turn a
    // panel's paint on or off — either changes what counts as open space.
    const observer = new MutationObserver((records) => {
      if (records.some((record) => !layer.contains(record.target))) invalidate();
    });
    observer.observe(document.body, {
      attributes: true,
      attributeFilter: ['class', 'style'],
      childList: true,
      subtree: true,
    });

    document.fonts.ready.then(invalidate);
    window.addEventListener('resize', invalidate);
    window.addEventListener('mousemove', handleMouseMove);

    const fade = setInterval(() => {
      setTrail((prev) =>
        prev
          .map((item) => ({ ...item, opacity: item.opacity - FADE_STEP }))
          .filter((item) => item.opacity > 0),
      );
    }, FADE_INTERVAL);

    return () => {
      observer.disconnect();
      clearInterval(fade);
      window.removeEventListener('resize', invalidate);
      window.removeEventListener('mousemove', handleMouseMove);
    };
  }, [module]);

  return (
    <div ref={layerRef} className={styles.layer} aria-hidden="true">
      <svg className={styles.svg}>
        {trail.map((item) => (
          <rect
            key={item.id}
            className={styles.cell}
            x={item.col * module}
            y={item.row * module}
            width={module}
            height={module}
            opacity={item.opacity}
          />
        ))}
      </svg>
    </div>
  );
}
