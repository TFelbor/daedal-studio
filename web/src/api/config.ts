/**
 * Where a stored printer credential is allowed to go.
 *
 * A key is bound to the host it was saved beside, so changing the printer address
 * on its own stops the key being sent. Only the three printer credentials carry
 * this; every other key answers null.
 */

import { apiFetch } from './http';

export interface HostBinding {
  /** The host the stored key was saved for, or null when nothing is bound. */
  bound_to: string | null;
  /** The host the address configured right now points at. */
  target: string | null;
  /** Whether the key will be sent on the next request. */
  sends: boolean;
  /** Why it will not be, phrased for a person. */
  message: string | null;
}

export interface ConfigItem {
  value: string | null;
  is_set: boolean;
  label: string;
  description: string;
  required: boolean;
  secret: boolean;
  host_binding?: HostBinding | null;
}

export type ConfigResponse = Record<string, ConfigItem>;

export interface ConnectionTestResult {
  success: boolean;
  message: string;
  latency_ms: number | null;
}

export interface SimulatorStatus {
  moonraker: { running: boolean; port: number | null; url: string | null };
  octoprint: {
    running: boolean;
    port: number | null;
    url: string | null;
    api_key?: string | null;
    /** False when Docker could not be reached — "we cannot tell", not "stopped". */
    available?: boolean;
    /** Why the state is unknown, when it is. */
    error?: string | null;
  };
}

/**
 * Pull the server's own explanation out of a failed response.
 *
 * FastAPI puts it in `detail`, and it is written to be shown to a person — "Is
 * Docker Desktop running?" is far more use than "Failed to start simulator".
 */
async function errorDetail(res: Response, fallback: string): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body?.detail === 'string' && body.detail) return body.detail;
  } catch {
    // Not JSON; fall through to the generic message.
  }
  return fallback;
}

export async function getConfig(): Promise<ConfigResponse> {
  const res = await apiFetch('/config');
  if (!res.ok) throw new Error('Failed to fetch config');
  return res.json();
}

export async function setConfig(key: string, value: string): Promise<void> {
  const res = await apiFetch('/config', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ key, value })
  });
  if (!res.ok) throw new Error('Failed to set config');
}

export async function deleteConfig(key: string): Promise<void> {
  const res = await apiFetch(`/config/${key}`, { method: 'DELETE' });
  if (!res.ok) throw new Error('Failed to delete config');
}

export async function revealConfig(key: string): Promise<string> {
  const res = await apiFetch(`/config/${key}/reveal`);
  if (!res.ok) throw new Error('Failed to reveal config');
  const data = await res.json();
  return data.value;
}

export async function testConnection(service: string): Promise<ConnectionTestResult> {
  const res = await apiFetch('/config/test-connection', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ service })
  });
  if (!res.ok) throw new Error('Failed to test connection');
  return res.json();
}

export async function getSimulatorStatus(): Promise<SimulatorStatus> {
  const res = await apiFetch('/simulators/status');
  if (!res.ok) throw new Error('Failed to fetch simulator status');
  return res.json();
}

export async function startSimulator(service: string): Promise<void> {
  const res = await apiFetch(`/simulators/${service}/start`, { method: 'POST' });
  if (!res.ok) throw new Error(await errorDetail(res, 'Could not start the simulator.'));
}

export async function stopSimulator(service: string): Promise<void> {
  const res = await apiFetch(`/simulators/${service}/stop`, { method: 'POST' });
  if (!res.ok) throw new Error(await errorDetail(res, 'Could not stop the simulator.'));
}
