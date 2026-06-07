import { useEffect, useState } from 'react';
import { listJobs } from '../api/client';
import type { PrintJob } from '../api/client';
import { JobCard } from '../components/JobCard';
import { Loader2 } from 'lucide-react';
import styles from './JobList.module.css';

export function JobList() {
  const [jobs, setJobs] = useState<(PrintJob & { status: string })[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchJobs = async () => {
      try {
        const data = await listJobs();
        setJobs(data);
      } catch (err) {
        console.error(err);
      } finally {
        setLoading(false);
      }
    };
    fetchJobs();
  }, []);

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <h2 className={styles.title}>Recent Print Jobs</h2>
      </div>

      {loading ? (
        <div className={styles.loading}>
          <Loader2 className="spinner" size={32} />
          <p>Loading jobs...</p>
        </div>
      ) : jobs.length === 0 ? (
        <div className={`card ${styles.empty}`}>
          <p>No print jobs found. Create one to get started!</p>
        </div>
      ) : (
        <div className={styles.grid}>
          {jobs.map(job => (
            <JobCard key={job.job_id} job={job} />
          ))}
        </div>
      )}
    </div>
  );
}
