import { useEffect, useState } from 'react';
import type { TelemetrySample } from '../api/client';

export function useJobWebSocket(jobId: string | null) {
  const [telemetrySamples, setTelemetrySamples] = useState<TelemetrySample[]>([]);
  const [wsConnected, setWsConnected] = useState(false);
  const [phases, setPhases] = useState<any[]>([]);
  const [jobStatus, setJobStatus] = useState<string | null>(null);
  const [printerState, setPrinterState] = useState<any>(null);

  useEffect(() => {
    if (!jobId) return;

    let mounted = true;
    const wsUrl = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws/jobs/${jobId}`;
    const ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      if (mounted) setWsConnected(true);
    };

    ws.onmessage = (event) => {
      if (!mounted) return;
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === 'telemetry_batch') {
          const sorted = [...msg.data].sort((a, b) => new Date(a.sampled_at).getTime() - new Date(b.sampled_at).getTime());
          setTelemetrySamples(sorted);
        } else if (msg.type === 'telemetry' || msg.type === 'telemetry_update') {
          setTelemetrySamples(prev => {
            const next = [...prev, msg.data];
            if (next.length > 100) return next.slice(next.length - 100);
            return next;
          });
        } else if (msg.type === 'printer_state') {
          setPrinterState(msg.data);
        } else if (msg.type === 'phase_update') {
          // This matches NewJob logic
          setPhases(prev => {
            const newPhases = [...prev];
            const idx = newPhases.findIndex(p => p.phase === msg.data.phase);
            if (idx >= 0) {
              newPhases[idx] = { ...newPhases[idx], status: msg.data.status };
            }
            for (let i = 0; i < idx; i++) {
              if (newPhases[i].status !== 'error') newPhases[i].status = 'complete';
            }
            return newPhases;
          });
        } else if (msg.type === 'job_complete') {
          setJobStatus(msg.data.outcome);
        }
      } catch (err) {
        console.error("WS Parse error", err);
      }
    };

    ws.onclose = () => {
      if (mounted) setWsConnected(false);
    };

    return () => {
      mounted = false;
      ws.close();
    };
  }, [jobId]);

  return { telemetrySamples, wsConnected, phases, jobStatus, printerState };
}
