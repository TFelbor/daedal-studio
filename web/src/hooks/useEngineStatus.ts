import { useEffect, useState } from 'react';
import { getConfig, testConnection } from '../api/config';

export type EngineState = 'checking' | 'active' | 'unreachable' | 'unconfigured';

const FIRMWARE_SERVICE: Record<string, string> = {
  octoprint: 'octoprint',
  klipper: 'moonraker',
  moonraker: 'moonraker',
};

const POLL_MS = 60_000;

/**
 * Whether this machine can actually reach a printer right now.
 *
 * The nav pill states a fact, so it is measured rather than assumed: the printer
 * has to be configured *and* answer. Polled a minute apart because it costs a
 * real round trip to the printer, and the answer does not change faster than that.
 * Bambu is reported as configured-only — `/config/test-connection` has no MQTT
 * probe, so claiming "active" for it would be a guess.
 */
export function useEngineStatus(): EngineState {
  const [state, setState] = useState<EngineState>('checking');

  useEffect(() => {
    let cancelled = false;

    async function check() {
      try {
        const config = await getConfig();
        if (cancelled) return;

        const firmware = config.DEFAULT_PRINTER_FIRMWARE?.value?.toLowerCase() ?? 'octoprint';
        const hasTarget =
          config.OCTOPRINT_URL?.is_set || config.MOONRAKER_URL?.is_set || config.BAMBU_IP?.is_set;

        if (!hasTarget) {
          setState('unconfigured');
          return;
        }

        const service = FIRMWARE_SERVICE[firmware];
        if (!service) {
          setState('active');
          return;
        }

        const result = await testConnection(service);
        if (!cancelled) setState(result.success ? 'active' : 'unreachable');
      } catch {
        if (!cancelled) setState('unreachable');
      }
    }

    check();
    const timer = window.setInterval(check, POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  return state;
}

export function engineLabel(state: EngineState): string {
  switch (state) {
    case 'active':
      return 'Local engine · active';
    case 'unreachable':
      return 'Printer unreachable';
    case 'unconfigured':
      return 'Local engine · no printer';
    default:
      return 'Checking printer';
  }
}

export function engineStatusClass(state: EngineState): string {
  switch (state) {
    case 'active':
      return 'status status-ok';
    case 'unreachable':
    case 'unconfigured':
      return 'status status-bad';
    default:
      return 'status status-off';
  }
}
