export interface PrintJob {
  job_id: string;
  prompt: string;
  printer_id: string;
  printer_firmware: string;
  slicer: string;
  profile_name: string;
  started_at: string | null;
  completed_at: string | null;
  outcome: string;
}

export interface JobResponse {
  job_id: string;
  status: string;
}

export interface PrintabilityCheck {
  check: string;
  status: 'pass' | 'warn' | 'fail' | 'not_checked';
  detail: string;
  value: unknown;
  threshold: unknown;
  weight: number;
  critical: boolean;
}

export interface PrintabilityReport {
  job_id: string | null;
  evaluated_at: string | null;
  process: string;
  score: number;
  verdict: 'ready' | 'risky' | 'unprintable';
  checks: PrintabilityCheck[];
  features: Record<string, unknown>;
}

export interface JobStatusResponse {
  job_id: string;
  status: string;
  prompt: string;
  started_at: string | null;
  completed_at: string | null;
  outcome: string;
  log_tail: string[];
  current_phase: any | null;
  printer_id: string | null;
  printer_firmware: string | null;
  profile_name: string | null;
  machine_name: string | null;
  layer_height_mm: number | null;
  printability_score: number | null;
  printability_verdict: string | null;
  material_type: string | null;
  material_brand: string | null;
  material_colour: string | null;
  blueprint_seed: number | null;
  parent_job_id: string | null;
  download_count: number;
  slice_status: string | null;
  estimated_print_time_s: number | null;
  filament_used_mm3: number | null;
  filament_used_g: number | null;
  support_filament_mm3: number | null;
  layer_count: number | null;
  outcome_source: string | null;
  /** The printer finished, but no human has confirmed the part survived. */
  awaiting_verdict: boolean;
}

export interface TelemetrySample {
  sample_id: string;
  job_id: string;
  sampled_at: string;
  hotend_actual_c: number | null;
  hotend_target_c: number | null;
  bed_actual_c: number | null;
  bed_target_c: number | null;
  z_height_mm: number | null;
  gcode_line: number | null;
  print_speed_pct: number | null;
  extrusion_factor_pct: number | null;
  fan_speed_pct: number | null;
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
  material_type?: string;
  material_brand?: string;
  material_colour?: string;
  /** Omit to let the server draw and record one; supply to reproduce a past result. */
  seed?: number;
  parent_job_id?: string;
  regeneration_reason?: string;
  /** TRELLIS.2 voxel resolution for Phase 2. Omit for the server default. */
  pipeline_type?: PipelineType;
  /**
   * Seed for the reconstruction — *not* `seed`, which seeds the blueprint.
   * They are separate so one image can be re-sculpted more than one way.
   */
  mesh_seed?: number;
}

/** Filament types the mass estimate has a density for. */
export const MATERIAL_TYPES = ['PLA', 'PETG', 'ABS', 'TPU', 'ASA', 'Nylon'] as const;

/**
 * TRELLIS.2 voxel resolutions, cheapest first. Higher resolutions resolve finer
 * detail at more GPU time; `1024_cascade` is the default.
 */
export const PIPELINE_TYPES = ['512', '1024', '1024_cascade', '1536_cascade'] as const;
export type PipelineType = (typeof PIPELINE_TYPES)[number];

export interface PendingFeedbackJob {
  job_id: string;
  prompt: string;
  printer_id: string;
  material_type: string | null;
  completed_at: string | null;
  estimated_print_time_s: number | null;
  printability_score: number | null;
}

export interface OutcomeRequest {
  verdict: 'success' | 'failure' | 'cancelled';
  failure_type?: string;
  notes?: string;
  layer_pct?: number;
}

export interface OutcomeResponse {
  job_id: string;
  outcome: string;
  outcome_source: string;
  failure_event_id: string | null;
}

/** The full capture record for one job — everything `/jobs/{id}/provenance` returns. */
export interface JobProvenance {
  job_id: string;
  prompt: string;
  blueprint: {
    model: string | null;
    model_version: string | null;
    seed: number | null;
    prompt_engineered: string | null;
    params: Record<string, unknown> | null;
    sha256: string | null;
    duration_s: number | null;
  };
  generation: {
    model: string | null;
    model_version: string | null;
    backend: string | null;
    params: Record<string, unknown> | null;
    cost_eur: number | null;
    duration_s: number | null;
  };
  mesh: {
    raw_sha256: string | null;
    raw_features: Record<string, unknown> | null;
    repaired_sha256: string | null;
    repaired_features: Record<string, unknown> | null;
    printed_features: Record<string, unknown> | null;
  };
  printability: { score: number | null; verdict: string | null };
  slice: {
    status: string | null;
    error: string | null;
    duration_s: number | null;
    estimated_print_time_s: number | null;
    filament_used_mm: number | null;
    filament_used_mm3: number | null;
    filament_used_g: number | null;
    support_filament_mm3: number | null;
    layer_count: number | null;
    stats: Record<string, unknown> | null;
  };
  target: {
    printer_id: string;
    printer_firmware: string;
    profile_name: string;
    process_params: Record<string, unknown> | null;
    nozzle_diameter_mm: number | null;
    material_type: string | null;
    material_brand: string | null;
    material_colour: string | null;
  };
  engagement: {
    download_count: number;
    parent_job_id: string | null;
    regeneration_reason: string | null;
    events: {
      event_id: string;
      job_id: string;
      occurred_at: string;
      kind: string;
      detail: Record<string, unknown> | null;
    }[];
  };
  outcome: {
    outcome: string;
    source: string | null;
    reported_at: string | null;
    completed_at: string | null;
  };
}

export interface FeedbackStats {
  prompts_shown: number;
  outcomes_reported: number;
  prompts_dismissed: number;
  unanswered: number;
  outcomes_reported_total: number;
  pending: number;
  response_rate: number | null;
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

export interface PrinterInfo {
  service: string;
  service_label: string;
  printer_name: string;
  profile_name: string | null;
  connection_status: 'online' | 'offline' | 'unknown';
  layer_height_mm: number | null;
  machine_dimensions: { width: number; depth: number; height: number } | null;
}

export async function createJob(request: JobRequest): Promise<JobResponse> {
  const res = await fetch('/jobs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request)
  });
  if (!res.ok) {
    const errBody = await res.json().catch(() => null);
    throw new Error(errBody?.detail || `Failed to create job (${res.status})`);
  }
  return res.json();
}

export async function getJob(jobId: string): Promise<JobStatusResponse> {
  const res = await fetch(`/jobs/${jobId}`);
  if (!res.ok) throw new Error('Failed to fetch job status');
  return res.json();
}

export async function getPrinterInfo(jobId: string): Promise<PrinterInfo> {
  const res = await fetch(`/jobs/${jobId}/printer-info`);
  if (!res.ok) throw new Error('Failed to fetch printer info');
  return res.json();
}

export interface PaginatedJobs {
  jobs: (PrintJob & { status: string })[];
  total: number;
  limit: number;
  offset: number;
  stats: {
    total: number;
    running: number;
    completed: number;
    failed: number;
    awaiting_verdict: number;
  };
}

export async function listJobs(limit = 20, offset = 0, status = 'all'): Promise<PaginatedJobs> {
  const res = await fetch(`/jobs?limit=${limit}&offset=${offset}&status=${status}`);
  if (!res.ok) throw new Error('Failed to list jobs');
  return res.json();
}

export async function getJobPrintability(jobId: string): Promise<PrintabilityReport | null> {
  const res = await fetch(`/jobs/${jobId}/printability`);
  if (res.status === 404) return null;   // not every job reaches the Engineer
  if (!res.ok) throw new Error('Failed to fetch printability report');
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

// ── Print outcome feedback ───────────────────────────────────────────────────
// A printer reporting "job finished" only means the file ran to the end. Whether the
// part adhered and came off the bed intact is knowable only by the person next to the
// machine, so the whole point of this surface is that answering costs one tap.

export async function listPendingFeedback(): Promise<{ count: number; jobs: PendingFeedbackJob[] }> {
  const res = await fetch('/feedback/pending');
  if (!res.ok) throw new Error('Failed to fetch pending feedback');
  return res.json();
}

/**
 * Record that the outcome prompt was actually put in front of someone.
 *
 * The server deduplicates, so a re-render cannot inflate the denominator of the
 * response rate.
 */
export async function markOutcomePromptShown(jobId: string): Promise<void> {
  await fetch(`/jobs/${jobId}/outcome/prompt-shown`, { method: 'POST' });
}

/** Record a skip. A declined prompt is data; only a prompt never shown is silence. */
export async function dismissOutcomePrompt(jobId: string): Promise<void> {
  const res = await fetch(`/jobs/${jobId}/outcome/dismiss`, { method: 'POST' });
  if (!res.ok) throw new Error('Failed to dismiss prompt');
}

export async function reportOutcome(jobId: string, request: OutcomeRequest): Promise<OutcomeResponse> {
  const res = await fetch(`/jobs/${jobId}/outcome`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request)
  });
  if (!res.ok) {
    const errBody = await res.json().catch(() => null);
    throw new Error(errBody?.detail || 'Failed to report outcome');
  }
  return res.json();
}

export async function getFeedbackStats(): Promise<FeedbackStats> {
  const res = await fetch('/feedback/stats');
  if (!res.ok) throw new Error('Failed to fetch feedback stats');
  return res.json();
}

export async function getJobProvenance(jobId: string): Promise<JobProvenance> {
  const res = await fetch(`/jobs/${jobId}/provenance`);
  if (!res.ok) throw new Error('Failed to fetch job provenance');
  return res.json();
}

export async function printerAction(jobId: string, action: 'pause' | 'resume' | 'cancel'): Promise<any> {
  const res = await fetch(`/jobs/${jobId}/action`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action })
  });
  if (!res.ok) {
    const errBody = await res.json().catch(() => null);
    throw new Error(errBody?.detail || `Failed to execute action ${action}`);
  }
  return res.json();
}
