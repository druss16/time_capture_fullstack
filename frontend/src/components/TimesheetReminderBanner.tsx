// src/components/TimesheetReminderBanner.tsx
// Persistent banner reminding users to review yesterday's hours
// Won't go away until they click Review or Dismiss

import { useState, useEffect } from 'react';
import { 
  Clock, 
  X, 
  ChevronRight, 
  AlertCircle, 
  Briefcase,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';
import { safeFetchJson, API_BASE } from '@/lib/api';

interface UnreviewedDay {
  date: string;
  day_name: string;
  total_hours: number;
  block_count: number;
  has_unassigned: boolean;
  unassigned_count: number;
  top_clients: { name: string; hours: number }[];
}

interface ReviewStatus {
  needs_review: boolean;
  days: UnreviewedDay[];
  total_unreviewed_hours: number;
  total_unassigned: number;
}

export default function TimesheetReminderBanner() {
  const [data, setData] = useState<ReviewStatus | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    // Check if already dismissed today
    const dismissedDate = localStorage.getItem('timesheet_reminder_dismissed');
    const today = new Date().toISOString().split('T')[0];
    if (dismissedDate === today) {
      setDismissed(true);
      setLoading(false);
      return;
    }

    loadUnreviewedHours();
  }, []);

  const loadUnreviewedHours = async () => {
    try {
      const result = await safeFetchJson<ReviewStatus>(
        `${API_BASE}/timesheet/needs-review/`
      );
      setData(result);
    } catch (err) {
      console.error('Failed to check timesheet:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleDismiss = async () => {
    const today = new Date().toISOString().split('T')[0];
    localStorage.setItem('timesheet_reminder_dismissed', today);
    setDismissed(true);
    
    try {
      await safeFetchJson(`${API_BASE}/timesheet/dismiss-reminder/`, {
        method: 'POST',
        body: JSON.stringify({ date: today }),
      });
    } catch (err) {
      // Silent fail
    }
  };

  const handleReview = () => {
    window.location.href = '/timesheet';
  };

  if (loading || dismissed || !data?.needs_review) {
    return null;
  }

  const primaryDay = data.days[0];
  const hasMultipleDays = data.days.length > 1;

  return (
    <div className="bg-gradient-to-r from-amber-500 via-orange-500 to-red-500 text-white shadow-lg relative overflow-hidden">
      {/* Animated background pattern */}
      <div className="absolute inset-0 opacity-10">
        <div className="absolute inset-0" style={{
          backgroundImage: `repeating-linear-gradient(
            45deg,
            transparent,
            transparent 10px,
            rgba(255,255,255,0.1) 10px,
            rgba(255,255,255,0.1) 20px
          )`
        }} />
      </div>
      
      <div className="relative">
        {/* Main Banner */}
        <div className="max-w-7xl mx-auto px-4 py-3">
          <div className="flex items-center justify-between gap-4">
            <div className="flex items-center gap-3 flex-1 min-w-0">
              {/* Icon with pulse animation */}
              <div className="relative flex-shrink-0">
                <div className="w-10 h-10 bg-white/20 rounded-full flex items-center justify-center">
                  <Clock className="w-5 h-5" />
                </div>
                {data.days.length > 1 && (
                  <span className="absolute -top-1 -right-1 w-5 h-5 bg-red-600 rounded-full flex items-center justify-center text-xs font-bold animate-pulse">
                    {data.days.length}
                  </span>
                )}
              </div>
              
              {/* Message */}
              <div className="min-w-0">
                <p className="font-bold truncate">
                  {hasMultipleDays ? (
                    <>Review {data.total_unreviewed_hours.toFixed(1)} hours from the last {data.days.length} days</>
                  ) : (
                    <>Review your timesheet from {primaryDay.day_name}</>
                  )}
                </p>
                <p className="text-sm text-white/90 truncate">
                  {!hasMultipleDays && `${primaryDay.total_hours.toFixed(1)} hours tracked`}
                  {data.total_unassigned > 0 && (
                    <span className="inline-flex items-center gap-1 ml-2">
                      <AlertCircle className="w-3.5 h-3.5" />
                      {data.total_unassigned} unassigned
                    </span>
                  )}
                </p>
              </div>
            </div>

            {/* Actions */}
            <div className="flex items-center gap-2 flex-shrink-0">
              {hasMultipleDays && (
                <button
                  onClick={() => setExpanded(!expanded)}
                  className="flex items-center gap-1 px-3 py-2 text-sm font-medium hover:bg-white/10 rounded-lg transition-colors hidden sm:flex"
                >
                  {expanded ? 'Hide' : 'Details'}
                  {expanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                </button>
              )}
              <button
                onClick={handleReview}
                className="flex items-center gap-2 px-4 py-2 bg-white text-orange-600 font-bold rounded-lg hover:bg-orange-50 transition-colors text-sm shadow-lg"
              >
                Review Now
                <ChevronRight className="w-4 h-4" />
              </button>
              <button
                onClick={handleDismiss}
                className="p-2 hover:bg-white/20 rounded-lg transition-colors"
                title="Dismiss for today"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
          </div>
        </div>

        {/* Expanded Details */}
        {expanded && hasMultipleDays && (
          <div className="border-t border-white/20 bg-black/10">
            <div className="max-w-7xl mx-auto px-4 py-3">
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
                {data.days.map((day) => (
                  <div 
                    key={day.date}
                    className="bg-white/10 rounded-lg p-3 hover:bg-white/20 transition-colors cursor-pointer"
                    onClick={handleReview}
                  >
                    <div className="flex items-center justify-between mb-2">
                      <span className="font-bold text-sm">{day.day_name}</span>
                      <span className="text-lg font-extrabold">{day.total_hours.toFixed(1)}h</span>
                    </div>
                    <div className="text-xs text-white/80">
                      {day.block_count} blocks
                      {day.unassigned_count > 0 && (
                        <span className="ml-2 text-yellow-200">
                          • {day.unassigned_count} unassigned
                        </span>
                      )}
                    </div>
                    {day.top_clients.length > 0 && (
                      <div className="mt-2 flex flex-wrap gap-1">
                        {day.top_clients.slice(0, 2).map((client, i) => (
                          <span 
                            key={i}
                            className="inline-flex items-center gap-1 text-xs bg-white/10 px-2 py-0.5 rounded"
                          >
                            <Briefcase className="w-3 h-3" />
                            {client.name}: {client.hours.toFixed(1)}h
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}


// ============================================================================
// FLOATING NOTIFICATION (Alternative style - bottom right corner)
// ============================================================================

export function TimesheetReminderFloating() {
  const [data, setData] = useState<ReviewStatus | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const [loading, setLoading] = useState(true);
  const [minimized, setMinimized] = useState(false);

  useEffect(() => {
    const dismissedDate = localStorage.getItem('timesheet_reminder_dismissed');
    const today = new Date().toISOString().split('T')[0];
    if (dismissedDate === today) {
      setDismissed(true);
      setLoading(false);
      return;
    }
    loadData();
  }, []);

  const loadData = async () => {
    try {
      const result = await safeFetchJson<ReviewStatus>(
        `${API_BASE}/timesheet/needs-review/`
      );
      setData(result);
    } catch (err) {
      console.error('Failed to check timesheet:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleDismiss = () => {
    const today = new Date().toISOString().split('T')[0];
    localStorage.setItem('timesheet_reminder_dismissed', today);
    setDismissed(true);
  };

  if (loading || dismissed || !data?.needs_review) {
    return null;
  }

  if (minimized) {
    return (
      <button
        onClick={() => setMinimized(false)}
        className="fixed bottom-4 right-4 z-50 w-14 h-14 bg-gradient-to-br from-amber-500 to-orange-600 text-white rounded-full shadow-2xl flex items-center justify-center hover:scale-110 transition-transform"
      >
        <Clock className="w-6 h-6" />
        <span className="absolute -top-1 -right-1 w-5 h-5 bg-red-600 rounded-full flex items-center justify-center text-xs font-bold animate-pulse">
          {data.days.length}
        </span>
      </button>
    );
  }

  return (
    <div className="fixed bottom-4 right-4 z-50 w-80 bg-white rounded-2xl shadow-2xl border border-slate-200 overflow-hidden animate-in slide-in-from-bottom-4">
      {/* Header */}
      <div className="bg-gradient-to-r from-amber-500 to-orange-500 text-white px-4 py-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Clock className="w-5 h-5" />
            <span className="font-bold">Timesheet Reminder</span>
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={() => setMinimized(true)}
              className="p-1 hover:bg-white/20 rounded transition-colors text-lg leading-none"
              title="Minimize"
            >
              −
            </button>
            <button
              onClick={handleDismiss}
              className="p-1 hover:bg-white/20 rounded transition-colors"
              title="Dismiss for today"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="p-4">
        <p className="text-slate-700 font-medium mb-3">
          You have <span className="font-bold text-orange-600">{data.total_unreviewed_hours.toFixed(1)} hours</span> to review
        </p>

        <div className="space-y-2 mb-4">
          {data.days.slice(0, 3).map((day) => (
            <div key={day.date} className="flex items-center justify-between text-sm">
              <span className="text-slate-600">{day.day_name}</span>
              <div className="flex items-center gap-2">
                <span className="font-bold text-slate-800">{day.total_hours.toFixed(1)}h</span>
                {day.unassigned_count > 0 && (
                  <span className="text-xs text-amber-600 bg-amber-50 px-1.5 py-0.5 rounded">
                    {day.unassigned_count} unassigned
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>

        <a
          href="/timesheet"
          className="block w-full py-2.5 bg-gradient-to-r from-amber-500 to-orange-500 text-white text-center font-bold rounded-xl hover:opacity-90 transition-opacity"
        >
          Review Timesheet →
        </a>
      </div>
    </div>
  );
}