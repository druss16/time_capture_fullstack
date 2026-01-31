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
  Monitor, 
  Settings, 
  LogOut,
  Clock,
  ChevronDown,
  User,
  CreditCard,
  KeyRound,
  Building2,
  Download
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
      .catch(console.error);
  }, []);

  // Close menu when clicking outside
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      const target = e.target as HTMLElement;
      if (!target.closest('[data-user-menu]')) {
        setMenuOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // Close menu on escape
  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setMenuOpen(false);
    };
    document.addEventListener('keydown', handleEscape);
    return () => document.removeEventListener('keydown', handleEscape);
  }, []);

  const userRole = userInfo?.role;
  const canAccessSettings = ['owner', 'admin'].includes(userRole || '');
  const isOwner = userRole === 'owner';
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

  // Display name: prefer first+last, fallback to username
  const displayName = userInfo?.first_name 
    ? `${userInfo.first_name} ${userInfo.last_name || ''}`.trim()
    : userInfo?.username || '';

  // Initials for avatar
  const initials = userInfo?.first_name 
    ? `${userInfo.first_name[0]}${userInfo.last_name?.[0] || ''}`.toUpperCase()
    : userInfo?.username?.charAt(0).toUpperCase() || '?';

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

          {/* Right: Date + User Menu */}
          <div className="flex items-center gap-4">
            <span className="hidden lg:block text-sm text-slate-400 font-medium">
              {new Date().toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })}
            </span>

            {/* User Menu Dropdown */}
            {userInfo && (
              <div className="relative" data-user-menu>
                <button
                  onClick={() => setMenuOpen(!menuOpen)}
                  className="flex items-center gap-2.5 px-2 py-1.5 rounded-xl hover:bg-slate-700 transition-colors"
                >
                  {/* Avatar */}
                  <div className="w-8 h-8 rounded-full bg-primary flex items-center justify-center text-sm font-bold text-primary-foreground">
                    {initials}
                  </div>
                  
                  {/* Name & Org */}
                  <div className="hidden md:block text-left">
                    <p className="text-sm font-semibold text-white leading-none">{displayName}</p>
                    {userInfo.org_name && <p className="text-xs text-slate-400">{userInfo.org_name}</p>}
                  </div>
                  
                  {/* Role Badge */}
                  {userRole && userRole !== 'member' && (
                    <span className={cn('hidden sm:inline text-xs px-2 py-0.5 rounded font-semibold', getRoleColor(userRole))}>
                      {userRole.charAt(0).toUpperCase() + userRole.slice(1)}
                    </span>
                  )}
                  
                  {/* Chevron */}
                  <ChevronDown className={cn(
                    'w-4 h-4 text-slate-400 transition-transform duration-200',
                    menuOpen && 'rotate-180'
                  )} />
                </button>

                {/* Dropdown Menu */}
                {menuOpen && (
                  <div className="absolute right-0 mt-2 w-64 bg-white rounded-xl shadow-xl border border-slate-200 py-2 z-50 animate-in fade-in slide-in-from-top-2 duration-200">
                    {/* User Info Header */}
                    <div className="px-4 py-3 border-b border-slate-100">
                      <div className="font-semibold text-slate-900">{displayName}</div>
                      <div className="text-sm text-slate-500">{userInfo.email}</div>
                      {userRole && (
                        <span className={cn('inline-flex mt-2 text-xs px-2 py-0.5 rounded font-semibold capitalize', getRoleColor(userRole))}>
                          {userRole}
                        </span>
                      )}
                    </div>

                  {/* Menu Items */}
                  <div className="py-2">
                    {/* My Account - Links to account page with all tabs */}
                    <button
                      onClick={() => handleNavigation('/account')}
                      className="w-full px-4 py-2.5 text-left flex items-center gap-3 hover:bg-slate-50 transition-colors"
                    >
                      <User className="w-4 h-4 text-slate-400" />
                      <span className="text-sm font-medium text-slate-700">My Account</span>
                    </button>

                    {/* Org Settings - Admin/Owner */}
                    {canAccessSettings && (
                      <button
                        onClick={() => handleNavigation('/settings')}
                        className="w-full px-4 py-2.5 text-left flex items-center gap-3 hover:bg-slate-50 transition-colors"
                      >
                        <Building2 className="w-4 h-4 text-slate-400" />
                        <span className="text-sm font-medium text-slate-700">Organization Settings</span>
                      </button>
                    )}
                  </div>

                  {/* Download Agent - ADD THIS */}
                  <button
                    onClick={() => handleNavigation('/account/download')}
                    className="w-full px-4 py-2.5 text-left flex items-center gap-3 hover:bg-slate-50 transition-colors"
                  >
                    <Download className="w-4 h-4 text-slate-400" />
                    <span className="text-sm font-medium text-slate-700">Download Agent</span>
                  </button>

                    {/* Logout */}
                    <div className="border-t border-slate-100 pt-2">
                      <button
                        onClick={handleLogout}
                        className="w-full px-4 py-2.5 text-left flex items-center gap-3 hover:bg-red-50 transition-colors group"
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