import { useEffect, useState } from 'react';
import { getJob } from '../api/client';
import type { JobStatusResponse } from '../api/client';
import styles from './PhaseProgress.module.css';
import { CheckCircle, Circle, Loader2 } from 'lucide-react';

interface PhaseProgressProps {
  jobId: string;
}

export function PhaseProgress({ jobId }: PhaseProgressProps) {
  const [jobStatus, setJobStatus] = useState<JobStatusResponse | null>(null);

  useEffect(() => {
    let mounted = true;
    
    const poll = async () => {
      try {
        const data = await getJob(jobId);
        if (mounted) {
          setJobStatus(data);
        }
      } catch (err) {
        console.error("Failed to poll job status", err);
      }
    };

    poll();
    const intervalId = setInterval(poll, 3000);

    return () => {
      mounted = false;
      clearInterval(intervalId);
    };
  }, [jobId]);

  if (!jobStatus) {
    return <div className={styles.loading}><Loader2 className={styles.spinner} /> Loading progress...</div>;
  }

  const phases = ['Modeling', 'Refining', 'Slicing', 'Printing'];
  
  // Try to determine current phase index based on log output or current_phase
  let activeIndex = -1;
  const currentPhaseName = jobStatus.current_phase?.name?.toLowerCase() || '';
  
  if (jobStatus.status === 'completed' || jobStatus.outcome === 'success') {
    activeIndex = 4; // All done
  } else if (jobStatus.outcome === 'failure') {
    activeIndex = -1; // Failed state
  } else if (currentPhaseName.includes('modeling')) {
    activeIndex = 0;
  } else if (currentPhaseName.includes('refining') || currentPhaseName.includes('sculptor')) {
    activeIndex = 1;
  } else if (currentPhaseName.includes('slicing') || currentPhaseName.includes('cura')) {
    activeIndex = 2;
  } else if (currentPhaseName.includes('printing') || currentPhaseName.includes('octoprint') || currentPhaseName.includes('moonraker')) {
    activeIndex = 3;
  } else if (jobStatus.status === 'running') {
    activeIndex = 0; // default to first if running but no phase reported yet
  }

  return (
    <div className={`card ${styles.progressCard}`}>
      <h3 className={styles.title}>Pipeline Progress</h3>
      <div className={styles.stepper}>
        {phases.map((phase, index) => {
          const isCompleted = index < activeIndex;
          const isActive = index === activeIndex;
          
          return (
            <div key={phase} className={`${styles.step} ${isActive ? styles.active : ''} ${isCompleted ? styles.completed : ''}`}>
              <div className={styles.iconContainer}>
                {isCompleted ? (
                  <CheckCircle className={styles.iconCompleted} size={24} />
                ) : isActive ? (
                  <Loader2 className={`${styles.iconActive} ${styles.spinner}`} size={24} />
                ) : (
                  <Circle className={styles.iconPending} size={24} />
                )}
              </div>
              <div className={styles.label}>{phase}</div>
            </div>
          );
        })}
      </div>
      
      {jobStatus.log_tail && jobStatus.log_tail.length > 0 && (
        <div className={styles.logsContainer}>
          <div className={styles.logsHeader}>Recent Logs</div>
          <pre className={styles.logs}>
            {jobStatus.log_tail.join('\n')}
          </pre>
        </div>
      )}
    </div>
  );
}
