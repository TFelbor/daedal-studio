import { useEffect, useState } from 'react';
import { Printer as PrinterIcon, StopCircle, Info } from 'lucide-react';
import { LineChart, Line, ResponsiveContainer, YAxis } from 'recharts';

interface JobControlPanelProps {
  jobId: string | null;
  currentJob: any;
  phases: any[];
  telemetrySamples: any[];
}

export function JobControlPanel({ jobId, currentJob, phases, telemetrySamples }: JobControlPanelProps) {
  const [printerConfigured, setPrinterConfigured] = useState(false);
  const [dispatching, setDispatching] = useState(false);
  const [cancelling, setCancelling] = useState(false);

  useEffect(() => {
    fetch('/config')
      .then(res => res.json())
      .then(data => {
        if (data.DEFAULT_PROFILE && data.DEFAULT_PROFILE.is_set) {
          setPrinterConfigured(true);
        }
      })
      .catch(console.error);
  }, []);

  const phase3Status = phases.find(p => p.phase === 3)?.status;
  const isPhase3Complete = phase3Status === 'complete';
  const isJobActive = currentJob && currentJob.status !== 'completed' && currentJob.outcome !== 'cancelled';
  const currentPhaseName = phases.slice().reverse().find(p => p.status === 'running')?.name || 
                           (currentJob?.status === 'completed' ? 'Done' : 'Queued');

  const handlePrint = async () => {
    if (!jobId || dispatching) return;
    setDispatching(true);
    try {
      const res = await fetch(`/jobs/${jobId}/print-dispatch`, { method: 'POST' });
      if (!res.ok) {
        const data = await res.json();
        alert(`Failed to dispatch print: ${data.detail}`);
      }
    } catch (err) {
      console.error(err);
      alert('Network error while dispatching print.');
    } finally {
      setDispatching(false);
    }
  };

  const handleStop = async () => {
    if (!jobId || cancelling) return;
    if (!confirm('Are you sure you want to cancel the job and printer?')) return;
    setCancelling(true);
    try {
      await fetch(`/jobs/${jobId}`, { method: 'DELETE' });
    } catch (err) {
      console.error(err);
    } finally {
      setCancelling(false);
    }
  };

  if (!jobId) {
    return (
      <div style={{ padding: '24px', backgroundColor: '#f9f9f9', borderRadius: '8px', height: '100%', border: '1px solid #e5e5e5' }}>
        <p style={{ color: '#666', textAlign: 'center', marginTop: '40px' }}>Controls will appear when a job is started.</p>
      </div>
    );
  }

  const chartData = telemetrySamples.map((s, i) => ({
    time: i,
    temp: s.hotend_actual_c || 0
  }));

  let printTooltip = "Ready to print";
  if (!isPhase3Complete) printTooltip = "Complete phases 1-3 first";
  if (!printerConfigured) printTooltip = "Configure a printer first";

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px', padding: '20px', backgroundColor: '#fff', borderRadius: '8px', height: '100%', border: '1px solid #e5e5e5' }}>
      
      {/* Job Details */}
      <div>
        <h3 style={{ margin: '0 0 12px 0', fontSize: '16px', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '8px' }}>
          <Info size={16} /> Job Details
        </h3>
        <div style={{ fontSize: '14px', color: '#4b5563', display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <span>ID:</span> <span style={{ fontFamily: 'monospace' }}>{jobId.substring(0, 8)}</span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <span>Status:</span> 
            <span style={{ 
              fontWeight: 600, 
              color: currentJob?.outcome === 'success' ? '#10b981' : currentJob?.outcome === 'cancelled' ? '#ef4444' : '#3b82f6'
            }}>
              {currentPhaseName}
            </span>
          </div>
          {currentJob?.started_at && (
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span>Started:</span> <span>{new Date(currentJob.started_at).toLocaleTimeString()}</span>
            </div>
          )}
        </div>
      </div>

      <hr style={{ border: 'none', borderTop: '1px solid #e5e5e5', margin: 0 }} />

      {/* Telemetry */}
      <div style={{ flex: 1, minHeight: '100px', display: 'flex', flexDirection: 'column' }}>
        <h3 style={{ margin: '0 0 12px 0', fontSize: '14px', fontWeight: 600, color: '#4b5563' }}>Hotend Temp (°C)</h3>
        {chartData.length > 0 ? (
          <div style={{ flex: 1, width: '100%' }}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData}>
                <YAxis domain={['auto', 'auto']} hide />
                <Line type="monotone" dataKey="temp" stroke="#ef4444" strokeWidth={2} dot={false} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', backgroundColor: '#f9f9f9', borderRadius: '4px' }}>
            <span style={{ fontSize: '12px', color: '#9ca3af' }}>No telemetry data</span>
          </div>
        )}
      </div>

      <hr style={{ border: 'none', borderTop: '1px solid #e5e5e5', margin: 0 }} />

      {/* Actions */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
        <button
          onClick={handlePrint}
          disabled={!isPhase3Complete || !printerConfigured || dispatching}
          title={printTooltip}
          style={{
            display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px',
            width: '100%', padding: '12px', borderRadius: '6px', border: 'none',
            backgroundColor: (!isPhase3Complete || !printerConfigured || dispatching) ? '#e5e5e5' : '#10b981',
            color: (!isPhase3Complete || !printerConfigured || dispatching) ? '#9ca3af' : '#fff',
            fontWeight: 600, fontSize: '16px', cursor: (!isPhase3Complete || !printerConfigured || dispatching) ? 'not-allowed' : 'pointer',
            transition: 'background-color 0.2s'
          }}
        >
          <PrinterIcon size={20} /> {dispatching ? 'Dispatching...' : 'PRINT'}
        </button>

        <button
          onClick={handleStop}
          disabled={!isJobActive || cancelling}
          style={{
            display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px',
            width: '100%', padding: '10px', borderRadius: '6px', 
            backgroundColor: 'transparent',
            border: `2px solid ${(!isJobActive || cancelling) ? '#e5e5e5' : '#ef4444'}`,
            color: (!isJobActive || cancelling) ? '#9ca3af' : '#ef4444',
            fontWeight: 600, fontSize: '14px', cursor: (!isJobActive || cancelling) ? 'not-allowed' : 'pointer'
          }}
        >
          <StopCircle size={18} /> {cancelling ? 'Stopping...' : 'STOP JOB'}
        </button>
      </div>

    </div>
  );
}
