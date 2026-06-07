import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowLeft, Settings, Info } from 'lucide-react';
import styles from './PrinterSetup.module.css';

export function PrinterSetup() {
  const [printerType, setPrinterType] = useState('moonraker');

  return (
    <div className={styles.container}>
      <Link to="/" className={styles.backLink}>
        <ArrowLeft size={16} /> Back to Dashboard
      </Link>
      
      <div className={`card ${styles.card}`}>
        <div className={styles.iconWrapper}>
          <Settings size={48} className={styles.icon} />
        </div>
        <h2 className={styles.title}>Printer Configuration</h2>
        
        <form className={styles.form} onSubmit={(e) => e.preventDefault()}>
          <div className="form-group">
            <label>Printer Type</label>
            <select 
              className="input" 
              value={printerType}
              onChange={(e) => setPrinterType(e.target.value)}
            >
              <option value="moonraker">Klipper / Moonraker</option>
              <option value="octoprint">OctoPrint</option>
              <option value="bambu">Bambu Lab</option>
            </select>
          </div>
          
          {printerType === 'bambu' && (
            <div className="alert alert-info" style={{ display: 'flex', gap: '8px', padding: '12px', backgroundColor: '#e0f2fe', borderRadius: '4px', marginTop: '16px' }}>
              <Info size={20} color="#0284c7" />
              <span style={{ color: '#0369a1' }}>
                <strong>Help:</strong> Enable LAN mode on your Bambu printer: Settings → Network → LAN Mode Liveview
              </span>
            </div>
          )}

          <div style={{ marginTop: '24px' }}>
            <button className="btn btn-primary" type="submit">Save Configuration</button>
          </div>
        </form>
      </div>
    </div>
  );
}
