import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { Activity, AlertTriangle, ArrowRight, Check, ChevronDown, Layers, RotateCcw } from 'lucide-react';
import { Blueprint, Marks } from '../components/Blueprint';
import { BlueprintPreview } from '../components/BlueprintPreview';
import { MeshViewer } from '../components/MeshViewer';
import { JobControlPanel } from '../components/JobControlPanel';
import { createJob, getJob, listJobs, MATERIAL_TYPES } from '../api/client';
import type { JobStatusResponse, TelemetrySample } from '../api/client';
import { getConfig } from '../api/config';
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
  const [wsConnected, setWsConnected] = useState(false);
  const [activeTab, setActiveTab] = useState<StageTab>('blueprint');
  /** Ticks the elapsed figure. Presentation only — nothing is fetched on this timer. */
  const [now, setNow] = useState(() => Date.now());

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
    }
  }, [jobId]);

  // Check for running job on mount
  useEffect(() => {
    listJobs(1, 0, 'running').then(data => {
      if (data.jobs && data.jobs.length > 0) {
        const activeJob = data.jobs[0];
        setAttachedAt(Date.now());
        setJobId(activeJob.job_id);
        setPrompt(activeJob.prompt);
        connectWebSocket(activeJob.job_id);
      }
    }).catch(err => {
      console.error('Failed to fetch active jobs on mount', err);
    });
  }, []);

  const connectWebSocket = (id: string) => {
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${wsProtocol}//${window.location.host}/ws/jobs/${id}`;
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      setWsConnected(true);
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
      }
    };

    ws.onmessage = (event) => {
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
        } else if (msg.type === 'job_complete') {
          setCurrentJob(prev => ({ ...(prev ?? {}), status: 'completed', outcome: msg.data.outcome }));
        }
      } catch (e) {
        console.error('WS parse error', e);
      }
    };

    ws.onclose = () => {
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
  const jobActive = isRunning && currentJob?.status !== 'completed' && currentJob?.outcome !== 'cancelled';

  // The elapsed figure only needs to move while the job does.
  useEffect(() => {
    if (!jobActive) return;
    const tick = window.setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(tick);
  }, [jobActive]);

  // The stage follows the pipeline to the newest artifact until someone picks a tab.
  useEffect(() => {
    if (tabPinnedRef.current) return;
    if (phases.find(p => p.phase === 3)?.status === 'complete') setActiveTab('mesh');
  }, [phases]);

  const handleSubmit = async (e?: FormEvent) => {
    e?.preventDefault();
    if (!prompt.trim()) return;

    setLoading(true);
    setSubmitError(null);
    try {
      const data = await createJob({
        prompt,
        printer_id: 'default_printer',
        profile: configDefaults.profile,
        skip_visualizer: configDefaults.skipVisualizer,
        skip_sculptor: configDefaults.skipSculptor,
        print: true,
        start_print: true,
        // Recorded per job rather than assumed from the printer: spools get swapped
        // without anyone telling the app, and material is the likeliest explanation
        // for a bed adhesion failure after the fact.
        material_type: materialType || undefined,
        material_brand: materialBrand || undefined,
        material_colour: materialColour || undefined,
        // Blank means "draw one and record it", which is what we want by default.
        seed: seed.trim() ? Number(seed) : undefined,
      });
      setAttachedAt(Date.now());
      setNow(Date.now());
      setJobId(data.job_id);

      // Initial phase running
      setPhases(prev => {
        const next = prev.map(p => ({ ...p, status: 'pending' as PhaseStatus['status'] }));
        next[0].status = 'running';
        return next;
      });

      connectWebSocket(data.job_id);
    } catch (err: any) {
      setSubmitError(err?.message || 'The job could not be started. Check the engine and try again.');
    } finally {
      setLoading(false);
    }
  };

  const resetJob = () => {
    if (wsRef.current) wsRef.current.close();
    if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
    pollIntervalRef.current = null;
    tabPinnedRef.current = false;
    setActiveTab('blueprint');
    setJobId(null);
    setPrompt('');
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
      <div className={styles.split}>
        <div className={styles.splitCell}>
          <div className={`eyebrow ${styles.heroEyebrow}`}>
            <span className="label-accent">Text prompt to printed model</span>
          </div>
          <h1 className={`display-lg ${styles.hero}`}>
            Describe it.<br />We print it.
          </h1>
          <p className={`lede ${styles.lede}`}>
            Describe the object in plain text. The engine draws a blueprint, reconstructs the
            geometry, repairs and slices it, then sends the job to your printer.
          </p>

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
            <Blueprint tone="accent" className={styles.promptFrame}>
              <textarea
                id="job-prompt"
                className={styles.promptInput}
                placeholder="A low poly planter box with a modern geometric design…"
                aria-label="Describe the object to print"
                value={prompt}
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
                <button
                  type="button"
                  className={styles.disclosure}
                  onClick={() => setShowAdvanced((v) => !v)}
                  aria-expanded={showAdvanced}
                  aria-controls="job-details"
                >
                  Brand, colour, seed
                </button>
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
    <div>
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
          <button type="button" className="btn btn-secondary" onClick={resetJob}>
            <RotateCcw size={14} strokeWidth={1.5} aria-hidden="true" /> New job
          </button>
        </div>
      </div>

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
            <div
              className={styles.stageBody}
              id="stage-panel"
              role="tabpanel"
              aria-labelledby={`stage-tab-${activeTab}`}
            >
              {activeTab === 'blueprint' && (
                <BlueprintPreview jobId={jobId} status={phases[0]?.status ?? 'pending'} />
              )}
              {activeTab === 'mesh' && (
                <MeshViewer jobId={jobId} status={currentJob?.status || 'queued'} phases={phases} />
              )}
              {activeTab === 'slice' && (
                sliceReady ? (
                  <div className={styles.slicePlate}>
                    <div className={`plate ${styles.slicePlateGrid}`}>
                      <div>
                        <div className="plate-figure">{currentJob?.layer_count ?? '—'}</div>
                        <div className="plate-label">Layers</div>
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
                        <div className="plate-label">Filament</div>
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className={styles.sliceEmpty}>
                    {sliceFailed
                      ? 'Slicing failed. The mesh reached the slicer but produced no G-code.'
                      : 'The slice figures appear here once phase 04 finishes.'}
                  </div>
                )
              )}
            </div>
          </Blueprint>

          <div className={styles.stageCaption}>
            <span>{caption.left}</span>
            <span className={styles.stageCaptionMono}>{caption.right}</span>
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
              <div className={`empty ${styles.railEmpty}`}>
                <Activity size={20} strokeWidth={1.5} aria-hidden="true" />
                <span>No printer data until phase 05</span>
              </div>
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
