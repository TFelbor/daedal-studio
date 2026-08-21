import { useState } from 'react';
import type { CSSProperties } from 'react';
import { Image as ImageIcon } from 'lucide-react';

interface BlueprintPreviewProps {
  jobId: string | null;
  status: string;
}

/* The artifact layer only. The frame, its registration marks and the ruled ground
   belong to the stage that hosts this — so the same slot can hold a blueprint, a
   mesh or a slice without three sets of chrome. Nothing here is a literal colour:
   every value is a token from global.css. */
const VIEWPORT: CSSProperties = {
  position: 'relative',
  height: '100%',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  overflow: 'hidden',
};

const IMAGE: CSSProperties = {
  position: 'relative',
  zIndex: 2,
  maxWidth: '100%',
  maxHeight: '100%',
  width: 'auto',
  height: 'auto',
  objectFit: 'contain',
  transition: 'opacity 0.3s ease',
};

const LOADING: CSSProperties = {
  position: 'absolute',
  left: 20,
  bottom: 18,
  zIndex: 3,
  fontFamily: 'var(--font-mono)',
  fontSize: '10.5px',
  letterSpacing: '0.1em',
  textTransform: 'uppercase',
  color: 'var(--accent)',
};

const PLACEHOLDER: CSSProperties = { height: '100%' };

export function BlueprintPreview({ jobId, status }: BlueprintPreviewProps) {
  const [loaded, setLoaded] = useState(false);
  const [retryCount, setRetryCount] = useState(0);

  // Phase 1 counts as running until the image itself has arrived.
  const isRunning = status === 'running' && !loaded;
  const showImage = !!jobId && (status === 'completed' || status === 'complete' || status === 'running');

  const imgSrc = jobId ? `/jobs/${jobId}/blueprint${retryCount > 0 ? `?t=${retryCount}` : ''}` : '';

  if (!jobId || status === 'queued' || status === 'pending') {
    return (
      <div className="empty" style={PLACEHOLDER}>
        <ImageIcon size={28} strokeWidth={1.5} aria-hidden="true" />
        <span>The blueprint appears here once phase 01 runs.</span>
      </div>
    );
  }

  if (status === 'error') {
    return (
      <div className="empty" style={PLACEHOLDER}>
        <ImageIcon size={28} strokeWidth={1.5} aria-hidden="true" />
        <span>The blueprint could not be drawn. Start a new job to try again.</span>
      </div>
    );
  }

  return (
    <div style={VIEWPORT}>
      {isRunning && <span style={LOADING}>Drawing blueprint…</span>}

      {showImage && (
        <img
          src={imgSrc}
          alt="Blueprint drawn from the prompt"
          style={{ ...IMAGE, opacity: loaded ? 1 : 0 }}
          onLoad={() => setLoaded(true)}
          onError={() => {
            // Phase 1 can be running before the file exists; ask again shortly.
            setLoaded(false);
            setTimeout(() => {
              setRetryCount(c => c + 1);
            }, 2000);
          }}
        />
      )}
    </div>
  );
}
