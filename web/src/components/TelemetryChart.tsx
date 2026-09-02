import { useEffect, useState } from 'react';
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { TelemetrySample } from '../api/client';
import { Blueprint } from './Blueprint';
import { DeadChannel } from './DeadChannel';
import styles from './TelemetryChart.module.css';

export interface TelemetryChartProps {
  jobId?: string;
  data?: TelemetrySample[];
}

/** Tooltip styling goes through inline style props because Recharts writes its own. */
const TOOLTIP_SURFACE = {
  background: 'var(--void)',
  border: '1px solid var(--rule-strong)',
  padding: '9px 12px',
  fontFamily: 'var(--font-mono)',
  fontSize: '11px',
};

const TOOLTIP_LABEL = {
  color: 'var(--ink-faint)',
  marginBottom: '4px',
  letterSpacing: '0.06em',
};

const TOOLTIP_ITEM = { color: 'var(--ink-strong)' };

const format = (value: number | null | undefined, decimals: number) => {
  if (value == null || Number.isNaN(value)) return '—';
  return value.toFixed(decimals);
};

export function TelemetryChart({ jobId, data = [] }: TelemetryChartProps) {
  const [fallbackData, setFallbackData] = useState<TelemetrySample[]>([]);
  const hasLiveData = data.length > 0;
  const sourceData = hasLiveData ? data : fallbackData;

  useEffect(() => {
    setFallbackData([]);
  }, [jobId]);

  useEffect(() => {
    if (!jobId || hasLiveData) return;

    let cancelled = false;
    const fetchTelemetry = async () => {
      try {
        const res = await fetch(`/jobs/${jobId}/telemetry`);
        if (!res.ok) throw new Error('Failed to fetch telemetry');
        const json = await res.json();
        if (!cancelled) {
          setFallbackData(json as TelemetrySample[]);
        }
      } catch {
        // Nothing recorded yet is the normal case; the empty state says so.
      }
    };

    fetchTelemetry();
    return () => {
      cancelled = true;
    };
  }, [jobId, hasLiveData]);

  const formattedData = sourceData.map(s => ({
    ...s,
    timeLabel: new Date(s.sampled_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  }));

  if (formattedData.length === 0) {
    return (
      <Blueprint className={styles.panel}>
        <div className={styles.head}>
          <div className="block-title">
            <h3 className="subheading">Live telemetry</h3>
            <span className="status status-off">No samples</span>
          </div>
          {/* Not "nothing here": the channel is open and listening, which is a
              different fact from a broken panel and the one worth showing. */}
          <DeadChannel height={132}>
            Hotend, bed, Z height, fan and speed appear here as the printer samples them
          </DeadChannel>
        </div>
      </Blueprint>
    );
  }

  const latest = formattedData[formattedData.length - 1];

  return (
    <Blueprint className={styles.panel} tone="run">
      <div className={styles.head}>
        <div className="block-title">
          <h3 className="subheading">Live telemetry</h3>
          <div className={styles.legend}>
            <span className={styles.legendItem}>
              <i className={`${styles.swatch} ${styles.swatchHotend}`} aria-hidden="true" />Hotend
            </span>
            <span className={styles.legendItem}>
              <i className={`${styles.swatch} ${styles.swatchBed}`} aria-hidden="true" />Bed
            </span>
            <span className={styles.legendItem}>
              <i className={`${styles.swatch} ${styles.swatchZ}`} aria-hidden="true" />Z
            </span>
          </div>
        </div>
      </div>

      <div className={`plate ${styles.figures}`}>
        <div className={styles.cell}>
          <div className={styles.figure}>
            {format(latest.hotend_actual_c, 1)}
            <i className={styles.unit}>/ {format(latest.hotend_target_c, 0)} &deg;C</i>
          </div>
          <div className="plate-label">Hotend</div>
        </div>
        <div className={styles.cell}>
          <div className={styles.figure}>
            {format(latest.bed_actual_c, 1)}
            <i className={styles.unit}>/ {format(latest.bed_target_c, 0)} &deg;C</i>
          </div>
          <div className="plate-label">Bed</div>
        </div>
        <div className={styles.cell}>
          <div className={styles.figure}>
            {format(latest.z_height_mm, 2)}
            <i className={styles.unit}>mm</i>
          </div>
          <div className="plate-label">Z height</div>
        </div>
        <div className={styles.cell}>
          <div className={styles.figure}>
            {format(latest.fan_speed_pct, 0)}
            <i className={styles.unit}>%</i>
          </div>
          <div className="plate-label">Fan</div>
        </div>
        <div className={styles.cell}>
          <div className={styles.figure}>
            {format(latest.print_speed_pct, 0)}
            <i className={styles.unit}>%</i>
          </div>
          <div className="plate-label">Speed</div>
        </div>
      </div>

      {/* Axes, grid and series all take their colour from the module stylesheet, so
          there is no hex anywhere in the chart. */}
      <div className={styles.chart}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={formattedData} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
            <CartesianGrid vertical={false} />
            <XAxis dataKey="timeLabel" tickMargin={10} minTickGap={44} interval="preserveStartEnd" />
            <YAxis yAxisId="temp" orientation="left" width={38} />
            <YAxis yAxisId="height" orientation="right" width={34} />
            <Tooltip
              contentStyle={TOOLTIP_SURFACE}
              labelStyle={TOOLTIP_LABEL}
              itemStyle={TOOLTIP_ITEM}
              cursor={{ className: styles.cursor }}
            />
            <Line
              yAxisId="temp"
              type="monotone"
              dataKey="hotend_actual_c"
              name="Hotend °C"
              className={styles.seriesHotend}
              strokeWidth={1.6}
              dot={false}
              activeDot={false}
            />
            <Line
              yAxisId="temp"
              type="monotone"
              dataKey="bed_actual_c"
              name="Bed °C"
              className={styles.seriesBed}
              strokeWidth={1.2}
              dot={false}
              activeDot={false}
            />
            <Line
              yAxisId="height"
              type="stepAfter"
              dataKey="z_height_mm"
              name="Z height mm"
              className={styles.seriesZ}
              strokeWidth={1.2}
              dot={false}
              activeDot={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </Blueprint>
  );
}
