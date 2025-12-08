// src/components/BillingRatesManager.tsx
// Admin component to manage billing rates per user/client

import React, { useState, useEffect, useCallback } from 'react';
import { safeFetchJson, API_BASE } from '@/lib/api';

// ===============================
// TYPES
// ===============================

interface BillingRate {
  id: number;
  user: number | null;
  user_name: string;
  client: number | null;
  client_name: string;
  task_type: number | null;
  task_type_name: string;
  hourly_rate: string;
  effective_date: string;
  end_date: string | null;
  is_default: boolean;
}

interface User {
  id: number;
  username: string;
  email: string;
}

interface Client {
  id: number;
  name: string;
  code: string;
}

// ===============================
// MAIN COMPONENT
// ===============================

const BillingRatesManager: React.FC = () => {
  const [rates, setRates] = useState<BillingRate[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [clients, setClients] = useState<Client[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showAddForm, setShowAddForm] = useState(false);
  
  // Form state
  const [formData, setFormData] = useState({
    user: '',
    client: '',
    hourly_rate: '150.00',
    effective_date: new Date().toISOString().split('T')[0],
  });

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [ratesData, usersData, clientsData] = await Promise.all([
        safeFetchJson<BillingRate[]>(`${API_BASE}/billing/rates/`),
        safeFetchJson<User[]>(`${API_BASE}/org/members/`).catch(() => []),
        safeFetchJson<Client[]>(`${API_BASE}/clients/`).catch(() => []),
      ]);
      setRates(ratesData);
      setUsers(usersData);
      setClients(clientsData);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await safeFetchJson(`${API_BASE}/billing/rates/`, {
        method: 'POST',
        body: JSON.stringify({
          user: formData.user || null,
          client: formData.client || null,
          hourly_rate: formData.hourly_rate,
          effective_date: formData.effective_date,
        }),
      });
      setShowAddForm(false);
      setFormData({ user: '', client: '', hourly_rate: '150.00', effective_date: new Date().toISOString().split('T')[0] });
      fetchData();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create rate');
    }
  };

  const handleDelete = async (rateId: number) => {
    if (!confirm('Delete this rate?')) return;
    try {
      await safeFetchJson(`${API_BASE}/billing/rates/${rateId}/`, { method: 'DELETE' });
      fetchData();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete');
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="w-8 h-8 border-4 border-blue-500 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold text-slate-800">Billing Rates</h2>
          <p className="text-sm text-slate-500 mt-1">
            Set hourly rates per user or client. Most specific rate wins.
          </p>
        </div>
        <button
          onClick={() => setShowAddForm(true)}
          className="px-4 py-2 bg-blue-600 text-white font-medium rounded-lg hover:bg-blue-700 transition-colors flex items-center gap-2"
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
          </svg>
          Add Rate
        </button>
      </div>

      {error && (
        <div className="p-4 bg-red-50 border border-red-200 rounded-lg text-red-700">
          {error}
        </div>
      )}

      {/* Rate Priority Explanation */}
      <div className="p-4 bg-blue-50 border border-blue-200 rounded-lg">
        <h4 className="font-medium text-blue-800 mb-2">Rate Priority (highest to lowest):</h4>
        <ol className="text-sm text-blue-700 space-y-1 list-decimal list-inside">
          <li>User + Client specific rate</li>
          <li>Client specific rate (any user)</li>
          <li>User default rate</li>
          <li>Organization default rate</li>
        </ol>
      </div>

      {/* Add Rate Form */}
      {showAddForm && (
        <div className="bg-white border border-slate-200 rounded-xl p-6 shadow-sm">
          <h3 className="font-semibold text-slate-800 mb-4">Add New Rate</h3>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">
                  User (blank = all users)
                </label>
                <select
                  value={formData.user}
                  onChange={(e) => setFormData({ ...formData, user: e.target.value })}
                  className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                >
                  <option value="">All Users (Default)</option>
                  {users.map((u) => (
                    <option key={u.id} value={u.id}>{u.username}</option>
                  ))}
                </select>
              </div>
              
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">
                  Client (blank = all clients)
                </label>
                <select
                  value={formData.client}
                  onChange={(e) => setFormData({ ...formData, client: e.target.value })}
                  className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                >
                  <option value="">All Clients (Default)</option>
                  {clients.map((c) => (
                    <option key={c.id} value={c.id}>{c.name}</option>
                  ))}
                </select>
              </div>
              
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">
                  Hourly Rate ($)
                </label>
                <input
                  type="number"
                  step="0.01"
                  min="0"
                  value={formData.hourly_rate}
                  onChange={(e) => setFormData({ ...formData, hourly_rate: e.target.value })}
                  className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                  required
                />
              </div>
              
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">
                  Effective Date
                </label>
                <input
                  type="date"
                  value={formData.effective_date}
                  onChange={(e) => setFormData({ ...formData, effective_date: e.target.value })}
                  className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                  required
                />
              </div>
            </div>
            
            <div className="flex justify-end gap-3 pt-4">
              <button
                type="button"
                onClick={() => setShowAddForm(false)}
                className="px-4 py-2 text-slate-700 hover:bg-slate-100 rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                type="submit"
                className="px-6 py-2 bg-blue-600 text-white font-medium rounded-lg hover:bg-blue-700 transition-colors"
              >
                Save Rate
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Rates Table */}
      <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
        <table className="w-full">
          <thead className="bg-slate-50 border-b border-slate-200">
            <tr>
              <th className="text-left px-4 py-3 text-sm font-semibold text-slate-700">User</th>
              <th className="text-left px-4 py-3 text-sm font-semibold text-slate-700">Client</th>
              <th className="text-right px-4 py-3 text-sm font-semibold text-slate-700">Rate/Hour</th>
              <th className="text-left px-4 py-3 text-sm font-semibold text-slate-700">Effective</th>
              <th className="text-right px-4 py-3 text-sm font-semibold text-slate-700">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {rates.length === 0 ? (
              <tr>
                <td colSpan={5} className="text-center py-8 text-slate-500">
                  No rates configured. Add your first rate above.
                </td>
              </tr>
            ) : (
              rates.map((rate) => (
                <tr key={rate.id} className="hover:bg-slate-50">
                  <td className="px-4 py-3">
                    {rate.user_name || (
                      <span className="text-slate-400 italic">All Users</span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    {rate.client_name || (
                      <span className="text-slate-400 italic">All Clients</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right font-semibold text-emerald-600">
                    ${parseFloat(rate.hourly_rate).toFixed(2)}
                  </td>
                  <td className="px-4 py-3 text-sm text-slate-600">
                    {new Date(rate.effective_date).toLocaleDateString()}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button
                      onClick={() => handleDelete(rate.id)}
                      className="text-red-600 hover:text-red-800 text-sm"
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};

export default BillingRatesManager;