import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';
import styles from './ProcessLog.module.css';

/**
 * How many lines are kept. A docker build plus five phases runs to thousands, and
 * every one of them in the DOM is a scroll janking under its own weight. The tail is
 * what anyone reads; the whole thing is on disk at `data/logs/{job_id}.log`.
 */
const MAX_LINES = 600;

interface ProcessLogProps {
  /** Newest last. Owned by the page, which fills it from the WebSocket. */
  lines: string[];
  /** Whether the source is still producing output. Drives the header pulse. */
  live: boolean;
  /** Panel heading. Defaults to the pipeline's stdout. */
  title?: string;
  /** Copy shown when nothing has arrived yet. */
  emptyHint?: string;
}

/**
 * The pipeline's own stdout, live.
 *
 * The phase row says which of five stages is running; it cannot say that TRELLIS.2 is
 * on its second of three latent decodes, or that the mesh went to the slicer four
 * minutes ago and CuraEngine has not spoken since. That distinction — working slowly
 * versus wedged — is only visible in the process output, and until now it was reachable
 * only by tailing a file on the host.
 *
 * Deliberately noisy. Every line the pipeline emits arrives here, batched at ~8 Hz by
 * the server so a burst does not flood the socket.
 */
export function ProcessLog({
  lines,
  live,
  title = 'Process output',
  emptyHint = 'Waiting for the pipeline to say something.',
}: ProcessLogProps) {
  const [open, setOpen] = useState(true);
  const scrollRef = useRef<HTMLPreElement>(null);
  /**
   * Whether to keep following the tail. Someone who has scrolled up is reading
   * something, and yanking them back to the bottom on the next line makes the log
   * unusable exactly when it matters.
   */
  const followRef = useRef(true);

  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    followRef.current = distanceFromBottom < 24;
  };

  // Layout effect, not effect: scrolling after paint shows one frame of the old
  // position and reads as a stutter on every batch.
  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el || !open || !followRef.current) return;
    el.scrollTop = el.scrollHeight;
  }, [lines, open]);

  // Reopening should land at the tail, not wherever it was when it closed.
  useEffect(() => {
    if (open) followRef.current = true;
  }, [open]);

  const shown = lines.length > MAX_LINES ? lines.slice(lines.length - MAX_LINES) : lines;

  return (
    <div className={styles.block}>
      <div className={styles.head}>
        <button
          type="button"
          className={styles.toggle}
          onClick={() => setOpen(o => !o)}
          aria-expanded={open}
        >
          {open ? <ChevronDown size={13} strokeWidth={1.5} /> : <ChevronUp size={13} strokeWidth={1.5} />}
          <span className="label">{title}</span>
        </button>
        <div className={styles.meta}>
          {live && (
            <span className="running-dots" aria-hidden="true">
              <i />
              <i />
              <i />
            </span>
          )}
          <span className={`mono ${styles.count}`}>
            {lines.length === 0
              ? 'nothing yet'
              : `${lines.length} line${lines.length === 1 ? '' : 's'}${
                  lines.length > MAX_LINES ? ` · tail ${MAX_LINES}` : ''
                }`}
          </span>
        </div>
      </div>

      {open && (
        <pre
          ref={scrollRef}
          className={styles.stream}
          onScroll={onScroll}
          aria-live="off"
          aria-label="Pipeline process output"
        >
          {shown.length > 0
            ? shown.join('\n')
            : emptyHint}
        </pre>
      )}
    </div>
  );
}
