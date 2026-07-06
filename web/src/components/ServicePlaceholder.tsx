import { Construction } from 'lucide-react';
import styles from './ServicePlaceholder.module.css';

interface ServicePlaceholderProps {
  service: 'klipper' | 'bambu';
}

const SERVICE_INFO: Record<string, { label: string; icon: string; description: string }> = {
  klipper: {
    label: 'Klipper',
    icon: '\u2699\ufe0f',
    description: 'Klipper telemetry integration is under development. Print jobs using Klipper will be dispatched but live monitoring is not yet available.',
  },
  bambu: {
    label: 'Bambu Lab',
    icon: '\ud83c\udf8b',
    description: 'Bambu Lab telemetry integration is under development. Print jobs using Bambu Lab printers will be dispatched but live monitoring is not yet available.',
  },
};

export function ServicePlaceholder({ service }: ServicePlaceholderProps) {
  const info = SERVICE_INFO[service] || SERVICE_INFO.klipper;

  return (
    <div className={`card ${styles.placeholder}`}>
      <div className={styles.header}>
        <span className={styles.serviceIcon}>{info.icon}</span>
        <div>
          <h3 className={styles.title}>{info.label}</h3>
          <span className={styles.badge}>
            <Construction size={12} /> Coming Soon
          </span>
        </div>
      </div>
      <p className={styles.description}>{info.description}</p>
    </div>
  );
}
