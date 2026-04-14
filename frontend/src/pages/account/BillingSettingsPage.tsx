// src/pages/account/BillingSettingsPage.tsx
// Subscription & Billing page (Owner only) — restyled to match design system

import React, { useState, useEffect } from 'react';
import {
  CreditCard, Loader2, CheckCircle2, AlertCircle, Crown, Star,
  Building2, ExternalLink, AlertTriangle, Sparkles, Users,
  Plus, Minus, RefreshCw, X, ArrowDown, ArrowUp, Percent,
} from 'lucide-react';
import { cn } from '@/lib/design-system';

const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api';

// ── Types ─────────────────────────────────────────────────────────────────────

interface SubscriptionData {
  organization: { id: number; name: string; plan: string; seat_count?: number };
  subscription: {
    id: string; status: string; current_period_end: number;
    cancel_at_period_end: boolean; plan: string | null;
    quantity: number; interval?: string;
  } | null;
  has_payment_method: boolean;
  is_owner: boolean;
}

interface SeatInfo {
  seat_count: number; members: number; pending_invites: number;
  total_allocated: number; seats_available: number; can_invite: boolean; plan: string;
}

type PlanId = 'professional' | 'executive';
type BillingInterval = 'monthly' | 'yearly';

interface Plan {
  id: PlanId; name: string; emoji: string;
  monthlyPrice: number; yearlyPrice: number;
  icon: any; popular?: boolean; features: string[];
}

// ── Plan config ───────────────────────────────────────────────────────────────

const PLANS: Plan[] = [
  {
    id: 'professional', name: 'Professional', emoji: '⭐',
    monthlyPrice: 29.99, yearlyPrice: 23.99,
    icon: Star,
    features: [
      'Automatic time tracking',
      'AI-powered categorization',
      'Client & project management',
      'Weekly timesheets & approvals',
      'Team invites & roles',
      'Basic reporting',
      'Desktop app (Mac & Windows)',
      'Email support',
    ],
  },
  {
    id: 'executive', name: 'Executive', emoji: '💎',
    monthlyPrice: 49.99, yearlyPrice: 39.99,
    icon: Crown, popular: true,
    features: [
      'Everything in Professional, plus:',
      'Client billing & invoicing',
      'Custom billing rates',
      'Employee cost tracking',
      'Profitability dashboards',
      'Timesheet history & archive',
      'Advanced analytics',
      'Priority support',
      'API access',
    ],
  },
];

// ── Shared modal shell ────────────────────────────────────────────────────────

const Modal: React.FC<{ title: string; onClose: () => void; children: React.ReactNode; maxWidth?: string }> = ({
  title, onClose, children, maxWidth = 'max-w-md',
}) => (
  <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50 p-4">
    <div className={cn('bg-white rounded-2xl shadow-xl w-full overflow-hidden', maxWidth)}>
      <div className="px-6 py-4 border-b border-border/50 flex items-center justify-between">
        <h3 className="text-base font-extrabold text-slate-800">{title}</h3>
        <button onClick={onClose} className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors">
          <X className="w-4 h-4" />
        </button>
      </div>
      {children}
    </div>
  </div>
);

// ── Main Component ────────────────────────────────────────────────────────────

export default function BillingSettingsPage() {
  const [subscription,    setSubscription]    = useState<SubscriptionData | null>(null);
  const [seatInfo,        setSeatInfo]        = useState<SeatInfo | null>(null);
  const [loading,         setLoading]         = useState(true);
  const [error,           setError]           = useState<string | null>(null);
  const [success,         setSuccess]         = useState<string | null>(null);
  const [upgrading,       setUpgrading]       = useState(false);
  const [managingBilling, setManagingBilling] = useState(false);
  const [billingInterval, setBillingInterval] = useState<BillingInterval>('monthly');
  const [showAddSeats,    setShowAddSeats]    = useState(false);
  const [seatsToAdd,      setSeatsToAdd]      = useState(1);
  const [addingSeats,     setAddingSeats]     = useState(false);
  const [showManageSeats, setShowManageSeats] = useState(false);
  const [newSeatCount,    setNewSeatCount]    = useState(1);
  const [reducingSeats,   setReducingSeats]   = useState(false);
  const [showChangePlan,  setShowChangePlan]  = useState(false);
  const [changingPlan,    setChangingPlan]    = useState(false);

  useEffect(() => { loadSubscription(); loadSeatInfo(); }, []);

  const getToken = () => localStorage.getItem('auth_token') || '';

  const loadSubscription = async () => {
    try {
      const res = await fetch(`${API_BASE}/billing/subscription/`, { headers: { Authorization: `Bearer ${getToken()}` } });
      if (!res.ok) throw new Error('Failed to load subscription');
      const data = await res.json();
      setSubscription(data);
      if (data.subscription?.interval === 'year') setBillingInterval('yearly');
    } catch (err: any) { setError(err.message); }
    finally { setLoading(false); }
  };

  const loadSeatInfo = async () => {
    try {
      const res = await fetch(`${API_BASE}/settings/seats/`, { headers: { Authorization: `Bearer ${getToken()}` } });
      if (res.ok) { const data = await res.json(); setSeatInfo(data); setNewSeatCount(data.seat_count); }
    } catch {}
  };

  const handleSubscribe = async (plan: PlanId, interval: BillingInterval = 'monthly') => {
    setUpgrading(true); setError(null);
    try {
      const res = await fetch(`${API_BASE}/billing/create-checkout-session/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${getToken()}` },
        body: JSON.stringify({ plan, interval, quantity: 1, success_url: `${window.location.origin}/account/billing?success=true`, cancel_url: `${window.location.origin}/account/billing` }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed to create checkout');
      if (!data.checkout_url) throw new Error('No checkout_url returned');
      window.location.href = data.checkout_url;
    } catch (err: any) { setError(err.message); }
    finally { setUpgrading(false); }
  };

  const handleAddSeats = async () => {
    setAddingSeats(true); setError(null);
    try {
      const res = await fetch(`${API_BASE}/settings/seats/add/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${getToken()}` },
        body: JSON.stringify({ seats: seatsToAdd }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed to add seats');
      setSuccess(`Added ${seatsToAdd} seat(s). New total: ${data.new_seat_count}`);
      setShowAddSeats(false); setSeatsToAdd(1);
      loadSubscription(); loadSeatInfo();
      setTimeout(() => setSuccess(null), 5000);
    } catch (err: any) { setError(err.message); }
    finally { setAddingSeats(false); }
  };

  const handleReduceSeats = async () => {
    setReducingSeats(true); setError(null);
    try {
      const res = await fetch(`${API_BASE}/settings/seats/reduce/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${getToken()}` },
        body: JSON.stringify({ seats: newSeatCount }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.message || data.error || 'Failed to update seats');
      setSuccess(`Updated to ${data.new_seat_count} seat(s). You'll receive a prorated credit.`);
      setShowManageSeats(false);
      loadSubscription(); loadSeatInfo();
      setTimeout(() => setSuccess(null), 5000);
    } catch (err: any) { setError(err.message); }
    finally { setReducingSeats(false); }
  };

  const handleChangePlan = async (newPlan: PlanId) => {
    setChangingPlan(true); setError(null);
    try {
      const res = await fetch(`${API_BASE}/settings/plan/change/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${getToken()}` },
        body: JSON.stringify({ plan: newPlan }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed to change plan');
      setSuccess(`${newPlan === 'executive' ? 'Upgraded' : 'Downgraded'} to ${newPlan.charAt(0).toUpperCase() + newPlan.slice(1)} successfully!`);
      setShowChangePlan(false);
      loadSubscription(); loadSeatInfo();
      setTimeout(() => setSuccess(null), 5000);
    } catch (err: any) { setError(err.message); }
    finally { setChangingPlan(false); }
  };

  const handleManageBilling = async () => {
    setManagingBilling(true); setError(null);
    try {
      const res = await fetch(`${API_BASE}/billing/portal/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${getToken()}` },
        body: JSON.stringify({ return_url: `${window.location.origin}/account/billing` }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed to open billing portal');
      if (!data.portal_url) throw new Error('No portal_url returned');
      window.location.href = data.portal_url;
    } catch (err: any) { setError(err.message); }
    finally { setManagingBilling(false); }
  };

  const getPlanPrice = (plan: Plan) => billingInterval === 'yearly' ? plan.yearlyPrice : plan.monthlyPrice;
  const getYearlySavings = (plan: Plan) => (plan.monthlyPrice - plan.yearlyPrice) * 12;

  if (loading) return (
    <div className="bg-white rounded-xl border border-border/60 flex items-center justify-center py-16">
      <Loader2 className="w-6 h-6 text-primary animate-spin" />
    </div>
  );

  const hasActive     = subscription?.subscription?.status === 'active';
  const currentPlan   = hasActive ? (subscription?.organization?.plan || 'none').toLowerCase() : 'none';
  const currentInterval = subscription?.subscription?.interval === 'year' ? 'yearly' : 'monthly';
  const currentPlanData = PLANS.find(p => p.id === currentPlan);
  const pricePerSeat  = currentPlanData
    ? (currentInterval === 'yearly' ? currentPlanData.yearlyPrice : currentPlanData.monthlyPrice)
    : 29.99;

  const PlanIcon = currentPlan === 'executive' ? Crown : currentPlan === 'professional' ? Star : Building2;
  const planName = currentPlan === 'executive' ? '💎 Executive' : currentPlan === 'professional' ? '⭐ Professional' : 'No Plan';

  // ── Modals ────────────────────────────────────────────────────────────────

  const addSeatsModal = showAddSeats && (
    <Modal title="Add Team Seats" onClose={() => setShowAddSeats(false)}>
      <div className="p-6 space-y-5">
        <div>
          <label className="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1.5">Seats to add</label>
          <input type="number" min="1" max="100" value={seatsToAdd}
            onChange={e => setSeatsToAdd(Math.max(1, parseInt(e.target.value) || 1))}
            className="w-full px-3 py-2.5 text-center text-lg font-bold border border-border/60 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary/50" />
        </div>
        <div className="bg-slate-50 rounded-xl p-4 space-y-2 text-sm">
          <div className="flex justify-between text-slate-500">
            <span>Price per seat ({currentInterval})</span>
            <span className="font-semibold text-slate-700">${pricePerSeat}/mo</span>
          </div>
          <div className="flex justify-between font-bold text-slate-800 border-t border-border/40 pt-2 mt-2">
            <span>Additional cost</span>
            <span>{currentInterval === 'yearly'
              ? `$${(seatsToAdd * pricePerSeat * 12).toFixed(2)}/yr`
              : `$${(seatsToAdd * pricePerSeat).toFixed(2)}/mo`}
            </span>
          </div>
          <p className="text-xs text-slate-400">Prorated for the current billing period.</p>
        </div>
      </div>
      <div className="px-6 py-4 bg-slate-50/60 border-t border-border/50 flex gap-3">
        <button onClick={() => setShowAddSeats(false)}
          className="flex-1 py-2 text-sm font-semibold text-slate-600 bg-white border border-border/60 rounded-lg hover:bg-slate-50 transition-colors">
          Cancel
        </button>
        <button onClick={handleAddSeats} disabled={addingSeats}
          className="flex-1 py-2 text-sm font-semibold bg-primary text-white rounded-lg hover:opacity-90 disabled:opacity-50 flex items-center justify-center gap-2 transition-all">
          {addingSeats ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
          Add {seatsToAdd} Seat{seatsToAdd !== 1 ? 's' : ''}
        </button>
      </div>
    </Modal>
  );

  const manageSeatsModal = showManageSeats && seatInfo && (
    <Modal title="Manage Seats" onClose={() => setShowManageSeats(false)}>
      <div className="p-6 space-y-5">
        {/* Usage summary */}
        <div className="bg-slate-50 rounded-xl p-4 space-y-2 text-sm">
          {[
            ['Current seats',      seatInfo.seat_count,       'text-slate-700'],
            ['Active members',     seatInfo.members,          'text-slate-700'],
            ['Minimum required',   seatInfo.total_allocated,  'text-primary font-bold'],
          ].map(([label, val, cls]) => (
            <div key={String(label)} className="flex justify-between">
              <span className="text-slate-500">{label}</span>
              <span className={cn('font-semibold', cls)}>{val}</span>
            </div>
          ))}
          {seatInfo.pending_invites > 0 && (
            <div className="flex justify-between text-amber-600">
              <span>Pending invites</span>
              <span className="font-semibold">{seatInfo.pending_invites}</span>
            </div>
          )}
        </div>

        {/* Seat count adjuster */}
        <div>
          <label className="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1.5">New seat count</label>
          <div className="flex items-center gap-2">
            <button onClick={() => setNewSeatCount(Math.max(seatInfo.total_allocated, newSeatCount - 1))}
              disabled={newSeatCount <= seatInfo.total_allocated}
              className="p-2.5 border border-border/60 rounded-lg hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
              <Minus className="w-4 h-4 text-slate-600" />
            </button>
            <input type="number" min={seatInfo.total_allocated} max="1000" value={newSeatCount}
              onChange={e => setNewSeatCount(Math.max(seatInfo.total_allocated, parseInt(e.target.value) || seatInfo.total_allocated))}
              className="flex-1 px-3 py-2.5 text-center font-bold border border-border/60 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary/50" />
            <button onClick={() => setNewSeatCount(newSeatCount + 1)}
              className="p-2.5 border border-border/60 rounded-lg hover:bg-slate-50 transition-colors">
              <Plus className="w-4 h-4 text-slate-600" />
            </button>
          </div>
        </div>

        {/* Savings / cost callout */}
        {newSeatCount < seatInfo.seat_count && (
          <div className="flex items-start gap-2.5 px-4 py-3 bg-emerald-50 border border-emerald-200 rounded-lg text-sm text-emerald-700">
            <CheckCircle2 className="w-4 h-4 mt-0.5 shrink-0" />
            <span>Reducing by {seatInfo.seat_count - newSeatCount} seat(s) saves <strong>
              {currentInterval === 'yearly'
                ? `$${((seatInfo.seat_count - newSeatCount) * pricePerSeat * 12).toFixed(2)}/yr`
                : `$${((seatInfo.seat_count - newSeatCount) * pricePerSeat).toFixed(2)}/mo`}
            </strong>. You'll receive a prorated credit.</span>
          </div>
        )}
        {newSeatCount > seatInfo.seat_count && (
          <div className="flex items-start gap-2.5 px-4 py-3 bg-primary/5 border border-primary/20 rounded-lg text-sm text-primary">
            <Plus className="w-4 h-4 mt-0.5 shrink-0" />
            <span>Adding {newSeatCount - seatInfo.seat_count} seat(s) costs <strong>
              {currentInterval === 'yearly'
                ? `$${((newSeatCount - seatInfo.seat_count) * pricePerSeat * 12).toFixed(2)}/yr`
                : `$${((newSeatCount - seatInfo.seat_count) * pricePerSeat).toFixed(2)}/mo`}
            </strong> more.</span>
          </div>
        )}
      </div>
      <div className="px-6 py-4 bg-slate-50/60 border-t border-border/50 flex gap-3">
        <button onClick={() => setShowManageSeats(false)}
          className="flex-1 py-2 text-sm font-semibold text-slate-600 bg-white border border-border/60 rounded-lg hover:bg-slate-50 transition-colors">
          Cancel
        </button>
        <button onClick={handleReduceSeats}
          disabled={reducingSeats || newSeatCount === seatInfo.seat_count || newSeatCount < seatInfo.total_allocated}
          className="flex-1 py-2 text-sm font-semibold bg-primary text-white rounded-lg hover:opacity-90 disabled:opacity-40 flex items-center justify-center gap-2 transition-all">
          {reducingSeats ? <Loader2 className="w-4 h-4 animate-spin" />
            : newSeatCount < seatInfo.seat_count ? <Minus className="w-4 h-4" /> : <Plus className="w-4 h-4" />}
          {newSeatCount === seatInfo.seat_count ? 'No Change'
            : newSeatCount < seatInfo.seat_count ? `Reduce to ${newSeatCount}` : `Increase to ${newSeatCount}`}
        </button>
      </div>
    </Modal>
  );

  const changePlanModal = showChangePlan && (
    <Modal title="Change Plan" onClose={() => setShowChangePlan(false)} maxWidth="max-w-lg">
      <div className="p-6 space-y-4">
        <p className="text-sm text-slate-500">
          You're on <span className="font-semibold text-slate-700">{planName}</span>, billed {currentInterval}.
        </p>

        {currentPlan === 'executive' ? (
          <div className="border border-amber-200 bg-amber-50 rounded-xl p-5 space-y-4">
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 bg-amber-100 rounded-lg flex items-center justify-center shrink-0">
                <Star className="w-4 h-4 text-amber-600" />
              </div>
              <div>
                <p className="font-bold text-slate-800">⭐ Professional</p>
                <p className="text-lg font-extrabold text-slate-800">
                  ${currentInterval === 'yearly' ? '23.99' : '29.99'}
                  <span className="text-xs font-medium text-slate-400">/user/mo</span>
                </p>
              </div>
            </div>
            <p className="text-xs text-amber-700 bg-amber-100 rounded-lg px-3 py-2">
              ⚠️ You'll lose access to billing rates, employee costs, profitability reports, and advanced analytics.
            </p>
            <button onClick={() => handleChangePlan('professional')} disabled={changingPlan}
              className="w-full py-2.5 bg-amber-500 text-white text-sm font-bold rounded-lg hover:bg-amber-600 flex items-center justify-center gap-2 transition-all">
              {changingPlan ? <Loader2 className="w-4 h-4 animate-spin" /> : <ArrowDown className="w-4 h-4" />}
              Downgrade to Professional
            </button>
          </div>
        ) : (
          <div className="border border-primary/30 bg-primary/5 rounded-xl p-5 space-y-4">
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 bg-primary rounded-lg flex items-center justify-center shrink-0">
                <Crown className="w-4 h-4 text-white" />
              </div>
              <div>
                <p className="font-bold text-slate-800">💎 Executive</p>
                <p className="text-lg font-extrabold text-slate-800">
                  ${currentInterval === 'yearly' ? '39.99' : '49.99'}
                  <span className="text-xs font-medium text-slate-400">/user/mo</span>
                </p>
              </div>
            </div>
            <p className="text-xs text-primary bg-primary/10 rounded-lg px-3 py-2">
              Unlock billing rates, employee costs, profitability reports, advanced analytics, and API access.
            </p>
            <button onClick={() => handleChangePlan('executive')} disabled={changingPlan}
              className="w-full py-2.5 bg-primary text-white text-sm font-bold rounded-lg hover:opacity-90 flex items-center justify-center gap-2 transition-all shadow-sm shadow-primary/25">
              {changingPlan ? <Loader2 className="w-4 h-4 animate-spin" /> : <ArrowUp className="w-4 h-4" />}
              Upgrade to Executive
            </button>
          </div>
        )}
      </div>
      <div className="px-6 py-4 bg-slate-50/60 border-t border-border/50">
        <button onClick={() => setShowChangePlan(false)}
          className="w-full py-2 text-sm font-semibold text-slate-600 hover:bg-slate-200 rounded-lg transition-colors">
          Keep Current Plan
        </button>
      </div>
    </Modal>
  );

  // ── Page ──────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-4">
      {addSeatsModal}
      {manageSeatsModal}
      {changePlanModal}

      {/* ── Page header ─────────────────────────────────────────────── */}
      <div className="bg-white rounded-xl border border-border/60 px-6 py-5 flex items-center gap-4">
        <div className="w-10 h-10 bg-primary/10 rounded-xl flex items-center justify-center shrink-0">
          <CreditCard className="w-5 h-5 text-primary" />
        </div>
        <div>
          <h2 className="text-lg font-extrabold text-slate-800">Subscription & Billing</h2>
          <p className="text-xs text-slate-400 mt-0.5">Manage your plan and payment method</p>
        </div>
      </div>

      {/* ── Alerts ──────────────────────────────────────────────────── */}
      {error && (
        <div className="flex items-start gap-2.5 px-4 py-3 bg-red-50 border border-red-200 rounded-xl text-sm text-red-700">
          <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" /> {error}
        </div>
      )}
      {success && (
        <div className="flex items-start gap-2.5 px-4 py-3 bg-emerald-50 border border-emerald-200 rounded-xl text-sm text-emerald-700">
          <CheckCircle2 className="w-4 h-4 mt-0.5 shrink-0" /> {success}
        </div>
      )}
      {!hasActive && (
        <div className="flex items-start gap-2.5 px-4 py-3 bg-red-50 border border-red-200 rounded-xl text-sm text-red-700">
          <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
          <div>
            <p className="font-semibold">No Active Subscription</p>
            <p className="text-xs mt-0.5 text-red-600">Subscribe to a plan below to access all features.</p>
          </div>
        </div>
      )}

      {/* ── Current plan card ────────────────────────────────────────── */}
      <div className="bg-white rounded-xl border border-border/60 overflow-hidden">
        <div className="px-6 py-4 border-b border-border/50">
          <h3 className="text-sm font-bold text-slate-700">Current Plan</h3>
        </div>
        <div className="px-6 py-5">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className={cn('w-10 h-10 rounded-xl flex items-center justify-center shrink-0',
                currentPlan === 'executive' ? 'bg-primary text-white'
                : currentPlan === 'professional' ? 'bg-amber-100 text-amber-600'
                : 'bg-slate-100 text-slate-400')}>
                <PlanIcon className="w-5 h-5" />
              </div>
              <div>
                <p className="font-extrabold text-slate-800">{planName}</p>
                {hasActive && (
                  <p className="text-xs text-slate-400 mt-0.5">
                    Billed {currentInterval} · renews {subscription?.subscription?.current_period_end
                      ? new Date(subscription.subscription.current_period_end * 1000).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
                      : '—'}
                  </p>
                )}
              </div>
            </div>
            {hasActive && (
              <button onClick={() => setShowChangePlan(true)}
                className="px-3 py-1.5 text-xs font-semibold text-slate-600 bg-slate-50 hover:bg-slate-100 border border-border/60 rounded-lg transition-colors">
                Change Plan
              </button>
            )}
          </div>

          {subscription?.subscription?.cancel_at_period_end && (
            <div className="mt-4 flex items-start gap-2.5 px-4 py-3 bg-amber-50 border border-amber-200 rounded-lg text-xs text-amber-700">
              <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
              Your subscription will cancel at the end of the billing period.
            </div>
          )}
        </div>

        {/* Seat usage */}
        {hasActive && seatInfo && (
          <div className="px-6 pb-5">
            <div className="bg-slate-50 rounded-xl p-4 border border-border/40">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <Users className="w-4 h-4 text-slate-400 shrink-0" />
                  <div>
                    <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Team Seats</p>
                    <p className="text-lg font-extrabold text-slate-800 leading-none mt-0.5">
                      {seatInfo.members} <span className="text-slate-400 font-normal text-sm">/ {seatInfo.seat_count} used</span>
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <button onClick={() => { setNewSeatCount(seatInfo.seat_count); setShowManageSeats(true); }}
                    className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-slate-600 bg-white border border-border/60 rounded-lg hover:bg-slate-50 transition-colors">
                    <Minus className="w-3 h-3" /> Manage
                  </button>
                  <button onClick={() => setShowAddSeats(true)}
                    className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-primary bg-primary/8 border border-primary/20 rounded-lg hover:bg-primary/12 transition-colors">
                    <Plus className="w-3 h-3" /> Add Seats
                  </button>
                </div>
              </div>
              {/* Usage bar */}
              <div className="h-1.5 bg-slate-200 rounded-full overflow-hidden mb-2">
                <div className={cn('h-full rounded-full transition-all',
                  seatInfo.members >= seatInfo.seat_count ? 'bg-red-500'
                  : seatInfo.members >= seatInfo.seat_count * 0.8 ? 'bg-amber-400'
                  : 'bg-emerald-500')}
                  style={{ width: `${Math.min(100, (seatInfo.members / seatInfo.seat_count) * 100)}%` }} />
              </div>
              <div className="flex justify-between text-[10px] text-slate-400">
                <span>{seatInfo.seats_available} seat{seatInfo.seats_available !== 1 ? 's' : ''} available</span>
                {seatInfo.pending_invites > 0 && <span className="text-amber-600">{seatInfo.pending_invites} pending invite{seatInfo.pending_invites !== 1 ? 's' : ''}</span>}
              </div>
            </div>
          </div>
        )}

        {/* Manage billing button */}
        {hasActive && (
          <div className="px-6 pb-5">
            <button onClick={handleManageBilling} disabled={managingBilling}
              className="w-full py-2.5 text-sm font-semibold text-slate-600 bg-slate-50 hover:bg-slate-100 border border-border/60 rounded-lg flex items-center justify-center gap-2 transition-colors">
              {managingBilling ? <Loader2 className="w-4 h-4 animate-spin" /> : <ExternalLink className="w-4 h-4" />}
              Manage Subscription & Payment Method
            </button>
          </div>
        )}
      </div>

      {/* ── Plans grid ───────────────────────────────────────────────── */}
      {(!hasActive || currentPlan === 'professional') && (
        <div className="bg-white rounded-xl border border-border/60 overflow-hidden">
          <div className="px-6 py-4 border-b border-border/50 flex items-center justify-between">
            <h3 className="text-sm font-bold text-slate-700">
              {hasActive ? 'Upgrade Your Plan' : 'Choose a Plan'}
            </h3>
            {/* Interval toggle */}
            <div className="flex items-center gap-1 p-1 bg-slate-100 rounded-lg">
              {(['monthly', 'yearly'] as BillingInterval[]).map(interval => (
                <button key={interval} onClick={() => setBillingInterval(interval)}
                  className={cn('flex items-center gap-1.5 px-3 py-1 text-xs font-semibold rounded-md transition-all',
                    billingInterval === interval ? 'bg-white text-slate-800 shadow-sm' : 'text-slate-500 hover:text-slate-700')}>
                  {interval.charAt(0).toUpperCase() + interval.slice(1)}
                  {interval === 'yearly' && (
                    <span className="px-1.5 py-0.5 bg-emerald-100 text-emerald-700 text-[9px] font-bold rounded-full">–20%</span>
                  )}
                </button>
              ))}
            </div>
          </div>

          {billingInterval === 'yearly' && (
            <div className="mx-6 mt-4 flex items-center gap-2.5 px-4 py-2.5 bg-emerald-50 border border-emerald-200 rounded-lg text-sm text-emerald-700">
              <Percent className="w-3.5 h-3.5 shrink-0" />
              <span><strong>Save 20%</strong> with yearly billing — that's 2+ months free.</span>
            </div>
          )}

          <div className="p-6 grid md:grid-cols-2 gap-4">
            {PLANS.map(plan => {
              const PlanIconEl = plan.icon;
              const isCurrentPlan = currentPlan === plan.id;
              const canUpgrade    = currentPlan === 'professional' && plan.id === 'executive';
              const canSubscribe  = !hasActive;
              const price         = getPlanPrice(plan);
              const savings       = getYearlySavings(plan);

              return (
                <div key={plan.id}
                  className={cn('relative rounded-xl border p-5 transition-all',
                    plan.popular ? 'border-primary/30 bg-primary/3' : 'border-border/60',
                    isCurrentPlan && 'ring-2 ring-primary/30')}>

                  {plan.popular && (
                    <span className="absolute -top-2.5 left-1/2 -translate-x-1/2 bg-primary text-white text-[10px] font-bold px-2.5 py-0.5 rounded-full uppercase tracking-wider">
                      Most Popular
                    </span>
                  )}

                  {/* Plan header */}
                  <div className="flex items-center gap-3 mb-4">
                    <div className={cn('w-9 h-9 rounded-lg flex items-center justify-center shrink-0',
                      plan.id === 'executive' ? 'bg-primary text-white' : 'bg-amber-100 text-amber-600')}>
                      <PlanIconEl className="w-4 h-4" />
                    </div>
                    <div>
                      <p className="font-extrabold text-slate-800">{plan.emoji} {plan.name}</p>
                      {isCurrentPlan && (
                        <span className="text-[10px] font-bold px-2 py-0.5 bg-primary/10 text-primary rounded-full">Current plan</span>
                      )}
                    </div>
                  </div>

                  {/* Price */}
                  <div className="mb-4">
                    <div className="flex items-baseline gap-1">
                      <span className="text-2xl font-extrabold text-slate-800">${price}</span>
                      <span className="text-xs text-slate-400">/user/month</span>
                    </div>
                    {billingInterval === 'yearly' && (
                      <div className="flex items-center gap-2 mt-0.5">
                        <span className="text-xs text-slate-400 line-through">${plan.monthlyPrice}/mo</span>
                        <span className="text-xs font-semibold text-emerald-600">Save ${savings.toFixed(0)}/yr</span>
                      </div>
                    )}
                    {billingInterval === 'yearly' && (
                      <p className="text-[10px] text-slate-400 mt-0.5">Billed as ${(price * 12).toFixed(2)}/year per user</p>
                    )}
                  </div>

                  {/* Features */}
                  <ul className="space-y-1.5 mb-5">
                    {plan.features.map((f, i) => (
                      <li key={i} className="flex items-start gap-2 text-xs text-slate-600">
                        <CheckCircle2 className={cn('w-3.5 h-3.5 mt-0.5 shrink-0', plan.id === 'executive' ? 'text-primary' : 'text-emerald-500')} />
                        {f}
                      </li>
                    ))}
                  </ul>

                  {/* CTA */}
                  {canSubscribe && (
                    <button onClick={() => handleSubscribe(plan.id, billingInterval)} disabled={upgrading}
                      className={cn('w-full py-2.5 text-sm font-bold rounded-lg flex items-center justify-center gap-2 transition-all',
                        plan.popular
                          ? 'bg-primary text-white hover:opacity-90 shadow-sm shadow-primary/25'
                          : 'bg-slate-100 text-slate-700 hover:bg-slate-200')}>
                      {upgrading ? <Loader2 className="w-4 h-4 animate-spin" /> : <CreditCard className="w-4 h-4" />}
                      Subscribe {billingInterval === 'yearly' ? 'Yearly' : 'Monthly'}
                    </button>
                  )}
                  {canUpgrade && (
                    <button onClick={() => handleChangePlan('executive')} disabled={changingPlan}
                      className="w-full py-2.5 text-sm font-bold rounded-lg flex items-center justify-center gap-2 bg-primary text-white hover:opacity-90 shadow-sm shadow-primary/25 transition-all">
                      {changingPlan ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
                      Upgrade to Executive
                    </button>
                  )}
                  {isCurrentPlan && (
                    <p className="text-center text-xs font-semibold text-primary">✓ Your current plan</p>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Executive — top plan banner */}
      {hasActive && currentPlan === 'executive' && (
        <div className="bg-primary/5 rounded-xl border border-primary/20 px-5 py-4 flex items-center gap-3">
          <div className="w-9 h-9 bg-primary rounded-lg flex items-center justify-center shrink-0">
            <Crown className="w-4 h-4 text-white" />
          </div>
          <div>
            <p className="text-sm font-bold text-slate-800">You're on the Executive plan</p>
            <p className="text-xs text-slate-500 mt-0.5">You have access to all TimeTracker features.</p>
          </div>
        </div>
      )}

      {/* Footer note */}
      <p className="text-xs text-slate-400 text-center flex items-center justify-center gap-1.5">
        <CreditCard className="w-3.5 h-3.5" /> Secure payments powered by Stripe · Cancel anytime
      </p>
    </div>
  );
}