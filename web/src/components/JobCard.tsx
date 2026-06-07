import { Link } from 'react-router-dom';
import type { PrintJob } from '../api/client';
import { Clock, Printer } from 'lucide-react';
import styles from './JobCard.module.css';

interface JobCardProps {
  job: PrintJob & { status: string };
}

export function JobCard({ job }: JobCardProps) {
  const getBadgeClass = (status: string, outcome: string) => {
    if (outcome === 'success') return 'badge-success';
    if (outcome === 'failure') return 'badge-failure';
    if (status === 'running') return 'badge-running';
    return 'badge-queued';
  };

  const badgeClass = getBadgeClass(job.status, job.outcome);
  const displayStatus = job.outcome !== 'unknown' ? job.outcome : job.status;

  return (
    <Link to={`/jobs/${job.job_id}`} className={`card ${styles.jobCard}`}>
      <div className={styles.header}>
        <h3 className={styles.prompt} title={job.prompt}>
          {job.prompt.length > 50 ? `${job.prompt.substring(0, 50)}...` : job.prompt}
        </h3>
        <span className={`badge ${badgeClass}`}>{displayStatus}</span>
      </div>
      
      <div className={styles.details}>
        <div className={styles.detailItem}>
          <Printer size={14} className={styles.icon} />
          <span>{job.printer_id} ({job.printer_firmware})</span>
        </div>
        <div className={styles.detailItem}>
          <Clock size={14} className={styles.icon} />
          <span>{new Date(job.started_at).toLocaleString()}</span>
        </div>
      </div>
    </Link>
  );
}
