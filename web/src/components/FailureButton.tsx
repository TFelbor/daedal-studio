import React, { useState } from 'react';
import { reportFailure } from '../api/client';
import { AlertTriangle, Loader2 } from 'lucide-react';
import styles from './FailureButton.module.css';

interface FailureButtonProps {
  jobId: string;
  onReported?: () => void;
}

export function FailureButton({ jobId, onReported }: FailureButtonProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [notes, setNotes] = useState('');
  const [failureType, setFailureType] = useState('Spaghetti');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      await reportFailure(jobId, { failure_type: failureType, notes });
      setIsOpen(false);
      if (onReported) onReported();
    } catch (err) {
      console.error(err);
      alert('Failed to report failure');
    } finally {
      setLoading(false);
    }
  };

  if (!isOpen) {
    return (
      <button className="btn btn-danger" onClick={() => setIsOpen(true)}>
        <AlertTriangle size={16} />
        Report Failure
      </button>
    );
  }

  return (
    <div className={styles.container}>
      <form onSubmit={handleSubmit} className={`card ${styles.form}`}>
        <h4 className={styles.title}>Report Print Failure</h4>
        
        <div className={styles.field}>
          <label>Failure Type</label>
          <select 
            className="input" 
            value={failureType} 
            onChange={(e) => setFailureType(e.target.value)}
          >
            <option value="Spaghetti">Spaghetti (Adhesion loss)</option>
            <option value="Stringing">Stringing</option>
            <option value="Under-extrusion">Under-extrusion</option>
            <option value="Layer Shift">Layer Shift</option>
            <option value="Other">Other</option>
          </select>
        </div>

        <div className={styles.field}>
          <label>Notes (Optional)</label>
          <textarea 
            className="input" 
            rows={3}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="Describe what went wrong..."
          />
        </div>

        <div className={styles.actions}>
          <button 
            type="button" 
            className="btn" 
            onClick={() => setIsOpen(false)}
            disabled={loading}
            style={{ backgroundColor: '#e0e0e0', color: '#333' }}
          >
            Cancel
          </button>
          <button type="submit" className="btn btn-danger" disabled={loading}>
            {loading ? <Loader2 className="spinner" size={16} /> : <AlertTriangle size={16} />}
            Confirm Report
          </button>
        </div>
      </form>
    </div>
  );
}
