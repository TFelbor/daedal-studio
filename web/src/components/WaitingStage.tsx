import { useEffect, useRef, useState } from 'react';
import { WaitingStageRenderer } from './waitingStageRenderer';
import type { WaitingKind } from './waitingStageRenderer';
import styles from './WaitingStage.module.css';

export type { WaitingKind } from './waitingStageRenderer';

/**
 * What each phase actually does, in the order it does it.
 *
 * Shown one line at a time while the phase is running and the pipeline has not sent
 * any output of its own yet. These are a description of the work, not a claim about
 * where in it we are — which is why they only appear once the phase is genuinely
 * running, and why a real `log_tail` line always wins over them. Inventing progress
 * for a phase that has not started would make the stage a liar, and the whole point
 * of it is that it shows the real work.
 */
const PHASE_STEPS: Record<WaitingKind, string[]> = {
  blueprint: [
    'flux.2-klein · loading',
    'prompt tokenised',
    'sampling · clay render',
    'matte pass',
    'composing blueprint sheet',
  ],
  mesh: [
    'trellis.2 · dinov3 encode',
    'sparse structure · voxels',
    'latent decode',
    'marching cubes · extracting',
    'manifold repair · sealing',
  ],
  slice: [
    'curaengine · loading definition',
    'wall thickness check',
    'overhang scan · flagging',
    'generating support',
    'writing g-code · walls first',
  ],
};

/** The gesture the real viewer answers to, taught while the artifact is still coming. */
const HINT: Record<WaitingKind, string> = {
  blueprint: 'drag to scrub',
  mesh: 'drag to orbit',
  slice: 'drag to travel',
};

const STEP_INTERVAL_MS = 1900;

interface WaitingStageProps {
  kind: WaitingKind;
  /**
   * Whether the phase that produces this artifact is running right now. A stage for
   * a phase that has not started shows `note` and no pulse: nothing is happening,
   * and saying otherwise is the failure mode this component exists to avoid.
   */
  running?: boolean;
  /**
   * Real pipeline output, newest last. Its last line is preferred over the step
   * vocabulary — actual output beats a description of the work every time.
   */
  logLines?: string[];
  /** The line shown when the phase has not started. */
  note?: string;
  /** Suppress the drag hint on a stage that is not the page's focus. */
  showHint?: boolean;
  /** Stage label, e.g. `PHASE 01 · OUTPUT`. Omit where the host already draws one. */
  label?: string;
  /**
   * Lay the stage over its host rather than flowing in it, for a frame that already
   * holds the real artifact and needs the wait drawn underneath it.
   */
  fill?: boolean;
  className?: string;
}

/**
 * The stage while its artifact does not exist yet.
 *
 * What was here before was an icon and a sentence inside a dashed box — the same
 * empty state a form field gets, standing in for the most interesting thing on the
 * page. This draws the phase's own work instead: the drafting head laying the
 * blueprint out, the solid assembling itself, the toolpath stack climbing. Every one
 * of them is draggable, so the wait teaches the gesture the finished artifact will
 * answer to rather than blocking it.
 *
 * It never claims a step the pipeline did not report. See `PHASE_STEPS`.
 */
export function WaitingStage({
  kind,
  running = false,
  logLines,
  note,
  showHint = true,
  label,
  fill = false,
  className = '',
}: WaitingStageProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rendererRef = useRef<WaitingStageRenderer | null>(null);
  const [dragged, setDragged] = useState(false);
  /** Ticks the step vocabulary along. Counts rather than resets, so switching tabs
      does not restart the line mid-sentence. */
  const [tick, setTick] = useState(0);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const renderer = new WaitingStageRenderer(canvas, kind, () => setDragged(true));
    rendererRef.current = renderer;
    renderer.start();
    return () => {
      renderer.destroy();
      rendererRef.current = null;
    };
    // Deliberately not keyed on `kind`: switching tabs swaps the drawing on the live
    // renderer below rather than tearing the canvas down, which would restart the
    // sweep and drop the orbit the user had set.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    rendererRef.current?.setKind(kind);
  }, [kind]);

  const liveLine = logLines && logLines.length > 0 ? logLines[logLines.length - 1] : null;

  useEffect(() => {
    if (!running || liveLine) return;
    const timer = window.setInterval(() => setTick((n) => n + 1), STEP_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [running, liveLine]);

  const steps = PHASE_STEPS[kind];
  const line = running ? liveLine ?? steps[tick % steps.length] : note;
  const classes = [styles.stage, fill ? styles.fill : '', className]
    .filter(Boolean)
    .join(' ');

  return (
    <div className={classes}>
      <canvas ref={canvasRef} className={styles.canvas} />

      {label && <span className={styles.label}>{label}</span>}

      {line && (
        <div className={styles.status}>
          {/* The pulse is the app's running marker, and it is gated on the phase
              genuinely running — a waiting stage for a queued phase must not throb. */}
          {running && (
            <span className="running-dots" aria-hidden="true">
              <i />
              <i />
              <i />
            </span>
          )}
          <span className={running ? styles.line : styles.lineIdle}>{line}</span>
        </div>
      )}

      {showHint && !dragged && <span className={styles.hint}>{HINT[kind]}</span>}
    </div>
  );
}
