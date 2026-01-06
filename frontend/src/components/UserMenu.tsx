// src/components/UserMenu.tsx
/**
 * User dropdown menu with personal settings
 * - Account: View/edit profile
 * - Billing: Stripe subscription (owner only)
 * - Reset Password: Change password
 * - Logout
 */

import React, { useState, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { 
  User, 
  CreditCard, 
  KeyRound, 
  LogOut, 
  ChevronDown,
  Settings,
  Building2
} from 'lucide-react';

interface UserMenuProps {
  user: {
    username: string;
    email?: string;
    first_name?: string;
    last_name?: string;
  };
  role: 'owner' | 'admin' | 'manager' | 'member';
  organizationName?: string;
  onLogout: () => void;
}

export default function UserMenu({ user, role, organizationName, onLogout }: UserMenuProps) {
  const [isOpen, setIsOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();

  // Close menu when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // Close menu on escape key
  useEffect(() => {
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setIsOpen(false);
      }
    };

    document.addEventListener('keydown', handleEscape);
    return () => document.removeEventListener('keydown', handleEscape);
  }, []);

  const displayName = user.first_name 
    ? `${user.first_name} ${user.last_name || ''}`.trim()
    : user.username;

  const initials = user.first_name 
    ? `${user.first_name[0]}${user.last_name?.[0] || ''}`.toUpperCase()
    : user.username.slice(0, 2).toUpperCase();

  const roleColors: Record<string, string> = {
    owner: 'bg-amber-100 text-amber-700 border-amber-200',
    admin: 'bg-purple-100 text-purple-700 border-purple-200',
    manager: 'bg-blue-100 text-blue-700 border-blue-200',
    member: 'bg-slate-100 text-slate-600 border-slate-200',
  };

  const handleNavigation = (path: string) => {
    setIsOpen(false);
    navigate(path);
  };

  const handleLogout = () => {
    setIsOpen(false);
    onLogout();
  };

  return (
    <div className="relative" ref={menuRef}>
      {/* Trigger Button */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center gap-3 px-3 py-2 rounded-xl hover:bg-slate-100 transition-colors"
      >
        {/* Avatar */}
        <div className="w-9 h-9 bg-emerald-600 rounded-full flex items-center justify-center text-white font-bold text-sm">
          {initials}
        </div>
        
        {/* Name & Role */}
        <div className="hidden sm:block text-left">
          <div className="font-semibold text-slate-900 text-sm">{displayName}</div>
          <div className="text-xs text-slate-500">{organizationName}</div>
        </div>
        
        {/* Role Badge */}
        <span className={`hidden md:inline-flex px-2 py-0.5 text-xs font-bold rounded-full border capitalize ${roleColors[role]}`}>
          {role}
        </span>
        
        {/* Chevron */}
        <ChevronDown className={`w-4 h-4 text-slate-400 transition-transform ${isOpen ? 'rotate-180' : ''}`} />
      </button>

      {/* Dropdown Menu */}
      {isOpen && (
        <div className="absolute right-0 mt-2 w-64 bg-white rounded-xl shadow-lg border border-slate-200 py-2 z-50">
          {/* User Info Header */}
          <div className="px-4 py-3 border-b border-slate-100">
            <div className="font-semibold text-slate-900">{displayName}</div>
            <div className="text-sm text-slate-500">{user.email}</div>
            <span className={`inline-flex mt-2 px-2 py-0.5 text-xs font-bold rounded-full border capitalize ${roleColors[role]}`}>
              {role}
            </span>
          </div>

          {/* Menu Items */}
          <div className="py-2">
            {/* Account */}
            <button
              onClick={() => handleNavigation('/account')}
              className="w-full px-4 py-2.5 text-left flex items-center gap-3 hover:bg-slate-50 transition-colors"
            >
              <User className="w-4 h-4 text-slate-400" />
              <span className="text-sm font-medium text-slate-700">Account Settings</span>
            </button>

            {/* Billing - Owner Only */}
            {role === 'owner' && (
              <button
                onClick={() => handleNavigation('/account/billing')}
                className="w-full px-4 py-2.5 text-left flex items-center gap-3 hover:bg-slate-50 transition-colors"
              >
                <CreditCard className="w-4 h-4 text-slate-400" />
                <span className="text-sm font-medium text-slate-700">Subscription & Billing</span>
              </button>
            )}

            {/* Reset Password */}
            <button
              onClick={() => handleNavigation('/account/password')}
              className="w-full px-4 py-2.5 text-left flex items-center gap-3 hover:bg-slate-50 transition-colors"
            >
              <KeyRound className="w-4 h-4 text-slate-400" />
              <span className="text-sm font-medium text-slate-700">Change Password</span>
            </button>

            {/* Org Settings Link (for admins/owners) */}
            {['owner', 'admin'].includes(role) && (
              <button
                onClick={() => handleNavigation('/settings')}
                className="w-full px-4 py-2.5 text-left flex items-center gap-3 hover:bg-slate-50 transition-colors"
              >
                <Building2 className="w-4 h-4 text-slate-400" />
                <span className="text-sm font-medium text-slate-700">Organization Settings</span>
              </button>
            )}
          </div>

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
  );
}