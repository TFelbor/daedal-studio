import React, { useState, useEffect, useRef } from 'react';
import { Play, RotateCcw } from 'lucide-react';
import { BlueprintPreview } from '../components/BlueprintPreview';
import { MeshViewer } from '../components/MeshViewer';
import { PipelineProgressBar } from '../components/PipelineProgressBar';
import { JobControlPanel } from '../components/JobControlPanel';
import { createJob, getJob, listJobs } from '../api/client';
import { getConfig } from '../api/config';
import './NewJob.css';
import styles from './NewJob.module.css';

interface PhaseStatus {
  phase: number;
  name: string;
  status: 'pending' | 'running' | 'complete' | 'error';
}

export function NewJob() {
  const [prompt, setPrompt] = useState('');
  const [loading, setLoading] = useState(false);
  
  const [jobId, setJobId] = useState<string | null>(null);
  const [currentJob, setCurrentJob] = useState<any>(null);
  const [phases, setPhases] = useState<PhaseStatus[]>([]);
  const [telemetrySamples, setTelemetrySamples] = useState<any[]>([]);
  const [wsConnected, setWsConnected] = useState(false);
  
  const wsRef = useRef<WebSocket | null>(null);
  const pollIntervalRef = useRef<number | null>(null);

  const [configDefaults, setConfigDefaults] = useState<{
    skipVisualizer: boolean;
    skipSculptor: boolean;
    profile: string;
  }>({ skipVisualizer: false, skipSculptor: false, profile: '' });

  const [printerReady, setPrinterReady] = useState(false);

  useEffect(() => {
    getConfig()
      .then(data => {
        setConfigDefaults({
          skipVisualizer: data['SKIP_VISUALIZER']?.value === 'true',
          skipSculptor: data['SKIP_SCULPTOR']?.value === 'true',
          profile: data['DEFAULT_PROFILE']?.value || '',
        });
      })
      .catch(() => {});

    const checkPrinter = async () => {
      try {
        const res = await fetch('/system/printer/status');
        if (res.ok) {
          const status = await res.json();
          setPrinterReady(status.configured && status.running);
        }
      } catch (err) {}
    };
    checkPrinter();
    const interval = setInterval(checkPrinter, 5000);
    return () => clearInterval(interval);
  }, []);

  // Initialize phases
  useEffect(() => {
    if (!jobId) {
      setPhases([
        { phase: 1, name: 'Visualizer', status: 'pending' },
        { phase: 2, name: 'Sculptor', status: 'pending' },
        { phase: 3, name: 'Engineer', status: 'pending' },
        { phase: 4, name: 'Slicer', status: 'pending' },
        { phase: 5, name: 'Operator', status: 'pending' }
      ]);
      setCurrentJob(null);
      setTelemetrySamples([]);
    }
  }, [jobId]);

  // Check for running job on mount
  useEffect(() => {
    listJobs(1, 0, 'running').then(data => {
      if (data.jobs && data.jobs.length > 0) {
        const activeJob = data.jobs[0];
        setJobId(activeJob.job_id);
        setPrompt(activeJob.prompt);
        connectWebSocket(activeJob.job_id);
      }
    }).catch(err => {
      console.error('Failed to fetch active jobs on mount', err);
    });
  }, []);

  const connectWebSocket = (id: string) => {
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${wsProtocol}//${window.location.host}/ws/jobs/${id}`;
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      setWsConnected(true);
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
      }
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === 'job_status') {
          setCurrentJob(msg.data);
        } else if (msg.type === 'phase_update') {
          setPhases(prev => {
            const newPhases = [...prev];
            const idx = newPhases.findIndex(p => p.phase === msg.data.phase);
            if (idx >= 0) {
              newPhases[idx] = { ...newPhases[idx], status: msg.data.status };
            }
            // Mark previous phases as complete if a later phase starts/completes
            for (let i = 0; i < idx; i++) {
              if (newPhases[i].status !== 'error') {
                newPhases[i].status = 'complete';
              }
            }
            return newPhases;
          });
        } else if (msg.type === 'telemetry_batch') {
          setTelemetrySamples(msg.data);
        } else if (msg.type === 'telemetry' || msg.type === 'telemetry_update') {
          setTelemetrySamples(prev => {
            const next = [...prev, msg.data];
            if (next.length > 20) return next.slice(next.length - 20);
            return next;
          });
        } else if (msg.type === 'printer_state') {
          if (msg.data?.temperature) {
            const tool0 = msg.data.temperature.tool0 || msg.data.temperature.extruder;
            const bed = msg.data.temperature.bed;
            if (tool0?.actual != null || bed?.actual != null) {
              const syntheticSample = {
                sample_id: 'sync_' + Date.now(),
                job_id: id,
                sampled_at: new Date().toISOString(),
                hotend_actual_c: tool0?.actual || 0,
                hotend_target_c: tool0?.target || 0,
                bed_actual_c: bed?.actual || 0,
                bed_target_c: bed?.target || 0,
                z_height_mm: null,
                gcode_line: null,
                print_speed_pct: null,
                extrusion_factor_pct: null,
                fan_speed_pct: null
              };
              setTelemetrySamples(prev => {
                const next = [...prev, syntheticSample];
                if (next.length > 20) return next.slice(next.length - 20);
                return next;
              });
            }
          }
        } else if (msg.type === 'job_complete') {
          setCurrentJob((prev: any) => ({ ...prev, status: 'completed', outcome: msg.data.outcome }));
        }
      } catch (e) {
        console.error('WS parse error', e);
      }
    };

    ws.onclose = () => {
      setWsConnected(false);
      // Start polling fallback if job is not completed
      if (currentJob?.status !== 'completed' && currentJob?.outcome !== 'cancelled') {
        startPolling(id);
      }
    };
  };

  const startPolling = (id: string) => {
    if (pollIntervalRef.current) return;
    pollIntervalRef.current = window.setInterval(async () => {
      try {
        const data = await getJob(id);
        setCurrentJob(data);
        if (data.current_phase) {
          setPhases(prev => {
            const newPhases = [...prev];
            if (data.current_phase) {
              for (let i = 0; i < Math.min(data.current_phase.phase - 1, newPhases.length); i++) {
                if (newPhases[i].status !== 'error') newPhases[i].status = 'complete';
              }
              const idx = newPhases.findIndex(p => p.phase === data.current_phase.phase);
              if (idx >= 0) newPhases[idx] = { ...newPhases[idx], status: data.current_phase.status };
            }
            return newPhases;
          });
        }
        if (data.status === 'completed' || data.outcome === 'cancelled') {
          if (pollIntervalRef.current) { clearInterval(pollIntervalRef.current); pollIntervalRef.current = null; }
        }
      } catch (e: any) {
        if (e?.message?.includes('404') || e?.status === 404) {
          if (pollIntervalRef.current) { clearInterval(pollIntervalRef.current); pollIntervalRef.current = null; }
        }
        console.error('Polling failed', e);
      }
    }, 5000);
  };

  useEffect(() => {
    return () => {
      if (wsRef.current) wsRef.current.close();
      if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
    };
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!prompt.trim()) return;

    setLoading(true);
    try {
      const data = await createJob({
        prompt,
        printer_id: 'default_printer',
        profile: configDefaults.profile,
        skip_visualizer: configDefaults.skipVisualizer,
        skip_sculptor: configDefaults.skipSculptor,
        print: true,
        start_print: true
      });
      setJobId(data.job_id);

      // Initial phase running
      setPhases(prev => {
        const next = prev.map(p => ({ ...p, status: 'pending' as PhaseStatus['status'] }));
        next[0].status = 'running';
        return next;
      });

      connectWebSocket(data.job_id);
    } catch (err: any) {
      console.error(err);
      alert(err?.message || 'Failed to start job');
    } finally {
      setLoading(false);
    }
  };

  const resetJob = () => {
    if (wsRef.current) wsRef.current.close();
    if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
    setJobId(null);
    setPrompt('');
  };

  const isRunning = jobId !== null;

  return (
    <div className={styles.pageLayout}>
      
      {!isRunning ? (
        <div className={styles.heroContainer}>
          <div className={styles.hero}>
            <h1 className={styles.title}>Prompt2Print</h1>
            <p className={styles.subtitle}>Enter a description and watch it become a physical object.</p>
          </div>

          <form className={`card ${styles.form}`} onSubmit={handleSubmit}>
            {!printerReady && (
              <div style={{ 
                backgroundColor: 'rgba(220, 53, 69, 0.1)', 
                border: '1px solid var(--danger-color)',
                color: 'var(--danger-color)', 
                padding: '12px',
                borderRadius: '8px',
                marginBottom: '16px', 
                fontSize: '14px', 
                textAlign: 'center',
                fontWeight: '500'
              }}>
                ⚠️ No printer or simulator configured/running. Please configure one in Settings.
              </div>
            )}
            <textarea
              className={`input ${styles.textarea}`}
              placeholder="e.g. A low poly planter box with a modern geometric design..."
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  if (prompt.trim() && !loading && printerReady) {
                    handleSubmit(e);
                  }
                }
              }}
              rows={4}
              autoFocus
              disabled={!printerReady}
            />
            
            <div className={styles.actions}>
              <button 
                type="submit" 
                className={`btn btn-primary ${styles.submitBtn}`}
                disabled={!prompt.trim() || loading || !printerReady}
              >
                {loading ? 'Starting...' : <><Play size={18} /> Generate & Print</>}
              </button>
            </div>
          </form>
        </div>
      ) : (
        <div className={styles.liveView}>
          <div className={styles.grid}>
            {/* Column 1: Prompt Summary */}
            <div className={styles.column}>
              <h3 className={styles.colTitle}>Prompt</h3>
              <div className={styles.componentWrapper} style={{ padding: '16px', display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center' }}>
                <p className={styles.promptText} style={{ textAlign: 'center' }}>{prompt}</p>
                <div style={{ marginTop: 'auto', width: '100%' }}>
                  <button onClick={resetJob} className={styles.resetBtn}>
                    <RotateCcw size={16} /> New Job
                  </button>
                  {!wsConnected && currentJob?.status !== 'completed' && currentJob?.outcome !== 'cancelled' && (
                    <div className={styles.offlineBadge}>Offline (Polling)</div>
                  )}
                </div>
              </div>
            </div>

            {/* Column 2: 2D Preview */}
            <div className={styles.column}>
              <h3 className={styles.colTitle}>2D Blueprint</h3>
              <div className={styles.componentWrapper}>
                <BlueprintPreview jobId={jobId} status={phases[0].status} />
              </div>
            </div>

            {/* Column 3: 3D Preview */}
            <div className={styles.column}>
              <h3 className={styles.colTitle}>3D Mesh</h3>
              <div className={styles.componentWrapper}>
                <MeshViewer jobId={jobId} status={currentJob?.status || 'queued'} phases={phases} />
              </div>
            </div>

            {/* Column 4: Control Panel */}
            <div className={styles.column}>
              <h3 className={styles.colTitle}>Control Panel</h3>
              <div className={styles.componentWrapper}>
                <JobControlPanel jobId={jobId} currentJob={currentJob} phases={phases} telemetrySamples={telemetrySamples} />
              </div>
            </div>
          </div>

          <div className={styles.progressWrapper}>
            <PipelineProgressBar phases={phases} />
          </div>
        </div>
      )}
    </div>
  );
}
