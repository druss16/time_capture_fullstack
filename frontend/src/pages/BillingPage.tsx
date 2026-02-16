/**
 * BillingPage.tsx - With Plan-Based Feature Gating
 * Professional plan: My Timesheet, Approvals
 * Executive plan: All features (Billing, Profitability, History)
 * No plan: Show subscribe prompt
 */
import React, { useState, useEffect, useMemo } from 'react';
import { safeFetchJson, API_BASE } from '@/lib/api';
import WeeklyTimesheet from '@/components/WeeklyTimesheet';
import ApprovalQueue from '@/components/ApprovalQueue';
import ClientSummary from '@/components/ClientSummary';
import ClientProfitability from '@/components/ClientProfitability';
import TimesheetHistory from '@/components/TimesheetHistory';
import IntegrationPushPanel from '@/components/IntegrationPushPanel';
import IntegrationInvoicePanel from '@/components/IntegrationInvoicePanel';
import {
  Clock,
  CheckSquare,
  DollarSign,
  TrendingUp,
  FileText,
  ChevronRight,
  Lock,
  Sparkles,
  AlertTriangle,
  CreditCard,
} from 'lucide-react';
import { cn, getRoleColor, SKELETON } from '@/lib/design-system';

type UserRole = 'owner' | 'admin' | 'manager' | 'member';
type PlanType = 'professional' | 'executive' | 'none';

interface Tab {
  id: string;
  label: string;
  icon: React.ElementType;
  description: string;
  requiredRoles: UserRole[];
  requiredPlan?: PlanType[]; // plans that can access this tab
}

interface WhoamiResponse {
  username: string;
  email: string;
  role: UserRole | null;
  org_name: string | null;
  org_id: number | null;
  is_authenticated: boolean;
}

interface OrgResponse {
  id: number;
  name: string;
  plan: string;
  trial_ends_at: string | null;
}

const PROFESSIONAL_PLANS: PlanType[] = ['professional', 'executive']; // professional can see base features
const EXECUTIVE_PLANS: PlanType[] = ['executive'];

const ALL_TABS: Tab[] = [
  {
    id: 'timesheet',
    label: 'My Timesheet',
    description: 'View and submit your weekly hours',
    requiredRoles: ['owner', 'admin', 'manager', 'member'],
    icon: Clock,
    requiredPlan: PROFESSIONAL_PLANS,
  },
  {
    id: 'approvals',
    label: 'Approvals',
    description: 'Review and approve team timesheets',
    requiredRoles: ['owner', 'admin', 'manager'],
    icon: CheckSquare,
    requiredPlan: PROFESSIONAL_PLANS,
  },
  {
    id: 'billing',
    label: 'Client Billing',
    description: 'Prepare invoices by client',
    requiredRoles: ['owner', 'admin'],
    icon: DollarSign,
    requiredPlan: EXECUTIVE_PLANS,
  },
  {
    id: 'profitability',
    label: 'Profitability',
    description: 'Analyze margins and efficiency',
    requiredRoles: ['owner', 'admin'],
    icon: TrendingUp,
    requiredPlan: EXECUTIVE_PLANS,
  },
  {
    id: 'history',
    label: 'History',
    description: 'View approved and locked timesheets',
    requiredRoles: ['owner', 'admin', 'manager'],
    icon: FileText,
    requiredPlan: EXECUTIVE_PLANS,
  },
];

// Loading skeleton for sidebar
const SidebarSkeleton = () => (
  <div className="space-y-2">
    {[1, 2, 3, 4].map((i) => (
      <div key={i} className={cn(SKELETON.base, 'h-14 w-full rounded-xl')} />
    ))}
  </div>
);

// Loading skeleton for content
const ContentSkeleton = () => (
  <div className="space-y-4">
    <div className={cn(SKELETON.heading, 'w-48')} />
    <div className="space-y-3">
      {[1, 2, 3, 4, 5].map((i) => (
        <div key={i} className={cn(SKELETON.row, 'w-full')} />
      ))}
    </div>
  </div>
);

// Subscribe prompt for users with no plan
const SubscribePrompt: React.FC = () => (
  <div className="relative flex items-center justify-center min-h-[400px]">
    {/* Blurred background placeholder */}
    <div className="absolute inset-0 overflow-hidden rounded-2xl">
      <div className="w-full h-full bg-gradient-to-br from-slate-100 to-slate-200 opacity-60 blur-sm" />
      <div className="absolute inset-0 p-6 opacity-30 blur-[2px]">
        <div className="h-8 w-48 bg-slate-300 rounded mb-4" />
        <div className="grid grid-cols-3 gap-4 mb-6">
          <div className="h-24 bg-slate-200 rounded-xl" />
          <div className="h-24 bg-slate-200 rounded-xl" />
          <div className="h-24 bg-slate-200 rounded-xl" />
        </div>
        <div className="space-y-3">
          <div className="h-12 bg-slate-200 rounded-lg" />
          <div className="h-12 bg-slate-200 rounded-lg" />
          <div className="h-12 bg-slate-200 rounded-lg" />
        </div>
      </div>
    </div>

    {/* Subscribe overlay */}
    <div className="relative z-10 text-center p-8 bg-white/95 backdrop-blur-sm rounded-2xl shadow-xl border-2 border-red-200 max-w-md">
      <div className="w-16 h-16 bg-red-100 rounded-full flex items-center justify-center mx-auto mb-4">
        <AlertTriangle className="w-8 h-8 text-red-500" />
      </div>
      <h3 className="text-xl font-extrabold text-slate-900 mb-2">No Active Subscription</h3>
      <p className="text-slate-600 font-medium mb-6">
        You need an active subscription to access TimeTracker features.
        Subscribe to a plan to start tracking time and billing clients.
      </p>
      <a
        href="/account/billing"
        className="inline-flex items-center gap-2 px-6 py-3 bg-primary text-white font-bold rounded-xl hover:opacity-90 transition-all shadow-lg shadow-primary/25"
      >
        <CreditCard className="w-5 h-5" />
        Subscribe Now
      </a>
      <p className="text-sm text-slate-500 font-medium mt-4">
        Plans start at $29.99/user/month
      </p>
    </div>
  </div>
);

// Upgrade prompt component for locked features (Executive)
const UpgradePrompt: React.FC<{ featureName: string }> = ({ featureName }) => (
  <div className="relative flex items-center justify-center min-h-[400px]">
    {/* Blurred background placeholder */}
    <div className="absolute inset-0 overflow-hidden rounded-2xl">
      <div className="w-full h-full bg-gradient-to-br from-slate-100 to-slate-200 opacity-60 blur-sm" />
      {/* Fake content behind blur */}
      <div className="absolute inset-0 p-6 opacity-30 blur-[2px]">
        <div className="h-8 w-48 bg-slate-300 rounded mb-4" />
        <div className="grid grid-cols-3 gap-4 mb-6">
          <div className="h-24 bg-slate-200 rounded-xl" />
          <div className="h-24 bg-slate-200 rounded-xl" />
          <div className="h-24 bg-slate-200 rounded-xl" />
        </div>
        <div className="space-y-3">
          <div className="h-12 bg-slate-200 rounded-lg" />
          <div className="h-12 bg-slate-200 rounded-lg" />
          <div className="h-12 bg-slate-200 rounded-lg" />
        </div>
      </div>
    </div>

    {/* Lock overlay */}
    <div className="relative z-10 text-center p-8 bg-white/95 backdrop-blur-sm rounded-2xl shadow-xl border-2 border-slate-200 max-w-md">
      <div className="w-16 h-16 bg-slate-100 rounded-full flex items-center justify-center mx-auto mb-4">
        <Lock className="w-8 h-8 text-slate-400" />
      </div>
      <h3 className="text-xl font-extrabold text-slate-900 mb-2">{featureName}</h3>
      <p className="text-slate-600 font-medium mb-6">
        This feature is available on the <span className="font-bold text-primary">Executive</span> plan.
        Upgrade to unlock advanced billing and profitability tools.
      </p>
      <a
        href="/account/billing"
        className="inline-flex items-center gap-2 px-6 py-3 bg-primary text-white font-bold rounded-xl hover:opacity-90 transition-all shadow-lg shadow-primary/25"
      >
        <Sparkles className="w-5 h-5" />
        Upgrade to Executive
      </a>
      <p className="text-sm text-slate-500 font-medium mt-4">See pricing in Billing</p>
    </div>
  </div>
);

const BillingPage: React.FC = () => {
  const [activeTab, setActiveTab] = useState<string>('timesheet');
  const [userInfo, setUserInfo] = useState<WhoamiResponse | null>(null);
  const [orgPlan, setOrgPlan] = useState<PlanType>('none');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // In BillingPage.tsx - update fetchUserInfo
    const fetchUserInfo = async () => {
      try {
        const response = await safeFetchJson<WhoamiResponse>(`${API_BASE}/whoami/`);
        setUserInfo(response);

        // Try to get org plan - multiple fallback methods
        if (response.org_id) {
          try {
            // Method 1: settings/org (may fail for non-admins)
            const orgResponse = await safeFetchJson<OrgResponse>(`${API_BASE}/settings/org/`);
            const plan = orgResponse.plan;
            if (plan === 'professional' || plan === 'executive') {
              setOrgPlan(plan);
              return;
            }
          } catch (err) {
            console.log('settings/org failed, trying subscription endpoint');
          }
          
          // Method 2: Fallback to subscription endpoint (works for all members)
          try {
            const subResponse = await safeFetchJson<any>(`${API_BASE}/billing/subscription/`);
            const plan = subResponse?.organization?.plan;
            if (plan === 'professional' || plan === 'executive') {
              setOrgPlan(plan);
              return;
            }
          } catch (err) {
            console.error('subscription endpoint also failed:', err);
          }
        }
        
        setOrgPlan('none');
      } catch (err) {
        console.error('Failed to fetch user info:', err);
        setOrgPlan('none');
      } finally {
        setLoading(false);
      }
    };

    fetchUserInfo();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const userRole = userInfo?.role || 'member';
  const hasNoPlan = orgPlan === 'none';

  // Filter tabs by role (but show locked tabs for plan restrictions)
  const visibleTabs = useMemo(
    () => ALL_TABS.filter((tab) => tab.requiredRoles.includes(userRole)),
    [userRole]
  );

  const isTabLocked = (tab: Tab): boolean => {
    // If no plan, all tabs are locked
    if (hasNoPlan) return true;
    if (!tab.requiredPlan) return false;
    return !tab.requiredPlan.includes(orgPlan);
  };

  // Prevent landing on a locked tab (e.g. deep link / stale state)
  useEffect(() => {
    const tab = ALL_TABS.find((t) => t.id === activeTab);
    if (tab && isTabLocked(tab)) setActiveTab('timesheet');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orgPlan]);

  const getLockedFeatureName = (tabId: string): string => {
    switch (tabId) {
      case 'billing':
        return 'Client Billing';
      case 'profitability':
        return 'Profitability Analysis';
      case 'history':
        return 'Timesheet History';
      default:
        return 'This Feature';
    }
  };

  const getPlanLabel = (): string => {
    switch (orgPlan) {
      case 'executive':
        return '💎 Executive';
      case 'professional':
        return '⭐ Professional';
      default:
        return '⚠️ No Plan';
    }
  };

  return (
    <div className="flex min-h-[calc(100vh-56px)]">
      {/* Sidebar */}
      <aside className="w-64 bg-white border-r-2 border-slate-200 flex-shrink-0 flex flex-col">
        {/* Sidebar Header */}
        <div className="p-4 border-b-2 border-slate-200">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-primary flex items-center justify-center shadow-lg shadow-primary/25">
              <DollarSign className="w-5 h-5 text-white" />
            </div>
            <div>
              <h1 className="text-lg font-extrabold text-slate-900 tracking-tight">Billing</h1>
              <p className="text-sm text-slate-600 font-medium">Time & Invoicing</p>
            </div>
          </div>
        </div>

        {/* Navigation */}
        <nav className="p-3 space-y-1 flex-1">
          {loading ? (
            <SidebarSkeleton />
          ) : (
            visibleTabs.map((tab) => {
              const Icon = tab.icon;
              const isActive = activeTab === tab.id;
              const locked = isTabLocked(tab);

              return (
                <button
                  key={tab.id}
                  onClick={() => {
                    if (locked) return; // prevent switching into locked tab
                    setActiveTab(tab.id);
                  }}
                  className={cn(
                    'w-full flex items-center gap-3 px-3 py-2.5 rounded-xl',
                    'text-sm font-bold transition-all duration-200',
                    'group border-2',
                    locked
                      ? 'text-slate-400 border-transparent hover:bg-slate-50 cursor-not-allowed'
                      : isActive
                        ? 'bg-primary/10 text-primary border-primary/30'
                        : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900 border-transparent'
                  )}
                >
                  <div
                    className={cn(
                      'w-8 h-8 rounded-lg flex items-center justify-center transition-colors relative',
                      locked
                        ? 'bg-slate-100 text-slate-400'
                        : isActive
                          ? 'bg-primary text-white'
                          : 'bg-slate-200 text-slate-600 group-hover:bg-slate-300'
                    )}
                  >
                    <Icon className="w-4 h-4" />
                    {locked && (
                      <div className="absolute -top-1 -right-1 w-4 h-4 bg-slate-300 rounded-full flex items-center justify-center">
                        <Lock className="w-2.5 h-2.5 text-slate-500" />
                      </div>
                    )}
                  </div>
                  <div className="flex-1 text-left">
                    <span className={cn('block', locked && 'text-slate-400')}>{tab.label}</span>
                    <span
                      className={cn(
                        'text-xs font-semibold',
                        locked ? 'text-slate-400' : isActive ? 'text-primary/70' : 'text-slate-500'
                      )}
                    >
                      {locked 
                        ? (hasNoPlan ? 'Requires subscription' : 'Executive plan') 
                        : tab.description}
                    </span>
                  </div>
                  {isActive && !locked && <ChevronRight className="w-4 h-4 text-primary" />}
                  {locked && <Lock className="w-4 h-4 text-slate-400" />}
                </button>
              );
            })
          )}
        </nav>

        {/* Plan Badge */}
        {!loading && (
          <div className="px-3 pb-2">
            <div
              className={cn(
                'px-3 py-2 rounded-xl text-center border-2',
                orgPlan === 'executive'
                  ? 'bg-primary/10 border-primary/20'
                  : orgPlan === 'professional'
                  ? 'bg-amber-50 border-amber-200'
                  : 'bg-red-50 border-red-200'
              )}
            >
              <p className={cn(
                'text-xs font-bold', 
                orgPlan === 'executive' 
                  ? 'text-primary' 
                  : orgPlan === 'professional'
                  ? 'text-amber-700'
                  : 'text-red-700'
              )}>
                {getPlanLabel()}
              </p>

              {orgPlan === 'professional' && (
                <a href="/account/billing" className="text-xs text-amber-600 font-semibold hover:underline">
                  Upgrade for more features
                </a>
              )}

              {hasNoPlan && (
                <a href="/account/billing" className="text-xs text-red-600 font-semibold hover:underline">
                  Subscribe now
                </a>
              )}
            </div>
          </div>
        )}

        {/* User Info at Bottom */}
        {userInfo && (
          <div className="p-4 border-t-2 border-slate-200 bg-slate-50">
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-full bg-slate-300 flex items-center justify-center text-sm font-bold text-slate-700">
                {userInfo.username.charAt(0).toUpperCase()}
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-bold text-slate-900 truncate">{userInfo.username}</p>
                {userInfo.org_name && (
                  <p className="text-xs text-slate-600 font-medium truncate">{userInfo.org_name}</p>
                )}
              </div>
              {userRole && userRole !== 'member' && (
                <span className={cn('text-xs px-2 py-0.5 rounded font-bold', getRoleColor(userRole))}>
                  {userRole.charAt(0).toUpperCase() + userRole.slice(1)}
                </span>
              )}
            </div>
          </div>
        )}
      </aside>

      {/* Main Content */}
      <main className="flex-1 p-6 bg-slate-50">
        {loading ? (
          <ContentSkeleton />
        ) : hasNoPlan ? (
          // Show subscribe prompt for users with no plan
          <SubscribePrompt />
        ) : (
          <>
            {(() => {
              const tab = ALL_TABS.find((t) => t.id === activeTab);
              const locked = tab ? isTabLocked(tab) : false;

              if (locked) {
                return <UpgradePrompt featureName={getLockedFeatureName(activeTab)} />;
              }

              return (
                <>
                  {activeTab === 'timesheet' && <WeeklyTimesheet />}
                  {activeTab === 'approvals' && <ApprovalQueue />}
                  {activeTab === 'billing' && (
                    <div className="space-y-6">
                      <ClientSummary />
                      <IntegrationPushPanel />
                    </div>
                  )}
                  {activeTab === 'profitability' && (
                    <div className="space-y-6">
                      <ClientProfitability />
                      <IntegrationInvoicePanel />
                    </div>
                  )}
                  {activeTab === 'history' && <TimesheetHistory />}
                </>
              );
            })()}
          </>
        )}
      </main>
    </div>
  );
};

export default BillingPage;