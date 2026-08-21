import { useState } from 'react';
import { Pause, Play, Square } from 'lucide-react';
import { Blueprint, Marks } from './Blueprint';
import { printerAction } from '../api/client';
import styles from './PrinterStateCard.module.css';

interface PrinterStateCardProps {
  jobId: string;
  printerState: any;
  startedAt?: string | null;
  layerHeightMm?: number | null;
}

const EM_DASH = '—';

export function PrinterStateCard({ jobId, printerState, startedAt, layerHeightMm }: PrinterStateCardProps) {
  const [loadingAction, setLoadingAction] = useState<string | null>(null);

  const handleAction = async (action: 'pause' | 'resume' | 'cancel') => {
    if (!window.confirm(`Are you sure you want to ${action} the print?`)) return;
    setLoadingAction(action);
    try {
      await printerAction(jobId, action);
    } catch (err) {
      alert(err instanceof Error ? err.message : `Failed to ${action}`);
    } finally {
      setLoadingAction(null);
    }
  };

  const formatTime = (seconds: number | undefined | null) => {
    if (seconds == null) return EM_DASH;
    const hrs = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    const secs = Math.floor(seconds % 60);
    if (hrs > 0) return `${hrs}h ${mins}m ${secs}s`;
    if (mins > 0) return `${mins}m ${secs}s`;
    return `${secs}s`;
  };

  const formatDateTime = (iso: string | null | undefined) => {
    if (!iso) return EM_DASH;
    return new Date(iso).toLocaleString([], {
      month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit'
    });
  };

  const getETA = (secondsLeft: number | null | undefined) => {
    if (secondsLeft == null) return EM_DASH;
    const eta = new Date(Date.now() + secondsLeft * 1000);
    return eta.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  };

  if (!printerState) {
    return (
      <Blueprint className={styles.block}>
        <div className={styles.section}>
          <div className="block-title">
            <h3 className="subheading">Print status</h3>
            <span className="status status-off">Waiting</span>
          </div>
          <div className="empty">
            <span>The printer has not reported yet.</span>
            <span>Progress, times and temperatures appear here once it does.</span>
          </div>
        </div>
      </Blueprint>
    );
  }

  const { state, job, progress } = printerState;

  const stateText = state?.text || 'Unknown';
  const flags = state?.flags || {};
  const isPrinting = flags.printing;
  const isPaused = flags.paused;

  const fileName = job?.file?.name || EM_DASH;
  const completionPct = progress?.completion != null ? progress.completion : 0;
  const printTime = progress?.printTime;
  const printTimeLeft = progress?.printTimeLeft;

  // Layer estimation from Z height and layer height
  let currentLayer: number | null = null;
  let totalLayers: number | null = null;
  if (layerHeightMm && layerHeightMm > 0) {
    const zFromProgress = progress?.currentZ || progress?.z;
    if (zFromProgress != null) {
      currentLayer = Math.max(1, Math.round(zFromProgress / layerHeightMm));
    }
    if (currentLayer != null && completionPct > 0) {
      totalLayers = Math.round(currentLayer / (completionPct / 100));
    }
  }

  // Temperatures
  const temps = printerState.temperature || {};
  const tool0 = temps.tool0 || temps.extruder || {};
  const bed = temps.bed || {};

  // Filament
  let filamentStr = EM_DASH;
  if (job?.filament?.tool0?.length) {
    filamentStr = `${(job.filament.tool0.length / 1000).toFixed(2)} m`;
  }

  return (
    <Blueprint className={styles.block}>
      <div className={styles.section}>
        <div className="block-title">
          <h3 className="subheading">Print status</h3>
          <span className={`status ${isPrinting ? 'status-run' : 'status-off'}`}>{stateText}</span>
        </div>

        <div className={styles.progressHead}>
          <span className="label">Progress</span>
          <span className={styles.progressPct}>
            {completionPct.toFixed(1)}<i className={styles.unit}>%</i>
          </span>
        </div>
        <div className={styles.track}>
          <div className={styles.fill} style={{ width: `${Math.min(completionPct, 100)}%` }} />
        </div>
      </div>

      <div className={`plate ${styles.figures}`}>
        <div className={styles.cell}>
          <div className={styles.figure}>{formatTime(printTime)}</div>
          <div className="plate-label">Elapsed</div>
        </div>
        <div className={styles.cell}>
          <div className={styles.figure}>{formatTime(printTimeLeft)}</div>
          <div className="plate-label">Remaining</div>
        </div>
        <div className={styles.cell}>
          <div className={styles.figure}>{getETA(printTimeLeft)}</div>
          <div className="plate-label">Done at</div>
        </div>
        {currentLayer != null && (
          <div className={styles.cell}>
            <div className={styles.figure}>
              {currentLayer}
              {totalLayers != null && <i className={styles.unit}>/ ~{totalLayers}</i>}
            </div>
            <div className="plate-label">Layer</div>
          </div>
        )}
      </div>

      {(tool0.actual != null || bed.actual != null) && (
        <div className={styles.temps}>
          {tool0.actual != null && (
            <div className={styles.temp}>
              <span className="label-tight">Hotend</span>
              <span className={styles.tempValue}>
                {tool0.actual?.toFixed(1)}&deg;C
                {tool0.target != null && <i className={styles.unit}>/ {tool0.target?.toFixed(1)}&deg;C</i>}
              </span>
            </div>
          )}
          {bed.actual != null && (
            <div className={styles.temp}>
              <span className="label-tight">Bed</span>
              <span className={styles.tempValue}>
                {bed.actual?.toFixed(1)}&deg;C
                {bed.target != null && <i className={styles.unit}>/ {bed.target?.toFixed(1)}&deg;C</i>}
              </span>
            </div>
          )}
        </div>
      )}

      <div className={styles.rows}>
        <div className={styles.row}>
          <span className="label-tight">File</span>
          <span className={`mono ${styles.rowValue}`} title={fileName}>{fileName}</span>
        </div>
        <div className={styles.row}>
          <span className="label-tight">Started</span>
          <span className={`mono ${styles.rowValue}`}>{formatDateTime(startedAt)}</span>
        </div>
        <div className={styles.row}>
          <span className="label-tight">Filament</span>
          <span className={`mono ${styles.rowValue}`}>{filamentStr}</span>
        </div>
      </div>

      <div className={styles.controls}>
        {!isPrinting ? (
          <button
            className="btn btn-primary blueprint marked-accent"
            onClick={() => handleAction('resume')}
            disabled={loadingAction === 'resume'}
          >
            <Marks />
            <Play size={14} strokeWidth={1.5} /> Resume
          </button>
        ) : (
          <button
            className="btn btn-secondary"
            onClick={() => handleAction('pause')}
            disabled={loadingAction === 'pause'}
          >
            <Pause size={14} strokeWidth={1.5} /> Pause
          </button>
        )}
        <button
          className="btn btn-danger"
          onClick={() => handleAction('cancel')}
          disabled={loadingAction === 'cancel' || (!isPrinting && !isPaused)}
        >
          <Square size={14} strokeWidth={1.5} /> Cancel
        </button>
      </div>
    </Blueprint>
  );
}
