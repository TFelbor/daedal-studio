import { useEffect, useState } from 'react';
import { getJob } from '../api/client';
import type { JobStatusResponse } from '../api/client';
import { PipelineProgressBar } from './PipelineProgressBar';
import { useJobWebSocket } from '../hooks/useJobWebSocket';
import { Loader2 } from 'lucide-react';
import styles from './PhaseProgress.module.css';

interface PhaseProgressProps {
  jobId: string;
}

export function PhaseProgress({ jobId }: PhaseProgressProps) {
  const [jobStatus, setJobStatus] = useState<JobStatusResponse | null>(null);
  
  // Initialize with all pending
  const [phases, setPhases] = useState<any[]>([
    { phase: 1, name: 'Visualizer', status: 'pending' },
    { phase: 2, name: 'Sculptor', status: 'pending' },
    { phase: 3, name: 'Engineer', status: 'pending' },
    { phase: 4, name: 'Slicer', status: 'pending' },
    { phase: 5, name: 'Operator', status: 'pending' }
  ]);

  const { phases: wsPhases } = useJobWebSocket(jobId);

  // Poll REST API once to get initial state
  useEffect(() => {
    let mounted = true;
    
    const fetchInitial = async () => {
      try {
        const data = await getJob(jobId);
        if (mounted) {
          setJobStatus(data);
          
          let activeIndex = -1;
          if (data.outcome === 'failure') {
            activeIndex = data.current_phase?.phase ? data.current_phase.phase - 1 : -1;
          } else if (data.status === 'completed' || data.outcome === 'success') {
            activeIndex = 5;
          } else if (data.current_phase?.phase) {
            activeIndex = data.current_phase.phase - 1;
          } else if (data.status === 'running') {
            activeIndex = 0;
          }

          setPhases(prev => {
            const next = [...prev];
            for (let i = 0; i < next.length; i++) {
              if (i < activeIndex) {
                next[i] = { ...next[i], status: 'complete' };
              } else if (i === activeIndex) {
                next[i] = { ...next[i], status: data.outcome === 'failure' ? 'error' : 'running' };
              }
            }
            return next;
          });
        }
      } catch (err) {
        console.error("Failed to fetch initial job status", err);
      }
    };

    fetchInitial();
  }, [jobId]);

  // Sync with WebSockets
  useEffect(() => {
    if (wsPhases && wsPhases.length > 0) {
      setPhases(prev => {
        const next = [...prev];
        wsPhases.forEach(wp => {
          const idx = next.findIndex(p => p.phase === wp.phase);
          if (idx >= 0 && wp.status !== 'pending') {
            next[idx] = { ...next[idx], status: wp.status };
          }
        });
        return next;
      });
    }
  }, [wsPhases]);

  if (!jobStatus) {
    return <div className={styles.loading}><Loader2 className={styles.spinner} /> Loading progress...</div>;
  }

  return (
    <div className={`card ${styles.progressCard}`}>
      <h3 className={styles.title} style={{ marginBottom: '8px' }}>Pipeline Progress</h3>
      <PipelineProgressBar phases={phases} />
      
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
