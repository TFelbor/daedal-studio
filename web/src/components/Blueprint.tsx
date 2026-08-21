import type { CSSProperties, ReactNode } from 'react';

type MarkTone = 'muted' | 'accent' | 'run';

const TONE_CLASS: Record<MarkTone, string> = {
  muted: '',
  accent: 'marked-accent',
  run: 'marked-run',
};

/**
 * The four registration marks that sit on the corners of a framed object.
 *
 * Exported on its own so an element that already has its own border — a primary
 * button, say — can wear the marks without inheriting the frame. The parent must
 * be `position: relative` (the `.blueprint` class does this).
 */
export function Marks() {
  return (
    <>
      <i className="corner tl" aria-hidden="true" />
      <i className="corner tr" aria-hidden="true" />
      <i className="corner bl" aria-hidden="true" />
      <i className="corner br" aria-hidden="true" />
    </>
  );
}

interface BlueprintProps {
  children?: ReactNode;
  className?: string;
  style?: CSSProperties;
  /** Mark colour. Accent for content the user acts on, run for a live phase. */
  tone?: MarkTone;
}

/**
 * A wireframe object: square corners, one hairline border, four corner marks.
 *
 * This is the frame every card, figure and plate in the app wears. Use it rather
 * than a bordered div so the marks cannot be forgotten — an unmarked frame reads
 * as a different design system.
 */
export function Blueprint({ children, className = '', style, tone = 'muted' }: BlueprintProps) {
  const classes = ['blueprint', TONE_CLASS[tone], className].filter(Boolean).join(' ');
  return (
    <div className={classes} style={style}>
      <Marks />
      {children}
    </div>
  );
}
