import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { listJobs, getPrinterInfo, type PrintJob, type PrinterInfo } from '../api/client';
import { PrinterStatus } from '../components/PrinterStatus';
import { PrinterStateCard } from '../components/PrinterStateCard';
import { ServicePlaceholder } from '../components/ServicePlaceholder';
import { TelemetryChart } from '../components/TelemetryChart';
import { useJobWebSocket } from '../hooks/useJobWebSocket';
import { Loader2, Monitor, Printer, AlertCircle } from 'lucide-react';
import './PrintMonitor.css';
import styles from './PrintMonitor.module.css';

// We need a wrapper component for each job to use hooks independently
function ActiveJobMonitor({ job }: { job: PrintJob & { status: string } }) {
  const { telemetrySamples, printerState, printerMeta } = useJobWebSocket(job.job_id);
  const [printerInfo, setPrinterInfo] = useState<PrinterInfo | null>(null);

  useEffect(() => {
    // Fetch printer info for the banner
    getPrinterInfo(job.job_id).then(setPrinterInfo).catch(() => {});
  }, [job.job_id]);

  const firmware = printerMeta.service || printerInfo?.service || job.printer_firmware || 'octoprint';
  const machineName = printerMeta.machineName || printerInfo?.printer_name || 'Printer';
  const layerHeightMm = printerMeta.layerHeightMm || printerInfo?.layer_height_mm || null;
  const connectionStatus = printerInfo?.connection_status || 'unknown';
  
  const isOctoprint = firmware === 'octoprint';
  const isKlipperOrBambu = firmware === 'klipper' || firmware === 'bambu';

  return (
    <div className={styles.jobMonitorContainer}>
      <div className={styles.jobBanner}>
        <PrinterStatus
          printerId={job.printer_id}
          firmware={firmware}
          status={connectionStatus === 'online' ? 'Online' : connectionStatus === 'offline' ? 'Offline' : 'Checking...'}
          machineName={machineName}
        />
        <div className={styles.jobInfo}>
          <h4>{job.prompt}</h4>
          <span className={styles.jobId}>Job: {job.job_id}</span>
        </div>
      </div>

      <div className={styles.monitorGrid}>
        <div className={styles.mainCol}>
          {isOctoprint && (
            <div className={`card ${styles.chartCard}`}>
              <TelemetryChart jobId={job.job_id} data={telemetrySamples} />
            </div>
          )}
        </div>
        <div className={styles.sideCol}>
          {isOctoprint && (
            <PrinterStateCard
              jobId={job.job_id}
              printerState={printerState}
              startedAt={job.started_at}
              layerHeightMm={layerHeightMm}
            />
          )}
          {isKlipperOrBambu && (
            <ServicePlaceholder service={firmware as 'klipper' | 'bambu'} />
          )}
        </div>
      </div>
    </div>
  );
}

export function PrintMonitor() {
  const [activeJobs, setActiveJobs] = useState<(PrintJob & { status: string })[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchActiveJobs = async () => {
    try {
      const res = await listJobs(50, 0, 'running');
      setActiveJobs(res.jobs);
      setError(null);
    } catch (err: any) {
      setError(err.message || 'Failed to fetch active jobs');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchActiveJobs();
    const interval = setInterval(fetchActiveJobs, 10000);
    return () => clearInterval(interval);
  }, []);

  if (loading) {
    return (
      <div className={styles.loading}>
        <Loader2 className="animate-spin" size={32} />
        <p>Finding active print jobs...</p>
      </div>
    );
  }

  return (
    <div className="container">
      <div className={styles.header}>
        <div className={styles.titleArea}>
          <Monitor size={28} className={styles.headerIcon} />
          <h1 className={styles.title}>Print Monitor</h1>
        </div>
        <p className={styles.subtitle}>Live telemetry and status for all active print jobs.</p>
      </div>

      {error && (
        <div className={`card ${styles.errorCard}`}>
          <AlertCircle size={20} />
          <span>{error}</span>
        </div>
      )}

      {!error && activeJobs.length === 0 && (
        <div className={`card ${styles.emptyState}`}>
          <Printer size={48} className={styles.emptyIcon} />
          <h2>No Active Prints</h2>
          <p>There are currently no print jobs running. Start a new job to monitor it here.</p>
          <Link to="/new" className="btn btn-primary" style={{ marginTop: '1rem' }}>
            Create New Job
          </Link>
        </div>
      )}

      {!error && activeJobs.length > 0 && (
        <div className={styles.jobList}>
          {activeJobs.map(job => (
            <ActiveJobMonitor key={job.job_id} job={job} />
          ))}
        </div>
      )}
    </div>
  );
}
