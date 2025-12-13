// src/components/ApprovalQueue.tsx
// Manager dashboard for reviewing and approving timesheets

import React, { useState, useEffect, useCallback } from 'react';
import { safeFetchJson, API_BASE } from '@/lib/api';

// ===============================
// TYPES
// ===============================

interface Timesheet {
  id: number;
  user: number;
  user_name: string;
  user_email: string;
  week_start: string;
  week_end: string;
  status: string;
  total_hours: number;
  billable_hours: number;
  total_amount: number;
  submitted_at: string | null;
  submitted_notes: string;
  days_pending: number;
  auto_submitted?: boolean;  // ← NEW: Flag for auto-submitted timesheets
}

interface QueueData {
  count: number;
  timesheets: Timesheet[];
}

interface ApprovalQueueProps {
  // No props needed - uses API_BASE from lib/api
}

interface TimesheetCardProps {
  timesheet: Timesheet;
  onApprove: (id: number) => Promise<void>;
  onReject: (id: number, reason: string) => Promise<void>;
  onViewDetails: (id: number) => void;
}

interface AvatarProps {
  name: string;
  size?: 'sm' | 'md' | 'lg';
}

// ===============================
// UTILITY FUNCTIONS
// ===============================

const formatHours = (hours: number | string): string => {
  const num = parseFloat(String(hours)) || 0;
  return num.toFixed(1);
};

const formatCurrency = (amount: number | string): string => {
  const num = parseFloat(String(amount)) || 0;
  return num.toLocaleString('en-US', { style: 'currency', currency: 'USD' });
};

const formatWeekRange = (weekStart: string, weekEnd: string): string => {
  const start = new Date(weekStart + 'T00:00:00');
  const end = new Date(weekEnd + 'T00:00:00');
  return `${start.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })} - ${end.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}`;
};

// ===============================
// SUB-COMPONENTS
// ===============================

const Avatar: React.FC<AvatarProps> = ({ name, size = 'md' }) => {
  const initials = name
    .split(' ')
    .map(n => n[0])
    .join('')
    .toUpperCase()
    .slice(0, 2);
  
  const colors = [
    'bg-blue-500', 'bg-emerald-500', 'bg-amber-500', 'bg-rose-500',
    'bg-violet-500', 'bg-cyan-500', 'bg-orange-500', 'bg-indigo-500',
  ];
  const colorIndex = name.length % colors.length;
  
  const sizes: Record<string, string> = {
    sm: 'w-8 h-8 text-xs',
    md: 'w-10 h-10 text-sm',
    lg: 'w-12 h-12 text-base',
  };
  
  return (
    <div className={`${sizes[size]} ${colors[colorIndex]} rounded-full flex items-center justify-center text-white font-semibold`}>
      {initials}
    </div>
  );
};

const TimesheetCard: React.FC<TimesheetCardProps> = ({ timesheet, onApprove, onReject, onViewDetails }) => {
  const [showRejectModal, setShowRejectModal] = useState<boolean>(false);
  const [rejectReason, setRejectReason] = useState<string>('');
  const [processing, setProcessing] = useState<boolean>(false);

  const handleApprove = async (): Promise<void> => {
    setProcessing(true);
    await onApprove(timesheet.id);
    setProcessing(false);
  };

  const handleReject = async (): Promise<void> => {
    if (!rejectReason.trim()) return;
    setProcessing(true);
    await onReject(timesheet.id, rejectReason);
    setProcessing(false);
    setShowRejectModal(false);
    setRejectReason('');
  };

  return (
    <>
      <div className={`bg-white rounded-xl border shadow-sm hover:shadow-md transition-shadow overflow-hidden ${
        timesheet.auto_submitted 
          ? 'border-amber-200 ring-1 ring-amber-100' 
          : 'border-slate-200'
      }`}>
        <div className="p-5">
          {/* Header */}
          <div className="flex items-start justify-between mb-4">
            <div className="flex items-center gap-3">
              <Avatar name={timesheet.user_name} />
              <div>
                <h3 className="font-semibold text-slate-800">{timesheet.user_name}</h3>
                <p className="text-sm text-slate-500">{timesheet.user_email}</p>
              </div>
            </div>
            <div className="flex flex-col items-end gap-1">
              {/* Auto-submitted badge */}
              {timesheet.auto_submitted && (
                <span className="px-2 py-1 rounded text-xs font-medium bg-amber-100 text-amber-700 flex items-center gap-1">
                  <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm1-12a1 1 0 10-2 0v4a1 1 0 00.293.707l2.828 2.829a1 1 0 101.415-1.415L11 9.586V6z" clipRule="evenodd" />
                  </svg>
                  Auto-submitted
                </span>
              )}
              {/* Days pending badge */}
              {timesheet.days_pending > 0 && (
                <span className={`px-2 py-1 rounded text-xs font-medium ${
                  timesheet.days_pending >= 3 
                    ? 'bg-red-100 text-red-700' 
                    : timesheet.days_pending >= 1 
                      ? 'bg-amber-100 text-amber-700'
                      : 'bg-slate-100 text-slate-600'
                }`}>
                  {timesheet.days_pending} day{timesheet.days_pending !== 1 ? 's' : ''} pending
                </span>
              )}
            </div>
          </div>

          {/* Auto-submitted notice */}
          {timesheet.auto_submitted && (
            <div className="mb-4 p-3 bg-amber-50 rounded-lg border border-amber-100">
              <div className="flex items-start gap-2">
                <svg className="w-4 h-4 text-amber-500 mt-0.5 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
                </svg>
                <div>
                  <div className="text-xs font-medium text-amber-700">Not manually reviewed</div>
                  <p className="text-xs text-amber-600 mt-0.5">
                    This timesheet was auto-submitted (Tuesday deadline). Employee did not review before submission.
                  </p>
                </div>
              </div>
            </div>
          )}

          {/* Week Info */}
          <div className="flex items-center gap-2 text-sm text-slate-600 mb-4">
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
            </svg>
            <span>Week of {formatWeekRange(timesheet.week_start, timesheet.week_end)}</span>
          </div>

          {/* Hours Summary */}
          <div className="grid grid-cols-3 gap-3 mb-4">
            <div className="bg-slate-50 rounded-lg p-3 text-center">
              <div className="text-xs text-slate-500 uppercase tracking-wide">Total</div>
              <div className="text-lg font-bold text-slate-800">{formatHours(timesheet.total_hours)}h</div>
            </div>
            <div className="bg-emerald-50 rounded-lg p-3 text-center">
              <div className="text-xs text-emerald-600 uppercase tracking-wide">Billable</div>
              <div className="text-lg font-bold text-emerald-700">{formatHours(timesheet.billable_hours)}h</div>
            </div>
            <div className="bg-blue-50 rounded-lg p-3 text-center">
              <div className="text-xs text-blue-600 uppercase tracking-wide">Amount</div>
              <div className="text-lg font-bold text-blue-700">{formatCurrency(timesheet.total_amount)}</div>
            </div>
          </div>

          {/* Notes */}
          {timesheet.submitted_notes && !timesheet.submitted_notes.startsWith('[Auto-submitted') && (
            <div className="mb-4 p-3 bg-blue-50 rounded-lg border border-blue-100">
              <div className="flex items-start gap-2">
                <svg className="w-4 h-4 text-blue-500 mt-0.5" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M18 13V5a2 2 0 00-2-2H4a2 2 0 00-2 2v8a2 2 0 002 2h3l3 3 3-3h3a2 2 0 002-2zM5 7a1 1 0 011-1h8a1 1 0 110 2H6a1 1 0 01-1-1zm1 3a1 1 0 100 2h3a1 1 0 100-2H6z" clipRule="evenodd" />
                </svg>
                <div>
                  <div className="text-xs font-medium text-blue-700 mb-1">Note from employee:</div>
                  <p className="text-sm text-blue-800">{timesheet.submitted_notes}</p>
                </div>
              </div>
            </div>
          )}

          {/* Actions */}
          <div className="flex items-center gap-2 pt-3 border-t border-slate-100">
            <button
              onClick={() => onViewDetails(timesheet.id)}
              className="flex-1 px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100 rounded-lg transition-colors"
            >
              View Details
            </button>
            <button
              onClick={() => setShowRejectModal(true)}
              disabled={processing}
              className="px-4 py-2 text-sm font-medium text-red-600 hover:bg-red-50 rounded-lg transition-colors disabled:opacity-50"
            >
              Reject
            </button>
            <button
              onClick={handleApprove}
              disabled={processing}
              className="px-5 py-2 text-sm font-medium bg-emerald-600 text-white hover:bg-emerald-700 rounded-lg transition-colors disabled:opacity-50 flex items-center gap-2"
            >
              {processing ? (
                <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
              ) : (
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                </svg>
              )}
              Approve
            </button>
          </div>
        </div>
      </div>

      {/* Reject Modal */}
      {showRejectModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl shadow-xl max-w-md w-full mx-4 overflow-hidden">
            <div className="px-6 py-4 border-b border-slate-200 bg-red-50">
              <h3 className="text-lg font-semibold text-red-800">Reject Timesheet</h3>
            </div>
            <div className="p-6">
              <p className="text-slate-600 mb-4">
                Please provide a reason for rejecting <strong>{timesheet.user_name}'s</strong> timesheet.
              </p>
              {timesheet.auto_submitted && (
                <div className="mb-4 p-3 bg-amber-50 rounded-lg border border-amber-200 text-sm text-amber-700">
                  <strong>Note:</strong> This timesheet was auto-submitted. The employee may not have reviewed their time entries.
                </div>
              )}
              <textarea
                value={rejectReason}
                onChange={(e) => setRejectReason(e.target.value)}
                placeholder="Reason for rejection..."
                className="w-full px-4 py-3 border border-slate-300 rounded-lg focus:ring-2 focus:ring-red-500 focus:border-red-500 resize-none"
                rows={3}
                autoFocus
              />
            </div>
            <div className="px-6 py-4 bg-slate-50 border-t border-slate-200 flex justify-end gap-3">
              <button
                onClick={() => {
                  setShowRejectModal(false);
                  setRejectReason('');
                }}
                className="px-4 py-2 text-slate-700 font-medium hover:bg-slate-200 rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleReject}
                disabled={!rejectReason.trim() || processing}
                className="px-6 py-2 bg-red-600 text-white font-medium rounded-lg hover:bg-red-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {processing ? 'Rejecting...' : 'Reject Timesheet'}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
};

// ===============================
// MAIN COMPONENT
// ===============================

const ApprovalQueue: React.FC<ApprovalQueueProps> = () => {
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [queueData, setQueueData] = useState<QueueData>({ count: 0, timesheets: [] });
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  const fetchQueue = useCallback(async (): Promise<void> => {
    setLoading(true);
    setError(null);
    try {
      const data = await safeFetchJson<QueueData>(`${API_BASE}/billing/approval-queue/`);
      setQueueData(data);
    } catch (err) {
      if (err instanceof Error && err.message.includes('403')) {
        setError('You do not have permission to view the approval queue');
      } else {
        setError(err instanceof Error ? err.message : 'Unknown error');
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchQueue();
  }, [fetchQueue]);

  const showSuccess = (message: string): void => {
    setSuccessMessage(message);
    setTimeout(() => setSuccessMessage(null), 3000);
  };

  const handleApprove = async (timesheetId: number): Promise<void> => {
    try {
      await safeFetchJson(
        `${API_BASE}/billing/timesheets/${timesheetId}/approve/`,
        {
          method: 'POST',
          body: JSON.stringify({ notes: '' }),
        }
      );
      showSuccess('Timesheet approved successfully');
      fetchQueue();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    }
  };

  const handleReject = async (timesheetId: number, reason: string): Promise<void> => {
    try {
      await safeFetchJson(
        `${API_BASE}/billing/timesheets/${timesheetId}/reject/`,
        {
          method: 'POST',
          body: JSON.stringify({ reason }),
        }
      );
      showSuccess('Timesheet rejected');
      fetchQueue();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    }
  };

  const handleViewDetails = (timesheetId: number): void => {
    window.location.href = `/timesheets/${timesheetId}`;
  };

  // Count auto-submitted
  const autoSubmittedCount = queueData.timesheets.filter(t => t.auto_submitted).length;

  if (loading) {
    return (
      <div className="min-h-[400px] flex items-center justify-center">
        <div className="flex flex-col items-center gap-3">
          <div className="w-8 h-8 border-3 border-blue-500 border-t-transparent rounded-full animate-spin" />
          <span className="text-slate-500">Loading approval queue...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">Approval Queue</h1>
          <p className="text-slate-500 mt-1">Review and approve team timesheets</p>
        </div>
        <button
          onClick={fetchQueue}
          className="p-2 hover:bg-slate-100 rounded-lg transition-colors"
          title="Refresh"
        >
          <svg className="w-5 h-5 text-slate-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
          </svg>
        </button>
      </div>

      {/* Success Message */}
      {successMessage && (
        <div className="p-4 bg-emerald-50 border border-emerald-200 rounded-lg flex items-center gap-3">
          <svg className="w-5 h-5 text-emerald-500" fill="currentColor" viewBox="0 0 20 20">
            <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
          </svg>
          <span className="text-emerald-700">{successMessage}</span>
        </div>
      )}

      {/* Error Message */}
      {error && (
        <div className="p-4 bg-red-50 border border-red-200 rounded-lg flex items-center gap-3">
          <svg className="w-5 h-5 text-red-500" fill="currentColor" viewBox="0 0 20 20">
            <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
          </svg>
          <span className="text-red-700">{error}</span>
        </div>
      )}

      {/* Queue Stats */}
      <div className="grid grid-cols-2 gap-4">
        <div className="bg-gradient-to-r from-amber-50 to-orange-50 rounded-xl p-5 border border-amber-100">
          <div className="flex items-center gap-4">
            <div className="w-12 h-12 bg-amber-500 rounded-xl flex items-center justify-center">
              <svg className="w-6 h-6 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" />
              </svg>
            </div>
            <div>
              <div className="text-3xl font-bold text-amber-800">{queueData.count}</div>
              <div className="text-amber-600">timesheet{queueData.count !== 1 ? 's' : ''} pending approval</div>
            </div>
          </div>
        </div>
        
        {/* Auto-submitted count */}
        {autoSubmittedCount > 0 && (
          <div className="bg-gradient-to-r from-slate-50 to-slate-100 rounded-xl p-5 border border-slate-200">
            <div className="flex items-center gap-4">
              <div className="w-12 h-12 bg-slate-400 rounded-xl flex items-center justify-center">
                <svg className="w-6 h-6 text-white" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm1-12a1 1 0 10-2 0v4a1 1 0 00.293.707l2.828 2.829a1 1 0 101.415-1.415L11 9.586V6z" clipRule="evenodd" />
                </svg>
              </div>
              <div>
                <div className="text-3xl font-bold text-slate-700">{autoSubmittedCount}</div>
                <div className="text-slate-500">auto-submitted (not manually reviewed)</div>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Queue List */}
      {queueData.timesheets.length === 0 ? (
        <div className="bg-white rounded-xl border border-slate-200 p-12 text-center">
          <div className="w-16 h-16 bg-emerald-100 rounded-full flex items-center justify-center mx-auto mb-4">
            <svg className="w-8 h-8 text-emerald-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
          </div>
          <h3 className="text-lg font-semibold text-slate-800 mb-2">All caught up!</h3>
          <p className="text-slate-500">No timesheets pending approval</p>
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {queueData.timesheets.map((timesheet) => (
            <TimesheetCard
              key={timesheet.id}
              timesheet={timesheet}
              onApprove={handleApprove}
              onReject={handleReject}
              onViewDetails={handleViewDetails}
            />
          ))}
        </div>
      )}
    </div>
  );
};

export default ApprovalQueue;