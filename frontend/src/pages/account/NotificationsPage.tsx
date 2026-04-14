// src/pages/account/NotificationsPage.tsx
// Notification preferences — restyled to match design system

import React, { useState, useEffect } from 'react';
import { Bell, Mail, Clock, CheckCircle2, Laptop, Loader2, AlertCircle } from 'lucide-react';
import { cn } from '@/lib/design-system';

const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api';

// ── Types ─────────────────────────────────────────────────────────────────────

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

// ── Config ────────────────────────────────────────────────────────────────────

const EMAIL_PREFS: PrefItem[] = [
  { key: 'email_timesheet_reminders',    label: 'Daily timesheet reminders',    desc: "Morning reminder to review the previous day's timesheet",      icon: <Clock className="w-4 h-4" />        },
  { key: 'email_weekly_summary',         label: 'Weekly summary',               desc: 'Weekly email with your time summary and insights',             icon: <Mail className="w-4 h-4" />         },
  { key: 'email_approval_notifications', label: 'Approval notifications',       desc: 'Email when timesheets are approved or rejected',               icon: <CheckCircle2 className="w-4 h-4" /> },
];

const DESKTOP_PREFS: PrefItem[] = [
  { key: 'desktop_notifications', label: 'Desktop agent notifications', desc: 'Client reminders, idle alerts, and morning review prompts from the desktop agent', icon: <Laptop className="w-4 h-4" /> },
];

// ── Toggle ────────────────────────────────────────────────────────────────────

const Toggle: React.FC<{ checked: boolean; onChange: (v: boolean) => void; disabled?: boolean }> = ({ checked, onChange, disabled }) => (
  <button type="button" role="switch" aria-checked={checked}
    onClick={() => onChange(!checked)} disabled={disabled}
    className={cn(
      'relative inline-flex h-6 w-10 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200',
      'focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/30 focus-visible:ring-offset-2',
      'disabled:opacity-50 disabled:cursor-not-allowed',
      checked ? 'bg-primary' : 'bg-slate-200'
    )}>
    <span className={cn('pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow-sm ring-0 transition duration-200', checked ? 'translate-x-4' : 'translate-x-0')} />
    {disabled && <Loader2 className="absolute inset-0 m-auto w-3 h-3 text-white animate-spin" />}
  </button>
);

// ── Pref Row ──────────────────────────────────────────────────────────────────

const PrefRow: React.FC<{ item: PrefItem; checked: boolean; saving: boolean; onChange: (v: boolean) => void }> = ({ item, checked, saving, onChange }) => (
  <div className="flex items-center justify-between py-3.5 px-4 -mx-4 rounded-lg hover:bg-slate-50/60 transition-colors">
    <div className="flex items-start gap-3 flex-1 mr-6">
      <span className="mt-0.5 text-slate-400 shrink-0">{item.icon}</span>
      <div>
        <p className="text-sm font-semibold text-slate-700">{item.label}</p>
        <p className="text-xs text-slate-400 mt-0.5">{item.desc}</p>
      </div>
    </div>
    <Toggle checked={checked} onChange={onChange} disabled={saving} />
  </div>
);

// ── Section Card ──────────────────────────────────────────────────────────────

const SectionCard: React.FC<{
  icon: React.ReactNode;
  iconBg: string;
  title: string;
  desc: string;
  children: React.ReactNode;
}> = ({ icon, iconBg, title, desc, children }) => (
  <div className="bg-white rounded-xl border border-border/60 overflow-hidden">
    <div className="px-6 py-4 border-b border-border/50 flex items-center gap-3">
      <div className={cn('w-9 h-9 rounded-lg flex items-center justify-center shrink-0', iconBg)}>{icon}</div>
      <div>
        <h3 className="text-sm font-extrabold text-slate-700">{title}</h3>
        <p className="text-xs text-slate-400 mt-0.5">{desc}</p>
      </div>
    </div>
    <div className="px-6 py-2">
      <div className="divide-y divide-border/30">{children}</div>
    </div>
  </div>
);

// ── Main Component ────────────────────────────────────────────────────────────

export default function NotificationsPage() {
  const [prefs, setPrefs] = useState<NotificationPrefs>({
    email_timesheet_reminders:    true,
    email_weekly_summary:         true,
    email_approval_notifications: true,
    desktop_notifications:        true,
  });
  const [loading,    setLoading]    = useState(true);
  const [saving,     setSaving]     = useState<string | null>(null);
  const [error,      setError]      = useState<string | null>(null);
  const [orgSettings, setOrgSettings] = useState<{ auto_submit_timesheets: boolean } | null>(null);
  const [userRole,   setUserRole]   = useState<string>('member');
  const [savingOrg,  setSavingOrg]  = useState(false);

  useEffect(() => { loadPrefs(); }, []);

  const getToken = () => {
    const token = localStorage.getItem('auth_token');
    if (!token) { window.location.href = '/login'; return null; }
    return token;
  };

  const loadPrefs = async () => {
    try {
      const token = getToken(); if (!token) return;
      const res = await fetch(`${API_BASE}/user/preferences/`, { headers: { Authorization: `Bearer ${token}` } });
      if (res.status === 401 || res.status === 403) { window.location.href = '/login'; return; }
      if (res.ok) { const data = await res.json(); setPrefs(prev => ({ ...prev, ...data })); }

      try {
        const whoami = await fetch(`${API_BASE}/whoami/`, { headers: { Authorization: `Bearer ${token}` } });
        if (whoami.ok) { const who = await whoami.json(); setUserRole(who.role || 'member'); }
        const orgRes = await fetch(`${API_BASE}/settings/org/`, { headers: { Authorization: `Bearer ${token}` } });
        if (orgRes.ok) { const orgData = await orgRes.json(); setOrgSettings({ auto_submit_timesheets: orgData.auto_submit_timesheets ?? false }); }
      } catch {}
    } catch {}
    finally { setLoading(false); }
  };

  const updatePref = async (key: keyof NotificationPrefs, value: boolean) => {
    const token = getToken(); if (!token) return;
    setPrefs(prev => ({ ...prev, [key]: value }));
    setSaving(key); setError(null);
    try {
      const res = await fetch(`${API_BASE}/user/preferences/`, {
        method: 'PATCH',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ [key]: value }),
      });
      if (!res.ok) { setPrefs(prev => ({ ...prev, [key]: !value })); setError('Failed to save. Please try again.'); }
    } catch {
      setPrefs(prev => ({ ...prev, [key]: !value })); setError('Network error. Please try again.');
    } finally { setSaving(null); }
  };

  const updateOrgSetting = async (key: string, value: boolean) => {
    const token = getToken(); if (!token) return;
    setSavingOrg(true);
    try {
      const res = await fetch(`${API_BASE}/settings/org/`, {
        method: 'PATCH',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ [key]: value }),
      });
      if (res.ok) { setOrgSettings(prev => prev ? { ...prev, [key]: value } : prev); }
      else { setError('Failed to save org setting.'); }
    } catch { setError('Network error.'); }
    finally { setSavingOrg(false); }
  };

  if (loading) return (
    <div className="bg-white rounded-xl border border-border/60 flex items-center justify-center py-16">
      <Loader2 className="w-6 h-6 text-primary animate-spin" />
    </div>
  );

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="bg-white rounded-xl border border-border/60 px-6 py-5 flex items-center gap-4">
        <div className="w-10 h-10 bg-primary/10 rounded-xl flex items-center justify-center shrink-0">
          <Bell className="w-5 h-5 text-primary" />
        </div>
        <div>
          <h2 className="text-lg font-extrabold text-slate-800">Notifications</h2>
          <p className="text-xs text-slate-400 mt-0.5">Choose which notifications you'd like to receive</p>
        </div>
      </div>

      {error && (
        <div className="flex items-start gap-2.5 px-4 py-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
          <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" /> {error}
        </div>
      )}

      {/* Email notifications */}
      <SectionCard
        icon={<Mail className="w-4 h-4 text-primary" />}
        iconBg="bg-primary/10"
        title="Email Notifications"
        desc="Choose which emails you'd like to receive">
        {EMAIL_PREFS.map(item => (
          <PrefRow key={item.key} item={item} checked={prefs[item.key]} saving={saving === item.key} onChange={v => updatePref(item.key, v)} />
        ))}
      </SectionCard>

      {/* Desktop notifications */}
      <SectionCard
        icon={<Laptop className="w-4 h-4 text-slate-500" />}
        iconBg="bg-slate-100"
        title="Desktop Notifications"
        desc="Notifications from the TimeTracker desktop agent">
        {DESKTOP_PREFS.map(item => (
          <PrefRow key={item.key} item={item} checked={prefs[item.key]} saving={saving === item.key} onChange={v => updatePref(item.key, v)} />
        ))}
      </SectionCard>

      {/* Automation — owner/admin only */}
      {orgSettings && ['owner', 'admin'].includes(userRole) && (
        <SectionCard
          icon={<Clock className="w-4 h-4 text-amber-600" />}
          iconBg="bg-amber-50"
          title="Automation"
          desc="Organization-wide automation settings">
          <PrefRow
            item={{ key: 'email_timesheet_reminders', label: 'Auto-submit timesheets', desc: 'Automatically submit draft timesheets on Tuesday at 9am if not manually submitted', icon: <CheckCircle2 className="w-4 h-4" /> }}
            checked={orgSettings.auto_submit_timesheets}
            saving={savingOrg}
            onChange={v => updateOrgSetting('auto_submit_timesheets', v)}
          />
        </SectionCard>
      )}

      {/* Footer note */}
      <p className="text-xs text-slate-400 text-center px-4">
        Daily reminders are sent at 8:00 AM on weekdays. On Mondays, you'll be reminded to review Friday's timesheet.
      </p>
    </div>
  );
}