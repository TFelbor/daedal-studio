import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { AlertTriangle, ChevronLeft, ChevronRight } from 'lucide-react';
import { BootMark } from '../components/BootMark';
import { listJobs } from '../api/client';
import type { PaginatedJobs } from '../api/client';
import { Blueprint } from '../components/Blueprint';
import styles from './JobList.module.css';

const LIMIT = 10;
const POLL_INTERVAL_MS = 10_000;

/** The four buckets the server filters on. `awaiting_verdict` is deliberately not
 *  one of them: it is a state a row wears, not a page of its own. */
const FILTERS = [
  { value: 'all', label: 'All' },
  { value: 'running', label: 'Running' },
  { value: 'completed', label: 'Completed' },
  { value: 'failed', label: 'Failed' },
] as const;

type FilterValue = (typeof FILTERS)[number]['value'];

/**
 * One row of `GET /jobs`.
 *
 * The endpoint returns three fields the shared `PrintJob` type does not declare.
 * Narrowed here rather than in `api/client` so no other page inherits fields only
 * this response carries.
 */
type JobRow = PaginatedJobs['jobs'][number] & {
  material_type?: string | null;
  awaiting_verdict?: boolean;
  /** Sliced and never sent — Phase 5 is waiting for a person to confirm the printer. */
  awaiting_dispatch?: boolean;
  outcome_source?: string | null;
};

function isAwaitingVerdict(job: JobRow): boolean {
  return job.awaiting_verdict === true || job.outcome === 'awaiting_verdict';
}

/** The status pill: a colour that means state, and a word that fits 96px. */
function rowStatus(job: JobRow): { label: string; className: string } {
  if (isAwaitingVerdict(job)) {
    // The printer reached the end of the file; nobody has confirmed the part.
    return { label: 'No verdict', className: styles.statusAwaiting };
  }
  if (job.awaiting_dispatch) {
    // The pipeline finished and stopped: Phase 5 is holding for a person to confirm the
    // printer. Calling this "Success" would describe a part that does not exist.
    return { label: 'To send', className: styles.statusAwaiting };
  }
  switch (job.outcome) {
    case 'success':
      return { label: 'Success', className: 'status-ok' };
    case 'failure':
      return { label: 'Failure', className: 'status-bad' };
    case 'cancelled':
      return { label: 'Cancelled', className: 'status-off' };
    default:
      // outcome is still 'unknown', so the pipeline's status is the authority.
      return job.status === 'running'
        ? { label: 'Running', className: 'status-run' }
        : { label: 'Queued', className: 'status-off' };
  }
}

/** Who called the ending. Only ever shown when the record actually says. */
function outcomeNote(job: JobRow): string | null {
  if (job.outcome !== 'failure' && job.outcome !== 'cancelled') return null;
  if (job.outcome_source === 'user') return 'reported by a person';
  if (job.outcome_source === 'machine') return 'reported by the printer';
  return null;
}

/** `job id · material · note` — the mono line under the prompt. */
function subLine(job: JobRow): string {
  const parts = [job.job_id.slice(0, 8)];
  if (job.material_type) parts.push(job.material_type);
  const note = outcomeNote(job);
  if (note) parts.push(note);
  return parts.join(' · ');
}

function relativeTime(iso: string | null): string {
  if (!iso) return '—';
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return '—';
  const seconds = Math.floor((Date.now() - then) / 1000);
  if (seconds < 60) return 'Just now';
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? '' : 's'} ago`;
  const days = Math.floor(hours / 24);
  return days === 1 ? 'Yesterday' : `${days} days ago`;
}

function duration(start: string | null, end: string | null): string {
  if (!start || !end) return '—';
  const ms = new Date(end).getTime() - new Date(start).getTime();
  if (!Number.isFinite(ms) || ms < 0) return '—';
  const seconds = Math.floor(ms / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const pad = (n: number) => String(n).padStart(2, '0');
  if (minutes < 60) return `${minutes}m ${pad(seconds % 60)}s`;
  return `${Math.floor(minutes / 60)}h ${pad(minutes % 60)}m`;
}

export function JobList() {
  const [data, setData] = useState<PaginatedJobs | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<FilterValue>('all');
  const [page, setPage] = useState(0);

  // One effect owns both the first load and the poll. `live` is the guard: when the
  // filter or page changes, the previous effect's cleanup flips it, so a slow
  // response for the filter the user just left can no longer land on screen.
  useEffect(() => {
    let live = true;

    const load = async (showLoading: boolean) => {
      if (showLoading) setLoading(true);
      try {
        const res = await listJobs(LIMIT, page * LIMIT, statusFilter);
        if (!live) return;
        setData(res);
        setError(null);
      } catch {
        if (live) setError('Could not reach the server. Retrying every 10 seconds.');
      } finally {
        if (live && showLoading) setLoading(false);
      }
    };

    load(true);
    const interval = setInterval(() => load(false), POLL_INTERVAL_MS);
    return () => {
      live = false;
      clearInterval(interval);
    };
  }, [statusFilter, page]);

  const handleFilterChange = (filter: FilterValue) => {
    setStatusFilter(filter);
    setPage(0);
  };

  const stats = data?.stats ?? { total: 0, running: 0, completed: 0, failed: 0 };
  const jobs: JobRow[] = data?.jobs ?? [];
  const total = data?.total ?? 0;
  const totalPages = total > 0 ? Math.ceil(total / LIMIT) : 0;
  const firstShown = jobs.length > 0 ? page * LIMIT + 1 : 0;
  const lastShown = page * LIMIT + jobs.length;
  const activeFilter = FILTERS.find((f) => f.value === statusFilter);

  return (
    <div className="sheet">
      <header className={styles.head}>
        <div>
          <div className={`eyebrow ${styles.kicker}`}>
            <span className="label-accent">Every job this machine has run</span>
          </div>
          <h1 className="display">Dashboard</h1>
        </div>
        <div className={`seg ${styles.filters}`} role="group" aria-label="Filter jobs by status">
          {FILTERS.map((filter) => (
            <button
              key={filter.value}
              type="button"
              onClick={() => handleFilterChange(filter.value)}
              className={statusFilter === filter.value ? 'is-active' : undefined}
              aria-pressed={statusFilter === filter.value}
            >
              {filter.label}
            </button>
          ))}
        </div>
      </header>

      {/* The counts are one object, not four cards: equal cells behind a single frame. */}
      <Blueprint tone="accent" className={styles.statsFrame}>
        <div className={`plate ${styles.stats}`}>
          <div className={styles.statCell}>
            <div className="plate-figure">{stats.total}</div>
            <div className="plate-label">Total jobs</div>
          </div>
          <div className={styles.statCell}>
            <div className={`plate-figure ${styles.figureOk}`}>{stats.completed}</div>
            <div className="plate-label">Printed &amp; fit confirmed</div>
          </div>
          <div className={styles.statCell}>
            <div className={`plate-figure ${styles.figureBad}`}>{stats.failed}</div>
            <div className="plate-label">Failed</div>
          </div>
          <div className={styles.statCell}>
            <div className={`plate-figure ${styles.figureRun}`}>{stats.running}</div>
            <div className="plate-label">Running</div>
          </div>
        </div>
      </Blueprint>

      {error && (
        <div className={`notice ${styles.error}`} role="status">
          <AlertTriangle size={16} strokeWidth={1.5} />
          <span>{error}</span>
        </div>
      )}

      {loading && jobs.length === 0 ? (
        <BootMark block label="Reading the job log" />
      ) : jobs.length === 0 ? (
        <div className="empty">
          {statusFilter === 'all' ? (
            <>
              <span>No jobs yet</span>
              <span>Every print this machine runs is recorded here.</span>
              <Link to="/" className={`btn btn-secondary ${styles.emptyAction}`}>
                New job
              </Link>
            </>
          ) : (
            <>
              <span>No {activeFilter?.label.toLowerCase()} jobs</span>
              <span>Nothing on this machine matches that filter.</span>
              <button
                type="button"
                className={`btn btn-secondary ${styles.emptyAction}`}
                onClick={() => handleFilterChange('all')}
              >
                Show all jobs
              </button>
            </>
          )}
        </div>
      ) : (
        <div className={loading ? styles.tableBusy : undefined} aria-busy={loading}>
          <div className={`rows-head ${styles.headRow}`}>
            <span />
            <span>Prompt</span>
            <span>Printer</span>
            <span>Started</span>
            <span>Duration</span>
            <span className={styles.statusCell}>Status</span>
          </div>

          {jobs.map((job) => {
            const status = rowStatus(job);
            const running = job.status === 'running';
            return (
              <Link
                key={job.job_id}
                to={`/dashboard/${job.job_id}`}
                className={`row row-link ${styles.jobRow}`}
              >
                <span className={styles.thumbCell}>
                  <span
                    className={running ? `${styles.thumb} ${styles.thumbRun}` : styles.thumb}
                    aria-hidden="true"
                  />
                </span>
                <span className={styles.promptCell}>
                  <span className={styles.promptText}>{job.prompt || 'Untitled job'}</span>
                  <span className={`mono ${styles.promptSub}`}>{subLine(job)}</span>
                </span>
                {/* display: contents on wide screens, so these three sit in their own
                    grid columns; a flex line of its own once the row stacks. */}
                <span className={styles.metaGroup}>
                  <span className={styles.cell}>
                    {job.printer_firmware || job.printer_id || '—'}
                  </span>
                  <span className={styles.cell}>{relativeTime(job.started_at)}</span>
                  <span className={`${styles.cell} ${styles.cellMono}`}>
                    {duration(job.started_at, job.completed_at)}
                  </span>
                </span>
                <span className={styles.statusCell}>
                  <span className={`status ${status.className}`}>{status.label}</span>
                </span>
              </Link>
            );
          })}

          <div className={styles.foot}>
            <span>
              Showing {firstShown}–{lastShown} of {total}
            </span>
            <div className={styles.pager}>
              <button
                type="button"
                className={styles.pageBtn}
                onClick={() => setPage((p) => Math.max(0, p - 1))}
                disabled={page === 0}
              >
                <ChevronLeft size={14} strokeWidth={1.5} />
                Previous
              </button>
              <button
                type="button"
                className={styles.pageBtn}
                onClick={() => setPage((p) => Math.min(Math.max(totalPages - 1, 0), p + 1))}
                disabled={page >= totalPages - 1}
              >
                Next
                <ChevronRight size={14} strokeWidth={1.5} />
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
