// src/pages/account/PasswordPage.tsx
/**
 * Change password page
 */

import React, { useState } from 'react';
import { KeyRound, Eye, EyeOff, Save, Loader2, CheckCircle2, AlertCircle, ShieldCheck } from 'lucide-react';

const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api';

export default function PasswordPage() {
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  
  const [showCurrent, setShowCurrent] = useState(false);
  const [showNew, setShowNew] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  // Password strength check
  const getPasswordStrength = (password: string) => {
    let strength = 0;
    if (password.length >= 8) strength++;
    if (password.length >= 12) strength++;
    if (/[a-z]/.test(password) && /[A-Z]/.test(password)) strength++;
    if (/\d/.test(password)) strength++;
    if (/[^a-zA-Z0-9]/.test(password)) strength++;
    return strength;
  };

  const passwordStrength = getPasswordStrength(newPassword);
  const strengthLabels = ['Very Weak', 'Weak', 'Fair', 'Good', 'Strong'];
  const strengthColors = ['bg-red-500', 'bg-orange-500', 'bg-yellow-500', 'bg-emerald-400', 'bg-emerald-600'];

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSuccess(false);

    // Validation
    if (!currentPassword) {
      setError('Please enter your current password');
      return;
    }

    if (newPassword.length < 8) {
      setError('New password must be at least 8 characters');
      return;
    }

    if (newPassword !== confirmPassword) {
      setError('New passwords do not match');
      return;
    }

    if (currentPassword === newPassword) {
      setError('New password must be different from current password');
      return;
    }

    setSaving(true);

    try {
      const token = localStorage.getItem('auth_token');
      const response = await fetch(`${API_BASE}/auth/change-password/`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        body: JSON.stringify({
          current_password: currentPassword,
          new_password: newPassword,
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || data.detail || 'Failed to change password');
      }

      setSuccess(true);
      setCurrentPassword('');
      setNewPassword('');
      setConfirmPassword('');
      
    } catch (err: any) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="bg-white rounded-2xl shadow-sm border-2 border-slate-200 p-8">
      <div className="flex items-center gap-4 mb-8">
        <div className="w-14 h-14 bg-emerald-100 rounded-2xl flex items-center justify-center">
          <KeyRound className="w-7 h-7 text-emerald-600" />
        </div>
        <div>
          <h2 className="text-xl font-bold text-slate-900">Change Password</h2>
          <p className="text-slate-500 font-medium">Update your account password</p>
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
          <div>
            <p className="text-emerald-700 font-bold">Password changed successfully!</p>
            <p className="text-emerald-600 text-sm font-medium mt-1">
              Your password has been updated. Use your new password next time you log in.
            </p>
          </div>
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-6">
        {/* Current Password */}
        <div>
          <label className="block text-sm font-bold text-slate-800 mb-2">
            Current Password
          </label>
          <div className="relative">
            <input
              type={showCurrent ? 'text' : 'password'}
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              className="w-full px-4 py-3 pr-12 border-2 border-slate-200 rounded-xl font-medium transition-all focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-500 focus:outline-none"
              placeholder="Enter current password"
            />
            <button
              type="button"
              onClick={() => setShowCurrent(!showCurrent)}
              className="absolute right-4 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
            >
              {showCurrent ? <EyeOff className="w-5 h-5" /> : <Eye className="w-5 h-5" />}
            </button>
          </div>
        </div>

        {/* New Password */}
        <div>
          <label className="block text-sm font-bold text-slate-800 mb-2">
            New Password
          </label>
          <div className="relative">
            <input
              type={showNew ? 'text' : 'password'}
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              className="w-full px-4 py-3 pr-12 border-2 border-slate-200 rounded-xl font-medium transition-all focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-500 focus:outline-none"
              placeholder="Enter new password"
            />
            <button
              type="button"
              onClick={() => setShowNew(!showNew)}
              className="absolute right-4 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
            >
              {showNew ? <EyeOff className="w-5 h-5" /> : <Eye className="w-5 h-5" />}
            </button>
          </div>
          
          {/* Password Strength Indicator */}
          {newPassword && (
            <div className="mt-3">
              <div className="flex gap-1 mb-1">
                {[0, 1, 2, 3, 4].map((i) => (
                  <div
                    key={i}
                    className={`h-1.5 flex-1 rounded-full transition-colors ${
                      i < passwordStrength ? strengthColors[passwordStrength - 1] : 'bg-slate-200'
                    }`}
                  />
                ))}
              </div>
              <p className="text-xs font-medium text-slate-500">
                Password strength: <span className={passwordStrength >= 4 ? 'text-emerald-600' : passwordStrength >= 3 ? 'text-yellow-600' : 'text-red-500'}>
                  {strengthLabels[passwordStrength - 1] || 'Too short'}
                </span>
              </p>
            </div>
          )}
        </div>

        {/* Confirm New Password */}
        <div>
          <label className="block text-sm font-bold text-slate-800 mb-2">
            Confirm New Password
          </label>
          <div className="relative">
            <input
              type={showConfirm ? 'text' : 'password'}
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              className={`w-full px-4 py-3 pr-12 border-2 rounded-xl font-medium transition-all focus:ring-2 focus:ring-emerald-500/20 focus:outline-none ${
                confirmPassword && confirmPassword !== newPassword
                  ? 'border-red-300 focus:border-red-500'
                  : confirmPassword && confirmPassword === newPassword
                  ? 'border-emerald-300 focus:border-emerald-500'
                  : 'border-slate-200 focus:border-emerald-500'
              }`}
              placeholder="Confirm new password"
            />
            <button
              type="button"
              onClick={() => setShowConfirm(!showConfirm)}
              className="absolute right-4 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
            >
              {showConfirm ? <EyeOff className="w-5 h-5" /> : <Eye className="w-5 h-5" />}
            </button>
          </div>
          {confirmPassword && confirmPassword !== newPassword && (
            <p className="mt-1.5 text-sm text-red-500 font-medium">Passwords do not match</p>
          )}
          {confirmPassword && confirmPassword === newPassword && (
            <p className="mt-1.5 text-sm text-emerald-500 font-medium flex items-center gap-1">
              <CheckCircle2 className="w-4 h-4" /> Passwords match
            </p>
          )}
        </div>

        {/* Password Requirements */}
        <div className="p-4 bg-slate-50 border-2 border-slate-200 rounded-xl">
          <div className="flex items-start gap-3">
            <ShieldCheck className="w-5 h-5 text-slate-400 mt-0.5" />
            <div>
              <p className="text-sm font-bold text-slate-800 mb-2">Password Requirements</p>
              <ul className="text-sm text-slate-600 space-y-1 font-medium">
                <li className={newPassword.length >= 8 ? 'text-emerald-600' : ''}>
                  • At least 8 characters
                </li>
                <li className={/[a-z]/.test(newPassword) && /[A-Z]/.test(newPassword) ? 'text-emerald-600' : ''}>
                  • Mix of uppercase & lowercase letters
                </li>
                <li className={/\d/.test(newPassword) ? 'text-emerald-600' : ''}>
                  • At least one number
                </li>
                <li className={/[^a-zA-Z0-9]/.test(newPassword) ? 'text-emerald-600' : ''}>
                  • At least one special character (recommended)
                </li>
              </ul>
            </div>
          </div>
        </div>

        {/* Save Button */}
        <div className="pt-4">
          <button
            type="submit"
            disabled={saving || !currentPassword || !newPassword || newPassword !== confirmPassword}
            className="flex items-center gap-2 px-6 py-3 bg-emerald-600 hover:bg-emerald-700 text-white font-bold rounded-xl transition-all disabled:opacity-50 disabled:cursor-not-allowed shadow-lg shadow-emerald-600/25"
          >
            {saving ? (
              <>
                <Loader2 className="w-5 h-5 animate-spin" />
                Changing Password...
              </>
            ) : (
              <>
                <KeyRound className="w-5 h-5" />
                Change Password
              </>
            )}
          </button>
        </div>
      </form>
    </div>
  );
}