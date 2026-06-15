import { useState } from 'react';
import { Loader2 } from 'lucide-react';

interface BlueprintPreviewProps {
  jobId: string | null;
  status: string;
}

export function BlueprintPreview({ jobId, status }: BlueprintPreviewProps) {
  const [loaded, setLoaded] = useState(false);
  const [retryCount, setRetryCount] = useState(0);

  // Consider phase 1 running if status is 'running' but image not loaded
  const isRunning = status === 'running' && !loaded;
  const showImage = !!jobId && (status === 'completed' || status === 'complete' || status === 'running');
  
  const imgSrc = jobId ? `/jobs/${jobId}/blueprint${retryCount > 0 ? `?t=${retryCount}` : ''}` : '';

  if (!jobId || status === 'queued') {
    return (
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        height: '100%', minHeight: '300px', border: '2px dashed #ccc',
        borderRadius: '8px', color: '#666', flexDirection: 'column'
      }}>
        <p>Waiting for prompt...</p>
      </div>
    );
  }

  return (
    <div style={{
      position: 'relative', height: '100%', minHeight: '300px',
      backgroundColor: '#f5f5f5', borderRadius: '8px', overflow: 'hidden',
      display: 'flex', alignItems: 'center', justifyContent: 'center'
    }}>
      {isRunning && (
        <div style={{
          position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column',
          alignItems: 'center', justifyContent: 'center',
          background: 'linear-gradient(90deg, #f0f0f0 25%, #e0e0e0 50%, #f0f0f0 75%)',
          backgroundSize: '200% 100%', animation: 'shimmer 1.5s infinite',
          zIndex: 1
        }}>
          <Loader2 className="animate-spin" size={32} color="#666" style={{ marginBottom: '16px' }} />
          <span style={{ color: '#666', fontWeight: 500 }}>Generating blueprint...</span>
        </div>
      )}
      
      {showImage && (
        <img 
          src={imgSrc}
          alt="Generated Blueprint"
          style={{
            width: '100%', height: '100%', objectFit: 'contain',
            opacity: loaded ? 1 : 0, transition: 'opacity 0.5s ease-in-out',
            position: 'relative', zIndex: 2
          }}
          onLoad={() => setLoaded(true)}
          onError={() => {
             // If image hasn't actually been generated yet (e.g. status running but Phase 1 not complete)
             // we can retry after a short delay
             setLoaded(false);
             setTimeout(() => {
                setRetryCount(c => c + 1);
             }, 2000);
          }}
        />
      )}
      <style>{`
        @keyframes shimmer {
          0% { background-position: 200% 0; }
          100% { background-position: -200% 0; }
        }
        @keyframes spin {
          to { transform: rotate(360deg); }
        }
        .animate-spin {
          animation: spin 1s linear infinite;
        }
      `}</style>
    </div>
  );
}
