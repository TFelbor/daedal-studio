import { RotateCcw } from 'lucide-react';
import { Blueprint } from './Blueprint';
import { FitsCheck } from './FitsCheck';
import { UNMEASURED_FIT_REASON, type OrganizerSpec } from '../organizer/spec';
import styles from './SpecPanel.module.css';

interface SpecPanelProps {
  spec: OrganizerSpec | null;
  /** Why there is no spec. Shown instead of the table. */
  unavailableReason: string;
  /**
   * What the table is, when it is neither of the two defaults below. The composer's
   * spec has not been compiled and is not being edited *in this table* — the form
   * above it is — so it may say neither "as compiled" nor "editable".
   */
  heading?: string;
  /**
   * Why there is no fit verdict. Defaults to the post-Phase-3 answer, which is the
   * right one for a job; the composer has a spec nothing has built yet and says so.
   */
  fitUnavailableReason?: string;
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
 * for a generative job the phase-1 output, labelled as the image it is. It does not
 * invent a table, and it does not pretend the absent one is loading.
 *
 * Every row is a field of the spec itself, so every number on screen is one somebody
 * wrote. The derived figures — the stack height, the internal depth — are the
 * compiler's, and they arrive with the annotated preview off `GET /jobs/{id}/spec`
 * rather than being recomputed here against a second copy of the dimension KB.
 */
export function SpecPanel({
  spec,
  unavailableReason,
  heading,
  fitUnavailableReason = UNMEASURED_FIT_REASON,
  onRecompile,
  children,
}: SpecPanelProps) {
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
        {/* "editable" is a promise, and only `onRecompile` keeps it. Until the
            composer can edit a spec and recompile it, this table is a record of
            what the part was built from — say that rather than the other thing. */}
        <span className="label">
          {heading ?? (onRecompile ? 'Spec · editable' : 'Spec · as compiled')}
        </span>
        <span className={styles.archetype}>
          {/* No version until Phase 2 has compiled it. "v?" would be a version, and
              "v1" would be a guess at which archetype ran. */}
          {spec.archetypeVersion
            ? `${spec.archetype} · ${spec.archetypeVersion} archetype`
            : `${spec.archetype} · not compiled yet`}
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

      {/* Not `unavailableReason`: that explains why there is no *spec*, and there
          plainly is one. A spec whose mesh Phase 3 has not measured has no fit
          verdict for its own reason, and none is invented for it meanwhile. */}
      <FitsCheck fits={spec.fits} unavailableReason={fitUnavailableReason} />

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
