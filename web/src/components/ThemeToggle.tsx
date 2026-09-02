import { Moon, Sun } from 'lucide-react';
import { useTheme } from '../hooks/useTheme';
import { toggleTheme } from '../theme';
import styles from './ThemeToggle.module.css';

/**
 * The ground switch.
 *
 * The icon shows the theme you are *in*, not the one you would get — a sun while
 * light, a moon while dark — because the button already says what it does in its
 * label, and an icon that contradicts the current state reads as a bug. The
 * accessible name carries the destination, which is what a screen reader user
 * needs and a sighted user infers from the icon changing after the click.
 */
export function ThemeToggle() {
  const theme = useTheme();
  const next = theme === 'dark' ? 'light' : 'dark';

  return (
    <button
      type="button"
      className={styles.toggle}
      onClick={toggleTheme}
      aria-label={`Switch to ${next} theme`}
      title={`Switch to ${next} theme`}
    >
      {theme === 'dark' ? <Moon size={17} strokeWidth={1.5} /> : <Sun size={17} strokeWidth={1.5} />}
    </button>
  );
}
