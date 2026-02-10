// src/pages/account/ProfilePage.tsx
/**
 * User profile settings - view and edit personal info + notification preferences
 */

import React, { useState, useEffect } from 'react';
import { User, Mail, Save, Loader2, CheckCircle2, AlertCircle, Bell, BellOff } from 'lucide-react';

const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api';

interface UserProfile {
  id: number;
  username: string;
  email: string;
  first_name: string;
  last_name: string;
}

interface NotificationPrefs {
  email_timesheet_reminders: boolean;
  email_weekly_summary: boolean;
  email_approval_notifications: boolean;
  desktop_notifications: boolean;
}

const PREF_ITEMS = [
  {
    key: 'email_timesheet_reminders' as const,
    label: 'Daily timesheet reminders',
    desc: 'Email reminder each morning to review the previous day\'s timesheet',
  },
  {
    key: 'email_weekly_summary' as const,
    label: 'Weekly summary',
    desc: 'Weekly email with your time summary',
  },
  {
    key: 'email_approval_notifications' as const,
    label: 'Approval notifications',
    desc: 'Email when timesheets are approved or rejected',
  },
  {
    key: 'desktop_notifications' as const,
    label: 'Desktop notifications',
    desc: 'Show notifications from the desktop agent',
  },
];

export default function ProfilePage() {
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  // Form state
  const [firstName, setFirstName] = useState('');
  const [lastName, setLastName] = useState('');
  const [email, setEmail] = useState('');

  // Notification preferences
  const [prefs, setPrefs] = useState<NotificationPrefs>({
    email_timesheet_reminders: true,
    email_weekly_summary: true,
    email_approval_notifications: true,
    desktop_notifications: true,
  });
  const [prefsSaving, setPrefsSaving] = useState<string | null>(null);

  useEffect(() => {
    loadProfile();
  }, []);

  const getToken = () => {
    const token = localStorage.getItem('auth_token');
    if (!token) {
      window.location.href = '/login';
      return null;
    }
    return token;
  };

  const loadProfile = async () => {
    try {
      const token = getToken();
      if (!token) return;

      // Fetch profile
      const response = await fetch(`${API_BASE}/profile/`, {
        headers: {
          'Authorization': `Bearer ${token}`,
        },
      });

      if (response.status === 401 || response.status === 403) {
        window.location.href = '/login';
        return;
      }

      if (!response.ok) throw new Error('Failed to load profile');

      const data = await response.json();
      setProfile(data);
      setFirstName(data.first_name || '');
      setLastName(data.last_name || '');
      setEmail(data.email || '');

      // Fetch notification preferences
      try {
        const prefsResponse = await fetch(`${API_BASE}/user/preferences/`, {
          headers: { 'Authorization': `Bearer ${token}` },
        });
        if (prefsResponse.ok) {
          const prefsData = await prefsResponse.json();
          setPrefs(prev => ({ ...prev, ...prefsData }));
        }
      } catch {
        // Preferences endpoint may not exist yet — use defaults
      }
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    setSuccess(false);

    try {
      const token = getToken();
      if (!token) return;

      const response = await fetch(`${API_BASE}/profile/`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        body: JSON.stringify({
          first_name: firstName,
          last_name: lastName,
          email: email,
        }),
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.error || 'Failed to update profile');
      }

      setSuccess(true);
      setTimeout(() => setSuccess(false), 3000);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  const updatePref = async (key: keyof NotificationPrefs, value: boolean) => {
    const token = getToken();
    if (!token) return;

    // Optimistic update
    setPrefs(prev => ({ ...prev, [key]: value }));
    setPrefsSaving(key);

    try {
      const response = await fetch(`${API_BASE}/user/preferences/`, {
        method: 'PATCH',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ [key]: value }),
      });

      if (!response.ok) {
        // Revert on failure
        setPrefs(prev => ({ ...prev, [key]: !value }));
      }
    } catch {
      // Revert on error
      setPrefs(prev => ({ ...prev, [key]: !value }));
    } finally {
      setPrefsSaving(null);
    }
  };

  if (loading) {
    return (
      <div className="bg-white rounded-2xl shadow-sm border-2 border-slate-200 p-8">
        <div className="flex items-center justify-center py-12">
          <Loader2 className="w-8 h-8 text-emerald-600 animate-spin" />
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* ── Profile Information ── */}
      <div className="bg-white rounded-2xl shadow-sm border-2 border-slate-200 p-8">
        <div className="flex items-center gap-4 mb-8">
          <div className="w-14 h-14 bg-emerald-100 rounded-2xl flex items-center justify-center">
            <User className="w-7 h-7 text-emerald-600" />
          </div>
          <div>
            <h2 className="text-xl font-bold text-slate-900">Profile Information</h2>
            <p className="text-slate-500 font-medium">Update your personal details</p>
          </div>
        </div>

        {error && (
          <div className="mb-6 p-4 bg-red-50 border-2 border-red-200 rounded-xl flex items-start gap-3">
            <AlertCircle className="w-5 h-5 text-red-500 mt-0.5" />
            <p className="text-red-700 font-medium">{error}</p>
          </div>
        )}

        {success && (
          <div className="mb-6 p-4 bg-emerald-50 border-2 border-emerald-200 rounded-xl flex items-start gap-3">
            <CheckCircle2 className="w-5 h-5 text-emerald-500 mt-0.5" />
            <p className="text-emerald-700 font-medium">Profile updated successfully!</p>
          </div>
        )}

        <form onSubmit={handleSave} className="space-y-6">
          {/* Username (read-only) */}
          <div>
            <label className="block text-sm font-bold text-slate-800 mb-2">
              Username
            </label>
            <input
              type="text"
              value={profile?.username || ''}
              disabled
              className="w-full px-4 py-3 bg-slate-50 border-2 border-slate-200 rounded-xl text-slate-500 font-medium"
            />
            <p className="mt-1.5 text-sm text-slate-500">Username cannot be changed</p>
          </div>

          {/* Name Fields */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-bold text-slate-800 mb-2">
                First Name
              </label>
              <input
                type="text"
                value={firstName}
                onChange={(e) => setFirstName(e.target.value)}
                className="w-full px-4 py-3 border-2 border-slate-200 rounded-xl font-medium transition-all focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-500 focus:outline-none"
                placeholder="John"
              />
            </div>
            <div>
              <label className="block text-sm font-bold text-slate-800 mb-2">
                Last Name
              </label>
              <input
                type="text"
                value={lastName}
                onChange={(e) => setLastName(e.target.value)}
                className="w-full px-4 py-3 border-2 border-slate-200 rounded-xl font-medium transition-all focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-500 focus:outline-none"
                placeholder="Doe"
              />
            </div>
          </div>

          {/* Email */}
          <div>
            <label className="block text-sm font-bold text-slate-800 mb-2">
              Email Address
            </label>
            <div className="relative">
              <Mail className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-slate-400" />
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full pl-12 pr-4 py-3 border-2 border-slate-200 rounded-xl font-medium transition-all focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-500 focus:outline-none"
                placeholder="john@example.com"
              />
            </div>
          </div>

          {/* Save Button */}
          <div className="pt-4">
            <button
              type="submit"
              disabled={saving}
              className="flex items-center gap-2 px-6 py-3 bg-emerald-600 hover:bg-emerald-700 text-white font-bold rounded-xl transition-all disabled:opacity-50 shadow-lg shadow-emerald-600/25"
            >
              {saving ? (
                <>
                  <Loader2 className="w-5 h-5 animate-spin" />
                  Saving...
                </>
              ) : (
                <>
                  <Save className="w-5 h-5" />
                  Save Changes
                </>
              )}
            </button>
          </div>
        </form>
      </div>

      {/* ── Notification Preferences ── */}
      <div className="bg-white rounded-2xl shadow-sm border-2 border-slate-200 p-8">
        <div className="flex items-center gap-4 mb-8">
          <div className="w-14 h-14 bg-teal-100 rounded-2xl flex items-center justify-center">
            <Bell className="w-7 h-7 text-teal-600" />
          </div>
          <div>
            <h2 className="text-xl font-bold text-slate-900">Notification Preferences</h2>
            <p className="text-slate-500 font-medium">Control how and when you receive notifications</p>
          </div>
        </div>

        <div className="space-y-1">
          {PREF_ITEMS.map((item) => (
            <div
              key={item.key}
              className="flex items-center justify-between py-4 px-4 -mx-4 rounded-xl hover:bg-slate-50 transition-colors"
            >
              <div className="flex-1 mr-4">
                <div className="text-sm font-bold text-slate-800">{item.label}</div>
                <div className="text-sm text-slate-500 mt-0.5">{item.desc}</div>
              </div>

              {/* Toggle Switch */}
              <button
                type="button"
                role="switch"
                aria-checked={prefs[item.key]}
                onClick={() => updatePref(item.key, !prefs[item.key])}
                disabled={prefsSaving === item.key}
                className={`
                  relative inline-flex h-7 w-12 shrink-0 cursor-pointer rounded-full 
                  border-2 border-transparent transition-colors duration-200 ease-in-out
                  focus:outline-none focus:ring-2 focus:ring-emerald-500/20 focus:ring-offset-2
                  disabled:opacity-50 disabled:cursor-not-allowed
                  ${prefs[item.key] ? 'bg-emerald-500' : 'bg-slate-300'}
                `}
              >
                <span
                  className={`
                    pointer-events-none inline-block h-6 w-6 transform rounded-full 
                    bg-white shadow-lg ring-0 transition duration-200 ease-in-out
                    ${prefs[item.key] ? 'translate-x-5' : 'translate-x-0'}
                  `}
                />
                {prefsSaving === item.key && (
                  <Loader2 className="absolute inset-0 m-auto w-3.5 h-3.5 text-white animate-spin" />
                )}
              </button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}