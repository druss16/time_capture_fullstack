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
  Star,
  Building2,
  ExternalLink,
  AlertTriangle,
  Sparkles
} from 'lucide-react';

const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api';

interface SubscriptionData {
  organization: {
    id: number;
    name: string;
    plan: string;
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

// Plan structure: Professional ($29.99) and Executive ($49.99)
const PLANS = [
  {
    id: 'professional',
    name: 'Professional',
    emoji: '⭐',
    price: 29.99,
    priceId: 'price_1SnryXKdcg3wPfHV3FymP9kw',
    icon: Star,
    features: [
      'Automatic time tracking',
      'AI-powered categorization',
      'Client & project management',
      'Weekly timesheets',
      'Timesheet approvals',
      'Team invites & roles',
      'Basic reporting',
      'Desktop app (Mac & Windows)',
      'Email support',
    ],
  },
  {
    id: 'executive',
    name: 'Executive',
    emoji: '💎',
    price: 49.99,
    priceId: 'price_1SnrzDKdcg3wPfHVydp72wac',
    icon: Crown,
    popular: true,
    features: [
      'Everything in Professional, plus:',
      'Client billing & invoicing',
      'Custom billing rates',
      'Employee cost tracking',
      'Profitability dashboards',
      'Client profitability reports',
      'Timesheet history & archive',
      'Advanced analytics',
      'Priority support',
      'API access',
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

  const handleSubscribe = async (priceId: string) => {
    setUpgrading(true);
    try {
      const token = localStorage.getItem('auth_token');
      const response = await fetch(`${API_BASE}/billing/create-checkout-session/`, {
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

  const handleUpgrade = async (priceId: string) => {
    setUpgrading(true);
    try {
      const token = localStorage.getItem('auth_token');
      const response = await fetch(`${API_BASE}/billing/create-checkout-session/`, {
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
          <Loader2 className="w-8 h-8 text-primary animate-spin" />
        </div>
      </div>
    );
  }

  const currentPlan = subscription?.organization?.plan || 'none';
  const hasActiveSubscription = subscription?.subscription?.status === 'active';
  
  // Check if user has no plan at all (not subscribed)
  const hasNoPlan = !hasActiveSubscription && (currentPlan === 'none' || !currentPlan);

  // Get plan display info
  const getPlanDisplay = (plan: string) => {
    switch (plan) {
      case 'executive':
        return { name: '💎 Executive', color: 'primary', icon: Crown };
      case 'professional':
        return { name: '⭐ Professional', color: 'amber', icon: Star };
      default:
        return { name: 'No Plan', color: 'slate', icon: Building2 };
    }
  };

  const planDisplay = getPlanDisplay(currentPlan);

  return (
    <div className="space-y-6">
      {/* Current Plan Card */}
      <div className="bg-white rounded-2xl shadow-sm border-2 border-slate-200 p-8">
        <div className="flex items-center gap-4 mb-6">
          <div className="w-14 h-14 bg-primary/10 rounded-2xl flex items-center justify-center">
            <CreditCard className="w-7 h-7 text-primary" />
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

        {/* No Plan Warning */}
        {hasNoPlan && (
          <div className="mb-6 p-4 bg-red-50 border-2 border-red-200 rounded-xl flex items-start gap-3">
            <AlertTriangle className="w-5 h-5 text-red-500 mt-0.5" />
            <div>
              <p className="font-bold text-red-800">No Active Subscription</p>
              <p className="text-sm text-red-700 font-medium mt-1">
                You don't have an active subscription. Subscribe to a plan below to access all features.
              </p>
            </div>
          </div>
        )}

        {/* Current Plan Status */}
        <div className="p-5 bg-slate-50 border-2 border-slate-200 rounded-xl mb-6">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <div className={`w-12 h-12 rounded-xl flex items-center justify-center ${
                currentPlan === 'executive' 
                  ? 'bg-primary/10 text-primary' 
                  : currentPlan === 'professional'
                  ? 'bg-amber-100 text-amber-600'
                  : 'bg-slate-200 text-slate-500'
              }`}>
                <planDisplay.icon className="w-6 h-6" />
              </div>
              <div>
                <p className="text-sm text-slate-500 font-medium">Current Plan</p>
                <p className="text-lg font-bold text-slate-900">
                  {planDisplay.name}
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

      {/* Show Plans if no subscription OR if on Professional (can upgrade to Executive) */}
      {(!hasActiveSubscription || currentPlan === 'professional') && (
        <div className="bg-white rounded-2xl shadow-sm border-2 border-slate-200 p-8">
          <h3 className="text-lg font-bold text-slate-900 mb-6">
            {hasActiveSubscription ? 'Upgrade Your Plan' : 'Choose a Plan'}
          </h3>

          <div className="grid md:grid-cols-2 gap-6">
            {PLANS.map((plan) => {
              const PlanIcon = plan.icon;
              const isCurrentPlan = currentPlan === plan.id;
              const canUpgrade = currentPlan === 'professional' && plan.id === 'executive';
              const canSubscribe = !hasActiveSubscription;

              return (
                <div
                  key={plan.id}
                  className={`
                    relative p-6 rounded-xl border-2 transition-all
                    ${plan.popular ? 'border-primary bg-primary/5' : 'border-slate-200'}
                    ${isCurrentPlan ? 'ring-2 ring-primary ring-offset-2' : ''}
                  `}
                >
                  {plan.popular && (
                    <span className="absolute -top-3 left-1/2 -translate-x-1/2 bg-primary text-white text-xs font-bold px-3 py-1 rounded-full">
                      MOST POPULAR
                    </span>
                  )}

                  <div className="flex items-center gap-3 mb-4">
                    <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${
                      plan.id === 'executive' ? 'bg-primary text-white' : 'bg-amber-100 text-amber-600'
                    }`}>
                      <PlanIcon className="w-5 h-5" />
                    </div>
                    <div>
                      <h4 className="font-bold text-slate-900">{plan.emoji} {plan.name}</h4>
                      {isCurrentPlan && (
                        <span className="text-xs bg-primary/10 text-primary px-2 py-0.5 rounded-full font-semibold">
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
                        <CheckCircle2 className={`w-4 h-4 mt-0.5 flex-shrink-0 ${
                          plan.id === 'executive' ? 'text-primary' : 'text-emerald-500'
                        }`} />
                        <span className="text-slate-600 font-medium">{feature}</span>
                      </li>
                    ))}
                  </ul>

                  {/* Subscribe button for users with no plan */}
                  {canSubscribe && (
                    <button
                      onClick={() => handleSubscribe(plan.priceId)}
                      disabled={upgrading}
                      className={`
                        w-full py-2.5 px-4 font-bold rounded-xl transition-all flex items-center justify-center gap-2
                        ${plan.popular 
                          ? 'bg-primary hover:opacity-90 text-white shadow-lg shadow-primary/25' 
                          : 'bg-slate-100 hover:bg-slate-200 text-slate-700'}
                      `}
                    >
                      {upgrading ? (
                        <Loader2 className="w-4 h-4 animate-spin" />
                      ) : (
                        <>
                          <CreditCard className="w-4 h-4" />
                          Subscribe Now
                        </>
                      )}
                    </button>
                  )}

                  {/* Upgrade button for Professional → Executive */}
                  {canUpgrade && (
                    <button
                      onClick={() => handleUpgrade(plan.priceId)}
                      disabled={upgrading}
                      className="w-full py-2.5 px-4 font-bold rounded-xl transition-all flex items-center justify-center gap-2 bg-primary hover:opacity-90 text-white shadow-lg shadow-primary/25"
                    >
                      {upgrading ? (
                        <Loader2 className="w-4 h-4 animate-spin" />
                      ) : (
                        <>
                          <Sparkles className="w-4 h-4" />
                          Upgrade to Executive
                        </>
                      )}
                    </button>
                  )}

                  {isCurrentPlan && (
                    <div className="text-center text-sm text-primary font-semibold">
                      ✓ Your current plan
                    </div>
                  )}

                  {/* Show disabled state for Professional card when user is already on Professional */}
                  {currentPlan === 'professional' && plan.id === 'professional' && !isCurrentPlan && (
                    <div className="text-center text-sm text-slate-400 font-medium">
                      Current plan
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Executive users - show they're on the top plan */}
      {hasActiveSubscription && currentPlan === 'executive' && (
        <div className="bg-primary/5 rounded-2xl border-2 border-primary/20 p-6">
          <div className="flex items-center gap-3">
            <div className="w-12 h-12 bg-primary rounded-xl flex items-center justify-center">
              <Crown className="w-6 h-6 text-white" />
            </div>
            <div>
              <p className="font-bold text-slate-900">You're on the Executive plan</p>
              <p className="text-sm text-slate-600 font-medium">
                You have access to all TimeTracker features.
              </p>
            </div>
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