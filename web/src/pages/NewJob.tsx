import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { AlertTriangle, ArrowRight, Check, ChevronDown, Layers, Maximize2, RotateCcw } from 'lucide-react';
import { Blueprint, Marks } from '../components/Blueprint';
import { BlueprintPreview } from '../components/BlueprintPreview';
import { DeadChannel } from '../components/DeadChannel';
import { MeshViewer } from '../components/MeshViewer';
import { GCodeViewer } from '../components/GCodeViewer';
import { ProcessLog } from '../components/ProcessLog';
import { PromptComposer } from '../components/PromptComposer';
import { WaitingStage } from '../components/WaitingStage';
import { JobControlPanel } from '../components/JobControlPanel';
import { DispatchGate } from '../components/DispatchGate';
import { PrintabilityCard } from '../components/PrintabilityCard';
import { PromptZoom } from '../components/PromptZoom';
import { COUNTER_REVEAL, MAX_PROMPT_CHARS } from '../components/promptLimits';
import { createJob, getJob, listJobs, MATERIAL_TYPES } from '../api/client';
import type { JobStatusResponse, TelemetrySample } from '../api/client';
import { getConfig } from '../api/config';
import { reportUi } from '../api/activity';
import { useActivityFeed } from '../hooks/useActivityFeed';
import styles from './NewJob.module.css';

interface PhaseStatus {
  phase: number;
  name: string;
  status: 'pending' | 'running' | 'complete' | 'error';
}

/** The job as it arrives over the socket — partial, because a fresh job has no result yet. */
type LiveJob = Partial<JobStatusResponse>;

/** What the printer probe answers. Only `configured && running` is a printer you can send to. */
interface PrinterProbe {
  configured: boolean;
  running: boolean;
  type: string;
}

/**
 * The five phases, in the order they run, with the one line each needs to explain
 * itself before anything has happened yet. The numbering is structure: the pipeline
 * is genuinely ordered, and the same numbers key the .status protocol.
 */
const PIPELINE = [
  { phase: 1, name: 'Visualizer', blurb: 'Prompt becomes a clay-render blueprint image', tag: 'FLUX.2' },
  { phase: 2, name: 'Sculptor', blurb: 'Blueprint reconstructed as a 3D geometry mesh', tag: 'TRELLIS.2' },
  { phase: 3, name: 'Engineer', blurb: 'Watertight repair, scaled to the print bed', tag: '.OBJ / .STL' },
  { phase: 4, name: 'Slicer', blurb: 'Wall thickness and overhangs inspected, then sliced', tag: 'G-CODE' },
  { phase: 5, name: 'Operator', blurb: 'Streamed to OctoPrint, Klipper or Bambu Lab', tag: 'JOB' },
];

/** Lines held in memory. The full log is on disk; ProcessLog renders the tail. */
const LOG_BUFFER = 800;

/** Outcomes after which nothing else will happen on its own. */
const TERMINAL_OUTCOMES = new Set(['success', 'awaiting_verdict', 'failure', 'cancelled']);

/** Statuses meaning the same, for a row whose outcome has not been written yet. */
const TERMINAL_STATUSES = new Set(['completed', 'failed', 'cancelled']);

const STAGE_TABS = [
  { id: 'blueprint', label: 'Blueprint', phase: 1 },
  { id: 'mesh', label: 'Mesh', phase: 3 },
  { id: 'slice', label: 'Slice', phase: 4 },
] as const;

type StageTab = (typeof STAGE_TABS)[number]['id'];

function pad2(value: number): string {
  return String(value).padStart(2, '0');
}

function parseTs(value: string | null | undefined): number | null {
  if (!value) return null;
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? null : parsed;
}

function formatElapsed(ms: number): string {
  const total = Math.floor(ms / 1000);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  return hours > 0
    ? `${hours}:${pad2(minutes)}:${pad2(seconds)}`
    : `${pad2(minutes)}:${pad2(seconds)}`;
}

function formatPrintTime(seconds: number): string {
  const totalMinutes = Math.round(seconds / 60);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return hours > 0 ? `${hours}h ${pad2(minutes)}m` : `${minutes}m`;
}

/** "pythonsrc/profiles/anycubic_mega.json" → "Anycubic Mega". */
function printerNameFromProfile(profile: string): string | null {
  const base = profile.split('/').pop()?.replace(/\.json$/, '') ?? '';
  if (!base) return null;
  return base
    .split(/[_-]/)
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}

const PHASE_NUM_CLASS: Record<PhaseStatus['status'], string> = {
  complete: 'phase-num-done',
  running: 'phase-num-run',
  // A failed phase is red, not the action orange `.phase-num` defaults to.
  error: styles.numBad,
  pending: 'phase-num-idle',
};

const MARK_CLASS: Record<PhaseStatus['status'], string> = {
  complete: styles.markOk,
  running: '',   // the running dots carry their own colour
  error: styles.markBad,
  pending: '',
};

const MARK_LABEL: Record<PhaseStatus['status'], string> = {
  complete: 'Done',
  running: 'Running',
  error: 'Failed',
  pending: 'Pending',
};

export function NewJob() {
  const [prompt, setPrompt] = useState('');
  const [materialType, setMaterialType] = useState('PLA');
  const [materialBrand, setMaterialBrand] = useState('');
  const [materialColour, setMaterialColour] = useState('');
  const [seed, setSeed] = useState('');
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [loading, setLoading] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const [jobId, setJobId] = useState<string | null>(null);
  const [currentJob, setCurrentJob] = useState<LiveJob | null>(null);
  const [phases, setPhases] = useState<PhaseStatus[]>([]);
  const [telemetrySamples, setTelemetrySamples] = useState<TelemetrySample[]>([]);
  /** The pipeline's stdout, newest last. Fed by the socket's batched `log` messages. */
  const [logLines, setLogLines] = useState<string[]>([]);
  const [wsConnected, setWsConnected] = useState(false);
  const [activeTab, setActiveTab] = useState<StageTab>('blueprint');
  /** Ticks the elapsed figure. Presentation only — nothing is fetched on this timer. */
  const [now, setNow] = useState(() => Date.now());
  /** Whether the inline composer for the *next* job is open. */
  const [composerOpen, setComposerOpen] = useState(false);
  /** Whether the landing prompt is raised onto its own plate. */
  const [promptZoomed, setPromptZoomed] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);
  const pollIntervalRef = useRef<number | null>(null);
  /** Once someone picks a tab themselves, the stage stops following the pipeline. */
  const tabPinnedRef = useRef(false);
  /** Fallback clock for a job whose server-side start time has not arrived yet.
      State rather than a ref because the elapsed figure is rendered from it, and a
      ref read during render is not safe under concurrent rendering. */
  const [attachedAt, setAttachedAt] = useState(() => Date.now());

  const [configDefaults, setConfigDefaults] = useState<{
    skipVisualizer: boolean;
    skipSculptor: boolean;
    profile: string;
  }>({ skipVisualizer: false, skipSculptor: false, profile: '' });

  const [printer, setPrinter] = useState<PrinterProbe | null>(null);
  /** The server's own activity — config edits, printer replies, phase boundaries. */
  const serverActivity = useActivityFeed();
  const printerReady = printer?.configured === true && printer?.running === true;

  useEffect(() => {
    getConfig()
      .then(data => {
        setConfigDefaults({
          skipVisualizer: data['SKIP_VISUALIZER']?.value === 'true',
          skipSculptor: data['SKIP_SCULPTOR']?.value === 'true',
          profile: data['DEFAULT_PROFILE']?.value || '',
        });
      })
      .catch(() => {});

    const checkPrinter = async () => {
      try {
        const res = await fetch('/system/printer/status');
        if (res.ok) {
          setPrinter((await res.json()) as PrinterProbe);
        }
      } catch {
        // The notice below is the user-facing answer; a console line adds nothing.
      }
    };
    checkPrinter();
    const interval = setInterval(checkPrinter, 5000);
    return () => clearInterval(interval);
  }, []);

  // Initialize phases
  useEffect(() => {
    if (!jobId) {
      setPhases(PIPELINE.map(p => ({ phase: p.phase, name: p.name, status: 'pending' })));
      setCurrentJob(null);
      setTelemetrySamples([]);
      setLogLines([]);
    }
  }, [jobId]);

  /**
   * Re-attach on mount — to a running job, or to one holding at the dispatch gate.
   *
   * The second case is what makes the confirmation step survive a reload. A job that
   * has been sliced and not sent has finished as far as the pipeline is concerned, so
   * it does not appear in the running list, and before this the pending decision simply
   * vanished on refresh and the part was never printed.
   */
  useEffect(() => {
    let cancelled = false;

    const attach = (job: { job_id: string; prompt: string }, live: boolean) => {
      if (cancelled) return;
      setAttachedAt(Date.now());
      setJobId(job.job_id);
      setPrompt(job.prompt);
      if (live) connectWebSocket(job.job_id);
      else getJob(job.job_id).then(setCurrentJob).catch(() => {});
    };

    listJobs(1, 0, 'running')
      .then(data => {
        if (data.jobs && data.jobs.length > 0) {
          attach(data.jobs[0], true);
          return null;
        }
        return listJobs(1, 0, 'awaiting_dispatch');
      })
      .then(waiting => {
        if (waiting?.jobs && waiting.jobs.length > 0) attach(waiting.jobs[0], false);
      })
      .catch(err => {
        console.error('Failed to look for a job to attach to on mount', err);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const connectWebSocket = (id: string) => {
    // Confirming a dispatch reconnects, so this can be called with a socket already
    // open. Closing the old one first is what stops two sockets writing the same state,
    // and every handler below checks it is still the current one before doing so.
    wsRef.current?.close();

    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${wsProtocol}//${window.location.host}/ws/jobs/${id}`;
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      if (wsRef.current !== ws) return;
      setWsConnected(true);
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
      }
    };

    ws.onmessage = (event) => {
      if (wsRef.current !== ws) return;
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === 'job_status') {
          setCurrentJob(msg.data);
        } else if (msg.type === 'phase_update') {
          setPhases(prev => {
            const newPhases = [...prev];
            const idx = newPhases.findIndex(p => p.phase === msg.data.phase);
            if (idx >= 0) {
              newPhases[idx] = { ...newPhases[idx], status: msg.data.status };
            }
            // Mark previous phases as complete if a later phase starts/completes
            for (let i = 0; i < idx; i++) {
              if (newPhases[i].status !== 'error') {
                newPhases[i].status = 'complete';
              }
            }
            return newPhases;
          });
        } else if (msg.type === 'telemetry_batch') {
          setTelemetrySamples(msg.data);
        } else if (msg.type === 'telemetry' || msg.type === 'telemetry_update') {
          setTelemetrySamples(prev => {
            const next = [...prev, msg.data];
            if (next.length > 20) return next.slice(next.length - 20);
            return next;
          });
        } else if (msg.type === 'printer_state') {
          if (msg.data?.temperature) {
            const tool0 = msg.data.temperature.tool0 || msg.data.temperature.extruder;
            const bed = msg.data.temperature.bed;
            if (tool0?.actual != null || bed?.actual != null) {
              const syntheticSample: TelemetrySample = {
                sample_id: 'sync_' + Date.now(),
                job_id: id,
                sampled_at: new Date().toISOString(),
                hotend_actual_c: tool0?.actual || 0,
                hotend_target_c: tool0?.target || 0,
                bed_actual_c: bed?.actual || 0,
                bed_target_c: bed?.target || 0,
                z_height_mm: null,
                gcode_line: null,
                print_speed_pct: null,
                extrusion_factor_pct: null,
                fan_speed_pct: null
              };
              setTelemetrySamples(prev => {
                const next = [...prev, syntheticSample];
                if (next.length > 20) return next.slice(next.length - 20);
                return next;
              });
            }
          }
        } else if (msg.type === 'log') {
          // Trim on ingest, not on render: an unbounded array is a leak on a job that
          // runs for an hour, and only the tail is ever displayed.
          setLogLines(prev => {
            const next = [...prev, ...(msg.data.lines ?? [])];
            return next.length > LOG_BUFFER ? next.slice(next.length - LOG_BUFFER) : next;
          });
        } else if (msg.type === 'job_complete') {
          const outcome = msg.data.outcome;
          setCurrentJob(prev => ({
            ...(prev ?? {}),
            status: outcome === 'cancelled' ? 'cancelled' : 'completed',
            outcome,
            // Stamp the end so the elapsed figure freezes on the instant the job
            // stopped rather than on whichever second the 1s tick last fired. The
            // next poll replaces this with the server's own value; until then, the
            // socket arriving *is* the event, so the two are the same moment.
            completed_at: prev?.completed_at ?? new Date().toISOString(),
          }));
          // Nothing is running any more. Without this the phase that was live when
          // the job stopped keeps its running status — and keeps pulsing, in the rail
          // and on the waiting stage — which is what made Stop job look like it had
          // done nothing at all.
          if (outcome !== 'success' && outcome !== 'awaiting_verdict') {
            setPhases(prev =>
              prev.map(p => (p.status === 'running' ? { ...p, status: 'error' } : p)),
            );
          }
          // One authoritative read. `dispatch_state` is derived on the server and the
          // socket's completion message does not carry it, so without this the
          // confirmation panel would not appear until something else refetched.
          getJob(id).then(setCurrentJob).catch(() => {});
        }
      } catch (e) {
        console.error('WS parse error', e);
      }
    };

    ws.onclose = () => {
      if (wsRef.current !== ws) return;
      setWsConnected(false);
      // Start polling fallback if job is not completed
      if (currentJob?.status !== 'completed' && currentJob?.outcome !== 'cancelled') {
        startPolling(id);
      }
    };
  };

  const startPolling = (id: string) => {
    if (pollIntervalRef.current) return;
    pollIntervalRef.current = window.setInterval(async () => {
      try {
        const data = await getJob(id);
        setCurrentJob(data);
        if (data.current_phase) {
          setPhases(prev => {
            const newPhases = [...prev];
            if (data.current_phase) {
              for (let i = 0; i < Math.min(data.current_phase.phase - 1, newPhases.length); i++) {
                if (newPhases[i].status !== 'error') newPhases[i].status = 'complete';
              }
              const idx = newPhases.findIndex(p => p.phase === data.current_phase.phase);
              if (idx >= 0) newPhases[idx] = { ...newPhases[idx], status: data.current_phase.status };
            }
            return newPhases;
          });
        }
        if (data.status === 'completed' || data.outcome === 'cancelled') {
          if (pollIntervalRef.current) { clearInterval(pollIntervalRef.current); pollIntervalRef.current = null; }
        }
      } catch (e: any) {
        if (e?.message?.includes('404') || e?.status === 404) {
          if (pollIntervalRef.current) { clearInterval(pollIntervalRef.current); pollIntervalRef.current = null; }
        }
        console.error('Polling failed', e);
      }
    }, 5000);
  };

  useEffect(() => {
    return () => {
      if (wsRef.current) wsRef.current.close();
      if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
    };
  }, []);

  const isRunning = jobId !== null;
  /**
   * A job stops for four reasons, and the clock has to stop for all of them.
   *
   * This used to be `status !== 'completed' && outcome !== 'cancelled'`, which misses
   * `failure` entirely: the server maps that outcome to status `failed`, so a job that
   * died in phase 2 kept a running clock for as long as the page stayed open. Phase 5
   * dispatching is the normal end — the pipeline exits the moment the printer accepts
   * the file, recording `awaiting_verdict` — and the clock must stop there too, because
   * what follows is the printer's time, not the pipeline's.
   */
  const jobActive =
    isRunning &&
    !TERMINAL_OUTCOMES.has(currentJob?.outcome ?? '') &&
    !TERMINAL_STATUSES.has(currentJob?.status ?? '');

  // The elapsed figure only needs to move while the job does.
  useEffect(() => {
    if (!jobActive) return;
    const tick = window.setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(tick);
  }, [jobActive]);

  /**
   * The stage follows the pipeline to the newest artifact until someone picks a tab.
   *
   * The toolpath is the last thing the pipeline makes and the thing worth looking at
   * before it goes to a printer, so the stage advances to it the moment it exists. It
   * used to stop at the mesh: the G-code preview was reachable only by clicking a tab,
   * or in a 240px slot in the rail, which is not where a 200-layer toolpath is read.
   */
  useEffect(() => {
    if (tabPinnedRef.current) return;
    if (currentJob?.slice_status === 'success' || currentJob?.layer_count != null) {
      setActiveTab('slice');
    } else if (phases.find(p => p.phase === 3)?.status === 'complete') {
      setActiveTab('mesh');
    }
  }, [phases, currentJob?.slice_status, currentJob?.layer_count]);

  /**
   * Start a job for `text`, from either entry point.
   *
   * Split out of `handleSubmit` so the landing form and the inline composer share one
   * implementation. They previously would have needed two, and the second would have
   * been the one that forgot to record the material.
   */
  const startJob = async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || loading) return;

    setLoading(true);
    setSubmitError(null);
    try {
      const data = await createJob({
        prompt: trimmed,
        printer_id: 'default_printer',
        profile: configDefaults.profile,
        skip_visualizer: configDefaults.skipVisualizer,
        skip_sculptor: configDefaults.skipSculptor,
        // Phases 1–4 only. Phase 5 is held behind the confirmation panel, so the
        // person who asked for the part sees which machine it is going to *before* a
        // nozzle heats up. `--start-print` still exists for the CLI, where there is
        // nobody to ask.
        print: false,
        start_print: false,
        // Recorded per job rather than assumed from the printer: spools get swapped
        // without anyone telling the app, and material is the likeliest explanation
        // for a bed adhesion failure after the fact.
        material_type: materialType || undefined,
        material_brand: materialBrand || undefined,
        material_colour: materialColour || undefined,
        // Blank means "draw one and record it", which is what we want by default.
        seed: seed.trim() ? Number(seed) : undefined,
      });
      // Everything from the job being replaced has to go, or the new run inherits its
      // log, its telemetry and its socket.
      if (wsRef.current) wsRef.current.close();
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
      }
      setPrompt(trimmed);
      setLogLines([]);
      setTelemetrySamples([]);
      setCurrentJob(null);
      tabPinnedRef.current = false;
      setActiveTab('blueprint');
      setComposerOpen(false);

      setAttachedAt(Date.now());
      setNow(Date.now());
      setJobId(data.job_id);

      // Initial phase running
      setPhases(PIPELINE.map((p, i) => ({
        phase: p.phase,
        name: p.name,
        status: i === 0 ? 'running' : 'pending',
      })));

      connectWebSocket(data.job_id);
    } catch (err: any) {
      setSubmitError(err?.message || 'The job could not be started. Check the engine and try again.');
    } finally {
      setLoading(false);
    }
  };

  const handleSubmit = (e?: FormEvent) => {
    e?.preventDefault();
    void startJob(prompt);
  };

  // ── Idle: the prompt and the pipeline it starts ────────────────────────────

  if (!isRunning) {
    const profileName = printerNameFromProfile(configDefaults.profile);
    const simulated = printer?.type === 'simulator';
    const printerName = simulated
      ? 'OctoPrint simulator'
      : profileName ?? 'No printer selected';
    const printerMeta = simulated
      ? 'octoprint · virtual printer'
      : configDefaults.profile || 'no profile selected';
    const printerStatusClass = printerReady
      ? 'status status-ok'
      : printer?.configured
        ? 'status status-bad'
        : 'status status-off';
    const printerStatusLabel = printerReady ? 'Online' : printer?.configured ? 'Offline' : 'Not configured';

    return (
      <>
        <div className={styles.split}>
          <div className={styles.splitCell}>
            {/* Whoever is reading this already chose to be here — they do not need
                selling, they need to know what to type and that it is safe to try. */}
            {/* The state of the product, not the name of the page: the nav already
                says where you are, and what a first-time user needs from this line is
                that the thing they are about to trust with a printer is pre-beta. */}
            <div className={`eyebrow ${styles.heroEyebrow}`}>
              <span className="label-accent">Pre-beta</span>
            </div>
            <h1 className={`display-lg ${styles.hero}`}>
              What are we<br />making today?
            </h1>
            <p className={`lede ${styles.lede}`}>
              Type the object the way you would describe it to someone: what it is, roughly how
              big, what it needs to do. Everything after that is automatic — blueprint, geometry,
              a printability check, then G-code. You can look it over before anything reaches the
              printer.
            </p>

            <div className={styles.composeGroup}>
              {!printerReady && (
                <div className={`notice ${styles.notice}`}>
                  <AlertTriangle size={15} strokeWidth={1.5} aria-hidden="true" />
                  <span>
                    No printer or simulator is running.{' '}
                    <Link to="/setup" className={styles.noticeLink}>Configure one in Settings</Link>{' '}
                    before you generate.
                  </span>
                </div>
              )}

              {submitError && (
                <div className={`notice ${styles.notice}`} role="alert">
                  <AlertTriangle size={15} strokeWidth={1.5} aria-hidden="true" />
                  <span>{submitError}</span>
                </div>
              )}

              <form onSubmit={handleSubmit}>
                <Blueprint tone="accent" className={`field-frame ${styles.promptFrame}`}>
                  <textarea
                    id="job-prompt"
                    className={styles.promptInput}
                    placeholder="A low poly planter box with a modern geometric design…"
                    aria-label="Describe the object to print"
                    value={prompt}
                    maxLength={MAX_PROMPT_CHARS}
                    onChange={(e) => setPrompt(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && !e.shiftKey) {
                        e.preventDefault();
                        if (prompt.trim() && !loading && printerReady) {
                          void handleSubmit();
                        }
                      }
                    }}
                    rows={3}
                    autoFocus
                    disabled={!printerReady}
                  />

                  <div className={styles.frameFooter}>
                    <div className={styles.materialRow}>
                      <label className="label-tight" htmlFor="material-type">Material</label>
                      <span className={styles.selectWrap}>
                        <select
                          id="material-type"
                          className={styles.materialSelect}
                          value={materialType}
                          onChange={(e) => setMaterialType(e.target.value)}
                          disabled={!printerReady}
                        >
                          {MATERIAL_TYPES.map((m) => (
                            <option key={m} value={m}>{m}</option>
                          ))}
                        </select>
                        <ChevronDown size={10} strokeWidth={1.5} className={styles.selectChevron} aria-hidden="true" />
                      </span>
                    </div>
                    <div className={styles.footerRight}>
                      {/* Appears only near the ceiling. See MAX_PROMPT_CHARS. */}
                      <span
                        className={
                          MAX_PROMPT_CHARS - prompt.length <= COUNTER_REVEAL
                            ? `${styles.counter} ${styles.counterShown}`
                            : styles.counter
                        }
                        aria-live="polite"
                      >
                        {MAX_PROMPT_CHARS - prompt.length} left
                      </span>
                      <button
                        type="button"
                        className={styles.disclosure}
                        onClick={() => setShowAdvanced((v) => !v)}
                        aria-expanded={showAdvanced}
                        aria-controls="job-details"
                      >
                        Brand, colour, seed
                      </button>
                      {/* Replaces the drag handle this field used to have. The corner
                          could be pulled past the viewport and asked the writer to do
                          layout; this raises the same text to reading size instead. */}
                      <button
                        type="button"
                        className={styles.expand}
                        onClick={() => {
                          reportUi('prompt field', 'expanded');
                          setPromptZoomed(true);
                        }}
                        disabled={!printerReady}
                        aria-label="Expand the prompt field"
                        title="Expand"
                      >
                        <Maximize2 size={13} strokeWidth={1.5} aria-hidden="true" />
                      </button>
                    </div>
                  </div>

                  {showAdvanced && (
                    <div className={styles.advanced} id="job-details">
                      <input
                        className="input"
                        placeholder="Filament brand"
                        aria-label="Filament brand"
                        value={materialBrand}
                        onChange={(e) => setMaterialBrand(e.target.value)}
                        disabled={!printerReady}
                      />
                      <input
                        className="input"
                        placeholder="Colour"
                        aria-label="Filament colour"
                        value={materialColour}
                        onChange={(e) => setMaterialColour(e.target.value)}
                        disabled={!printerReady}
                      />
                      {/* Blank draws a fresh seed and records it. Filling it in reproduces a
                          previous blueprint exactly — the point of recording it at all. */}
                      <input
                        className="input"
                        type="number"
                        min={0}
                        placeholder="Seed (blank draws one)"
                        aria-label="Blueprint seed"
                        value={seed}
                        onChange={(e) => setSeed(e.target.value)}
                        disabled={!printerReady}
                      />
                    </div>
                  )}
                </Blueprint>

                <div className={styles.submitRow}>
                  {/* `blueprint` is what scopes the corner marks; `.btn`'s own transparent
                      border is declared later in global.css, so the fill stays clean. */}
                  <button
                    type="submit"
                    className={`btn btn-primary blueprint marked-accent ${styles.submitBtn}`}
                    disabled={!prompt.trim() || loading || !printerReady}
                  >
                    <Marks />
                    {loading ? 'Starting…' : 'Generate & print'}
                    {!loading && <ArrowRight size={16} strokeWidth={1.5} aria-hidden="true" />}
                  </button>
                  <span className={styles.submitHint}>Enter to send · Shift + Enter for a new line</span>
                </div>
              </form>
            </div>
          </div>

          <div className={styles.splitCell}>
            <div className="block-title">
              <span className="label">Pipeline · what runs when you hit send</span>
              <span className="label-tight">05 phases</span>
            </div>

            {PIPELINE.map((p) => (
              <div key={p.phase} className="phase-row">
                <span className="phase-num">{pad2(p.phase)}</span>
                <div>
                  <div className={styles.phaseName}>{p.name}</div>
                  <div className={styles.phaseBlurb}>{p.blurb}</div>
                </div>
                <span className={styles.tag}>{p.tag}</span>
              </div>
            ))}

            <div className={styles.printerBlock}>
              <div className={`label ${styles.printerLabel}`}>Printer</div>
              <Blueprint className={styles.printerFrame}>
                <div>
                  <div className={styles.printerName}>{printerName}</div>
                  <div className={styles.printerMeta}>{printerMeta}</div>
                </div>
                <span className={printerStatusClass}>{printerStatusLabel}</span>
              </Blueprint>
            </div>
          </div>
        </div>

        {promptZoomed && (
          <PromptZoom
            value={prompt}
            busy={loading}
            onChange={setPrompt}
            onSubmit={next => {
              setPromptZoomed(false);
              void startJob(next);
            }}
            onClose={() => {
              reportUi('prompt field', 'collapsed');
              setPromptZoomed(false);
              document.getElementById('job-prompt')?.focus();
            }}
          />
        )}
      </>
    );
  }

  // ── Running: one dominant artifact, one rail ───────────────────────────────

  const errorPhase = phases.find(p => p.status === 'error');
  const runningPhase = phases.find(p => p.status === 'running');
  const lastComplete = phases.slice().reverse().find(p => p.status === 'complete');
  const headPhase = errorPhase ?? runningPhase ?? lastComplete ?? phases[0] ?? PIPELINE[0];
  const headPhaseClass = errorPhase
    ? styles.figureBad
    : runningPhase
      ? styles.figureRun
      : phases.every(p => p.status === 'complete')
        ? styles.figureDone
        : '';

  const startMs = parseTs(currentJob?.started_at) ?? attachedAt;
  const endMs = jobActive ? now : parseTs(currentJob?.completed_at) ?? now;
  const elapsed = formatElapsed(Math.max(0, endMs - startMs));

  const headLabel = errorPhase
    ? 'Failed job'
    : currentJob?.outcome === 'cancelled'
      ? 'Cancelled job'
      : currentJob?.dispatch_state === 'awaiting_confirmation'
        ? 'Ready to print'
        : jobActive
          ? 'Running job'
          : 'Finished job';

  const layerHeight = currentJob?.layer_height_mm;
  const chip = [currentJob?.material_type, layerHeight ? `${layerHeight} mm layers` : null]
    .filter(Boolean)
    .join(' · ');

  const activeTabPhase = STAGE_TABS.find(t => t.id === activeTab)?.phase ?? 1;
  const meshRepaired = phases.find(p => p.phase === 3)?.status === 'complete';
  const sliceReady = currentJob?.slice_status === 'success' || currentJob?.layer_count != null;
  const sliceFailed = currentJob?.slice_status === 'failed';

  const caption: { left: string; right: string } = {
    blueprint: {
      left: 'Blueprint drawn from the prompt',
      right: currentJob?.blueprint_seed != null ? `seed ${currentJob.blueprint_seed}` : 'seed recorded when phase 01 runs',
    },
    mesh: {
      left: 'Repaired geometry, scaled to the print bed',
      right: meshRepaired ? '.OBJ' : 'awaiting phase 03',
    },
    slice: {
      left: sliceFailed
        ? 'The slice failed — open the job in Dashboard for the error'
        : 'Sliced for the loaded filament',
      right: sliceReady && currentJob?.layer_count != null ? `${currentJob.layer_count} layers` : 'G-CODE',
    },
  }[activeTab];

  return (
    <div className={styles.page}>
      <div className={styles.jobHeader}>
        <div className={styles.jobHeadLeft}>
          <div className={styles.jobIdRow}>
            <span className="label">{headLabel}</span>
            <span className="mono">{jobId.slice(0, 8)}</span>
            {!wsConnected && jobActive && <span className="status status-off">Polling</span>}
          </div>
          <h1 className={styles.jobTitle}>{prompt || currentJob?.prompt}</h1>
        </div>
        <div className={styles.jobFigures}>
          <div>
            <div className={styles.figureLabel}>Phase</div>
            <div className={`${styles.figureValue} ${headPhaseClass}`}>
              {pad2(headPhase.phase)} · {headPhase.name}
            </div>
          </div>
          <div>
            <div className={styles.figureLabel}>Elapsed</div>
            <div className={styles.figureValue}>{elapsed}</div>
          </div>
          <button
            type="button"
            className={composerOpen ? 'btn btn-secondary' : 'btn btn-primary blueprint marked-accent'}
            onClick={() => {
              reportUi('new job', composerOpen ? 'closed composer' : 'opened composer');
              setComposerOpen(o => !o);
            }}
            aria-expanded={composerOpen}
          >
            {!composerOpen && <Marks />}
            <RotateCcw size={14} strokeWidth={1.5} aria-hidden="true" /> New job
          </button>
        </div>
      </div>

      {/* Phase 5 waits here. Directly under the header rather than in the rail: it is a
          decision about the whole job, and a 380px column is where controls go to be
          missed. */}
      {currentJob?.dispatch_state === 'awaiting_confirmation' && (
        <DispatchGate
          jobId={jobId}
          job={currentJob}
          onDispatched={() => {
            // The operator is launched, so phase 05 is live and the row is now waiting
            // on a human verdict about the part. Reconnecting the socket is what brings
            // the printer's telemetry back onto the page — the old one closed when the
            // pipeline finished.
            setCurrentJob(prev => (prev ? { ...prev, dispatch_state: 'dispatched', outcome: 'awaiting_verdict' } : prev));
            setPhases(prev => prev.map(p => (p.phase === 5 ? { ...p, status: 'running' } : p)));
            connectWebSocket(jobId);
            getJob(jobId).then(setCurrentJob).catch(() => {});
          }}
        />
      )}

      <PromptComposer
        open={composerOpen}
        busy={loading}
        error={submitError}
        onCancel={() => setComposerOpen(false)}
        onSubmit={next => startJob(next)}
      />

      <div className={styles.liveGrid}>
        <div className={styles.stagePane}>
          <div className={`${styles.tabs} scroll-x`}>
            <div className={styles.tabButtons} role="tablist" aria-label="Job artifacts">
              {STAGE_TABS.map((tab) => (
                <button
                  key={tab.id}
                  type="button"
                  role="tab"
                  id={`stage-tab-${tab.id}`}
                  aria-selected={activeTab === tab.id}
                  aria-controls="stage-panel"
                  className={activeTab === tab.id ? `${styles.tab} ${styles.tabActive}` : styles.tab}
                  onClick={() => {
                    tabPinnedRef.current = true;
                    reportUi('stage tab', `${activeTab} → ${tab.id}`);
                    setActiveTab(tab.id);
                  }}
                >
                  {tab.label}
                </button>
              ))}
            </div>
            {chip && (
              <span className={styles.tabChip}>
                <Layers size={12} strokeWidth={1.5} aria-hidden="true" />
                {chip}
              </span>
            )}
          </div>

          <Blueprint tone="accent" className={styles.stage}>
            <span className={styles.stageLabel}>PHASE {pad2(activeTabPhase)} · OUTPUT</span>
            {/* Keyed on the tab so both remount at a handoff: the sweep crosses the
                top rule, then the new output drifts in from upstream. */}
            <span key={`sweep-${activeTab}`} className={styles.handoff} aria-hidden="true" />
            <div
              key={activeTab}
              className={styles.stageBody}
              id="stage-panel"
              role="tabpanel"
              aria-labelledby={`stage-tab-${activeTab}`}
            >
              {activeTab === 'blueprint' && (
                <BlueprintPreview
                  jobId={jobId}
                  status={phases[0]?.status ?? 'pending'}
                  logLines={currentJob?.log_tail}
                />
              )}
              {activeTab === 'mesh' && (
                <MeshViewer
                  jobId={jobId}
                  status={currentJob?.status || 'queued'}
                  phases={phases}
                  logLines={currentJob?.log_tail}
                />
              )}
              {activeTab === 'slice' && (
                sliceReady ? (
                  // The toolpath itself, at stage size. The slice figures stay, moved
                  // out below the frame — the geometry is what the stage is for, and
                  // three numbers were standing in for it.
                  <GCodeViewer
                    key={jobId}
                    jobId={jobId}
                    zHeightMm={
                      telemetrySamples.length > 0
                        ? telemetrySamples[telemetrySamples.length - 1].z_height_mm
                        : null
                    }
                    buildVolumeMm={currentJob?.build_volume_mm}
                    nozzleDiameterMm={currentJob?.nozzle_diameter_mm}
                  />
                ) : sliceFailed ? (
                  // A failed slice must not animate hopefully.
                  <div className={styles.sliceEmpty}>
                    Slicing failed. The mesh reached the slicer but produced no G-code.
                  </div>
                ) : (
                  <WaitingStage
                    kind="slice"
                    running={phases.find(p => p.phase === 4)?.status === 'running'}
                    logLines={currentJob?.log_tail}
                    note="awaiting phase 04"
                    fill
                  />
                )
              )}
            </div>
          </Blueprint>

          <div className={styles.stageCaption}>
            <span>{caption.left}</span>
            <span className={styles.stageCaptionMono}>{caption.right}</span>
          </div>

          {/* Printability, where the mesh is. The gate runs the moment the Engineer
              finishes, and its verdict is about the geometry on the stage — reading it
              on another page, after the part is already on a printer, is too late to be
              a decision. */}
          {activeTab === 'mesh' && meshRepaired && (
            <div className={styles.meshQuality}>
              <PrintabilityCard
                jobId={jobId}
                supportFilamentMm3={currentJob?.support_filament_mm3}
                reloadKey={currentJob?.printability_score ?? null}
                pending={currentJob?.printability_score == null && Boolean(jobActive)}
              />
            </div>
          )}

          {activeTab === 'slice' && sliceReady && (
            <div className={`plate ${styles.slicePlateGrid}`}>
              <div>
                <div className="plate-figure">{currentJob?.layer_count ?? '—'}</div>
                <div className="plate-label">
                  Layers{currentJob?.layer_height_mm ? ` · ${currentJob.layer_height_mm} mm` : ''}
                </div>
              </div>
              <div>
                <div className="plate-figure">
                  {currentJob?.estimated_print_time_s != null
                    ? formatPrintTime(currentJob.estimated_print_time_s)
                    : '—'}
                </div>
                <div className="plate-label">Print time</div>
              </div>
              <div>
                <div className="plate-figure">
                  {currentJob?.filament_used_g != null
                    ? `${Math.round(currentJob.filament_used_g)} g`
                    : '—'}
                </div>
                <div className="plate-label">
                  {currentJob?.material_type ? currentJob.material_type : 'Filament'}
                  {currentJob?.support_filament_mm3 ? ' · incl. supports' : ''}
                </div>
              </div>
            </div>
          )}

          {/* Under the stage rather than in the rail: it is wide content, and the rail
              is a 380px column that would wrap every docker line into confetti. */}
          <div className={styles.processLog}>
            <ProcessLog lines={logLines} live={Boolean(jobActive)} />
            {/* Two streams, not one merged list: the pipeline's stdout is thousands of
                tool lines, and the server's own activity is a few dozen decisions.
                Interleaving them buries the second in the first. */}
            <ProcessLog
              lines={serverActivity.lines}
              live={serverActivity.connected}
              title="Server activity"
              emptyHint="Nothing from the server yet."
            />
          </div>
        </div>

        <div className={styles.rail}>
          <div>
            <div className={styles.railHead}>
              <span className="label">Phases</span>
            </div>
            {phases.map((p) => (
              <div key={p.phase} className={styles.railRow}>
                <span className={`phase-num ${styles.railNum} ${PHASE_NUM_CLASS[p.status]}`}>
                  {pad2(p.phase)}
                </span>
                <span
                  className={p.status === 'pending' ? `${styles.railName} ${styles.railNamePending}` : styles.railName}
                >
                  {p.name}
                </span>
                {/* The colour lives on this span so the icon keeps `currentColor`:
                    a CSS variable in an SVG attribute would not resolve. */}
                <span
                  key={p.status}
                  className={`${styles.railMark} ${MARK_CLASS[p.status]}`}
                  role="img"
                  aria-label={MARK_LABEL[p.status]}
                >
                  {p.status === 'complete' && <Check size={15} strokeWidth={1.5} />}
                  {p.status === 'running' && (
                    <span className="running-dots">
                      <i /><i /><i />
                    </span>
                  )}
                  {p.status === 'error' && <AlertTriangle size={14} strokeWidth={1.5} />}
                  {p.status === 'pending' && '—'}
                </span>
              </div>
            ))}
          </div>

          {telemetrySamples.length === 0 && (
            <div>
              <div className={styles.railHead}>
                <span className="label">Telemetry</span>
              </div>
              <DeadChannel className={styles.railEmpty}>
                No printer data until phase 05
              </DeadChannel>
            </div>
          )}

          <div className={styles.railBottom}>
            {/* The dispatch and stop actions live here, with the telemetry they read. */}
            <JobControlPanel
              jobId={jobId}
              currentJob={currentJob}
              phases={phases}
              telemetrySamples={telemetrySamples}
            />
            {!meshRepaired && (
              <p className={styles.railCaption}>Available once the mesh is repaired</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
