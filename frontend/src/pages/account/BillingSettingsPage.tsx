// src/pages/account/BillingSettingsPage.tsx
/**
 * Subscription & Billing page (Owner only)
 * Shows current plan, subscription status, and Stripe management
 */

import React, { useState, useEffect } from 'react';
import { 
  CreditCard, 
  Loader2, 
  CheckCircle2, 
  AlertCircle,
  Crown,
  Zap,
  Building2,
  Users,
  ExternalLink,
  Calendar,
  AlertTriangle
} from 'lucide-react';

const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api';

interface SubscriptionData {
  organization: {
    id: number;
    name: string;
    plan: string;
  };
  trial: {
    active: boolean;
    ends_at: string | null;
    days_left: number;
  };
  subscription: {
    id: string;
    status: string;
    current_period_end: number;
    cancel_at_period_end: boolean;
    plan: string | null;
    quantity: number;
  } | null;
  has_payment_method: boolean;
}

const PLANS = [
  {
    id: 'starter',
    name: 'Starter',
    price: 29.99,
    icon: Zap,
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
    icon: Crown,
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

export default function BillingSettingsPage() {
  const [subscription, setSubscription] = useState<SubscriptionData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [upgrading, setUpgrading] = useState(false);
  const [managingBilling, setManagingBilling] = useState(false);

  useEffect(() => {
    loadSubscription();
  }, []);

  const loadSubscription = async () => {
    try {
      const token = localStorage.getItem('auth_token');
      const response = await fetch(`${API_BASE}/billing/subscription/`, {
        headers: {
          'Authorization': `Bearer ${token}`,
        },
      });

      if (!response.ok) throw new Error('Failed to load subscription');

      const data = await response.json();
      setSubscription(data);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleUpgrade = async (priceId: string) => {
    setUpgrading(true);
    try {
      const token = localStorage.getItem('auth_token');
      const response = await fetch(`${API_BASE}/billing/checkout/`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        body: JSON.stringify({
          price_id: priceId,
          quantity: 1,
          success_url: `${window.location.origin}/account/billing?success=true`,
          cancel_url: `${window.location.origin}/account/billing`,
        }),
      });

      const data = await response.json();

      if (!response.ok) throw new Error(data.error || 'Failed to create checkout');

      // Redirect to Stripe Checkout
      window.location.href = data.checkout_url;
    } catch (err: any) {
      setError(err.message);
      setUpgrading(false);
    }
  };

  const handleManageBilling = async () => {
    setManagingBilling(true);
    try {
      const token = localStorage.getItem('auth_token');
      const response = await fetch(`${API_BASE}/billing/portal/`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        body: JSON.stringify({
          return_url: `${window.location.origin}/account/billing`,
        }),
      });

      const data = await response.json();

      if (!response.ok) throw new Error(data.error || 'Failed to open billing portal');

      // Redirect to Stripe Customer Portal
      window.location.href = data.portal_url;
    } catch (err: any) {
      setError(err.message);
      setManagingBilling(false);
    }
  };

  if (loading) {
    return (
      <div className="bg-white rounded-2xl shadow-sm border-2 border-slate-200 p-8">
        <div className="flex items-center justify-center py-12">
          <Loader2 className="w-8 h-8 text-emerald-600 animate-spin" />
        </div>
      </div>
    );
  }

  const currentPlan = subscription?.organization?.plan || 'trial';
  const isTrialActive = subscription?.trial?.active;
  const trialDaysLeft = subscription?.trial?.days_left || 0;
  const hasActiveSubscription = subscription?.subscription?.status === 'active';

  return (
    <div className="space-y-6">
      {/* Current Plan Card */}
      <div className="bg-white rounded-2xl shadow-sm border-2 border-slate-200 p-8">
        <div className="flex items-center gap-4 mb-6">
          <div className="w-14 h-14 bg-emerald-100 rounded-2xl flex items-center justify-center">
            <CreditCard className="w-7 h-7 text-emerald-600" />
          </div>
          <div>
            <h2 className="text-xl font-bold text-slate-900">Subscription & Billing</h2>
            <p className="text-slate-500 font-medium">Manage your plan and payment method</p>
          </div>
        </div>

        {error && (
          <div className="mb-6 p-4 bg-red-50 border-2 border-red-200 rounded-xl flex items-start gap-3">
            <AlertCircle className="w-5 h-5 text-red-500 mt-0.5" />
            <p className="text-red-700 font-medium">{error}</p>
          </div>
        )}

        {/* Trial Warning */}
        {isTrialActive && (
          <div className={`mb-6 p-4 rounded-xl flex items-start gap-3 ${
            trialDaysLeft <= 3 
              ? 'bg-red-50 border-2 border-red-200' 
              : 'bg-amber-50 border-2 border-amber-200'
          }`}>
            <AlertTriangle className={`w-5 h-5 mt-0.5 ${
              trialDaysLeft <= 3 ? 'text-red-500' : 'text-amber-500'
            }`} />
            <div>
              <p className={`font-bold ${
                trialDaysLeft <= 3 ? 'text-red-800' : 'text-amber-800'
              }`}>
                {trialDaysLeft} day{trialDaysLeft !== 1 ? 's' : ''} left in your trial
              </p>
              <p className={`text-sm font-medium mt-1 ${
                trialDaysLeft <= 3 ? 'text-red-700' : 'text-amber-700'
              }`}>
                Subscribe now to keep access to all features after your trial ends.
              </p>
            </div>
          </div>
        )}

        {/* Current Plan Status */}
        <div className="p-5 bg-slate-50 border-2 border-slate-200 rounded-xl mb-6">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <div className={`w-12 h-12 rounded-xl flex items-center justify-center ${
                currentPlan === 'professional' 
                  ? 'bg-emerald-100 text-emerald-600' 
                  : currentPlan === 'starter'
                  ? 'bg-blue-100 text-blue-600'
                  : 'bg-slate-200 text-slate-500'
              }`}>
                {currentPlan === 'professional' ? (
                  <Crown className="w-6 h-6" />
                ) : currentPlan === 'starter' ? (
                  <Zap className="w-6 h-6" />
                ) : (
                  <Building2 className="w-6 h-6" />
                )}
              </div>
              <div>
                <p className="text-sm text-slate-500 font-medium">Current Plan</p>
                <p className="text-lg font-bold text-slate-900 capitalize">
                  {currentPlan === 'trial' ? 'Free Trial' : currentPlan}
                </p>
              </div>
            </div>

            {hasActiveSubscription && (
              <div className="text-right">
                <p className="text-sm text-slate-500 font-medium">Next billing date</p>
                <p className="font-bold text-slate-900">
                  {subscription?.subscription?.current_period_end 
                    ? new Date(subscription.subscription.current_period_end * 1000).toLocaleDateString()
                    : '-'}
                </p>
              </div>
            )}
          </div>

          {subscription?.subscription?.cancel_at_period_end && (
            <div className="mt-4 p-3 bg-amber-50 border border-amber-200 rounded-lg">
              <p className="text-sm text-amber-800 font-medium">
                ⚠️ Your subscription will cancel at the end of the billing period.
              </p>
            </div>
          )}
        </div>

        {/* Manage Subscription Button */}
        {hasActiveSubscription && (
          <button
            onClick={handleManageBilling}
            disabled={managingBilling}
            className="w-full py-3 px-4 bg-slate-100 hover:bg-slate-200 text-slate-700 font-bold rounded-xl transition-all flex items-center justify-center gap-2"
          >
            {managingBilling ? (
              <Loader2 className="w-5 h-5 animate-spin" />
            ) : (
              <>
                <ExternalLink className="w-5 h-5" />
                Manage Subscription & Payment Method
              </>
            )}
          </button>
        )}
      </div>

      {/* Upgrade Plans */}
      {(!hasActiveSubscription || currentPlan === 'starter') && (
        <div className="bg-white rounded-2xl shadow-sm border-2 border-slate-200 p-8">
          <h3 className="text-lg font-bold text-slate-900 mb-6">
            {hasActiveSubscription ? 'Upgrade Your Plan' : 'Choose a Plan'}
          </h3>

          <div className="grid md:grid-cols-2 gap-6">
            {PLANS.map((plan) => {
              const PlanIcon = plan.icon;
              const isCurrentPlan = currentPlan === plan.id;
              const canSelect = !isCurrentPlan && (currentPlan === 'trial' || currentPlan === 'starter');

              return (
                <div
                  key={plan.id}
                  className={`
                    relative p-6 rounded-xl border-2 transition-all
                    ${plan.popular ? 'border-emerald-400 bg-emerald-50/50' : 'border-slate-200'}
                    ${isCurrentPlan ? 'ring-2 ring-emerald-500 ring-offset-2' : ''}
                  `}
                >
                  {plan.popular && (
                    <span className="absolute -top-3 left-1/2 -translate-x-1/2 bg-emerald-500 text-white text-xs font-bold px-3 py-1 rounded-full">
                      MOST POPULAR
                    </span>
                  )}

                  <div className="flex items-center gap-3 mb-4">
                    <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${
                      plan.id === 'professional' ? 'bg-emerald-100 text-emerald-600' : 'bg-blue-100 text-blue-600'
                    }`}>
                      <PlanIcon className="w-5 h-5" />
                    </div>
                    <div>
                      <h4 className="font-bold text-slate-900">{plan.name}</h4>
                      {isCurrentPlan && (
                        <span className="text-xs bg-emerald-100 text-emerald-700 px-2 py-0.5 rounded-full font-semibold">
                          Current Plan
                        </span>
                      )}
                    </div>
                  </div>

                  <div className="mb-4">
                    <span className="text-3xl font-extrabold text-slate-900">${plan.price}</span>
                    <span className="text-slate-500 font-medium">/user/month</span>
                  </div>

                  <ul className="space-y-2 mb-6">
                    {plan.features.map((feature, idx) => (
                      <li key={idx} className="flex items-start gap-2 text-sm">
                        <CheckCircle2 className="w-4 h-4 text-emerald-500 mt-0.5 flex-shrink-0" />
                        <span className="text-slate-600 font-medium">{feature}</span>
                      </li>
                    ))}
                  </ul>

                  {canSelect && (
                    <button
                      onClick={() => handleUpgrade(`price_${plan.id}_monthly`)}
                      disabled={upgrading}
                      className={`
                        w-full py-2.5 px-4 font-bold rounded-xl transition-all flex items-center justify-center gap-2
                        ${plan.popular 
                          ? 'bg-emerald-600 hover:bg-emerald-700 text-white shadow-lg shadow-emerald-600/25' 
                          : 'bg-slate-100 hover:bg-slate-200 text-slate-700'}
                      `}
                    >
                      {upgrading ? (
                        <Loader2 className="w-4 h-4 animate-spin" />
                      ) : (
                        <>
                          {currentPlan === 'trial' ? 'Subscribe' : 'Upgrade'}
                        </>
                      )}
                    </button>
                  )}

                  {isCurrentPlan && (
                    <div className="text-center text-sm text-emerald-600 font-semibold">
                      ✓ Your current plan
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Billing Info */}
      <div className="bg-white rounded-2xl shadow-sm border-2 border-slate-200 p-6">
        <div className="flex items-center gap-3 text-sm text-slate-500">
          <CreditCard className="w-4 h-4" />
          <span className="font-medium">
            Secure payments powered by Stripe. Cancel anytime.
          </span>
        </div>
      </div>
    </div>
  );
}