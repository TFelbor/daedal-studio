import { useEffect, useRef, useState } from 'react';
import { WebGLPreview } from 'gcode-preview';
import { Activity } from 'lucide-react';

interface GCodeViewerProps {
  jobId: string;
  zHeightMm?: number | null;
}

export function GCodeViewer({ jobId, zHeightMm }: GCodeViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const previewRef = useRef<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // Initialize preview only once
  useEffect(() => {
    if (!canvasRef.current || previewRef.current) return;

    previewRef.current = new WebGLPreview({
      canvas: canvasRef.current,
      buildVolume: { x: 220, y: 220, z: 250 },
      initialCameraPosition: [0, 400, 450],
      topLayerColor: '#10b981',
      lastSegmentColor: '#ef4444',
      renderTravel: false,
      backgroundColor: '#f9fafb'
    });

    return () => {
      if (previewRef.current && typeof previewRef.current.dispose === 'function') {
        previewRef.current.dispose();
        previewRef.current = null;
      }
    };
  }, []);

  // Handle ResizeObserver
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

  // Fetch GCode
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
          setError(null);
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

  // Handle Z-Height syncing
  useEffect(() => {
    if (previewRef.current && !loading && !error && zHeightMm != null) {
      const layers = previewRef.current.layers;
      if (layers && layers.length > 0) {
        let targetLayer = 0;
        // Find the highest layer that is <= current zHeightMm (with a small tolerance)
        for (let i = 0; i < layers.length; i++) {
          if (layers[i].height <= zHeightMm + 0.1) {
            targetLayer = i;
          } else {
            break;
          }
        }

        const currentEndLayer = typeof previewRef.current.endLayer === 'number'
          ? previewRef.current.endLayer
          : previewRef.current.maxLayerIndex;

        if (currentEndLayer !== targetLayer) {
          previewRef.current.endLayer = targetLayer;
          if (typeof previewRef.current.render === 'function') {
            previewRef.current.render();
          }
        }
      }
    }
  }, [zHeightMm, loading, error]);

  return (
    <div ref={containerRef} style={{ position: 'relative', width: '100%', height: '100%', minHeight: '300px', backgroundColor: '#f9fafb', borderRadius: '8px', overflow: 'hidden', border: '1px solid #e5e5e5' }}>
      <canvas ref={canvasRef} style={{ width: '100%', height: '100%', display: 'block' }} />
      {loading && (
        <div style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', backgroundColor: 'rgba(249, 250, 251, 0.8)', color: '#6b7280', zIndex: 10 }}>
          <Activity size={24} className="spinner" style={{ animation: 'spin 2s linear infinite' }} />
          <p style={{ marginTop: '8px' }}>Loading G-code preview...</p>
        </div>
      )}
      {error && (
        <div style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', backgroundColor: 'rgba(249, 250, 251, 0.9)', color: '#ef4444', zIndex: 10 }}>
          <p>{error}</p>
        </div>
      )}
    </div>
  );
}
