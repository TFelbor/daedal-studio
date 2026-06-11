import { useEffect, useState } from 'react';
import { getJobTelemetry } from '../api/client';
import type { TelemetrySample } from '../api/client';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';
import styles from './TelemetryChart.module.css';
import { Activity } from 'lucide-react';

interface TelemetryChartProps {
  jobId: string;
}

export function TelemetryChart({ jobId }: TelemetryChartProps) {
  const [data, setData] = useState<TelemetrySample[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;

    const poll = async () => {
      try {
        const samples = await getJobTelemetry(jobId);
        if (mounted) {
          // Recharts prefers oldest data first for left-to-right graphs.
          // Depending on API, samples might be newest first. Let's sort by sampled_at ascending.
          const sorted = [...samples].sort((a, b) => new Date(a.sampled_at).getTime() - new Date(b.sampled_at).getTime());
          
          // Format timestamps for display
          const formatted = sorted.map(s => ({
            ...s,
            timeLabel: new Date(s.sampled_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
          }));
          
          setData(formatted);
          setError(null);
        }
      } catch (err) {
        console.error("Failed to fetch telemetry", err);
        if (mounted) setError("Failed to load telemetry data");
      }
    };

    poll();
    const intervalId = setInterval(poll, 5000);

    return () => {
      mounted = false;
      clearInterval(intervalId);
    };
  }, [jobId]);

  if (error) {
    return (
      <div className={`card ${styles.chartCard} ${styles.error}`}>
        <Activity size={24} />
        <p>{error}</p>
      </div>
    );
  }

  if (data.length === 0) {
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
          <LineChart data={data} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
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
