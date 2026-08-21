import { Blueprint } from './Blueprint';
import styles from './ServicePlaceholder.module.css';

interface ServicePlaceholderProps {
  service: 'klipper' | 'bambu';
}

const SERVICE_INFO: Record<string, { label: string; description: string }> = {
  klipper: {
    label: 'Klipper',
    description:
      'Jobs dispatch to Klipper and print. It does not report temperatures or layer progress yet, so nothing streams here.',
  },
  bambu: {
    label: 'Bambu Lab',
    description:
      'Jobs dispatch to Bambu Lab and print. It does not report temperatures or layer progress yet, so nothing streams here.',
  },
};

/** Stands in for the telemetry panel on a stack that does not report samples. */
export function ServicePlaceholder({ service }: ServicePlaceholderProps) {
  const info = SERVICE_INFO[service] || SERVICE_INFO.klipper;

  return (
    <Blueprint className={styles.block}>
      <div className="block-title">
        <h3 className="subheading">{info.label}</h3>
        <span className="status status-off">Not monitored</span>
      </div>
      <p className={styles.description}>{info.description}</p>
    </Blueprint>
  );
}
