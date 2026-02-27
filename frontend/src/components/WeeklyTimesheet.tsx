// src/components/WeeklyTimesheet.tsx (also known as MyTimesheet)
// Professional weekly timesheet grid for CPA firms

import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { safeFetchJson, API_BASE } from '@/lib/api';

// ===============================
// TYPES
// ===============================

interface TimesheetEntry {
  client_id: number | null;
  client_name: string;
  task_type_id: number | null;
  task_type_name: string;
  is_billable: boolean;
  days: Record<string, number>;
  total: number;
}

interface TimesheetData {
  week_start: string;
  week_end: string;
  timesheet_id: number;
  status: 'draft' | 'submitted' | 'approved' | 'rejected' | 'locked';
  entries: TimesheetEntry[];
  daily_totals: Record<string, number>;
  grand_total: number;
  billable_total: number;
  auto_submitted?: boolean;  // ← NEW: Flag for auto-submitted timesheets
  submitted_at?: string | null;
  rejection_reason?: string;
}

interface DayHeader {
  date: string;
  label: string;
  dayNum: number;
  isWeekend: boolean;
}

interface WeeklyTimesheetProps {
  // No props needed - uses API_BASE from lib/api
}

interface TimeCellProps {
  value: number;
  onChange?: (val: number) => void;
  disabled?: boolean;
  isTotal?: boolean;
}

interface StatusBadgeProps {
  status: TimesheetData['status'];
  autoSubmitted?: boolean;
}

// ===============================
// UTILITY FUNCTIONS
// ===============================

const formatHours = (hours: number | string): string => {
  const num = parseFloat(String(hours)) || 0;
  return num.toFixed(2);
};

const getMonday = (date: Date): Date => {
  const d = new Date(date);
  const day = d.getDay();
  const diff = d.getDate() - day + (day === 0 ? -6 : 1);
  return new Date(d.setDate(diff));
};

const formatWeekRange = (weekStart: string): string => {
  const start = new Date(weekStart + 'T00:00:00');
  const end = new Date(start);
  end.setDate(end.getDate() + 6);
  return `${start.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })} - ${end.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}`;
};

const isWeekEnded = (weekStart: string): boolean => {
  const start = new Date(weekStart + 'T00:00:00');
  const weekEnd = new Date(start);
  weekEnd.setDate(weekEnd.getDate() + 6); // Sunday
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return today > weekEnd;
};

const getCanSubmitDate = (weekStart: string): string => {
  const start = new Date(weekStart + 'T00:00:00');
  const monday = new Date(start);
  monday.setDate(monday.getDate() + 7); // Next Monday
  return monday.toLocaleDateString('en-US', { weekday: 'long', month: 'short', day: 'numeric' });
};

const getDaysUntilSubmit = (weekStart: string): number => {
  const start = new Date(weekStart + 'T00:00:00');
  const weekEnd = new Date(start);
  weekEnd.setDate(weekEnd.getDate() + 6); // Sunday
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const diff = weekEnd.getTime() - today.getTime();
  return Math.ceil(diff / (1000 * 60 * 60 * 24)) + 1; // +1 because submit is available day after week ends
};

// ===============================
// SUB-COMPONENTS
// ===============================

const StatusBadge: React.FC<StatusBadgeProps> = ({ status, autoSubmitted }) => {
  const styles: Record<string, string> = {
    draft: 'bg-slate-100 text-slate-700 border-slate-200',
    submitted: 'bg-amber-50 text-amber-700 border-amber-200',
    approved: 'bg-emerald-50 text-emerald-700 border-emerald-200',
    rejected: 'bg-red-50 text-red-700 border-red-200',
    locked: 'bg-slate-200 text-slate-600 border-slate-300',
  };

  const labels: Record<string, string> = {
    draft: 'Draft',
    submitted: 'Pending Approval',
    approved: 'Approved',
    rejected: 'Rejected',
    locked: 'Locked',
  };

  return (
    <div className="flex items-center gap-2">
      <span className={`inline-flex items-center px-3 py-1 rounded-full text-sm font-medium border ${styles[status] || styles.draft}`}>
        {status === 'submitted' && (
          <span className="w-2 h-2 bg-amber-500 rounded-full mr-2 animate-pulse" />
        )}
        {status === 'approved' && (
          <svg className="w-4 h-4 mr-1.5" fill="currentColor" viewBox="0 0 20 20">
            <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
          </svg>
        )}
        {status === 'locked' && (
          <svg className="w-4 h-4 mr-1.5" fill="currentColor" viewBox="0 0 20 20">
            <path fillRule="evenodd" d="M5 9V7a5 5 0 0110 0v2a2 2 0 012 2v5a2 2 0 01-2 2H5a2 2 0 01-2-2v-5a2 2 0 012-2zm8-2v2H7V7a3 3 0 016 0z" clipRule="evenodd" />
          </svg>
        )}
        {labels[status] || status}
      </span>
      
      {/* Auto-submitted badge */}
      {autoSubmitted && (
        <span className="inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-amber-100 text-amber-700 border border-amber-200">
          <svg className="w-3 h-3 mr-1" fill="currentColor" viewBox="0 0 20 20">
            <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm1-12a1 1 0 10-2 0v4a1 1 0 00.293.707l2.828 2.829a1 1 0 101.415-1.415L11 9.586V6z" clipRule="evenodd" />
          </svg>
          Auto-submitted
        </span>
      )}
    </div>
  );
};

const TimeCell: React.FC<TimeCellProps> = ({ value, onChange, disabled, isTotal }) => {
  const [editing, setEditing] = useState(false);
  const [localValue, setLocalValue] = useState(formatHours(value));

  useEffect(() => {
    setLocalValue(formatHours(value));
  }, [value]);

  const handleBlur = () => {
    setEditing(false);
    const newValue = parseFloat(localValue) || 0;
    if (newValue !== parseFloat(String(value)) && onChange) {
      onChange(newValue);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      (e.target as HTMLInputElement).blur();
    }
    if (e.key === 'Escape') {
      setLocalValue(formatHours(value));
      setEditing(false);
    }
  };

  if (isTotal) {
    return (
      <div className="px-3 py-2 text-right font-semibold text-slate-800 bg-slate-50">
        {formatHours(value)}
      </div>
    );
  }

  if (disabled) {
    return (
      <div className="px-3 py-2 text-right text-slate-500 bg-slate-50/50">
        {formatHours(value)}
      </div>
    );
  }

  return (
    <div className="relative">
      {editing ? (
        <input
          type="number"
          step="0.25"
          min="0"
          max="24"
          value={localValue}
          onChange={(e) => setLocalValue(e.target.value)}
          onBlur={handleBlur}
          onKeyDown={handleKeyDown}
          className="w-full px-3 py-2 text-right bg-white border-2 border-blue-500 rounded focus:outline-none focus:ring-2 focus:ring-blue-200"
          autoFocus
        />
      ) : (
        <button
          onClick={() => setEditing(true)}
          className={`w-full px-3 py-2 text-right hover:bg-blue-50 transition-colors rounded ${
            parseFloat(String(value)) > 0 ? 'text-slate-800 font-medium' : 'text-slate-400'
          }`}
        >
          {formatHours(value)}
        </button>
      )}
    </div>
  );
};

// ===============================
// MAIN COMPONENT
// ===============================

const WeeklyTimesheet: React.FC<WeeklyTimesheetProps> = () => {
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [weekStart, setWeekStart] = useState<string>(() => {
    const params = new URLSearchParams(window.location.search);
    const weekParam = params.get('week');
    if (weekParam && /^\d{4}-\d{2}-\d{2}$/.test(weekParam)) {
        return weekParam;
    }
    const monday = getMonday(new Date());
    return monday.toISOString().split('T')[0];
  });
  const [timesheetData, setTimesheetData] = useState<TimesheetData | null>(null);
  const [submitting, setSubmitting] = useState<boolean>(false);
  const [submitNotes, setSubmitNotes] = useState<string>('');
  const [showSubmitModal, setShowSubmitModal] = useState<boolean>(false);

  // Fetch timesheet data
  const fetchTimesheet = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await safeFetchJson<TimesheetData>(
        `${API_BASE}/billing/weekly/?week_start=${weekStart}`
      );
      setTimesheetData(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  }, [weekStart]);

  useEffect(() => {
    fetchTimesheet();
  }, [fetchTimesheet]);

  // Navigate weeks
  const goToWeek = (direction: number): void => {
    const current = new Date(weekStart + 'T00:00:00');
    current.setDate(current.getDate() + (direction * 7));
    setWeekStart(current.toISOString().split('T')[0]);
  };

  const goToCurrentWeek = (): void => {
    const monday = getMonday(new Date());
    setWeekStart(monday.toISOString().split('T')[0]);
  };

  // Check if can submit
  const canSubmitTimesheet = useMemo(() => {
    if (!timesheetData) return false;
    if (timesheetData.status !== 'draft' && timesheetData.status !== 'rejected') return false;
    return isWeekEnded(timesheetData.week_start);
  }, [timesheetData]);

  const daysUntilCanSubmit = useMemo(() => {
    if (!timesheetData) return 0;
    return getDaysUntilSubmit(timesheetData.week_start);
  }, [timesheetData]);

  // Submit timesheet
  const handleSubmit = async (): Promise<void> => {
    if (!timesheetData?.timesheet_id) return;
    
    setSubmitting(true);
    setError(null);
    try {
      await safeFetchJson(
        `${API_BASE}/billing/timesheets/${timesheetData.timesheet_id}/submit/`,
        {
          method: 'POST',
          body: JSON.stringify({ notes: submitNotes }),
        }
      );
      setShowSubmitModal(false);
      setSubmitNotes('');
      fetchTimesheet();
    } catch (err: any) {
      // Handle the "week not ended" error from backend
      const errorData = err?.data || {};
      if (errorData.can_submit_on) {
        setError(`Cannot submit yet. This timesheet can be submitted starting ${errorData.can_submit_on}.`);
      } else {
        setError(err instanceof Error ? err.message : 'Unknown error');
      }
    } finally {
      setSubmitting(false);
    }
  };

  // Reopen rejected timesheet
  const handleReopen = async (): Promise<void> => {
    if (!timesheetData?.timesheet_id) return;
    
    try {
      await safeFetchJson(
        `${API_BASE}/billing/timesheets/${timesheetData.timesheet_id}/reopen/`,
        { method: 'POST' }
      );
      fetchTimesheet();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    }
  };

  // Generate day headers
  const getDayHeaders = (): DayHeader[] => {
    if (!timesheetData) return [];
    const start = new Date(timesheetData.week_start + 'T00:00:00');
    const days: DayHeader[] = [];
    for (let i = 0; i < 7; i++) {
      const day = new Date(start);
      day.setDate(day.getDate() + i);
      days.push({
        date: day.toISOString().split('T')[0],
        label: day.toLocaleDateString('en-US', { weekday: 'short' }),
        dayNum: day.getDate(),
        isWeekend: i >= 5,
      });
    }
    return days;
  };

  const days = getDayHeaders();
  const isEditable = timesheetData?.status === 'draft' || timesheetData?.status === 'rejected';
  const weekHasEnded = timesheetData ? isWeekEnded(timesheetData.week_start) : false;

  // Loading state
  if (loading) {
    return (
      <div className="min-h-[400px] flex items-center justify-center">
        <div className="flex flex-col items-center gap-3">
          <div className="w-8 h-8 border-3 border-blue-500 border-t-transparent rounded-full animate-spin" />
          <span className="text-slate-500">Loading timesheet...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden">
      {/* Header */}
      <div className="px-6 py-4 border-b border-slate-200 bg-gradient-to-r from-slate-50 to-white">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <h2 className="text-xl font-semibold text-slate-800">My Timesheet</h2>
            {timesheetData && (
              <StatusBadge 
                status={timesheetData.status} 
                autoSubmitted={timesheetData.auto_submitted}
              />
            )}
          </div>
          
          {/* Week Navigation */}
          <div className="flex items-center gap-2">
            <button
              onClick={() => goToWeek(-1)}
              className="p-2 hover:bg-slate-100 rounded-lg transition-colors"
              title="Previous week"
            >
              <svg className="w-5 h-5 text-slate-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
              </svg>
            </button>
            
            <button
              onClick={goToCurrentWeek}
              className="px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100 rounded-lg transition-colors"
            >
              Today
            </button>
            
            <button
              onClick={() => goToWeek(1)}
              className="p-2 hover:bg-slate-100 rounded-lg transition-colors"
              title="Next week"
            >
              <svg className="w-5 h-5 text-slate-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
              </svg>
            </button>
            
            <span className="ml-3 px-4 py-2 bg-slate-100 rounded-lg text-sm font-medium text-slate-700">
              {timesheetData && formatWeekRange(timesheetData.week_start)}
            </span>
          </div>
        </div>
      </div>

      {/* Error Display */}
      {error && (
        <div className="mx-6 mt-4 p-4 bg-red-50 border border-red-200 rounded-lg">
          <div className="flex items-center gap-2 text-red-700">
            <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
            </svg>
            <span>{error}</span>
          </div>
        </div>
      )}

      {/* Auto-submitted Notice */}
      {timesheetData?.auto_submitted && timesheetData?.status === 'submitted' && (
        <div className="mx-6 mt-4 p-4 bg-amber-50 border border-amber-200 rounded-lg">
          <div className="flex items-start gap-3">
            <svg className="w-5 h-5 text-amber-500 mt-0.5" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm1-12a1 1 0 10-2 0v4a1 1 0 00.293.707l2.828 2.829a1 1 0 101.415-1.415L11 9.586V6z" clipRule="evenodd" />
            </svg>
            <div>
              <h4 className="font-medium text-amber-800">Timesheet Auto-Submitted</h4>
              <p className="text-sm text-amber-700 mt-1">
                This timesheet was automatically submitted on Tuesday because it wasn't manually submitted by the deadline.
                Your manager will review it shortly.
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Week Not Ended Info (for draft timesheets) */}
      {timesheetData?.status === 'draft' && !weekHasEnded && (
        <div className="mx-6 mt-4 p-4 bg-blue-50 border border-blue-200 rounded-lg">
          <div className="flex items-start gap-3">
            <svg className="w-5 h-5 text-blue-500 mt-0.5" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clipRule="evenodd" />
            </svg>
            <div>
              <h4 className="font-medium text-blue-800">Week In Progress</h4>
              <p className="text-sm text-blue-700 mt-1">
                You can submit this timesheet starting <strong>{getCanSubmitDate(timesheetData.week_start)}</strong> 
                {daysUntilCanSubmit > 0 && ` (${daysUntilCanSubmit} day${daysUntilCanSubmit !== 1 ? 's' : ''} from now)`}.
                Your time is being tracked automatically.
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Rejection Notice */}
      {timesheetData?.status === 'rejected' && (
        <div className="mx-6 mt-4 p-4 bg-red-50 border border-red-200 rounded-lg">
          <div className="flex items-start gap-3">
            <svg className="w-5 h-5 text-red-500 mt-0.5" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
            </svg>
            <div>
              <h4 className="font-medium text-red-800">Timesheet Rejected</h4>
              <p className="text-sm text-red-700 mt-1">
                {timesheetData.rejection_reason || 'Please review and make corrections before resubmitting.'}
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Timesheet Grid */}
      <div className="p-6">
        <div className="overflow-x-auto">
          <table className="w-full border-collapse">
            <thead>
              <tr>
                <th className="text-left px-4 py-3 bg-slate-50 border-b-2 border-slate-200 font-semibold text-slate-700 min-w-[200px]">
                  Client / Task
                </th>
                {days.map((day) => (
                  <th
                    key={day.date}
                    className={`text-center px-2 py-3 border-b-2 border-slate-200 font-semibold min-w-[80px] ${
                      day.isWeekend ? 'bg-slate-100 text-slate-500' : 'bg-slate-50 text-slate-700'
                    }`}
                  >
                    <div className="text-xs uppercase tracking-wide">{day.label}</div>
                    <div className="text-lg">{day.dayNum}</div>
                  </th>
                ))}
                <th className="text-center px-4 py-3 bg-slate-100 border-b-2 border-slate-300 font-semibold text-slate-800 min-w-[80px]">
                  Total
                </th>
              </tr>
            </thead>
            <tbody>
              {timesheetData?.entries?.length === 0 ? (
                <tr>
                  <td colSpan={9} className="text-center py-12 text-slate-500">
                    <div className="flex flex-col items-center gap-2">
                      <svg className="w-12 h-12 text-slate-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                      </svg>
                      <span>No time entries for this week</span>
                      <span className="text-sm">Time will appear here as it's tracked by your desktop agent</span>
                    </div>
                  </td>
                </tr>
              ) : (
                timesheetData?.entries?.map((entry, idx) => (
                  <tr
                    key={`${entry.client_id}-${entry.task_type_id}`}
                    className={`border-b border-slate-100 hover:bg-slate-50/50 transition-colors ${
                      idx % 2 === 0 ? 'bg-white' : 'bg-slate-50/30'
                    }`}
                  >
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-3">
                        <div
                          className={`w-2 h-8 rounded-full ${
                            entry.is_billable ? 'bg-emerald-500' : 'bg-slate-300'
                          }`}
                          title={entry.is_billable ? 'Billable' : 'Non-billable'}
                        />
                        <div>
                          <div className="font-medium text-slate-800">{entry.client_name}</div>
                          <div className="text-sm text-slate-500">{entry.task_type_name}</div>
                        </div>
                      </div>
                    </td>
                    {days.map((day) => (
                      <td
                        key={day.date}
                        className={`border-l border-slate-100 ${day.isWeekend ? 'bg-slate-50/50' : ''}`}
                      >
                        <TimeCell
                          value={entry.days[day.date] || 0}
                          onChange={(val) => {
                            // TODO: Implement cell update via API
                            console.log('Update', entry.client_id, day.date, val);
                          }}
                          disabled={!isEditable}
                        />
                      </td>
                    ))}
                    <td className="border-l-2 border-slate-200 bg-slate-50">
                      <TimeCell value={entry.total} isTotal />
                    </td>
                  </tr>
                ))
              )}
            </tbody>
            <tfoot>
              <tr className="bg-slate-100 border-t-2 border-slate-300">
                <td className="px-4 py-3 font-semibold text-slate-800">Daily Totals</td>
                {days.map((day) => (
                  <td key={day.date} className="text-center px-3 py-3 font-semibold text-slate-800 border-l border-slate-200">
                    {formatHours(timesheetData?.daily_totals?.[day.date] || 0)}
                  </td>
                ))}
                <td className="text-center px-4 py-3 font-bold text-slate-900 border-l-2 border-slate-300 bg-slate-200">
                  {formatHours(timesheetData?.grand_total || 0)}
                </td>
              </tr>
            </tfoot>
          </table>
        </div>

        {/* Summary Cards */}
        <div className="grid grid-cols-3 gap-4 mt-6">
          <div className="p-4 bg-gradient-to-br from-slate-50 to-slate-100 rounded-lg border border-slate-200">
            <div className="text-sm text-slate-500 font-medium">Total Hours</div>
            <div className="text-2xl font-bold text-slate-800 mt-1">
              {formatHours(timesheetData?.grand_total || 0)}
            </div>
          </div>
          <div className="p-4 bg-gradient-to-br from-emerald-50 to-emerald-100 rounded-lg border border-emerald-200">
            <div className="text-sm text-emerald-600 font-medium">Billable Hours</div>
            <div className="text-2xl font-bold text-emerald-700 mt-1">
              {formatHours(timesheetData?.billable_total || 0)}
            </div>
          </div>
          <div className="p-4 bg-gradient-to-br from-slate-50 to-slate-100 rounded-lg border border-slate-200">
            <div className="text-sm text-slate-500 font-medium">Non-Billable</div>
            <div className="text-2xl font-bold text-slate-600 mt-1">
              {formatHours((timesheetData?.grand_total || 0) - (timesheetData?.billable_total || 0))}
            </div>
          </div>
        </div>

        {/* Action Buttons */}
        <div className="flex items-center justify-between mt-6 pt-6 border-t border-slate-200">
          <div className="text-sm text-slate-500">
            {isEditable ? (
              <span className="flex items-center gap-2">
                <span className="w-2 h-2 bg-emerald-500 rounded-full" />
                Click any cell to edit hours
              </span>
            ) : (
              <span className="flex items-center gap-2">
                <span className="w-2 h-2 bg-slate-400 rounded-full" />
                Timesheet is locked for editing
              </span>
            )}
          </div>
          
          <div className="flex items-center gap-3">
            {/* Draft - can submit if week ended */}
            {timesheetData?.status === 'draft' && (
              <>
                {weekHasEnded ? (
                  <button
                    onClick={() => setShowSubmitModal(true)}
                    className="px-6 py-2.5 bg-blue-600 text-white font-medium rounded-lg hover:bg-blue-700 transition-colors shadow-sm hover:shadow flex items-center gap-2"
                  >
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                    Submit for Approval
                  </button>
                ) : (
                  <button
                    disabled
                    className="px-6 py-2.5 bg-slate-300 text-slate-500 font-medium rounded-lg cursor-not-allowed flex items-center gap-2"
                    title={`Submit available ${getCanSubmitDate(timesheetData.week_start)}`}
                  >
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                    Submit ({daysUntilCanSubmit} day{daysUntilCanSubmit !== 1 ? 's' : ''})
                  </button>
                )}
              </>
            )}
            
            {/* Rejected - can reopen and resubmit */}
            {timesheetData?.status === 'rejected' && (
              <>
                <button
                  onClick={handleReopen}
                  className="px-4 py-2.5 bg-slate-100 text-slate-700 font-medium rounded-lg hover:bg-slate-200 transition-colors"
                >
                  Edit Timesheet
                </button>
                <button
                  onClick={() => setShowSubmitModal(true)}
                  className="px-6 py-2.5 bg-blue-600 text-white font-medium rounded-lg hover:bg-blue-700 transition-colors shadow-sm"
                >
                  Resubmit
                </button>
              </>
            )}
            
            {/* Submitted - waiting */}
            {timesheetData?.status === 'submitted' && (
              <span className="text-amber-600 font-medium flex items-center gap-2">
                <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm1-12a1 1 0 10-2 0v4a1 1 0 00.293.707l2.828 2.829a1 1 0 101.415-1.415L11 9.586V6z" clipRule="evenodd" />
                </svg>
                Awaiting manager approval
                {timesheetData.auto_submitted && ' (auto-submitted)'}
              </span>
            )}
            
            {/* Approved */}
            {timesheetData?.status === 'approved' && (
              <span className="text-emerald-600 font-medium flex items-center gap-2">
                <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
                </svg>
                Approved
              </span>
            )}
            
            {/* Locked */}
            {timesheetData?.status === 'locked' && (
              <span className="text-slate-600 font-medium flex items-center gap-2">
                <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M5 9V7a5 5 0 0110 0v2a2 2 0 012 2v5a2 2 0 01-2 2H5a2 2 0 01-2-2v-5a2 2 0 012-2zm8-2v2H7V7a3 3 0 016 0z" clipRule="evenodd" />
                </svg>
                Locked (Invoiced)
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Submit Modal */}
      {showSubmitModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl shadow-xl max-w-md w-full mx-4 overflow-hidden">
            <div className="px-6 py-4 border-b border-slate-200 bg-slate-50">
              <h3 className="text-lg font-semibold text-slate-800">Submit Timesheet</h3>
            </div>
            <div className="p-6">
              <p className="text-slate-600 mb-4">
                You're about to submit your timesheet for the week of{' '}
                <strong>{timesheetData && formatWeekRange(timesheetData.week_start)}</strong>.
              </p>
              <div className="bg-slate-50 rounded-lg p-4 mb-4">
                <div className="grid grid-cols-2 gap-4 text-sm">
                  <div>
                    <span className="text-slate-500">Total Hours:</span>
                    <span className="ml-2 font-semibold">{formatHours(timesheetData?.grand_total || 0)}</span>
                  </div>
                  <div>
                    <span className="text-slate-500">Billable:</span>
                    <span className="ml-2 font-semibold text-emerald-600">{formatHours(timesheetData?.billable_total || 0)}</span>
                  </div>
                </div>
              </div>
              <div className="mb-4">
                <label className="block text-sm font-medium text-slate-700 mb-2">
                  Notes (optional)
                </label>
                <textarea
                  value={submitNotes}
                  onChange={(e) => setSubmitNotes(e.target.value)}
                  placeholder="Any notes for your manager..."
                  className="w-full px-4 py-3 border border-slate-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 resize-none"
                  rows={3}
                />
              </div>
              <div className="p-3 bg-blue-50 rounded-lg border border-blue-100 text-sm text-blue-700">
                <strong>Note:</strong> Once submitted, you won't be able to edit this timesheet until your manager reviews it.
              </div>
            </div>
            <div className="px-6 py-4 bg-slate-50 border-t border-slate-200 flex justify-end gap-3">
              <button
                onClick={() => setShowSubmitModal(false)}
                className="px-4 py-2 text-slate-700 font-medium hover:bg-slate-200 rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleSubmit}
                disabled={submitting}
                className="px-6 py-2 bg-blue-600 text-white font-medium rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
              >
                {submitting ? (
                  <>
                    <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                    Submitting...
                  </>
                ) : (
                  'Submit for Approval'
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default WeeklyTimesheet;