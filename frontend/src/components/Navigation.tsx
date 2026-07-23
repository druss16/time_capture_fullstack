/**
 * Navigation.tsx - Dark header navigation with UserMenu dropdown
 * Uses dark slate header (intentional) + shadcn variables for content
 */
import React, { useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthProvider";
import {
  Users,
  Receipt,
  Calendar,
  Clock,
  Monitor,
  Settings,
  LogOut,
  ChevronDown,
  User,
  Building2,
  Download,
  BarChart2,
  PieChart,
} from 'lucide-react';

import { safeFetchJson, API_BASE } from "@/lib/api";

import { cn, getRoleColor } from "@/lib/design-system";

interface UserInfo {
  username: string;
  email: string;
  first_name?: string;
  last_name?: string;
  role: 'owner' | 'admin' | 'manager' | 'member' | null;
  org_name: string | null;
  is_authenticated: boolean;
  mdm_managed?: boolean;
}

export default function Navigation() {
  const location = useLocation();
  const navigate = useNavigate();
  const { logout } = useAuth();
  const [userInfo, setUserInfo] = useState<UserInfo | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    safeFetchJson(`${API_BASE}/whoami/`)
      .then(data => setUserInfo(data))
      .catch(() => {});
  }, []);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      const target = e.target as HTMLElement;
      if (!target.closest('[data-user-menu]')) setMenuOpen(false);
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setMenuOpen(false);
    };
    document.addEventListener('keydown', handleEscape);
    return () => document.removeEventListener('keydown', handleEscape);
  }, []);

  const userRole = userInfo?.role;
  const canAccessSettings  = ['owner', 'admin'].includes(userRole || '');
  const canAccessAnalytics = ['owner', 'admin', 'manager'].includes(userRole || '');
  const canAccessBilling   = ['owner', 'admin'].includes(userRole || '');
  const mdmManaged = userInfo?.mdm_managed || false;
  const isActive = (path: string) => location.pathname === path || location.pathname.startsWith(path + '/');

  const handleLogout = async () => {
    setMenuOpen(false);
    await logout();
    navigate("/login");
  };

  const handleNavigation = (path: string) => {
    setMenuOpen(false);
    navigate(path);
  };

  const impersonatingUserName = localStorage.getItem("impersonating_user_name");
  const impersonatingOrgName  = localStorage.getItem("impersonating_org_name");

  const displayName = impersonatingUserName
    ? impersonatingUserName
    : userInfo?.first_name 
      ? `${userInfo.first_name} ${userInfo.last_name || ''}`.trim()
      : userInfo?.username || '';

  const orgDisplayName = impersonatingUserName
    ? impersonatingOrgName || userInfo?.org_name
    : userInfo?.org_name;

  const initials = impersonatingUserName
    ? impersonatingUserName.charAt(0).toUpperCase()
    : userInfo?.first_name 
      ? `${userInfo.first_name[0]}${userInfo.last_name?.[0] || ''}`.toUpperCase()
      : userInfo?.username?.charAt(0).toUpperCase() || '?';

  const navItems = [
    { path: '/daily',     label: 'Daily Review', icon: Calendar,  show: true                },
    { path: '/timesheet', label: 'Timesheet',    icon: Clock,     show: true                },
    { path: '/billing',   label: 'Billing',      icon: Receipt,   show: canAccessBilling    },
    { path: '/reports',   label: 'Reports',      icon: PieChart,  show: true                },
    { path: '/analytics', label: 'Analytics',    icon: BarChart2, show: canAccessAnalytics  },
  ].filter(item => item.show);

  const navLinkCls = (active: boolean) => cn(
    'flex items-center gap-2 px-3.5 py-2 rounded-xl',
    'text-sm font-semibold transition-all duration-200',
    active
      ? 'bg-primary text-primary-foreground shadow-lg shadow-primary/30'
      : 'text-slate-300 hover:text-white hover:bg-slate-700'
  );

  const mobileLinkCls = (active: boolean) => cn(
    'flex items-center gap-1.5 px-3 py-2 rounded-lg whitespace-nowrap',
    'text-sm font-semibold transition-all',
    active ? 'bg-primary text-primary-foreground' : 'text-slate-400 hover:text-white hover:bg-slate-700'
  );

  return (
    <nav className="bg-slate-800 text-white shadow-xl">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-14">

          {/* Left: Logo + Nav */}
          <div className="flex items-center gap-8">
            <Link to="/" className="flex items-center gap-2.5 group">
              <img src="/timetracker-icon-mono-white-blue.svg" alt="TimeTracker" className="w-9 h-9" />
              <div className="hidden sm:block">
                <span className="text-base font-bold text-white tracking-tight">TimeTracker</span>
                <span className="text-xs text-slate-400 block -mt-0.5">by MavOps</span>
              </div>
            </Link>

            <div className="hidden md:flex items-center gap-1">
              {navItems.map(({ path, label, icon: Icon }) => (
                <Link key={path} to={path} className={navLinkCls(isActive(path))}>
                  <Icon className="w-4 h-4" />
                  {label}
                </Link>
              ))}
            </div>
          </div>

          {/* Right: Date + User Menu */}
          <div className="flex items-center gap-4">
            <span className="hidden lg:block text-sm text-slate-400 font-medium">
              {new Date().toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })}
            </span>

            {userInfo && (
              <div className="relative" data-user-menu>
                <button
                  onClick={() => setMenuOpen(!menuOpen)}
                  className="flex items-center gap-2.5 px-2 py-1.5 rounded-xl hover:bg-slate-700 transition-colors"
                >
                  <div className="w-8 h-8 rounded-full bg-primary flex items-center justify-center text-sm font-bold text-primary-foreground">
                    {initials}
                  </div>
                  <div className="hidden md:block text-left">
                    <p className="text-sm font-semibold text-white leading-none">{displayName}</p>
                    {orgDisplayName && <p className="text-xs text-slate-400">{orgDisplayName}</p>}
                  </div>
                  {userRole && userRole !== 'member' && (
                    <span className={cn('hidden sm:inline text-xs px-2 py-0.5 rounded font-semibold', getRoleColor(userRole))}>
                      {userRole.charAt(0).toUpperCase() + userRole.slice(1)}
                    </span>
                  )}
                  <ChevronDown className={cn('w-4 h-4 text-slate-400 transition-transform duration-200', menuOpen && 'rotate-180')} />
                </button>

                {menuOpen && (
                  <div className="absolute right-0 mt-2 w-56 bg-white rounded-xl shadow-xl border border-slate-200 py-2 z-50 animate-in fade-in slide-in-from-top-2 duration-200">
                    {/* Identity header */}
                    <div className="px-4 py-3 border-b border-slate-100">
                      <p className="font-semibold text-slate-900 text-sm leading-tight">{displayName}</p>
                      <p className="text-xs text-slate-400 mt-0.5">{userInfo.email}</p>
                      {userRole && (
                        <span className={cn('inline-flex mt-2 text-xs px-2 py-0.5 rounded font-semibold capitalize', getRoleColor(userRole))}>
                          {userRole}
                        </span>
                      )}
                    </div>

                    {/* Account links */}
                    <div className="py-1.5">
                      <button
                        onClick={() => handleNavigation('/account')}
                        className="w-full px-4 py-2 text-left flex items-center gap-3 hover:bg-slate-50 transition-colors"
                      >
                        <User className="w-4 h-4 text-slate-400" />
                        <span className="text-sm font-medium text-slate-700">Account</span>
                      </button>
                      {canAccessSettings && (
                        <button
                          onClick={() => handleNavigation('/settings')}
                          className="w-full px-4 py-2 text-left flex items-center gap-3 hover:bg-slate-50 transition-colors"
                        >
                          <Settings className="w-4 h-4 text-slate-400" />
                          <span className="text-sm font-medium text-slate-700">Settings</span>
                        </button>
                      )}
                      {!mdmManaged && (
                        <button
                          onClick={() => handleNavigation('/account/download')}
                          className="w-full px-4 py-2 text-left flex items-center gap-3 hover:bg-slate-50 transition-colors"
                        >
                          <Download className="w-4 h-4 text-slate-400" />
                          <span className="text-sm font-medium text-slate-700">Download Agent</span>
                        </button>
                      )}
                    </div>

                    {/* Sign out */}
                    <div className="border-t border-slate-100 py-1.5">
                      <button
                        onClick={handleLogout}
                        className="w-full px-4 py-2 text-left flex items-center gap-3 hover:bg-red-50 transition-colors group"
                      >
                        <LogOut className="w-4 h-4 text-slate-400 group-hover:text-red-500" />
                        <span className="text-sm font-medium text-slate-700 group-hover:text-red-600">Log Out</span>
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Mobile Navigation */}
      <div className="md:hidden border-t border-slate-700 bg-slate-900">
        <div className="px-2 py-2 flex items-center gap-1 overflow-x-auto scrollbar-hide">
          {navItems.map(({ path, label, icon: Icon }) => (
            <Link key={path} to={path} className={mobileLinkCls(isActive(path))}>
              <Icon className="w-4 h-4" />
              {label}
            </Link>
          ))}
        </div>
      </div>
    </nav>
  );
}