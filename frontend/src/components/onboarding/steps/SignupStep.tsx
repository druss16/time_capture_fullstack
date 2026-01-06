// src/components/onboarding/steps/SignupStep.tsx

import React, { useState, FormEvent, ChangeEvent } from 'react';
import { signup, Organization, ApiError } from '../../../services/onboardingApi';
import { Building2, Mail, Lock, User, AlertCircle, Loader2, Clock } from 'lucide-react';

interface FormData {
  firmName: string;
  email: string;
  password: string;
  confirmPassword: string;
  ownerName: string;
}

interface SignupStepProps {
  onComplete: (data: { organization: Organization }) => void;
}

export default function SignupStep({ onComplete }: SignupStepProps) {
  const [formData, setFormData] = useState<FormData>({
    firmName: '',
    email: '',
    password: '',
    confirmPassword: '',
    ownerName: '',
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);

  const handleChange = (e: ChangeEvent<HTMLInputElement>) => {
    const { name, value } = e.target;
    setFormData(prev => ({ ...prev, [name]: value }));
    if (errors[name]) {
      setErrors(prev => ({ ...prev, [name]: '' }));
    }
  };

  const validate = (): boolean => {
    const newErrors: Record<string, string> = {};
    
    if (!formData.firmName.trim()) {
      newErrors.firmName = 'Firm name is required';
    }
    
    if (!formData.email.trim()) {
      newErrors.email = 'Email is required';
    } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(formData.email)) {
      newErrors.email = 'Invalid email format';
    }
    
    if (!formData.password) {
      newErrors.password = 'Password is required';
    } else if (formData.password.length < 8) {
      newErrors.password = 'Password must be at least 8 characters';
    }
    
    if (formData.password !== formData.confirmPassword) {
      newErrors.confirmPassword = 'Passwords do not match';
    }
    
    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    
    if (!validate()) return;
    
    setLoading(true);
    setErrors({});
    
    try {
      const data = await signup({
        firmName: formData.firmName,
        email: formData.email,
        password: formData.password,
        ownerName: formData.ownerName,
      });
      
      onComplete({ organization: data.organization });
    } catch (err) {
      const apiError = err as ApiError;
      if (apiError.errors) {
        setErrors(apiError.errors);
      } else {
        setErrors({ general: apiError.error || 'Failed to create account' });
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="bg-white rounded-2xl shadow-sm border-2 border-slate-200 p-8">
      <div className="text-center mb-8">
        <div className="w-16 h-16 bg-emerald-100 rounded-2xl flex items-center justify-center mx-auto mb-4">
          <Clock className="w-8 h-8 text-emerald-600" />
        </div>
        <h2 className="text-2xl font-bold text-slate-900">Create Your Firm Account</h2>
        <p className="text-slate-600 mt-2 font-medium">
          Get started with automatic time tracking in 2 minutes
        </p>
      </div>

      {errors.general && (
        <div className="mb-6 p-4 bg-red-50 border-2 border-red-200 rounded-xl flex items-start gap-3">
          <AlertCircle className="w-5 h-5 text-red-500 mt-0.5" />
          <p className="text-red-700 font-medium">{errors.general}</p>
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-5">
        {/* Firm Name */}
        <div>
          <label className="block text-sm font-bold text-slate-800 mb-2">
            Firm Name *
          </label>
          <div className="relative">
            <Building2 className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-slate-400" />
            <input
              type="text"
              name="firmName"
              value={formData.firmName}
              onChange={handleChange}
              placeholder="Smith & Associates CPA"
              className={`
                w-full pl-10 pr-4 py-3 border-2 rounded-xl font-medium transition-all
                focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-500 focus:outline-none
                ${errors.firmName ? 'border-red-300' : 'border-slate-200'}
              `}
            />
          </div>
          {errors.firmName && (
            <p className="mt-1.5 text-sm text-red-600 font-medium">{errors.firmName}</p>
          )}
        </div>

        {/* Owner Name */}
        <div>
          <label className="block text-sm font-bold text-slate-800 mb-2">
            Your Name
          </label>
          <div className="relative">
            <User className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-slate-400" />
            <input
              type="text"
              name="ownerName"
              value={formData.ownerName}
              onChange={handleChange}
              placeholder="John Smith"
              className="w-full pl-10 pr-4 py-3 border-2 border-slate-200 rounded-xl font-medium transition-all focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-500 focus:outline-none"
            />
          </div>
        </div>

        {/* Email */}
        <div>
          <label className="block text-sm font-bold text-slate-800 mb-2">
            Email Address *
          </label>
          <div className="relative">
            <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-slate-400" />
            <input
              type="email"
              name="email"
              value={formData.email}
              onChange={handleChange}
              placeholder="john@smithcpa.com"
              className={`
                w-full pl-10 pr-4 py-3 border-2 rounded-xl font-medium transition-all
                focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-500 focus:outline-none
                ${errors.email ? 'border-red-300' : 'border-slate-200'}
              `}
            />
          </div>
          {errors.email && (
            <p className="mt-1.5 text-sm text-red-600 font-medium">{errors.email}</p>
          )}
        </div>

        {/* Password */}
        <div>
          <label className="block text-sm font-bold text-slate-800 mb-2">
            Password *
          </label>
          <div className="relative">
            <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-slate-400" />
            <input
              type="password"
              name="password"
              value={formData.password}
              onChange={handleChange}
              placeholder="At least 8 characters"
              className={`
                w-full pl-10 pr-4 py-3 border-2 rounded-xl font-medium transition-all
                focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-500 focus:outline-none
                ${errors.password ? 'border-red-300' : 'border-slate-200'}
              `}
            />
          </div>
          {errors.password && (
            <p className="mt-1.5 text-sm text-red-600 font-medium">{errors.password}</p>
          )}
        </div>

        {/* Confirm Password */}
        <div>
          <label className="block text-sm font-bold text-slate-800 mb-2">
            Confirm Password *
          </label>
          <div className="relative">
            <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-slate-400" />
            <input
              type="password"
              name="confirmPassword"
              value={formData.confirmPassword}
              onChange={handleChange}
              placeholder="Confirm your password"
              className={`
                w-full pl-10 pr-4 py-3 border-2 rounded-xl font-medium transition-all
                focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-500 focus:outline-none
                ${errors.confirmPassword ? 'border-red-300' : 'border-slate-200'}
              `}
            />
          </div>
          {errors.confirmPassword && (
            <p className="mt-1.5 text-sm text-red-600 font-medium">{errors.confirmPassword}</p>
          )}
        </div>

        {/* Submit */}
        <button
          type="submit"
          disabled={loading}
          className="w-full py-3.5 px-4 bg-emerald-600 hover:bg-emerald-700 text-white font-bold rounded-xl transition-all flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed shadow-lg shadow-emerald-600/25"
        >
          {loading ? (
            <>
              <Loader2 className="w-5 h-5 animate-spin" />
              Creating Account...
            </>
          ) : (
            'Create Account'
          )}
        </button>

        <p className="text-center text-sm text-slate-500 font-medium">
          Already have an account?{' '}
          <a href="/login" className="text-emerald-600 hover:text-emerald-700 font-semibold hover:underline">
            Sign in
          </a>
        </p>
      </form>
    </div>
  );
}