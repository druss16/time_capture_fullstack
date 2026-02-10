// src/pages/account/NotificationsPage.tsx
/**
 * Notification preferences — email and desktop notification toggles
 */

import React, { useState, useEffect } from 'react';
import {
  Bell,
  Mail,
  Clock,
  CheckCircle2,
  Laptop,
  Loader2,
  AlertCircle,
} from 'lucide-react';

const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api';

// ════════════════════════════════════════
// Types
// ════════════════════════════════════════
interface NotificationPrefs {
  email_timesheet_reminders: boolean;
  email_weekly_summary: boolean;
  email_approval_notifications: boolean;
  desktop_notifications: boolean;
}

interface PrefItem {
  key: keyof NotificationPrefs;
  label: string;
  desc: string;
  icon: React.ReactNode;
}

// ════════════════════════════════════════
// Config
// ════════════════════════════════════════
const EMAIL_PREFS: PrefItem[] = [
  {
    key: 'email_timesheet_reminders',
    label: 'Daily timesheet reminders',
    desc: "Email reminder each morning to review the previous day's timesheet",
    icon: <Clock className="w-[18px] h-[18px]" />,
  },
  {
    key: 'email_weekly_summary',
    label: 'Weekly summary',
    desc: 'Weekly email with your time summary and insights',
    icon: <Mail className="w-[18px] h-[18px]" />,
  },
  {
    key: 'email_approval_notifications',
    label: 'Approval notifications',
    desc: 'Email when timesheets are approved or rejected',
    icon: <CheckCircle2 className="w-[18px] h-[18px]" />,
  },
];

const DESKTOP_PREFS: PrefItem[] = [
  {
    key: 'desktop_notifications',
    label: 'Desktop agent notifications',
    desc: 'Client reminders, idle alerts, and morning review prompts from the desktop agent',
    icon: <Laptop className="w-[18px] h-[18px]" />,
  },
];

// ════════════════════════════════════════
// Toggle Component
// ════════════════════════════════════════
function Toggle({
  checked,
  onChange,
  disabled = false,
}: {
  checked: boolean;
  onChange: (val: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      disabled={disabled}
      className={`
        relative inline-flex h-7 w-12 shrink-0 cursor-pointer rounded-full
        border-2 border-transparent transition-colors duration-200 ease-in-out
        focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500/30 focus-visible:ring-offset-2
        disabled:opacity-50 disabled:cursor-not-allowed
        ${checked ? 'bg-teal-500' : 'bg-slate-300'}
      `}
    >
      <span
        className={`
          pointer-events-none inline-block h-6 w-6 transform rounded-full
          bg-white shadow-lg ring-0 transition duration-200 ease-in-out
          ${checked ? 'translate-x-5' : 'translate-x-0'}
        `}
      />
      {disabled && (
        <Loader2 className="absolute inset-0 m-auto w-3.5 h-3.5 text-white animate-spin" />
      )}
    </button>
  );
}

// ════════════════════════════════════════
// Main Component
// ════════════════════════════════════════
export default function NotificationsPage() {
  const [prefs, setPrefs] = useState<NotificationPrefs>({
    email_timesheet_reminders: true,
    email_weekly_summary: true,
    email_approval_notifications: true,
    desktop_notifications: true,
  });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadPrefs();
  }, []);

  const getToken = () => {
    const token = localStorage.getItem('auth_token');
    if (!token) {
      window.location.href = '/login';
      return null;
    }
    return token;
  };

  const loadPrefs = async () => {
    try {
      const token = getToken();
      if (!token) return;

      const res = await fetch(`${API_BASE}/user/preferences/`, {
        headers: { Authorization: `Bearer ${token}` },
      });

      if (res.status === 401 || res.status === 403) {
        window.location.href = '/login';
        return;
      }

      if (res.ok) {
        const data = await res.json();
        setPrefs((prev) => ({ ...prev, ...data }));
      }
    } catch {
      // Endpoint may not exist yet — use defaults
    } finally {
      setLoading(false);
    }
  };

  const updatePref = async (key: keyof NotificationPrefs, value: boolean) => {
    const token = getToken();
    if (!token) return;

    // Optimistic update
    setPrefs((prev) => ({ ...prev, [key]: value }));
    setSaving(key);
    setError(null);

    try {
      const res = await fetch(`${API_BASE}/user/preferences/`, {
        method: 'PATCH',
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ [key]: value }),
      });

      if (!res.ok) {
        // Revert
        setPrefs((prev) => ({ ...prev, [key]: !value }));
        setError('Failed to save. Please try again.');
      }
    } catch {
      setPrefs((prev) => ({ ...prev, [key]: !value }));
      setError('Network error. Please try again.');
    } finally {
      setSaving(null);
    }
  };

  // ── Render a group of toggles ──
  const renderGroup = (items: PrefItem[]) =>
    items.map((item) => (
      <div
        key={item.key}
        className="flex items-center justify-between py-4 px-4 -mx-4 rounded-xl hover:bg-slate-50 transition-colors"
      >
        <div className="flex items-start gap-3 flex-1 mr-4">
          <span className="mt-0.5 text-slate-400">{item.icon}</span>
          <div>
            <div className="text-sm font-bold text-slate-800">{item.label}</div>
            <div className="text-xs text-slate-500 mt-0.5">{item.desc}</div>
          </div>
        </div>
        <Toggle
          checked={prefs[item.key]}
          onChange={(val) => updatePref(item.key, val)}
          disabled={saving === item.key}
        />
      </div>
    ));

  if (loading) {
    return (
      <div className="bg-white rounded-2xl shadow-sm border-2 border-slate-200 p-8">
        <div className="flex items-center justify-center py-12">
          <Loader2 className="w-8 h-8 text-teal-600 animate-spin" />
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Error Banner */}
      {error && (
        <div className="p-4 bg-red-50 border-2 border-red-200 rounded-xl flex items-center gap-3">
          <AlertCircle className="w-5 h-5 text-red-500 shrink-0" />
          <p className="text-red-700 font-medium text-sm">{error}</p>
        </div>
      )}

      {/* ── Email Notifications ── */}
      <div className="bg-white rounded-2xl shadow-sm border-2 border-slate-200 overflow-hidden">
        <div className="px-8 py-6 border-b border-slate-100">
          <div className="flex items-center gap-4">
            <div className="w-11 h-11 bg-teal-100 rounded-xl flex items-center justify-center">
              <Mail className="w-5 h-5 text-teal-600" />
            </div>
            <div>
              <h3 className="text-lg font-bold text-slate-900">Email Notifications</h3>
              <p className="text-sm text-slate-500">Choose which emails you'd like to receive</p>
            </div>
          </div>
        </div>
        <div className="px-8 py-2">
          <div className="divide-y divide-slate-100">{renderGroup(EMAIL_PREFS)}</div>
        </div>
      </div>

      {/* ── Desktop Notifications ── */}
      <div className="bg-white rounded-2xl shadow-sm border-2 border-slate-200 overflow-hidden">
        <div className="px-8 py-6 border-b border-slate-100">
          <div className="flex items-center gap-4">
            <div className="w-11 h-11 bg-slate-100 rounded-xl flex items-center justify-center">
              <Laptop className="w-5 h-5 text-slate-600" />
            </div>
            <div>
              <h3 className="text-lg font-bold text-slate-900">Desktop Notifications</h3>
              <p className="text-sm text-slate-500">
                Notifications from the TimeTracker desktop agent
              </p>
            </div>
          </div>
        </div>
        <div className="px-8 py-2">
          <div className="divide-y divide-slate-100">{renderGroup(DESKTOP_PREFS)}</div>
        </div>
      </div>

      {/* ── Info Footer ── */}
      <div className="px-4 py-3">
        <p className="text-xs text-slate-400 text-center">
          Daily reminders are sent at 8:00 AM on weekdays. On Mondays, you'll be
          reminded to review Friday's timesheet.
        </p>
      </div>
    </div>
  );
}