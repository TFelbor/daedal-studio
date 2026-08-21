import { useMemo, useState } from 'react';
import type { CSSProperties } from 'react';
import { StopCircle } from 'lucide-react';
import { Line, LineChart, ResponsiveContainer, YAxis } from 'recharts';
import { Blueprint } from './Blueprint';

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
  const [cancelling, setCancelling] = useState(false);
  const [stopError, setStopError] = useState<string | null>(null);
  const accent = useMemo(() => token('--accent'), []);

  const isJobActive = currentJob && currentJob.status !== 'completed' && currentJob.outcome !== 'cancelled';
  const currentPhaseName =
    phases.slice().reverse().find(p => p.status === 'running')?.name ||
    (currentJob?.status === 'completed' ? 'Done' : 'Queued');

  const handleStop = async () => {
    if (!jobId || cancelling) return;
    if (!confirm('Are you sure you want to cancel the job and printer?')) return;
    setCancelling(true);
    setStopError(null);
    try {
      const res = await fetch(`/jobs/${jobId}`, { method: 'DELETE' });
      if (!res.ok) {
        // The old version swallowed this: a failed cancel left the button re-enabled
        // and the job running, with nothing on screen to say the stop had not landed.
        let detail = `The server answered ${res.status}.`;
        try {
          const data = await res.json();
          if (data?.detail) detail = String(data.detail);
        } catch {
          /* not JSON — the status code is the whole story */
        }
        setStopError(detail);
      }
      // The button stays busy on success. The pipeline is killed with a grace period,
      // so the endpoint can take several seconds to return, and re-enabling a control
      // whose job is already terminal only invites a second press.
    } catch (err) {
      console.error(err);
      setStopError('Network error while stopping the job.');
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

      <hr style={RULE} />

      <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
        <button
          type="button"
          className="btn btn-danger btn-block"
          onClick={handleStop}
          disabled={!isJobActive || cancelling}
        >
          <StopCircle size={16} strokeWidth={1.5} />
          {cancelling ? 'Stopping' : isJobActive ? 'Stop job' : 'Stopped'}
        </button>
        {stopError && (
          <span className="hint" role="alert" style={{ color: 'var(--bad-ink)' }}>
            {stopError}
          </span>
        )}
      </div>
    </Blueprint>
  );
}
