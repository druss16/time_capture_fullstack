// src/components/onboarding/steps/PricingStep.tsx

import React, { useState } from 'react';
import { Check, Zap, Crown, ArrowRight, Shield, Clock, Users, BarChart3, Loader2, CreditCard } from 'lucide-react';

interface PricingStepProps {
  onComplete: () => void;
  onStartTrial: () => void;
  organizationId: number;
  userCount?: number;
}

interface PricingTier {
  id: 'starter' | 'professional';
  name: string;
  price: number;
  priceId: string;
  description: string;
  icon: React.ReactNode;
  popular?: boolean;
  features: string[];
  notIncluded?: string[];
}

const PRICING_TIERS: PricingTier[] = [
  {
    id: 'starter',
    name: 'Starter',
    price: 29.99,
    priceId: 'price_1SnryXKdcg3wPfHV3FymP9kw',
    description: 'Essential time tracking for growing firms',
    icon: <Zap className="w-6 h-6" />,
    features: [
      'Automatic time tracking',
      'AI-powered categorization',
      'Client & project management',
      'Weekly timesheets',
      'Team invites & roles',
      'Basic reporting',
      'Desktop app (Mac & Windows)',
      'Email support',
    ],
    notIncluded: [
      'Cost & margin analysis',
      'Profitability dashboards',
      'Advanced analytics',
    ],
  },
  {
    id: 'professional',
    name: 'Professional',
    price: 49.99,
    priceId: 'price_1SnrzDKdcg3wPfHVydp72wac',
    description: 'Full suite with profitability insights',
    icon: <Crown className="w-6 h-6" />,
    popular: true,
    features: [
      'Everything in Starter, plus:',
      'Cost & margin analysis',
      'Profitability dashboards',
      'Employee cost tracking',
      'Client profitability reports',
      'Advanced analytics',
      'Custom billing rates',
      'Priority support',
      'API access',
    ],
  },
];

const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api';

export default function PricingStep({ 
  onComplete, 
  onStartTrial,
  organizationId,
  userCount = 1 
}: PricingStepProps) {
  const [selectedTier, setSelectedTier] = useState<'starter' | 'professional'>('professional');
  const [loading, setLoading] = useState(false);
  const [seats, setSeats] = useState(userCount);

  const selectedPlan = PRICING_TIERS.find(t => t.id === selectedTier)!;
  const monthlyTotal = selectedPlan.price * seats;

  // Start trial WITH credit card - Stripe handles the 7-day free period
  const handleStartTrial = async () => {
    setLoading(true);
    try {
      const token = localStorage.getItem('auth_token');
      const response = await fetch(`${API_BASE}/billing/create-checkout-session/`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        body: JSON.stringify({
          price_id: selectedPlan.priceId,
          quantity: seats,
          trial_days: 7,  // ← Request 7-day trial
          success_url: `${window.location.origin}/onboarding?step=complete&session_id={CHECKOUT_SESSION_ID}`,
          cancel_url: `${window.location.origin}/onboarding?step=pricing`,
        }),
      });
      
      const data = await response.json();
      
      if (data.checkout_url) {
        window.location.href = data.checkout_url;
      } else {
        throw new Error('No checkout URL returned');
      }
    } catch (err) {
      console.error('Failed to create checkout session:', err);
      alert('Unable to start checkout. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  // Subscribe immediately - no trial, charge now
  const handleSubscribeNow = async () => {
    setLoading(true);
    try {
      const token = localStorage.getItem('auth_token');
      const response = await fetch(`${API_BASE}/billing/create-checkout-session/`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        body: JSON.stringify({
          price_id: selectedPlan.priceId,
          quantity: seats,
          trial_days: 0,  // ← No trial, charge immediately
          success_url: `${window.location.origin}/onboarding?step=complete&session_id={CHECKOUT_SESSION_ID}`,
          cancel_url: `${window.location.origin}/onboarding?step=pricing`,
        }),
      });
      
      const data = await response.json();
      
      if (data.checkout_url) {
        window.location.href = data.checkout_url;
      } else {
        throw new Error('No checkout URL returned');
      }
    } catch (err) {
      console.error('Failed to create checkout session:', err);
      alert('Unable to start checkout. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="bg-white rounded-2xl shadow-sm border-2 border-slate-200 p-8">
      {/* Header */}
      <div className="text-center mb-8">
        <div className="w-16 h-16 bg-emerald-100 rounded-2xl flex items-center justify-center mx-auto mb-4">
          <Crown className="w-8 h-8 text-emerald-600" />
        </div>
        <h2 className="text-2xl font-bold text-slate-900">Choose Your Plan</h2>
        <p className="text-slate-600 mt-2 font-medium">
          Start with a 7-day free trial • Cancel anytime
        </p>
      </div>

      {/* Trial Banner */}
      <div className="mb-8 p-4 bg-emerald-50 border-2 border-emerald-200 rounded-xl">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-emerald-100 rounded-full flex items-center justify-center">
              <Clock className="w-5 h-5 text-emerald-600" />
            </div>
            <div>
              <p className="font-bold text-emerald-900">7-Day Free Trial</p>
              <p className="text-sm text-emerald-700 font-medium">Full access to all features • You won't be charged until day 8</p>
            </div>
          </div>
          <Shield className="w-8 h-8 text-emerald-400" />
        </div>
      </div>

      {/* Pricing Cards */}
      <div className="grid md:grid-cols-2 gap-6 mb-8">
        {PRICING_TIERS.map((tier) => (
          <div
            key={tier.id}
            onClick={() => setSelectedTier(tier.id)}
            className={`
              relative cursor-pointer rounded-2xl border-2 p-6 transition-all
              ${selectedTier === tier.id 
                ? 'border-emerald-500 bg-emerald-50/50 shadow-lg shadow-emerald-500/10' 
                : 'border-slate-200 hover:border-slate-300 hover:shadow-md'}
            `}
          >
            {/* Popular Badge */}
            {tier.popular && (
              <div className="absolute -top-3 left-1/2 -translate-x-1/2">
                <span className="bg-emerald-600 text-white text-xs font-bold px-3 py-1 rounded-full shadow-lg">
                  MOST POPULAR
                </span>
              </div>
            )}

            {/* Selection Indicator */}
            <div className={`
              absolute top-4 right-4 w-6 h-6 rounded-full border-2 flex items-center justify-center transition-all
              ${selectedTier === tier.id ? 'border-emerald-500 bg-emerald-500' : 'border-slate-300'}
            `}>
              {selectedTier === tier.id && <Check className="w-4 h-4 text-white" />}
            </div>

            {/* Tier Header */}
            <div className="flex items-center gap-3 mb-4">
              <div className={`
                w-12 h-12 rounded-xl flex items-center justify-center
                ${tier.id === 'professional' 
                  ? 'bg-emerald-600 text-white' 
                  : 'bg-slate-100 text-slate-600'}
              `}>
                {tier.icon}
              </div>
              <div>
                <h3 className="text-lg font-bold text-slate-900">{tier.name}</h3>
                <p className="text-sm text-slate-500 font-medium">{tier.description}</p>
              </div>
            </div>

            {/* Price */}
            <div className="mb-6">
              <div className="flex items-baseline gap-1">
                <span className="text-4xl font-extrabold text-slate-900">${tier.price}</span>
                <span className="text-slate-500 font-medium">/user/month</span>
              </div>
              <p className="text-sm text-slate-500 mt-1 font-medium">Billed monthly after trial</p>
            </div>

            {/* Features */}
            <ul className="space-y-3">
              {tier.features.map((feature, idx) => (
                <li key={idx} className="flex items-start gap-2">
                  <Check className={`w-5 h-5 mt-0.5 flex-shrink-0 ${
                    tier.id === 'professional' ? 'text-emerald-500' : 'text-emerald-500'
                  }`} />
                  <span className="text-sm text-slate-700 font-medium">{feature}</span>
                </li>
              ))}
              {tier.notIncluded?.map((feature, idx) => (
                <li key={`not-${idx}`} className="flex items-start gap-2 opacity-50">
                  <span className="w-5 h-5 mt-0.5 flex-shrink-0 text-center text-slate-400">—</span>
                  <span className="text-sm text-slate-500 line-through font-medium">{feature}</span>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>

      {/* Seat Selection */}
      <div className="mb-8 p-5 bg-slate-50 rounded-xl border-2 border-slate-200">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <Users className="w-5 h-5 text-slate-600" />
            <span className="font-bold text-slate-900">Team Size</span>
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={() => setSeats(Math.max(1, seats - 1))}
              className="w-8 h-8 rounded-lg border-2 border-slate-300 flex items-center justify-center hover:bg-slate-100 transition-colors font-bold"
            >
              -
            </button>
            <span className="w-12 text-center font-bold text-lg">{seats}</span>
            <button
              onClick={() => setSeats(seats + 1)}
              className="w-8 h-8 rounded-lg border-2 border-slate-300 flex items-center justify-center hover:bg-slate-100 transition-colors font-bold"
            >
              +
            </button>
          </div>
        </div>

        {/* Summary */}
        <div className="flex items-center justify-between pt-4 border-t-2 border-slate-200">
          <div>
            <p className="text-sm text-slate-500 font-medium">Monthly total after trial</p>
            <p className="text-2xl font-extrabold text-slate-900">
              ${monthlyTotal.toFixed(2)}<span className="text-sm font-medium text-slate-500">/month</span>
            </p>
          </div>
          <div className="text-right">
            <p className="text-xs text-slate-500 font-medium">Annual pricing available</p>
            <p className="text-sm text-emerald-600 font-bold">Save 20% with yearly billing</p>
          </div>
        </div>
      </div>

      {/* CTA Buttons */}
      <div className="space-y-3">
        <button
          onClick={handleStartTrial}
          disabled={loading}
          className="w-full py-4 px-6 bg-emerald-600 hover:bg-emerald-700 text-white font-bold rounded-xl transition-all flex items-center justify-center gap-2 shadow-lg shadow-emerald-600/25 disabled:opacity-50"
        >
          {loading ? (
            <Loader2 className="w-5 h-5 animate-spin" />
          ) : (
            <>
              <CreditCard className="w-5 h-5" />
              Start 7-Day Free Trial
              <ArrowRight className="w-5 h-5" />
            </>
          )}
        </button>

        <button
          onClick={handleSubscribeNow}
          disabled={loading}
          className="w-full py-3 px-6 border-2 border-slate-200 hover:border-slate-300 text-slate-700 font-bold rounded-xl transition-all hover:bg-slate-50"
        >
          Subscribe Now & Skip Trial
        </button>
      </div>

      {/* Trust Badges */}
      <div className="mt-8 pt-6 border-t-2 border-slate-200">
        <div className="flex items-center justify-center gap-8 text-sm text-slate-500">
          <div className="flex items-center gap-2">
            <Shield className="w-4 h-4" />
            <span className="font-medium">Secure payment</span>
          </div>
          <div className="flex items-center gap-2">
            <Clock className="w-4 h-4" />
            <span className="font-medium">Cancel anytime</span>
          </div>
          <div className="flex items-center gap-2">
            <BarChart3 className="w-4 h-4" />
            <span className="font-medium">No hidden fees</span>
          </div>
        </div>
      </div>

      {/* Fine Print */}
      <p className="mt-4 text-center text-xs text-slate-400">
        Your card will be charged ${monthlyTotal.toFixed(2)}/month after the 7-day trial ends.
        <br />Cancel anytime before then and you won't be charged.
      </p>
    </div>
  );
}