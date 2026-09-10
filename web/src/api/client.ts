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

/**
 * What the pipeline records when the scorer itself breaks.
 *
 * Scoring is advisory, so a crash in it never fails a job — which used to mean it left
 * no trace at all, and the UI could not tell "nothing measured this mesh" from "the
 * measurement broke". Both then rendered as the same quiet empty state, which is the
 * one thing a quality gate must never look like.
 */
export interface PrintabilityFailure {
  job_id: string | null;
  evaluated_at: string | null;
  status: 'error';
  error: string;
  error_type?: string | null;
}

export type PrintabilityResult = PrintabilityReport | PrintabilityFailure;

/** Distinguishes a scored mesh from a recorded scoring failure. */
export function isPrintabilityReport(
  result: PrintabilityResult,
): result is PrintabilityReport {
  return Array.isArray((result as PrintabilityReport).checks);
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
  /** [width, depth, height] in mm. Null when the printer profile does not declare one. */
  build_volume_mm: number[] | null;
  nozzle_diameter_mm: number | null;
  printability_score: number | null;
  printability_verdict: string | null;
  material_type: string | null;
  material_brand: string | null;
  material_colour: string | null;
  /** The size the requester asked for, in mm, or null when they did not choose. */
  requested_size_mm: number | null;
  /** "default" | "user" | "prompt_hint" — who decided `requested_size_mm`. */
  size_source: string | null;
  /** "height" | "longest" — which extent `requested_size_mm` described. */
  requested_scale_axis: string | null;
  /**
   * "not_ready" | "awaiting_approval" | "approved" | "rejected".
   * Phase 2 does not run until this is "approved".
   */
  blueprint_gate_state: string;
  blueprint_gate_subject: BlueprintGateSubject | null;
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
  /** A bundled fixture stood in for Phase 1 or Phase 2 — nothing here came from a
   *  model. Null on rows written before the column existed, which is not the same
   *  as a verified false. */
  used_reference_assets: boolean | null;
  /** Where the job stands with Phase 5. See `dispatch_state` in server/app.py. */
  dispatch_state?: 'not_ready' | 'awaiting_confirmation' | 'dispatched';
  /** The printer a dispatch would go to, resolved when the job was read. */
  dispatch_target?: DispatchTarget | null;
  /** The canonical organizer spec this job was compiled from, or null for a prompt
   *  job. See `job_spec_summary` in server/app.py. */
  spec?: RawSpec | null;
  /** sha256 of the canonical spec — what Phase 2 recorded as `spec_sha256`. */
  spec_hash?: string | null;
  /** The archetype that compiled it, and the version of that archetype. The version
   *  is null until Phase 2 has run. */
  archetype?: string | null;
  archetype_version?: string | null;
  /** Phase 3's measurement of the compiled mesh against the spec. The only fit
   *  verdict on this endpoint, because it is the only one that was measured. */
  dimension_check?: DimensionCheck | null;
}

/**
 * The organizer spec as the server stores it: `pythonsrc/organizer/spec.py`, canonical.
 *
 * Every field is present, because `POST /jobs` normalises a submitted spec through
 * the schema before it is stored — a request may omit `process` and mean its defaults
 * by it, but what lands on the row and in `spec.json` never does.
 *
 * The two archetype-specific *sections* are the exception, and deliberately: an absent
 * one is **omitted** from the canonical form rather than written as null, so that
 * adding an archetype does not move the `spec_hash` of every spec that never mentioned
 * it. So `lid` is present on a deck box and absent on a divider, and `divider` the
 * other way round — read them as optional, not as always-there-and-maybe-null.
 */
export interface RawSpec {
  archetype: string;
  schema_version: number;
  compartments: { contents: { count: number; card: string; sleeving: string } }[];
  lid?: {
    kind: string;
    magnets: boolean;
    height_mm: number;
    wall_mm: number;
    clearance_mm: number;
    top_mm: number;
  } | null;
  divider?: {
    thickness_mm: number;
    tab_width_mm: number;
    tab_height_mm: number;
    tab_position: string;
  } | null;
  constraints: { max_external_mm: [number, number, number] | null };
  process: {
    wall_mm: number;
    floor_mm: number;
    cavity_clearance_mm: number;
    stack_slack_mm: number;
    min_feature_mm: number;
  };
}

/**
 * Phase 3's dimension check — every designed feature measured back off the exported
 * mesh. `pythonsrc/organizer/compiler.py::DimensionReport.to_dict`.
 */
export interface DimensionCheck {
  tolerance_mm: number;
  within_tolerance: boolean;
  features_checked: number;
  features_within: number;
  /** Null when nothing could be measured at all. */
  max_abs_error_mm: number | null;
  features: Record<string, { designed_mm: number; measured_mm: number; error_mm: number }>;
  missing: string[];
  out_of_tolerance: string[];
}

/** The full parametric record, from the un-polled `GET /jobs/{id}/spec`. */
export interface JobSpecResponse {
  job_id: string;
  spec: RawSpec;
  spec_hash: string | null;
  archetype: string | null;
  archetype_version: string | null;
  dimension_check: DimensionCheck | null;
  /** Every designed dimension the compiler produced — `compile_features.json`. */
  compile_features: {
    archetype: string;
    archetype_version: string;
    spec_sha256: string;
    parts: string[];
    features: Record<string, number>;
  } | null;
  /** The same document as `dimension_check`, read from the job's own artifact. */
  dimension_report: DimensionCheck | null;
}

export interface DispatchTarget {
  profile: string;
  firmware: string;
  base_url: string | null;
  machine_name: string | null;
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
  /**
   * Target size of the finished part, in millimetres. Omit to let the pipeline's
   * own default (50 mm) apply — sending an explicit 50 would be recorded as a
   * deliberate choice, which is a different fact.
   */
  target_mm?: number;
  /**
   * Which extent `target_mm` describes. Send whatever the control was labelled —
   * the row records it as the promise made, so a "Height" label that submitted a
   * longest-edge job is visible rather than silent.
   */
  scale_axis?: 'height' | 'longest';
  /**
   * Whether the person typed the size or accepted one parsed from their prompt.
   * Only the client knows which, so only the client can say. Omit when no size is
   * sent — the server writes "default" itself and will not take our word for it.
   */
  size_source?: 'user' | 'prompt_hint';
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
  /**
   * `dev` marks a developer's test run so it can be excluded from analysis; `declined`
   * records that the user was asked twice and does not want to be asked again. Neither
   * describes a part. See `OutcomeRequest` in server/app.py.
   */
  verdict: 'success' | 'failure' | 'cancelled' | 'dev' | 'declined';
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

/** A physical size read out of a prompt. A suggestion — never applied by itself. */
export interface SizeHint {
  /** The size in millimetres. Converted at the parser, so this is never inches. */
  mm: number;
  /** The exact substring that was matched, so the offer can quote it back. */
  text: string;
  /** Start and end offsets of `text` in the prompt. */
  span: [number, number];
  /** 'height' | 'longest', or null when the phrasing does not say which. */
  axis: 'height' | 'longest' | null;
}

/**
 * Ask whether a prompt states a physical size.
 *
 * Returns null when it does not, and a failure is also null: this is a
 * convenience, so a composer that cannot reach the endpoint should behave exactly
 * like one looking at a prompt with no size in it rather than showing an error.
 */
export async function fetchSizeHint(prompt: string): Promise<SizeHint | null> {
  try {
    const res = await fetch('/prompt/size-hint', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt }),
    });
    if (!res.ok) return null;
    return (await res.json()).hint ?? null;
  } catch {
    return null;
  }
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

/**
 * Send an already-sliced job to its printer.
 *
 * `confirmed` is the human in the loop, and the server requires it. The target is echoed
 * back as it was displayed, so a profile swapped in Settings while the confirmation was
 * on screen is answered with a 409 rather than a print to a machine nobody chose.
 */
/** What the person is being asked to approve, as the server resolved it. */
export interface BlueprintGateSubject {
  /** The blueprint's own hash, sent back so the server can refuse a stale approval. */
  sha256: string;
  url: string;
}

/**
 * Approve or reject a rendered blueprint.
 *
 * `confirmed: true` is the gate — the server has no unconfirmed code path, so an
 * empty body cannot start a reconstruction. `sha256` is the hash **as displayed**:
 * if the image has changed since, the server answers 409 rather than approving
 * something the person never saw.
 */
export async function decideBlueprint(
  jobId: string,
  approve: boolean,
  sha256?: string | null,
): Promise<{ decision: string; blueprint_gate_state: string }> {
  const res = await fetch(`/jobs/${jobId}/blueprint-approval`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ confirmed: true, approve, sha256: sha256 ?? null }),
  });
  if (!res.ok) {
    let detail = `The server answered ${res.status}`;
    try {
      const data = await res.json();
      if (data?.detail) detail = String(data.detail);
    } catch {
      // The body was not JSON; the status line is all there is to report.
    }
    throw new Error(detail);
  }
  return res.json();
}

export async function dispatchPrint(
  jobId: string,
  target?: DispatchTarget | null,
): Promise<{ status: string; target: DispatchTarget }> {
  const res = await fetch(`/jobs/${jobId}/print-dispatch`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      confirmed: true,
      profile: target?.profile ?? null,
      base_url: target?.base_url ?? null,
    }),
  });
  if (!res.ok) {
    let detail = `The server answered ${res.status}`;
    try {
      const data = await res.json();
      if (data?.detail) detail = String(data.detail);
    } catch {
      /* not JSON — the status code is the whole story */
    }
    throw new Error(detail);
  }
  return res.json();
}

export async function getJobPrintability(jobId: string): Promise<PrintabilityResult | null> {
  const res = await fetch(`/jobs/${jobId}/printability`);
  if (res.status === 404) return null;   // not every job reaches the Engineer
  if (!res.ok) throw new Error(`The server answered ${res.status} for this report`);
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
