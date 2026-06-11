export interface ConfigItem {
  value: string | null;
  is_set: boolean;
  label: string;
  description: string;
  required: boolean;
  secret: boolean;
}

export type ConfigResponse = Record<string, ConfigItem>;

export interface ConnectionTestResult {
  success: boolean;
  message: string;
  latency_ms: number | null;
}

export interface SimulatorStatus {
  moonraker: { running: boolean; port: number | null; url: string | null };
  octoprint: { running: boolean; port: number | null; url: string | null };
}

export async function getConfig(): Promise<ConfigResponse> {
  const res = await fetch('/config');
  if (!res.ok) throw new Error('Failed to fetch config');
  return res.json();
}

export async function setConfig(key: string, value: string): Promise<void> {
  const res = await fetch('/config', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ key, value })
  });
  if (!res.ok) throw new Error('Failed to set config');
}

export async function deleteConfig(key: string): Promise<void> {
  const res = await fetch(`/config/${key}`, { method: 'DELETE' });
  if (!res.ok) throw new Error('Failed to delete config');
}

export async function revealConfig(key: string): Promise<string> {
  const res = await fetch(`/config/${key}/reveal`);
  if (!res.ok) throw new Error('Failed to reveal config');
  const data = await res.json();
  return data.value;
}

export async function testConnection(service: string): Promise<ConnectionTestResult> {
  const res = await fetch('/config/test-connection', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ service })
  });
  if (!res.ok) throw new Error('Failed to test connection');
  return res.json();
}

export async function getSimulatorStatus(): Promise<SimulatorStatus> {
  const res = await fetch('/simulators/status');
  if (!res.ok) throw new Error('Failed to fetch simulator status');
  return res.json();
}

export async function startSimulator(service: string): Promise<void> {
  const res = await fetch(`/simulators/${service}/start`, { method: 'POST' });
  if (!res.ok) throw new Error('Failed to start simulator');
}

export async function stopSimulator(service: string): Promise<void> {
  const res = await fetch(`/simulators/${service}/stop`, { method: 'POST' });
  if (!res.ok) throw new Error('Failed to stop simulator');
}
