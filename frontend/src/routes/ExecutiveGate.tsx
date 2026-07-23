// src/routes/ExecutiveGate.tsx
/**
 * Plan gate for the Analytics page. Unlike a hard route guard, this keeps the
 * page mounted and drapes a faded, non-interactive "cloak" over it with an
 * upgrade CTA when the org is not on the Executive plan.
 *
 * Plan is resolved the same way as BillingPage: admin impersonation forces
 * executive, otherwise read /settings/org/ with a /billing/subscription-status/
 * fallback.
 */

import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { safeFetchJson, API_BASE } from '@/lib/api';
import { Lock, Sparkles } from 'lucide-react';
import { hasAnalyticsAccess, type PlanType } from '@/pages/settings/types';

interface ExecutiveGateProps {
  children: React.ReactNode;
}

export default function ExecutiveGate({ children }: ExecutiveGateProps) {
  const [status, setStatus] = useState<'loading' | 'unlocked' | 'locked'>('loading');

  useEffect(() => {
    const checkPlan = async () => {
      // Admin impersonation: always grant executive access.
      if (localStorage.getItem('impersonating_org_id')) {
        setStatus('unlocked');
        return;
      }

      let plan: PlanType | undefined;
      try {
        const org = await safeFetchJson<{ plan?: PlanType }>(`${API_BASE}/settings/org/`);
        plan = org?.plan;
      } catch {
        try {
          const sub = await safeFetchJson<{ organization?: { plan?: PlanType } }>(
            `${API_BASE}/billing/subscription-status/`,
          );
          plan = sub?.organization?.plan;
        } catch {
          plan = undefined;
        }
      }

      setStatus(hasAnalyticsAccess(plan) ? 'unlocked' : 'locked');
    };

    checkPlan();
  }, []);

  if (status === 'loading') {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
      </div>
    );
  }

  if (status === 'unlocked') {
    return <>{children}</>;
  }

  // Locked: render the page underneath, cloaked and non-interactive, with an
  // upgrade overlay on top.
  return (
    <div className="relative">
      <div
        className="pointer-events-none select-none blur-sm opacity-40"
        aria-hidden="true"
        {...({ inert: '' } as Record<string, unknown>)}
      >
        {children}
      </div>

      <div className="absolute inset-0 z-10 flex items-start justify-center bg-white/60 backdrop-blur-[2px] pt-24">
        <div className="text-center p-10 bg-white rounded-2xl border border-border/60 shadow-lg max-w-md mx-4">
          <div className="w-14 h-14 bg-slate-50 rounded-full flex items-center justify-center mx-auto mb-5">
            <Lock className="w-7 h-7 text-slate-300" />
          </div>
          <h3 className="text-lg font-bold text-slate-900 mb-2">Analytics is an Executive feature</h3>
          <p className="text-slate-500 text-sm leading-relaxed mb-6">
            Upgrade to the{' '}
            <span className="font-semibold text-primary">Executive</span> plan to unlock firm-wide
            profitability, client, and staff analytics.
          </p>
          <Link
            to="/account/billing"
            className="inline-flex items-center gap-2 px-5 py-2.5 bg-primary text-white text-sm font-semibold rounded-lg hover:opacity-90 transition-all"
          >
            <Sparkles className="w-4 h-4" />
            Upgrade to Executive
          </Link>
        </div>
      </div>
    </div>
  );
}
