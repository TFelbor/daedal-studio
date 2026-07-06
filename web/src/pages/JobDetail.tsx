import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { getJob } from '../api/client';
import type { JobStatusResponse, FailureEvent } from '../api/client';
import { PhaseProgress } from '../components/PhaseProgress';
import { TelemetryChart } from '../components/TelemetryChart';
import { GCodeViewer } from '../components/GCodeViewer';
import { FailureButton } from '../components/FailureButton';
import { PrinterStatus } from '../components/PrinterStatus';
import { PrinterStateCard } from '../components/PrinterStateCard';
import { ServicePlaceholder } from '../components/ServicePlaceholder';
import { ArrowLeft, Download, Loader2, AlertTriangle, Printer } from 'lucide-react';
import { getConfig, testConnection } from '../api/config';
import { useJobWebSocket } from '../hooks/useJobWebSocket';
import styles from './JobDetail.module.css';

export function JobDetail() {
  const { id } = useParams<{ id: string }>();
  const [job, setJob] = useState<JobStatusResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [failureEvents, setFailureEvents] = useState<FailureEvent[]>([]);
  const [printerConfigured, setPrinterConfigured] = useState(false);
  const [printerStatus, setPrinterStatus] = useState('Checking...');
  const [printing, setPrinting] = useState(false);

  const { telemetrySamples, printerState, printerMeta } = useJobWebSocket(job ? job.job_id : null);
  const latestZHeight = telemetrySamples.length > 0 ? telemetrySamples[telemetrySamples.length - 1].z_height_mm : null;

  const fetchJob = async () => {
    if (!id) return;
    try {
      const data = await getJob(id);
      setJob(data);
      if (data.outcome === 'failure' || data.outcome === 'cancelled') {
        fetch(`/jobs/${id}/failure`)
          .then(res => res.json())
          .then((events: FailureEvent[]) => setFailureEvents(events))
          .catch(() => {});
      }
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchJob();
    getConfig().then(data => {
      const isConfigured = !!(data['MOONRAKER_URL']?.value || data['OCTOPRINT_URL']?.value || data['BAMBU_IP']?.value);
      setPrinterConfigured(isConfigured);
    }).catch(() => {});
    const intervalId = setInterval(fetchJob, 5000);
    return () => clearInterval(intervalId);
  }, [id]);

  useEffect(() => {
    if (job?.printer_firmware) {
      testConnection(job.printer_firmware)
        .then(res => {
          setPrinterStatus(res.success ? 'Online' : 'Offline');
        })
        .catch(() => setPrinterStatus('Offline'));
    }
  }, [job?.printer_firmware]);

  const handlePrint = async () => {
    if (!job) return;
    setPrinting(true);
    try {
      const res = await fetch(`/jobs/${job.job_id}/print-dispatch`, { method: 'POST' });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Failed to dispatch print');
      }
      alert('Print job dispatched successfully!');
    } catch (err: any) {
      alert(err.message);
    } finally {
      setPrinting(false);
    }
  };

  if (loading || !job) {
    return (
      <div className={styles.loading}>
        <Loader2 className="spinner" size={32} />
        <p>Loading job details...</p>
      </div>
    );
  }

  const isCompleted = job.status === 'completed' || job.outcome === 'success';
  const hasReachedPhase5 = job.current_phase?.phase >= 5 || (job.outcome === 'failure' && job.current_phase?.phase >= 5);
  const showPrintMonitoring = job.status === 'running' || isCompleted || hasReachedPhase5;

  // Determine firmware type — prefer WebSocket meta, fallback to REST response
  const firmware = printerMeta.service || job.printer_firmware || 'octoprint';
  const machineName = printerMeta.machineName || job.machine_name;
  const layerHeightMm = printerMeta.layerHeightMm || job.layer_height_mm;
  const isOctoprint = firmware === 'octoprint';
  const isKlipperOrBambu = firmware === 'klipper' || firmware === 'bambu';

  return (
    <div className={styles.container}>
      <Link to="/dashboard" className={styles.backLink}>
        <ArrowLeft size={16} /> Back to Dashboard
      </Link>
      
      <div className={styles.header}>
        <div>
          <h2 className={styles.title}>{job.prompt}</h2>
          <p className={styles.subtitle}>Job ID: {job.job_id}</p>
        </div>
        
        {isCompleted && (
          <div style={{ display: 'flex', gap: '8px' }}>
            <a href={`/jobs/${job.job_id}/download`} className="btn btn-primary" download>
              <Download size={16} /> Download G-Code
            </a>
            {printerConfigured && (
              <button 
                className="btn btn-primary" 
                onClick={handlePrint} 
                disabled={printing}
                style={{ backgroundColor: 'var(--accent-color)', borderColor: 'var(--accent-color)' }}
              >
                {printing ? <Loader2 className="animate-spin" size={16} /> : <Printer size={16} />}
                {printing ? ' Dispatching...' : ' Print'}
              </button>
            )}
          </div>
        )}
      </div>

      <div className={styles.grid}>
        <div className={styles.mainCol}>
          <PhaseProgress jobId={job.job_id} />
          {showPrintMonitoring && (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '24px', minHeight: '350px' }}>
              <div style={{ display: 'flex', flexDirection: 'column' }}>
                <TelemetryChart jobId={job.job_id} data={telemetrySamples} />
              </div>
              <div style={{ display: 'flex', flexDirection: 'column' }}>
                <div className={`card ${styles.chartCard}`} style={{ flex: 1, padding: 0 }}>
                  <GCodeViewer jobId={job.job_id} zHeightMm={latestZHeight} />
                </div>
              </div>
            </div>
          )}
        </div>
        
        <div className={styles.sideCol}>
          <PrinterStatus
            printerId={job.printer_id || 'Printer'}
            firmware={firmware}
            status={printerStatus}
            machineName={machineName}
          />
          
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
          
          <div className={`card ${styles.detailsCard}`}>
            <h3>Job Details</h3>
            <div className={styles.detailRow}>
              <span className={styles.detailLabel}>Status</span>
              <span className={`badge ${job.outcome === 'success' ? 'badge-success' : job.outcome === 'failure' ? 'badge-failure' : job.status === 'running' ? 'badge-running' : 'badge-queued'}`}>
                {job.outcome !== 'unknown' ? job.outcome : job.status}
              </span>
            </div>
            <div className={styles.detailRow}>
              <span className={styles.detailLabel}>Started</span>
              <span>{job.started_at ? new Date(job.started_at).toLocaleString() : '\u2014'}</span>
            </div>
            {job.completed_at && (
              <div className={styles.detailRow}>
                <span className={styles.detailLabel}>Completed</span>
                <span>{new Date(job.completed_at).toLocaleString()}</span>
              </div>
            )}
            
            {job.status === 'running' && (
              <div className={styles.failureSection}>
                <hr className={styles.divider} />
                <FailureButton jobId={job.job_id} onReported={fetchJob} />
              </div>
            )}
          </div>

          {failureEvents.length > 0 && (
            <div className={`card ${styles.detailsCard}`}>
              <h3 style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--accent-color)' }}>
                <AlertTriangle size={18} /> Failure Events
              </h3>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                {failureEvents.map(evt => (
                  <div key={evt.event_id} style={{
                    padding: '12px', backgroundColor: 'var(--surface-color)', borderRadius: 'var(--border-radius)',
                    border: '1px solid var(--border-color)', fontSize: '14px'
                  }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
                      <span style={{ fontWeight: 600, textTransform: 'capitalize', color: 'var(--accent-color)' }}>
                        {evt.failure_type.replace(/_/g, ' ')}
                      </span>
                      <span style={{ color: 'var(--text-secondary)', fontSize: '12px' }}>
                        {new Date(evt.detected_at).toLocaleString()}
                      </span>
                    </div>
                    <div style={{ color: 'var(--text-secondary)' }}>
                      Source: <span style={{ fontWeight: 500 }}>{evt.source}</span>
                      {evt.z_height_mm != null && <> | Z: {evt.z_height_mm?.toFixed(1)}mm</>}
                      {evt.gcode_line != null && <> | Line: {evt.gcode_line}</>}
                    </div>
                    {evt.notes && <div style={{ color: 'var(--text-secondary)', marginTop: '4px', fontStyle: 'italic' }}>"{evt.notes}"</div>}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
