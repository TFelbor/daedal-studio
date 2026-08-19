import { useEffect, useState } from 'react';
import { AlertTriangle, CheckCircle2, CircleSlash, Loader2, XCircle } from 'lucide-react';
import { getJobPrintability } from '../api/client';
import type { PrintabilityCheck, PrintabilityReport } from '../api/client';
import styles from './PrintabilityCard.module.css';

interface PrintabilityCardProps {
  jobId: string;
}

const STATUS_COLOR: Record<PrintabilityCheck['status'], string> = {
  pass: '#10b981',
  warn: 'var(--highlight-color)',
  fail: 'var(--accent-color)',
  not_checked: 'var(--secondary-color)',
};

const VERDICT_COLOR: Record<PrintabilityReport['verdict'], string> = {
  ready: '#10b981',
  risky: 'var(--highlight-color)',
  unprintable: 'var(--accent-color)',
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

const FEATURE_LABELS: [string, string, (v: number) => string][] = [
  ['min_wall_thickness_mm', 'Thinnest wall', v => `${v.toFixed(2)} mm`],
  ['overhang_area_fraction', 'Overhanging area', v => `${(v * 100).toFixed(1)}%`],
  ['bed_contact_mm2', 'Bed contact', v => `${v.toFixed(0)} mm²`],
  ['volume_mm3', 'Volume', v => `${(v / 1000).toFixed(1)} cm³`],
  ['face_count', 'Faces', v => v.toLocaleString()],
  ['component_count', 'Components', v => `${v}`],
];

function statusIcon(status: PrintabilityCheck['status']) {
  const color = STATUS_COLOR[status];
  if (status === 'pass') return <CheckCircle2 size={16} color={color} />;
  if (status === 'warn') return <AlertTriangle size={16} color={color} />;
  if (status === 'fail') return <XCircle size={16} color={color} />;
  return <CircleSlash size={16} color={color} />;
}

/** Order that puts what blocks a print first, and what merely passed last. */
const STATUS_ORDER: Record<PrintabilityCheck['status'], number> = {
  fail: 0,
  warn: 1,
  not_checked: 2,
  pass: 3,
};

export function PrintabilityCard({ jobId }: PrintabilityCardProps) {
  const [report, setReport] = useState<PrintabilityReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [showAll, setShowAll] = useState(false);

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
      <div className={`card ${styles.card}`}>
        <p className={styles.empty}>
          <Loader2 size={14} /> Checking printability…
        </p>
      </div>
    );
  }

  if (!report) {
    return (
      <div className={`card ${styles.card}`}>
        <h3 className={styles.title}>Printability</h3>
        <p className={styles.empty}>
          No report yet. A mesh is scored after the Engineer phase, before slicing.
        </p>
      </div>
    );
  }

  const scored = report.checks.filter(c => c.status !== 'not_checked');
  const totalWeight = scored.reduce((sum, c) => sum + c.weight, 0) || 1;
  const ordered = [...report.checks].sort(
    (a, b) => STATUS_ORDER[a.status] - STATUS_ORDER[b.status] || b.weight - a.weight,
  );
  const blocking = ordered.filter(c => c.status === 'fail' || c.status === 'warn');
  const visible = showAll ? ordered : blocking;

  const counts = report.checks.reduce<Record<string, number>>((acc, c) => {
    acc[c.status] = (acc[c.status] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <div className={`card ${styles.card}`}>
      <div className={styles.header}>
        <div>
          <h3 className={styles.title}>Printability</h3>
          <p className={styles.subtitle}>
            {report.checks.length} geometry checks against the {report.process.toUpperCase()} profile
          </p>
        </div>
        <div className={styles.scoreBlock}>
          <span className={styles.score} style={{ color: VERDICT_COLOR[report.verdict] }}>
            {report.score.toFixed(0)}
          </span>
          <span className={styles.scoreMax}>/ 100</span>
          <span className={styles.verdict} style={{ color: VERDICT_COLOR[report.verdict] }}>
            {report.verdict}
          </span>
        </div>
      </div>

      <div
        className={styles.ribbon}
        role="img"
        aria-label={`Score ${report.score.toFixed(0)} of 100: ${counts.pass ?? 0} passed, ${
          counts.warn ?? 0
        } warned, ${counts.fail ?? 0} failed, ${counts.not_checked ?? 0} not checked`}
      >
        {scored.map(c => (
          <div
            key={c.check}
            className={styles.segment}
            style={{
              width: `${(c.weight / totalWeight) * 100}%`,
              backgroundColor: STATUS_COLOR[c.status],
            }}
            title={`${CHECK_LABELS[c.check] ?? c.check} — ${c.status} (weight ${c.weight})`}
          />
        ))}
      </div>

      <div className={styles.ribbonLegend}>
        <span className={styles.legendItem}>
          <span className={styles.legendSwatch} style={{ backgroundColor: STATUS_COLOR.pass }} />
          {counts.pass ?? 0} passed
        </span>
        <span className={styles.legendItem}>
          <span className={styles.legendSwatch} style={{ backgroundColor: STATUS_COLOR.warn }} />
          {counts.warn ?? 0} to review
        </span>
        <span className={styles.legendItem}>
          <span className={styles.legendSwatch} style={{ backgroundColor: STATUS_COLOR.fail }} />
          {counts.fail ?? 0} failed
        </span>
        {counts.not_checked ? (
          <span className={styles.legendItem}>
            <span
              className={styles.legendSwatch}
              style={{ backgroundColor: STATUS_COLOR.not_checked }}
            />
            {counts.not_checked} not checked
          </span>
        ) : null}
        <span className={styles.legendItem}>Segment width = weight in the score</span>
      </div>

      {visible.length === 0 ? (
        <p className={styles.empty}>Every check passed. Nothing to fix before printing.</p>
      ) : (
        <ul className={styles.checks}>
          {visible.map(c => (
            <li
              key={c.check}
              className={`${styles.check} ${
                c.critical && c.status === 'fail' ? styles.checkCritical : ''
              } ${c.status === 'not_checked' ? styles.muted : ''}`}
            >
              <span className={styles.checkIcon}>{statusIcon(c.status)}</span>
              <div>
                <p className={styles.checkName}>{CHECK_LABELS[c.check] ?? c.check}</p>
                <p className={styles.checkDetail}>{c.detail}</p>
              </div>
            </li>
          ))}
        </ul>
      )}

      <button className={styles.toggle} onClick={() => setShowAll(v => !v)}>
        {showAll ? 'Show only what needs attention' : `Show all ${report.checks.length} checks`}
      </button>

      <div className={styles.features}>
        {FEATURE_LABELS.filter(([key]) => typeof report.features[key] === 'number').map(
          ([key, label, format]) => (
            <div key={key} className={styles.feature}>
              <span className={styles.featureLabel}>{label}</span>
              <span className={styles.featureValue}>{format(report.features[key] as number)}</span>
            </div>
          ),
        )}
      </div>
    </div>
  );
}
