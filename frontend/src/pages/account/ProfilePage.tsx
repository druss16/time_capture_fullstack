// src/pages/account/ProfilePage.tsx
// User profile settings — restyled to match design system

import React, { useState, useEffect } from 'react';
import { User, Mail, Save, Loader2, CheckCircle2, AlertCircle } from 'lucide-react';
import { cn } from '@/lib/design-system';

const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api';

interface UserProfile {
  id: number;
  username: string;
  email: string;
  first_name: string;
  last_name: string;
}

// ── Shared field label ────────────────────────────────────────────────────────

const Label: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <label className="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1.5">{children}</label>
);

const inputCls = 'w-full px-3 py-2.5 text-sm bg-white border border-border/60 rounded-lg font-medium text-slate-800 placeholder:text-slate-300 transition-all focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary/50';

// ── Main Component ────────────────────────────────────────────────────────────

export default function ProfilePage() {
  const [profile,   setProfile]   = useState<UserProfile | null>(null);
  const [loading,   setLoading]   = useState(true);
  const [saving,    setSaving]    = useState(false);
  const [error,     setError]     = useState<string | null>(null);
  const [success,   setSuccess]   = useState(false);
  const [firstName, setFirstName] = useState('');
  const [lastName,  setLastName]  = useState('');
  const [email,     setEmail]     = useState('');

  useEffect(() => { loadProfile(); }, []);

  const loadProfile = async () => {
    try {
      const token = localStorage.getItem('auth_token');
      if (!token) { window.location.href = '/login'; return; }
      const res = await fetch(`${API_BASE}/profile/`, { headers: { Authorization: `Bearer ${token}` } });
      if (!res.ok) throw new Error('Failed to load profile');
      const data = await res.json();
      setProfile(data);
      setFirstName(data.first_name || '');
      setLastName(data.last_name || '');
      setEmail(data.email || '');
    } catch (err: any) { setError(err.message); }
    finally { setLoading(false); }
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true); setError(null); setSuccess(false);
    try {
      const token = localStorage.getItem('auth_token');
      const res = await fetch(`${API_BASE}/profile/`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ first_name: firstName, last_name: lastName, email }),
      });
      if (!res.ok) { const d = await res.json(); throw new Error(d.error || 'Failed to update profile'); }
      setSuccess(true);
      setTimeout(() => setSuccess(false), 3000);
    } catch (err: any) { setError(err.message); }
    finally { setSaving(false); }
  };

  if (loading) return (
    <div className="bg-white rounded-xl border border-border/60 flex items-center justify-center py-16">
      <Loader2 className="w-6 h-6 text-primary animate-spin" />
    </div>
  );

  // Avatar initials
  const initials = `${firstName?.[0] || ''}${lastName?.[0] || ''}`.toUpperCase() || profile?.username?.[0]?.toUpperCase() || '?';

  return (
    <div className="space-y-4">
      {/* Header card */}
      <div className="bg-white rounded-xl border border-border/60 px-6 py-5">
        <div className="flex items-center gap-4">
          <div className="w-14 h-14 rounded-xl bg-primary flex items-center justify-center text-white text-lg font-bold shrink-0">
            {initials}
          </div>
          <div>
            <h2 className="text-lg font-extrabold text-slate-800">
              {firstName || lastName ? `${firstName} ${lastName}`.trim() : profile?.username}
            </h2>
            <p className="text-sm text-slate-400">{profile?.email}</p>
          </div>
        </div>
      </div>

      {/* Form card */}
      <div className="bg-white rounded-xl border border-border/60 overflow-hidden">
        <div className="px-6 py-4 border-b border-border/50">
          <h3 className="text-sm font-extrabold text-slate-700">Profile Information</h3>
          <p className="text-xs text-slate-400 mt-0.5">Update your personal details</p>
        </div>

        <form onSubmit={handleSave} className="px-6 py-5 space-y-5">
          {error && (
            <div className="flex items-start gap-2.5 px-4 py-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
              <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" /> {error}
            </div>
          )}
          {success && (
            <div className="flex items-start gap-2.5 px-4 py-3 bg-emerald-50 border border-emerald-200 rounded-lg text-sm text-emerald-700">
              <CheckCircle2 className="w-4 h-4 mt-0.5 shrink-0" /> Profile updated successfully!
            </div>
          )}

          {/* Username read-only */}
          <div>
            <Label>Username</Label>
            <input type="text" value={profile?.username || ''} disabled
              className={cn(inputCls, 'bg-slate-50 text-slate-400 cursor-not-allowed')} />
            <p className="text-xs text-slate-400 mt-1">Username cannot be changed</p>
          </div>

          {/* Name */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label>First Name</Label>
              <input type="text" value={firstName} onChange={e => setFirstName(e.target.value)}
                className={inputCls} placeholder="John" />
            </div>
            <div>
              <Label>Last Name</Label>
              <input type="text" value={lastName} onChange={e => setLastName(e.target.value)}
                className={inputCls} placeholder="Doe" />
            </div>
          </div>

          {/* Email */}
          <div>
            <Label>Email Address</Label>
            <div className="relative">
              <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-300 pointer-events-none" />
              <input type="email" value={email} onChange={e => setEmail(e.target.value)}
                className={cn(inputCls, 'pl-9')} placeholder="john@example.com" />
            </div>
          </div>
        </form>

        {/* Footer */}
        <div className="px-6 py-4 bg-slate-50/60 border-t border-border/50 flex justify-end">
          <button onClick={handleSave} disabled={saving}
            className="flex items-center gap-2 px-4 py-2 bg-primary text-white text-sm font-semibold rounded-lg hover:opacity-90 disabled:opacity-50 transition-all">
            {saving ? <><Loader2 className="w-4 h-4 animate-spin" /> Saving…</> : <><Save className="w-4 h-4" /> Save Changes</>}
          </button>
        </div>
      </div>
    </div>
  );
}