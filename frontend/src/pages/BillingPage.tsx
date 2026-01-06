// src/pages/BillingPage.tsx
/**
 * Billing page for subscription management.
 * Shows when trial expired or for managing existing subscription.
 */

import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  CreditCard,
  Check,
  Zap,
  Crown,
  ArrowRight,
  Clock,
  AlertTriangle,
  ExternalLink,
  Loader2,
  Shield,
  Users,
} from 'lucide-react';

const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api';

interface PricingTier {
  id: 'starter' | 'professional';
  name: string;
  price: number;
  priceId: string;
  description: string;
  popular?: boolean;
  features: string[];
}

const PRICING_TIERS: PricingTier[] = [
  {
    id: 'starter',
    name: 'Starter',
    price: 29.99,
    priceId: 'price_starter_monthly',
    description: 'Essential time tracking',
    features: [
      'Automatic time tracking',
      'AI-powered categorization',
      'Client & project management',
      'Weekly timesheets',
      'Team invites & roles',
      'Basic reporting',
    ],
  },
  {
    id: 'professional',
    name: 'Professional',
    price: 49.99,
    priceId: 'price_professional_monthly',
    description: 'Full suite with profitability',
    popular: true,
    features: [
      'Everything in Starter',
      'Cost & margin analysis',
      'Profitability dashboards',
      'Employee cost tracking',
      'Advanced analytics',
      'Priority support',
    ],
  },
];

export default function BillingPage() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [subscribing, setSubscribing] = useState(false);
  const [selectedTier, setSelectedTier] = useState<'starter' | 'professional'>('professional');
  const [seats, setSeats] = useState(1);
  const [subscription, setSubscription] = useState<any>(null);
  const [trialExpired, setTrialExpired] = useState(false);

  useEffect(() => {
    loadSubscriptionStatus();
  }, []);

  const loadSubscriptionStatus = async () => {
    try {
      const token = localStorage.getItem('auth_token');
      const response = await fetch(`${API_BASE}/billing/subscription/`, {
        headers: { 'Authorization': `Bearer ${token}` },
      });

      if (response.ok) {
        const data = await response.json();
        setSubscription(data.subscription);
        setTrialExpired(!data.trial?.active && !data.subscription);
        
        // Get team size for seat count
        if (data.organization?.team_size) {
          setSeats(data.organization.team_size);
        }
      } else if (response.status === 402) {
        setTrialExpired(true);
      }
    } catch (err) {
      console.error('Failed to load subscription:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleSubscribe = async () => {
    setSubscribing(true);
    try {
      const token = localStorage.getItem('auth_token');
      const selectedPlan = PRICING_TIERS.find(t => t.id === selectedTier)!;
      
      const response = await fetch(`${API_BASE}/billing/create-checkout-session/`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        body: JSON.stringify({
          price_id: selectedPlan.priceId,
          quantity: seats,
          success_url: `${window.location.origin}/daily?subscribed=true`,
          cancel_url: `${window.location.origin}/billing`,
        }),
      });

      const data = await response.json();
      
      if (data.checkout_url) {
        window.location.href = data.checkout_url;
      } else {
        alert('Failed to start checkout. Please try again.');
      }
    } catch (err) {
      console.error('Checkout error:', err);
      alert('Failed to start checkout. Please try again.');
    } finally {
      setSubscribing(false);
    }
  };

  const handleManageBilling = async () => {
    try {
      const token = localStorage.getItem('auth_token');
      const response = await fetch(`${API_BASE}/billing/portal/`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        body: JSON.stringify({
          return_url: `${window.location.origin}/billing`,
        }),
      });

      const data = await response.json();
      
      if (data.portal_url) {
        window.location.href = data.portal_url;
      }
    } catch (err) {
      console.error('Portal error:', err);
    }
  };

  const selectedPlan = PRICING_TIERS.find(t => t.id === selectedTier)!;
  const monthlyTotal = selectedPlan.price * seats;

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center">
        <Loader2 className="w-8 h-8 text-emerald-600 animate-spin" />
      </div>
    );
  }

  // Already subscribed - show management view
  if (subscription) {
    return (
      <div className="min-h-screen bg-slate-50 py-12">
        <div className="max-w-2xl mx-auto px-4">
          <div className="bg-white rounded-2xl shadow-sm border-2 border-slate-200 p-8">
            <div className="text-center mb-8">
              <div className="w-16 h-16 bg-emerald-100 rounded-2xl flex items-center justify-center mx-auto mb-4">
                <Check className="w-8 h-8 text-emerald-600" />
              </div>
              <h1 className="text-2xl font-bold text-slate-900">Active Subscription</h1>
              <p className="text-slate-600 mt-2 font-medium">
                You're on the {subscription.plan || 'Professional'} plan
              </p>
            </div>

            <div className="bg-emerald-50 border-2 border-emerald-200 rounded-xl p-6 mb-8">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-emerald-700 font-medium">Current Plan</p>
                  <p className="text-2xl font-bold text-emerald-900">{subscription.plan || 'Professional'}</p>
                </div>
                <div className="text-right">
                  <p className="text-sm text-emerald-700 font-medium">Seats</p>
                  <p className="text-2xl font-bold text-emerald-900">{subscription.quantity || 1}</p>
                </div>
              </div>
            </div>

            <button
              onClick={handleManageBilling}
              className="w-full py-4 px-6 bg-emerald-600 hover:bg-emerald-700 text-white font-bold rounded-xl transition-all flex items-center justify-center gap-2 shadow-lg shadow-emerald-600/25"
            >
              Manage Subscription
              <ExternalLink className="w-5 h-5" />
            </button>

            <p className="mt-4 text-center text-sm text-slate-500 font-medium">
              Update payment method, change plan, or cancel
            </p>

            <button
              onClick={() => navigate('/daily')}
              className="w-full mt-4 py-3 px-6 border-2 border-slate-200 hover:border-slate-300 text-slate-700 font-bold rounded-xl transition-all"
            >
              Back to Dashboard
            </button>
          </div>
        </div>
      </div>
    );
  }

  // Trial expired or no subscription - show pricing
  return (
    <div className="min-h-screen bg-slate-50 py-12">
      <div className="max-w-4xl mx-auto px-4">
        {/* Trial Expired Warning */}
        {trialExpired && (
          <div className="mb-8 p-4 bg-amber-50 border-2 border-amber-200 rounded-xl flex items-start gap-3">
            <AlertTriangle className="w-6 h-6 text-amber-500 mt-0.5" />
            <div>
              <p className="font-bold text-amber-900">Your trial has expired</p>
              <p className="text-amber-700 font-medium">
                Subscribe now to regain access to TimeTracker and all your data.
              </p>
            </div>
          </div>
        )}

        <div className="bg-white rounded-2xl shadow-sm border-2 border-slate-200 p-8">
          {/* Header */}
          <div className="text-center mb-8">
            <div className="w-16 h-16 bg-emerald-100 rounded-2xl flex items-center justify-center mx-auto mb-4">
              <CreditCard className="w-8 h-8 text-emerald-600" />
            </div>
            <h1 className="text-2xl font-bold text-slate-900">Choose Your Plan</h1>
            <p className="text-slate-600 mt-2 font-medium">
              Get unlimited access to automatic time tracking
            </p>
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
                    ? 'border-emerald-500 bg-emerald-50/50 shadow-lg' 
                    : 'border-slate-200 hover:border-slate-300'}
                `}
              >
                {tier.popular && (
                  <div className="absolute -top-3 left-1/2 -translate-x-1/2">
                    <span className="bg-emerald-600 text-white text-xs font-bold px-3 py-1 rounded-full">
                      MOST POPULAR
                    </span>
                  </div>
                )}

                <div className={`
                  absolute top-4 right-4 w-6 h-6 rounded-full border-2 flex items-center justify-center
                  ${selectedTier === tier.id ? 'border-emerald-500 bg-emerald-500' : 'border-slate-300'}
                `}>
                  {selectedTier === tier.id && <Check className="w-4 h-4 text-white" />}
                </div>

                <div className="flex items-center gap-3 mb-4">
                  <div className={`
                    w-12 h-12 rounded-xl flex items-center justify-center
                    ${tier.id === 'professional' ? 'bg-emerald-600 text-white' : 'bg-slate-100 text-slate-600'}
                  `}>
                    {tier.id === 'professional' ? <Crown className="w-6 h-6" /> : <Zap className="w-6 h-6" />}
                  </div>
                  <div>
                    <h3 className="text-lg font-bold text-slate-900">{tier.name}</h3>
                    <p className="text-sm text-slate-500 font-medium">{tier.description}</p>
                  </div>
                </div>

                <div className="mb-6">
                  <span className="text-4xl font-extrabold text-slate-900">${tier.price}</span>
                  <span className="text-slate-500 font-medium">/user/month</span>
                </div>

                <ul className="space-y-2">
                  {tier.features.map((feature, idx) => (
                    <li key={idx} className="flex items-center gap-2">
                      <Check className="w-4 h-4 text-emerald-500" />
                      <span className="text-sm text-slate-700 font-medium">{feature}</span>
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
                  className="w-8 h-8 rounded-lg border-2 border-slate-300 flex items-center justify-center hover:bg-slate-100 font-bold"
                >
                  -
                </button>
                <span className="w-12 text-center font-bold text-lg">{seats}</span>
                <button
                  onClick={() => setSeats(seats + 1)}
                  className="w-8 h-8 rounded-lg border-2 border-slate-300 flex items-center justify-center hover:bg-slate-100 font-bold"
                >
                  +
                </button>
              </div>
            </div>

            <div className="flex items-center justify-between pt-4 border-t-2 border-slate-200">
              <div>
                <p className="text-sm text-slate-500 font-medium">Monthly total</p>
                <p className="text-2xl font-extrabold text-slate-900">
                  ${monthlyTotal.toFixed(2)}<span className="text-sm font-medium text-slate-500">/month</span>
                </p>
              </div>
              <div className="text-right">
                <p className="text-sm text-emerald-600 font-bold">Save 20% with yearly billing</p>
              </div>
            </div>
          </div>

          {/* Subscribe Button */}
          <button
            onClick={handleSubscribe}
            disabled={subscribing}
            className="w-full py-4 px-6 bg-emerald-600 hover:bg-emerald-700 text-white font-bold rounded-xl transition-all flex items-center justify-center gap-2 shadow-lg shadow-emerald-600/25 disabled:opacity-50"
          >
            {subscribing ? (
              <Loader2 className="w-5 h-5 animate-spin" />
            ) : (
              <>
                Subscribe Now
                <ArrowRight className="w-5 h-5" />
              </>
            )}
          </button>

          {/* Trust Badges */}
          <div className="mt-6 flex items-center justify-center gap-6 text-sm text-slate-500">
            <div className="flex items-center gap-2">
              <Shield className="w-4 h-4" />
              <span className="font-medium">Secure payment</span>
            </div>
            <div className="flex items-center gap-2">
              <Clock className="w-4 h-4" />
              <span className="font-medium">Cancel anytime</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}