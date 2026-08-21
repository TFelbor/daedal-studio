/**
 * The app is a single visual world: a near-black ground with one orange for
 * actions. There is no light variant — the ground is the identity, not a
 * preference — so this module exists only to stamp the attribute that stylesheets
 * and any remaining `[data-theme='dark']` rules key off.
 */
export function initializeTheme() {
  if (typeof document === 'undefined') return;
  document.documentElement.dataset.theme = 'dark';
}

initializeTheme();

/**
 * Read a design token off the document root.
 *
 * Canvas and WebGL surfaces cannot use `var(--accent)`, so anything drawn rather
 * than styled has to look the value up. Going through here rather than hardcoding
 * the hex is what keeps a drawn stage and the stylesheet from drifting apart.
 */
export function cssToken(name: string, fallback: string): string {
  if (typeof document === 'undefined') return fallback;
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

/** True when the viewer has asked for less motion. Drawn surfaces must check this themselves. */
export function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined' || !window.matchMedia) return false;
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}
