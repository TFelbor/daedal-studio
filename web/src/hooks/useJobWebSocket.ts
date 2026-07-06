import { useEffect, useState } from 'react';
import type { TelemetrySample } from '../api/client';

export interface PrinterMeta {
  service: string | null;
  machineName: string | null;
  layerHeightMm: number | null;
  profileName: string | null;
}

export function useJobWebSocket(jobId: string | null) {
  const [telemetrySamples, setTelemetrySamples] = useState<TelemetrySample[]>([]);
  const [wsConnected, setWsConnected] = useState(false);
  const [phases, setPhases] = useState<any[]>([]);
  const [jobStatus, setJobStatus] = useState<string | null>(null);
  const [printerState, setPrinterState] = useState<any>(null);
  const [printerMeta, setPrinterMeta] = useState<PrinterMeta>({ service: null, machineName: null, layerHeightMm: null, profileName: null });

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
        if (msg.type === 'job_status') {
          const d = msg.data;
          setPrinterMeta({
            service: d.printer_firmware || null,
            machineName: d.machine_name || null,
            layerHeightMm: d.layer_height_mm || null,
            profileName: d.profile_name || null,
          });
        } else if (msg.type === 'telemetry_batch') {
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
          if (msg.data?.temperature) {
            const tool0 = msg.data.temperature.tool0 || msg.data.temperature.extruder;
            const bed = msg.data.temperature.bed;
            if (tool0?.actual != null || bed?.actual != null) {
              const syntheticSample = {
                sample_id: 'sync_' + Date.now(),
                job_id: jobId,
                sampled_at: new Date().toISOString(),
                hotend_actual_c: tool0?.actual || null,
                hotend_target_c: tool0?.target || null,
                bed_actual_c: bed?.actual || null,
                bed_target_c: bed?.target || null,
                z_height_mm: null,
                gcode_line: null,
                print_speed_pct: null,
                extrusion_factor_pct: null,
                fan_speed_pct: null
              };
              setTelemetrySamples(prev => {
                const next = [...prev, syntheticSample as any];
                if (next.length > 100) return next.slice(next.length - 100);
                return next;
              });
            }
          }
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

  return { telemetrySamples, wsConnected, phases, jobStatus, printerState, printerMeta };
}
