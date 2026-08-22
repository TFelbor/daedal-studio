import { useEffect, useState } from 'react';
import { RotateCcw } from 'lucide-react';
import { getJobPrintability, isPrintabilityReport } from '../api/client';
import type {
  PrintabilityCheck,
  PrintabilityFailure,
  PrintabilityReport,
} from '../api/client';
import { BootMark } from './BootMark';
import styles from './PrintabilityCard.module.css';

interface PrintabilityCardProps {
  jobId: string;
  /**
   * Whether the slicer generated support material.
   *
   * It comes from the job row rather than the printability report: the report scores
   * geometry before slicing and has no way to know what the slicer decided.
   */
  supportFilamentMm3?: number | null;
  /**
   * Any value that changes when a report may have appeared — the job's score, usually.
   *
   * The card is mounted while a job is still running, so it is on screen *before* the
   * scorer has written anything. Without this it would fetch once, find nothing, and
   * keep saying so for the rest of the run.
   */
  reloadKey?: string | number | null;
  /**
   * Whether scoring is expected imminently: the mesh is repaired and the gate runs next.
   *
   * Printability is evaluated between the Engineer and the slicer, so there is a window
   * of a few seconds where the mesh exists and the report does not. Reporting "nothing
   * measured this mesh" during it would be true and useless — the honest answer is that
   * the measurement is running.
   */
  pending?: boolean;
}

const VERDICT_CLASS: Record<PrintabilityReport['verdict'], string> = {
  ready: styles.scoreReady,
  risky: styles.scoreRisky,
  unprintable: styles.scoreBad,
};

const CHECK_STATUS_CLASS: Record<PrintabilityCheck['status'], string> = {
  pass: styles.statusPass,
  warn: styles.statusWarn,
  fail: styles.statusFail,
  not_checked: styles.statusSkipped,
};

const CHECK_STATUS_WORD: Record<PrintabilityCheck['status'], string> = {
  pass: 'Pass',
  warn: 'Review',
  fail: 'Fail',
  not_checked: 'Not checked',
};

/** Fail first, then what needs a look, then what nobody could measure. */
const CHECK_STATUS_ORDER: Record<PrintabilityCheck['status'], number> = {
  fail: 0,
  warn: 1,
  not_checked: 2,
  pass: 3,
};

const CHECK_LABELS: Record<string, string> = {
  watertight: 'Closed volume',
  winding_consistent: 'Consistent face winding',
  non_manifold_edges: 'Manifold edges',
  degenerate_faces: 'Zero-area faces',
  floating_components: 'Parts resting on the plate',
  escape_hole: 'Drainable interior',
  min_wall_thickness: 'Wall thickness',
  overhang_area: 'Overhangs',
  bed_contact: 'First-layer footprint',
  build_volume_fit: 'Fits the build volume',
  self_intersections: 'Self-intersections',
};

const DASH = '—';

/** A feature the report may not carry reads as an em dash, never as a guess. */
function feature(features: Record<string, unknown>, key: string, format: (v: number) => string) {
  const value = features[key];
  return typeof value === 'number' ? format(value) : DASH;
}

/**
 * What the card is currently able to say.
 *
 * Four of these five states used to collapse into one: the fetch either produced a
 * report or it did not, and everything that was not a report rendered the same
 * "No report for this job" line. So a scorer that crashed, a server that answered 500
 * and a job that never reached the Engineer were indistinguishable — and all three
 * read as reassurance, because an empty quality panel looks like a clean one.
 */
type CardState =
  | { kind: 'loading' }
  | { kind: 'report'; report: PrintabilityReport }
  | { kind: 'failed'; failure: PrintabilityFailure }
  | { kind: 'unreachable'; reason: string }
  | { kind: 'absent' };

export function PrintabilityCard({
  jobId,
  supportFilamentMm3,
  reloadKey,
  pending,
}: PrintabilityCardProps) {
  const [state, setState] = useState<CardState>({ kind: 'loading' });
  // Bumped by "Try again". Keying the effect on it rather than calling the fetch from
  // the handler is what keeps a slow first request from landing on top of the retry.
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let live = true;
    setState({ kind: 'loading' });

    getJobPrintability(jobId)
      .then(result => {
        if (!live) return;
        if (result == null) setState({ kind: 'absent' });
        else if (isPrintabilityReport(result)) setState({ kind: 'report', report: result });
        else setState({ kind: 'failed', failure: result });
      })
      .catch((err: unknown) => {
        if (!live) return;
        setState({
          kind: 'unreachable',
          reason: err instanceof Error ? err.message : 'The request did not complete',
        });
      });

    return () => {
      live = false;
    };
  }, [jobId, attempt, reloadKey]);

  const report = state.kind === 'report' ? state.report : null;
  const notChecked = report ? report.checks.filter(c => c.status === 'not_checked') : [];

  // The header reads the same in every state, so the block is always in the page at
  // the same place — including when what it has to report is that it has nothing.
  const header = (
    <div className={`block-title ${styles.title}`}>
      <span className="label">Printability</span>
      {report ? (
        <span className={styles.scoreSlot}>
          {notChecked.length > 0 && <span className={styles.chip}>Partial</span>}
          <span className={`${styles.score} ${VERDICT_CLASS[report.verdict] ?? ''}`}>
            {report.score.toFixed(0)}
            <span className={styles.scoreMax}>/100</span>
          </span>
        </span>
      ) : (
        <span className={styles.scoreSlot}>
          {state.kind === 'failed' && <span className={styles.chipBad}>Scoring failed</span>}
          {state.kind === 'unreachable' && <span className={styles.chipBad}>Unavailable</span>}
          {state.kind === 'absent' && (
            <span className={styles.chip}>{pending ? 'Scoring' : 'Not scored'}</span>
          )}
          <span className={`${styles.score} ${styles.scoreUnknown}`}>{DASH}</span>
        </span>
      )}
    </div>
  );

  // `pending` covers the gap between "the mesh is done" and "the report exists": the
  // absent state is the wrong thing to show while the scorer is still running.
  if (state.kind === 'loading' || (pending && state.kind === 'absent')) {
    return (
      <div>
        {header}
        <div className={styles.pending}>
          <BootMark
            size={22}
            label={state.kind === 'loading' ? 'Reading the report' : 'Scoring the geometry'}
          />
        </div>
      </div>
    );
  }

  // Guarding on the report rather than on the state kind is what narrows it for
  // everything below: past here there is a score to render.
  if (!report) {
    return (
      <div>
        {header}
        <div className={styles.note}>
          {state.kind === 'absent' && (
            <>
              <p className={styles.noteLead}>Nothing measured this mesh.</p>
              <p className={styles.noteBody}>
                Geometry is scored after the Engineer repairs it and before the slicer runs.
                A job with no report never reached that point — which is not the same as
                passing it. Wall thickness, overhangs and bed contact are unknown here.
              </p>
            </>
          )}
          {state.kind === 'failed' && (
            <>
              <p className={styles.noteLead}>Scoring did not finish.</p>
              <p className={styles.noteBody}>
                The job carried on without a score: printability is advisory and never
                blocks a print. None of the geometry checks produced a result, so treat
                this mesh as unverified rather than as sound.
              </p>
              <p className={styles.noteReason}>{state.failure.error}</p>
            </>
          )}
          {state.kind === 'unreachable' && (
            <>
              <p className={styles.noteLead}>Could not read the report.</p>
              <p className={styles.noteBody}>
                A score may exist for this job — this panel could not fetch it. The
                absence here says nothing about the mesh.
              </p>
              <p className={styles.noteReason}>{state.reason}</p>
              <button
                type="button"
                className={`btn btn-secondary ${styles.retry}`}
                onClick={() => setAttempt(a => a + 1)}
              >
                <RotateCcw size={13} strokeWidth={1.5} aria-hidden="true" /> Try again
              </button>
            </>
          )}
        </div>
      </div>
    );
  }

  const supports =
    supportFilamentMm3 == null ? DASH : supportFilamentMm3 > 0 ? 'Yes' : 'No';

  // Only what a person would act on — plus what could not be established, which is
  // the same kind of information: a check that did not run is not a check that passed.
  const attention = report.checks
    .filter(c => c.status !== 'pass')
    .slice()
    .sort((a, b) => CHECK_STATUS_ORDER[a.status] - CHECK_STATUS_ORDER[b.status]);

  const wallTolerance = report.features['min_wall_tolerance_mm'];
  const wallMeasured = typeof report.features['min_wall_thickness_mm'] === 'number';
  const scored = report.checks.length - notChecked.length;

  return (
    <div>
      {header}

      <div className={styles.figures}>
        <div className={styles.cell}>
          <div className={styles.figure}>
            {feature(report.features, 'min_wall_thickness_mm', v => `${v.toFixed(1)} mm`)}
          </div>
          <div className={styles.cellLabel}>Min wall</div>
          {/* The measurement is a voxel count, so it carries a pitch. Stating it beside
              the figure is the difference between a number and a claim. Every note here
              qualifies or excuses its figure — none of them merely restate it. */}
          <div className={styles.cellNote}>
            {wallMeasured && typeof wallTolerance === 'number'
              ? `± ${wallTolerance.toFixed(2)} mm`
              : 'not measured'}
          </div>
        </div>
        <div className={styles.cell}>
          <div className={styles.figure}>
            {feature(report.features, 'overhang_area_fraction', v => `${(v * 100).toFixed(1)} %`)}
          </div>
          <div className={styles.cellLabel}>Overhang area</div>
          {typeof report.features['overhang_area_fraction'] !== 'number' && (
            <div className={styles.cellNote}>not measured</div>
          )}
        </div>
        <div className={styles.cell}>
          <div className={styles.figure}>{supports}</div>
          <div className={styles.cellLabel}>Supports</div>
          {supportFilamentMm3 == null && (
            <div className={styles.cellNote}>slicer has not run</div>
          )}
        </div>
      </div>

      {attention.length > 0 && (
        <ul className={styles.checks}>
          {attention.map(check => (
            <li key={check.check} className={styles.check}>
              <div className={styles.checkText}>
                <span className={styles.checkName}>
                  {CHECK_LABELS[check.check] ?? check.check}
                </span>
                <span className={styles.checkDetail}>{check.detail}</span>
              </div>
              <span className={`${styles.checkStatus} ${CHECK_STATUS_CLASS[check.status]}`}>
                {CHECK_STATUS_WORD[check.status]}
              </span>
            </li>
          ))}
        </ul>
      )}

      {/* Says what the score is worth. It is a geometry measurement taken before
          slicing, weighted over the checks that ran — not a prediction that the part
          survives the bed. */}
      <p className={styles.caveat}>
        Advisory: geometry only, measured before the slice. A score never blocks a print.
        {notChecked.length > 0 &&
          ` ${notChecked.length} of ${report.checks.length} checks could not run, so the score is` +
            ` weighted over the ${scored} that did and describes only what was measurable.`}
      </p>
    </div>
  );
}
