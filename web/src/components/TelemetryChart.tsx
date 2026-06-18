import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';
import type { TelemetrySample } from '../api/client';
import styles from './TelemetryChart.module.css';
import { Activity } from 'lucide-react';

export interface TelemetryChartProps {
  jobId?: string;
  data?: TelemetrySample[];
}

export function TelemetryChart({ data = [] }: TelemetryChartProps) {
  // Format timestamps for display
  const formattedData = data.map(s => ({
    ...s,
    timeLabel: new Date(s.sampled_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  }));

  if (formattedData.length === 0) {
    return (
      <div className={`card ${styles.chartCard} ${styles.empty}`}>
        <Activity size={24} className={styles.iconEmpty} />
        <p>Waiting for telemetry data...</p>
      </div>
    );
  }

  return (
    <div className={`card ${styles.chartCard}`}>
      <h3 className={styles.title}>Live Telemetry</h3>
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
    </div>
  );
}
