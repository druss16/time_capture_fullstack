// src/pages/Clients.tsx

import { useState, useEffect } from 'react';
import {
  Briefcase,
  Search,
  Plus,
  Settings,
  Loader2,
  Send,
  Check,
  X,
  ExternalLink,
  Users,
} from 'lucide-react';
import { Link } from 'react-router-dom';
import { cn } from '@/lib/design-system';
import { safeFetchJson } from '@/lib/api';

const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api';

interface Client {
  id: number;
  name: string;
  code: string;
  visibility?: string;
  is_active?: boolean;
}

interface UserInfo {
  role: string;
  user_id: number;
}

export default function Clients() {
  const [clients, setClients] = useState<Client[]>([]);
  const [loading, setLoading] = useState(true);
  const [userInfo, setUserInfo] = useState<UserInfo | null>(null);
  const [search, setSearch] = useState('');
  
  // Request new client modal
  const [showRequest, setShowRequest] = useState(false);
  const [requestForm, setRequestForm] = useState({ name: '', notes: '' });
  const [submitting, setSubmitting] = useState(false);
  const [requestSent, setRequestSent] = useState(false);

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    setLoading(true);
    try {
      const [clientsData, whoami] = await Promise.all([
        safeFetchJson<Client[]>(`${API_BASE}/settings/my-clients/`),
        safeFetchJson<UserInfo>(`${API_BASE}/whoami/`),
      ]);
      setClients(clientsData || []);
      setUserInfo(whoami);
    } catch (err) {
      console.error('Failed to load clients:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleRequestClient = async () => {
    if (!requestForm.name.trim()) return;
    
    setSubmitting(true);
    try {
      await safeFetchJson(`${API_BASE}/settings/client-requests/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(requestForm),
      });
      setRequestSent(true);
      setTimeout(() => {
        setShowRequest(false);
        setRequestForm({ name: '', notes: '' });
        setRequestSent(false);
      }, 2000);
    } catch (err: any) {
      console.error('Failed to submit request:', err);
    } finally {
      setSubmitting(false);
    }
  };

  const canManageClients = userInfo?.role && ['owner', 'admin'].includes(userInfo.role);
  
  const filteredClients = clients.filter(c => 
    c.name.toLowerCase().includes(search.toLowerCase()) ||
    c.code?.toLowerCase().includes(search.toLowerCase())
  );

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <Loader2 className="w-8 h-8 text-primary animate-spin" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <div className="p-3 bg-primary/10 rounded-xl">
            <Users className="w-7 h-7 text-primary" />
          </div>
          <div>
            <h1 className="text-2xl font-extrabold text-slate-900">My Clients</h1>
            <p className="text-slate-500 font-medium">
              Clients you can log time to
            </p>
          </div>
        </div>
        
        <div className="flex items-center gap-3">
          <button
            onClick={() => setShowRequest(true)}
            className="flex items-center gap-2 px-4 py-2.5 border-2 border-slate-200 rounded-xl font-bold text-slate-700 hover:bg-slate-100 transition-all"
          >
            <Plus className="w-4 h-4" />
            Request Client
          </button>
          
          {canManageClients && (
            <Link
              to="/settings?tab=clients"
              className="flex items-center gap-2 px-4 py-2.5 bg-primary text-white rounded-xl font-bold hover:opacity-90 shadow-lg shadow-primary/25 transition-all"
            >
              <Settings className="w-4 h-4" />
              Manage Clients
            </Link>
          )}
        </div>
      </div>

      {/* Search Card */}
      <div className="bg-[#F5F7F3] rounded-2xl p-6 border border-slate-200/60">
        <div className="relative">
          <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-slate-400" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search clients by name or code..."
            className="w-full pl-12 pr-4 py-3 bg-white border-2 border-slate-200 rounded-xl font-medium text-slate-900 focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none transition-all"
          />
        </div>
      </div>

      {/* Clients Card */}
      <div className="bg-[#F5F7F3] rounded-2xl p-6 border border-slate-200/60">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h2 className="text-lg font-extrabold text-slate-900">Your Clients</h2>
            <p className="text-sm text-slate-500 font-medium">
              {filteredClients.length} client{filteredClients.length !== 1 ? 's' : ''} available
            </p>
          </div>
        </div>

        {filteredClients.length === 0 ? (
          <div className="bg-white rounded-xl border-2 border-dashed border-slate-200 p-12 text-center">
            <Briefcase className="w-12 h-12 mx-auto mb-4 text-slate-300" />
            {search ? (
              <>
                <p className="font-bold text-slate-700">No clients match "{search}"</p>
                <p className="text-sm text-slate-500 mt-1">Try a different search term</p>
              </>
            ) : (
              <>
                <p className="font-bold text-slate-700">No clients assigned yet</p>
                <p className="text-sm text-slate-500 mt-1 mb-4">
                  Request access to clients or contact your administrator
                </p>
                <button
                  onClick={() => setShowRequest(true)}
                  className="px-4 py-2 bg-primary text-white rounded-xl font-bold text-sm hover:opacity-90"
                >
                  <Plus className="w-4 h-4 inline mr-2" />
                  Request New Client
                </button>
              </>
            )}
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {filteredClients.map(client => (
              <div
                key={client.id}
                className="p-4 bg-white border-2 border-slate-200 rounded-xl hover:border-primary/50 hover:shadow-lg hover:shadow-primary/5 transition-all group"
              >
                <div className="flex items-start justify-between">
                  <div className="flex-1 min-w-0">
                    <h3 className="font-bold text-slate-900 truncate group-hover:text-primary transition-colors">
                      {client.name}
                    </h3>
                    {client.code && (
                      <p className="text-sm text-slate-500 font-mono font-semibold mt-0.5">
                        {client.code}
                      </p>
                    )}
                  </div>
                  <div className="ml-3 flex-shrink-0">
                    <span className={cn(
                      'text-xs px-2 py-1 rounded-full font-bold',
                      client.is_active !== false
                        ? 'bg-emerald-100 text-emerald-700'
                        : 'bg-slate-100 text-slate-500'
                    )}>
                      {client.is_active !== false ? 'Active' : 'Inactive'}
                    </span>
                  </div>
                </div>
                
                <div className="mt-4 pt-3 border-t border-slate-100 flex items-center gap-2">
                  // Change the link to include both client and action
                  <Link
                    to={`/daily?add=true&client_id=${client.id}`}
                    className="text-xs text-primary font-bold hover:underline flex items-center gap-1"
                  >
                    Log Time
                    <ExternalLink className="w-3 h-3" />
                  </Link>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ================================================================== */}
      {/* Request New Client Modal                                          */}
      {/* ================================================================== */}
      {showRequest && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white rounded-2xl p-6 max-w-md w-full mx-4 shadow-2xl">
            {requestSent ? (
              <div className="text-center py-8">
                <div className="w-16 h-16 bg-emerald-100 rounded-full flex items-center justify-center mx-auto mb-4">
                  <Check className="w-8 h-8 text-emerald-600" />
                </div>
                <h3 className="text-xl font-extrabold text-slate-900 mb-2">Request Sent!</h3>
                <p className="text-slate-600 font-medium">
                  Your admin will review and add the client.
                </p>
              </div>
            ) : (
              <>
                <div className="flex items-center justify-between mb-6">
                  <div>
                    <h3 className="text-xl font-extrabold text-slate-900">Request New Client</h3>
                    <p className="text-sm text-slate-500 font-medium">
                      Your admin will review this request
                    </p>
                  </div>
                  <button
                    onClick={() => setShowRequest(false)}
                    className="p-2 hover:bg-slate-100 rounded-lg transition-colors"
                  >
                    <X className="w-5 h-5 text-slate-500" />
                  </button>
                </div>

                <div className="space-y-4">
                  <div>
                    <label className="block text-sm font-bold text-slate-800 mb-2">
                      Client Name *
                    </label>
                    <input
                      type="text"
                      value={requestForm.name}
                      onChange={(e) => setRequestForm({ ...requestForm, name: e.target.value })}
                      placeholder="Acme Corporation"
                      className="w-full border-2 border-slate-200 rounded-xl px-4 py-2.5 text-slate-900 font-medium focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none transition-all"
                    />
                  </div>

                  <div>
                    <label className="block text-sm font-bold text-slate-800 mb-2">
                      Notes (optional)
                    </label>
                    <textarea
                      value={requestForm.notes}
                      onChange={(e) => setRequestForm({ ...requestForm, notes: e.target.value })}
                      placeholder="Any additional context for your admin..."
                      rows={3}
                      className="w-full border-2 border-slate-200 rounded-xl px-4 py-2.5 text-slate-900 font-medium focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none transition-all resize-none"
                    />
                  </div>
                </div>

                <div className="flex gap-3 mt-6">
                  <button
                    onClick={() => setShowRequest(false)}
                    className="flex-1 px-4 py-3 border-2 border-slate-200 rounded-xl font-bold text-slate-700 hover:bg-slate-100 transition-colors"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={handleRequestClient}
                    disabled={submitting || !requestForm.name.trim()}
                    className="flex-1 px-4 py-3 bg-primary text-white rounded-xl font-bold hover:opacity-90 disabled:opacity-50 flex items-center justify-center gap-2 shadow-lg shadow-primary/25 transition-all"
                  >
                    {submitting ? (
                      <Loader2 className="w-4 h-4 animate-spin" />
                    ) : (
                      <Send className="w-4 h-4" />
                    )}
                    Send Request
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}