/**
 * OrganizationSettings.tsx - Configure organization context for AI
 * Place in: frontend/src/pages/OrganizationSettings.tsx
 */

import React, { useState, useEffect } from 'react';

interface OrgSettings {
  company_name: string;
  industry: string;
  description: string;
  internal_keywords: string[];
  default_internal_project: string;
  custom_instructions: string;
}

interface KnownEntity {
  id?: number;
  entity_type: 'client' | 'project' | 'category' | 'person';
  name: string;
  aliases: string[];
  description: string;
  is_internal: boolean;
}

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:7123/api';

export default function OrganizationSettings() {
  const [settings, setSettings] = useState<OrgSettings>({
    company_name: '',
    industry: '',
    description: '',
    internal_keywords: [],
    default_internal_project: '',
    custom_instructions: '',
  });
  
  const [entities, setEntities] = useState<KnownEntity[]>([]);
  const [newKeyword, setNewKeyword] = useState('');
  const [newEntity, setNewEntity] = useState<KnownEntity>({
    entity_type: 'client',
    name: '',
    aliases: [],
    description: '',
    is_internal: false,
  });
  const [newAlias, setNewAlias] = useState('');
  const [loading, setLoading] = useState(true);
  const [saveStatus, setSaveStatus] = useState<string | null>(null);

  // Load settings and entities
  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    setLoading(true);
    try {
      const [settingsRes, entitiesRes] = await Promise.all([
        fetch(`${API_BASE}/settings/organization/`),
        fetch(`${API_BASE}/settings/entities/`),
      ]);
      
      const settingsData = await settingsRes.json();
      const entitiesData = await entitiesRes.json();
      
      setSettings(settingsData);
      setEntities(entitiesData);
    } catch (error) {
      console.error('Failed to load settings:', error);
    } finally {
      setLoading(false);
    }
  };

  // Save organization settings
  const saveSettings = async () => {
    setSaveStatus('Saving...');
    try {
      const response = await fetch(`${API_BASE}/settings/organization/`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(settings),
      });
      
      if (response.ok) {
        setSaveStatus('✓ Saved successfully!');
        setTimeout(() => setSaveStatus(null), 3000);
      } else {
        setSaveStatus('❌ Failed to save');
      }
    } catch (error) {
      console.error('Failed to save settings:', error);
      setSaveStatus('❌ Failed to save');
    }
  };

  // Add internal keyword
  const addKeyword = () => {
    if (newKeyword && !settings.internal_keywords.includes(newKeyword)) {
      setSettings({
        ...settings,
        internal_keywords: [...settings.internal_keywords, newKeyword],
      });
      setNewKeyword('');
    }
  };

  // Remove internal keyword
  const removeKeyword = (keyword: string) => {
    setSettings({
      ...settings,
      internal_keywords: settings.internal_keywords.filter(k => k !== keyword),
    });
  };

  // Add entity
  const addEntity = async () => {
    if (!newEntity.name) {
      alert('Please enter a name for the entity');
      return;
    }
    
    try {
      const response = await fetch(`${API_BASE}/settings/entities/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newEntity),
      });
      
      if (response.ok) {
        await loadData();
        // Reset form for next entity
        setNewEntity({
          entity_type: 'client',
          name: '',
          aliases: [],
          description: '',
          is_internal: false,
        });
        setNewAlias('');
        alert(`✅ ${newEntity.name} added successfully! Add another or scroll down to see your list.`);
      } else {
        alert('Failed to add entity. Check console for errors.');
      }
    } catch (error) {
      console.error('Failed to add entity:', error);
      alert('Failed to add entity. Check console for errors.');
    }
  };

  // Delete entity
  const deleteEntity = async (id: number) => {
    if (!confirm('Delete this entity?')) return;
    
    try {
      await fetch(`${API_BASE}/settings/entities/${id}/`, {
        method: 'DELETE',
      });
      await loadData();
    } catch (error) {
      console.error('Failed to delete entity:', error);
    }
  };

  // Add alias to new entity
  const addAliasToNewEntity = () => {
    if (newAlias && !newEntity.aliases.includes(newAlias)) {
      setNewEntity({
        ...newEntity,
        aliases: [...newEntity.aliases, newAlias],
      });
      setNewAlias('');
    }
  };

  if (loading) {
    return <div className="p-6">Loading settings...</div>;
  }

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold">Organization Settings</h1>
        <button
          onClick={saveSettings}
          className="bg-blue-600 text-white px-6 py-2 rounded-lg hover:bg-blue-700"
        >
          Save Changes
        </button>
      </div>
      
      {saveStatus && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 text-blue-800">
          {saveStatus}
        </div>
      )}

      <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
        <p className="text-sm text-yellow-800">
          <strong>💡 Tip:</strong> Configure your company information and known clients so the AI can better classify your time entries automatically.
        </p>
      </div>

      {/* Company Information */}
      <section className="bg-white rounded-lg shadow p-6 space-y-4">
        <h2 className="text-xl font-semibold mb-4">Company Information</h2>
        
        <div>
          <label className="block text-sm font-medium mb-2">Company Name *</label>
          <input
            type="text"
            className="w-full border rounded-lg px-4 py-2"
            value={settings.company_name}
            onChange={(e) => setSettings({ ...settings, company_name: e.target.value })}
            placeholder="e.g., PredictorEdge"
          />
          <p className="text-sm text-gray-600 mt-1">
            Your business name (NOT a client). This helps AI distinguish internal work.
          </p>
        </div>

        <div>
          <label className="block text-sm font-medium mb-2">Industry</label>
          <input
            type="text"
            className="w-full border rounded-lg px-4 py-2"
            value={settings.industry}
            onChange={(e) => setSettings({ ...settings, industry: e.target.value })}
            placeholder="e.g., Analytics & Consulting"
          />
        </div>

        <div>
          <label className="block text-sm font-medium mb-2">Description</label>
          <textarea
            className="w-full border rounded-lg px-4 py-2"
            rows={3}
            value={settings.description}
            onChange={(e) => setSettings({ ...settings, description: e.target.value })}
            placeholder="Brief description of what your company does"
          />
        </div>
      </section>

      {/* Internal Work Configuration */}
      <section className="bg-white rounded-lg shadow p-6 space-y-4">
        <h2 className="text-xl font-semibold mb-4">Internal Work Detection</h2>
        
        <div>
          <label className="block text-sm font-medium mb-2">Internal Keywords</label>
          <div className="flex gap-2 mb-2">
            <input
              type="text"
              className="flex-1 border rounded-lg px-4 py-2"
              value={newKeyword}
              onChange={(e) => setNewKeyword(e.target.value)}
              onKeyPress={(e) => e.key === 'Enter' && addKeyword()}
              placeholder="e.g., admin, standup, internal"
            />
            <button
              onClick={addKeyword}
              className="bg-gray-200 px-4 py-2 rounded-lg hover:bg-gray-300"
            >
              Add
            </button>
          </div>
          <div className="flex flex-wrap gap-2">
            {settings.internal_keywords.map((keyword) => (
              <span
                key={keyword}
                className="bg-blue-100 text-blue-800 px-3 py-1 rounded-full text-sm flex items-center gap-2"
              >
                {keyword}
                <button
                  onClick={() => removeKeyword(keyword)}
                  className="text-blue-600 hover:text-blue-800"
                >
                  ×
                </button>
              </span>
            ))}
          </div>
          <p className="text-sm text-gray-600 mt-2">
            When these words appear in calendar events or tasks, the AI will classify them as internal work.
          </p>
        </div>

        <div>
          <label className="block text-sm font-medium mb-2">Default Internal Project</label>
          <input
            type="text"
            className="w-full border rounded-lg px-4 py-2"
            value={settings.default_internal_project}
            onChange={(e) => setSettings({ ...settings, default_internal_project: e.target.value })}
            placeholder="e.g., Internal Operations"
          />
          <p className="text-sm text-gray-600 mt-1">
            Project name to use for internal work when no specific project is identified.
          </p>
        </div>

        <div>
          <label className="block text-sm font-medium mb-2">Custom AI Instructions</label>
          <textarea
            className="w-full border rounded-lg px-4 py-2"
            rows={4}
            value={settings.custom_instructions}
            onChange={(e) => setSettings({ ...settings, custom_instructions: e.target.value })}
            placeholder="e.g., Any work mentioning 'standup' or 'team sync' is internal work. Client meetings should default to 'Consulting' category."
          />
          <p className="text-sm text-gray-600 mt-1">
            Additional context to help the AI classify your work correctly.
          </p>
        </div>
      </section>

      {/* Known Entities */}
      <section className="bg-white rounded-lg shadow p-6 space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-xl font-semibold">Known Clients & Projects</h2>
            <p className="text-sm text-gray-600 mt-1">
              Add all your clients so AI can recognize them automatically. You can add as many as you need!
            </p>
          </div>
          <div className="text-right">
            <div className="text-3xl font-bold text-blue-600">{entities.length}</div>
            <div className="text-sm text-gray-600">Total Added</div>
          </div>
        </div>
        
        {/* Add New Entity */}
        <div className="bg-gray-50 rounded-lg p-4 space-y-3 border-2 border-dashed border-gray-300">
          <div className="flex items-center justify-between">
            <h3 className="font-medium text-lg">➕ Add New Client/Project</h3>
            <span className="text-xs text-gray-500">Fill form and click Add. Repeat for each entity.</span>
          </div>
          
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium mb-2">Type</label>
              <select
                className="w-full border rounded-lg px-4 py-2"
                value={newEntity.entity_type}
                onChange={(e) => setNewEntity({ ...newEntity, entity_type: e.target.value as any })}
              >
                <option value="client">Client</option>
                <option value="project">Project</option>
                <option value="category">Category</option>
                <option value="person">Person</option>
              </select>
            </div>
            
            <div>
              <label className="block text-sm font-medium mb-2">Name *</label>
              <input
                type="text"
                className="w-full border rounded-lg px-4 py-2"
                value={newEntity.name}
                onChange={(e) => setNewEntity({ ...newEntity, name: e.target.value })}
                placeholder="e.g., Acme Corp"
              />
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium mb-2">Aliases / Keywords</label>
            <div className="flex gap-2 mb-2">
              <input
                type="text"
                className="flex-1 border rounded-lg px-4 py-2"
                value={newAlias}
                onChange={(e) => setNewAlias(e.target.value)}
                onKeyPress={(e) => e.key === 'Enter' && addAliasToNewEntity()}
                placeholder="e.g., ACME, acme.com"
              />
              <button
                onClick={addAliasToNewEntity}
                className="bg-gray-200 px-4 py-2 rounded-lg hover:bg-gray-300"
              >
                Add
              </button>
            </div>
            <div className="flex flex-wrap gap-2">
              {newEntity.aliases.map((alias) => (
                <span
                  key={alias}
                  className="bg-gray-100 px-3 py-1 rounded-full text-sm flex items-center gap-2"
                >
                  {alias}
                  <button
                    onClick={() => setNewEntity({
                      ...newEntity,
                      aliases: newEntity.aliases.filter(a => a !== alias)
                    })}
                    className="text-gray-600 hover:text-gray-800"
                  >
                    ×
                  </button>
                </span>
              ))}
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium mb-2">Description</label>
            <input
              type="text"
              className="w-full border rounded-lg px-4 py-2"
              value={newEntity.description}
              onChange={(e) => setNewEntity({ ...newEntity, description: e.target.value })}
              placeholder="Brief description"
            />
          </div>

          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              id="is-internal"
              checked={newEntity.is_internal}
              onChange={(e) => setNewEntity({ ...newEntity, is_internal: e.target.checked })}
            />
            <label htmlFor="is-internal" className="text-sm">
              This is internal (not a real client)
            </label>
          </div>

          <button
            onClick={addEntity}
            disabled={!newEntity.name}
            className="bg-green-600 text-white px-6 py-2 rounded-lg hover:bg-green-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
          >
            ➕ Add Entity
          </button>
          
          <div className="bg-blue-50 border border-blue-200 rounded p-3 text-sm text-blue-800">
            💡 <strong>Tip:</strong> After clicking "Add Entity", the form will clear so you can add another. 
            Scroll down to see your list of added entities.
          </div>
        </div>

        {/* Entity List */}
        <div className="space-y-2">
          {['client', 'project', 'category', 'person'].map((type) => {
            const typeEntities = entities.filter(e => e.entity_type === type);
            if (typeEntities.length === 0) return null;
            
            return (
              <div key={type}>
                <h3 className="font-medium text-sm text-gray-600 uppercase mb-2 mt-4">
                  {type}s ({typeEntities.length})
                </h3>
                <div className="space-y-2">
                  {typeEntities.map((entity) => (
                    <div
                      key={entity.id}
                      className="flex items-center justify-between border rounded-lg p-3 hover:bg-gray-50"
                    >
                      <div className="flex-1">
                        <div className="flex items-center gap-2">
                          <span className="font-medium">{entity.name}</span>
                          {entity.is_internal && (
                            <span className="bg-yellow-100 text-yellow-800 text-xs px-2 py-1 rounded">
                              INTERNAL
                            </span>
                          )}
                        </div>
                        {entity.aliases.length > 0 && (
                          <div className="text-sm text-gray-600 mt-1">
                            Also: {entity.aliases.join(', ')}
                          </div>
                        )}
                        {entity.description && (
                          <div className="text-sm text-gray-500 mt-1">{entity.description}</div>
                        )}
                      </div>
                      <button
                        onClick={() => deleteEntity(entity.id!)}
                        className="text-red-600 hover:text-red-800 px-3"
                      >
                        Delete
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </section>
    </div>
  );
}