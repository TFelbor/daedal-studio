import { Download } from 'lucide-react';
import { reportUi } from '../api/activity';
import styles from './DownloadFormats.module.css';

/**
 * The three files a finished job leaves behind, in the order they are wanted.
 *
 * G-code first because it is the sliced result for *this* profile and the default the
 * endpoint has always served. The two mesh formats are the handoff: the printers this
 * project cannot dispatch to are reached by opening a file in their own slicer, and
 * the roadmap's interim route to a Bambu is exactly that. 3MF rather than STL where
 * there is a choice — an STL carries no unit, so the receiving program guesses
 * millimetres, while 3MF says so. For a part compiled from a spec, where the
 * dimensions *are* the deliverable, that guess is the whole risk.
 */
const FORMATS = [
  { format: 'gcode', label: 'G-code', hint: 'Sliced for this job’s printer profile' },
  { format: 'stl', label: 'STL', hint: 'Geometry only, no unit — most slicers assume mm' },
  { format: '3mf', label: '3MF', hint: 'Geometry in millimetres — Bambu Studio, Orca, PrusaSlicer' },
] as const;

interface DownloadFormatsProps {
  jobId: string;
  /** Where this control is being rendered, for the activity feed. */
  source?: string;
}

/**
 * One control, three files.
 *
 * Three separate buttons would say the choice is between three actions; it is one
 * action with a format, which is also how the server records it — a single `download`
 * event with the format in its detail.
 */
export function DownloadFormats({ jobId, source = 'job detail' }: DownloadFormatsProps) {
  return (
    <div className={styles.group} role="group" aria-label="Download this job's files">
      <Download size={14} strokeWidth={1.5} aria-hidden="true" className={styles.icon} />
      {FORMATS.map(({ format, label, hint }) => (
        <a
          key={format}
          className={styles.link}
          href={`/jobs/${jobId}/download?format=${format}`}
          download
          title={hint}
          onClick={() => reportUi(source, `downloaded ${label}`)}
        >
          {label}
        </a>
      ))}
    </div>
  );
}
