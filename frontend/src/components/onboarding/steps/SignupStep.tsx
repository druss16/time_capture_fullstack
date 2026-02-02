// src/components/onboarding/steps/SignupStep.tsx
/**
 * Step 1: Create Account - NOW WITH INDUSTRY SELECTOR
 */

import React, { useState, useEffect } from 'react';
import { Building2, Mail, Lock, User, ChevronRight, Briefcase } from 'lucide-react';
import { onboardingSignup, Organization, getIndustryOptions } from '../../../services/onboardingApi';

interface IndustryOption {
  value: string;
  label: string;
}

// Industry icons/descriptions for better UX
const INDUSTRY_INFO: Record<string, { icon: string; description: string }> = {
  cpa: { icon: '📊', description: 'Tax, audit, bookkeeping, and accounting services' },
  ai_consulting: { icon: '🤖', description: 'Software development, AI/ML, and tech consulting' },
  marketing: { icon: '📢', description: 'Digital marketing, content, design, and advertising' },
  legal: { icon: '⚖️', description: 'Legal research, document drafting, and litigation' },
  general: { icon: '💼', description: 'General professional services and consulting' },
};

interface SignupStepProps {
  onComplete: (data: { organization: Organization }) => void;
}

export default function SignupStep({ onComplete }: SignupStepProps) {
  const [formData, setFormData] = useState({
    firm_name: '',
    owner_name: '',
    email: '',
    password: '',
    industry_type: 'general',  // ✅ NEW
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [industries, setIndustries] = useState<IndustryOption[]>([]);
  const [loadingIndustries, setLoadingIndustries] = useState(true);

  // Load industry options on mount
  useEffect(() => {
    loadIndustries();
  }, []);

  const loadIndustries = async () => {
    try {
      const data = await getIndustryOptions();
      setIndustries(data.industries || []);
    } catch (err) {
      // Fallback to hardcoded options
      setIndustries([
        { value: 'cpa', label: 'CPA / Accounting Firm' },
        { value: 'ai_consulting', label: 'AI / Technology Consulting' },
        { value: 'marketing', label: 'Marketing / Creative Agency' },
        { value: 'legal', label: 'Law Firm / Legal Services' },
        { value: 'general', label: 'General Professional Services' },
      ]);
    } finally {
      setLoadingIndustries(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrors({});
    setLoading(true);

    try {
      const result = await onboardingSignup({
        firmName: formData.firm_name,      // camelCase for the API function
        ownerName: formData.owner_name,
        email: formData.email,
        password: formData.password,
        industryType: formData.industry_type,
      });

      if (result.ok) {
        // Store auth token
        localStorage.setItem('auth_token', result.token);
        onComplete({ organization: result.organization });
      } else {
        setErrors(result.errors || { general: 'Signup failed' });
      }
    } catch (err: any) {
      setErrors({ general: err.message || 'Network error' });
    } finally {
      setLoading(false);
    }
  };

  const selectedIndustryInfo = INDUSTRY_INFO[formData.industry_type] || INDUSTRY_INFO.general;

  return (
    <div className="bg-white rounded-2xl shadow-xl border border-slate-200 overflow-hidden">
      {/* Header */}
      <div className="bg-gradient-to-r from-teal-500 to-teal-600 px-6 py-8 text-white">
        <h2 className="text-2xl font-bold mb-2">Create Your Account</h2>
        <p className="text-teal-100">Set up your firm in under a minute</p>
      </div>

      {/* Form */}
      <form onSubmit={handleSubmit} className="p-6 space-y-5">
        {errors.general && (
          <div className="p-3 bg-red-50 border border-red-200 rounded-xl text-red-700 text-sm font-medium">
            {errors.general}
          </div>
        )}

        {/* Firm Name */}
        <div>
          <label className="block text-sm font-semibold text-slate-700 mb-1.5">
            Firm Name
          </label>
          <div className="relative">
            <Building2 className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-slate-400" />
            <input
              type="text"
              value={formData.firm_name}
              onChange={(e) => setFormData({ ...formData, firm_name: e.target.value })}
              placeholder="Smith & Associates CPA"
              className={`w-full pl-11 pr-4 py-3 border-2 rounded-xl font-medium transition-all
                ${errors.firm_name ? 'border-red-300 focus:border-red-500' : 'border-slate-200 focus:border-teal-500'}
                focus:outline-none focus:ring-2 focus:ring-teal-500/20`}
              required
            />
          </div>
          {errors.firm_name && <p className="mt-1 text-sm text-red-600">{errors.firm_name}</p>}
        </div>

        {/* ✅ NEW: Industry Type Selector */}
        <div>
          <label className="block text-sm font-semibold text-slate-700 mb-1.5">
            Industry Type
          </label>
          <div className="relative">
            <Briefcase className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-slate-400" />
            <select
              value={formData.industry_type}
              onChange={(e) => setFormData({ ...formData, industry_type: e.target.value })}
              disabled={loadingIndustries}
              className={`w-full pl-11 pr-4 py-3 border-2 rounded-xl font-medium transition-all appearance-none
                border-slate-200 focus:border-teal-500
                focus:outline-none focus:ring-2 focus:ring-teal-500/20
                ${loadingIndustries ? 'opacity-50' : ''}`}
            >
              {industries.map((ind) => (
                <option key={ind.value} value={ind.value}>
                  {ind.label}
                </option>
              ))}
            </select>
            <ChevronRight className="absolute right-3 top-1/2 -translate-y-1/2 w-5 h-5 text-slate-400 rotate-90" />
          </div>
          {/* Industry description */}
          <p className="mt-1.5 text-sm text-slate-500 flex items-center gap-2">
            <span>{selectedIndustryInfo.icon}</span>
            {selectedIndustryInfo.description}
          </p>
        </div>

        {/* Your Name */}
        <div>
          <label className="block text-sm font-semibold text-slate-700 mb-1.5">
            Your Name
          </label>
          <div className="relative">
            <User className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-slate-400" />
            <input
              type="text"
              value={formData.owner_name}
              onChange={(e) => setFormData({ ...formData, owner_name: e.target.value })}
              placeholder="John Smith"
              className="w-full pl-11 pr-4 py-3 border-2 border-slate-200 rounded-xl font-medium 
                focus:border-teal-500 focus:outline-none focus:ring-2 focus:ring-teal-500/20 transition-all"
            />
          </div>
        </div>

        {/* Email */}
        <div>
          <label className="block text-sm font-semibold text-slate-700 mb-1.5">
            Email Address
          </label>
          <div className="relative">
            <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-slate-400" />
            <input
              type="email"
              value={formData.email}
              onChange={(e) => setFormData({ ...formData, email: e.target.value })}
              placeholder="john@smithcpa.com"
              className={`w-full pl-11 pr-4 py-3 border-2 rounded-xl font-medium transition-all
                ${errors.email ? 'border-red-300 focus:border-red-500' : 'border-slate-200 focus:border-teal-500'}
                focus:outline-none focus:ring-2 focus:ring-teal-500/20`}
              required
            />
          </div>
          {errors.email && <p className="mt-1 text-sm text-red-600">{errors.email}</p>}
        </div>

        {/* Password */}
        <div>
          <label className="block text-sm font-semibold text-slate-700 mb-1.5">
            Password
          </label>
          <div className="relative">
            <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-slate-400" />
            <input
              type="password"
              value={formData.password}
              onChange={(e) => setFormData({ ...formData, password: e.target.value })}
              placeholder="At least 8 characters"
              className={`w-full pl-11 pr-4 py-3 border-2 rounded-xl font-medium transition-all
                ${errors.password ? 'border-red-300 focus:border-red-500' : 'border-slate-200 focus:border-teal-500'}
                focus:outline-none focus:ring-2 focus:ring-teal-500/20`}
              required
              minLength={8}
            />
          </div>
          {errors.password && <p className="mt-1 text-sm text-red-600">{errors.password}</p>}
        </div>

        {/* Submit */}
        <button
          type="submit"
          disabled={loading}
          className="w-full py-3.5 bg-teal-500 text-white font-bold rounded-xl
            hover:bg-teal-600 disabled:opacity-50 disabled:cursor-not-allowed
            transition-all flex items-center justify-center gap-2 shadow-lg shadow-teal-500/25"
        >
          {loading ? (
            <>
              <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              Creating Account...
            </>
          ) : (
            <>
              Create Account
              <ChevronRight className="w-5 h-5" />
            </>
          )}
        </button>

        <p className="text-center text-sm text-slate-500">
          Already have an account?{' '}
          <a href="/login" className="text-teal-600 font-semibold hover:underline">
            Sign in
          </a>
        </p>
      </form>
    </div>
  );
}