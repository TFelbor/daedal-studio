import { useEffect, useState } from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';
import type { TelemetrySample } from '../api/client';
import styles from './TelemetryChart.module.css';
import { Activity } from 'lucide-react';

export interface TelemetryChartProps {
  jobId?: string;
  data?: TelemetrySample[];
}

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
        // Keep using the placeholder UI until live data arrives.
      }
    };

    fetchTelemetry();
    return () => {
      cancelled = true;
    };
  }, [jobId, hasLiveData]);

  // Format timestamps for display
  const formattedData = sourceData.map(s => ({
    ...s,
    timeLabel: new Date(s.sampled_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  }));

  if (formattedData.length === 0) {
    return (
      <div className={`card ${styles.chartCard} ${styles.empty}`}>
        <Activity size={24} className={styles.iconEmpty} />
        <p>Leave this in maintenance until telemetry data from a real 3D printer is available.</p>
        <details style={{ marginTop: '1rem', padding: '0.5rem', background: '#f5f5f5', borderRadius: '4px', alignSelf: 'stretch', textAlign: 'left', color: 'var(--text-primary)' }}>
          <summary style={{ cursor: 'pointer', fontWeight: 'bold' }}>Debug: Raw Data Prop</summary>
          <pre style={{ fontSize: '0.75rem', maxHeight: '200px', overflow: 'auto', marginTop: '0.5rem' }}>
            Raw data: {JSON.stringify(data, null, 2)}
          </pre>
          <pre style={{ fontSize: '0.75rem', maxHeight: '200px', overflow: 'auto', marginTop: '0.5rem' }}>
            Formatted data: {JSON.stringify(formattedData, null, 2)}
          </pre>
        </details>
      </div>
    );
  }

  const latestSample = formattedData[formattedData.length - 1];

  const formatNum = (val: any, decimals: number) => {
    if (val == null) return '--';
    const num = Number(val);
    if (isNaN(num)) return '--';
    return num.toFixed(decimals);
  };

  const formatVal = (val: any) => {
    if (val == null) return '--';
    const num = Number(val);
    if (isNaN(num)) return '--';
    return num.toString();
  };

  return (
    <div className={`card ${styles.chartCard}`}>
      <div className={styles.header}>
        <h3 className={styles.title}>Live Telemetry</h3>
        <div className={styles.statsContainer}>
          <div className={styles.statItem}>
            <span className={styles.statLabel}>Hotend</span>
            <span className={styles.statValue}>
              {formatNum(latestSample.hotend_actual_c, 1)}
              <span>/ {formatVal(latestSample.hotend_target_c) !== '--' ? formatVal(latestSample.hotend_target_c) : '0'} °C</span>
            </span>
          </div>
          <div className={styles.statItem}>
            <span className={styles.statLabel}>Bed</span>
            <span className={styles.statValue}>
              {formatNum(latestSample.bed_actual_c, 1)}
              <span>/ {formatVal(latestSample.bed_target_c) !== '--' ? formatVal(latestSample.bed_target_c) : '0'} °C</span>
            </span>
          </div>
          <div className={styles.statItem}>
            <span className={styles.statLabel}>Z Height</span>
            <span className={styles.statValue}>
              {formatNum(latestSample.z_height_mm, 2)}
              <span>mm</span>
            </span>
          </div>
          <div className={styles.statItem}>
            <span className={styles.statLabel}>Fan</span>
            <span className={styles.statValue}>
              {formatVal(latestSample.fan_speed_pct)}
              <span>%</span>
            </span>
          </div>
          <div className={styles.statItem}>
            <span className={styles.statLabel}>Speed</span>
            <span className={styles.statValue}>
              {formatVal(latestSample.print_speed_pct)}
              <span>%</span>
            </span>
          </div>
        </div>
      </div>
      <div className={styles.chartContainer}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={formattedData} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border-color)" />
            <XAxis dataKey="timeLabel" tick={{ fontSize: 12, fill: 'var(--text-secondary)' }} tickMargin={10} />
            <YAxis yAxisId="temp" orientation="left" stroke="#ff7300" tick={{ fontSize: 12 }} />
            <YAxis yAxisId="height" orientation="right" stroke="#387908" tick={{ fontSize: 12 }} />
            <Tooltip 
              contentStyle={{ borderRadius: '8px', border: '1px solid var(--border-color)', boxShadow: 'var(--shadow-sm)' }}
              labelStyle={{ color: 'var(--text-primary)', fontWeight: 600, marginBottom: '0.5rem' }}
            />
            <Legend wrapperStyle={{ paddingTop: '20px' }} />
            <Line yAxisId="temp" type="monotone" dataKey="hotend_actual_c" name="Extruder Temp (°C)" stroke="#ff7300" strokeWidth={2} dot={false} activeDot={{ r: 6 }} />
            <Line yAxisId="temp" type="monotone" dataKey="bed_actual_c" name="Bed Temp (°C)" stroke="#8884d8" strokeWidth={2} dot={false} />
            <Line yAxisId="height" type="stepAfter" dataKey="z_height_mm" name="Z Height (mm)" stroke="#387908" strokeWidth={2} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <details style={{ marginTop: '1rem', padding: '0.5rem', background: '#f5f5f5', borderRadius: '4px' }}>
        <summary style={{ cursor: 'pointer', fontWeight: 'bold' }}>Debug: Raw Telemetry Data</summary>
        <pre style={{ fontSize: '0.75rem', maxHeight: '200px', overflow: 'auto', marginTop: '0.5rem' }}>
          {JSON.stringify(formattedData, null, 2)}
        </pre>
      </details>
    </div>
  );
}
