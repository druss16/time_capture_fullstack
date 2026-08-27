/**
 * BillingPage.tsx - Two sections behind plan/role gating.
 *  · section="timesheet"  →  My Timesheet · Approvals · History   (route /timesheet)
 *  · section="billing"    →  Set Fees · Client Billing · Invoices (route /billing)
 * Professional plan: Timesheet section. Executive plan: Billing section + History.
 * No plan: Show subscribe prompt.
 */
import React, { useState, useEffect, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { safeFetchJson, API_BASE } from '@/lib/api';
import WeeklyTimesheet from '@/components/WeeklyTimesheet';
import WeekCoverage from '@/components/WeekCoverage';
import ApprovalQueue from '@/components/ApprovalQueue';
import ClientSummary from '@/components/ClientSummary';
import FeeBasis from '@/components/FeeBasis';
import TimesheetHistory from '@/components/TimesheetHistory';
import IntegrationInvoicePanel from '@/components/IntegrationInvoicePanel';
import InvoiceManager from '@/components/InvoiceManager';
import {
  Clock,
  CheckSquare,
  DollarSign,
  FileText,
  Receipt,
  Lock,
  Sparkles,
  AlertTriangle,
  CreditCard,
} from 'lucide-react';
import { cn, getRoleColor, SKELETON } from '@/lib/design-system';
import { useSearchParams } from 'react-router-dom';

type UserRole = 'owner' | 'admin' | 'manager' | 'member';
type PlanType = 'professional' | 'executive' | 'none';
type Section = 'timesheet' | 'billing';

interface Tab {
  id: string;
  label: string;
  icon: React.ElementType;
  description: string;
  requiredRoles: UserRole[];
  requiredPlan?: PlanType[];
}

interface SectionConfig {
  eyebrow: string;
  title: string;
  tabs: Tab[];
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

const PROFESSIONAL_PLANS: PlanType[] = ['professional', 'executive'];
const EXECUTIVE_PLANS: PlanType[] = ['executive'];

const SECTIONS: Record<Section, SectionConfig> = {
  timesheet: {
    eyebrow: 'My Week',
    // Named for the question it answers, not a ritual most firms skip. Daily
    // Review asks "is this the right client?" — attribution, and visible.
    // This asks "is my time whole?" — completeness, which is invisible unless
    // something goes looking for it. Submitting is one optional thing you can
    // do here, not what the page is for.
    title: 'Is your time whole?',
    tabs: [
      {
        id: 'timesheet',
        label: 'My Week',
        description: 'Check nothing is missing',
        requiredRoles: ['owner', 'admin', 'manager', 'member'],
        icon: Clock,
        requiredPlan: PROFESSIONAL_PLANS,
      },
      {
        id: 'approvals',
        label: 'Approvals',
        description: 'Approve team timesheets',
        requiredRoles: ['owner', 'admin', 'manager'],
        icon: CheckSquare,
        requiredPlan: PROFESSIONAL_PLANS,
      },
      {
        id: 'history',
        label: 'History',
        description: 'Past & locked weeks',
        requiredRoles: ['owner', 'admin', 'manager'],
        icon: FileText,
        requiredPlan: EXECUTIVE_PLANS,
      },
    ],
  },
  billing: {
    eyebrow: 'Billing',
    title: 'Clients & Invoices',
    tabs: [
      {
        id: 'fees',
        label: 'Set Fees',
        description: 'Decide what to charge, by client',
        requiredRoles: ['owner', 'admin', 'manager'],
        icon: DollarSign,
        requiredPlan: EXECUTIVE_PLANS,
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
        id: 'invoices',
        label: 'Invoices',
        description: 'Manage imported & billed invoices',
        requiredRoles: ['owner', 'admin'],
        icon: Receipt,
        requiredPlan: EXECUTIVE_PLANS,
      },
    ],
  },
};

const SidebarSkeleton = () => (
  <div className="space-y-1">
    {[1, 2, 3, 4].map((i) => (
      <div key={i} className={cn(SKELETON.base, 'h-10 w-full rounded-lg')} />
    ))}
  </div>
);

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

const SubscribePrompt: React.FC = () => (
  <div className="flex items-center justify-center min-h-[400px]">
    <div className="text-center p-10 bg-white rounded-2xl border border-border/60 shadow-sm max-w-md">
      <div className="w-14 h-14 bg-red-50 rounded-full flex items-center justify-center mx-auto mb-5">
        <AlertTriangle className="w-7 h-7 text-red-500" />
      </div>
      <h3 className="text-lg font-bold text-slate-900 mb-2">No Active Subscription</h3>
      <p className="text-slate-500 text-sm leading-relaxed mb-6">
        You need an active subscription to access TimeTracker features.
      </p>
      <a
        href="/account/billing"
        className="inline-flex items-center gap-2 px-5 py-2.5 bg-primary text-white text-sm font-semibold rounded-lg hover:opacity-90 transition-all"
      >
        <CreditCard className="w-4 h-4" />
        Subscribe Now
      </a>
      <p className="text-xs text-slate-400 mt-4">Plans start at $29.99/user/month</p>
    </div>
  </div>
);

const UpgradePrompt: React.FC<{ featureName: string }> = ({ featureName }) => (
  <div className="flex items-center justify-center min-h-[400px]">
    <div className="text-center p-10 bg-white rounded-2xl border border-border/60 shadow-sm max-w-md">
      <div className="w-14 h-14 bg-slate-50 rounded-full flex items-center justify-center mx-auto mb-5">
        <Lock className="w-7 h-7 text-slate-300" />
      </div>
      <h3 className="text-lg font-bold text-slate-900 mb-2">{featureName}</h3>
      <p className="text-slate-500 text-sm leading-relaxed mb-6">
        This feature is available on the{' '}
        <span className="font-semibold text-primary">Executive</span> plan.
      </p>
      <a
        href="/account/billing"
        className="inline-flex items-center gap-2 px-5 py-2.5 bg-primary text-white text-sm font-semibold rounded-lg hover:opacity-90 transition-all"
      >
        <Sparkles className="w-4 h-4" />
        Upgrade to Executive
      </a>
    </div>
  </div>
);

const BillingPage: React.FC<{ section?: Section }> = ({ section = 'timesheet' }) => {
  const navigate = useNavigate();
  const sectionConfig = SECTIONS[section];
  const sectionTabs = sectionConfig.tabs;
  const defaultTab = sectionTabs[0].id;
  const tabInSection = (id: string | null): boolean => !!id && sectionTabs.some((t) => t.id === id);

  const [searchParams, setSearchParams] = useSearchParams();
  const [activeTab, setActiveTab] = useState<string>(
    tabInSection(searchParams.get('tab')) ? (searchParams.get('tab') as string) : defaultTab
  );
  const [invoiceFilter, setInvoiceFilter] = useState<string>(searchParams.get('filter') || '');
  const [userInfo, setUserInfo] = useState<WhoamiResponse | null>(null);
  const [orgPlan, setOrgPlan] = useState<PlanType>('none');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchUserInfo = async () => {
      try {
        const response = await safeFetchJson<WhoamiResponse>(`${API_BASE}/whoami/`);
        setUserInfo(response);

        // ── Admin impersonation: always grant executive access ──
        if (localStorage.getItem("impersonating_org_id")) {
          setOrgPlan('executive');
          setLoading(false);
          return;
        }

        if (response.org_id) {
          try {
            const orgResponse = await safeFetchJson<OrgResponse>(`${API_BASE}/settings/org/`);
            const plan = orgResponse.plan;
            if (plan === 'professional' || plan === 'executive') {
              setOrgPlan(plan);
              return;
            }
          } catch (err) {
            console.log('settings/org failed, trying subscription endpoint');
          }

          try {
            const subResponse = await safeFetchJson<any>(`${API_BASE}/billing/subscription-status/`);
            const plan = subResponse?.organization?.plan;
            if (plan === 'professional' || plan === 'executive') {
              setOrgPlan(plan);
              return;
            }
          } catch (err) {
            console.error('subscription-status endpoint also failed:', err);
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
  }, []);

  const userRole = userInfo?.role || 'member';
  const hasNoPlan = orgPlan === 'none';

  const visibleTabs = useMemo(
    () => sectionTabs.filter((tab) => tab.requiredRoles.includes(userRole)),
    [sectionTabs, userRole]
  );

  const isTabLocked = (tab: Tab): boolean => {
    if (hasNoPlan) return true;
    if (!tab.requiredPlan) return false;
    return !tab.requiredPlan.includes(orgPlan);
  };

  // A user with no role access to this whole section (e.g. a member on /billing)
  // is bounced to their timesheet rather than shown an empty sidebar.
  useEffect(() => {
    if (loading || hasNoPlan) return;
    if (visibleTabs.length === 0 && section !== 'timesheet') navigate('/timesheet', { replace: true });
  }, [loading, hasNoPlan, visibleTabs.length, section, navigate]);

  // Keep the active tab valid: fall back to this section's first available tab
  // if the current one is locked or belongs to another section.
  useEffect(() => {
    if (loading) return;
    const tab = sectionTabs.find((t) => t.id === activeTab);
    if (!tab || isTabLocked(tab)) {
      const firstUnlocked = visibleTabs.find((t) => !isTabLocked(t));
      setActiveTab((firstUnlocked ?? sectionTabs[0]).id);
    }
  }, [orgPlan, loading, section]);

  useEffect(() => {
    const tabParam = searchParams.get('tab');
    const filterParam = searchParams.get('filter') || '';
    if (tabInSection(tabParam) && tabParam !== activeTab) setActiveTab(tabParam as string);
    setInvoiceFilter(filterParam);
  }, [searchParams]);

  const handleTabChange = (tabId: string) => {
    setActiveTab(tabId);
    setInvoiceFilter('');
    setSearchParams({ tab: tabId });
  };

  const getLockedFeatureName = (tabId: string): string => {
    switch (tabId) {
      case 'billing':       return 'Client Billing';
      case 'invoices':      return 'Invoice Management';
      case 'history':       return 'Timesheet History';
      default:              return 'This Feature';
    }
  };

  const getPlanLabel = (): string => {
    switch (orgPlan) {
      case 'executive':    return '💎 Executive';
      case 'professional': return '⭐ Professional';
      default:             return '⚠️ No Plan';
    }
  };

  return (
    <div className="flex min-h-[calc(100vh-56px)]">

      {/* ── Sidebar ── */}
      <aside className="w-56 bg-white border-r border-border/50 flex-shrink-0 flex flex-col">
        <div className="px-5 py-4 border-b border-border/40">
          <p className="text-[11px] font-semibold uppercase tracking-widest text-slate-400 mb-0.5">{sectionConfig.eyebrow}</p>
          <p className="text-base font-extrabold text-slate-900 tracking-tight">{sectionConfig.title}</p>
        </div>

        <nav className="flex-1 py-3 px-2 space-y-0.5">
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
                  onClick={() => { if (!locked) handleTabChange(tab.id); }}
                  className={cn(
                    'w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm transition-all duration-150 group relative',
                    locked
                      ? 'text-slate-400 cursor-not-allowed'
                      : isActive
                        ? 'bg-primary/8 text-primary font-semibold'
                        : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900 font-medium'
                  )}
                >
                  {isActive && !locked && (
                    <span className="absolute left-0 top-1/2 -translate-y-1/2 w-0.5 h-5 bg-primary rounded-r-full" />
                  )}
                  <span className={cn(
                    'shrink-0 transition-colors',
                    locked ? 'text-slate-400' : isActive ? 'text-primary' : 'text-slate-400 group-hover:text-slate-600'
                  )}>
                    <Icon className="w-4 h-4" />
                  </span>
                  <div className="flex-1 text-left min-w-0">
                    <p className="truncate">{tab.label}</p>
                    <p className={cn(
                      'text-[10px] font-medium truncate',
                      locked ? 'text-slate-400' : isActive ? 'text-primary/60' : 'text-slate-400'
                    )}>
                      {locked
                        ? (hasNoPlan ? 'Requires subscription' : 'Executive plan')
                        : tab.description}
                    </p>
                  </div>
                  {locked && <Lock className="w-3 h-3 text-slate-400 shrink-0" />}
                </button>
              );
            })
          )}
        </nav>

        {/* Plan badge */}
        {!loading && (
          <div className="px-4 py-3 border-t border-border/40">
            <div className={cn(
              'text-xs font-semibold px-2.5 py-1.5 rounded-lg text-center',
              orgPlan === 'executive'    ? 'bg-primary/8 text-primary'
              : orgPlan === 'professional' ? 'bg-amber-50 text-amber-600'
              : 'bg-red-50 text-red-600'
            )}>
              {getPlanLabel()}
            </div>
            {orgPlan === 'professional' && (
              <a href="/account/billing" className="block text-center text-[11px] text-slate-400 hover:text-primary mt-1.5 transition-colors">
                Upgrade for more features →
              </a>
            )}
            {hasNoPlan && (
              <a href="/account/billing" className="block text-center text-[11px] text-red-400 hover:text-red-600 mt-1.5 transition-colors">
                Subscribe now →
              </a>
            )}
          </div>
        )}
      </aside>

      {/* ── Main Content ── */}
      <main className="flex-1 pt-2 px-6 pb-6 bg-slate-50 overflow-auto min-w-0">
        {loading ? (
          <ContentSkeleton />
        ) : hasNoPlan ? (
          <SubscribePrompt />
        ) : (
          <>
            {(() => {
              const tab = sectionTabs.find((t) => t.id === activeTab);
              const locked = tab ? isTabLocked(tab) : false;
              if (locked) return <UpgradePrompt featureName={getLockedFeatureName(activeTab)} />;
              return (
                <>
                  {activeTab === 'timesheet' && (
                    <div className="space-y-4">
                      <WeekCoverage />
                      <WeeklyTimesheet />
                    </div>
                  )}
                  {activeTab === 'approvals' && <ApprovalQueue />}
                  {activeTab === 'fees'      && <FeeBasis />}
                  {activeTab === 'billing'   && <ClientSummary />}
                  {activeTab === 'invoices'  && (
                    <div className="space-y-6">
                      <InvoiceManager
                        filter={invoiceFilter}
                        onFilterClear={() => {
                          setInvoiceFilter('');
                          setSearchParams({ tab: 'invoices' });
                        }}
                      />
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