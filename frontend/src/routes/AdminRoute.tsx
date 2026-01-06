// src/routes/AdminRoute.tsx
/**
 * Route guard that only allows owners and admins to access
 * Uses whoami endpoint to check role
 */

import React, { useEffect, useState } from 'react';
import { Navigate, Link } from 'react-router-dom';
import { safeFetchJson, API_BASE } from '@/lib/api';
import { ShieldX, ArrowLeft } from 'lucide-react';

interface AdminRouteProps {
  children: React.ReactNode;
}

export default function AdminRoute({ children }: AdminRouteProps) {
  const [status, setStatus] = useState<'loading' | 'allowed' | 'denied'>('loading');

  useEffect(() => {
    const checkAccess = async () => {
      try {
        const data = await safeFetchJson(`${API_BASE}/whoami/`);
        
        console.log('[AdminRoute] whoami response:', data);
        
        // Check if user has admin access (owner OR admin role)
        const role = data?.role?.toLowerCase();
        const hasAccess = role === 'owner' || role === 'admin';
        
        console.log('[AdminRoute] Role:', role, 'Has access:', hasAccess);
        
        setStatus(hasAccess ? 'allowed' : 'denied');
      } catch (err) {
        console.error('[AdminRoute] Error checking access:', err);
        setStatus('denied');
      }
    };

    checkAccess();
  }, []);

  if (status === 'loading') {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
      </div>
    );
  }

  if (status === 'denied') {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <div className="bg-red-50 border-2 border-red-200 rounded-2xl p-8 max-w-md text-center">
          <ShieldX className="w-12 h-12 text-red-500 mx-auto mb-4" />
          <h2 className="text-xl font-bold text-red-800 mb-2">Access Denied</h2>
          <p className="text-red-600 mb-2">You don't have permission to access this page.</p>
          <p className="text-red-500 text-sm mb-6">Only organization administrators can access Settings.</p>
          <Link 
            to="/daily" 
            className="inline-flex items-center gap-2 px-4 py-2 bg-red-100 hover:bg-red-200 text-red-700 font-semibold rounded-lg transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
            Return to Daily Review
          </Link>
        </div>
      </div>
    );
  }

  return <>{children}</>;
}