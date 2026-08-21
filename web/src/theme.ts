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
