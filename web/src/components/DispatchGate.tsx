import { useState } from 'react';
import { AlertTriangle, Download, Printer } from 'lucide-react';
import { dispatchPrint } from '../api/client';
import type { DispatchTarget, JobStatusResponse } from '../api/client';
import { Marks } from './Blueprint';
import { reportUi } from '../api/activity';
import { downloadAuthed } from '../api/http';
import styles from './DispatchGate.module.css';

interface DispatchGateProps {
  jobId: string;
  /** Partial, because the running view builds this row from socket messages. */
  job: Partial<JobStatusResponse> | null;
  /** Called once the operator has been launched, so the view can follow Phase 5. */
  onDispatched: (target: DispatchTarget) => void;
}

const DASH = '—';

function formatPrintTime(seconds: number | null | undefined): string {
  if (seconds == null) return DASH;
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.round((seconds % 3600) / 60);
  return hours > 0 ? `${hours}h ${String(minutes).padStart(2, '0')}m` : `${minutes}m`;
}

const VERDICT_CLASS: Record<string, string> = {
  ready: styles.verdictReady,
  risky: styles.verdictRisky,
  unprintable: styles.verdictBad,
};

/**
 * The last thing between a sliced file and a machine.
 *
 * Phase 5 used to follow Phase 4 automatically: the pipeline was launched with
 * `--print --start-print`, so the first time anyone saw where the part was going was in
 * the past tense. A print is the only step in this pipeline that spends filament, heats
 * a nozzle for hours and cannot be undone, and the one thing a person can usefully check
 * before it happens is whether the target and the numbers are the ones they meant.
 *
 * So the pipeline stops after slicing and this panel holds the file. It shows the target
 * as the server resolves it *now* — not as it was at job creation — and sends that same
 * target back on confirmation, which is what lets the server refuse if it moved in the
 * meantime.
 */
export function DispatchGate({ jobId, job, onDispatched }: DispatchGateProps) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const target = job?.dispatch_target ?? null;
  const score = job?.printability_score;
  const verdict = job?.printability_verdict;

  const send = async () => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      reportUi('dispatch gate', `confirmed ${target?.profile ?? 'unknown profile'}`);
      const result = await dispatchPrint(jobId, target);
      onDispatched(result.target);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'The dispatch did not go through');
      setBusy(false);
    }
  };

  return (
    <section className={styles.gate} aria-label="Confirm the printer before printing">
      <div className={styles.head}>
        <span className="label-accent">Phase 05 · waiting on you</span>
        <span className={styles.headNote}>
          The file is sliced. Nothing is sent until you confirm the printer.
        </span>
      </div>

      <div className={styles.body}>
        <div className={`blueprint marked-accent ${styles.targetFrame}`}>
          <Marks />
          <div className={styles.targetName}>
            {target?.machine_name || target?.profile || 'No printer resolved'}
          </div>
          <dl className={styles.rows}>
            <div className={styles.row}>
              <dt>Firmware</dt>
              <dd className="mono">{target?.firmware || DASH}</dd>
            </div>
            <div className={styles.row}>
              <dt>Address</dt>
              <dd className="mono">{target?.base_url || DASH}</dd>
            </div>
            <div className={styles.row}>
              <dt>Profile</dt>
              <dd className="mono">{target?.profile || DASH}</dd>
            </div>
            <div className={styles.row}>
              <dt>Material</dt>
              <dd>
                {[job?.material_type, job?.material_brand, job?.material_colour]
                  .filter(Boolean)
                  .join(' · ') || DASH}
              </dd>
            </div>
          </dl>
        </div>

        <div className={styles.figures}>
          <div className={styles.cell}>
            <div className={styles.figure}>{formatPrintTime(job?.estimated_print_time_s)}</div>
            <div className={styles.cellLabel}>Print time</div>
          </div>
          <div className={styles.cell}>
            <div className={styles.figure}>
              {job?.filament_used_g != null ? `${Math.round(job.filament_used_g)} g` : DASH}
            </div>
            <div className={styles.cellLabel}>Filament</div>
          </div>
          <div className={styles.cell}>
            <div className={styles.figure}>{job?.layer_count ?? DASH}</div>
            <div className={styles.cellLabel}>
              Layers{job?.layer_height_mm ? ` · ${job.layer_height_mm} mm` : ''}
            </div>
          </div>
          {/* The quality gate's own verdict, in the place the decision is made. */}
          <div className={styles.cell}>
            <div className={`${styles.figure} ${verdict ? VERDICT_CLASS[verdict] ?? '' : ''}`}>
              {score != null ? score.toFixed(0) : DASH}
              {score != null && <span className={styles.figureMax}>/100</span>}
            </div>
            <div className={styles.cellLabel}>
              Printability{verdict ? ` · ${verdict}` : ''}
            </div>
          </div>
        </div>
      </div>

      {error && (
        <div className={`notice ${styles.error}`} role="alert">
          <AlertTriangle size={15} strokeWidth={1.5} aria-hidden="true" />
          <span>{error}</span>
        </div>
      )}

      <div className={styles.actions}>
        <button
          type="button"
          className={`btn btn-primary blueprint marked-accent ${styles.send}`}
          onClick={send}
          disabled={busy || !target?.base_url}
        >
          <Marks />
          <Printer size={16} strokeWidth={1.5} aria-hidden="true" />
          {busy ? 'Sending' : 'Send to printer'}
        </button>
        {/* The other real choice. Taking the file is not declining the job.
            A button rather than an anchor: the route is authenticated, and the
            browser sends none of our headers when it follows an `href`. */}
        <button
          type="button"
          className={`btn btn-secondary ${styles.download}`}
          onClick={() => {
            reportUi('dispatch gate', 'downloaded instead of printing');
            void downloadAuthed(`/jobs/${jobId}/download`, `${jobId}.gcode`);
          }}
        >
          <Download size={15} strokeWidth={1.5} aria-hidden="true" /> Download G-code
        </button>
        {!target?.base_url && (
          <span className="hint">No printer address resolved — choose one in Settings.</span>
        )}
      </div>
    </section>
  );
}
