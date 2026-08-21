import { useState } from 'react';
import type { FormEvent } from 'react';
import { AlertTriangle, Loader2 } from 'lucide-react';
import { reportFailure } from '../api/client';
import { Blueprint } from './Blueprint';
import styles from './FailureButton.module.css';

interface FailureButtonProps {
  jobId: string;
  onReported?: () => void;
}

/**
 * The failure vocabulary, in the detector's own spelling.
 *
 * These strings go straight into `failure_event.failure_type`, which the telemetry
 * schema validates against a fixed set — and which `AnomalyDetector` writes to from
 * the other side. Inventing display-friendly values here ("Spaghetti", "Layer Shift")
 * put the same failure in the database under two names and made the column unusable
 * for any query spanning both sources. Labels are for humans; values are not.
 */
const FAILURE_TYPES = [
  { value: 'adhesion', label: 'Came off the bed / warped' },
  { value: 'layer_shift', label: 'Layer shift' },
  { value: 'extrusion_issue', label: 'Under-extrusion / gaps' },
  { value: 'clog', label: 'Clog / no filament' },
  { value: 'thermal_runaway', label: 'Temperature problem' },
  { value: 'unknown', label: 'Something else' },
];

export function FailureButton({ jobId, onReported }: FailureButtonProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notes, setNotes] = useState('');
  const [failureType, setFailureType] = useState('adhesion');

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      await reportFailure(jobId, { failure_type: failureType, notes });
      setIsOpen(false);
      if (onReported) onReported();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not record that');
    } finally {
      setLoading(false);
    }
  };

  if (!isOpen) {
    return (
      <button type="button" className="btn btn-danger" onClick={() => setIsOpen(true)}>
        <AlertTriangle size={14} strokeWidth={1.5} />
        Report a failure
      </button>
    );
  }

  return (
    <Blueprint className={styles.form}>
      <form onSubmit={handleSubmit}>
        <div className={styles.field}>
          <label className="field-label" htmlFor={`failure-type-${jobId}`}>
            What went wrong
          </label>
          <select
            id={`failure-type-${jobId}`}
            className="select"
            value={failureType}
            onChange={e => setFailureType(e.target.value)}
          >
            {FAILURE_TYPES.map(type => (
              <option key={type.value} value={type.value}>
                {type.label}
              </option>
            ))}
          </select>
        </div>

        <div className={styles.field}>
          <label className="field-label" htmlFor={`failure-notes-${jobId}`}>
            Notes (optional)
          </label>
          <textarea
            id={`failure-notes-${jobId}`}
            className="textarea"
            rows={3}
            value={notes}
            onChange={e => setNotes(e.target.value)}
            placeholder="Anything else worth knowing"
          />
        </div>

        {error && <div className={`notice ${styles.error}`}>{error}</div>}

        <div className={styles.actions}>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => setIsOpen(false)}
            disabled={loading}
          >
            Cancel
          </button>
          <button type="submit" className="btn btn-danger" disabled={loading}>
            {loading ? (
              <Loader2 className="spin" size={14} strokeWidth={1.5} />
            ) : (
              <AlertTriangle size={14} strokeWidth={1.5} />
            )}
            Record failure
          </button>
        </div>
      </form>
    </Blueprint>
  );
}
