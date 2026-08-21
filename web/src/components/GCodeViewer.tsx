import { useEffect, useRef, useState } from 'react';
import { WebGLPreview } from 'gcode-preview';

interface GCodeViewerProps {
  jobId: string;
  zHeightMm?: number | null;
}

/**
 * Read a design token so the WebGL scene is drawn in the app's palette.
 *
 * The preview paints into a canvas, which cannot inherit a CSS variable, so the
 * value is resolved once at construction instead of being hard-coded here.
 */
function token(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

export function GCodeViewer({ jobId, zHeightMm }: GCodeViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const previewRef = useRef<any>(null);
  const [loading, setLoading] = useState(true);

  // Initialize preview only once
  useEffect(() => {
    if (!canvasRef.current || previewRef.current) return;

    previewRef.current = new WebGLPreview({
      canvas: canvasRef.current,
      buildVolume: { x: 220, y: 220, z: 250 },
      initialCameraPosition: [0, 400, 450],
      extrusionColor: token('--accent-press'),
      topLayerColor: token('--accent'),
      lastSegmentColor: token('--ink'),
      renderTravel: false,
      backgroundColor: token('--void'),
    });

    return () => {
      if (previewRef.current && typeof previewRef.current.dispose === 'function') {
        previewRef.current.dispose();
        previewRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    if (!containerRef.current) return;

    const resizeObserver = new ResizeObserver(() => {
      if (previewRef.current && typeof previewRef.current.resize === 'function') {
        previewRef.current.resize();
      }
    });

    resizeObserver.observe(containerRef.current);
    return () => resizeObserver.disconnect();
  }, []);

  // The slicer may not have written the file yet, so a miss is retried rather than
  // reported as an error. NOTE: this endpoint books a `download` engagement event
  // server-side; changing that needs a server change and is out of scope here.
  useEffect(() => {
    let mounted = true;
    let timeoutId: number;

    const fetchGCode = () => {
      fetch(`/jobs/${jobId}/download`)
        .then(res => {
          if (!res.ok) throw new Error('G-code not available yet');
          return res.text();
        })
        .then(gcode => {
          if (!mounted) return;
          if (previewRef.current) {
            previewRef.current.clear();
            previewRef.current.processGCode(gcode);
            if (typeof previewRef.current.render === 'function') {
              previewRef.current.render();
            }
          }
          setLoading(false);
        })
        .catch(() => {
          if (!mounted) return;
          timeoutId = window.setTimeout(fetchGCode, 3000);
        });
    };

    fetchGCode();

    return () => {
      mounted = false;
      window.clearTimeout(timeoutId);
    };
  }, [jobId]);

  // Show the print as far as the nozzle has actually got.
  useEffect(() => {
    if (!previewRef.current || loading || zHeightMm == null) return;
    const layers = previewRef.current.layers;
    if (!layers || layers.length === 0) return;

    let targetLayer = 0;
    // The highest layer at or below the current Z, within one nozzle-noise tolerance.
    for (let i = 0; i < layers.length; i++) {
      if (layers[i].height <= zHeightMm + 0.1) {
        targetLayer = i;
      } else {
        break;
      }
    }

    const currentEndLayer =
      typeof previewRef.current.endLayer === 'number'
        ? previewRef.current.endLayer
        : previewRef.current.maxLayerIndex;

    if (currentEndLayer !== targetLayer) {
      previewRef.current.endLayer = targetLayer;
      if (typeof previewRef.current.render === 'function') {
        previewRef.current.render();
      }
    }
  }, [zHeightMm, loading]);

  return (
    <div
      ref={containerRef}
      style={{
        position: 'relative',
        width: '100%',
        height: '100%',
        minHeight: '300px',
        overflow: 'hidden',
        background: 'var(--void)',
      }}
    >
      <canvas ref={canvasRef} style={{ width: '100%', height: '100%', display: 'block' }} />
      {loading && (
        <div
          style={{
            position: 'absolute',
            inset: 0,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '8px',
            padding: '20px',
            textAlign: 'center',
            background: 'var(--void)',
          }}
        >
          <span className="label">Waiting for G-code</span>
          <span style={{ fontSize: '12.5px', color: 'var(--ink-35)' }}>
            The preview draws itself once the slicer writes the file
          </span>
        </div>
      )}
    </div>
  );
}
