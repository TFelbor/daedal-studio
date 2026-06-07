import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { createJob } from '../api/client';
import { Play } from 'lucide-react';
import styles from './NewJob.module.css';

export function NewJob() {
  const [prompt, setPrompt] = useState('');
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!prompt.trim()) return;

    setLoading(true);
    try {
      const response = await createJob({
        prompt,
        printer_id: 'default_printer',
        profile: 'pythonsrc/profiles/moonraker.json', // Default to moonraker for the test
        skip_visualizer: true,
        skip_sculptor: false,
        print: true,
        start_print: true
      });
      navigate(`/jobs/${response.job_id}`);
    } catch (err) {
      console.error(err);
      alert('Failed to start job');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className={styles.container}>
      <div className={styles.hero}>
        <h1 className={styles.title}>Prompt to Print</h1>
        <p className={styles.subtitle}>Enter a description and watch it become a physical object.</p>
      </div>

      <form className={`card ${styles.form}`} onSubmit={handleSubmit}>
        <textarea
          className={`input ${styles.textarea}`}
          placeholder="e.g. A low poly planter box with a modern geometric design..."
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          rows={4}
          autoFocus
        />
        
        <div className={styles.actions}>
          <button 
            type="submit" 
            className={`btn btn-primary ${styles.submitBtn}`}
            disabled={!prompt.trim() || loading}
          >
            {loading ? 'Starting...' : <><Play size={18} /> Generate & Print</>}
          </button>
        </div>
      </form>
    </div>
  );
}
