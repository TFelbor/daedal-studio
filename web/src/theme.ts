export type ThemeMode = 'light' | 'dark';

export function getPreferredTheme(): ThemeMode {
  if (typeof window === 'undefined') {
    return 'light';
  }

  const savedTheme = localStorage.getItem('theme');
  if (savedTheme === 'light' || savedTheme === 'dark') {
    return savedTheme;
  }

  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

export function applyTheme(theme: ThemeMode) {
  if (typeof document === 'undefined') {
    return;
  }

  document.documentElement.dataset.theme = theme;
  localStorage.setItem('theme', theme);
  window.dispatchEvent(new CustomEvent('themechange', { detail: theme }));
}

export function initializeTheme() {
  applyTheme(getPreferredTheme());
}

export function toggleTheme() {
  const activeTheme = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
  applyTheme(activeTheme);
  return activeTheme;
}

if (typeof window !== 'undefined') {
  initializeTheme();
}
