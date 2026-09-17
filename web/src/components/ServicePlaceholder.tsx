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
      'This app does not start prints on Bambu firmware — download the 3MF and print it ' +
      'from Bambu Studio. Nothing streams here yet: the printer pushes its own state ' +
      'over MQTT, but there is no collector reading it into telemetry.',
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
