import { PIPELINE, phaseName } from '../pipeline';
import type { StageStatus } from './stageStatus';
import styles from './StageState.module.css';

const STATE_WORD: Record<StageStatus, string> = {
  pending: 'pending',
  running: 'running',
  done: 'done',
};

interface StageStateProps {
  /** 1-indexed phase whose output this stage holds, matching `pipeline.ts`. */
  phase: number;
  status?: StageStatus;
  /**
   * Real pipeline output, newest last. Its last line is shown as-is while the phase
   * runs, and nothing is shown when there is none — this component has no vocabulary
   * of its own to fall back on.
   */
  logLines?: string[];
  /**
   * The host's own statement, shown instead of the derived phase line and blurb.
   * For the case the phase state cannot describe: a settled job with no artifact on
   * file, where "pending" would be a lie and "done" would promise a picture.
   */
  note?: string;
  /**
   * Lay the stage over its host rather than flowing in it, for a frame that already
   * holds something and needs the state drawn on top of it.
   */
  fill?: boolean;
  className?: string;
}

/**
 * The stage while its artifact does not exist yet.
 *
 * It says three things and invents none of them: which phase the artifact comes out
 * of and where that phase is, what that phase does (the blurb from `pipeline.ts`, the
 * single source the composer's pipeline panel reads too), and the pipeline's own last
 * line of output when there is one.
 *
 * What was here before was a canvas cycling a hard-coded list of steps —
 * `flux.2-klein · loading`, `sparse structure · voxels` — on a timer, with a drag hint
 * for a drawing that answered to the drag. Two things were wrong with it. It named the
 * generative stack in the one place the product describes itself, and the parametric
 * path compiles a spec in well under a second, so there is no wait to fill: theatre
 * sized for a four-minute reconstruction. And the steps were not measurements. The
 * pipeline never reported them; they advanced on a 1.9s interval whatever it was
 * doing. A real `log_tail` line is the only progress this component has ever had, and
 * it is the only one it shows now.
 */
export function StageState({
  phase,
  status = 'pending',
  logLines,
  note,
  fill = false,
  className = '',
}: StageStateProps) {
  const blurb = PIPELINE[phase - 1]?.blurb;
  const liveLine =
    status === 'running' && logLines && logLines.length > 0
      ? logLines[logLines.length - 1]
      : null;

  const classes = [styles.stage, fill ? styles.fill : '', className]
    .filter(Boolean)
    .join(' ');

  const head = note ?? `Phase ${String(phase).padStart(2, '0')} · ${phaseName(phase)} · ${STATE_WORD[status]}`;

  return (
    <div className={classes}>
      <div className={styles.body}>
        <div className={styles.head}>
          {/* The pulse is the app's running marker and it is gated on the phase
              genuinely running — a stage for a queued phase must not throb. */}
          {status === 'running' && (
            <span className="running-dots" aria-hidden="true">
              <i />
              <i />
              <i />
            </span>
          )}
          {/* Accent means work is happening. A phase that has not started gets ink,
              because the accent in this app means "live" and would read as a lie. */}
          <span className={status === 'running' ? styles.headLive : styles.headIdle}>{head}</span>
        </div>

        {/* Suppressed under a note: the host has said something more specific, and the
            phase's job description underneath it would argue with it. */}
        {!note && blurb && <p className={styles.blurb}>{blurb}</p>}

        {liveLine && <span className={styles.live}>{liveLine}</span>}
      </div>
    </div>
  );
}
