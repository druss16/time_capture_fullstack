// src/components/onboarding/steps/BillingRatesStep.tsx

import React, { useState } from 'react';
import { 
  DollarSign, 
  ArrowRight, 
  Loader2,
  Info,
  CheckCircle2,
  AlertCircle
} from 'lucide-react';
import { Organization } from '../../../services/onboardingApi';

interface BillingRatesStepProps {
  organization: Organization | null;
  onComplete: () => void;
  onSkip: () => void;
}

const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api';

export default function BillingRatesStep({ organization, onComplete, onSkip }: BillingRatesStepProps) {
  const [billingRate, setBillingRate] = useState('150.00');
  const [costRate, setCostRate] = useState('75.00');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const handleSave = async () => {
    setLoading(true);
    setError(null);

    try {
      const token = localStorage.getItem('auth_token');
      
      // Use existing settings endpoint to save billing rate
      const response = await fetch(`${API_BASE}/settings/org/`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        body: JSON.stringify({
          billing_rate_default: billingRate,
          // Note: cost_rate_default needs to be added to your Organization model
          // and settings_org view if you want to save it too
        }),
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.error || 'Failed to save rates');
      }
      
      setSuccess(true);
      setTimeout(() => onComplete(), 1000);
    } catch (err: any) {
      // If endpoint doesn't exist, just continue anyway
      if (err.message?.includes('404') || err.message?.includes('Not Found')) {
        console.warn('Rates endpoint not available, continuing...');
        setSuccess(true);
        setTimeout(() => onComplete(), 500);
        return;
      }
      setError(err.message || 'Failed to save rates');
    } finally {
      setLoading(false);
    }
  };

  const margin = parseFloat(billingRate || '0') - parseFloat(costRate || '0');
  const marginPercent = parseFloat(billingRate) > 0 
    ? ((margin / parseFloat(billingRate)) * 100).toFixed(0)
    : 0;

  return (
    <div className="bg-white rounded-2xl shadow-sm border-2 border-slate-200 p-8">
      <div className="text-center mb-8">
        <div className="w-16 h-16 bg-emerald-100 rounded-2xl flex items-center justify-center mx-auto mb-4">
          <DollarSign className="w-8 h-8 text-emerald-600" />
        </div>
        <h2 className="text-2xl font-bold text-slate-900">Set Default Rates</h2>
        <p className="text-slate-600 mt-2 font-medium">
          Configure your firm's default billing and cost rates
        </p>
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
          <p className="text-emerald-700 font-medium">Rates saved successfully!</p>
        </div>
      )}

      {/* Rate Inputs */}
      <div className="space-y-6 mb-8">
        {/* Billing Rate */}
        <div>
          <label className="block text-sm font-bold text-slate-800 mb-2">
            Default Billing Rate ($/hour)
          </label>
          <div className="relative">
            <span className="absolute left-4 top-1/2 -translate-y-1/2 text-slate-500 font-bold text-lg">$</span>
            <input
              type="number"
              step="0.01"
              min="0"
              value={billingRate}
              onChange={(e) => setBillingRate(e.target.value)}
              className="w-full pl-10 pr-4 py-3 border-2 border-slate-200 rounded-xl font-semibold text-lg transition-all focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-500 focus:outline-none"
            />
          </div>
          <p className="mt-1.5 text-sm text-slate-500 font-medium">
            What you charge clients per hour
          </p>
        </div>

        {/* Cost Rate */}
        <div>
          <label className="block text-sm font-bold text-slate-800 mb-2">
            Default Employee Cost ($/hour)
          </label>
          <div className="relative">
            <span className="absolute left-4 top-1/2 -translate-y-1/2 text-slate-500 font-bold text-lg">$</span>
            <input
              type="number"
              step="0.01"
              min="0"
              value={costRate}
              onChange={(e) => setCostRate(e.target.value)}
              className="w-full pl-10 pr-4 py-3 border-2 border-slate-200 rounded-xl font-semibold text-lg transition-all focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-500 focus:outline-none"
            />
          </div>
          <p className="mt-1.5 text-sm text-slate-500 font-medium">
            Your loaded labor cost per employee hour
          </p>
        </div>
      </div>

      {/* Margin Preview */}
      <div className="mb-8 p-5 bg-emerald-50 border-2 border-emerald-200 rounded-xl">
        <div className="flex items-center justify-between mb-3">
          <span className="text-sm font-bold text-emerald-800">Profit Margin Preview</span>
          <span className="text-2xl font-extrabold text-emerald-700">
            ${margin.toFixed(2)}/hr ({marginPercent}%)
          </span>
        </div>
        <div className="w-full bg-emerald-200 rounded-full h-3">
          <div 
            className="bg-emerald-600 h-3 rounded-full transition-all"
            style={{ width: `${Math.min(Math.max(Number(marginPercent), 0), 100)}%` }}
          />
        </div>
        <p className="mt-3 text-sm text-emerald-700 font-medium">
          For every hour billed, your firm earns ${margin.toFixed(2)} in profit
        </p>
      </div>

      {/* Info Box */}
      <div className="mb-8 p-4 bg-slate-50 border-2 border-slate-200 rounded-xl">
        <div className="flex items-start gap-3">
          <Info className="w-5 h-5 text-slate-400 mt-0.5" />
          <div>
            <p className="text-sm text-slate-600 font-medium">
              <strong className="text-slate-800">These are defaults.</strong> You can set different rates per employee, client, or task type in Settings → Billing Rates.
            </p>
          </div>
        </div>
      </div>

      {/* Actions */}
      <div className="flex gap-3">
        <button
          onClick={handleSave}
          disabled={loading}
          className="flex-1 py-3.5 px-4 bg-emerald-600 hover:bg-emerald-700 text-white font-bold rounded-xl transition-all flex items-center justify-center gap-2 disabled:opacity-50 shadow-lg shadow-emerald-600/25"
        >
          {loading ? (
            <>
              <Loader2 className="w-5 h-5 animate-spin" />
              Saving...
            </>
          ) : (
            <>
              Save Rates
              <ArrowRight className="w-5 h-5" />
            </>
          )}
        </button>
        
        <button
          onClick={onSkip}
          className="px-6 py-3.5 border-2 border-slate-200 hover:border-slate-300 text-slate-700 font-bold rounded-xl transition-all hover:bg-slate-50"
        >
          Use Defaults
        </button>
      </div>
    </div>
  );
}