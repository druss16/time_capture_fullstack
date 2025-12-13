// src/pages/BillingPage.tsx
// Main billing page with tabs for timesheet, approvals, and client summary

import React, { useState, useEffect } from 'react';
import { safeFetchJson, API_BASE } from '@/lib/api';
import WeeklyTimesheet from '@/components/WeeklyTimesheet';
import ApprovalQueue from '@/components/ApprovalQueue';
import ClientSummary from '@/components/ClientSummary';
import ClientProfitability from '@/components/ClientProfitability';
import TimesheetHistory from '@/components/TimesheetHistory';

// ===============================
// TYPES
// ===============================

type UserRole = 'owner' | 'admin' | 'manager' | 'member';

interface Tab {
  id: string;
  label: string;
  icon: React.ReactNode;
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

// ===============================
// TAB CONFIGURATION
// ===============================

const ALL_TABS: Tab[] = [
  {
    id: 'timesheet',
    label: 'My Timesheet',
    description: 'View and submit your weekly hours',
    requiredRoles: ['owner', 'admin', 'manager', 'member'],
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
    ),
  },
  {
    id: 'approvals',
    label: 'Approvals',
    description: 'Review and approve team timesheets',
    requiredRoles: ['owner', 'admin', 'manager'],
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" />
      </svg>
    ),
  },
  {
    id: 'billing',
    label: 'Client Billing',
    description: 'Prepare invoices by client',
    requiredRoles: ['owner', 'admin'],
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
    ),
  },
  {
    id: 'profitability',
    label: 'Profitability',
    description: 'Analyze margins (revenue vs cost)',
    requiredRoles: ['owner', 'admin'],
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
      </svg>
    ),
  },
  {
    id: 'history',
    label: 'History',
    description: 'View approved and locked timesheets',
    requiredRoles: ['owner', 'admin', 'manager'],
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
      </svg>
    ),
  },
];

// ===============================
// MAIN COMPONENT
// ===============================

const BillingPage: React.FC = () => {
  const [activeTab, setActiveTab] = useState<string>('timesheet');
  const [userInfo, setUserInfo] = useState<WhoamiResponse | null>(null);
  const [loading, setLoading] = useState(true);
  
  // Fetch role from whoami endpoint (now includes role field)
  useEffect(() => {
    const fetchUserInfo = async () => {
      try {
        const response = await safeFetchJson<WhoamiResponse>(`${API_BASE}/whoami/`);
        console.log('BillingPage - whoami response:', response);
        setUserInfo(response);
        
        // If current tab is not accessible with user's role, switch to timesheet
        if (response.role) {
          const currentTab = ALL_TABS.find(t => t.id === activeTab);
          if (currentTab && !currentTab.requiredRoles.includes(response.role)) {
            setActiveTab('timesheet');
          }
        }
      } catch (err) {
        console.error('Failed to fetch user info:', err);
        // Default to member role if fetch fails
        setUserInfo({
          username: 'Unknown',
          email: '',
          role: 'member',
          org_name: null,
          is_authenticated: true,
        });
      } finally {
        setLoading(false);
      }
    };
    
    fetchUserInfo();
  }, []);
  
  const userRole = userInfo?.role || 'member';
  
  // Filter tabs based on user role
  const visibleTabs = ALL_TABS.filter(tab => tab.requiredRoles.includes(userRole));
  
  // Get current tab info
  const currentTab = ALL_TABS.find(t => t.id === activeTab);

  // Role badge styling
  const getRoleBadgeStyle = (role: UserRole): string => {
    const styles: Record<UserRole, string> = {
      owner: 'bg-purple-100 text-purple-700',
      admin: 'bg-blue-100 text-blue-700',
      manager: 'bg-green-100 text-green-700',
      member: 'bg-slate-100 text-slate-700',
    };
    return styles[role] || styles.member;
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex justify-between items-start">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">Time & Billing</h1>
          <p className="text-slate-500 mt-1">
            {currentTab?.description || 'Track time, submit timesheets, and manage billing'}
          </p>
        </div>
        
        {/* User info with role badge */}
        {userInfo && (
          <div className="flex items-center gap-2">
            <span className="text-sm text-slate-600">{userInfo.username}</span>
            <span className={`text-xs px-2 py-1 rounded font-medium ${getRoleBadgeStyle(userRole)}`}>
              {userRole.charAt(0).toUpperCase() + userRole.slice(1)}
            </span>
          </div>
        )}
      </div>
      
      {loading ? (
        <div className="flex items-center justify-center py-12">
          <div className="flex flex-col items-center gap-3">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
            <span className="text-slate-500">Loading...</span>
          </div>
        </div>
      ) : (
        <>
          {/* Tabs */}
          <div className="border-b border-slate-200">
            <div className="flex gap-1">
              {visibleTabs.map((tab) => (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  title={tab.description}
                  className={`flex items-center gap-2 px-5 py-3 font-medium rounded-t-lg transition-colors ${
                    activeTab === tab.id
                      ? 'bg-white text-blue-600 border-t-2 border-x border-blue-500 border-slate-200 -mb-px'
                      : 'text-slate-600 hover:bg-slate-50'
                  }`}
                >
                  {tab.icon}
                  {tab.label}
                </button>
              ))}
            </div>
          </div>

          {/* Content */}
          <div className="min-h-[500px]">
            {activeTab === 'timesheet' && <WeeklyTimesheet />}
            {activeTab === 'approvals' && <ApprovalQueue />}
            {activeTab === 'billing' && <ClientSummary />}
            {activeTab === 'profitability' && <ClientProfitability />}
            {activeTab === 'history' && <TimesheetHistory />}
          </div>
        </>
      )}
    </div>
  );
};

export default BillingPage;