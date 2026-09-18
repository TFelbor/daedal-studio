/**
 * "Add a photo" — the camera, and the upload it posts to.
 *
 * "Does it fit?" is the question the parametric pivot turns on, and the only answer
 * the system could hold until now was one word. A photograph of the tray with the
 * cards in it is the evidence behind that word, and the only record of what the part
 * actually looked like: `printability_score` is a prediction about a mesh, `outcome`
 * is one word about a print, and neither can be re-derived into "the lid sat 0,4 mm
 * proud".
 *
 * The camera is ten lines of it. `capture="environment"` on a file input opens the
 * rear camera directly on a phone and degrades to a file picker on a desktop — no
 * `getUserMedia`, no preview canvas, no permission dialog to explain, no dependency.
 *
 * The upload is its own request, fired on selection rather than carried with the
 * verdict. Two reasons: the verdict stays one tap, and a failed upload — the phone
 * that walked out of Wi-Fi range next to the printer — never blocks the answer that
 * matters more.
 */

import { useEffect, useRef, useState } from 'react';
import { Camera, Check, Loader2 } from 'lucide-react';
import { FIT_PHOTO_MAX_BYTES, FIT_PHOTO_TYPES, uploadFitPhoto } from '../api/client';
import styles from './FitPhotoInput.module.css';

interface Props {
  jobId: string;
  /** Called once the server has stored a photo, so a page can re-read the job. */
  onUploaded?: () => void;
  /** Extra classes for the button, so a host can dress it as one of its own. */
  buttonClassName?: string;
}

type State = 'idle' | 'uploading' | 'done';

export function FitPhotoInput({ jobId, onUploaded, buttonClassName }: Props) {
  const input = useRef<HTMLInputElement>(null);
  const [state, setState] = useState<State>('idle');
  const [error, setError] = useState<string | null>(null);
  // The picked file, shown back immediately. A local object URL rather than a re-fetch
  // of `/jobs/{id}/photo`: the bytes are already on the device, and the acknowledgement
  // should not wait for a round trip over the connection that just carried them up.
  const [preview, setPreview] = useState<string | null>(null);

  // An object URL that is never revoked keeps the whole image alive for the life of
  // the document, and a phone photo is several megabytes.
  useEffect(() => () => {
    if (preview) URL.revokeObjectURL(preview);
  }, [preview]);

  const pick = async (file: File) => {
    setError(null);
    if (file.size > FIT_PHOTO_MAX_BYTES) {
      setError(`That photo is ${Math.round(file.size / 1024 / 1024)} MB; the limit is 10 MB.`);
      return;
    }
    if (!FIT_PHOTO_TYPES.includes(file.type)) {
      // iOS normally transcodes a file-input upload to JPEG; what lands here is the
      // residue that did not, and saying which types work is more use than "refused".
      setError('Send a JPEG, PNG or WebP. Your phone’s camera app produces one of those.');
      return;
    }

    setState('uploading');
    try {
      await uploadFitPhoto(jobId, file);
      setPreview((previous) => {
        if (previous) URL.revokeObjectURL(previous);
        return URL.createObjectURL(file);
      });
      setState('done');
      onUploaded?.();
    } catch (err) {
      // The server's own sentence, verbatim: it names the cap and the three types.
      setError(err instanceof Error ? err.message : 'Could not upload that photo');
      setState('idle');
    }
  };

  return (
    <div className={styles.wrap}>
      <input
        ref={input}
        type="file"
        className={styles.file}
        accept={FIT_PHOTO_TYPES.join(',')}
        // The whole mobile affordance. Rear camera on a phone, file picker elsewhere.
        capture="environment"
        onChange={(e) => {
          const file = e.target.files?.[0];
          // Cleared so picking the same file twice still fires a change event — a
          // retry after a failed upload is exactly that.
          e.target.value = '';
          if (file) void pick(file);
        }}
      />
      <button
        type="button"
        className={`${styles.button} ${buttonClassName ?? ''}`}
        onClick={() => input.current?.click()}
        disabled={state === 'uploading'}
      >
        {state === 'uploading' ? (
          <Loader2 size={16} className="spin" />
        ) : state === 'done' ? (
          <Check size={16} />
        ) : (
          <Camera size={16} />
        )}
        {state === 'done' ? 'Photo added' : state === 'uploading' ? 'Uploading…' : 'Add a photo'}
      </button>

      {preview && (
        <img className={styles.thumb} src={preview} alt="The printed part, as photographed" />
      )}
      {error && <div className={styles.error}>{error}</div>}
    </div>
  );
}
