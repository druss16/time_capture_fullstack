// src/components/onboarding/steps/BillingRatesStep.tsx

import React, { useState } from 'react';
import { setDefaultRate, skipRates, Organization } from '../../../services/onboardingApi';
import { DollarSign, Loader2, ArrowRight, Info } from 'lucide-react';

const COMMON_RATES = [125, 150, 175, 200, 250, 300];

interface BillingRatesStepProps {
  organization: Organization | null;
  onComplete: () => void;
  onSkip: () => void;
}

export default function BillingRatesStep({ organization, onComplete, onSkip }: BillingRatesStepProps) {
  const [rate, setRate] = useState('150');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleRateClick = (value: number) => {
    setRate(value.toString());
  };

  const handleSubmit = async () => {
    const numRate = parseFloat(rate);
    if (isNaN(numRate) || numRate < 0) {
      setError('Please enter a valid rate');
      return;
    }

    setLoading(true);
    setError(null);

    try {
      await setDefaultRate(numRate);
      onComplete();
    } catch (err) {
      const apiError = err as { message?: string };
      setError(apiError.message || 'Failed to save rate');
    } finally {
      setLoading(false);
    }
  };

  const handleSkip = async () => {
    try {
      await skipRates();
    } catch (err) {
      // Continue anyway
    }
    onSkip();
  };

  const numericRate = parseFloat(rate) || 0;

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-8">
      <div className="text-center mb-8">
        <div className="w-16 h-16 bg-green-100 rounded-full flex items-center justify-center mx-auto mb-4">
          <DollarSign className="w-8 h-8 text-green-600" />
        </div>
        <h2 className="text-2xl font-bold text-gray-900">Set Your Billing Rate</h2>
        <p className="text-gray-600 mt-2">
          This will be the default rate for calculating billable value
        </p>
      </div>

      {/* Rate Input */}
      <div className="mb-6">
        <label className="block text-sm font-medium text-gray-700 mb-2">
          Default Hourly Rate
        </label>
        <div className="relative">
          <span className="absolute left-4 top-1/2 -translate-y-1/2 text-gray-500 text-xl">$</span>
          <input
            type="number"
            value={rate}
            onChange={(e) => setRate(e.target.value)}
            min="0"
            step="5"
            className="w-full pl-10 pr-20 py-4 text-2xl font-semibold border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-center"
          />
          <span className="absolute right-4 top-1/2 -translate-y-1/2 text-gray-500">/hour</span>
        </div>
        {error && (
          <p className="mt-2 text-sm text-red-600">{error}</p>
        )}
      </div>

      {/* Quick Select Buttons */}
      <div className="mb-8">
        <p className="text-sm text-gray-500 mb-3">Quick select:</p>
        <div className="flex flex-wrap gap-2">
          {COMMON_RATES.map((r) => (
            <button
              key={r}
              onClick={() => handleRateClick(r)}
              className={`
                px-4 py-2 rounded-lg text-sm font-medium transition-colors
                ${rate === r.toString() 
                  ? 'bg-blue-600 text-white' 
                  : 'bg-gray-100 text-gray-700 hover:bg-gray-200'}
              `}
            >
              ${r}
            </button>
          ))}
        </div>
      </div>

      {/* Info Box */}
      <div className="bg-blue-50 rounded-lg p-4 mb-8 flex gap-3">
        <Info className="w-5 h-5 text-blue-600 mt-0.5 flex-shrink-0" />
        <div className="text-sm text-blue-800">
          <p className="font-medium mb-1">You can customize rates later</p>
          <p>
            Set different rates per team member, client, or task type from Settings.
            This is just your starting default.
          </p>
        </div>
      </div>

      {/* Example Calculation */}
      <div className="bg-gray-50 rounded-lg p-4 mb-8">
        <p className="text-sm font-medium text-gray-700 mb-3">Example monthly value:</p>
        <div className="grid grid-cols-3 gap-4 text-center">
          <div>
            <p className="text-2xl font-bold text-gray-900">
              ${(numericRate * 40).toLocaleString()}
            </p>
            <p className="text-xs text-gray-500">Per week</p>
          </div>
          <div>
            <p className="text-2xl font-bold text-gray-900">
              ${(numericRate * 160).toLocaleString()}
            </p>
            <p className="text-xs text-gray-500">Per month</p>
          </div>
          <div>
            <p className="text-2xl font-bold text-green-600">
              ${(numericRate * 2000).toLocaleString()}
            </p>
            <p className="text-xs text-gray-500">Per year</p>
          </div>
        </div>
        <p className="text-xs text-gray-400 text-center mt-2">
          Based on 40 billable hours/week
        </p>
      </div>

      {/* Action Buttons */}
      <div className="flex flex-col sm:flex-row gap-3">
        <button
          onClick={handleSubmit}
          disabled={loading}
          className="flex-1 py-3 px-4 bg-blue-600 hover:bg-blue-700 text-white font-medium rounded-lg transition-colors flex items-center justify-center gap-2 disabled:opacity-50"
        >
          {loading ? (
            <>
              <Loader2 className="w-5 h-5 animate-spin" />
              Saving...
            </>
          ) : (
            <>
              Save Rate
              <ArrowRight className="w-5 h-5" />
            </>
          )}
        </button>
        
        <button
          onClick={handleSkip}
          disabled={loading}
          className="py-3 px-4 bg-gray-100 hover:bg-gray-200 text-gray-700 font-medium rounded-lg transition-colors"
        >
          Use Default ($150)
        </button>
      </div>
    </div>
  );
}