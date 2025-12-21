/**
 * Navigation.tsx - Dark header navigation
 * Uses dark slate header (intentional) + shadcn variables for content
 */
import React, { useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthProvider";
import { 
  Users, 
  Receipt, 
  Calendar, 
  Monitor, 
  Settings, 
  LogOut,
  Clock
} from 'lucide-react';
import { safeFetchJson, API_BASE } from "@/lib/api";
import { cn, getRoleColor } from "@/lib/design-system";

interface UserInfo {
  username: string;
  email: string;
  role: 'owner' | 'admin' | 'manager' | 'member' | null;
  org_name: string | null;
  is_authenticated: boolean;
}

export default function Navigation() {
  const location = useLocation();
  const navigate = useNavigate();
  const { logout } = useAuth();
  const [userInfo, setUserInfo] = useState<UserInfo | null>(null);

  useEffect(() => {
    safeFetchJson(`${API_BASE}/whoami/`)
      .then(data => setUserInfo(data))
      .catch(console.error);
  }, []);

  const userRole = userInfo?.role;
  const canAccessSettings = ['owner', 'admin'].includes(userRole || '');
  const isActive = (path: string) => location.pathname === path || location.pathname.startsWith(path + '/');

  const navItems = [
    { path: '/daily', label: 'Daily Review', icon: Calendar },
    { path: '/billing', label: 'Billing', icon: Receipt },
    { path: '/devices', label: 'Devices', icon: Monitor },
    { path: '/clients', label: 'Clients', icon: Users },
  ];

  return (
    <nav className="bg-slate-800 text-white shadow-xl">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-14">
          {/* Left: Logo + Nav */}
          <div className="flex items-center gap-8">
            {/* Logo */}
            <Link to="/" className="flex items-center gap-2.5 group">
              <div className="w-9 h-9 rounded-lg bg-primary flex items-center justify-center shadow-lg shadow-primary/30 group-hover:opacity-90 transition-opacity">
                <Clock className="w-5 h-5 text-primary-foreground" />
              </div>
              <div className="hidden sm:block">
                <span className="text-base font-bold text-white tracking-tight">TimeTracker</span>
                <span className="text-xs text-slate-400 block -mt-0.5">by MavOps</span>
              </div>
            </Link>

            {/* Nav Links */}
            <div className="hidden md:flex items-center gap-1">
              {navItems.map((item) => {
                const Icon = item.icon;
                const active = isActive(item.path);
                
                return (
                  <Link
                    key={item.path}
                    to={item.path}
                    className={cn(
                      'flex items-center gap-2 px-3.5 py-2 rounded-xl',
                      'text-sm font-semibold transition-all duration-200',
                      active 
                        ? 'bg-primary text-primary-foreground shadow-lg shadow-primary/30' 
                        : 'text-slate-300 hover:text-white hover:bg-slate-700'
                    )}
                  >
                    <Icon className="w-4 h-4" />
                    {item.label}
                  </Link>
                );
              })}
              
              {canAccessSettings && (
                <Link
                  to="/settings"
                  className={cn(
                    'flex items-center gap-2 px-3.5 py-2 rounded-xl',
                    'text-sm font-semibold transition-all duration-200',
                    isActive('/settings')
                      ? 'bg-primary text-primary-foreground shadow-lg shadow-primary/30' 
                      : 'text-slate-300 hover:text-white hover:bg-slate-700'
                  )}
                >
                  <Settings className="w-4 h-4" />
                  Settings
                </Link>
              )}
            </div>
          </div>

          {/* Right: Date + User + Logout */}
          <div className="flex items-center gap-4">
            <span className="hidden lg:block text-sm text-slate-400 font-medium">
              {new Date().toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })}
            </span>

            {userInfo && (
              <div className="flex items-center gap-2.5">
                <div className="w-8 h-8 rounded-full bg-slate-600 flex items-center justify-center text-sm font-bold text-white">
                  {userInfo.username.charAt(0).toUpperCase()}
                </div>
                <div className="hidden md:block">
                  <p className="text-sm font-semibold text-white leading-none">{userInfo.username}</p>
                  {userInfo.org_name && <p className="text-xs text-slate-400">{userInfo.org_name}</p>}
                </div>
                {userRole && userRole !== 'member' && (
                  <span className={cn('text-xs px-2 py-0.5 rounded font-semibold', getRoleColor(userRole))}>
                    {userRole.charAt(0).toUpperCase() + userRole.slice(1)}
                  </span>
                )}
              </div>
            )}

            <button
              onClick={async () => { await logout(); navigate("/login"); }}
              className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium text-slate-300 hover:text-white hover:bg-slate-700 transition-all"
            >
              <LogOut className="w-4 h-4" />
              <span className="hidden sm:inline">Logout</span>
            </button>
          </div>
        </div>
      </div>

      {/* Mobile Navigation */}
      <div className="md:hidden border-t border-slate-700 bg-slate-900">
        <div className="px-2 py-2 flex items-center gap-1 overflow-x-auto scrollbar-hide">
          {navItems.map((item) => {
            const Icon = item.icon;
            const active = isActive(item.path);
            return (
              <Link
                key={item.path}
                to={item.path}
                className={cn(
                  'flex items-center gap-1.5 px-3 py-2 rounded-lg whitespace-nowrap',
                  'text-sm font-semibold transition-all',
                  active ? 'bg-primary text-primary-foreground' : 'text-slate-400 hover:text-white hover:bg-slate-700'
                )}
              >
                <Icon className="w-4 h-4" />
                {item.label}
              </Link>
            );
          })}
          {canAccessSettings && (
            <Link
              to="/settings"
              className={cn(
                'flex items-center gap-1.5 px-3 py-2 rounded-lg whitespace-nowrap',
                'text-sm font-semibold transition-all',
                isActive('/settings') ? 'bg-primary text-primary-foreground' : 'text-slate-400 hover:text-white hover:bg-slate-700'
              )}
            >
              <Settings className="w-4 h-4" />
              Settings
            </Link>
          )}
        </div>
      </div>
    </nav>
  );
}