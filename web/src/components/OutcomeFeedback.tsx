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
  FlaskConical,
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

/**
 * How FDM prints actually fail, in roughly descending order of how often.
 *
 * The first five match the `AnomalyDetector`'s own rule names on purpose: when the
 * detector fires and a human agrees, the two records should use the same word, or the
 * question "how often is the detector right" cannot be answered by a query.
 *
 * `other` is last and opens a free-text box. A fixed list cannot anticipate every way
 * a part comes out wrong, and the failures worth hearing about are exactly the ones
 * nobody thought to list.
 */
const FAILURE_TYPES = [
  { value: 'adhesion', label: 'Came off the bed / warped' },
  { value: 'layer_shift', label: 'Layer shift' },
  { value: 'extrusion_issue', label: 'Under-extrusion / gaps' },
  { value: 'clog', label: 'Clog / nothing coming out' },
  { value: 'thermal_runaway', label: 'Temperature problem' },
  { value: 'detached', label: 'Detached mid-print (spaghetti)' },
  { value: 'supports', label: 'Supports failed or would not come off' },
  { value: 'surface', label: 'Stringing, blobs or poor surface' },
  { value: 'dimensional', label: 'Wrong size — does not fit' },
  { value: 'filament_out', label: 'Ran out of filament / tangled spool' },
  { value: 'other', label: 'Other:' },
];

/** The one option that requires words, because it is the one the list did not cover. */
const OTHER = 'other';

/**
 * Whether the developer-only verdict is offered.
 *
 * Vite replaces `import.meta.env.DEV` at build time, so the button and its handler are
 * dropped from the production bundle entirely rather than merely hidden — a beta user
 * cannot reach it by editing the DOM. Two options for them; three for us.
 */
const SHOW_DEV_VERDICT = import.meta.env.DEV;

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
  /**
   * Whether the first skip has already happened.
   *
   * One press records a skip and asks once more. The second press is where "don't ask
   * again" is offered, because that is a heavier answer than "not now" and should not
   * be one careless click away — while a user who genuinely never wants to be asked
   * must be able to say so rather than dismissing the same card every day.
   */
  const [skipAsked, setSkipAsked] = useState(false);

  const otherChosen = failureType === OTHER;
  const trimmedNotes = notes.trim();
  // "Other:" is a promise of words. Recording it with an empty note stores strictly
  // less than the dropdown already said.
  const failureReady = !otherChosen || trimmedNotes.length > 0;

  const submit = async (
    verdict: 'success' | 'failure' | 'dev' | 'declined',
    withDetail = false,
  ) => {
    setBusy(verdict);
    setError(null);
    try {
      await reportOutcome(job.job_id, {
        verdict,
        ...(verdict === 'failure' && withDetail
          ? { failure_type: failureType, notes: trimmedNotes || undefined }
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
    // The dismissal is recorded on the first press. Whether pilot users answer at all
    // is the thing being measured, so a decline has to be distinguishable from never
    // having been asked — and that stays true even if they never press again.
    setBusy('skip');
    try {
      await dismissOutcomePrompt(job.job_id);
    } catch {
      // A failed skip is not worth interrupting anyone over.
    }
    if (!skipAsked) {
      setSkipAsked(true);
      setBusy(null);
      return;
    }
    onResolved(job.job_id);
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
          {busy === 'success' ? <Loader2 size={16} className="spin" /> : <ThumbsUp size={16} />}
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
          {skipAsked ? 'Skip & don’t ask again' : 'Skip'}
        </button>
        {/* Dropped from the production bundle. See SHOW_DEV_VERDICT. */}
        {SHOW_DEV_VERDICT && (
          <button
            type="button"
            className={`${styles.verdict} ${styles.dev}`}
            onClick={() => submit('dev')}
            disabled={busy !== null}
            title="Developer test run — recorded, but excluded from the dataset"
          >
            {busy === 'dev' ? <Loader2 size={16} className="spin" /> : <FlaskConical size={16} />}
            Dev
          </button>
        )}
      </div>

      {skipAsked && (
        <div className={styles.skipAgain} role="status">
          <span>
            Skipped. Your answer is the only way we learn whether a part survived — but
            if you would rather not be asked, say so and we will stop.
          </span>
          <button
            type="button"
            className={`${styles.verdict} ${styles.skip}`}
            onClick={() => submit('declined')}
            disabled={busy !== null}
          >
            {busy === 'declined' ? <Loader2 size={16} className="spin" /> : null}
            Don’t ask again
          </button>
        </div>
      )}

      {showDetail && (
        <div className={styles.detail}>
          <div className={styles.detailRow}>
            <label className={styles.detailLabel} htmlFor={`ft-${job.job_id}`}>
              What went wrong?
            </label>
            <select
              id={`ft-${job.job_id}`}
              className="select"
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
            className="textarea"
            rows={otherChosen ? 3 : 2}
            placeholder={
              otherChosen
                ? 'What happened? This is the box that catches what the list could not.'
                : 'Anything else worth knowing (optional)'
            }
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            aria-label={otherChosen ? 'Describe what went wrong' : 'Additional notes'}
          />
          <div className={styles.actions}>
            <button
              type="button"
              className={`${styles.verdict} ${styles.failed}`}
              onClick={() => submit('failure', true)}
              disabled={busy !== null || !failureReady}
              title={failureReady ? undefined : 'Describe what happened first'}
            >
              {busy === 'failure' ? <Loader2 size={16} className="spin" /> : <ThumbsDown size={16} />}
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
  // Jobs answered or skipped in this session. `/feedback/pending` keeps returning a
  // dismissed job — declining is recorded, not acted on — so without this the card
  // reappears on the next poll and every re-skip books another dismissal event.
  const resolved = useRef<Set<string>>(new Set());

  useEffect(() => {
    let cancelled = false;

    const poll = async () => {
      try {
        const body = await listPendingFeedback();
        // A print can finish long after the page that started it was closed, so the
        // banner polls rather than relying on the job's WebSocket still being open.
        if (!cancelled) setJobs(body.jobs.filter((job) => !resolved.current.has(job.job_id)));
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
    resolved.current.add(jobId);
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
