// Create this file: src/routes/AdminRoute.tsx

import { useEffect, useState } from 'react';
import { Navigate } from 'react-router-dom';
import { safeFetchJson, API_BASE } from '@/lib/api';

interface AdminRouteProps {
  children: React.ReactNode;
}

export default function AdminRoute({ children }: AdminRouteProps) {
  const [checking, setChecking] = useState(true);
  const [isAdmin, setIsAdmin] = useState(false);

  useEffect(() => {
    safeFetchJson(`${API_BASE}/whoami/`)
      .then(data => {
        setIsAdmin(data.is_staff || data.is_superuser || false);
        setChecking(false);
      })
      .catch(() => {
        setIsAdmin(false);
        setChecking(false);
      });
  }, []);

  if (checking) {
    return <div className="p-6">Checking permissions...</div>;
  }

  if (!isAdmin) {
    return (
      <div className="p-6 max-w-2xl mx-auto">
        <div className="bg-red-50 border border-red-200 rounded-lg p-6 text-center">
          <h2 className="text-xl font-bold text-red-800 mb-2">Access Denied</h2>
          <p className="text-red-700">You don't have permission to access this page.</p>
          <p className="text-sm text-red-600 mt-4">Only organization administrators can access Settings.</p>
          <a href="/daily" className="mt-4 inline-block text-blue-600 hover:underline">
            Return to Daily Review
          </a>
        </div>
      </div>
    );
  }

  return <>{children}</>;
}