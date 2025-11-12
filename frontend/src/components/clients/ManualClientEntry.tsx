/**
 * ManualClientEntry.tsx - Using your existing csrf.ts utilities
 */
import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowLeft, Save } from 'lucide-react';
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
    
    // Validation
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
      // ✅ Use your existing postJson utility - handles CSRF automatically!
      const response = await postJson('/api/clients/', {
        name: formData.name.trim(),
        code: formData.code.trim(),
      });

      if (response.ok) {
        const data = await response.json();
        if (data.ok) {
          // Success! Navigate back to clients list
          navigate('/clients');
        } else {
          setError(data.error || 'Failed to create client');
        }
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
    <div className="min-h-screen bg-gray-50 p-6">
      <div className="max-w-2xl mx-auto">
        {/* Back Button */}
        <button
          onClick={() => navigate('/clients')}
          className="flex items-center gap-2 text-gray-600 hover:text-gray-900 mb-6 transition-colors"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to Clients
        </button>

        {/* Form Card */}
        <div className="bg-white rounded-lg shadow-sm p-8">
          <div className="mb-8">
            <h1 className="text-2xl font-bold text-gray-900 mb-2">Add New Client</h1>
            <p className="text-gray-600">Enter client details to add them to your system</p>
          </div>

          {error && (
            <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg">
              <p className="text-red-800 text-sm">{error}</p>
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-6">
            {/* Client Name */}
            <div>
              <label htmlFor="name" className="block text-sm font-medium text-gray-700 mb-2">
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
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
            </div>

            {/* Client Code */}
            <div>
              <label htmlFor="code" className="block text-sm font-medium text-gray-700 mb-2">
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
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
              <p className="mt-1 text-sm text-gray-500">
                Short identifier for quick reference (e.g., initials or abbreviation)
              </p>
            </div>

            {/* Actions */}
            <div className="flex gap-3 pt-4">
              <button
                type="submit"
                disabled={saving}
                className="flex-1 flex items-center justify-center gap-2 px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:bg-gray-400 disabled:cursor-not-allowed transition-colors font-medium"
              >
                {saving ? (
                  <>
                    <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
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
                className="px-6 py-3 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 transition-colors font-medium"
              >
                Cancel
              </button>
            </div>
          </form>

          {/* Help Text */}
          <div className="mt-8 p-4 bg-blue-50 rounded-lg">
            <h3 className="font-medium text-blue-900 mb-2">💡 Quick Tips</h3>
            <ul className="text-sm text-blue-800 space-y-1">
              <li>• Use a consistent naming convention for client codes</li>
              <li>• Client codes should be short and memorable</li>
              <li>• You can also import multiple clients at once via CSV</li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
}

export default ManualClientEntry;