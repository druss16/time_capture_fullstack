/**
 * Navigation.tsx - Simple navigation component
 * Place in: frontend/src/components/Navigation.tsx
 */

import React from 'react';
import { Link, useLocation } from 'react-router-dom';
import { useAuth } from '../auth/AuthProvider';

export default function Navigation() {
  const location = useLocation();
  const { logout } = useAuth();

  const isActive = (path: string) => {
    return location.pathname === path;
  };

  const linkClass = (path: string) => {
    const base = "px-4 py-2 rounded-lg transition-colors";
    return isActive(path)
      ? `${base} bg-blue-600 text-white`
      : `${base} hover:bg-gray-100`;
  };

  return (
    <nav className="bg-white border-b border-gray-200 px-6 py-4">
      <div className="max-w-7xl mx-auto flex items-center justify-between">
        <div className="flex items-center gap-1">
          <Link to="/" className={linkClass("/")}>
            📅 Daily Review
          </Link>
          <Link to="/timecards" className={linkClass("/timecards")}>
            ⏱️ Timecards
          </Link>
          <Link to="/settings" className={linkClass("/settings")}>
            ⚙️ Settings
          </Link>
        </div>
        
        <div className="flex items-center gap-4">
          <span className="text-sm text-gray-600">
            {new Date().toLocaleDateString()}
          </span>
          <button
            onClick={logout}
            className="px-4 py-2 text-sm text-gray-600 hover:text-gray-800"
          >
            Logout
          </button>
        </div>
      </div>
    </nav>
  );
}