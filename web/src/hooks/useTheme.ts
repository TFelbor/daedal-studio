import { useEffect, useState } from 'react';
import { getTheme, onThemeChange, type Theme } from '../theme';

/**
 * The current theme, as React state.
 *
 * Two uses, and they are different. A component that only *styles* itself does
 * not need this at all — CSS variables re-resolve on their own when the root
 * attribute flips. This is for the surfaces that resolved a colour into
 * something CSS cannot reach back into: a WebGL scene background, a Three.js
 * material, a canvas stroke. Putting the return value in an effect's dependency
 * array is what makes such a surface rebuild when the ground moves.
 */
export function useTheme(): Theme {
  const [theme, setThemeState] = useState<Theme>(getTheme);
  useEffect(() => onThemeChange(setThemeState), []);
  return theme;
}
