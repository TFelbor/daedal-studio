import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { AlertCircle, ArrowRight } from 'lucide-react';
import { BootMark } from '../components/BootMark';
import { listJobs, getPrinterInfo, type PrintJob, type PrinterInfo } from '../api/client';
import { getSimulatorStatus, type SimulatorStatus } from '../api/config';
import { Blueprint, Marks } from '../components/Blueprint';
import { PrinterStatus } from '../components/PrinterStatus';
import { PrinterStateCard } from '../components/PrinterStateCard';
import { ServicePlaceholder } from '../components/ServicePlaceholder';
import { TelemetryChart } from '../components/TelemetryChart';
import { useJobWebSocket } from '../hooks/useJobWebSocket';
import styles from './PrintMonitor.module.css';

// We need a wrapper component for each job to use hooks independently
function ActiveJobMonitor({ job }: { job: PrintJob & { status: string } }) {
  const { telemetrySamples, printerState, printerMeta } = useJobWebSocket(job.job_id);
  const [printerInfo, setPrinterInfo] = useState<PrinterInfo | null>(null);

  useEffect(() => {
    // Fetch printer info for the banner
    getPrinterInfo(job.job_id).then(setPrinterInfo).catch(() => {});
  }, [job.job_id]);

  const firmware = printerMeta.service || printerInfo?.service || job.printer_firmware || 'octoprint';
  const machineName = printerMeta.machineName || printerInfo?.printer_name || 'Printer';
  const layerHeightMm = printerMeta.layerHeightMm || printerInfo?.layer_height_mm || null;
  const connectionStatus = printerInfo?.connection_status || 'unknown';

  const isOctoprint = firmware === 'octoprint';
  const isKlipperOrBambu = firmware === 'klipper' || firmware === 'bambu';

  return (
    <section className={styles.job}>
      <Blueprint tone="run" className={styles.jobHead}>
        <div className={styles.jobIdentity}>
          <span className="label">Running now</span>
          <h2 className={styles.jobPrompt}>{job.prompt}</h2>
          <span className={`mono ${styles.jobId}`}>{job.job_id}</span>
        </div>
        <span className="status status-run">{job.status}</span>
      </Blueprint>

      <div className={`${styles.jobGrid} ${isOctoprint ? '' : styles.jobGridSolo}`}>
        {isOctoprint && (
          <div className={styles.mainCol}>
            <TelemetryChart jobId={job.job_id} data={telemetrySamples} />
          </div>
        )}
        <div className={styles.sideCol}>
          <PrinterStatus
            printerId={job.printer_id}
            firmware={firmware}
            status={connectionStatus === 'online' ? 'Online' : connectionStatus === 'offline' ? 'Offline' : 'Checking...'}
            machineName={machineName}
          />
          {isOctoprint && (
            <PrinterStateCard
              jobId={job.job_id}
              printerState={printerState}
              startedAt={job.started_at}
              layerHeightMm={layerHeightMm}
            />
          )}
          {isKlipperOrBambu && (
            <ServicePlaceholder service={firmware as 'klipper' | 'bambu'} />
          )}
        </div>
      </div>
    </section>
  );
}

interface PrinterRow {
  name: string;
  detail: string;
  state: string;
  tone: string;
}

type SimulatorEntry = SimulatorStatus['octoprint'];

/** Where a simulator can be reached, or the fact that it is not running. */
function whereItLives(sim: SimulatorEntry): string {
  if (!sim.running) return 'stopped';
  if (sim.url) {
    try {
      return new URL(sim.url).host;
    } catch {
      return sim.url;
    }
  }
  return sim.port != null ? `localhost:${sim.port}` : 'running';
}

function toRow(name: string, firmware: string, sim: SimulatorEntry): PrinterRow {
  return {
    name,
    detail: `${firmware} · ${whereItLives(sim)}`,
    // A running simulator is not printing anything: idle is the honest word for it.
    state: sim.running ? 'Idle' : 'Off',
    tone: sim.running ? 'status-ok' : 'status-off',
  };
}

/**
 * The printers this machine can talk to.
 *
 * Shown beside the empty state because an idle printer is still worth seeing: the
 * question a person arrives with is "is anything printing", and the answer is more
 * useful when it also says what could be.
 */
function PrinterList({ simulators }: { simulators: SimulatorStatus | null }) {
  const rows = simulators
    ? [
        toRow('OctoPrint simulator', 'octoprint', simulators.octoprint),
        toRow('Moonraker simulator', 'klipper', simulators.moonraker),
      ]
    : null;

  return (
    <aside className={styles.printers}>
      <div className={`label ${styles.printersHead}`}>Printers on this machine</div>
      {rows ? (
        rows.map(row => (
          <div key={row.name} className={styles.printerRow}>
            <div className={styles.printerIdentity}>
              <div className={styles.printerName}>{row.name}</div>
              <div className={`mono ${styles.printerMeta}`}>{row.detail}</div>
            </div>
            <span className={`status ${row.tone}`}>{row.state}</span>
          </div>
        ))
      ) : (
        <div className="empty">
          <span>Printer status is unavailable.</span>
          <span>The API server did not answer — check that it is running.</span>
        </div>
      )}
    </aside>
  );
}

export function PrintMonitor() {
  const [activeJobs, setActiveJobs] = useState<(PrintJob & { status: string })[]>([]);
  const [simulators, setSimulators] = useState<SimulatorStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchActiveJobs = async () => {
    try {
      const res = await listJobs(50, 0, 'running');
      setActiveJobs(res.jobs);
      setError(null);
      // The printer list only renders when nothing is printing, so it is only read
      // then — this rides the existing poll rather than adding a second timer.
      if (res.jobs.length === 0) {
        getSimulatorStatus().then(setSimulators).catch(() => setSimulators(null));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not reach the API server.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchActiveJobs();
    const interval = setInterval(fetchActiveJobs, 10000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="sheet">
      <header className={styles.head}>
        <div className="eyebrow">
          <span className="label-accent">Live telemetry from every active print</span>
        </div>
        <h1 className="display">Monitor</h1>
      </header>

      {loading && (
        <BootMark block label="Looking for prints in progress" />
      )}

      {!loading && error && (
        <div className="notice">
          <AlertCircle size={16} strokeWidth={1.5} />
          <span>{error} Active prints cannot be listed until it answers.</span>
        </div>
      )}

      {!loading && !error && activeJobs.length === 0 && (
        <Blueprint tone="accent" className={styles.emptyFrame}>
          <div className={styles.emptyMain}>
            <h2 className={styles.emptyTitle}>Nothing is printing.</h2>
            <p className={`lede ${styles.emptyLede}`}>
              When a job reaches the operator phase, its temperatures, layer progress and
              failure watch appear here.
            </p>
            <Link to="/" className={`btn btn-primary blueprint marked-accent ${styles.cta}`}>
              <Marks />
              Start a job
              <ArrowRight size={15} strokeWidth={1.5} />
            </Link>
          </div>
          <PrinterList simulators={simulators} />
        </Blueprint>
      )}

      {!loading && !error && activeJobs.length > 0 && (
        <div className={styles.jobList}>
          {activeJobs.map(job => (
            <ActiveJobMonitor key={job.job_id} job={job} />
          ))}
        </div>
      )}
    </div>
  );
}
