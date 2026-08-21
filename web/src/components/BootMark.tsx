import styles from './BootMark.module.css';

interface BootMarkProps {
  /**
   * Edge of the square mark in px. 54 is the full-page size; 22 sits inline beside
   * a block label.
   */
  size?: number;
  /** The one line saying what is being waited for. Rendered as a micro-label. */
  label?: string;
  /**
   * Centre the mark in its container with the label under it, rather than sitting
   * inline on a text baseline.
   */
  block?: boolean;
  /** Draw the ruled ground behind a `block` mark, as a whole-page wait does. */
  ground?: boolean;
  className?: string;
}

/**
 * The identity drawing itself: the finished top face fills, then the two walls
 * strike in. A part mid-print.
 *
 * This replaces the spinning Lucide loader on every wait that is the app reading
 * its own state — page loads, panel loads, "reading pipeline state". A spinner says
 * only "time is passing"; the mark says which product is starting up, and it is
 * built from the same isometric cube and registration grammar as everything else on
 * the board.
 *
 * It is deliberately the *only* place the logo animates. Put it on a page or a
 * panel; do not put it inside a button, where a 14px mark drawing itself reads as a
 * glitch rather than as the product.
 */
export function BootMark({
  size = 54,
  label,
  block = false,
  ground = false,
  className = '',
}: BootMarkProps) {
  // The paths are authored on a 64-unit grid, so a fixed stroke width thins out as
  // the mark shrinks. Scaling it back up holds the walls at a constant optical
  // weight — around 1.4 device px, the same hairline the frames use.
  const stroke = (1.7 * 54) / size;

  const wrapper = [
    block ? styles.block : styles.inline,
    ground ? styles.ground : '',
    className,
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <div className={wrapper}>
      <svg
        width={size}
        height={size}
        viewBox="0 0 64 64"
        role="img"
        aria-label={label || 'Working'}
      >
        <path
          className={styles.face}
          d="M32 6 L54.5167 19 L32 32 L9.4833 19 Z"
          fill="var(--accent)"
        />
        <path
          className={styles.wall}
          d="M9.4833 19 L32 32 V58 L9.4833 45 Z"
          stroke="var(--accent)"
          strokeWidth={stroke}
          fill="none"
          pathLength={1}
          strokeDasharray={1}
        />
        <path
          className={`${styles.wall} ${styles.wallLag}`}
          d="M54.5167 19 V45 L32 58 V32 Z"
          stroke="var(--accent)"
          strokeWidth={stroke}
          fill="none"
          pathLength={1}
          strokeDasharray={1}
        />
      </svg>
      {label && <span className={`label ${styles.label}`}>{label}</span>}
    </div>
  );
}
