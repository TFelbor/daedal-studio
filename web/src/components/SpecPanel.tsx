import { RotateCcw } from 'lucide-react';
import { Blueprint } from './Blueprint';
import { FitsCheck } from './FitsCheck';
import type { OrganizerSpec } from '../organizer/spec';
import styles from './SpecPanel.module.css';

interface SpecPanelProps {
  spec: OrganizerSpec | null;
  /** Why there is no spec. Shown instead of the table. */
  unavailableReason: string;
  /** Recompile after an edit. Absent while nothing is editable. */
  onRecompile?: () => void;
  /** Anything to show in place of the table — today, the phase-1 artifact. */
  children?: React.ReactNode;
}

/**
 * The spec: every number the part is built from, in one editable table.
 *
 * This is the "editable parameters, not a black box" promise made concrete, and
 * the reason the panel is a table of labelled millimetres rather than a summary.
 * The audience checks tolerances against their own callipers; a paragraph
 * describing the box is not something anyone can verify.
 *
 * With no spec it renders the reason and whatever the caller passes as children —
 * today the phase-1 output, labelled as the image it is. It does not invent a
 * table, and it does not pretend the absent one is loading.
 */
export function SpecPanel({ spec, unavailableReason, onRecompile, children }: SpecPanelProps) {
  if (!spec) {
    return (
      <div className={styles.panel}>
        <div className={styles.head}>
          <span className="label">Spec</span>
          <span className={styles.unavailableTag}>not available</span>
        </div>
        <p className={styles.unavailableBody}>{unavailableReason}</p>
        {children}
      </div>
    );
  }

  return (
    <Blueprint tone="accent" className={styles.panel}>
      <div className={styles.head}>
        <span className="label">Spec · editable</span>
        <span className={styles.archetype}>
          {spec.archetype} · {spec.archetypeVersion} archetype
        </span>
      </div>

      <dl className={styles.rows}>
        {spec.dimensions.map((d) => (
          <div key={d.key} className={styles.row}>
            <div className={styles.rowMain}>
              <dt className={styles.rowLabel}>{d.label}</dt>
              {/* An editable number is framed like a field; a derived one is plain
                  text, so the table shows at a glance what a remix may change. */}
              <dd className={d.editable ? styles.valueEditable : styles.valueDerived}>
                {d.value} {d.unit}
              </dd>
            </div>
            {d.note && <p className={styles.rowNote}>{d.note}</p>}
          </div>
        ))}
      </dl>

      <FitsCheck fits={spec.fits} unavailableReason={unavailableReason} />

      {onRecompile && (
        <div className={styles.actions}>
          <button type="button" className="btn btn-secondary" onClick={onRecompile}>
            <RotateCcw size={13} strokeWidth={1.5} aria-hidden="true" />
            Recompile
          </button>
          <span className="hint">Edits recompile in under a second</span>
        </div>
      )}
    </Blueprint>
  );
}
