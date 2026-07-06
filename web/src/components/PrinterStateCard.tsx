import { useState } from 'react';
import styles from './PrinterStateCard.module.css';
import { printerAction } from '../api/client';
import { Play, Pause, Square, Clock, FileText, Thermometer, Layers, Timer } from 'lucide-react';

interface PrinterStateCardProps {
  jobId: string;
  printerState: any;
  startedAt?: string | null;
  layerHeightMm?: number | null;
}

export function PrinterStateCard({ jobId, printerState, startedAt, layerHeightMm }: PrinterStateCardProps) {
  const [loadingAction, setLoadingAction] = useState<string | null>(null);

  const handleAction = async (action: 'pause' | 'resume' | 'cancel') => {
    if (!window.confirm(`Are you sure you want to ${action} the print?`)) return;
    setLoadingAction(action);
    try {
      await printerAction(jobId, action);
    } catch (err: any) {
      alert(err.message || `Failed to ${action}`);
    } finally {
      setLoadingAction(null);
    }
  };

  const formatTime = (seconds: number | undefined | null) => {
    if (seconds == null) return '\u2014';
    const hrs = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    const secs = Math.floor(seconds % 60);
    if (hrs > 0) return `${hrs}h ${mins}m ${secs}s`;
    if (mins > 0) return `${mins}m ${secs}s`;
    return `${secs}s`;
  };

  const formatDateTime = (iso: string | null | undefined) => {
    if (!iso) return '\u2014';
    return new Date(iso).toLocaleString([], {
      month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit'
    });
  };

  const getETA = (secondsLeft: number | null | undefined) => {
    if (secondsLeft == null) return '\u2014';
    const eta = new Date(Date.now() + secondsLeft * 1000);
    return eta.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  };

  if (!printerState) {
    return (
      <div className={`card ${styles.stateCard} ${styles.waiting}`}>
        <Timer size={20} className={styles.waitingIcon} />
        <p className={styles.waitingText}>Waiting for printer data\u2026</p>
        <p className={styles.waitingHint}>Telemetry will appear once the print starts.</p>
      </div>
    );
  }

  const { state, job, progress } = printerState;

  const stateText = state?.text || 'Unknown';
  const flags = state?.flags || {};
  const isPrinting = flags.printing;
  const isPaused = flags.paused;

  const fileName = job?.file?.name || '\u2014';
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
  let filamentStr = '\u2014';
  if (job?.filament?.tool0?.length) {
    filamentStr = `${(job.filament.tool0.length / 1000).toFixed(2)}m`;
  }

  return (
    <div className={`card ${styles.stateCard}`}>
      <div className={styles.header}>
        <h3 className={styles.title}>Print Status</h3>
        <span className={`${styles.badge} ${isPrinting ? styles.badgePrinting : isPaused ? styles.badgePaused : styles.badgeDefault}`}>
          {stateText}
        </span>
      </div>

      <div className={styles.progressSection}>
        <div className={styles.progressHeader}>
          <span className={styles.progressLabel}>Progress</span>
          <span className={styles.progressPct}>{completionPct.toFixed(1)}%</span>
        </div>
        <div className={styles.progressBarBg}>
          <div
            className={styles.progressBarFill}
            style={{ width: `${Math.min(completionPct, 100)}%` }}
          />
        </div>
      </div>

      <div className={styles.controlButtons}>
        {!isPrinting ? (
          <button
            className="btn btn-primary"
            onClick={() => handleAction('resume')}
            disabled={loadingAction === 'resume'}
          >
            <Play size={14} /> Resume
          </button>
        ) : (
          <button
            className="btn btn-secondary"
            onClick={() => handleAction('pause')}
            disabled={loadingAction === 'pause'}
          >
            <Pause size={14} /> Pause
          </button>
        )}
        <button
          className="btn btn-danger"
          onClick={() => handleAction('cancel')}
          disabled={loadingAction === 'cancel' || (!isPrinting && !isPaused)}
        >
          <Square size={14} /> Cancel
        </button>
      </div>

      <div className={styles.statsGrid}>
        <div className={styles.statRow}>
          <span className={styles.statLabel}><FileText size={13} className={styles.icon} /> File</span>
          <span className={styles.statValue} title={fileName}>{fileName}</span>
        </div>
        <div className={styles.statRow}>
          <span className={styles.statLabel}><Clock size={13} className={styles.icon} /> Started</span>
          <span className={styles.statValue}>{formatDateTime(startedAt)}</span>
        </div>
        <div className={styles.statRow}>
          <span className={styles.statLabel}><Timer size={13} className={styles.icon} /> Elapsed</span>
          <span className={styles.statValue}>{formatTime(printTime)}</span>
        </div>
        <div className={styles.statRow}>
          <span className={styles.statLabel}><Timer size={13} className={styles.icon} /> Remaining</span>
          <span className={styles.statValue}>{formatTime(printTimeLeft)}</span>
        </div>
        <div className={styles.statRow}>
          <span className={styles.statLabel}><Clock size={13} className={styles.icon} /> ETA</span>
          <span className={styles.statValue}>{getETA(printTimeLeft)}</span>
        </div>
        {currentLayer != null && (
          <div className={styles.statRow}>
            <span className={styles.statLabel}><Layers size={13} className={styles.icon} /> Layer</span>
            <span className={styles.statValue}>
              {currentLayer}{totalLayers != null ? ` / ~${totalLayers}` : ''}
            </span>
          </div>
        )}
        <div className={styles.statRow}>
          <span className={styles.statLabel}><span className={styles.icon}>🧵</span> Filament</span>
          <span className={styles.statValue}>{filamentStr}</span>
        </div>
      </div>

      {(tool0.actual != null || bed.actual != null) && (
        <div className={styles.tempSection}>
          <h4 className={styles.tempTitle}>
            <Thermometer size={14} /> Temperatures
          </h4>
          <div className={styles.tempGrid}>
            {tool0.actual != null && (
              <div className={styles.tempItem}>
                <span className={styles.tempLabel}>Hotend</span>
                <span className={styles.tempValue}>
                  {tool0.actual?.toFixed(1)}°C
                  {tool0.target != null && (
                    <span className={styles.tempTarget}> / {tool0.target?.toFixed(1)}°C</span>
                  )}
                </span>
              </div>
            )}
            {bed.actual != null && (
              <div className={styles.tempItem}>
                <span className={styles.tempLabel}>Bed</span>
                <span className={styles.tempValue}>
                  {bed.actual?.toFixed(1)}°C
                  {bed.target != null && (
                    <span className={styles.tempTarget}> / {bed.target?.toFixed(1)}°C</span>
                  )}
                </span>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
