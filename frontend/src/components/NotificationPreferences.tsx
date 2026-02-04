// src/components/NotificationPreferences.tsx
// User settings for controlling notification preferences

import { useState, useEffect } from 'react';
import {
  Bell,
  Mail,
  Monitor,
  Clock,
  CheckCircle2,
  AlertCircle,
  Loader2,
  BellOff,
  Calendar,
  FileText,
  ThumbsUp,
} from 'lucide-react';
import { safeFetchJson, API_BASE } from '@/lib/api';
import { cn } from '@/lib/design-system';

interface NotificationPrefs {
  email_timesheet_reminders: boolean;
  email_weekly_summary: boolean;
  email_approval_notifications: boolean;
  desktop_notifications: boolean;
  reminder_time: string;
}

export default function NotificationPreferences() {
  const [prefs, setPrefs] = useState<NotificationPrefs>({
    email_timesheet_reminders: true,
    email_weekly_summary: true,
    email_approval_notifications: true,
    desktop_notifications: true,
    reminder_time: '09:00',
  });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadPreferences();
  }, []);

  const loadPreferences = async () => {
    try {
      const data = await safeFetchJson<NotificationPrefs>(
        `${API_BASE}/notifications/preferences/`
      );
      setPrefs(data);
    } catch (err) {
      console.error('Failed to load notification preferences:', err);
    } finally {
      setLoading(false);
    }
  };

  const updatePreference = async (key: keyof NotificationPrefs, value: boolean | string) => {
    const newPrefs = { ...prefs, [key]: value };
    setPrefs(newPrefs);
    setSaving(true);
    setError(null);

    try {
      await safeFetchJson(`${API_BASE}/notifications/preferences/`, {
        method: 'PUT',
        body: JSON.stringify({ [key]: value }),
      });
      
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (err: any) {
      setError(err.message || 'Failed to save');
      // Revert on error
      setPrefs(prefs);
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="w-6 h-6 text-primary animate-spin" />
      </div>
    );
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-xl font-extrabold text-slate-900 flex items-center gap-2">
            <Bell className="w-5 h-5 text-primary" />
            Notifications
          </h2>
          <p className="text-sm text-slate-500 font-medium mt-1">
            Control how and when you receive reminders
          </p>
        </div>
        {saved && (
          <div className="flex items-center gap-2 text-emerald-600 animate-in fade-in">
            <CheckCircle2 className="w-4 h-4" />
            <span className="text-sm font-medium">Saved</span>
          </div>
        )}
      </div>

      {error && (
        <div className="mb-6 p-4 bg-red-50 border-2 border-red-200 rounded-xl flex items-center gap-2">
          <AlertCircle className="w-5 h-5 text-red-500" />
          <span className="text-red-700 font-medium">{error}</span>
        </div>
      )}

      <div className="space-y-6">
        {/* Email Notifications Section */}
        <div className="bg-slate-50 rounded-xl p-5">
          <h3 className="font-bold text-slate-800 flex items-center gap-2 mb-4">
            <Mail className="w-4 h-4 text-slate-600" />
            Email Notifications
          </h3>
          
          <div className="space-y-4">
            {/* Daily Timesheet Reminders */}
            <div className="flex items-center justify-between">
              <div className="flex items-start gap-3">
                <div className="w-10 h-10 bg-amber-100 rounded-lg flex items-center justify-center flex-shrink-0">
                  <Clock className="w-5 h-5 text-amber-600" />
                </div>
                <div>
                  <p className="font-bold text-slate-800">Daily Timesheet Reminders</p>
                  <p className="text-sm text-slate-500">
                    Get reminded to review yesterday's hours each morning
                  </p>
                </div>
              </div>
              <ToggleSwitch
                enabled={prefs.email_timesheet_reminders}
                onChange={(v) => updatePreference('email_timesheet_reminders', v)}
                disabled={saving}
              />
            </div>

            {/* Weekly Summary */}
            <div className="flex items-center justify-between pt-4 border-t border-slate-200">
              <div className="flex items-start gap-3">
                <div className="w-10 h-10 bg-blue-100 rounded-lg flex items-center justify-center flex-shrink-0">
                  <Calendar className="w-5 h-5 text-blue-600" />
                </div>
                <div>
                  <p className="font-bold text-slate-800">Weekly Summary</p>
                  <p className="text-sm text-slate-500">
                    Receive a summary of your time tracked each week
                  </p>
                </div>
              </div>
              <ToggleSwitch
                enabled={prefs.email_weekly_summary}
                onChange={(v) => updatePreference('email_weekly_summary', v)}
                disabled={saving}
              />
            </div>

            {/* Approval Notifications */}
            <div className="flex items-center justify-between pt-4 border-t border-slate-200">
              <div className="flex items-start gap-3">
                <div className="w-10 h-10 bg-emerald-100 rounded-lg flex items-center justify-center flex-shrink-0">
                  <ThumbsUp className="w-5 h-5 text-emerald-600" />
                </div>
                <div>
                  <p className="font-bold text-slate-800">Approval Notifications</p>
                  <p className="text-sm text-slate-500">
                    Get notified when your timesheets are approved or rejected
                  </p>
                </div>
              </div>
              <ToggleSwitch
                enabled={prefs.email_approval_notifications}
                onChange={(v) => updatePreference('email_approval_notifications', v)}
                disabled={saving}
              />
            </div>
          </div>
        </div>

        {/* Desktop Notifications Section */}
        <div className="bg-slate-50 rounded-xl p-5">
          <h3 className="font-bold text-slate-800 flex items-center gap-2 mb-4">
            <Monitor className="w-4 h-4 text-slate-600" />
            Desktop Notifications
          </h3>
          
          <div className="flex items-center justify-between">
            <div className="flex items-start gap-3">
              <div className="w-10 h-10 bg-purple-100 rounded-lg flex items-center justify-center flex-shrink-0">
                <Bell className="w-5 h-5 text-purple-600" />
              </div>
              <div>
                <p className="font-bold text-slate-800">Agent Notifications</p>
                <p className="text-sm text-slate-500">
                  Show desktop notifications from the TimeTracker agent when you log in
                </p>
              </div>
            </div>
            <ToggleSwitch
              enabled={prefs.desktop_notifications}
              onChange={(v) => updatePreference('desktop_notifications', v)}
              disabled={saving}
            />
          </div>
        </div>

        {/* Reminder Time */}
        <div className="bg-slate-50 rounded-xl p-5">
          <h3 className="font-bold text-slate-800 flex items-center gap-2 mb-4">
            <Clock className="w-4 h-4 text-slate-600" />
            Reminder Schedule
          </h3>
          
          <div className="flex items-center justify-between">
            <div className="flex items-start gap-3">
              <div className="w-10 h-10 bg-orange-100 rounded-lg flex items-center justify-center flex-shrink-0">
                <Clock className="w-5 h-5 text-orange-600" />
              </div>
              <div>
                <p className="font-bold text-slate-800">Preferred Reminder Time</p>
                <p className="text-sm text-slate-500">
                  When should we send your daily reminders?
                </p>
              </div>
            </div>
            <select
              value={prefs.reminder_time}
              onChange={(e) => updatePreference('reminder_time', e.target.value)}
              disabled={saving}
              className="border-2 border-slate-200 rounded-lg px-3 py-2 font-medium bg-white focus:border-primary focus:outline-none"
            >
              <option value="07:00">7:00 AM</option>
              <option value="08:00">8:00 AM</option>
              <option value="09:00">9:00 AM</option>
              <option value="10:00">10:00 AM</option>
              <option value="11:00">11:00 AM</option>
              <option value="12:00">12:00 PM</option>
            </select>
          </div>
        </div>

        {/* Info Box */}
        <div className="bg-blue-50 border-2 border-blue-200 rounded-xl p-4">
          <p className="text-sm text-blue-700 font-medium">
            💡 <strong>Tip:</strong> Keep daily reminders enabled to ensure you never forget
            to review your timesheet. Unreviewed time can lead to inaccurate billing!
          </p>
        </div>
      </div>
    </div>
  );
}


// ============================================================================
// Toggle Switch Component
// ============================================================================

interface ToggleSwitchProps {
  enabled: boolean;
  onChange: (value: boolean) => void;
  disabled?: boolean;
}

function ToggleSwitch({ enabled, onChange, disabled }: ToggleSwitchProps) {
  return (
    <button
      type="button"
      onClick={() => !disabled && onChange(!enabled)}
      disabled={disabled}
      className={cn(
        'relative inline-flex h-7 w-12 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2',
        enabled ? 'bg-primary' : 'bg-slate-200',
        disabled && 'opacity-50 cursor-not-allowed'
      )}
    >
      <span
        className={cn(
          'pointer-events-none inline-block h-6 w-6 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out',
          enabled ? 'translate-x-5' : 'translate-x-0'
        )}
      >
        {enabled ? (
          <Bell className="w-3.5 h-3.5 text-primary absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2" />
        ) : (
          <BellOff className="w-3.5 h-3.5 text-slate-400 absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2" />
        )}
      </span>
    </button>
  );
}