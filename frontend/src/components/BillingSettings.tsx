// src/components/settings/BillingSettings.tsx
// Billing rate configuration for CPA firms

import React, { useState, useEffect } from 'react';
import { safeFetchJson, API_BASE } from '@/lib/api';

// ===============================
// TYPES
// ===============================

interface OrgSettings {
  id: number;
  name: string;
  billing_rate_default: string;
  billing_email?: string;
  billing_contact?: string;
}

interface Client {
  id: number;
  name: string;
  code: string;
}

interface BillingRate {
  id: number;
  client_id: number | null;
  client_name: string | null;
  user_id: number | null;
  user_name: string | null;
  rate: string;
  effective_date: string;
}

interface TeamMember {
  id: number;
  username: string;
  first_name: string;
  last_name: string;
  email: string;
}

// ===============================
// MAIN COMPONENT
// ===============================

const BillingSettings: React.FC = () => {
  // State
  const [orgSettings, setOrgSettings] = useState<OrgSettings | null>(null);
  const [clients, setClients] = useState<Client[]>([]);
  const [teamMembers, setTeamMembers] = useState<TeamMember[]>([]);
  const [billingRates, setBillingRates] = useState<BillingRate[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  
  // Form state for default rate
  const [defaultRate, setDefaultRate] = useState<string>('150.00');
  
  // Form state for new custom rate
  const [showAddRate, setShowAddRate] = useState(false);
  const [newRate, setNewRate] = useState({
    client_id: '',
    user_id: '',
    rate: '',
  });

  // ===============================
  // DATA FETCHING
  // ===============================

  useEffect(() => {
    fetchAllData();
  }, []);

  const fetchAllData = async () => {
    setLoading(true);
    setError(null);
    
    try {
      // Fetch org settings
      const orgData = await safeFetchJson<OrgSettings>(`${API_BASE}/settings/org/`);
      setOrgSettings(orgData);
      setDefaultRate(orgData.billing_rate_default || '150.00');
      
      // Fetch clients
      const clientsData = await safeFetchJson<Client[]>(`${API_BASE}/settings/clients/`);
      setClients(clientsData);
      
      // Fetch team members
      const teamData = await safeFetchJson<TeamMember[]>(`${API_BASE}/settings/team/`);
      setTeamMembers(teamData);
      
      // Fetch custom billing rates
      try {
        const ratesData = await safeFetchJson<BillingRate[]>(`${API_BASE}/billing/rates/`);
        setBillingRates(ratesData);
      } catch {
        // Billing rates endpoint might not exist yet
        setBillingRates([]);
      }
      
    } catch (err: any) {
      setError(err.message || 'Failed to load settings');
    } finally {
      setLoading(false);
    }
  };

  // ===============================
  // SAVE DEFAULT RATE
  // ===============================

  const saveDefaultRate = async () => {
    setSaving(true);
    setError(null);
    setSuccess(null);
    
    try {
      const response = await fetch(`${API_BASE}/settings/org/`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${localStorage.getItem('token')}`,
        },
        body: JSON.stringify({
          billing_rate_default: defaultRate,
        }),
      });
      
      if (!response.ok) {
        throw new Error('Failed to save default rate');
      }
      
      const data = await response.json();
      setOrgSettings(data);
      setSuccess('Default billing rate updated successfully!');
      
      // Clear success message after 3 seconds
      setTimeout(() => setSuccess(null), 3000);
      
    } catch (err: any) {
      setError(err.message || 'Failed to save');
    } finally {
      setSaving(false);
    }
  };

  // ===============================
  // ADD CUSTOM RATE
  // ===============================

  const addCustomRate = async () => {
    if (!newRate.rate) {
      setError('Rate is required');
      return;
    }
    
    if (!newRate.client_id && !newRate.user_id) {
      setError('Select a client or team member (or both)');
      return;
    }
    
    setSaving(true);
    setError(null);
    
    try {
      const response = await fetch(`${API_BASE}/billing/rates/`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${localStorage.getItem('token')}`,
        },
        body: JSON.stringify({
          client_id: newRate.client_id || null,
          user_id: newRate.user_id || null,
          rate: newRate.rate,
        }),
      });
      
      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.error || 'Failed to add rate');
      }
      
      // Refresh rates
      await fetchAllData();
      
      // Reset form
      setNewRate({ client_id: '', user_id: '', rate: '' });
      setShowAddRate(false);
      setSuccess('Custom rate added!');
      setTimeout(() => setSuccess(null), 3000);
      
    } catch (err: any) {
      setError(err.message || 'Failed to add rate');
    } finally {
      setSaving(false);
    }
  };

  // ===============================
  // DELETE CUSTOM RATE
  // ===============================

  const deleteRate = async (rateId: number) => {
    if (!confirm('Delete this custom rate?')) return;
    
    try {
      const response = await fetch(`${API_BASE}/billing/rates/${rateId}/`, {
        method: 'DELETE',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('token')}`,
        },
      });
      
      if (!response.ok) {
        throw new Error('Failed to delete rate');
      }
      
      // Remove from local state
      setBillingRates(billingRates.filter(r => r.id !== rateId));
      setSuccess('Rate deleted');
      setTimeout(() => setSuccess(null), 3000);
      
    } catch (err: any) {
      setError(err.message || 'Failed to delete');
    }
  };

  // ===============================
  // RENDER
  // ===============================

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <h2 className="text-xl font-semibold text-slate-800">Billing Settings</h2>
        <p className="text-slate-500 mt-1">
          Configure default billing rates for your firm
        </p>
      </div>

      {/* Alerts */}
      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg">
          {error}
        </div>
      )}
      
      {success && (
        <div className="bg-green-50 border border-green-200 text-green-700 px-4 py-3 rounded-lg">
          {success}
        </div>
      )}

      {/* Default Rate Card */}
      <div className="bg-white rounded-xl border border-slate-200 p-6">
        <div className="flex items-start justify-between">
          <div>
            <h3 className="text-lg font-medium text-slate-800">Default Hourly Rate</h3>
            <p className="text-sm text-slate-500 mt-1">
              This rate applies to all billable time unless a custom rate is set
            </p>
          </div>
          
          <div className="bg-blue-50 text-blue-700 px-3 py-1 rounded-full text-sm font-medium">
            Firm Default
          </div>
        </div>
        
        <div className="mt-6 flex items-end gap-4">
          <div className="flex-1 max-w-xs">
            <label className="block text-sm font-medium text-slate-700 mb-2">
              Rate per Hour
            </label>
            <div className="relative">
              <span className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500">$</span>
              <input
                type="number"
                min="0"
                step="0.01"
                value={defaultRate}
                onChange={(e) => setDefaultRate(e.target.value)}
                className="w-full pl-8 pr-4 py-2.5 border border-slate-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                placeholder="150.00"
              />
            </div>
          </div>
          
          <button
            onClick={saveDefaultRate}
            disabled={saving}
            className="px-6 py-2.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed font-medium"
          >
            {saving ? 'Saving...' : 'Save Rate'}
          </button>
        </div>
        
        {/* Rate explanation */}
        <div className="mt-6 p-4 bg-slate-50 rounded-lg">
          <h4 className="text-sm font-medium text-slate-700 mb-2">How billing rates work:</h4>
          <ul className="text-sm text-slate-600 space-y-1">
            <li>• <strong>Default rate</strong> applies to all new time entries</li>
            <li>• <strong>Client rates</strong> override the default for specific clients</li>
            <li>• <strong>User + Client rates</strong> are most specific (e.g., "Dan bills Vici at $200/hr")</li>
          </ul>
        </div>
      </div>

      {/* Custom Rates Card */}
      <div className="bg-white rounded-xl border border-slate-200 p-6">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h3 className="text-lg font-medium text-slate-800">Custom Rates</h3>
            <p className="text-sm text-slate-500 mt-1">
              Set specific rates for clients or team members
            </p>
          </div>
          
          <button
            onClick={() => setShowAddRate(!showAddRate)}
            className="px-4 py-2 bg-slate-100 text-slate-700 rounded-lg hover:bg-slate-200 font-medium text-sm flex items-center gap-2"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
            </svg>
            Add Custom Rate
          </button>
        </div>

        {/* Add Rate Form */}
        {showAddRate && (
          <div className="mb-6 p-4 bg-slate-50 rounded-lg border border-slate-200">
            <h4 className="font-medium text-slate-700 mb-4">New Custom Rate</h4>
            
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {/* Client Select */}
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">
                  Client (optional)
                </label>
                <select
                  value={newRate.client_id}
                  onChange={(e) => setNewRate({ ...newRate, client_id: e.target.value })}
                  className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                >
                  <option value="">All Clients</option>
                  {clients.map(client => (
                    <option key={client.id} value={client.id}>
                      {client.name}
                    </option>
                  ))}
                </select>
              </div>
              
              {/* User Select */}
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">
                  Team Member (optional)
                </label>
                <select
                  value={newRate.user_id}
                  onChange={(e) => setNewRate({ ...newRate, user_id: e.target.value })}
                  className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                >
                  <option value="">All Staff</option>
                  {teamMembers.map(member => (
                    <option key={member.id} value={member.id}>
                      {member.first_name} {member.last_name} ({member.username})
                    </option>
                  ))}
                </select>
              </div>
              
              {/* Rate Input */}
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">
                  Rate per Hour *
                </label>
                <div className="relative">
                  <span className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500">$</span>
                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    value={newRate.rate}
                    onChange={(e) => setNewRate({ ...newRate, rate: e.target.value })}
                    className="w-full pl-8 pr-4 py-2 border border-slate-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                    placeholder="175.00"
                  />
                </div>
              </div>
            </div>
            
            {/* Rate description */}
            <div className="mt-3 text-sm text-slate-600">
              {newRate.client_id && newRate.user_id && (
                <span>
                  → {teamMembers.find(m => m.id === parseInt(newRate.user_id))?.first_name || 'User'} will bill{' '}
                  {clients.find(c => c.id === parseInt(newRate.client_id))?.name || 'Client'} at ${newRate.rate || '0'}/hr
                </span>
              )}
              {newRate.client_id && !newRate.user_id && (
                <span>
                  → All staff will bill {clients.find(c => c.id === parseInt(newRate.client_id))?.name || 'Client'} at ${newRate.rate || '0'}/hr
                </span>
              )}
              {!newRate.client_id && newRate.user_id && (
                <span>
                  → {teamMembers.find(m => m.id === parseInt(newRate.user_id))?.first_name || 'User'}'s default rate will be ${newRate.rate || '0'}/hr
                </span>
              )}
            </div>
            
            <div className="mt-4 flex gap-3">
              <button
                onClick={addCustomRate}
                disabled={saving || !newRate.rate}
                className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 font-medium text-sm"
              >
                {saving ? 'Adding...' : 'Add Rate'}
              </button>
              <button
                onClick={() => {
                  setShowAddRate(false);
                  setNewRate({ client_id: '', user_id: '', rate: '' });
                }}
                className="px-4 py-2 bg-slate-200 text-slate-700 rounded-lg hover:bg-slate-300 font-medium text-sm"
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {/* Existing Rates Table */}
        {billingRates.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-slate-200">
                  <th className="text-left py-3 px-4 text-sm font-medium text-slate-600">Client</th>
                  <th className="text-left py-3 px-4 text-sm font-medium text-slate-600">Team Member</th>
                  <th className="text-left py-3 px-4 text-sm font-medium text-slate-600">Rate</th>
                  <th className="text-right py-3 px-4 text-sm font-medium text-slate-600">Actions</th>
                </tr>
              </thead>
              <tbody>
                {billingRates.map(rate => (
                  <tr key={rate.id} className="border-b border-slate-100 hover:bg-slate-50">
                    <td className="py-3 px-4">
                      {rate.client_name || <span className="text-slate-400">All Clients</span>}
                    </td>
                    <td className="py-3 px-4">
                      {rate.user_name || <span className="text-slate-400">All Staff</span>}
                    </td>
                    <td className="py-3 px-4 font-medium">
                      ${parseFloat(rate.rate).toFixed(2)}/hr
                    </td>
                    <td className="py-3 px-4 text-right">
                      <button
                        onClick={() => deleteRate(rate.id)}
                        className="text-red-600 hover:text-red-700 text-sm font-medium"
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="text-center py-8 text-slate-500">
            <svg className="w-12 h-12 mx-auto text-slate-300 mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <p>No custom rates configured</p>
            <p className="text-sm mt-1">All time will be billed at the default rate</p>
          </div>
        )}
      </div>

      {/* Rate Priority Explanation */}
      <div className="bg-amber-50 border border-amber-200 rounded-xl p-6">
        <h3 className="text-lg font-medium text-amber-800 mb-3">Rate Priority Order</h3>
        <p className="text-amber-700 text-sm mb-4">
          When calculating billing amounts, the most specific rate is used:
        </p>
        <ol className="space-y-2 text-sm text-amber-700">
          <li className="flex items-center gap-3">
            <span className="w-6 h-6 rounded-full bg-amber-200 text-amber-800 flex items-center justify-center font-bold text-xs">1</span>
            <span><strong>User + Client rate</strong> — "Dan bills Vici at $200/hr"</span>
          </li>
          <li className="flex items-center gap-3">
            <span className="w-6 h-6 rounded-full bg-amber-200 text-amber-800 flex items-center justify-center font-bold text-xs">2</span>
            <span><strong>Client rate</strong> — "Anyone billing Vici = $175/hr"</span>
          </li>
          <li className="flex items-center gap-3">
            <span className="w-6 h-6 rounded-full bg-amber-200 text-amber-800 flex items-center justify-center font-bold text-xs">3</span>
            <span><strong>User rate</strong> — "Dan's default rate = $150/hr"</span>
          </li>
          <li className="flex items-center gap-3">
            <span className="w-6 h-6 rounded-full bg-amber-200 text-amber-800 flex items-center justify-center font-bold text-xs">4</span>
            <span><strong>Firm default</strong> — "${defaultRate}/hr" (set above)</span>
          </li>
        </ol>
      </div>
    </div>
  );
};

export default BillingSettings;