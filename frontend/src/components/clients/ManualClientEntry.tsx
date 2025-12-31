/**
 * ManualClientEntry.tsx - Add new client form
 * Updated to match design system
 */

import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowLeft, Save, Plus, AlertCircle, Lightbulb, RefreshCw } from 'lucide-react';
import { API_BASE } from '@/lib/api';
import { postJson } from '@/lib/csrf';

interface ClientFormData {
  name: string;
  code: string;
}

export function ManualClientEntry() {
  const navigate = useNavigate();
  const [formData, setFormData] = useState<ClientFormData>({
    name: '',
    code: '',
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value } = e.target;
    setFormData(prev => ({
      ...prev,
      [name]: value
    }));
    setError(null);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    
    if (!formData.name.trim()) {
      setError('Client name is required');
      return;
    }

    if (!formData.code.trim()) {
      setError('Client code is required');
      return;
    }

    setSaving(true);
    setError(null);

    try {
      const response = await postJson(`${API_BASE}/clients/`, {
        name: formData.name.trim(),
        code: formData.code.trim(),
      });

      if (response.ok) {
        navigate('/clients');
      } else {
        const data = await response.json().catch(() => ({ error: 'Failed to create client' }));
        setError(data.error || `Error: ${response.status}`);
      }
    } catch (err: any) {
      console.error('Error creating client:', err);
      setError(err.message || 'Network error. Please try again.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-50">
      <div className="max-w-2xl mx-auto p-6">
        {/* Back Button */}
        <button
          onClick={() => navigate('/clients')}
          className="flex items-center gap-2 text-slate-600 hover:text-slate-900 font-semibold mb-6 transition-colors"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to Clients
        </button>

        {/* Header */}
        <div className="flex items-center gap-3 mb-6">
          <div className="w-12 h-12 rounded-xl bg-primary flex items-center justify-center shadow-lg shadow-primary/25">
            <Plus className="w-6 h-6 text-white" />
          </div>
          <div>
            <h1 className="text-2xl font-extrabold text-slate-900 tracking-tight">Add New Client</h1>
            <p className="text-slate-600 font-medium">Enter client details to add them to your system</p>
          </div>
        </div>

        {/* Form Card */}
        <div className="bg-white rounded-2xl border-2 border-slate-200 shadow-sm p-6">
          {error && (
            <div className="mb-6 p-4 bg-red-50 border-2 border-red-200 rounded-xl flex items-center gap-3">
              <AlertCircle className="w-5 h-5 text-red-600 flex-shrink-0" />
              <p className="text-red-700 font-semibold">{error}</p>
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-6">
            {/* Client Name */}
            <div>
              <label htmlFor="name" className="block text-sm font-bold text-slate-800 mb-2">
                Client Name <span className="text-red-500">*</span>
              </label>
              <input
                type="text"
                id="name"
                name="name"
                value={formData.name}
                onChange={handleChange}
                placeholder="Acme Corporation"
                required
                className="w-full border-2 border-slate-200 rounded-xl px-4 py-3 text-slate-900 font-medium focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none transition-all"
              />
            </div>

            {/* Client Code */}
            <div>
              <label htmlFor="code" className="block text-sm font-bold text-slate-800 mb-2">
                Client Code <span className="text-red-500">*</span>
              </label>
              <input
                type="text"
                id="code"
                name="code"
                value={formData.code}
                onChange={handleChange}
                placeholder="ACME"
                required
                className="w-full border-2 border-slate-200 rounded-xl px-4 py-3 text-slate-900 font-medium focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none transition-all uppercase"
              />
              <p className="mt-2 text-sm text-slate-500 font-medium">
                Short identifier for quick reference (e.g., initials or abbreviation)
              </p>
            </div>

            {/* Actions */}
            <div className="flex gap-3 pt-4">
              <button
                type="submit"
                disabled={saving}
                className="flex-1 flex items-center justify-center gap-2 px-6 py-3 bg-primary text-white rounded-xl font-bold hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed shadow-lg shadow-primary/25 transition-all"
              >
                {saving ? (
                  <>
                    <RefreshCw className="w-4 h-4 animate-spin" />
                    Saving...
                  </>
                ) : (
                  <>
                    <Save className="w-4 h-4" />
                    Save Client
                  </>
                )}
              </button>
              <button
                type="button"
                onClick={() => navigate('/clients')}
                className="px-6 py-3 border-2 border-slate-200 text-slate-700 rounded-xl font-bold hover:bg-slate-50 transition-all"
              >
                Cancel
              </button>
            </div>
          </form>
        </div>

        {/* Tips */}
        <div className="mt-6 p-4 bg-amber-50 border-2 border-amber-200 rounded-2xl">
          <h3 className="font-bold text-amber-800 mb-3 flex items-center gap-2">
            <Lightbulb className="w-4 h-4" />
            Quick Tips
          </h3>
          <ul className="text-sm text-amber-700 font-medium space-y-2">
            <li>• Use a consistent naming convention for client codes</li>
            <li>• Client codes should be short and memorable</li>
            <li>• You can also <button onClick={() => navigate('/clients/import')} className="text-amber-900 underline hover:no-underline">import multiple clients via CSV</button></li>
          </ul>
        </div>
      </div>
    </div>
  );
}

export default ManualClientEntry;