/**
 * TimecardReview.tsx - Timecard review interface component
 * Place in: frontend/src/pages/TimecardReview.tsx
 */

import React, { useState, useEffect } from 'react';
import './TimecardReview.css';

// Types
interface TimecardEntry {
  id: number;
  date: string;
  user: string;
  client_name: string;
  project_name: string | null;
  total_hours: number;
  category_breakdown: Record<string, number>;
  activities_summary: string[];
  confidence_score: number;
  needs_review: boolean;
  status: 'draft' | 'pending' | 'approved' | 'rejected';
  reviewed_at: string | null;
  notes: string;
  block_ids: string[];
}

interface SummaryData {
  total_hours: number;
  by_client: Array<{ client__name: string; total: number }>;
  by_status: {
    approved: number;
    pending: number;
    draft: number;
    rejected: number;
  };
  entries_count: number;
  needs_review_count: number;
}

// API functions
const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:7123/api';

const fetchTimecards = async (date?: string): Promise<TimecardEntry[]> => {
  const params = new URLSearchParams();
  if (date) params.append('date', date);
  
  const url = `${API_BASE}/timecards/?${params}`;
  console.log('Fetching timecards from:', url);
  
  const response = await fetch(url);
  if (!response.ok) {
    const text = await response.text();
    console.error('Failed response from:', url);
    console.error('Response:', text);
    throw new Error(`Failed to fetch timecards: ${response.status} ${response.statusText}`);
  }
  
  const contentType = response.headers.get('content-type');
  if (!contentType || !contentType.includes('application/json')) {
    throw new Error('Server returned non-JSON response. Check if API endpoints are configured.');
  }
  
  return response.json();
};

const fetchSummary = async (startDate?: string, endDate?: string): Promise<SummaryData> => {
  const params = new URLSearchParams();
  if (startDate) params.append('start_date', startDate);
  if (endDate) params.append('end_date', endDate);
  
  const url = `${API_BASE}/timecards/summary/?${params}`;
  console.log('Fetching summary from:', url);
  
  const response = await fetch(url);
  if (!response.ok) {
    const text = await response.text();
    console.error('Failed response from:', url);
    console.error('Response:', text);
    throw new Error(`Failed to fetch summary: ${response.status} ${response.statusText}`);
  }
  
  const contentType = response.headers.get('content-type');
  if (!contentType || !contentType.includes('application/json')) {
    throw new Error('Server returned non-JSON response. Check if API endpoints are configured.');
  }
  
  return response.json();
};

const approveTimecard = async (id: number, notes?: string): Promise<void> => {
  const response = await fetch(`${API_BASE}/timecards/${id}/approve/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ notes: notes || '' }),
  });
  if (!response.ok) throw new Error('Failed to approve timecard');
};

const rejectTimecard = async (id: number, reason: string): Promise<void> => {
  const response = await fetch(`${API_BASE}/timecards/${id}/reject/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reason }),
  });
  if (!response.ok) throw new Error('Failed to reject timecard');
};

// Main Component
const TimecardReview: React.FC = () => {
  console.log('TimecardReview component loaded');
  console.log('API_BASE:', API_BASE);
  console.log('VITE_API_BASE_URL:', import.meta.env.VITE_API_BASE_URL);
  
  const [entries, setEntries] = useState<TimecardEntry[]>([]);
  const [summary, setSummary] = useState<SummaryData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedDate, setSelectedDate] = useState<string>(
    new Date().toISOString().split('T')[0]
  );
  const [expandedCategories, setExpandedCategories] = useState<Set<number>>(new Set());

  // Load data
  const loadData = async () => {
    setLoading(true);
    setError(null);
    try {
      const [entriesData, summaryData] = await Promise.all([
        fetchTimecards(selectedDate),
        fetchSummary(),
      ]);
      setEntries(entriesData);
      setSummary(summaryData);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, [selectedDate]);

  // Handlers
  const handleApprove = async (id: number) => {
    try {
      await approveTimecard(id);
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to approve');
    }
  };

  const handleReject = async (id: number) => {
    const reason = prompt('Please enter a reason for rejection:');
    if (!reason) return;

    try {
      await rejectTimecard(id, reason);
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to reject');
    }
  };

  const toggleCategoryExpansion = (id: number) => {
    setExpandedCategories((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  // Render loading state
  if (loading) {
    return (
      <div className="timecard-container">
        <div className="loading-spinner">
          <div className="spinner" />
          <p>Loading timecards...</p>
        </div>
      </div>
    );
  }

  // Render error state
  if (error) {
    return (
      <div className="timecard-container">
        <div className="error-banner">{error}</div>
      </div>
    );
  }

  return (
    <div className="timecard-container">
      {/* Header */}
      <div className="timecard-header">
        <h1>Timecard Review</h1>
        <div className="header-controls">
          <input
            type="date"
            className="date-input"
            value={selectedDate}
            onChange={(e) => setSelectedDate(e.target.value)}
          />
          <button className="btn btn-primary" onClick={loadData}>
            Refresh
          </button>
        </div>
      </div>

      {error && <div className="error-banner">{error}</div>}

      {/* Summary Cards */}
      {summary && (
        <div className="summary-cards">
          <div className="summary-card">
            <div className="summary-label">Total Hours</div>
            <div className="summary-value">{summary.total_hours.toFixed(1)}</div>
          </div>
          <div className="summary-card">
            <div className="summary-label">Total Entries</div>
            <div className="summary-value">{summary.entries_count}</div>
          </div>
          <div className="summary-card">
            <div className="summary-label">Needs Review</div>
            <div className={`summary-value ${summary.needs_review_count > 0 ? 'warning' : ''}`}>
              {summary.needs_review_count}
            </div>
          </div>
          <div className="summary-card">
            <div className="summary-label">Approved</div>
            <div className="summary-value">{summary.by_status.approved.toFixed(1)}h</div>
          </div>
        </div>
      )}

      {/* Entries List */}
      {entries.length === 0 ? (
        <div className="empty-state">
          <p>📋</p>
          <p>No timecard entries found for this date.</p>
          <p>Try selecting a different date.</p>
        </div>
      ) : (
        <div className="entries-list">
          {entries.map((entry) => (
            <EntryCard
              key={entry.id}
              entry={entry}
              onApprove={handleApprove}
              onReject={handleReject}
              isExpanded={expandedCategories.has(entry.id)}
              onToggleExpand={() => toggleCategoryExpansion(entry.id)}
            />
          ))}
        </div>
      )}
    </div>
  );
};

// Entry Card Component
interface EntryCardProps {
  entry: TimecardEntry;
  onApprove: (id: number) => void;
  onReject: (id: number) => void;
  isExpanded: boolean;
  onToggleExpand: () => void;
}

const EntryCard: React.FC<EntryCardProps> = ({
  entry,
  onApprove,
  onReject,
  isExpanded,
  onToggleExpand,
}) => {
  const maxCategoryHours = Math.max(...Object.values(entry.category_breakdown));

  return (
    <div className={`entry-card ${entry.needs_review ? 'needs-review' : ''}`}>
      {/* Entry Header */}
      <div className="entry-header">
        <div className="entry-title">
          <h2>{entry.client_name}</h2>
          <div className="entry-meta">
            {entry.needs_review && <span className="badge warning">Needs Review</span>}
            {entry.project_name && <span className="badge project">{entry.project_name}</span>}
          </div>
        </div>
      </div>

      {/* Entry Info */}
      <div className="entry-info">
        <div className="info-item">
          <strong>{entry.total_hours.toFixed(2)}h</strong> Total
        </div>
        <div className="info-item">
          <strong>{entry.date}</strong> Date
        </div>
        <div className="info-item">
          <strong>{entry.user}</strong> User
        </div>
        <div className="info-item">
          <strong>{(entry.confidence_score * 100).toFixed(0)}%</strong> Confidence
        </div>
      </div>

      {/* Activities Summary */}
      {entry.activities_summary && entry.activities_summary.length > 0 && (
        <div className="activities-summary">
          <h3>Activities</h3>
          <ul>
            {entry.activities_summary.map((activity, idx) => (
              <li key={idx}>{activity}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Category Breakdown */}
      <div className="category-section">
        <button className="expand-btn" onClick={onToggleExpand}>
          {isExpanded ? '▼' : '▶'} Category Breakdown ({Object.keys(entry.category_breakdown).length} categories)
        </button>
        
        {isExpanded && (
          <div className="category-breakdown">
            {Object.entries(entry.category_breakdown).map(([category, hours]) => (
              <div key={category} className="category-item">
                <div className="category-name">{category}</div>
                <div className="category-hours">{hours.toFixed(2)}h</div>
                <div className="category-bar">
                  <div
                    className="category-bar-fill"
                    style={{ width: `${(hours / maxCategoryHours) * 100}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Notes */}
      {entry.notes && (
        <div className="entry-notes">
          <strong>Notes:</strong> {entry.notes}
        </div>
      )}

      {/* Entry Actions */}
      {entry.status === 'draft' && (
        <div className="entry-actions">
          <button
            className="btn btn-success"
            onClick={() => onApprove(entry.id)}
          >
            ✓ Approve
          </button>
          <button
            className="btn btn-danger"
            onClick={() => onReject(entry.id)}
          >
            ✗ Reject
          </button>
        </div>
      )}

      {/* Review Info */}
      {entry.status !== 'draft' && (
        <div className="review-info">
          Status: <strong>{entry.status}</strong>
          {entry.reviewed_at && ` on ${new Date(entry.reviewed_at).toLocaleString()}`}
        </div>
      )}
    </div>
  );
};

export default TimecardReview;