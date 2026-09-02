/**
 * The app has two grounds now, not one.
 *
 * The dark ground is still the identity and still the default — this audience
 * overlaps gamers, makers and developers, all of whom work in dark tools — but
 * the light sheet is complete and the toggle is real. The choice is the
 * viewer's; we only pick the first one for them.
 *
 * Resolution order, and it matters: an explicit stored choice always wins,
 * because someone who has flipped the switch has said what they want and the OS
 * changing at sunset must not overrule them. Only when nothing is stored do we
 * read `prefers-color-scheme`, and only then do we keep following it.
 */

export type Theme = 'dark' | 'light';

const STORAGE_KEY = 'ds.theme';
const DEFAULT: Theme = 'dark';

/** Everything drawn rather than styled — canvas, WebGL — has to be told to repaint. */
const listeners = new Set<(theme: Theme) => void>();

function stored(): Theme | null {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    return v === 'dark' || v === 'light' ? v : null;
  } catch {
    // Private windows and blocked site data both throw on read. A theme is a
    // convenience; failing to read one is not a reason to fail to render.
    return null;
  }
}

function systemPreference(): Theme {
  if (typeof window === 'undefined' || !window.matchMedia) return DEFAULT;
  return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : DEFAULT;
}

/** The ground colour, for the browser chrome around the page. */
const CHROME: Record<Theme, string> = { dark: '#2f3030', light: '#dbdbdb' };

function apply(theme: Theme) {
  if (typeof document === 'undefined') return;
  document.documentElement.dataset.theme = theme;

  // `index.html` declares one `theme-color` per `prefers-color-scheme`, which is
  // right until someone uses the in-app toggle — a media query cannot see that.
  // Pinning an unconditional meta to the active theme overrides both.
  let meta = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]:not([media])');
  if (!meta) {
    meta = document.createElement('meta');
    meta.name = 'theme-color';
    document.head.appendChild(meta);
  }
  meta.content = CHROME[theme];

  listeners.forEach((fn) => fn(theme));
}

export function getTheme(): Theme {
  if (typeof document === 'undefined') return DEFAULT;
  return document.documentElement.dataset.theme === 'light' ? 'light' : DEFAULT;
}

export function setTheme(theme: Theme) {
  try {
    localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    // Same as above: the theme still applies for this session, it just will not
    // survive a reload. Better than refusing to switch.
  }
  apply(theme);
}

export function toggleTheme() {
  setTheme(getTheme() === 'dark' ? 'light' : 'dark');
}

/**
 * Subscribe to theme changes. Returns the unsubscribe.
 *
 * A canvas cannot use `var(--ink)`: it resolved its colours once, at the frame it
 * drew. Every drawn surface therefore has to re-read its palette when the ground
 * moves under it, or a toggle leaves near-black strokes on a paper background.
 */
export function onThemeChange(fn: (theme: Theme) => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function initializeTheme() {
  if (typeof document === 'undefined') return;
  const explicit = stored();
  apply(explicit ?? systemPreference());

  // Keep following the OS only while the viewer has not chosen for themselves.
  if (!explicit && typeof window !== 'undefined' && window.matchMedia) {
    window
      .matchMedia('(prefers-color-scheme: light)')
      .addEventListener('change', (e) => {
        if (stored()) return;
        apply(e.matches ? 'light' : 'dark');
      });
  }
}

initializeTheme();

/**
 * Read a design token off the document root.
 *
 * Canvas and WebGL surfaces cannot use `var(--accent)`, so anything drawn rather
 * than styled has to look the value up. Going through here rather than hardcoding
 * the hex is what keeps a drawn stage and the stylesheet from drifting apart.
 *
 * Read it per frame or per repaint, never once at construction: the value it
 * returns is theme-dependent now.
 */
export function cssToken(name: string, fallback: string): string {
  if (typeof document === 'undefined') return fallback;
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

/** `#rgb` / `#rrggbb` / an `rgb()` or `rgba()` string → `r, g, b`. */
function channels(color: string): string | null {
  const hex = color.trim();
  if (hex.startsWith('#')) {
    const h = hex.slice(1);
    const full = h.length === 3 ? h.split('').map((c) => c + c).join('') : h;
    if (full.length < 6) return null;
    const n = parseInt(full.slice(0, 6), 16);
    if (Number.isNaN(n)) return null;
    return `${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}`;
  }
  const m = hex.match(/rgba?\(\s*([0-9.]+)[\s,]+([0-9.]+)[\s,]+([0-9.]+)/i);
  return m ? `${m[1]}, ${m[2]}, ${m[3]}` : null;
}

/**
 * A token's colour at an arbitrary alpha, for the drawn surfaces.
 *
 * The stylesheet expresses muted ink as a named ladder step; a canvas needs a
 * continuous ramp (a fading trail, a depth cue), which no fixed ladder can
 * supply. This composes one from the live token so the ramp still moves with
 * the theme instead of being a second, hardcoded palette.
 */
export function tokenAlpha(name: string, alpha: number, fallback: string): string {
  const rgb = channels(cssToken(name, fallback));
  return rgb ? `rgba(${rgb}, ${alpha})` : fallback;
}

/** Muted ink at an arbitrary alpha. The commonest use of `tokenAlpha`. */
export function inkAt(alpha: number): string {
  return tokenAlpha('--ink', alpha, '#dbdbdb');
}

/** The accent at an arbitrary alpha. */
export function accentAt(alpha: number): string {
  return tokenAlpha('--accent', alpha, '#43a38d');
}

/** True when the viewer has asked for less motion. Drawn surfaces must check this themselves. */
export function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined' || !window.matchMedia) return false;
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}
