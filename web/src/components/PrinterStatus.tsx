import { Wifi, WifiOff } from 'lucide-react';
import styles from './PrinterStatus.module.css';

interface PrinterStatusProps {
  printerId: string;
  firmware: string;
  status?: string;
  machineName?: string | null;
}

const SERVICE_CONFIG: Record<string, { label: string; icon: string; accentClass: string }> = {
  octoprint: { label: 'OctoPrint', icon: '\ud83d\udc19', accentClass: 'octoprint' },
  klipper: { label: 'Klipper', icon: '\u2699\ufe0f', accentClass: 'klipper' },
  bambu: { label: 'Bambu Lab', icon: '\ud83c\udf8b', accentClass: 'bambu' },
};

export function PrinterStatus({ printerId, firmware, status = 'Online', machineName }: PrinterStatusProps) {
  const config = SERVICE_CONFIG[firmware] || { label: firmware, icon: '\ud83d\udda8\ufe0f', accentClass: 'default' };
  const isOnline = status.toLowerCase() === 'online';
  const displayName = machineName || printerId;

  return (
    <div className={`card ${styles.statusCard} ${styles[config.accentClass] || ''}`}>
      <div className={styles.serviceRow}>
        <span className={styles.serviceIcon}>{config.icon}</span>
        <div className={styles.serviceInfo}>
          <span className={styles.serviceLabel}>{config.label}</span>
          <span className={styles.printerName}>{displayName}</span>
        </div>
        <div className={`${styles.statusIndicator} ${isOnline ? styles.online : styles.offline}`}>
          {isOnline ? <Wifi size={14} /> : <WifiOff size={14} />}
          <span>{status}</span>
        </div>
      </div>
    </div>
  );
}
