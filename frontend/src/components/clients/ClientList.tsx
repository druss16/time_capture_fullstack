/**
 * ClientList.tsx - Client management page
 * Updated to match design system
 */

import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Search, Plus, Upload, Pencil, Trash2, Briefcase, RefreshCw } from 'lucide-react';
import { safeFetchJson, API_BASE } from '@/lib/api';
import { cn } from '@/lib/design-system';

interface Client {
  id: number;
  name: string;
  code: string;
  is_active: boolean;
}

export function ClientList() {
  const navigate = useNavigate();
  const [clients, setClients] = useState<Client[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');

  useEffect(() => {
    fetchClients();
  }, []);

  const fetchClients = async () => {
    setLoading(true);
    try {
      const data = await safeFetchJson<Client[]>(`${API_BASE}/clients/list/`);
      setClients(data);
    } catch (error) {
      console.error('Error fetching clients:', error);
    } finally {
      setLoading(false);
    }
  };

  const filteredClients = clients.filter(client =>
    client.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
    client.code.toLowerCase().includes(searchQuery.toLowerCase())
  );

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center">
        <div className="text-center">
          <RefreshCw className="w-8 h-8 text-primary animate-spin mx-auto mb-3" />
          <p className="text-slate-600 font-semibold">Loading clients...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-50">
      <div className="max-w-6xl mx-auto p-6">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <div className="w-12 h-12 rounded-xl bg-primary flex items-center justify-center shadow-lg shadow-primary/25">
              <Briefcase className="w-6 h-6 text-white" />
            </div>
            <div>
              <h1 className="text-2xl font-extrabold text-slate-900 tracking-tight">Clients</h1>
              <p className="text-slate-600 font-medium">Manage your client list</p>
            </div>
          </div>

          {/* Action Buttons */}
          <div className="flex gap-2">
            <button
              onClick={() => navigate('/clients/add')}
              className="flex items-center gap-2 px-4 py-2.5 bg-primary text-white rounded-xl font-bold text-sm hover:opacity-90 shadow-lg shadow-primary/25 transition-all"
            >
              <Plus className="w-4 h-4" />
              Add Client
            </button>
            <button
              onClick={() => navigate('/clients/import')}
              className="flex items-center gap-2 px-4 py-2.5 border-2 border-slate-200 bg-white text-slate-700 rounded-xl font-bold text-sm hover:bg-slate-50 transition-all"
            >
              <Upload className="w-4 h-4" />
              Import CSV
            </button>
          </div>
        </div>

        {/* Search Bar */}
        <div className="bg-white rounded-2xl border-2 border-slate-200 shadow-sm p-4 mb-6">
          <div className="relative max-w-md">
            <Search className="absolute left-4 top-1/2 transform -translate-y-1/2 text-slate-400 w-5 h-5" />
            <input
              type="text"
              placeholder="Search clients..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-12 pr-4 py-3 border-2 border-slate-200 rounded-xl text-slate-900 font-medium focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none transition-all"
            />
          </div>
        </div>

        {/* Clients Table */}
        <div className="bg-white rounded-2xl border-2 border-slate-200 shadow-sm overflow-hidden">
          {filteredClients.length === 0 ? (
            <div className="text-center py-16">
              <div className="w-16 h-16 rounded-full bg-slate-100 flex items-center justify-center mx-auto mb-4">
                <Briefcase className="w-8 h-8 text-slate-400" />
              </div>
              {searchQuery ? (
                <>
                  <p className="text-slate-700 font-bold">No clients match "{searchQuery}"</p>
                  <p className="text-sm text-slate-500 font-medium mt-1">
                    Try a different search term
                  </p>
                </>
              ) : (
                <>
                  <p className="text-slate-700 font-bold">No clients yet</p>
                  <button
                    onClick={() => navigate('/clients/add')}
                    className="mt-4 px-4 py-2 text-primary font-bold hover:underline"
                  >
                    Add your first client →
                  </button>
                </>
              )}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead className="bg-slate-100">
                  <tr>
                    <th className="text-left px-6 py-3 text-sm font-bold text-slate-700">Client Name</th>
                    <th className="text-left px-6 py-3 text-sm font-bold text-slate-700">Code</th>
                    <th className="text-left px-6 py-3 text-sm font-bold text-slate-700">Status</th>
                    <th className="text-right px-6 py-3 text-sm font-bold text-slate-700">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-200">
                  {filteredClients.map((client) => (
                    <tr key={client.id} className="hover:bg-slate-50 transition-colors">
                      <td className="px-6 py-4">
                        <p className="font-bold text-slate-900">{client.name}</p>
                      </td>
                      <td className="px-6 py-4">
                        <span className="text-sm text-slate-500 font-mono font-semibold">{client.code || '—'}</span>
                      </td>
                      <td className="px-6 py-4">
                        <span className={cn(
                          'text-xs px-2.5 py-1 rounded-full font-bold',
                          client.is_active 
                            ? 'bg-emerald-100 text-emerald-700' 
                            : 'bg-slate-100 text-slate-500'
                        )}>
                          {client.is_active ? 'Active' : 'Inactive'}
                        </span>
                      </td>
                      <td className="px-6 py-4">
                        <div className="flex items-center justify-end gap-1">
                          <button
                            onClick={() => navigate(`/clients/${client.id}/edit`)}
                            className="p-2 text-primary hover:bg-primary/10 rounded-lg transition-colors"
                            title="Edit"
                          >
                            <Pencil className="w-4 h-4" />
                          </button>
                          <button
                            className="p-2 text-red-500 hover:bg-red-50 rounded-lg transition-colors"
                            title="Delete"
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Stats */}
        {clients.length > 0 && (
          <div className="mt-4 text-center text-sm text-slate-500 font-medium">
            Showing {filteredClients.length} of {clients.length} client{clients.length !== 1 ? 's' : ''}
          </div>
        )}
      </div>
    </div>
  );
}

export default ClientList;