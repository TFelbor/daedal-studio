import { useState } from 'react';
import type { CSSProperties } from 'react';
import { WaitingStage } from './WaitingStage';

interface BlueprintPreviewProps {
  jobId: string | null;
  status: string;
  /** Live pipeline output, newest last. Passed through to the waiting stage. */
  logLines?: string[];
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

const PLACEHOLDER: CSSProperties = { height: '100%' };

export function BlueprintPreview({ jobId, status, logLines }: BlueprintPreviewProps) {
  const [loaded, setLoaded] = useState(false);
  const [retryCount, setRetryCount] = useState(0);

  // Phase 1 counts as running until the image itself has arrived.
  const isRunning = status === 'running' && !loaded;
  const showImage = !!jobId && (status === 'completed' || status === 'complete' || status === 'running');

  const imgSrc = jobId ? `/jobs/${jobId}/blueprint${retryCount > 0 ? `?t=${retryCount}` : ''}` : '';

  // Nothing has been drawn yet — so draw the drawing. The head lays the same
  // isometric outline the blueprint will arrive as, and answers to the same drag.
  if (!jobId || status === 'queued' || status === 'pending') {
    return <WaitingStage kind="blueprint" note="awaiting phase 01" fill />;
  }

  // A failed phase is the one case that must not animate hopefully.
  if (status === 'error') {
    return (
      <div className="empty" style={PLACEHOLDER}>
        <span>The blueprint could not be drawn.</span>
        <span>Start a new job to try again.</span>
      </div>
    );
  }

  return (
    <div style={VIEWPORT}>
      {/* The waiting stage stays underneath while phase 1 runs, so the frame is never
          blank and the sweep is what the wait looks like. It is unmounted the moment
          the real image loads. */}
      {isRunning && (
        <WaitingStage kind="blueprint" running logLines={logLines} fill />
      )}

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
