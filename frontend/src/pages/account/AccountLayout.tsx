// src/pages/account/AccountLayout.tsx
/**
 * Shared layout for account settings pages
 * Sidebar navigation for: Profile, Notifications, Desktop Agent, Password, Billing (owner)
 */

import React from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import {
  User,
  CreditCard,
  KeyRound,
  ArrowLeft,
  Download,
  Bell,
  ChevronRight,
} from 'lucide-react';

interface AccountLayoutProps {
  role: 'owner' | 'admin' | 'manager' | 'member';
}

interface NavItem {
  path: string;
  label: string;
  description: string;
  icon: React.ComponentType<{ className?: string }>;
  exact?: boolean;
}

export default function AccountLayout({ role }: AccountLayoutProps) {
  const location = useLocation();

  const navItems: NavItem[] = [
    {
      path: '/account',
      label: 'Profile',
      description: 'Name, email, and personal info',
      icon: User,
      exact: true,
    },
    {
      path: '/account/notifications',
      label: 'Notifications',
      description: 'Email and desktop alerts',
      icon: Bell,
    },
    {
      path: '/account/download',
      label: 'Desktop Agent',
      description: 'Download and pair your device',
      icon: Download,
    },
    {
      path: '/account/password',
      label: 'Password',
      description: 'Change your password',
      icon: KeyRound,
    },
    // Billing only for owners
    ...(role === 'owner'
      ? [
          {
            path: '/account/billing',
            label: 'Subscription & Billing',
            description: 'Plan, seats, and payments',
            icon: CreditCard,
          },
        ]
      : []),
  ];

  return (
    <div className="bg-slate-50 min-h-0">
      <div className="max-w-5xl mx-auto px-4 py-8">
        <div className="flex flex-col md:flex-row gap-8">
          {/* ── Sidebar Navigation ── */}
          <aside className="md:w-72 flex-shrink-0">
            <h1 className="text-2xl font-extrabold text-slate-900 mb-1">Account Settings</h1>
            <p className="text-sm text-slate-500 mb-5">Manage your account and preferences</p>

            <nav className="bg-white rounded-2xl border-2 border-slate-200 shadow-sm overflow-hidden">
              {navItems.map((item, idx) => {
                // Determine active state
                const isActive = item.exact
                  ? location.pathname === item.path
                  : location.pathname.startsWith(item.path);

                return (
                  <NavLink
                    key={item.path}
                    to={item.path}
                    end={item.exact}
                    className={`
                      flex items-center gap-3 px-5 py-4 transition-all
                      ${idx < navItems.length - 1 ? 'border-b border-slate-100' : ''}
                      ${isActive
                        ? 'bg-teal-50 border-l-4 border-l-teal-500'
                        : 'border-l-4 border-l-transparent hover:bg-slate-50'
                      }
                    `}
                  >
                    <div
                      className={`
                        w-9 h-9 rounded-xl flex items-center justify-center shrink-0
                        ${isActive ? 'bg-teal-100 text-teal-600' : 'bg-slate-100 text-slate-400'}
                      `}
                    >
                      <item.icon className="w-[18px] h-[18px]" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div
                        className={`text-sm font-bold ${
                          isActive ? 'text-teal-700' : 'text-slate-700'
                        }`}
                      >
                        {item.label}
                      </div>
                      <div className="text-xs text-slate-400 truncate">
                        {item.description}
                      </div>
                    </div>
                    <ChevronRight
                      className={`w-4 h-4 shrink-0 ${
                        isActive ? 'text-teal-400' : 'text-slate-300'
                      }`}
                    />
                  </NavLink>
                );
              })}
            </nav>
          </aside>

          {/* ── Main Content ── */}
          <main className="flex-1 min-w-0">
            <Outlet />
          </main>
        </div>
      </div>
    </div>
  );
}