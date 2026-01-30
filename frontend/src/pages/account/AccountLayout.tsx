// src/pages/account/AccountLayout.tsx
/**
 * Shared layout for account settings pages
 * Shows sidebar navigation for: Profile, Download, Password, Billing (owner)
 */

import React from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import { User, CreditCard, KeyRound, ArrowLeft, Download } from 'lucide-react';

interface AccountLayoutProps {
  role: 'owner' | 'admin' | 'manager' | 'member';
}

export default function AccountLayout({ role }: AccountLayoutProps) {
  const navItems = [
    { path: '/account', label: 'Profile', icon: User, exact: true },
    { path: '/account/download', label: 'Download Agent', icon: Download },
    { path: '/account/password', label: 'Change Password', icon: KeyRound },
    // Billing only for owners
    ...(role === 'owner' ? [{ path: '/account/billing', label: 'Subscription & Billing', icon: CreditCard }] : []),
  ];

  return (
    <div className="min-h-screen bg-slate-50">
      <div className="max-w-5xl mx-auto px-4 py-8">
        {/* Back Link */}
        <NavLink 
          to="/daily" 
          className="inline-flex items-center gap-2 text-slate-600 hover:text-emerald-600 font-medium mb-6 group"
        >
          <ArrowLeft className="w-4 h-4 group-hover:-translate-x-1 transition-transform" />
          Back to Dashboard
        </NavLink>

        <div className="flex flex-col md:flex-row gap-8">
          {/* Sidebar Navigation */}
          <aside className="md:w-64 flex-shrink-0">
            <h1 className="text-xl font-bold text-slate-900 mb-4">Account Settings</h1>
            <nav className="space-y-1">
              {navItems.map((item) => (
                <NavLink
                  key={item.path}
                  to={item.path}
                  end={item.exact}
                  className={({ isActive }) => `
                    flex items-center gap-3 px-4 py-2.5 rounded-xl font-medium transition-all
                    ${isActive 
                      ? 'bg-emerald-50 text-emerald-700 border-2 border-emerald-200' 
                      : 'text-slate-600 hover:bg-slate-100 border-2 border-transparent'}
                  `}
                >
                  <item.icon className="w-5 h-5" />
                  {item.label}
                </NavLink>
              ))}
            </nav>
          </aside>

          {/* Main Content */}
          <main className="flex-1">
            <Outlet />
          </main>
        </div>
      </div>
    </div>
  );
}