/**
 * BillingPage.tsx - With Plan-Based Feature Gating
 * Starter plan: My Timesheet, Approvals only
 * Professional plan: All features
 */
import React, { useState, useEffect } from 'react';
import { safeFetchJson, API_BASE } from '@/lib/api';
import WeeklyTimesheet from '@/components/WeeklyTimesheet';
import ApprovalQueue from '@/components/ApprovalQueue';
import ClientSummary from '@/components/ClientSummary';
import ClientProfitability from '@/components/ClientProfitability';
import TimesheetHistory from '@/components/TimesheetHistory';
import { 
  Clock, 
  CheckSquare, 
  DollarSign, 
  TrendingUp, 
  FileText,
  ChevronRight,
  Lock,
  Sparkles,
} from 'lucide-react';
import { cn, getRoleColor, SKELETON } from '@/lib/design-system';

type UserRole = 'owner' | 'admin' | 'manager' | 'member';
type PlanType = 'trial' | 'starter' | 'professional' | 'enterprise';

interface Tab {
  id: string;
  label: string;
  icon: React.ElementType;
  description: string;
  requiredRoles: UserRole[];
  requiredPlan?: PlanType[]; // Plans that can access this tab
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
  plan: PlanType;
  trial_ends_at: string | null;
}

// Define which plans can access which features
const PROFESSIONAL_PLANS: PlanType[] = ['professional', 'enterprise'];
const ALL_PLANS: PlanType[] = ['trial', 'starter', 'professional', 'enterprise'];

const ALL_TABS: Tab[] = [
  { 
    id: 'timesheet', 
    label: 'My Timesheet', 
    description: 'View and submit your weekly hours', 
    requiredRoles: ['owner', 'admin', 'manager', 'member'], 
    icon: Clock,
    requiredPlan: ALL_PLANS,
  },
  { 
    id: 'approvals', 
    label: 'Approvals', 
    description: 'Review and approve team timesheets', 
    requiredRoles: ['owner', 'admin', 'manager'], 
    icon: CheckSquare,
    requiredPlan: ALL_PLANS,
  },
  { 
    id: 'billing', 
    label: 'Client Billing', 
    description: 'Prepare invoices by client', 
    requiredRoles: ['owner', 'admin'], 
    icon: DollarSign,
    requiredPlan: PROFESSIONAL_PLANS, // Professional only
  },
  { 
    id: 'profitability', 
    label: 'Profitability', 
    description: 'Analyze margins and efficiency', 
    requiredRoles: ['owner', 'admin'], 
    icon: TrendingUp,
    requiredPlan: PROFESSIONAL_PLANS, // Professional only
  },
  { 
    id: 'history', 
    label: 'History', 
    description: 'View approved and locked timesheets', 
    requiredRoles: ['owner', 'admin', 'manager'], 
    icon: FileText,
    requiredPlan: PROFESSIONAL_PLANS, // Professional only
  },
];

// Loading skeleton for sidebar
const SidebarSkeleton = () => (
  <div className="space-y-2">
    {[1, 2, 3, 4].map(i => (
      <div key={i} className={cn(SKELETON.base, 'h-14 w-full rounded-xl')} />
    ))}
  </div>
);

// Loading skeleton for content
const ContentSkeleton = () => (
  <div className="space-y-4">
    <div className={cn(SKELETON.heading, 'w-48')} />
    <div className="space-y-3">
      {[1, 2, 3, 4, 5].map(i => (
        <div key={i} className={cn(SKELETON.row, 'w-full')} />
      ))}
    </div>
  </div>
);

// Upgrade prompt component for locked features
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
      <h3 className="text-xl font-extrabold text-slate-900 mb-2">
        {featureName}
      </h3>
      <p className="text-slate-600 font-medium mb-6">
        This feature is available on the <span className="font-bold text-primary">Professional</span> plan.
        Upgrade to unlock advanced billing and profitability tools.
      </p>
      <a
        href="/settings?tab=billing"
        className="inline-flex items-center gap-2 px-6 py-3 bg-primary text-white font-bold rounded-xl hover:opacity-90 transition-all shadow-lg shadow-primary/25"
      >
        <Sparkles className="w-5 h-5" />
        Upgrade to Professional
      </a>
      <p className="text-sm text-slate-500 font-medium mt-4">
        Starting at $49.99/user/month
      </p>
    </div>
  </div>
);

const BillingPage: React.FC = () => {
  const [activeTab, setActiveTab] = useState<string>('timesheet');
  const [userInfo, setUserInfo] = useState<WhoamiResponse | null>(null);
  const [orgPlan, setOrgPlan] = useState<PlanType>('starter');
  const [loading, setLoading] = useState(true);
  
  useEffect(() => {
    const fetchUserInfo = async () => {
      try {
        const response = await safeFetchJson<WhoamiResponse>(`${API_BASE}/whoami/`);
        setUserInfo(response);
        
        // Fetch org info to get plan
        if (response.org_id) {
          try {
            const orgResponse = await safeFetchJson<OrgResponse>(`${API_BASE}/settings/org/`);
            setOrgPlan(orgResponse.plan || 'starter');
          } catch (err) {
            console.error('Failed to fetch org info:', err);
            setOrgPlan('starter'); // Default to starter if can't fetch
          }
        }
        
        if (response.role) {
          const currentTab = ALL_TABS.find(t => t.id === activeTab);
          if (currentTab && !currentTab.requiredRoles.includes(response.role)) {
            setActiveTab('timesheet');
          }
        }
      } catch (err) {
        console.error('Failed to fetch user info:', err);
        setUserInfo({ username: 'Unknown', email: '', role: 'member', org_name: null, org_id: null, is_authenticated: true });
      } finally {
        setLoading(false);
      }
    };
    
    fetchUserInfo();
  }, []);
  
  const userRole = userInfo?.role || 'member';
  
  // Filter tabs by role (but show locked tabs for plan restrictions)
  const visibleTabs = ALL_TABS.filter(tab => tab.requiredRoles.includes(userRole));
  
  // Check if a tab is locked due to plan restrictions
  const isTabLocked = (tab: Tab): boolean => {
    if (!tab.requiredPlan) return false;
    return !tab.requiredPlan.includes(orgPlan);
  };
  
  // Get the feature name for locked tab display
  const getLockedFeatureName = (tabId: string): string => {
    switch (tabId) {
      case 'billing': return 'Client Billing';
      case 'profitability': return 'Profitability Analysis';
      case 'history': return 'Timesheet History';
      default: return 'This Feature';
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
              const isLocked = isTabLocked(tab);
              
              return (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={cn(
                    'w-full flex items-center gap-3 px-3 py-2.5 rounded-xl',
                    'text-sm font-bold transition-all duration-200',
                    'group border-2',
                    isLocked
                      ? 'text-slate-400 border-transparent hover:bg-slate-50'
                      : isActive 
                        ? 'bg-primary/10 text-primary border-primary/30' 
                        : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900 border-transparent'
                  )}
                >
                  <div className={cn(
                    'w-8 h-8 rounded-lg flex items-center justify-center transition-colors relative',
                    isLocked
                      ? 'bg-slate-100 text-slate-400'
                      : isActive 
                        ? 'bg-primary text-white' 
                        : 'bg-slate-200 text-slate-600 group-hover:bg-slate-300'
                  )}>
                    <Icon className="w-4 h-4" />
                    {isLocked && (
                      <div className="absolute -top-1 -right-1 w-4 h-4 bg-slate-300 rounded-full flex items-center justify-center">
                        <Lock className="w-2.5 h-2.5 text-slate-500" />
                      </div>
                    )}
                  </div>
                  <div className="flex-1 text-left">
                    <span className={cn('block', isLocked && 'text-slate-400')}>{tab.label}</span>
                    <span className={cn(
                      'text-xs font-semibold',
                      isLocked
                        ? 'text-slate-400'
                        : isActive 
                          ? 'text-primary/70' 
                          : 'text-slate-500'
                    )}>
                      {isLocked ? 'Professional plan' : tab.description}
                    </span>
                  </div>
                  {isActive && !isLocked && <ChevronRight className="w-4 h-4 text-primary" />}
                  {isLocked && (
                    <Lock className="w-4 h-4 text-slate-400" />
                  )}
                </button>
              );
            })
          )}
        </nav>

        {/* Plan Badge */}
        {!loading && (
          <div className="px-3 pb-2">
            <div className={cn(
              'px-3 py-2 rounded-xl text-center',
              orgPlan === 'professional' || orgPlan === 'enterprise'
                ? 'bg-primary/10 border-2 border-primary/20'
                : 'bg-amber-50 border-2 border-amber-200'
            )}>
              <p className={cn(
                'text-xs font-bold',
                orgPlan === 'professional' || orgPlan === 'enterprise'
                  ? 'text-primary'
                  : 'text-amber-700'
              )}>
                {orgPlan === 'trial' ? '🎁 Trial' : 
                 orgPlan === 'starter' ? '⭐ Starter Plan' :
                 orgPlan === 'professional' ? '💎 Professional' : '🏢 Enterprise'}
              </p>
              {(orgPlan === 'starter' || orgPlan === 'trial') && (
                <a 
                  href="/settings?tab=billing" 
                  className="text-xs text-amber-600 font-semibold hover:underline"
                >
                  Upgrade for more features
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
                {userInfo.org_name && <p className="text-xs text-slate-600 font-medium truncate">{userInfo.org_name}</p>}
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
        ) : (
          <>
            {/* Check if active tab is locked */}
            {isTabLocked(ALL_TABS.find(t => t.id === activeTab)!) ? (
              <UpgradePrompt featureName={getLockedFeatureName(activeTab)} />
            ) : (
              <>
                {activeTab === 'timesheet' && <WeeklyTimesheet />}
                {activeTab === 'approvals' && <ApprovalQueue />}
                {activeTab === 'billing' && <ClientSummary />}
                {activeTab === 'profitability' && <ClientProfitability />}
                {activeTab === 'history' && <TimesheetHistory />}
              </>
            )}
          </>
        )}
      </main>
    </div>
  );
};

export default BillingPage;