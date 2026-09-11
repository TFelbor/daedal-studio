import { useState } from 'react';
import type { CSSProperties } from 'react';
import { StageState } from './StageState';

interface BlueprintPreviewProps {
  jobId: string | null;
  status: string;
  /** Live pipeline output, newest last. Passed through to the stage state. */
  logLines?: string[];
  /**
   * `used_reference_assets` — a bundled fixture stood in for Phase 1.
   *
   * It reaches the alt text and nothing else. The visible caption beside this frame
   * already says "a fixture, not a render of this prompt"; without the flag here the
   * alt text said the opposite of it, so the caption a screen reader got was the one
   * the fixture badge exists to prevent (docs/SYSTEM-AS-BUILT.md § The fixture flag
   * is carried out to the UI). Defaults to false because that is what an unknown
   * flag means for every job the pipeline actually renders.
   */
  usedFixtures?: boolean;
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

export function BlueprintPreview({
  jobId,
  status,
  logLines,
  usedFixtures,
}: BlueprintPreviewProps) {
  const [loaded, setLoaded] = useState(false);
  const [retryCount, setRetryCount] = useState(0);

  // Phase 1 counts as running until the image itself has arrived.
  const isRunning = status === 'running' && !loaded;
  const showImage = !!jobId && (status === 'completed' || status === 'complete' || status === 'running');

  const imgSrc = jobId ? `/jobs/${jobId}/blueprint${retryCount > 0 ? `?t=${retryCount}` : ''}` : '';

  // Nothing has arrived yet, and phase 1 has not started — so the frame says that.
  if (!jobId || status === 'queued' || status === 'pending') {
    return <StageState phase={1} status="pending" fill />;
  }

  // A failed phase is the one case that must not read as work in progress.
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
      {/* The phase state stays underneath while phase 1 runs, so the frame is never
          blank and the pipeline's own output is what fills it. Unmounted the moment
          the real image loads. */}
      {isRunning && <StageState phase={1} status="running" logLines={logLines} fill />}

      {showImage && (
        <img
          src={imgSrc}
          alt={
            usedFixtures
              ? 'Reference blueprint — a fixture, not a render of this prompt'
              : 'Blueprint drawn from the prompt'
          }
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
