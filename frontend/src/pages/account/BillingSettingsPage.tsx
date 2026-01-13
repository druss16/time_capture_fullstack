// src/pages/account/BillingSettingsPage.tsx
/**
 * Subscription & Billing page (Owner only)
 * Shows current plan, subscription status, seat management, and Stripe management
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
  Sparkles,
  Users,
  Plus,
  RefreshCw,
  X
} from 'lucide-react';

const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api';

interface SubscriptionData {
  organization: {
    id: number;
    name: string;
    plan: string;
    seat_count?: number;
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

interface SeatInfo {
  seat_count: number;
  members: number;
  pending_invites: number;
  total_allocated: number;
  seats_available: number;
  can_invite: boolean;
  plan: string;
}

type PlanId = 'professional' | 'executive';
type BillingInterval = 'monthly' | 'yearly';

type Plan = {
  id: PlanId;
  name: string;
  emoji: string;
  price: number;
  icon: any;
  popular?: boolean;
  features: string[];
};

const PLANS: Plan[] = [
  {
    id: 'professional',
    name: 'Professional',
    emoji: '⭐',
    price: 29.99,
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
  const [seatInfo, setSeatInfo] = useState<SeatInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [upgrading, setUpgrading] = useState(false);
  const [managingBilling, setManagingBilling] = useState(false);
  
  // Add seats modal state
  const [showAddSeats, setShowAddSeats] = useState(false);
  const [seatsToAdd, setSeatsToAdd] = useState(1);
  const [addingSeats, setAddingSeats] = useState(false);

  useEffect(() => {
    loadSubscription();
    loadSeatInfo();
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

  const loadSeatInfo = async () => {
    try {
      const token = localStorage.getItem('auth_token');
      const response = await fetch(`${API_BASE}/settings/seats/`, {
        headers: {
          'Authorization': `Bearer ${token}`,
        },
      });

      if (response.ok) {
        const data = await response.json();
        setSeatInfo(data);
      }
    } catch (err) {
      console.error('Failed to load seat info:', err);
    }
  };

  const handleSubscribe = async (plan: PlanId, interval: BillingInterval = 'monthly') => {
    setUpgrading(true);
    setError(null);

    try {
      const token = localStorage.getItem('auth_token');
      if (!token) {
        throw new Error('You are not logged in. Please sign in again.');
      }

      const response = await fetch(`${API_BASE}/billing/create-checkout-session/`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        body: JSON.stringify({
          plan,
          interval,
          quantity: 1,
          success_url: `${window.location.origin}/account/billing?success=true`,
          cancel_url: `${window.location.origin}/account/billing`,
        }),
      });

      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Failed to create checkout');
      if (!data.checkout_url) throw new Error('No checkout_url returned');

      window.location.href = data.checkout_url;
    } catch (err: any) {
      setError(err.message);
    } finally {
      setUpgrading(false);
    }
  };

  const handleUpgrade = async () => handleSubscribe('executive', 'monthly');

  const handleAddSeats = async () => {
    setAddingSeats(true);
    setError(null);

    try {
      const token = localStorage.getItem('auth_token');
      const response = await fetch(`${API_BASE}/settings/seats/add/`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        body: JSON.stringify({ seats: seatsToAdd }),
      });

      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Failed to add seats');

      setSuccess(`Added ${seatsToAdd} seat(s). New total: ${data.new_seat_count}`);
      setShowAddSeats(false);
      setSeatsToAdd(1);
      
      // Reload data
      loadSubscription();
      loadSeatInfo();
      
      setTimeout(() => setSuccess(null), 5000);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setAddingSeats(false);
    }
  };

  const handleManageBilling = async () => {
    setManagingBilling(true);
    setError(null);

    try {
      const token = localStorage.getItem('auth_token');
      if (!token) {
        throw new Error('You are not logged in. Please sign in again.');
      }

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
      if (!data.portal_url) throw new Error('No portal_url returned');

      window.location.href = data.portal_url;
    } catch (err: any) {
      setError(err.message);
    } finally {
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

  const hasActiveSubscription = subscription?.subscription?.status === 'active';
  const currentPlan = hasActiveSubscription 
    ? (subscription?.organization?.plan || 'none').toLowerCase()
    : 'none';
  const hasNoPlan = !hasActiveSubscription;

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
  const pricePerSeat = currentPlan === 'executive' ? 49.99 : 29.99;

  return (
    <div className="space-y-6">
      {/* Add Seats Modal */}
      {showAddSeats && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white rounded-2xl p-6 max-w-md w-full mx-4 shadow-2xl animate-in fade-in zoom-in-95">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-xl font-extrabold text-slate-900">Add Team Seats</h3>
              <button
                onClick={() => setShowAddSeats(false)}
                className="p-2 hover:bg-slate-100 rounded-lg transition-colors"
              >
                <X className="w-5 h-5 text-slate-500" />
              </button>
            </div>
            
            <div className="mb-6">
              <label className="block text-sm font-bold text-slate-700 mb-2">
                Number of seats to add
              </label>
              <input
                type="number"
                min="1"
                max="100"
                value={seatsToAdd}
                onChange={(e) => setSeatsToAdd(Math.max(1, parseInt(e.target.value) || 1))}
                className="w-full border-2 border-slate-200 rounded-xl px-4 py-3 text-lg font-bold text-center focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none"
              />
            </div>
            
            <div className="bg-slate-50 rounded-xl p-4 mb-6">
              <div className="flex justify-between text-sm font-medium text-slate-600">
                <span>Price per seat</span>
                <span>${pricePerSeat}/mo</span>
              </div>
              <div className="flex justify-between text-lg font-bold text-slate-900 mt-2">
                <span>Additional monthly cost</span>
                <span>${(seatsToAdd * pricePerSeat).toFixed(2)}</span>
              </div>
              <p className="text-xs text-slate-500 mt-2">
                You'll be charged a prorated amount for the current billing period.
              </p>
            </div>
            
            <div className="flex gap-3">
              <button
                onClick={() => setShowAddSeats(false)}
                className="flex-1 px-4 py-3 border-2 border-slate-200 rounded-xl font-bold text-slate-700 hover:bg-slate-100 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleAddSeats}
                disabled={addingSeats}
                className="flex-1 px-4 py-3 bg-primary text-white rounded-xl font-bold hover:opacity-90 transition-all flex items-center justify-center gap-2 shadow-lg shadow-primary/25"
              >
                {addingSeats ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Plus className="w-4 h-4" />
                )}
                Add {seatsToAdd} Seat(s)
              </button>
            </div>
          </div>
        </div>
      )}

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

        {success && (
          <div className="mb-6 p-4 bg-emerald-50 border-2 border-emerald-200 rounded-xl flex items-start gap-3">
            <CheckCircle2 className="w-5 h-5 text-emerald-500 mt-0.5" />
            <p className="text-emerald-700 font-medium">{success}</p>
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

        {/* Seat Usage Section - Only show for active subscriptions */}
        {hasActiveSubscription && seatInfo && (
          <div className="p-5 bg-slate-50 border-2 border-slate-200 rounded-xl mb-6">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-3">
                <Users className="w-5 h-5 text-slate-600" />
                <div>
                  <p className="text-sm text-slate-500 font-medium">Team Seats</p>
                  <p className="text-xl font-extrabold text-slate-900">
                    {seatInfo.members} / {seatInfo.seat_count} used
                  </p>
                </div>
              </div>
              <button
                onClick={() => setShowAddSeats(true)}
                className="flex items-center gap-2 px-4 py-2 border-2 border-primary text-primary font-bold rounded-xl hover:bg-primary/10 transition-colors"
              >
                <Plus className="w-4 h-4" />
                Add Seats
              </button>
            </div>
            
            {/* Progress bar */}
            <div className="h-2 bg-slate-200 rounded-full overflow-hidden mb-2">
              <div
                className={`h-full rounded-full transition-all ${
                  seatInfo.members >= seatInfo.seat_count 
                    ? 'bg-red-500' 
                    : seatInfo.members >= seatInfo.seat_count * 0.8 
                      ? 'bg-amber-500' 
                      : 'bg-emerald-500'
                }`}
                style={{ width: `${Math.min(100, (seatInfo.members / seatInfo.seat_count) * 100)}%` }}
              />
            </div>
            
            <div className="flex justify-between text-xs text-slate-500 font-medium">
              <span>{seatInfo.seats_available} seat(s) available</span>
              {seatInfo.pending_invites > 0 && (
                <span className="text-amber-600">{seatInfo.pending_invites} pending invite(s)</span>
              )}
            </div>
          </div>
        )}

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
                      onClick={() => handleSubscribe(plan.id)}
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
                      onClick={() => handleUpgrade()}
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