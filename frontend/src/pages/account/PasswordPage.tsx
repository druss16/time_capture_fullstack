// src/pages/account/PasswordPage.tsx
// Change password page — restyled to match design system

import React, { useState } from 'react';
import { KeyRound, Eye, EyeOff, Loader2, CheckCircle2, AlertCircle, ShieldCheck } from 'lucide-react';
import { cn } from '@/lib/design-system';

const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api';

const Label: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <label style={{ display: 'block', fontSize: '11px', fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', color: '#475569', marginBottom: '6px' }}>
    {children}
  </label>
);

const inputCls = 'w-full px-4 py-3 pr-11 text-sm font-medium text-slate-800 placeholder:text-slate-400 transition-all focus:outline-none';
const inputStyle: React.CSSProperties = {
  background: '#ffffff',
  border: '1.5px solid #cbd5e1',
  borderRadius: '10px',
  boxShadow: 'none',
};

export default function PasswordPage() {
  const [current,     setCurrent]     = useState('');
  const [newPass,     setNewPass]     = useState('');
  const [confirm,     setConfirm]     = useState('');
  const [showCurrent, setShowCurrent] = useState(false);
  const [showNew,     setShowNew]     = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [saving,      setSaving]      = useState(false);
  const [error,       setError]       = useState<string | null>(null);
  const [success,     setSuccess]     = useState(false);

  const strength = (() => {
    let s = 0;
    if (newPass.length >= 8)  s++;
    if (newPass.length >= 12) s++;
    if (/[a-z]/.test(newPass) && /[A-Z]/.test(newPass)) s++;
    if (/\d/.test(newPass))   s++;
    if (/[^a-zA-Z0-9]/.test(newPass)) s++;
    return s;
  })();

  const STRENGTH_LABELS = ['Very Weak', 'Weak', 'Fair', 'Good', 'Strong'];
  const STRENGTH_COLORS = ['bg-red-500', 'bg-orange-400', 'bg-amber-400', 'bg-emerald-400', 'bg-emerald-600'];

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null); setSuccess(false);
    if (!current)              { setError('Please enter your current password'); return; }
    if (newPass.length < 8)    { setError('New password must be at least 8 characters'); return; }
    if (newPass !== confirm)   { setError('New passwords do not match'); return; }
    if (current === newPass)   { setError('New password must differ from current password'); return; }

    setSaving(true);
    try {
      const token = localStorage.getItem('auth_token');
      const res = await fetch(`${API_BASE}/auth/change-password/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ current_password: current, new_password: newPass }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || data.detail || 'Failed to change password');
      setSuccess(true);
      setCurrent(''); setNewPass(''); setConfirm('');
    } catch (err: any) { setError(err.message); }
    finally { setSaving(false); }
  };

  const EyeToggle = ({ show, onToggle }: { show: boolean; onToggle: () => void }) => (
    <button type="button" onClick={onToggle}
      className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-300 hover:text-slate-500 transition-colors">
      {show ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
    </button>
  );

  const requirements = [
    { label: 'At least 8 characters',           met: newPass.length >= 8 },
    { label: 'Uppercase & lowercase letters',    met: /[a-z]/.test(newPass) && /[A-Z]/.test(newPass) },
    { label: 'At least one number',              met: /\d/.test(newPass) },
    { label: 'Special character (recommended)',  met: /[^a-zA-Z0-9]/.test(newPass) },
  ];

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="bg-white rounded-xl border border-slate-200 px-6 py-5 flex items-center gap-4">
        <div className="w-10 h-10 bg-teal-50 rounded-xl flex items-center justify-center shrink-0">
          <KeyRound className="w-5 h-5 text-teal-600" />
        </div>
        <div>
          <h2 className="text-lg font-extrabold text-slate-800">Change Password</h2>
          <p className="text-xs text-slate-400 mt-0.5">Update your account password</p>
        </div>
      </div>

      {/* Form */}
      <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
        <form onSubmit={handleSubmit}>
          <div className="px-6 py-5 space-y-5">
            {error && (
              <div className="flex items-start gap-2.5 px-4 py-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
                <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" /> {error}
              </div>
            )}
            {success && (
              <div className="flex items-start gap-2.5 px-4 py-3 bg-emerald-50 border border-emerald-200 rounded-lg text-sm text-emerald-700">
                <CheckCircle2 className="w-4 h-4 mt-0.5 shrink-0" />
                <div>
                  <p className="font-semibold">Password changed successfully!</p>
                  <p className="text-emerald-600 text-xs mt-0.5">Use your new password next time you log in.</p>
                </div>
              </div>
            )}

            {/* Current password */}
            <div>
              <Label>Current Password</Label>
              <div className="relative">
                <input type={showCurrent ? 'text' : 'password'} value={current} onChange={e => setCurrent(e.target.value)}
                  className={inputCls} style={inputStyle} placeholder="Enter current password" />
                <EyeToggle show={showCurrent} onToggle={() => setShowCurrent(v => !v)} />
              </div>
            </div>

            {/* New password */}
            <div>
              <Label>New Password</Label>
              <div className="relative">
                <input type={showNew ? 'text' : 'password'} value={newPass} onChange={e => setNewPass(e.target.value)}
                  className={inputCls} style={inputStyle} placeholder="Enter new password" />
                <EyeToggle show={showNew} onToggle={() => setShowNew(v => !v)} />
              </div>
              {/* Strength bar */}
              {newPass && (
                <div className="mt-2 space-y-1">
                  <div className="flex gap-1">
                    {[0,1,2,3,4].map(i => (
                      <div key={i} className={cn('h-1 flex-1 rounded-full transition-colors', i < strength ? STRENGTH_COLORS[strength - 1] : 'bg-slate-100')} />
                    ))}
                  </div>
                  <p className="text-[10px] text-slate-400">
                    Strength: <span className={cn('font-semibold', strength >= 4 ? 'text-emerald-600' : strength >= 3 ? 'text-amber-500' : 'text-red-500')}>
                      {STRENGTH_LABELS[strength - 1] || 'Too short'}
                    </span>
                  </p>
                </div>
              )}
            </div>

            {/* Confirm password */}
            <div>
              <Label>Confirm New Password</Label>
              <div className="relative">
                <input type={showConfirm ? 'text' : 'password'} value={confirm} onChange={e => setConfirm(e.target.value)}
                  className={cn(inputCls,
                    confirm && confirm !== newPass ? 'border-red-300 focus:border-red-400 focus:ring-red-500/20' :
                    confirm && confirm === newPass  ? 'border-emerald-300 focus:border-emerald-400 focus:ring-emerald-500/20' : ''
                  )}
                  style={{
                    ...inputStyle,
                    borderColor: confirm && confirm !== newPass ? '#fca5a5'
                      : confirm && confirm === newPass ? '#6ee7b7'
                      : '#cbd5e1',
                  }}
                  placeholder="Confirm new password" />
                <EyeToggle show={showConfirm} onToggle={() => setShowConfirm(v => !v)} />
              </div>
              {confirm && confirm !== newPass && <p className="text-xs text-red-500 font-medium mt-1">Passwords do not match</p>}
              {confirm && confirm === newPass  && <p className="text-xs text-emerald-500 font-medium mt-1 flex items-center gap-1"><CheckCircle2 className="w-3.5 h-3.5" /> Passwords match</p>}
            </div>

            {/* Requirements */}
            <div className="p-4 bg-slate-50 border border-slate-200 rounded-xl">
              <div className="flex items-start gap-2.5">
                <ShieldCheck className="w-4 h-4 text-slate-400 mt-0.5 shrink-0" />
                <div>
                  <p className="text-xs font-bold text-slate-700 mb-2">Password Requirements</p>
                  <ul className="space-y-1">
                    {requirements.map(r => (
                      <li key={r.label} className={cn('text-xs flex items-center gap-1.5 transition-colors', r.met ? 'text-emerald-600' : 'text-slate-400')}>
                        <CheckCircle2 className={cn('w-3 h-3 shrink-0', r.met ? 'text-emerald-500' : 'text-slate-200')} />
                        {r.label}
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            </div>
          </div>

          {/* Footer */}
          <div className="px-6 py-4 bg-slate-50 border-t border-slate-200 flex justify-end">
            <button type="submit" disabled={saving || !current || !newPass || newPass !== confirm}
              className="flex items-center gap-2 px-4 py-2 bg-teal-600 text-white text-sm font-semibold rounded-lg hover:bg-teal-700 disabled:opacity-40 transition-all">
              {saving ? <><Loader2 className="w-4 h-4 animate-spin" /> Changing…</> : <><KeyRound className="w-4 h-4" /> Change Password</>}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}