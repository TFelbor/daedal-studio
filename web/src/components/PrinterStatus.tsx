import { Server, Zap } from 'lucide-react';
import styles from './PrinterStatus.module.css';

interface PrinterStatusProps {
  printerId: string;
  firmware: string;
  status?: string;
}

export function PrinterStatus({ printerId, firmware, status = 'Online' }: PrinterStatusProps) {
  return (
    <div className={`card ${styles.statusCard}`}>
      <div className={styles.iconWrapper}>
        <Server size={24} className={styles.icon} />
      </div>
      <div className={styles.info}>
        <h3 className={styles.title}>{printerId}</h3>
        <div className={styles.details}>
          <span className={styles.firmware}>{firmware}</span>
          <span className={styles.dot}>•</span>
          <span className={`${styles.status} ${status.toLowerCase() === 'online' ? styles.online : styles.offline}`}>
            <Zap size={12} /> {status}
          </span>
        </div>
      </div>
    </div>
  );
}
