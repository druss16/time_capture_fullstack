/**
 * BillingPage.tsx - Sidebar layout with STRONGER FONTS
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
  ChevronRight
} from 'lucide-react';
import { cn, getRoleColor, SKELETON } from '@/lib/design-system';

type UserRole = 'owner' | 'admin' | 'manager' | 'member';

interface Tab {
  id: string;
  label: string;
  icon: React.ElementType;
  description: string;
  requiredRoles: UserRole[];
}

interface WhoamiResponse {
  username: string;
  email: string;
  role: UserRole | null;
  org_name: string | null;
  is_authenticated: boolean;
}

const ALL_TABS: Tab[] = [
  { id: 'timesheet', label: 'My Timesheet', description: 'View and submit your weekly hours', requiredRoles: ['owner', 'admin', 'manager', 'member'], icon: Clock },
  { id: 'approvals', label: 'Approvals', description: 'Review and approve team timesheets', requiredRoles: ['owner', 'admin', 'manager'], icon: CheckSquare },
  { id: 'billing', label: 'Client Billing', description: 'Prepare invoices by client', requiredRoles: ['owner', 'admin'], icon: DollarSign },
  { id: 'profitability', label: 'Profitability', description: 'Analyze margins and efficiency', requiredRoles: ['owner', 'admin'], icon: TrendingUp },
  { id: 'history', label: 'History', description: 'View approved and locked timesheets', requiredRoles: ['owner', 'admin', 'manager'], icon: FileText },
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

const BillingPage: React.FC = () => {
  const [activeTab, setActiveTab] = useState<string>('timesheet');
  const [userInfo, setUserInfo] = useState<WhoamiResponse | null>(null);
  const [loading, setLoading] = useState(true);
  
  useEffect(() => {
    const fetchUserInfo = async () => {
      try {
        const response = await safeFetchJson<WhoamiResponse>(`${API_BASE}/whoami/`);
        setUserInfo(response);
        
        if (response.role) {
          const currentTab = ALL_TABS.find(t => t.id === activeTab);
          if (currentTab && !currentTab.requiredRoles.includes(response.role)) {
            setActiveTab('timesheet');
          }
        }
      } catch (err) {
        console.error('Failed to fetch user info:', err);
        setUserInfo({ username: 'Unknown', email: '', role: 'member', org_name: null, is_authenticated: true });
      } finally {
        setLoading(false);
      }
    };
    
    fetchUserInfo();
  }, []);
  
  const userRole = userInfo?.role || 'member';
  const visibleTabs = ALL_TABS.filter(tab => tab.requiredRoles.includes(userRole));

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
              
              return (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={cn(
                    'w-full flex items-center gap-3 px-3 py-2.5 rounded-xl',
                    'text-sm font-bold transition-all duration-200',
                    'group border-2',
                    isActive 
                      ? 'bg-primary/10 text-primary border-primary/30' 
                      : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900 border-transparent'
                  )}
                >
                  <div className={cn(
                    'w-8 h-8 rounded-lg flex items-center justify-center transition-colors',
                    isActive ? 'bg-primary text-white' : 'bg-slate-200 text-slate-600 group-hover:bg-slate-300'
                  )}>
                    <Icon className="w-4 h-4" />
                  </div>
                  <div className="flex-1 text-left">
                    <span className="block">{tab.label}</span>
                    <span className={cn(
                      'text-xs font-semibold',
                      isActive ? 'text-primary/70' : 'text-slate-500'
                    )}>{tab.description}</span>
                  </div>
                  {isActive && <ChevronRight className="w-4 h-4 text-primary" />}
                </button>
              );
            })
          )}
        </nav>

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
            {activeTab === 'timesheet' && <WeeklyTimesheet />}
            {activeTab === 'approvals' && <ApprovalQueue />}
            {activeTab === 'billing' && <ClientSummary />}
            {activeTab === 'profitability' && <ClientProfitability />}
            {activeTab === 'history' && <TimesheetHistory />}
          </>
        )}
      </main>
    </div>
  );
};

export default BillingPage;