export interface PrintJob {
  job_id: string;
  prompt: string;
  printer_id: string;
  printer_firmware: string;
  slicer: string;
  profile_name: string;
  started_at: string;
  completed_at: string | null;
  outcome: string;
}

export interface JobResponse {
  job_id: string;
  status: string;
}

export interface JobStatusResponse {
  job_id: string;
  status: string;
  prompt: string;
  started_at: string;
  completed_at: string | null;
  outcome: string;
  log_tail: string[];
  current_phase: any | null;
}

export interface TelemetrySample {
  sample_id: string;
  job_id: string;
  timestamp: string;
  extruder_temp: number;
  bed_temp: number;
  z_height_mm: number | null;
  gcode_line: number | null;
  print_progress_pct: number | null;
  state: string;
}

export interface JobRequest {
  prompt: string;
  printer_id: string;
  profile: string;
  skip_visualizer: boolean;
  skip_sculptor: boolean;
  blueprint_path?: string;
  print: boolean;
  start_print: boolean;
}

export interface FailureRequest {
  failure_type: string;
  notes?: string;
}

export interface FailureEvent {
  event_id: string;
  job_id: string;
  detected_at: string;
  gcode_line: number | null;
  z_height_mm: number | null;
  failure_type: string;
  source: string;
  notes: string | null;
}

export async function createJob(request: JobRequest): Promise<JobResponse> {
  const res = await fetch('/jobs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request)
  });
  if (!res.ok) throw new Error('Failed to create job');
  return res.json();
}

export async function getJob(jobId: string): Promise<JobStatusResponse> {
  const res = await fetch(`/jobs/${jobId}`);
  if (!res.ok) throw new Error('Failed to fetch job status');
  return res.json();
}

export async function listJobs(): Promise<(PrintJob & { status: string })[]> {
  const res = await fetch('/jobs');
  if (!res.ok) throw new Error('Failed to list jobs');
  return res.json();
}

export async function getJobTelemetry(jobId: string): Promise<TelemetrySample[]> {
  const res = await fetch(`/jobs/${jobId}/telemetry`);
  if (!res.ok) throw new Error('Failed to fetch telemetry');
  return res.json();
}

export async function reportFailure(jobId: string, request: FailureRequest): Promise<FailureEvent> {
  const res = await fetch(`/jobs/${jobId}/failure`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request)
  });
  if (!res.ok) throw new Error('Failed to report failure');
  return res.json();
}
