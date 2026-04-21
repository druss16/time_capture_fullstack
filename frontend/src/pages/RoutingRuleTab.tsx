import { useState, useEffect } from 'react';

/**
 * RoutingRulesTab.tsx
 *
 * Admin UI for per-firm routing rules. Drops into your MavOps admin
 * dashboard under /mavops-admin/orgs/:orgId/settings/routing-rules
 *
 * Features:
 *   - List / enable / disable / delete rules
 *   - Create new rule form
 *   - "Test this title" simulator — paste a title, see what fires
 *   - Distinguishes default (shipped) rules from custom rules
 *   - Shows fire_count telemetry so admins know what rules actually trigger
 *
 * Auth token: reads from localStorage 'auth_token' with fallbacks
 *   (auth_token → tt_auth_token → authToken → token) per established convention.
 */

interface RoutingRule {
  id: number;
  match_type: 'exe' | 'exe_family' | 'title_contains' | 'title_regex' | 'file_path_contains';
  match_type_display: string;
  match_value: string;
  action: 'route_to_client' | 'never_switch_away' | 'suppress';
  action_display: string;
  target_client_id: number | null;
  target_client_name: string | null;
  priority: number;
  enabled: boolean;
  description: string;
  is_default: boolean;
  fire_count: number;
  last_fired_at: string | null;
  created_by: string | null;
  created_at: string;
}

interface Client {
  id: number;
  name: string;
}

interface Props {
  orgId: number;
  orgName: string;
  clients: Client[];
}

function getToken(): string | null {
  for (const k of ['auth_token', 'tt_auth_token', 'authToken', 'token']) {
    const v = localStorage.getItem(k);
    if (v) return v;
  }
  return null;
}

async function api(path: string, init: RequestInit = {}): Promise<any> {
  const token = getToken();
  const resp = await fetch(path, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init.headers || {}),
    },
  });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`${resp.status}: ${text}`);
  }
  return resp.json();
}

export default function RoutingRulesTab({ orgId, orgName, clients }: Props) {
  const [rules, setRules] = useState<RoutingRule[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [testerInput, setTesterInput] = useState({ title: '', exe: '', file_path: '' });
  const [testerResult, setTesterResult] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadRules();
  }, [orgId]);

  async function loadRules() {
    setLoading(true);
    try {
      const data = await api(`/api/orgs/${orgId}/routing-rules/`);
      setRules(data.rules);
      setError(null);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  async function toggleEnabled(rule: RoutingRule) {
    try {
      await api(`/api/orgs/${orgId}/routing-rules/${rule.id}/`, {
        method: 'PATCH',
        body: JSON.stringify({ enabled: !rule.enabled }),
      });
      loadRules();
    } catch (e: any) {
      alert(`Failed: ${e.message}`);
    }
  }

  async function deleteRule(rule: RoutingRule) {
    if (rule.is_default) {
      alert('Default rules can only be disabled, not deleted.');
      return;
    }
    if (!confirm(`Delete rule "${rule.match_value}"?`)) return;
    try {
      await api(`/api/orgs/${orgId}/routing-rules/${rule.id}/`, { method: 'DELETE' });
      loadRules();
    } catch (e: any) {
      alert(`Failed: ${e.message}`);
    }
  }

  async function runTest() {
    try {
      const data = await api(`/api/orgs/${orgId}/routing-rules/test/`, {
        method: 'POST',
        body: JSON.stringify(testerInput),
      });
      setTesterResult(data);
    } catch (e: any) {
      alert(`Test failed: ${e.message}`);
    }
  }

  if (loading) {
    return <div className="p-6 text-slate-500">Loading routing rules…</div>;
  }

  if (error) {
    return (
      <div className="p-6">
        <div className="bg-red-50 border border-red-200 text-red-800 rounded p-4">
          Error: {error}
        </div>
      </div>
    );
  }

  return (
    <div className="bg-slate-50 min-h-screen">
      <div className="max-w-6xl mx-auto p-6 space-y-6">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Routing Rules</h1>
          <p className="text-slate-600 mt-1">
            Hard rules for <strong>{orgName}</strong>. These take priority over
            the AI client switcher and learned patterns. Use them to lock in
            firm-specific behavior (e.g. "UltraTax is always Internal - Tax").
          </p>
        </div>

        {/* Rule Tester */}
        <div className="bg-white border border-slate-200 rounded-lg shadow-sm">
          <div className="border-l-4 border-blue-500 px-4 py-3">
            <h2 className="font-semibold text-slate-900">Test a Window Title</h2>
            <p className="text-sm text-slate-600">
              Paste what an agent might see. Preview which rule (if any) would fire.
            </p>
          </div>
          <div className="p-4 grid grid-cols-1 md:grid-cols-3 gap-3">
            <input
              className="border border-slate-300 rounded px-3 py-2 text-sm"
              placeholder="Window title"
              value={testerInput.title}
              onChange={(e) => setTesterInput({ ...testerInput, title: e.target.value })}
            />
            <input
              className="border border-slate-300 rounded px-3 py-2 text-sm"
              placeholder="Exe name (e.g. utw25.exe)"
              value={testerInput.exe}
              onChange={(e) => setTesterInput({ ...testerInput, exe: e.target.value })}
            />
            <input
              className="border border-slate-300 rounded px-3 py-2 text-sm"
              placeholder="File path (optional)"
              value={testerInput.file_path}
              onChange={(e) => setTesterInput({ ...testerInput, file_path: e.target.value })}
            />
          </div>
          <div className="px-4 pb-4">
            <button
              onClick={runTest}
              className="bg-blue-600 text-white px-4 py-2 rounded text-sm font-medium hover:bg-blue-700"
            >
              Run Test
            </button>
          </div>

          {testerResult && (
            <div className="border-t border-slate-200 p-4 bg-slate-50 text-sm">
              <div className="font-medium mb-2 text-slate-900">
                Outcome: {testerResult.outcome.message}
              </div>
              {testerResult.matches.length > 0 && (
                <div>
                  <div className="text-slate-600 mb-1">Matching rules (highest priority wins):</div>
                  <ol className="list-decimal list-inside space-y-1">
                    {testerResult.matches.map((m: any) => (
                      <li key={m.rule_id}>
                        <code className="bg-slate-200 px-1 rounded">{m.match_type}={m.match_value}</code>
                        {' → '}
                        {m.target_client_name || m.action}
                        <span className="text-slate-500"> (priority {m.priority})</span>
                      </li>
                    ))}
                  </ol>
                </div>
              )}
              {testerResult.matches.length === 0 && (
                <div className="text-slate-600">
                  No rules match — agent falls through to default tier matching.
                </div>
              )}
            </div>
          )}
        </div>

        {/* Rules list */}
        <div className="bg-white border border-slate-200 rounded-lg shadow-sm">
          <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200">
            <h2 className="font-semibold text-slate-900">
              Active Rules ({rules.filter((r) => r.enabled).length} of {rules.length})
            </h2>
            <button
              onClick={() => setShowCreateForm(!showCreateForm)}
              className="bg-slate-900 text-white px-3 py-1.5 rounded text-sm font-medium hover:bg-slate-700"
            >
              + New Rule
            </button>
          </div>

          {showCreateForm && (
            <CreateRuleForm
              orgId={orgId}
              clients={clients}
              onCreated={() => {
                setShowCreateForm(false);
                loadRules();
              }}
              onCancel={() => setShowCreateForm(false)}
            />
          )}

          <table className="w-full text-sm">
            <thead className="bg-slate-100 sticky top-0">
              <tr className="text-left text-slate-600">
                <th className="px-4 py-2 font-medium">Match</th>
                <th className="px-4 py-2 font-medium">Action</th>
                <th className="px-4 py-2 font-medium">Priority</th>
                <th className="px-4 py-2 font-medium">Fires</th>
                <th className="px-4 py-2 font-medium">Type</th>
                <th className="px-4 py-2 font-medium">State</th>
                <th className="px-4 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {rules.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-slate-500">
                    No rules yet. Click "New Rule" to create one.
                  </td>
                </tr>
              )}
              {rules.map((r) => (
                <tr
                  key={r.id}
                  className={`border-t border-slate-100 ${r.enabled ? '' : 'opacity-50'}`}
                >
                  <td className="px-4 py-3">
                    <div className="font-mono text-xs text-slate-600">{r.match_type}</div>
                    <div className="font-medium">{r.match_value}</div>
                    {r.description && (
                      <div className="text-xs text-slate-500">{r.description}</div>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    {r.action === 'route_to_client' && r.target_client_name && (
                      <span>
                        → <strong>{r.target_client_name}</strong>
                      </span>
                    )}
                    {r.action !== 'route_to_client' && r.action_display}
                  </td>
                  <td className="px-4 py-3">{r.priority}</td>
                  <td className="px-4 py-3">
                    {r.fire_count}
                    {r.last_fired_at && (
                      <div className="text-xs text-slate-500">
                        {new Date(r.last_fired_at).toLocaleDateString()}
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    {r.is_default ? (
                      <span className="text-xs bg-blue-100 text-blue-800 px-2 py-0.5 rounded">
                        default
                      </span>
                    ) : (
                      <span className="text-xs bg-slate-100 text-slate-700 px-2 py-0.5 rounded">
                        custom
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <button
                      onClick={() => toggleEnabled(r)}
                      className={`text-xs px-2 py-0.5 rounded ${
                        r.enabled
                          ? 'bg-green-100 text-green-800 hover:bg-green-200'
                          : 'bg-slate-200 text-slate-600 hover:bg-slate-300'
                      }`}
                    >
                      {r.enabled ? 'Enabled' : 'Disabled'}
                    </button>
                  </td>
                  <td className="px-4 py-3 text-right">
                    {!r.is_default && (
                      <button
                        onClick={() => deleteRule(r)}
                        className="text-red-600 hover:text-red-800 text-xs"
                      >
                        Delete
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}


// ---------- New rule form ----------------------------------------------

function CreateRuleForm({
  orgId,
  clients,
  onCreated,
  onCancel,
}: {
  orgId: number;
  clients: Client[];
  onCreated: () => void;
  onCancel: () => void;
}) {
  const [form, setForm] = useState({
    match_type: 'exe_family',
    match_value: '',
    action: 'route_to_client',
    target_client_id: '',
    priority: 100,
    description: '',
    enabled: true,
  });
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    try {
      await api(`/api/orgs/${orgId}/routing-rules/`, {
        method: 'POST',
        body: JSON.stringify({
          ...form,
          target_client_id: form.target_client_id ? Number(form.target_client_id) : null,
        }),
      });
      onCreated();
    } catch (e: any) {
      alert(`Save failed: ${e.message}`);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="border-t border-slate-200 bg-slate-50 p-4 space-y-3">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <label className="block text-sm">
          <span className="text-slate-700 font-medium">Match type</span>
          <select
            className="mt-1 w-full border border-slate-300 rounded px-3 py-2 text-sm"
            value={form.match_type}
            onChange={(e) => setForm({ ...form, match_type: e.target.value })}
          >
            <option value="exe_family">App Family (e.g. taxwise, ultratax)</option>
            <option value="exe">Exact Exe Name</option>
            <option value="title_contains">Title Contains</option>
            <option value="title_regex">Title Regex</option>
            <option value="file_path_contains">File Path Contains</option>
          </select>
        </label>
        <label className="block text-sm">
          <span className="text-slate-700 font-medium">Match value</span>
          <input
            className="mt-1 w-full border border-slate-300 rounded px-3 py-2 text-sm"
            value={form.match_value}
            onChange={(e) => setForm({ ...form, match_value: e.target.value })}
            placeholder={form.match_type === 'exe_family' ? 'taxwise' : '...'}
          />
        </label>

        <label className="block text-sm">
          <span className="text-slate-700 font-medium">Action</span>
          <select
            className="mt-1 w-full border border-slate-300 rounded px-3 py-2 text-sm"
            value={form.action}
            onChange={(e) => setForm({ ...form, action: e.target.value })}
          >
            <option value="route_to_client">Route to a Client</option>
            <option value="never_switch_away">Never Switch Away</option>
            <option value="suppress">Suppress (Ignore)</option>
          </select>
        </label>

        {form.action === 'route_to_client' && (
          <label className="block text-sm">
            <span className="text-slate-700 font-medium">Target client</span>
            <select
              className="mt-1 w-full border border-slate-300 rounded px-3 py-2 text-sm"
              value={form.target_client_id}
              onChange={(e) => setForm({ ...form, target_client_id: e.target.value })}
            >
              <option value="">— Select a client —</option>
              {clients.map((c) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
          </label>
        )}

        <label className="block text-sm">
          <span className="text-slate-700 font-medium">Priority</span>
          <input
            type="number"
            className="mt-1 w-full border border-slate-300 rounded px-3 py-2 text-sm"
            value={form.priority}
            onChange={(e) => setForm({ ...form, priority: Number(e.target.value) })}
          />
          <span className="text-xs text-slate-500 mt-1 block">
            Higher wins. 500 = hard firm rule, 300 = default, 100 = soft override.
          </span>
        </label>

        <label className="block text-sm md:col-span-2">
          <span className="text-slate-700 font-medium">Description</span>
          <input
            className="mt-1 w-full border border-slate-300 rounded px-3 py-2 text-sm"
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
            placeholder="Human-readable note for other admins"
          />
        </label>
      </div>

      <div className="flex gap-2 pt-2">
        <button
          onClick={save}
          disabled={saving || !form.match_value}
          className="bg-slate-900 text-white px-4 py-2 rounded text-sm font-medium hover:bg-slate-700 disabled:opacity-50"
        >
          {saving ? 'Saving…' : 'Save Rule'}
        </button>
        <button
          onClick={onCancel}
          className="bg-white border border-slate-300 px-4 py-2 rounded text-sm font-medium hover:bg-slate-100"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}