import { Blueprint } from './Blueprint';
import styles from './PrinterStatus.module.css';

interface PrinterStatusProps {
  printerId: string;
  firmware: string;
  status?: string;
  machineName?: string | null;
}

/**
 * Pill tone for a reachability word.
 *
 * A colour here always means state — never that something can be clicked — so this
 * only ever returns one of the status classes.
 */
function toneFor(status: string): string {
  const word = status.toLowerCase();
  if (word === 'online') return 'status-ok';
  if (word === 'offline') return 'status-bad';
  return 'status-off';
}

/** The machine a job is pointed at: what it is called, which stack, whether it answers. */
export function PrinterStatus({ printerId, firmware, status = 'Online', machineName }: PrinterStatusProps) {
  const displayName = machineName || printerId;
  // The mono line carries the identity the pill cannot: which firmware, which target.
  const detail = displayName === printerId
    ? firmware.toLowerCase()
    : `${firmware.toLowerCase()} · ${printerId}`;

  return (
    <Blueprint className={styles.block}>
      <div className="label">Printer</div>
      <div className={styles.row}>
        <div className={styles.identity}>
          <div className={`subheading ${styles.name}`} title={displayName}>{displayName}</div>
          <div className={`mono ${styles.meta}`}>{detail}</div>
        </div>
        <span className={`status ${toneFor(status)}`}>{status}</span>
      </div>
    </Blueprint>
  );
}
