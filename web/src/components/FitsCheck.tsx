import { Check, Ruler, X } from 'lucide-react';
import type { FitsResult } from '../organizer/spec';
import styles from './FitsCheck.module.css';

interface FitsCheckProps {
  /** The verdict, or null when nothing has computed one. */
  fits: FitsResult | null;
  /** Why there is no verdict. Shown in place of the badge. */
  unavailableReason: string;
  /** `badge` sits inline under the composer; `panel` is the rail and gate form. */
  variant?: 'badge' | 'panel';
}

/**
 * The Fits Check — the mm math, shown.
 *
 * This is the product's signature trust feature and the answer to the
 * community's single biggest complaint about static STLs, so the arithmetic is
 * on screen rather than the conclusion alone: "✓ Fits" on its own is a claim,
 * and "100 × 0.665 mm = 66.5 mm stack · internal 70.5 mm · clearance +4.0 mm" is
 * a sum somebody can check against their own callipers.
 *
 * It renders an explicit unavailable state and never a hopeful one. A fits badge
 * with no measurement behind it is worse than no badge: it is the exact failure —
 * a confident number that was never computed — that the feature exists to prevent.
 */
export function FitsCheck({ fits, unavailableReason, variant = 'panel' }: FitsCheckProps) {
  const cls = variant === 'badge' ? styles.badge : styles.panel;

  if (!fits) {
    return (
      <div className={`${cls} ${styles.unavailable}`}>
        <Ruler size={variant === 'badge' ? 12 : 15} strokeWidth={1.5} aria-hidden="true" />
        <span className={styles.unavailableText}>
          <span className={styles.unavailableHead}>No fit check</span>
          <span className={styles.unavailableBody}>{unavailableReason}</span>
        </span>
      </div>
    );
  }

  const Icon = fits.fits ? Check : X;
  return (
    <div className={`${cls} ${fits.fits ? styles.pass : styles.fail}`}>
      <span className={styles.verdict}>
        <Icon size={variant === 'badge' ? 12 : 18} strokeWidth={2} aria-hidden="true" />
        {fits.fits ? 'Fits' : "Doesn't fit"}
      </span>
      <span className={styles.sum}>{fits.line}</span>
      {fits.basis && <span className={styles.basis}>{fits.basis}</span>}
      {!fits.fits && fits.remedy && <span className={styles.remedy}>{fits.remedy}</span>}
    </div>
  );
}
