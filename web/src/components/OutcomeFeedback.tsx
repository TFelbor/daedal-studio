/**
 * The print-outcome prompt.
 *
 * This is the one signal the system cannot collect for itself. A printer reporting
 * "job finished" means the G-code file ran to the end; it says nothing about whether
 * the part adhered, warped, or came off the bed in one piece. Only the person standing
 * next to the machine knows that, and they will only tell us if saying so is trivial.
 *
 * Hence the shape: a persistent banner that follows the user across every page rather
 * than a notification they can miss, two large verdict buttons as the primary action,
 * and failure detail that appears only after someone has already said it failed. A
 * skip is recorded rather than ignored — whether pilot users answer at all is the
 * thing being tested, so declining has to be distinguishable from never being asked.
 */

import { useEffect, useRef, useState } from 'react';
import {
  AlertTriangle,
  Check,
  ChevronDown,
  ChevronUp,
  Loader2,
  ThumbsDown,
  ThumbsUp,
} from 'lucide-react';
import {
  dismissOutcomePrompt,
  listPendingFeedback,
  markOutcomePromptShown,
  reportOutcome,
  type PendingFeedbackJob,
} from '../api/client';
import styles from './OutcomeFeedback.module.css';

const FAILURE_TYPES = [
  { value: 'adhesion', label: 'Came off the bed / warped' },
  { value: 'layer_shift', label: 'Layer shift' },
  { value: 'extrusion_issue', label: 'Under-extrusion / gaps' },
  { value: 'clog', label: 'Clog / no filament' },
  { value: 'thermal_runaway', label: 'Temperature problem' },
  { value: 'unknown', label: 'Something else' },
];

/** How often to look for newly finished prints, in milliseconds. */
const POLL_MS = 30_000;

function formatDuration(seconds: number | null): string | null {
  if (!seconds) return null;
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.round((seconds % 3600) / 60);
  return hours ? `${hours}h ${minutes}m` : `${minutes}m`;
}

interface CardProps {
  job: PendingFeedbackJob;
  onResolved: (jobId: string) => void;
}

function OutcomeCard({ job, onResolved }: CardProps) {
  const [busy, setBusy] = useState<string | null>(null);
  const [showDetail, setShowDetail] = useState(false);
  const [failureType, setFailureType] = useState('adhesion');
  const [notes, setNotes] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const submit = async (verdict: 'success' | 'failure', withDetail = false) => {
    setBusy(verdict);
    setError(null);
    try {
      await reportOutcome(job.job_id, {
        verdict,
        ...(verdict === 'failure' && withDetail
          ? { failure_type: failureType, notes: notes || undefined }
          : {}),
      });
      setDone(true);
      // Held briefly so the acknowledgement is visible before the card leaves.
      setTimeout(() => onResolved(job.job_id), 900);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save that');
      setBusy(null);
    }
  };

  const skip = async () => {
    setBusy('skip');
    try {
      await dismissOutcomePrompt(job.job_id);
      onResolved(job.job_id);
    } catch {
      // A failed skip is not worth interrupting anyone over; the card simply stays.
      setBusy(null);
    }
  };

  if (done) {
    return (
      <div className={styles.card}>
        <div className={styles.thanks}>
          <Check size={18} /> Thanks — recorded.
        </div>
      </div>
    );
  }

  const estimate = formatDuration(job.estimated_print_time_s);

  return (
    <div className={styles.card}>
      <div className={styles.cardHead}>
        <span className={styles.prompt}>{job.prompt}</span>
        <span className={styles.meta}>
          {[job.material_type, estimate && `~${estimate}`, job.printer_id]
            .filter(Boolean)
            .join(' · ')}
        </span>
      </div>

      <div className={styles.actions}>
        <button
          type="button"
          className={`${styles.verdict} ${styles.clean}`}
          onClick={() => submit('success')}
          disabled={busy !== null}
        >
          {busy === 'success' ? <Loader2 size={16} className="spinner" /> : <ThumbsUp size={16} />}
          Came off clean
        </button>
        <button
          type="button"
          className={`${styles.verdict} ${styles.failed}`}
          onClick={() => setShowDetail(true)}
          disabled={busy !== null}
        >
          <ThumbsDown size={16} />
          It failed
        </button>
        <button
          type="button"
          className={`${styles.verdict} ${styles.skip}`}
          onClick={skip}
          disabled={busy !== null}
        >
          Skip
        </button>
      </div>

      {showDetail && (
        <div className={styles.detail}>
          <div className={styles.detailRow}>
            <label className={styles.detailLabel} htmlFor={`ft-${job.job_id}`}>
              What went wrong?
            </label>
            <select
              id={`ft-${job.job_id}`}
              className="input"
              value={failureType}
              onChange={(e) => setFailureType(e.target.value)}
              style={{ maxWidth: 260 }}
            >
              {FAILURE_TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
          </div>
          <textarea
            className="input"
            rows={2}
            placeholder="Anything else worth knowing (optional)"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />
          <div className={styles.actions}>
            <button
              type="button"
              className={`${styles.verdict} ${styles.failed}`}
              onClick={() => submit('failure', true)}
              disabled={busy !== null}
            >
              {busy === 'failure' ? <Loader2 size={16} className="spinner" /> : <ThumbsDown size={16} />}
              Record failure
            </button>
            <button
              type="button"
              className={`${styles.verdict} ${styles.skip}`}
              onClick={() => setShowDetail(false)}
              disabled={busy !== null}
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {error && <div className={styles.error}>{error}</div>}
    </div>
  );
}

export function OutcomeFeedback() {
  const [jobs, setJobs] = useState<PendingFeedbackJob[]>([]);
  const [open, setOpen] = useState(true);
  // Jobs whose prompt-shown event has already been sent this session. The server
  // deduplicates too, but tracking it here avoids a request per poll.
  const marked = useRef<Set<string>>(new Set());

  useEffect(() => {
    let cancelled = false;

    const poll = async () => {
      try {
        const body = await listPendingFeedback();
        // A print can finish long after the page that started it was closed, so the
        // banner polls rather than relying on the job's WebSocket still being open.
        if (!cancelled) setJobs(body.jobs);
      } catch {
        // The banner is additive; a failed poll must never break the page around it.
      }
    };

    poll();
    const timer = setInterval(poll, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  // Record that these prompts were actually seen. This is the denominator of the
  // pilot's response rate, so it has to fire when a card renders — not when the job
  // entered the queue, and not when someone answers.
  useEffect(() => {
    if (!open) return;
    jobs.forEach((job) => {
      if (marked.current.has(job.job_id)) return;
      marked.current.add(job.job_id);
      markOutcomePromptShown(job.job_id).catch(() => {
        marked.current.delete(job.job_id);
      });
    });
  }, [jobs, open]);

  const handleResolved = (jobId: string) => {
    setJobs((current) => current.filter((j) => j.job_id !== jobId));
  };

  if (jobs.length === 0) return null;

  return (
    <div className={styles.banner}>
      <button type="button" className={styles.header} onClick={() => setOpen((v) => !v)}>
        <AlertTriangle size={20} className={styles.headerIcon} />
        <span className={styles.headerText}>
          <span className={styles.headerTitle}>
            {jobs.length === 1
              ? '1 print awaiting your verdict'
              : `${jobs.length} prints awaiting your verdict`}
          </span>
          <span className={styles.headerSub}>
            Did it come off the bed? One tap tells us whether the model actually worked.
          </span>
        </span>
        {open ? <ChevronUp size={18} /> : <ChevronDown size={18} />}
      </button>

      {open && (
        <div className={styles.list}>
          {jobs.map((job) => (
            <OutcomeCard key={job.job_id} job={job} onResolved={handleResolved} />
          ))}
        </div>
      )}
    </div>
  );
}
