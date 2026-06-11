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
        backgroundColor: '#fff', padding: '16px', borderRadius: '8px', 
        boxShadow: '0 1px 3px rgba(0,0,0,0.1)', border: '1px solid #f3f4f6'
      }}>
        <div style={{ flex: 1, textAlign: 'center' }}>
          <div style={{ fontSize: '24px', fontWeight: 700, color: '#111827' }}>{stats.total}</div>
          <div style={{ fontSize: '12px', color: '#6b7280', textTransform: 'uppercase', fontWeight: 600 }}>Total Jobs</div>
        </div>
        <div style={{ width: '1px', backgroundColor: '#e5e7eb' }} />
        <div style={{ flex: 1, textAlign: 'center' }}>
          <div style={{ fontSize: '24px', fontWeight: 700, color: '#10b981' }}>{stats.completed}</div>
          <div style={{ fontSize: '12px', color: '#6b7280', textTransform: 'uppercase', fontWeight: 600 }}>Successful</div>
        </div>
        <div style={{ width: '1px', backgroundColor: '#e5e7eb' }} />
        <div style={{ flex: 1, textAlign: 'center' }}>
          <div style={{ fontSize: '24px', fontWeight: 700, color: '#ef4444' }}>{stats.failed}</div>
          <div style={{ fontSize: '12px', color: '#6b7280', textTransform: 'uppercase', fontWeight: 600 }}>Failed</div>
        </div>
        <div style={{ width: '1px', backgroundColor: '#e5e7eb' }} />
        <div style={{ flex: 1, textAlign: 'center' }}>
          <div style={{ fontSize: '24px', fontWeight: 700, color: '#3b82f6' }}>{stats.running}</div>
          <div style={{ fontSize: '12px', color: '#6b7280', textTransform: 'uppercase', fontWeight: 600 }}>Running</div>
        </div>
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
        <h2 className={styles.title} style={{ margin: 0 }}>Print History</h2>
        
        {/* Filter Tabs */}
        <div style={{ display: 'flex', backgroundColor: '#f3f4f6', padding: '4px', borderRadius: '8px' }}>
          {['all', 'running', 'completed', 'failed'].map(f => (
            <button
              key={f}
              onClick={() => handleFilterChange(f)}
              style={{
                padding: '6px 16px', borderRadius: '6px', border: 'none',
                backgroundColor: statusFilter === f ? '#fff' : 'transparent',
                color: statusFilter === f ? '#111827' : '#6b7280',
                fontWeight: statusFilter === f ? 600 : 500,
                boxShadow: statusFilter === f ? '0 1px 2px rgba(0,0,0,0.1)' : 'none',
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
          padding: '64px 24px', backgroundColor: '#fff', borderRadius: '8px', 
          border: '1px solid #f3f4f6', color: '#9ca3af'
        }}>
          <Inbox size={48} style={{ marginBottom: '16px', opacity: 0.5 }} />
          <p style={{ fontSize: '16px', fontWeight: 500, color: '#6b7280' }}>No print jobs found</p>
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
                  backgroundColor: '#fff', border: '1px solid #d1d5db', borderRadius: '6px',
                  color: page === 0 ? '#9ca3af' : '#374151', cursor: page === 0 ? 'not-allowed' : 'pointer'
                }}
              >
                <ChevronLeft size={16} /> Previous
              </button>
              <span style={{ fontSize: '14px', color: '#4b5563', fontWeight: 500 }}>
                Page {page + 1} of {totalPages}
              </span>
              <button 
                onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))}
                disabled={page >= totalPages - 1}
                style={{
                  display: 'flex', alignItems: 'center', gap: '4px', padding: '8px 16px',
                  backgroundColor: '#fff', border: '1px solid #d1d5db', borderRadius: '6px',
                  color: page >= totalPages - 1 ? '#9ca3af' : '#374151', cursor: page >= totalPages - 1 ? 'not-allowed' : 'pointer'
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
