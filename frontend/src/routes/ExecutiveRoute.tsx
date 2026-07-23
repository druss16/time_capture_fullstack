// src/routes/ExecutiveRoute.tsx
/**
 * Route guard that only allows orgs on the Executive plan.
 * Mirrors AdminRoute, but gates on subscription plan rather than role.
 * Plan is resolved the same way as BillingPage: admin impersonation forces
 * executive, otherwise read /settings/org/ with a /billing/subscription-status/
 * fallback.
 */

import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { safeFetchJson, API_BASE } from '@/lib/api';
import { Lock, Sparkles } from 'lucide-react';
import { EXECUTIVE_PLANS, type PlanType } from '@/pages/settings/types';

interface ExecutiveRouteProps {
  children: React.ReactNode;
}

export default function ExecutiveRoute({ children }: ExecutiveRouteProps) {
  const [status, setStatus] = useState<'loading' | 'allowed' | 'denied'>('loading');

  useEffect(() => {
    const checkPlan = async () => {
      // Admin impersonation: always grant executive access.
      if (localStorage.getItem('impersonating_org_id')) {
        setStatus('allowed');
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

      setStatus(plan && EXECUTIVE_PLANS.includes(plan) ? 'allowed' : 'denied');
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

  if (status === 'denied') {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <div className="text-center p-10 bg-white rounded-2xl border border-border/60 shadow-sm max-w-md">
          <div className="w-14 h-14 bg-slate-50 rounded-full flex items-center justify-center mx-auto mb-5">
            <Lock className="w-7 h-7 text-slate-300" />
          </div>
          <h3 className="text-lg font-bold text-slate-900 mb-2">Analytics</h3>
          <p className="text-slate-500 text-sm leading-relaxed mb-6">
            This feature is available on the{' '}
            <span className="font-semibold text-primary">Executive</span> plan.
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
    );
  }

  return <>{children}</>;
}
