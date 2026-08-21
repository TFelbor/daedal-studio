import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { WebGLPreview } from 'gcode-preview';
import { Layers3, Maximize2, Move3d, RotateCcw, X } from 'lucide-react';
import { cssToken } from '../theme';
import { reportUi } from '../api/activity';
import styles from './GCodeViewer.module.css';

/**
 * Build volume used when the printer profile does not declare one.
 *
 * Deliberately not a "sensible average": it is the bed of the Ender 3, the profile
 * this repo ships as its default. A guessed envelope is worse than a wrong one that
 * can be traced to a file — a part that fits reads as overflowing a machine it was
 * never sliced for.
 */
const FALLBACK_VOLUME: [number, number, number] = [220, 220, 250];

interface GCodeStats {
  layerCount: number | null;
  printTimeS: number | null;
  filamentG: number | null;
  supportMm3: number | null;
  material: string | null;
  layerHeightMm: number | null;
}

interface GCodeViewerProps {
  jobId: string;
  /** Live nozzle height. Drives the follow mode, until someone scrubs by hand. */
  zHeightMm?: number | null;
  /** [width, depth, height] in mm, from the job's frozen profile snapshot. */
  buildVolumeMm?: number[] | null;
  nozzleDiameterMm?: number | null;
  /**
   * The slice figures. Rendered on the viewer's own footer rather than only in a
   * separate plate: layer count, time and filament are what the preview is *for*,
   * and reading them a screen away from the geometry they describe is worse.
   */
  stats?: GCodeStats;
  /**
   * Drop the scrubber and the figures, leaving the canvas and an expand affordance.
   *
   * For the rail, which is a 380px column sharing its height with a chart and two
   * buttons: a full control strip there does not fit, and a flex child that cannot
   * shrink pushes the Print button off its own panel.
   */
  compact?: boolean;
}

function formatTime(seconds: number): string {
  const total = Math.round(seconds / 60);
  const h = Math.floor(total / 60);
  const m = total % 60;
  return h > 0 ? `${h}h ${String(m).padStart(2, '0')}m` : `${m}m`;
}

export function GCodeViewer({
  jobId,
  zHeightMm,
  buildVolumeMm,
  nozzleDiameterMm,
  stats,
  compact = false,
}: GCodeViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const previewRef = useRef<WebGLPreview | null>(null);

  const [loading, setLoading] = useState(true);
  const [maxLayer, setMaxLayer] = useState(0);
  const [layer, setLayer] = useState(0);
  const [layerZ, setLayerZ] = useState<number | null>(null);
  const [showTravel, setShowTravel] = useState(false);
  const [isolate, setIsolate] = useState(false);
  /**
   * Whether the view still tracks the nozzle. A hand on the scrubber wins: someone
   * inspecting layer 40 of a running print must not be yanked back to the top on the
   * next telemetry sample.
   */
  const [following, setFollowing] = useState(true);
  /**
   * Full-window inspection.
   *
   * Implemented by restyling this element's own box rather than re-rendering the
   * viewer somewhere else: the WebGL context is bound to one canvas, and moving that
   * canvas in the DOM would tear the context down and reload the file. The
   * ResizeObserver below already refits on a box change, so the same instance simply
   * becomes large.
   */
  const [expanded, setExpanded] = useState(false);

  const volume = useMemo(() => {
    const v = buildVolumeMm;
    if (v && v.length === 3 && v.every(n => typeof n === 'number' && n > 0)) {
      return { x: v[0], y: v[1], z: v[2] };
    }
    return { x: FALLBACK_VOLUME[0], y: FALLBACK_VOLUME[1], z: FALLBACK_VOLUME[2] };
  }, [buildVolumeMm]);

  // ── The renderer. Built once; everything else mutates it in place. ───────────
  useEffect(() => {
    if (!canvasRef.current || previewRef.current) return;

    previewRef.current = new WebGLPreview({
      canvas: canvasRef.current,
      buildVolume: volume,
      initialCameraPosition: [-200, 320, 380],
      backgroundColor: cssToken('--void', '#0d0d0d'),
      // A gradient down the stack reads as depth without any lighting: the earliest
      // layers recede, the newest sits forward. Same grammar as the slice waiting
      // stage, where cooled layers fade.
      extrusionColor: [
        cssToken('--accent-press', '#c26f18'),
        cssToken('--accent', '#eb8724'),
        cssToken('--accent-hover', '#f7a24c'),
      ],
      topLayerColor: cssToken('--ink', '#f2f0ed'),
      lastSegmentColor: cssToken('--run', '#5c9ce6'),
      travelColor: 'rgba(92, 156, 230, 0.35)',
      renderTravel: false,
      // Tubes, not lines: a 1px line cannot show that a wall is 0.4mm wide, and wall
      // width is most of what someone checks a preview for. Extrusion width comes
      // from the profile's own nozzle rather than a constant.
      renderTubes: true,
      extrusionWidth: nozzleDiameterMm ?? 0.4,
      lineWidth: 2,
    });

    return () => {
      previewRef.current?.dispose();
      previewRef.current = null;
    };
    // Volume and nozzle are read at construction. A job change remounts this
    // component (the parent keys it by job), so they cannot go stale here.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Escape closes it. A full-window overlay with no keyboard exit is a trap, and the
  // close button is at the far corner of whatever screen this is on.
  useEffect(() => {
    if (!expanded) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setExpanded(false);
        reportUi('gcode expand', 'closed with escape');
      }
    };
    window.addEventListener('keydown', onKey);
    // The page behind must not scroll under a full-window overlay.
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      window.removeEventListener('keydown', onKey);
      document.body.style.overflow = previous;
    };
  }, [expanded]);

  // ── Resize ──────────────────────────────────────────────────────────────────
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    let scheduled = false;
    const observer = new ResizeObserver(() => {
      // Scheduled, not synchronous: the renderer writes canvas dimensions, which
      // re-notifies the observer and trips "ResizeObserver loop completed".
      if (scheduled) return;
      scheduled = true;
      requestAnimationFrame(() => {
        scheduled = false;
        previewRef.current?.resize();
      });
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  // ── Load the G-code, retrying while the slicer is still writing it ───────────
  useEffect(() => {
    let mounted = true;
    let timeoutId = 0;

    const load = () => {
      fetch(`/jobs/${jobId}/download`)
        .then(res => {
          if (!res.ok) throw new Error('not ready');
          return res.text();
        })
        .then(gcode => {
          if (!mounted) return;
          const preview = previewRef.current;
          if (!preview) return;
          preview.clear();
          preview.processGCode(gcode);
          const top = preview.maxLayerIndex;
          setMaxLayer(top);
          setLayer(top);
          setLayerZ(preview.layers[top]?.height ?? null);
          preview.render();
          setLoading(false);
        })
        .catch(() => {
          if (!mounted) return;
          timeoutId = window.setTimeout(load, 3000);
        });
    };

    load();
    return () => {
      mounted = false;
      window.clearTimeout(timeoutId);
    };
  }, [jobId]);

  /** Draw up to `index`, either as a stack or as that layer alone. */
  const draw = useCallback((index: number, isolateOne: boolean) => {
    const preview = previewRef.current;
    if (!preview) return;
    preview.endLayer = index;
    preview.startLayer = isolateOne ? index : 0;
    preview.singleLayerMode = isolateOne;
    preview.render();
    setLayerZ(preview.layers[index]?.height ?? null);
  }, []);

  useEffect(() => {
    if (loading) return;
    draw(layer, isolate);
  }, [layer, isolate, loading, draw]);

  useEffect(() => {
    const preview = previewRef.current;
    if (!preview || loading) return;
    preview.renderTravel = showTravel;
    preview.render();
  }, [showTravel, loading]);

  // ── Follow the nozzle ───────────────────────────────────────────────────────
  useEffect(() => {
    const preview = previewRef.current;
    if (!preview || loading || !following || zHeightMm == null) return;
    const layers = preview.layers;
    if (!layers.length) return;

    // The highest layer at or below the reported Z, within one layer of nozzle noise.
    let target = 0;
    for (let i = 0; i < layers.length; i++) {
      if (layers[i].height <= zHeightMm + 0.1) target = i;
      else break;
    }
    setLayer(target);
  }, [zHeightMm, following, loading]);

  const onScrub = (value: number) => {
    setLayer(value);
    if (following) {
      setFollowing(false);
      reportUi('gcode scrub', `left follow mode at layer ${value}`);
    }
  };

  const showControls = !loading && (expanded || !compact);
  const hasStats =
    (expanded || !compact) &&
    Boolean(stats && (stats.layerCount != null || stats.printTimeS != null || stats.filamentG != null));

  return (
    <div className={expanded ? `${styles.viewer} ${styles.expanded}` : styles.viewer}>
      <div ref={containerRef} className={styles.stage}>
        <canvas ref={canvasRef} className={styles.canvas} />

        {!loading && (
          <div className={styles.overlay}>
            <span className={styles.readout}>
              L{String(layer).padStart(3, '0')}
              <span className={styles.readoutDim}> / {String(maxLayer).padStart(3, '0')}</span>
              {layerZ != null && <span className={styles.readoutDim}>  ·  Z {layerZ.toFixed(2)} mm</span>}
            </span>
            {following && zHeightMm != null && (
              <span className={styles.live}>
                <span className="running-dots" aria-hidden="true"><i /><i /><i /></span>
                following nozzle
              </span>
            )}
          </div>
        )}

        {!loading && (
          <button
            type="button"
            className={styles.expandBtn}
            onClick={() => {
              setExpanded(v => !v);
              reportUi('gcode expand', expanded ? 'collapsed' : 'expanded');
            }}
            title={expanded ? 'Close (Esc)' : 'Inspect full window'}
            aria-label={expanded ? 'Close full window preview' : 'Expand preview to full window'}
          >
            {expanded ? <X size={13} strokeWidth={1.5} /> : <Maximize2 size={13} strokeWidth={1.5} />}
          </button>
        )}

        {loading && (
          <div className={styles.waiting}>
            <span className="label">Waiting for G-code</span>
            <span className={styles.waitingHint}>
              The preview draws itself once the slicer writes the file
            </span>
          </div>
        )}
      </div>

      {showControls && (
        <div className={styles.controls}>
          <input
            type="range"
            className={styles.scrub}
            min={0}
            max={Math.max(0, maxLayer)}
            value={layer}
            onChange={e => onScrub(Number(e.target.value))}
            aria-label="Layer"
          />
          <div className={styles.buttons}>
            <button
              type="button"
              className={isolate ? `${styles.chip} ${styles.chipOn}` : styles.chip}
              onClick={() => {
                setIsolate(v => !v);
                reportUi('gcode isolate', isolate ? 'off' : 'on');
              }}
              aria-pressed={isolate}
              title="Show only the selected layer"
            >
              <Layers3 size={12} strokeWidth={1.5} /> Single
            </button>
            <button
              type="button"
              className={showTravel ? `${styles.chip} ${styles.chipOn}` : styles.chip}
              onClick={() => {
                setShowTravel(v => !v);
                reportUi('gcode travel', showTravel ? 'off' : 'on');
              }}
              aria-pressed={showTravel}
              title="Draw non-extruding moves"
            >
              <Move3d size={12} strokeWidth={1.5} /> Travel
            </button>
            {!following && zHeightMm != null && (
              <button
                type="button"
                className={styles.chip}
                onClick={() => {
                  setFollowing(true);
                  reportUi('gcode follow', 'resumed');
                }}
                title="Track the nozzle again"
              >
                <RotateCcw size={12} strokeWidth={1.5} /> Follow
              </button>
            )}
          </div>
        </div>
      )}

      {hasStats && stats && (
        <div className={styles.stats}>
          <div className={styles.stat}>
            <span className={styles.statValue}>{stats.layerCount ?? '—'}</span>
            <span className={styles.statLabel}>
              Layers{stats.layerHeightMm ? ` · ${stats.layerHeightMm} mm` : ''}
            </span>
          </div>
          <div className={styles.stat}>
            <span className={styles.statValue}>
              {stats.printTimeS != null ? formatTime(stats.printTimeS) : '—'}
            </span>
            <span className={styles.statLabel}>Print time</span>
          </div>
          <div className={styles.stat}>
            <span className={styles.statValue}>
              {stats.filamentG != null ? `${Math.round(stats.filamentG)} g` : '—'}
            </span>
            <span className={styles.statLabel}>
              {stats.material ? stats.material : 'Filament'}
              {stats.supportMm3 ? ' · incl. supports' : ''}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
