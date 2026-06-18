import { useState } from 'react';
import styles from './PrinterStateCard.module.css';
import { printerAction } from '../api/client';
import { Play, Pause, Square, AlertCircle, Clock, Database, FileText } from 'lucide-react';

interface PrinterStateCardProps {
  jobId: string;
  printerState: any;
}

export function PrinterStateCard({ jobId, printerState }: PrinterStateCardProps) {
  const [loadingAction, setLoadingAction] = useState<string | null>(null);

  if (!printerState) {
    return null;
  }

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

  const { state, job, progress, resends } = printerState;
  
  const stateText = state?.text || 'Unknown';
  const flags = state?.flags || {};
  const isPrinting = flags.printing;
  const isPaused = flags.paused;
  
  const resendRatio = resends?.ratio != null ? resends.ratio : 0;
  const resendCount = resends?.count || 0;
  
  const fileName = job?.file?.name || '—';
  
  // Format times (seconds to HH:MM:SS)
  const formatTime = (seconds: number | undefined | null) => {
    if (seconds == null) return '—';
    const hrs = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    const secs = Math.floor(seconds % 60);
    if (hrs > 0) return `${hrs}h ${mins}m ${secs}s`;
    if (mins > 0) return `${mins}m ${secs}s`;
    return `${secs}s`;
  };
  
  const approxTotalPrintTime = job?.estimatedPrintTime;
  const printTime = progress?.printTime;
  const printTimeLeft = progress?.printTimeLeft;
  
  // Format bytes
  const formatBytes = (bytes: number | undefined | null) => {
    if (bytes == null) return '—';
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  };

  const printedBytes = progress?.filepos;
  const totalBytes = job?.file?.size;
  
  const completionPct = progress?.completion != null ? progress.completion : 0;
  
  // Filament
  let filamentStr = '—';
  if (job?.filament?.tool0?.length) {
    filamentStr = `${(job.filament.tool0.length / 1000).toFixed(2)}m`;
  }

  return (
    <div className={`card ${styles.stateCard}`}>
      <div className={styles.header}>
        <h3 className={styles.title}>Printer Control Panel</h3>
        <span className={`${styles.badge} ${isPrinting ? styles.badgePrinting : isPaused ? styles.badgePaused : styles.badgeDefault}`}>
          {stateText}
        </span>
      </div>

      <div className={styles.controlButtons}>
        {!isPrinting ? (
          <button 
            className="btn btn-primary" 
            onClick={() => handleAction('resume')}
            disabled={loadingAction === 'resume'}
          >
            <Play size={16} /> Resume
          </button>
        ) : (
          <button 
            className="btn btn-secondary" 
            onClick={() => handleAction('pause')}
            disabled={loadingAction === 'pause'}
          >
            <Pause size={16} /> Pause
          </button>
        )}
        <button 
          className="btn btn-danger" 
          onClick={() => handleAction('cancel')}
          disabled={loadingAction === 'cancel' || (!isPrinting && !isPaused)}
        >
          <Square size={16} /> Cancel
        </button>
      </div>

      <div className={styles.progressSection}>
        <div className={styles.progressHeader}>
          <span>Print Progress</span>
          <span className={styles.progressPct}>{completionPct.toFixed(1)}%</span>
        </div>
        <div className={styles.progressBarBg}>
          <div 
            className={styles.progressBarFill} 
            style={{ width: `${completionPct}%` }}
          />
        </div>
      </div>

      <div className={styles.statsGrid}>
        <div className={styles.statRow}>
          <span className={styles.statLabel}><FileText size={14} className={styles.icon}/> File</span>
          <span className={styles.statValue} title={fileName}>{fileName}</span>
        </div>
        
        <div className={styles.statRow}>
          <span className={styles.statLabel}><Clock size={14} className={styles.icon}/> Print Time</span>
          <span className={styles.statValue}>{formatTime(printTime)}</span>
        </div>
        
        <div className={styles.statRow}>
          <span className={styles.statLabel}><Clock size={14} className={styles.icon}/> Time Left</span>
          <span className={styles.statValue}>{formatTime(printTimeLeft)}</span>
        </div>
        
        <div className={styles.statRow}>
          <span className={styles.statLabel}><Clock size={14} className={styles.icon}/> Est. Total Time</span>
          <span className={styles.statValue}>{formatTime(approxTotalPrintTime)}</span>
        </div>

        <div className={styles.statRow}>
          <span className={styles.statLabel}><Database size={14} className={styles.icon}/> Printed Data</span>
          <span className={styles.statValue}>{formatBytes(printedBytes)} / {formatBytes(totalBytes)}</span>
        </div>
        
        <div className={styles.statRow}>
          <span className={styles.statLabel}><span className={styles.icon}>🧵</span> Filament (Tool 0)</span>
          <span className={styles.statValue}>{filamentStr}</span>
        </div>

        <div className={styles.statRow}>
          <span className={styles.statLabel}><AlertCircle size={14} className={styles.icon}/> Resends</span>
          <span className={styles.statValue}>{resendCount} ({resendRatio}%)</span>
        </div>
      </div>
    </div>
  );
}
