// src/pages/BillingPage.tsx
// Main billing page with tabs for timesheet, approvals, and client summary

import React, { useState } from 'react';
import { useAuth } from '@/auth/AuthProvider';
import WeeklyTimesheet from '@/components/WeeklyTimesheet';
import ApprovalQueue from '@/components/ApprovalQueue';
import ClientSummary from '@/components/ClientSummary';
import ClientProfitability from '@/components/ClientProfitability';

// ===============================
// TYPES
// ===============================

type UserRole = 'owner' | 'admin' | 'manager' | 'member';

interface Tab {
  id: string;
  label: string;
  icon: React.ReactNode;
}

// ===============================
// MAIN COMPONENT
// ===============================

const BillingPage: React.FC = () => {
  const [activeTab, setActiveTab] = useState<string>('timesheet');
  const { user } = useAuth();
  
  // Get role from auth - adjust property path based on your user object
  const userRole = (user?.role || user?.membership?.role || 'member') as UserRole;
  const isManager = ['owner', 'admin', 'manager'].includes(userRole);

  const tabs: Tab[] = [
    {
      id: 'timesheet',
      label: 'My Timesheet',
      icon: (
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
      ),
    },
    ...(isManager ? [
      {
        id: 'approvals',
        label: 'Approvals',
        icon: (
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" />
          </svg>
        ),
      },
      {
        id: 'billing',
        label: 'Client Billing',
        icon: (
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
        ),
      },
      {
        id: 'profitability',
        label: 'Profitability',
        icon: (
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
          </svg>
        ),
      },
    ] : []),
  ];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-slate-800">Time & Billing</h1>
        <p className="text-slate-500 mt-1">Track time, submit timesheets, and manage billing</p>
      </div>
      
      {/* Tabs */}
      <div className="border-b border-slate-200">
        <div className="flex gap-1">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
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
      <div>
        {activeTab === 'timesheet' && <WeeklyTimesheet />}
        {activeTab === 'approvals' && isManager && <ApprovalQueue />}
        {activeTab === 'billing' && isManager && <ClientSummary />}
        {activeTab === 'profitability' && isManager && <ClientProfitability />}
      </div>
    </div>
  );
};

export default BillingPage;