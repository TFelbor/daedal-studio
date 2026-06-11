import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { getJob } from '../api/client';
import type { JobStatusResponse, FailureEvent } from '../api/client';
import { PhaseProgress } from '../components/PhaseProgress';
import { TelemetryChart } from '../components/TelemetryChart';
import { FailureButton } from '../components/FailureButton';
import { PrinterStatus } from '../components/PrinterStatus';
import { ArrowLeft, Download, Loader2, AlertTriangle } from 'lucide-react';
import styles from './JobDetail.module.css';

export function JobDetail() {
  const { id } = useParams<{ id: string }>();
  const [job, setJob] = useState<JobStatusResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [failureEvents, setFailureEvents] = useState<FailureEvent[]>([]);

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
    const intervalId = setInterval(fetchJob, 5000);
    return () => clearInterval(intervalId);
  }, [id]);

  if (loading || !job) {
    return (
      <div className={styles.loading}>
        <Loader2 className="spinner" size={32} />
        <p>Loading job details...</p>
      </div>
    );
  }

  const isCompleted = job.status === 'completed' || job.outcome === 'success';

  return (
    <div className={styles.container}>
      <Link to="/" className={styles.backLink}>
        <ArrowLeft size={16} /> Back to Dashboard
      </Link>
      
      <div className={styles.header}>
        <div>
          <h2 className={styles.title}>{job.prompt}</h2>
          <p className={styles.subtitle}>Job ID: {job.job_id}</p>
        </div>
        
        {isCompleted && (
          <a href={`/jobs/${job.job_id}/download`} className="btn btn-primary" download>
            <Download size={16} /> Download G-Code
          </a>
        )}
      </div>

      <div className={styles.grid}>
        <div className={styles.mainCol}>
          <PhaseProgress jobId={job.job_id} />
          {job.status === 'running' || isCompleted ? (
            <TelemetryChart jobId={job.job_id} />
          ) : null}
        </div>
        
        <div className={styles.sideCol}>
          <PrinterStatus printerId="default_printer" firmware="moonraker" />
          
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
              <span>{job.started_at ? new Date(job.started_at).toLocaleString() : '—'}</span>
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
              <h3 style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#dc2626' }}>
                <AlertTriangle size={18} /> Failure Events
              </h3>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                {failureEvents.map(evt => (
                  <div key={evt.event_id} style={{
                    padding: '12px', backgroundColor: '#fef2f2', borderRadius: '6px',
                    border: '1px solid #fecaca', fontSize: '14px'
                  }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
                      <span style={{ fontWeight: 600, textTransform: 'capitalize', color: '#991b1b' }}>
                        {evt.failure_type.replace(/_/g, ' ')}
                      </span>
                      <span style={{ color: '#6b7280', fontSize: '12px' }}>
                        {new Date(evt.detected_at).toLocaleString()}
                      </span>
                    </div>
                    <div style={{ color: '#4b5563' }}>
                      Source: <span style={{ fontWeight: 500 }}>{evt.source}</span>
                      {evt.z_height_mm != null && <> | Z: {evt.z_height_mm?.toFixed(1)}mm</>}
                      {evt.gcode_line != null && <> | Line: {evt.gcode_line}</>}
                    </div>
                    {evt.notes && <div style={{ color: '#4b5563', marginTop: '4px', fontStyle: 'italic' }}>"{evt.notes}"</div>}
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
