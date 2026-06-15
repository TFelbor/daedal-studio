import { useEffect, useState } from 'react';
import { listJobs } from '../api/client';
import type { PaginatedJobs } from '../api/client';
import { JobCard } from '../components/JobCard';
import { Loader2, Inbox, ChevronLeft, ChevronRight } from 'lucide-react';
import styles from './JobList.module.css';

export function JobList() {
  const [data, setData] = useState<PaginatedJobs | null>(null);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState('all');
  const [page, setPage] = useState(0);
  const LIMIT = 10;

  const fetchJobs = async (hideLoading = false) => {
    if (!hideLoading) setLoading(true);
    try {
      const res = await listJobs(LIMIT, page * LIMIT, statusFilter);
      setData(res);
    } catch (err) {
      console.error(err);
    } finally {
      if (!hideLoading) setLoading(false);
    }
  };

  useEffect(() => {
    fetchJobs();
  }, [statusFilter, page]);

  useEffect(() => {
    const interval = setInterval(() => {
      fetchJobs(true);
    }, 10000);
    return () => clearInterval(interval);
  }, [statusFilter, page]);

  const handleFilterChange = (filter: string) => {
    setStatusFilter(filter);
    setPage(0); // reset page on filter change
  };

  const stats = data?.stats || { total: 0, running: 0, completed: 0, failed: 0 };
  const jobs = data?.jobs || [];
  const totalPages = data ? Math.ceil(data.total / LIMIT) : 0;

  return (
    <div className={styles.container}>
      {/* Stats Bar */}
      <div style={{
        display: 'flex', gap: '16px', marginBottom: '24px', 
        backgroundColor: 'var(--surface-color)', padding: '16px', borderRadius: 'var(--border-radius)', 
        border: '1px solid var(--border-color)'
      }}>
        <div style={{ flex: 1, textAlign: 'center' }}>
          <div style={{ fontSize: '24px', fontWeight: 700, color: 'var(--text-primary)' }}>{stats.total}</div>
          <div style={{ fontSize: '12px', color: 'var(--text-secondary)', textTransform: 'uppercase', fontWeight: 600 }}>Total Jobs</div>
        </div>
        <div style={{ width: '1px', backgroundColor: 'var(--border-color)' }} />
        <div style={{ flex: 1, textAlign: 'center' }}>
          <div style={{ fontSize: '24px', fontWeight: 700, color: '#10b981' }}>{stats.completed}</div>
          <div style={{ fontSize: '12px', color: 'var(--text-secondary)', textTransform: 'uppercase', fontWeight: 600 }}>Successful</div>
        </div>
        <div style={{ width: '1px', backgroundColor: 'var(--border-color)' }} />
        <div style={{ flex: 1, textAlign: 'center' }}>
          <div style={{ fontSize: '24px', fontWeight: 700, color: 'var(--accent-color)' }}>{stats.failed}</div>
          <div style={{ fontSize: '12px', color: 'var(--text-secondary)', textTransform: 'uppercase', fontWeight: 600 }}>Failed</div>
        </div>
        <div style={{ width: '1px', backgroundColor: 'var(--border-color)' }} />
        <div style={{ flex: 1, textAlign: 'center' }}>
          <div style={{ fontSize: '24px', fontWeight: 700, color: '#3b82f6' }}>{stats.running}</div>
          <div style={{ fontSize: '12px', color: 'var(--text-secondary)', textTransform: 'uppercase', fontWeight: 600 }}>Running</div>
        </div>
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
        <h2 className={styles.title} style={{ margin: 0 }}>Print History</h2>
        
        {/* Filter Tabs */}
        <div style={{ display: 'flex', backgroundColor: 'var(--surface-color)', padding: '4px', borderRadius: 'var(--border-radius)', border: '1px solid var(--border-color)' }}>
          {['all', 'running', 'completed', 'failed'].map(f => (
            <button
              key={f}
              onClick={() => handleFilterChange(f)}
              style={{
                padding: '6px 16px', borderRadius: 'var(--border-radius)', border: 'none',
                backgroundColor: statusFilter === f ? 'var(--border-color)' : 'transparent',
                color: statusFilter === f ? 'var(--surface-color)' : 'var(--text-secondary)',
                fontWeight: statusFilter === f ? 600 : 500,
                cursor: 'pointer', textTransform: 'capitalize', transition: 'all 0.2s'
              }}
            >
              {f}
            </button>
          ))}
        </div>
      </div>

      {loading && jobs.length === 0 ? (
        <div className={styles.loading} style={{ padding: '48px 0' }}>
          <Loader2 className="spinner" size={32} />
          <p>Loading jobs...</p>
        </div>
      ) : jobs.length === 0 ? (
        <div style={{
          display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
          padding: '64px 24px', backgroundColor: 'var(--surface-color)', borderRadius: 'var(--border-radius)', 
          border: '1px solid var(--border-color)', color: 'var(--text-secondary)'
        }}>
          <Inbox size={48} style={{ marginBottom: '16px', opacity: 0.5 }} />
          <p style={{ fontSize: '16px', fontWeight: 500, color: 'var(--text-secondary)' }}>No print jobs found</p>
          <p style={{ fontSize: '14px' }}>Adjust your filters or create a new job to get started.</p>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          {jobs.map(job => (
            <JobCard key={job.job_id} job={job} />
          ))}
          
          {/* Pagination */}
          {totalPages > 1 && (
            <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: '16px', marginTop: '24px' }}>
              <button 
                onClick={() => setPage(p => Math.max(0, p - 1))}
                disabled={page === 0}
                style={{
                  display: 'flex', alignItems: 'center', gap: '4px', padding: '8px 16px',
                  backgroundColor: 'var(--surface-color)', border: '1px solid var(--border-color)', borderRadius: 'var(--border-radius)',
                  color: page === 0 ? 'var(--text-secondary)' : 'var(--text-primary)', cursor: page === 0 ? 'not-allowed' : 'pointer'
                }}
              >
                <ChevronLeft size={16} /> Previous
              </button>
              <span style={{ fontSize: '14px', color: 'var(--text-primary)', fontWeight: 500 }}>
                Page {page + 1} of {totalPages}
              </span>
              <button 
                onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))}
                disabled={page >= totalPages - 1}
                style={{
                  display: 'flex', alignItems: 'center', gap: '4px', padding: '8px 16px',
                  backgroundColor: 'var(--surface-color)', border: '1px solid var(--border-color)', borderRadius: 'var(--border-radius)',
                  color: page >= totalPages - 1 ? 'var(--text-secondary)' : 'var(--text-primary)', cursor: page >= totalPages - 1 ? 'not-allowed' : 'pointer'
                }}
              >
                Next <ChevronRight size={16} />
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
