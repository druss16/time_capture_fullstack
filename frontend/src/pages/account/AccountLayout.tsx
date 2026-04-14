// src/pages/account/AccountLayout.tsx
// Account settings layout — styled to match billing/settings sections
// Uses same bg-slate-50 + bg-white rounded-xl card pattern as the rest of the app

import React from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import { User, CreditCard, KeyRound, Download, Bell, ChevronRight } from 'lucide-react';
import { cn } from '@/lib/design-system';

interface AccountLayoutProps {
  role: 'owner' | 'admin' | 'manager' | 'member';
  mdmManaged?: boolean;
}

interface NavItem {
  path: string;
  label: string;
  description: string;
  icon: React.ComponentType<{ className?: string }>;
  exact?: boolean;
}

export default function AccountLayout({ role, mdmManaged }: AccountLayoutProps) {
  const location = useLocation();

  const navItems: NavItem[] = [
    { path: '/account',               label: 'Profile',               description: 'Name, email, personal info',    icon: User,      exact: true },
    { path: '/account/notifications', label: 'Notifications',         description: 'Email and desktop alerts',      icon: Bell               },
    { path: '/account/password',      label: 'Password',              description: 'Change your password',          icon: KeyRound           },
    { path: '/account/download',      label: 'Desktop Agent',         description: 'Download and pair your device', icon: Download           },
    ...(role === 'owner' ? [{
      path: '/account/billing',       label: 'Subscription & Billing', description: 'Plan, seats, and payments',    icon: CreditCard,
    }] : []),
  ].filter(item => !(item.path === '/account/download' && mdmManaged));

  return (
    // Fills the content area provided by the app shell — no extra page wrapper
    <div className="flex gap-6 h-full min-h-0">

      {/* ── Left nav ─────────────────────────────────────────────────────── */}
      <aside className="w-56 shrink-0 flex flex-col gap-1 pt-0.5">
        <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-400 px-2 mb-1">
          Account
        </p>

        {navItems.map((item) => {
          const isActive = item.exact
            ? location.pathname === item.path
            : location.pathname.startsWith(item.path);

          return (
            <NavLink
              key={item.path}
              to={item.path}
              end={item.exact}
              className={cn(
                'group flex items-center gap-3 px-3 py-2.5 rounded-xl transition-all relative',
                isActive
                  ? 'bg-white border border-border/60 shadow-sm'
                  : 'hover:bg-white/60 border border-transparent'
              )}
            >
              {/* Active left accent */}
              <div className={cn(
                'absolute left-0 top-2 bottom-2 w-0.5 rounded-r transition-all',
                isActive ? 'bg-primary' : 'bg-transparent'
              )} />

              <div className={cn(
                'w-7 h-7 rounded-lg flex items-center justify-center shrink-0 transition-colors',
                isActive
                  ? 'bg-primary text-white'
                  : 'bg-slate-100 text-slate-400 group-hover:bg-slate-200'
              )}>
                <item.icon className="w-3.5 h-3.5" />
              </div>

              <div className="flex-1 min-w-0">
                <p className={cn(
                  'text-sm font-semibold leading-tight truncate',
                  isActive ? 'text-slate-800' : 'text-slate-600'
                )}>
                  {item.label}
                </p>
                <p className="text-[10px] text-slate-400 truncate mt-0.5">{item.description}</p>
              </div>
            </NavLink>
          );
        })}
      </aside>

      {/* ── Content ──────────────────────────────────────────────────────── */}
      <main className="flex-1 min-w-0 min-h-0 overflow-y-auto">
        <Outlet />
      </main>

    </div>
  );
}