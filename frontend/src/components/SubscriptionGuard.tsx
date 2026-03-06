// src/components/SubscriptionGuard.tsx
/**
 * Wraps protected routes to check subscription status.
 * Redirects to billing page if trial expired.
 */

import React, { useEffect, useState, createContext, useContext } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { Loader2 } from 'lucide-react';

interface SubscriptionStatus {
  isActive: boolean;
  isTrial: boolean;
  trialDaysLeft: number;
  plan: string | null;
  trialEndsAt: string | null;
}

interface SubscriptionContextType {
  status: SubscriptionStatus | null;
  loading: boolean;
  refresh: () => Promise<void>;
}

const SubscriptionContext = createContext<SubscriptionContextType>({
  status: null,
  loading: true,
  refresh: async () => {},
});

export const useSubscription = () => useContext(SubscriptionContext);

const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api';

export function SubscriptionProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<SubscriptionStatus | null>(null);
  const [loading, setLoading] = useState(true);

  const checkSubscription = async () => {
    try {
      const token = localStorage.getItem('auth_token');
      if (!token) {
        setStatus(null);
        setLoading(false);
        return;
      }

      const response = await fetch(`${API_BASE}/billing/subscription/`, {
        headers: {
          'Authorization': `Bearer ${token}`,
        },
      });

      if (response.ok) {
        const data = await response.json();
        
        const now = new Date();
        const trialEndsAt = data.trial?.ends_at ? new Date(data.trial.ends_at) : null;
        const trialDaysLeft = trialEndsAt 
          ? Math.max(0, Math.ceil((trialEndsAt.getTime() - now.getTime()) / (1000 * 60 * 60 * 24)))
          : 0;

        setStatus({
          isActive: data.subscription?.status === 'active' || data.trial?.active || ['professional', 'executive'].includes(data.organization?.plan),
          isTrial: data.trial?.active || false,
          trialDaysLeft,
          plan: data.organization?.plan || null,
          trialEndsAt: data.trial?.ends_at || null,
        });
      } else if (response.status === 402) {
        // Trial expired, no subscription
        const data = await response.json();
        setStatus({
          isActive: false,
          isTrial: false,
          trialDaysLeft: 0,
          plan: null,
          trialEndsAt: data.trial_ended_at || null,
        });
      }
    } catch (err) {
      console.error('Failed to check subscription:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    checkSubscription();
  }, []);

  return (
    <SubscriptionContext.Provider value={{ status, loading, refresh: checkSubscription }}>
      {children}
    </SubscriptionContext.Provider>
  );
}

interface SubscriptionGuardProps {
  children: React.ReactNode;
}

export function SubscriptionGuard({ children }: SubscriptionGuardProps) {
  const { status, loading } = useSubscription();
  const location = useLocation();

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center">
        <Loader2 className="w-8 h-8 text-emerald-600 animate-spin" />
      </div>
    );
  }

  // Not logged in - let auth guard handle it
  if (!status) {
    return <>{children}</>;
  }

  // Subscription/trial is active
  if (status.isActive) {
    return <>{children}</>;
  }

  // Trial expired, no subscription - redirect to billing
  return <Navigate to="/billing" state={{ from: location }} replace />;
}

// Trial Banner Component - show days remaining
export function TrialBanner() {
  const { status } = useSubscription();

  if (!status?.isTrial || status.trialDaysLeft > 7) {
    return null;
  }

  const urgency = status.trialDaysLeft <= 2 ? 'bg-red-500' : 'bg-amber-500';

  return (
    <div className={`${urgency} text-white py-2 px-4 text-center text-sm font-medium`}>
      {status.trialDaysLeft === 0 ? (
        <>Your trial expires today! <a href="/billing" className="underline font-bold">Subscribe now</a> to keep access.</>
      ) : status.trialDaysLeft === 1 ? (
        <>Your trial expires tomorrow! <a href="/billing" className="underline font-bold">Subscribe now</a> to keep access.</>
      ) : (
        <>{status.trialDaysLeft} days left in your trial. <a href="/billing" className="underline font-bold">Subscribe now</a> to keep access.</>
      )}
    </div>
  );
}

export default SubscriptionGuard;