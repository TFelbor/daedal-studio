import { useEffect, useRef } from 'react';
import { cssToken, prefersReducedMotion } from '../theme';
import styles from './DeadChannel.module.css';

interface DeadChannelProps {
  /** What is not reporting, and when it will. One line, sentence case. */
  children: React.ReactNode;
  /** Channel height in px. 120 is the rail size the design was drawn at. */
  height?: number;
  className?: string;
}

/**
 * A telemetry channel with nothing on the line.
 *
 * The old empty state was an icon and a sentence, which reads as a broken panel.
 * This is an instrument instead: a dead-flat trace with a sweep running along it.
 * The distinction matters because "no data" and "not listening" are different
 * facts, and only one of them is a problem — the sweep is what says the channel is
 * open and waiting. It carries no interaction on purpose.
 */
export function DeadChannel({ children, height = 120, className = '' }: DeadChannelProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const accent = cssToken('--accent', '#eb8724');
    const reduced = prefersReducedMotion();
    let box = { w: 0, h: 0 };
    let raf = 0;

    const fit = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const rect = canvas.getBoundingClientRect();
      if (!rect.width || !rect.height) return;
      // A sub-pixel jitter is not a resize, and rewriting the backing store re-notifies
      // the observer — which is how a ResizeObserver ends up in a reported loop.
      if (Math.abs(rect.width - box.w) < 0.5 && Math.abs(rect.height - box.h) < 0.5) return;
      canvas.width = Math.round(rect.width * dpr);
      canvas.height = Math.round(rect.height * dpr);
      canvas.getContext('2d')?.setTransform(dpr, 0, 0, dpr, 0, 0);
      box = { w: rect.width, h: rect.height };
    };

    const draw = (now: number) => {
      const ctx = canvas.getContext('2d');
      if (!ctx || !box.w) return;
      const { w, h } = box;
      const mid = h * 0.42;

      ctx.clearRect(0, 0, w, h);
      ctx.save();

      // Time graticule, then the baseline the trace would sit on.
      ctx.lineWidth = 1;
      ctx.strokeStyle = 'rgba(242, 240, 237, 0.07)';
      for (let x = 0; x < w; x += 22) {
        ctx.beginPath();
        ctx.moveTo(x + 0.5, 0);
        ctx.lineTo(x + 0.5, h);
        ctx.stroke();
      }
      ctx.strokeStyle = 'rgba(242, 240, 237, 0.16)';
      ctx.beginPath();
      ctx.moveTo(0, mid + 0.5);
      ctx.lineTo(w, mid + 0.5);
      ctx.stroke();

      // The sweep: a short accent tail with a head, proving the channel is live. With
      // reduced motion it parks mid-span rather than freezing at an arbitrary phase.
      const sx = reduced ? w * 0.5 : ((now / 22) % (w + 90)) - 45;
      const grad = ctx.createLinearGradient(sx - 70, 0, sx, 0);
      grad.addColorStop(0, 'rgba(235, 135, 36, 0)');
      grad.addColorStop(1, 'rgba(235, 135, 36, 0.5)');
      ctx.strokeStyle = grad;
      ctx.lineWidth = 1.4;
      ctx.beginPath();
      ctx.moveTo(Math.max(0, sx - 70), mid + 0.5);
      ctx.lineTo(Math.max(0, Math.min(w, sx)), mid + 0.5);
      ctx.stroke();
      if (sx > 0 && sx < w) {
        ctx.fillStyle = accent;
        ctx.fillRect(sx - 1.5, mid - 1.5, 3, 3);
      }

      ctx.restore();
    };

    const frame = (now: number) => {
      draw(now);
      raf = requestAnimationFrame(frame);
    };

    let refitScheduled = false;
    const observer = new ResizeObserver(() => {
      if (refitScheduled) return;
      refitScheduled = true;
      requestAnimationFrame(() => {
        refitScheduled = false;
        fit();
      });
    });
    fit();
    observer.observe(canvas);
    raf = requestAnimationFrame(frame);

    return () => {
      cancelAnimationFrame(raf);
      observer.disconnect();
    };
  }, []);

  const classes = [styles.channel, className].filter(Boolean).join(' ');

  return (
    <div className={classes} style={{ height }}>
      <canvas ref={canvasRef} className={styles.canvas} aria-hidden="true" />
      <span className={styles.caption}>{children}</span>
    </div>
  );
}
