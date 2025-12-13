/**
 * Navigation.tsx — Updated with organization role display and Billing link
 */
import React, { useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthProvider";
import { Users, Receipt } from 'lucide-react';
import { safeFetchJson, API_BASE } from "@/lib/api";

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

  // Fetch user info including organization role
  useEffect(() => {
    safeFetchJson(`${API_BASE}/whoami/`)
      .then(data => setUserInfo(data))
      .catch(console.error);
  }, []);

  // Role-based permissions
  const userRole = userInfo?.role;
  const canAccessSettings = ['owner', 'admin'].includes(userRole || '');
  const canApproveTime = ['owner', 'admin', 'manager'].includes(userRole || '');

  const isActive = (path: string) => location.pathname === path || location.pathname.startsWith(path + '/');
  
  const linkClass = (path: string) => {
    const base = "px-4 py-2 rounded-lg font-medium text-sm transition-colors duration-150 flex items-center gap-2";
    return isActive(path)
      ? `${base} bg-blue-600 text-white`
      : `${base} text-blue-800 hover:bg-blue-50 hover:text-blue-900`;
  };

  // Role badge styling
  const getRoleBadge = (role: string | null) => {
    if (!role || role === 'member') return null;
    
    const styles: Record<string, string> = {
      owner: 'bg-purple-100 text-purple-800',
      admin: 'bg-blue-100 text-blue-800',
      manager: 'bg-green-100 text-green-800',
    };
    
    return (
      <span className={`text-xs px-2 py-1 rounded font-medium ${styles[role] || 'bg-gray-100 text-gray-800'}`}>
        {role.charAt(0).toUpperCase() + role.slice(1)}
      </span>
    );
  };

  return (
    <nav className="sticky top-0 z-40 bg-white border-b border-blue-100 shadow-sm">
      <div className="max-w-7xl mx-auto flex items-center justify-between px-6 py-3">
        {/* Left: Brand + links */}
        <div className="flex items-center gap-2">
          <Link to="/" className="flex items-center gap-2 text-blue-900 font-semibold">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-600 text-white font-bold text-sm">
              T
            </span>
            <span>Time Capture</span>
          </Link>

          <div className="hidden sm:flex items-center gap-1 ml-4">
            <Link to="/daily" className={linkClass("/daily")}>
              📅 Daily Review
            </Link>
            <Link to="/timecards" className={linkClass("/timecards")}>
              ⏱️ Timecards
            </Link>
            
            {/* Billing - Timesheets, Approvals, etc. */}
            <Link to="/billing" className={linkClass("/billing")}>
              <Receipt className="w-4 h-4" />
              Billing
            </Link>
            
            <Link to="/devices" className={linkClass("/devices")}>
              💻 Devices
            </Link>
            
            {/* Only show Settings to owners and admins */}
            {canAccessSettings && (
              <Link to="/settings" className={linkClass("/settings")}>
                ⚙️ Settings
              </Link>
            )}
            
            <Link to="/clients" className={linkClass("/clients")}>
              <Users className="w-4 h-4" />
              Clients
            </Link>
          </div>
        </div>

        {/* Right: User info + Logout */}
        <div className="flex items-center gap-4">
          {userInfo && (
            <div className="flex items-center gap-2">
              <span className="text-sm text-blue-700 hidden sm:inline">
                {userInfo.username}
              </span>
              {getRoleBadge(userRole || null)}
            </div>
          )}
          <span className="text-sm text-blue-700 hidden sm:inline">
            {new Date().toLocaleDateString()}
          </span>
          <button
            onClick={async () => {
              await logout();
              navigate("/login");
            }}
            className="rounded-lg border border-blue-200 px-4 py-2 text-sm text-blue-800 hover:bg-blue-50 hover:text-blue-900"
          >
            Logout
          </button>
        </div>
      </div>

      {/* Mobile Navigation */}
      <div className="sm:hidden border-t border-blue-100 px-4 py-2 flex items-center gap-2 overflow-x-auto">
        <Link to="/daily" className={linkClass("/daily")}>
          📅 Daily
        </Link>
        <Link to="/timecards" className={linkClass("/timecards")}>
          ⏱️ Time
        </Link>
        <Link to="/billing" className={linkClass("/billing")}>
          💰 Billing
        </Link>
        <Link to="/devices" className={linkClass("/devices")}>
          💻 Devices
        </Link>
        {canAccessSettings && (
          <Link to="/settings" className={linkClass("/settings")}>
            ⚙️ Settings
          </Link>
        )}
        <Link to="/clients" className={linkClass("/clients")}>
          👥 Clients
        </Link>
      </div>
    </nav>
  );
}