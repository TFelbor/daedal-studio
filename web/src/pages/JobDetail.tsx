import { useEffect, useMemo, useState } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import { Area, AreaChart, ResponsiveContainer, XAxis, YAxis } from 'recharts';
import { ArrowLeft, Loader2, Printer, RefreshCw } from 'lucide-react';
import {
  createJob,
  dispatchPrint,
  fitPhotoUrl,
  getJob,
  getJobTelemetry,
  reportOutcome,
} from '../api/client';
import type { FailureEvent, JobStatusResponse, TelemetrySample } from '../api/client';
import { BootMark } from '../components/BootMark';
import { DeadChannel } from '../components/DeadChannel';
import { DownloadFormats } from '../components/DownloadFormats';
import { PhaseProgress, derivePhases } from '../components/PhaseProgress';
import { StageState } from '../components/StageState';
import { stageStatus } from '../components/stageStatus';
import { PrintabilityCard } from '../components/PrintabilityCard';
import { FailureButton } from '../components/FailureButton';
import { FitPhotoInput } from '../components/FitPhotoInput';
import { MeshViewer } from '../components/MeshViewer';
import { PrinterStateCard } from '../components/PrinterStateCard';
import { ServicePlaceholder } from '../components/ServicePlaceholder';
import { Blueprint, Marks } from '../components/Blueprint';
import { SpecPanel } from '../components/SpecPanel';
import { NO_SPEC_REASON, specFromJob } from '../organizer/spec';
import { getConfig, testConnection } from '../api/config';
import { useJobWebSocket } from '../hooks/useJobWebSocket';
import { useAuthedObjectUrl } from '../hooks/useAuthedObjectUrl';
import styles from './JobDetail.module.css';
import { apiFetch } from '../api/http';

/** A job in one of these states will not change again on its own. */
const TERMINAL_STATUSES = new Set(['completed', 'failed', 'cancelled']);

const POLL_ACTIVE_MS = 5_000;
/** A settled job is still polled, but slowly: only a human verdict can change it now. */
const POLL_SETTLED_MS = 30_000;

/**
 * Firmware name → the service `/config/test-connection` actually knows about.
 *
 * Klipper speaks over Moonraker, which is the name the endpoint takes. Bambu has no
 * probe at all, so it maps to null and the check is skipped rather than sent and
 * reported as "Offline" forever.
 */
const CONNECTION_SERVICE: Record<string, string | null> = {
  octoprint: 'octoprint',
  klipper: 'moonraker',
  moonraker: 'moonraker',
  bambu: null,
};

type Connection = 'checking' | 'online' | 'offline' | 'unchecked';

const CONNECTION_PILL: Record<Connection, { className: string; label: string }> = {
  checking: { className: 'status status-run', label: 'Checking' },
  online: { className: 'status status-ok', label: 'Online' },
  offline: { className: 'status status-bad', label: 'Offline' },
  unchecked: { className: 'status status-off', label: 'Not checked' },
};

function statusPill(job: JobStatusResponse): { className: string; label: string } {
  if (job.outcome === 'success') return { className: 'status status-ok', label: 'Success' };
  if (job.outcome === 'awaiting_verdict') return { className: 'status status-ok', label: 'Awaiting verdict' };
  if (job.outcome === 'failure') return { className: 'status status-bad', label: 'Failure' };
  if (job.status === 'cancelled') return { className: 'status status-off', label: 'Cancelled' };
  if (job.status === 'failed') return { className: 'status status-bad', label: 'Failed' };
  if (job.status === 'running') return { className: 'status status-run', label: 'Running' };
  return { className: 'status status-off', label: 'Queued' };
}

function clockTime(epochMs: number): string {
  return new Date(epochMs).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function stamp(iso: string | null): string {
  if (!iso) return '—';
  return new Date(iso).toLocaleString([], {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function JobDetail() {
  const { id } = useParams<{ id: string }>();
  const [job, setJob] = useState<JobStatusResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [failureEvents, setFailureEvents] = useState<FailureEvent[]>([]);
  const [printerConfigured, setPrinterConfigured] = useState(false);
  const [connection, setConnection] = useState<Connection>('checking');
  const [printing, setPrinting] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const [blueprintOk, setBlueprintOk] = useState(true);
  const [verdictBusy, setVerdictBusy] = useState<'success' | 'failure' | null>(null);
  const [verdictError, setVerdictError] = useState<string | null>(null);
  const [fallbackTelemetry, setFallbackTelemetry] = useState<TelemetrySample[]>([]);
  const navigate = useNavigate();

  const { telemetrySamples, printerState, printerMeta } = useJobWebSocket(job ? job.job_id : null);

  // The blueprint route needs the shared secret, and the browser sends no headers of
  // ours on an `<img src>` — so the bytes are fetched here and shown as a blob.
  const blueprintSrc = useAuthedObjectUrl(job ? `/jobs/${job.job_id}/blueprint` : null);

  // Same reason, and asked for only once the row says there is one: `/photo` is a 404
  // for every job nobody has photographed, and requesting it anyway would put one in
  // the network log of every job page anyone opens.
  const fitPhotoSrc = useAuthedObjectUrl(
    job && job.has_fit_photo ? fitPhotoUrl(job.job_id) : null,
  );

  const fetchJob = async () => {
    if (!id) return;
    try {
      const data = await getJob(id);
      setJob(data);
      if (data.outcome === 'failure' || data.outcome === 'cancelled') {
        apiFetch(`/jobs/${id}/failure`)
          .then(res => res.json())
          .then((events: FailureEvent[]) => setFailureEvents(events))
          .catch(() => {});
      }
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setBlueprintOk(true);
    setFallbackTelemetry([]);
    fetchJob();
    getConfig()
      .then(data => {
        const isConfigured = !!(
          data['MOONRAKER_URL']?.value ||
          data['OCTOPRINT_URL']?.value ||
          data['BAMBU_IP']?.value
        );
        setPrinterConfigured(isConfigured);
      })
      .catch(() => {});
  }, [id]);

  const settled = job ? TERMINAL_STATUSES.has(job.status) : false;

  // A finished job cannot advance a phase, so the 5s poll would be pure noise.
  // It keeps ticking slowly because a human verdict can still land on it.
  useEffect(() => {
    if (!id) return;
    const intervalId = setInterval(fetchJob, settled ? POLL_SETTLED_MS : POLL_ACTIVE_MS);
    return () => clearInterval(intervalId);
  }, [id, settled]);

  useEffect(() => {
    const firmware = job?.printer_firmware;
    if (!firmware) return;
    const service = CONNECTION_SERVICE[firmware.toLowerCase()] ?? null;
    if (!service) {
      setConnection('unchecked');
      return;
    }
    let cancelled = false;
    setConnection('checking');
    testConnection(service)
      .then(res => {
        if (!cancelled) setConnection(res.success ? 'online' : 'offline');
      })
      .catch(() => {
        if (!cancelled) setConnection('offline');
      });
    return () => {
      cancelled = true;
    };
  }, [job?.printer_firmware]);

  // Live samples arrive over the WebSocket; a job that finished before the page
  // opened has none, so its history is read back once from the REST endpoint.
  const hasLiveTelemetry = telemetrySamples.length > 0;

  useEffect(() => {
    if (!id || hasLiveTelemetry) return;
    let cancelled = false;
    getJobTelemetry(id)
      .then(rows => {
        if (!cancelled) setFallbackTelemetry(rows);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [id, hasLiveTelemetry]);

  const samples = hasLiveTelemetry ? telemetrySamples : fallbackTelemetry;

  const temperature = useMemo(() => {
    const series = samples
      .filter(s => s.hotend_actual_c != null)
      .map(s => ({ at: new Date(s.sampled_at).getTime(), hotend: s.hotend_actual_c as number }));
    if (series.length === 0) return null;
    let peak = series[0].hotend;
    for (const point of series) if (point.hotend > peak) peak = point.hotend;
    let target: number | null = null;
    for (const s of samples) if (s.hotend_target_c != null) target = s.hotend_target_c;
    return { series, peak, target };
  }, [samples]);

  /**
   * Start a fresh job from this one, carrying the link between them.
   *
   * The link is the point. "The user asked for another one" is a judgement on this
   * result that nothing else records, and it is unrecoverable once the two jobs sit in
   * the database as unrelated rows.
   */
  const handleRegenerate = async () => {
    if (!job) return;
    setRegenerating(true);
    try {
      const created = await createJob({
        prompt: job.prompt,
        printer_id: job.printer_id || 'default_printer',
        profile: job.profile_name && job.profile_name !== 'default' ? job.profile_name : '',
        skip_visualizer: false,
        skip_sculptor: false,
        // Sliced but not sent, like every other job: the regenerated part stops at the
        // confirmation panel too.
        print: false,
        start_print: false,
        material_type: job.material_type || undefined,
        material_brand: job.material_brand || undefined,
        material_colour: job.material_colour || undefined,
        parent_job_id: job.job_id,
        // The size *is* carried over, unlike the seed. Regenerating means the result
        // was not wanted, not that the size was wrong — and this request is rebuilt
        // from the row, so a size omitted here silently falls back to the pipeline
        // default and the difference gets blamed on the model. `size_source` is
        // carried too, but only as a value the server will accept: it re-derives
        // "default" itself when no size is sent.
        target_mm: job.requested_size_mm ?? undefined,
        scale_axis:
          job.requested_size_mm != null
            ? ((job.requested_scale_axis as 'height' | 'longest' | null) ?? 'height')
            : undefined,
        size_source:
          job.requested_size_mm != null && job.size_source === 'prompt_hint'
            ? 'prompt_hint'
            : job.requested_size_mm != null
              ? 'user'
              : undefined,
        // A new seed on purpose: regenerating means the last result was not wanted, so
        // reusing its seed would reproduce exactly what the user rejected.
      });
      navigate(`/dashboard/${created.job_id}`);
    } catch (err) {
      console.error(err);
      alert(err instanceof Error ? err.message : 'Failed to regenerate');
    } finally {
      setRegenerating(false);
    }
  };

  /**
   * Send this job's existing G-code to the printer.
   *
   * The target goes back to the server exactly as it was rendered on this page, which
   * is what lets it refuse when the profile has been changed in Settings since. Pressing
   * the button *is* the confirmation — there is no unconfirmed dispatch path left.
   */
  const handlePrint = async () => {
    if (!job) return;
    setPrinting(true);
    try {
      const result = await dispatchPrint(job.job_id, job.dispatch_target ?? null);
      const where = result.target.machine_name || result.target.base_url || 'the printer';
      alert(`Sent to ${where}.`);
      setJob(await getJob(job.job_id));
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Failed to dispatch print');
    } finally {
      setPrinting(false);
    }
  };

  /**
   * Record the one signal the machine cannot produce.
   *
   * The printer reaching the end of the file is not the part surviving, so only a
   * person can close this out. Answering costs one tap on purpose.
   */
  const handleVerdict = async (verdict: 'success' | 'failure') => {
    if (!job) return;
    setVerdictBusy(verdict);
    setVerdictError(null);
    try {
      await reportOutcome(job.job_id, { verdict });
      await fetchJob();
    } catch (err) {
      setVerdictError(err instanceof Error ? err.message : 'Could not save that');
    } finally {
      setVerdictBusy(null);
    }
  };

  if (loading || !job) {
    return (
      <div className="sheet">
        <BootMark block label="Reading the job record" />
      </div>
    );
  }

  const phases = derivePhases(job);
  const isCompleted = job.status === 'completed' || job.outcome === 'success';
  const firmware = printerMeta.service || job.printer_firmware || 'octoprint';
  const machineName = printerMeta.machineName || job.machine_name;
  const layerHeightMm = printerMeta.layerHeightMm || job.layer_height_mm;
  const printerStateText: string = printerState?.state?.text
    ? String(printerState.state.text).toLowerCase()
    : job.status;
  const pill = statusPill(job);
  const connectionPill = CONNECTION_PILL[connection];

  /**
   * Whether there is a print on the machine right now.
   *
   * Not simply `status === 'running'`: the pipeline exits 0 the moment phase 5
   * dispatches the file, so a job whose outcome is already `awaiting_verdict` reads
   * as "completed" while the printer still has an hour of part to lay down — which
   * is precisely the window in which someone reaches for Cancel. The printer's own
   * flags settle it, and a genuinely finished job reports neither.
   */
  const printerBusy = Boolean(
    printerState?.state?.flags?.printing || printerState?.state?.flags?.paused,
  );
  const printIsLive = job.status === 'running' || printerBusy;

  // Only OctoPrint streams printer state; the other stacks dispatch and go quiet, so
  // they get the panel that says so rather than one stuck on "has not reported yet".
  // `moonraker` is folded into `klipper` because the config store persists the former
  // while the profiles use the latter.
  const streamsState = firmware === 'octoprint';
  const quietService: 'klipper' | 'bambu' | null =
    firmware === 'bambu'
      ? 'bambu'
      : firmware === 'klipper' || firmware === 'moonraker'
        ? 'klipper'
        : null;

  const layers =
    job.layer_count != null
      ? `${job.layer_count}${layerHeightMm ? ` · ${layerHeightMm} mm` : ''}`
      : null;
  const filament =
    job.filament_used_g != null
      ? `${job.filament_used_g.toFixed(1)} g${job.support_filament_mm3 ? ' incl. supports' : ''}`
      : null;
  const material = [job.material_type, job.material_brand, job.material_colour]
    .filter(Boolean)
    .join(' · ');

  return (
    <div className="sheet">
      <div className={styles.page}>
        <Link to="/dashboard" className={styles.backLink}>
          <ArrowLeft size={14} strokeWidth={1.5} /> Dashboard
        </Link>

        <div className={styles.header}>
          <div>
            <div className={styles.identity}>
              <span className={pill.className}>{pill.label}</span>
              <span className={styles.jobId}>{job.job_id}</span>
            </div>
            <h1 className={styles.title}>{job.prompt}</h1>
          </div>

          <div className={styles.actions}>
            {/* All three files, not the G-code alone: the engineered mesh was written
                to disk and had no way out of the app, and a printer this project
                cannot dispatch to is reached by opening the mesh in its own slicer. */}
            {isCompleted && <DownloadFormats jobId={job.job_id} />}
            {job.status !== 'running' && (
              // Regenerating is an implicit judgement on this result. Routing it through
              // here rather than the blank new-job form is what makes the lineage
              // recordable at all.
              <button
                type="button"
                className="btn btn-secondary"
                onClick={handleRegenerate}
                disabled={regenerating}
              >
                {regenerating ? (
                  <Loader2 size={14} className="spin" strokeWidth={1.5} />
                ) : (
                  <RefreshCw size={14} strokeWidth={1.5} />
                )}
                Regenerate
              </button>
            )}
            {/* Offered on the state, not on the status: "sliced and never sent" is the
                only condition under which this job has a print to authorise, and it
                says so rather than offering "Print again" for a part already made. */}
            {job.dispatch_state === 'awaiting_confirmation' && printerConfigured && (
              <button
                type="button"
                className="btn btn-primary blueprint marked-accent"
                onClick={handlePrint}
                disabled={printing}
                title={
                  job.dispatch_target?.machine_name || job.dispatch_target?.base_url || undefined
                }
              >
                <Marks />
                {printing ? (
                  <Loader2 size={16} className="spin" strokeWidth={1.5} />
                ) : (
                  <Printer size={16} strokeWidth={1.5} />
                )}
                {printing ? 'Sending' : 'Send to printer'}
              </button>
            )}
          </div>
        </div>

        <div className={styles.grid}>
          <div className={styles.mainCol}>
            <PhaseProgress jobId={job.job_id} />

            <div className={styles.specBlock}>
              <span className={`label ${styles.blockLabel}`}>Spec · what the part was built from</span>
              <SpecPanel spec={specFromJob(job)} unavailableReason={NO_SPEC_REASON} />
            </div>

            <div className={styles.figures}>
              <div className={styles.figure}>
                <span className={`label ${styles.blockLabel}`}>Blueprint</span>
                <Blueprint tone="accent" className={styles.frame}>
                  {blueprintOk && blueprintSrc ? (
                    <img
                      className={styles.frameImage}
                      src={blueprintSrc}
                      alt={`Blueprint for “${job.prompt}”`}
                      onError={() => setBlueprintOk(false)}
                    />
                  ) : (
                    // On a running job phase 1 is genuinely still working, so the
                    // frame reports that and carries its output. On a settled job
                    // nothing is coming, and the note says so — the derived line
                    // would read "phase 01 · done" over an empty frame.
                    <div className={styles.frameSlot}>
                      <StageState
                        phase={1}
                        status={stageStatus(phases[0]?.status)}
                        logLines={job.log_tail}
                        note={
                          phases[0]?.status === 'running'
                            ? undefined
                            : 'No blueprint on file for this job'
                        }
                      />
                    </div>
                  )}
                </Blueprint>
              </div>

              <div className={styles.figure}>
                <span className={`label ${styles.blockLabel}`}>Mesh</span>
                <Blueprint tone="accent" className={styles.frame}>
                  <div className={styles.frameSlot}>
                    <MeshViewer
                      jobId={job.job_id}
                      status={job.status}
                      phases={phases}
                      logLines={job.log_tail}
                      hasSpec={Boolean(job.spec)}
                    />
                  </div>
                </Blueprint>
              </div>
            </div>

            <PrintabilityCard
              jobId={job.job_id}
              supportFilamentMm3={job.support_filament_mm3}
            />

            <div>
              <span className={`label ${styles.blockLabel}`}>
                Hotend temperature · whole print
              </span>
              {temperature ? (
                <Blueprint className={styles.chartFrame}>
                  <div className={styles.chart}>
                    <ResponsiveContainer width="100%" height="100%">
                      <AreaChart
                        data={temperature.series}
                        margin={{ top: 4, right: 0, bottom: 0, left: 0 }}
                      >
                        <XAxis dataKey="at" hide />
                        <YAxis hide domain={['dataMin - 5', 'dataMax + 5']} />
                        <Area
                          type="monotone"
                          dataKey="hotend"
                          dot={false}
                          activeDot={false}
                          isAnimationActive={false}
                        />
                      </AreaChart>
                    </ResponsiveContainer>
                  </div>
                  <div className={styles.chartCaption}>
                    <span>{clockTime(temperature.series[0].at)}</span>
                    <span className={styles.chartCaptionMid}>
                      {temperature.target != null
                        ? `target ${temperature.target.toFixed(0)} °C · peak ${temperature.peak.toFixed(1)} °C`
                        : `peak ${temperature.peak.toFixed(1)} °C`}
                    </span>
                    <span>
                      {clockTime(temperature.series[temperature.series.length - 1].at)}
                    </span>
                  </div>
                </Blueprint>
              ) : (
                <DeadChannel height={148}>
                  {printIsLive
                    ? 'The hotend charts here once the printer starts reporting'
                    : 'No temperature readings for this job'}
                </DeadChannel>
              )}
            </div>
          </div>

          <div className={styles.sideCol}>
            {/* A live print leads the column: progress, ETA and the pause/cancel
                controls are what someone opening this page mid-print came for. On a
                finished job neither panel renders and the record leads instead. */}
            {printIsLive && streamsState && (
              <PrinterStateCard
                jobId={job.job_id}
                printerState={printerState}
                startedAt={job.started_at}
                layerHeightMm={layerHeightMm}
              />
            )}
            {printIsLive && quietService && <ServicePlaceholder service={quietService} />}

            <Blueprint className={styles.panel}>
              <span className={`label ${styles.blockLabel}`}>Record</span>
              <div className={styles.recordRows}>
                <div className={styles.recordRow}>
                  <span className={styles.recordKey}>Started</span>
                  <span className={styles.recordValue}>{stamp(job.started_at)}</span>
                </div>
                <div className={styles.recordRow}>
                  <span className={styles.recordKey}>Completed</span>
                  <span className={styles.recordValue}>{stamp(job.completed_at)}</span>
                </div>
                {material && (
                  <div className={styles.recordRow}>
                    <span className={styles.recordKey}>Material</span>
                    <span className={styles.recordValue}>{material}</span>
                  </div>
                )}
                {job.blueprint_seed != null && (
                  <div className={styles.recordRow}>
                    <span className={styles.recordKey}>Seed</span>
                    <span className={`${styles.recordValue} ${styles.recordMono}`}>
                      {job.blueprint_seed}
                    </span>
                  </div>
                )}
                {layers && (
                  <div className={styles.recordRow}>
                    <span className={styles.recordKey}>Layers</span>
                    <span className={styles.recordValue}>{layers}</span>
                  </div>
                )}
                {filament && (
                  <div className={styles.recordRow}>
                    <span className={styles.recordKey}>Filament</span>
                    <span className={styles.recordValue}>{filament}</span>
                  </div>
                )}
                {job.estimated_print_time_s != null && (
                  <div className={styles.recordRow}>
                    <span className={styles.recordKey}>Estimated time</span>
                    <span className={styles.recordValue}>
                      {Math.round(job.estimated_print_time_s / 60)} min
                    </span>
                  </div>
                )}
                {job.outcome_source && (
                  <div className={styles.recordRow}>
                    <span className={styles.recordKey}>Outcome reported by</span>
                    {/* "machine" means the printer reached the end of the file, which is
                        not the same as the part surviving. Worth showing plainly. */}
                    <span className={styles.recordValue}>
                      {job.outcome_source === 'user' ? 'a person' : 'the printer'}
                    </span>
                  </div>
                )}
                {job.parent_job_id && (
                  <div className={styles.recordRow}>
                    <span className={styles.recordKey}>Regenerated from</span>
                    <Link
                      to={`/dashboard/${job.parent_job_id}`}
                      className={`${styles.recordValue} ${styles.recordMono}`}
                    >
                      {job.parent_job_id.slice(0, 8)}
                    </Link>
                  </div>
                )}
              </div>
            </Blueprint>

            <Blueprint className={styles.panel}>
              <span className={`label ${styles.blockLabel}`}>Printer</span>
              <div className={styles.printerRow}>
                <div>
                  <div className="subheading">{machineName || job.printer_id || 'Printer'}</div>
                  <div className={styles.printerMeta}>
                    {firmware} · {printerStateText}
                  </div>
                </div>
                <span className={connectionPill.className}>{connectionPill.label}</span>
              </div>
            </Blueprint>

            {job.awaiting_verdict && (
              <Blueprint className={styles.panel}>
                <span className={`label ${styles.blockLabel}`}>Does it fit?</span>
                <p className={styles.verdictText}>
                  The printer says it finished. Only you can say whether the part came out and
                  holds what it was made for — that answer is the only ground truth here, and
                  it is what a fit guarantee would have to be built from.
                </p>
                <div className={styles.verdictActions}>
                  <button
                    type="button"
                    className="btn btn-ok"
                    onClick={() => handleVerdict('success')}
                    disabled={verdictBusy !== null}
                  >
                    {verdictBusy === 'success' ? (
                      <Loader2 size={14} className="spin" strokeWidth={1.5} />
                    ) : null}
                    Fits — it's good
                  </button>
                  <button
                    type="button"
                    className="btn btn-danger"
                    onClick={() => handleVerdict('failure')}
                    disabled={verdictBusy !== null}
                  >
                    {verdictBusy === 'failure' ? (
                      <Loader2 size={14} className="spin" strokeWidth={1.5} />
                    ) : null}
                    Doesn't fit / failed
                  </button>
                </div>
                {/* The evidence behind the word. Its own request, so it neither
                    blocks a verdict nor is blocked by one — and `fetchJob` is what
                    makes the photo appear in the panel below without a reload. */}
                <div className={styles.photoRow}>
                  <FitPhotoInput jobId={job.job_id} onUploaded={fetchJob} />
                </div>
                {verdictError && (
                  <div className={`notice ${styles.verdictNotice}`}>{verdictError}</div>
                )}
              </Blueprint>
            )}

            {/* Shown once there is a photo, and on any finished job that has been
                answered — otherwise saying "it fits" in the banner would take the
                camera away with it, and the part is still on the bed for an hour
                after the word. A job still awaiting its verdict is not included: the
                panel above already carries the control, and a second empty one below
                it would read as a second question. */}
            {(job.has_fit_photo || (job.status === 'completed' && !job.awaiting_verdict)) && (
              <Blueprint className={styles.panel}>
                <span className={`label ${styles.blockLabel}`}>Fit photo</span>
                {!job.has_fit_photo ? (
                  <p className={styles.verdictText}>
                    Nobody photographed this part. The score above is a prediction about a
                    mesh and the verdict is one word about a print; neither can be turned
                    back into what the thing actually looked like.
                  </p>
                ) : fitPhotoSrc ? (
                  <img
                    className={styles.fitPhoto}
                    src={fitPhotoSrc}
                    alt={`The printed part for “${job.prompt}”`}
                  />
                ) : (
                  <p className={styles.verdictText}>Loading the photo…</p>
                )}
                {/* Re-offered here, because the first photograph is often the one
                    taken in a hurry beside the printer. */}
                <div className={styles.photoRow}>
                  <FitPhotoInput jobId={job.job_id} onUploaded={fetchJob} />
                </div>
              </Blueprint>
            )}

            {job.status === 'running' && (
              <Blueprint className={styles.panel}>
                <span className={`label ${styles.blockLabel}`}>Something going wrong?</span>
                <p className={styles.verdictText}>
                  Reporting it now records the layer height and G-code line the print reached.
                </p>
                <FailureButton jobId={job.job_id} onReported={fetchJob} />
              </Blueprint>
            )}

            {failureEvents.length > 0 && (
              <Blueprint className={styles.panel}>
                <span className={`label ${styles.blockLabel}`}>Failure events</span>
                <div className={styles.failureRows}>
                  {failureEvents.map(evt => (
                    <div key={evt.event_id} className={styles.failureRow}>
                      <div className={styles.failureHead}>
                        <span className={styles.failureType}>
                          {evt.failure_type.replace(/_/g, ' ')}
                        </span>
                        <span className={styles.failureWhen}>
                          {stamp(evt.detected_at)}
                        </span>
                      </div>
                      <div className={styles.failureMeta}>
                        {[
                          evt.source,
                          evt.z_height_mm != null ? `z ${evt.z_height_mm.toFixed(1)} mm` : null,
                          evt.gcode_line != null ? `line ${evt.gcode_line}` : null,
                        ]
                          .filter(Boolean)
                          .join(' · ')}
                      </div>
                      {evt.notes && <div className={styles.failureNotes}>{evt.notes}</div>}
                    </div>
                  ))}
                </div>
              </Blueprint>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
