import { useEffect, useState } from 'react';
import { AlertTriangle, Check, Loader2 } from 'lucide-react';
import { getJob } from '../api/client';
import type { JobStatusResponse } from '../api/client';
import { useJobWebSocket } from '../hooks/useJobWebSocket';
import styles from './PhaseProgress.module.css';

export type PipelinePhaseStatus = 'pending' | 'running' | 'complete' | 'error';

export interface PipelinePhase {
  phase: number;
  name: string;
  status: PipelinePhaseStatus;
}

/** The five phases, in the order the pipeline runs them. */
const PHASE_NAMES = ['Visualizer', 'Sculptor', 'Engineer', 'Slicer', 'Operator'];

const PHASE_STATUSES: PipelinePhaseStatus[] = ['pending', 'running', 'complete', 'error'];

/**
 * Narrow a status off the wire.
 *
 * The WebSocket payload is untyped, and an unrecognised word would otherwise index
 * the lookup tables below to `undefined` and render as literal "undefined".
 */
function asPhaseStatus(value: unknown): PipelinePhaseStatus | null {
  return PHASE_STATUSES.includes(value as PipelinePhaseStatus)
    ? (value as PipelinePhaseStatus)
    : null;
}

const STATE_WORD: Record<PipelinePhaseStatus, string> = {
  complete: 'Complete',
  running: 'Running',
  error: 'Stopped',
  pending: 'Waiting',
};

const NUM_CLASS: Record<PipelinePhaseStatus, string> = {
  complete: 'phase-num-done',
  running: 'phase-num-run',
  error: styles.numError,
  pending: 'phase-num-idle',
};

/**
 * Work out where a job got to from its status row.
 *
 * Shared with the page so the mesh viewer and the pipeline row cannot disagree about
 * whether phase 3 finished — they read the same job object rather than each guessing.
 */
export function derivePhases(job: JobStatusResponse | null): PipelinePhase[] {
  const phases: PipelinePhase[] = PHASE_NAMES.map((name, i) => ({
    phase: i + 1,
    name,
    status: 'pending',
  }));
  if (!job) return phases;

  let activeIndex = -1;
  if (job.outcome === 'failure') {
    activeIndex = job.current_phase?.phase ? job.current_phase.phase - 1 : -1;
  } else if (job.status === 'completed' || job.outcome === 'success') {
    activeIndex = phases.length;
  } else if (job.current_phase?.phase) {
    activeIndex = job.current_phase.phase - 1;
  } else if (job.status === 'running') {
    activeIndex = 0;
  }

  for (let i = 0; i < phases.length; i++) {
    if (i < activeIndex) {
      phases[i].status = 'complete';
    } else if (i === activeIndex) {
      phases[i].status = job.outcome === 'failure' ? 'error' : 'running';
    }
  }
  return phases;
}

/** The line above the row: what the pipeline is doing, in the user's terms. */
function summarise(phases: PipelinePhase[]): string {
  const failed = phases.find(p => p.status === 'error');
  if (failed) return `Pipeline · stopped at phase ${failed.phase}`;
  const running = phases.find(p => p.status === 'running');
  if (running) return `Pipeline · phase ${running.phase} of ${phases.length}`;
  if (phases.every(p => p.status === 'complete')) return 'Pipeline · all phases complete';
  return 'Pipeline · not started';
}

function marker(status: PipelinePhaseStatus) {
  if (status === 'complete') {
    return <Check size={13} strokeWidth={1.5} className={styles.markDone} />;
  }
  if (status === 'running') {
    return (
      <span className="running-dots">
        <i />
        <i />
        <i />
      </span>
    );
  }
  if (status === 'error') {
    return <AlertTriangle size={13} strokeWidth={1.5} className={styles.markError} />;
  }
  return null;
}

interface PhaseProgressProps {
  jobId: string;
}

export function PhaseProgress({ jobId }: PhaseProgressProps) {
  const [jobStatus, setJobStatus] = useState<JobStatusResponse | null>(null);
  const [phases, setPhases] = useState<PipelinePhase[]>(() => derivePhases(null));

  const { phases: wsPhases } = useJobWebSocket(jobId);

  // Read the stored state once; the WebSocket carries it from here.
  useEffect(() => {
    let mounted = true;

    getJob(jobId)
      .then(data => {
        if (!mounted) return;
        setJobStatus(data);
        setPhases(derivePhases(data));
      })
      .catch(err => {
        console.error('Failed to fetch initial job status', err);
      });

    return () => {
      mounted = false;
    };
  }, [jobId]);

  useEffect(() => {
    if (!wsPhases || wsPhases.length === 0) return;
    setPhases(prev => {
      const next = [...prev];
      wsPhases.forEach(wp => {
        const status = asPhaseStatus(wp.status);
        if (status === null || status === 'pending') return;
        const idx = next.findIndex(p => p.phase === wp.phase);
        if (idx >= 0) {
          next[idx] = { ...next[idx], status };
        }
      });
      return next;
    });
  }, [wsPhases]);

  if (!jobStatus) {
    return (
      <div className={styles.loading}>
        <Loader2 size={14} className="spin" strokeWidth={1.5} />
        <span className="label">Reading pipeline state</span>
      </div>
    );
  }

  // A finished job's log adds nothing the row above does not already say; a running
  // or stopped one is exactly when someone needs to see what the pipeline printed.
  const showLog = jobStatus.status !== 'completed' && jobStatus.log_tail.length > 0;

  return (
    <div>
      <span className={`label ${styles.summary}`}>{summarise(phases)}</span>

      <div className="scroll-x">
        <div className={styles.row}>
          {phases.map(phase => (
            <div key={phase.phase} className={styles.cell}>
              <div className={styles.cellHead}>
                <span className={`phase-num ${NUM_CLASS[phase.status]}`}>
                  {String(phase.phase).padStart(2, '0')}
                </span>
                {marker(phase.status)}
              </div>
              <div className={styles.cellName}>{phase.name}</div>
              <div className={`mono ${styles.cellState}`}>{STATE_WORD[phase.status]}</div>
            </div>
          ))}
        </div>
      </div>

      {showLog && (
        <div className={styles.logBlock}>
          <span className={`label-tight ${styles.logLabel}`}>Recent output</span>
          <pre className="log">{jobStatus.log_tail.join('\n')}</pre>
        </div>
      )}
    </div>
  );
}
