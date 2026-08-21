import { useEffect, useMemo, useState } from 'react';
import type { CSSProperties } from 'react';
import { Printer as PrinterIcon, StopCircle } from 'lucide-react';
import { Line, LineChart, ResponsiveContainer, YAxis } from 'recharts';
import { Blueprint, Marks } from './Blueprint';
import { GCodeViewer } from './GCodeViewer';

interface JobControlPanelProps {
  jobId: string | null;
  currentJob: any;
  phases: any[];
  telemetrySamples: any[];
}

/** Resolve a design token for a canvas or an SVG attribute, which cannot inherit one. */
function token(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

const PANEL: CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: '20px',
  padding: '20px 22px',
  height: '100%',
};

const RULE: CSSProperties = {
  border: 'none',
  borderTop: '1px solid var(--rule-sub)',
  margin: 0,
};

const ROW: CSSProperties = {
  display: 'flex',
  justifyContent: 'space-between',
  gap: '16px',
  padding: '6px 0',
  fontSize: '13.5px',
};

const KEY: CSSProperties = { color: 'var(--ink-50)' };

export function JobControlPanel({ jobId, currentJob, phases, telemetrySamples }: JobControlPanelProps) {
  const [printerConfigured, setPrinterConfigured] = useState(false);
  const [dispatching, setDispatching] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const accent = useMemo(() => token('--accent'), []);

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
  const currentPhaseName =
    phases.slice().reverse().find(p => p.status === 'running')?.name ||
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
      <Blueprint style={PANEL}>
        <span className="label">Controls</span>
        <div className="empty" style={{ flex: 1 }}>
          <span>Nothing running</span>
          <span>Controls appear here once a job starts</span>
        </div>
      </Blueprint>
    );
  }

  const chartData = telemetrySamples.map((s, i) => ({
    time: i,
    temp: s.hotend_actual_c || 0,
  }));

  const showPreview =
    phases.some(p => p.phase === 4 && p.status === 'complete') ||
    phases.some(p => p.phase >= 5) ||
    currentJob?.status === 'completed';

  let printHint = 'Ready to print';
  if (!isPhase3Complete) printHint = 'Complete phases 1–3 first';
  if (!printerConfigured) printHint = 'Configure a printer first';
  const printDisabled = !isPhase3Complete || !printerConfigured || dispatching;

  return (
    <Blueprint style={PANEL}>
      <div>
        <span className="label" style={{ display: 'block', marginBottom: '12px' }}>
          Job
        </span>
        <div style={ROW}>
          <span style={KEY}>ID</span>
          <span className="mono">{jobId.substring(0, 8)}</span>
        </div>
        <div style={ROW}>
          <span style={KEY}>Phase</span>
          <span>{currentPhaseName}</span>
        </div>
        {currentJob?.started_at && (
          <div style={ROW}>
            <span style={KEY}>Started</span>
            <span>{new Date(currentJob.started_at).toLocaleTimeString()}</span>
          </div>
        )}
      </div>

      <hr style={RULE} />

      <div style={{ flex: 1, minHeight: '100px', display: 'flex', flexDirection: 'column' }}>
        <span className="label" style={{ display: 'block', marginBottom: '12px' }}>
          Hotend temperature
        </span>
        {chartData.length > 0 ? (
          <div style={{ flex: 1, width: '100%' }}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData}>
                <YAxis domain={['auto', 'auto']} hide />
                <Line
                  type="monotone"
                  dataKey="temp"
                  stroke={accent}
                  strokeWidth={1.5}
                  dot={false}
                  isAnimationActive={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <div className="empty" style={{ flex: 1 }}>
            <span>No telemetry yet</span>
            <span>Readings appear once the printer reports</span>
          </div>
        )}
      </div>

      {showPreview && (
        <>
          <hr style={RULE} />
          <div style={{ flex: 2, minHeight: '200px', display: 'flex', flexDirection: 'column' }}>
            <span className="label" style={{ display: 'block', marginBottom: '12px' }}>
              Print preview
            </span>
            <div style={{ flex: 1, position: 'relative' }}>
              <GCodeViewer
                jobId={jobId}
                zHeightMm={
                  telemetrySamples.length > 0
                    ? telemetrySamples[telemetrySamples.length - 1].z_height_mm
                    : null
                }
              />
            </div>
          </div>
        </>
      )}

      <hr style={RULE} />

      <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
        <button
          type="button"
          className="btn btn-primary btn-block blueprint marked-accent"
          onClick={handlePrint}
          disabled={printDisabled}
          title={printHint}
        >
          <Marks />
          <PrinterIcon size={16} strokeWidth={1.5} />
          {dispatching ? 'Dispatching' : 'Print'}
        </button>
        {/* A disabled control keeps the caption that explains what would enable it. */}
        {printDisabled && !dispatching && <span className="hint">{printHint}</span>}

        <button
          type="button"
          className="btn btn-danger btn-block"
          onClick={handleStop}
          disabled={!isJobActive || cancelling}
        >
          <StopCircle size={16} strokeWidth={1.5} />
          {cancelling ? 'Stopping' : 'Stop job'}
        </button>
      </div>
    </Blueprint>
  );
}
