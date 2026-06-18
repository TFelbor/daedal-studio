import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import type { PrintJob } from '../api/client';
import { getJobTelemetry } from '../api/client';
import { Printer, Clock, ExternalLink } from 'lucide-react';
import { LineChart, Line, ResponsiveContainer, YAxis } from 'recharts';

interface JobCardProps {
  job: PrintJob & { status: string };
}

function getRelativeTime(dateString: string | null) {
  if (!dateString) return '—';
  const d = new Date(dateString);
  const now = new Date();
  const diffInSeconds = Math.floor((now.getTime() - d.getTime()) / 1000);

  if (diffInSeconds < 60) return 'just now';
  if (diffInSeconds < 3600) return `${Math.floor(diffInSeconds / 60)} minutes ago`;
  if (diffInSeconds < 86400) return `${Math.floor(diffInSeconds / 3600)} hours ago`;
  return `${Math.floor(diffInSeconds / 86400)} days ago`;
}

function getDuration(start: string | null, end: string | null) {
  if (!start || !end) return '—';
  const diff = Math.floor((new Date(end).getTime() - new Date(start).getTime()) / 1000);
  if (diff < 60) return `${diff}s`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ${diff % 60}s`;
  return `${Math.floor(diff / 3600)}h ${Math.floor((diff % 3600) / 60)}m`;
}

export function JobCard({ job }: JobCardProps) {
  const [telemetry, setTelemetry] = useState<any[]>([]);

  useEffect(() => {
    if (job.status === 'running' || job.outcome === 'success') {
      getJobTelemetry(job.job_id)
        .then(data => setTelemetry(data))
        .catch(() => {});
    }
  }, [job.job_id, job.status, job.outcome]);

  const displayStatus = job.outcome !== 'unknown' ? job.outcome : job.status;
  
  let badgeStyle = { backgroundColor: '#e5e7eb', color: '#374151' };
  let isRunning = false;
  if (displayStatus === 'success') badgeStyle = { backgroundColor: '#d1fae5', color: '#065f46' };
  else if (displayStatus === 'failure') badgeStyle = { backgroundColor: '#fee2e2', color: '#991b1b' };
  else if (displayStatus === 'running') {
    badgeStyle = { backgroundColor: '#dbeafe', color: '#1e40af' };
    isRunning = true;
  }

  const promptText = job.prompt.length > 80 ? job.prompt.substring(0, 80) + '...' : job.prompt;
  
  const chartData = telemetry.map((s, i) => ({ time: i, temp: s.hotend_actual_c || 0 }));

  return (
    <div style={{
      display: 'flex', alignItems: 'center', backgroundColor: '#fff', 
      borderRadius: '8px', padding: '16px', marginBottom: '12px',
      boxShadow: '0 1px 3px rgba(0,0,0,0.1)', border: '1px solid #f3f4f6',
      gap: '24px'
    }}>
      {/* Left Section */}
      <div style={{ flex: 1, minWidth: '0' }}>
        <h3 style={{ margin: '0 0 8px 0', fontSize: '16px', fontWeight: 600, color: '#111827', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
          {promptText}
        </h3>
        <div style={{ display: 'flex', gap: '16px', color: '#6b7280', fontSize: '14px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
            <Printer size={14} />
            <span>{job.printer_firmware || 'unknown'}</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
            <Clock size={14} />
            <span>{getRelativeTime(job.started_at)}</span>
          </div>
        </div>
      </div>

      {/* Center Section: Telemetry */}
      <div style={{ flex: 1, maxWidth: '200px', height: '60px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        {chartData.length > 0 ? (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData}>
              <YAxis domain={['auto', 'auto']} hide />
              <Line type="monotone" dataKey="temp" stroke="#3b82f6" strokeWidth={2} dot={false} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        ) : (
          <span style={{ fontSize: '12px', color: '#9ca3af' }}>No telemetry</span>
        )}
      </div>

      {/* Right Section */}
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '8px', minWidth: '120px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          {isRunning && (
            <span style={{
              display: 'inline-block', width: '8px', height: '8px', borderRadius: '50%',
              backgroundColor: '#3b82f6', animation: 'pulse 2s infinite'
            }} />
          )}
          <span style={{
            ...badgeStyle, padding: '4px 8px', borderRadius: '9999px',
            fontSize: '12px', fontWeight: 600, textTransform: 'capitalize'
          }}>
            {isRunning ? 'In Progress' : displayStatus}
          </span>
        </div>
        
        <div style={{ fontSize: '12px', color: '#6b7280' }}>
          Duration: {getDuration(job.started_at, job.completed_at)}
        </div>
        
        <Link to={`/dashboard/${job.job_id}`} style={{
          display: 'flex', alignItems: 'center', gap: '4px', fontSize: '14px',
          color: '#3b82f6', textDecoration: 'none', fontWeight: 500, marginTop: '4px'
        }}>
          Details <ExternalLink size={14} />
        </Link>
      </div>

      <style>{`
        @keyframes pulse {
          0% { box-shadow: 0 0 0 0 rgba(59, 130, 246, 0.7); }
          70% { box-shadow: 0 0 0 6px rgba(59, 130, 246, 0); }
          100% { box-shadow: 0 0 0 0 rgba(59, 130, 246, 0); }
        }
      `}</style>
    </div>
  );
}
