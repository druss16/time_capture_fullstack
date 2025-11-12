/**
 * Navigation.tsx — Updated with Clients link (blue theme)
 */
import React from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthProvider";
import { Users } from 'lucide-react';

export default function Navigation() {
  const location = useLocation();
  const navigate = useNavigate();
  const { logout } = useAuth();

  const isActive = (path: string) => location.pathname === path;

  const linkClass = (path: string) => {
    const base = "px-4 py-2 rounded-lg font-medium text-sm transition-colors duration-150 flex items-center gap-2";
    return isActive(path)
      ? `${base} bg-blue-600 text-white`
      : `${base} text-blue-800 hover:bg-blue-50 hover:text-blue-900`;
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
            <Link to="/devices" className={linkClass("/devices")}>
              💻 Devices
            </Link>
            <Link to="/settings" className={linkClass("/settings")}>
              ⚙️ Settings
            </Link>
            
            {/* 👇 CLIENTS LINK - Matching your blue theme */}
            <Link to="/clients" className={linkClass("/clients")}>
              <Users className="w-4 h-4" />
              Clients
            </Link>
          </div>
        </div>

        {/* Right: Date + Logout */}
        <div className="flex items-center gap-4">
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
    </nav>
  );
}