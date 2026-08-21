import { useEffect, useState } from 'react';
import { getJobPrintability } from '../api/client';
import type { PrintabilityCheck, PrintabilityReport } from '../api/client';
import { BootMark } from './BootMark';
import styles from './PrintabilityCard.module.css';

interface PrintabilityCardProps {
  jobId: string;
  /**
   * Whether the slicer generated support material.
   *
   * It comes from the job row rather than the printability report: the report scores
   * geometry before slicing and has no way to know what the slicer decided.
   */
  supportFilamentMm3?: number | null;
}

const VERDICT_CLASS: Record<PrintabilityReport['verdict'], string> = {
  ready: styles.scoreReady,
  risky: styles.scoreRisky,
  unprintable: styles.scoreBad,
};

const CHECK_STATUS_CLASS: Record<PrintabilityCheck['status'], string> = {
  pass: styles.statusPass,
  warn: styles.statusWarn,
  fail: styles.statusFail,
  not_checked: styles.statusSkipped,
};

const CHECK_STATUS_WORD: Record<PrintabilityCheck['status'], string> = {
  pass: 'Pass',
  warn: 'Review',
  fail: 'Fail',
  not_checked: 'Not checked',
};

const CHECK_LABELS: Record<string, string> = {
  watertight: 'Closed volume',
  winding_consistent: 'Consistent face winding',
  non_manifold_edges: 'Manifold edges',
  degenerate_faces: 'Zero-area faces',
  floating_components: 'Parts resting on the plate',
  escape_hole: 'Drainable interior',
  min_wall_thickness: 'Wall thickness',
  overhang_area: 'Overhangs',
  bed_contact: 'First-layer footprint',
  build_volume_fit: 'Fits the build volume',
  self_intersections: 'Self-intersections',
};

const DASH = '—';

/** A feature the report may not carry reads as an em dash, never as a guess. */
function feature(features: Record<string, unknown>, key: string, format: (v: number) => string) {
  const value = features[key];
  return typeof value === 'number' ? format(value) : DASH;
}

export function PrintabilityCard({ jobId, supportFilamentMm3 }: PrintabilityCardProps) {
  const [report, setReport] = useState<PrintabilityReport | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    setLoading(true);

    getJobPrintability(jobId)
      .then(data => {
        if (mounted) setReport(data);
      })
      .catch(() => {
        if (mounted) setReport(null);
      })
      .finally(() => {
        if (mounted) setLoading(false);
      });

    return () => {
      mounted = false;
    };
  }, [jobId]);

  if (loading) {
    return (
      <div>
        <div className={`block-title ${styles.title}`}>
          <span className="label">Printability</span>
        </div>
        <div className={styles.pending}>
          <BootMark size={22} label="Reading the report" />
        </div>
      </div>
    );
  }

  if (!report) {
    return (
      <div>
        <div className={`block-title ${styles.title}`}>
          <span className="label">Printability</span>
        </div>
        <div className="empty">
          <span>No report for this job</span>
          <span>A mesh is scored after the Engineer phase, before slicing</span>
        </div>
      </div>
    );
  }

  const supports =
    supportFilamentMm3 == null ? DASH : supportFilamentMm3 > 0 ? 'Yes' : 'No';

  // Only what a person would act on. Everything that passed is already in the score.
  const attention = report.checks.filter(c => c.status === 'fail' || c.status === 'warn');

  return (
    <div>
      <div className={`block-title ${styles.title}`}>
        <span className="label">Printability</span>
        <span className={`${styles.score} ${VERDICT_CLASS[report.verdict]}`}>
          {report.score.toFixed(0)}
          <span className={styles.scoreMax}>/100</span>
        </span>
      </div>

      <div className={styles.figures}>
        <div className={styles.cell}>
          <div className={styles.figure}>
            {feature(report.features, 'min_wall_thickness_mm', v => `${v.toFixed(1)} mm`)}
          </div>
          <div className={styles.cellLabel}>Min wall</div>
        </div>
        <div className={styles.cell}>
          <div className={styles.figure}>
            {feature(report.features, 'overhang_area_fraction', v => `${(v * 100).toFixed(1)} %`)}
          </div>
          <div className={styles.cellLabel}>Overhang area</div>
        </div>
        <div className={styles.cell}>
          <div className={styles.figure}>{supports}</div>
          <div className={styles.cellLabel}>Supports</div>
        </div>
      </div>

      {attention.length > 0 && (
        <ul className={styles.checks}>
          {attention.map(check => (
            <li key={check.check} className={styles.check}>
              <div className={styles.checkText}>
                <span className={styles.checkName}>
                  {CHECK_LABELS[check.check] ?? check.check}
                </span>
                <span className={styles.checkDetail}>{check.detail}</span>
              </div>
              <span className={`${styles.checkStatus} ${CHECK_STATUS_CLASS[check.status]}`}>
                {CHECK_STATUS_WORD[check.status]}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
