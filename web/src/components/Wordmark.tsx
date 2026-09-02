/**
 * The Daedal mark and lockup, as drawing rather than as an image.
 *
 * It replaces a PNG for two reasons that both matter now: the mark takes the
 * accent from `currentColor`, so it follows the theme instead of carrying a
 * baked-in orange; and it stays sharp at any size on any display, which a 26px
 * raster does not.
 *
 * Four strokes, largest at the top — the feather. Drawn from the marketing
 * site's own `Wordmark`, so the app and the landing page cannot drift.
 */

type MarkProps = {
  /** Edge length in px. The lockup uses 26 in the nav, larger on a splash. */
  size?: number;
  className?: string;
};

export function DaedalMark({ size = 26, className }: MarkProps) {
  return (
    <svg
      viewBox="0 0 120 120"
      width={size}
      height={size}
      fill="none"
      className={className}
      aria-hidden="true"
      focusable="false"
      style={{ color: 'var(--accent)', flex: 'none' }}
    >
      <path d="M12,62 C24,36 60,24 110,26 C72,36 38,50 18,68 Z" fill="currentColor" />
      <path d="M16,76 C30,56 58,46 98,48 C66,56 38,66 22,80 Z" fill="currentColor" />
      <path d="M20,90 C32,74 54,66 84,68 C58,76 36,84 26,94 Z" fill="currentColor" />
      <path d="M24,104 C34,92 48,86 68,88 C48,94 34,100 30,108 Z" fill="currentColor" />
    </svg>
  );
}

type WordmarkProps = MarkProps & {
  /** Hide the words, keeping only the mark. Used where the bar is too narrow. */
  markOnly?: boolean;
  /**
   * Class applied to the words alone.
   *
   * The nav hides them below 720px with CSS rather than a JS breakpoint: the
   * lockup is ~140px of the bar, and on a phone that pushed every nav link out of
   * the scroller and left the engine pill sitting on top of the logo.
   */
  wordsClassName?: string;
};

/**
 * Mark plus "Daedal Studio".
 *
 * The two words carry different weights on purpose — 600 against 300 — which is
 * the whole lockup: one name, said once, with the second half stepping back.
 */
export function Wordmark({ size = 26, markOnly = false, className, wordsClassName }: WordmarkProps) {
  return (
    <span
      className={className}
      style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0 }}
    >
      <DaedalMark size={size} />
      {!markOnly && (
        <span
          className={wordsClassName}
          style={{
            fontFamily: 'var(--font-heading)',
            fontSize: 19,
            lineHeight: 1,
            whiteSpace: 'nowrap',
            color: 'var(--ink)',
          }}
        >
          <span style={{ fontWeight: 600 }}>Daedal</span>{' '}
          <span style={{ fontWeight: 300, color: 'var(--ink-soft)' }}>Studio</span>
        </span>
      )}
    </span>
  );
}
