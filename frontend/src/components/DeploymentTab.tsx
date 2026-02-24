import React, { useState, useEffect, useCallback } from 'react';

// ─── Types ───
interface DeploymentToken {
  id: number;
  token: string;
  is_active: boolean;
  is_valid: boolean;
  created_at: string;
  expires_at: string | null;
  max_devices: number | null;
  devices_claimed: number;
  notes: string;
  created_by: string | null;
}

interface DeploymentTabProps {
  apiBase?: string;
}

// ─── Helpers ───
const getCSRFToken = (): string => {
  const match = document.cookie.match(/csrftoken=([^;]+)/);
  return match ? match[1] : '';
};

const apiRequest = async (url: string, options: RequestInit = {}) => {
  const resp = await fetch(url, {
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': getCSRFToken(),
      ...(options.headers || {}),
    },
    ...options,
  });
  return resp;
};

// ─── Sub-components ───

const CopyButton: React.FC<{ text: string; label?: string }> = ({ text, label }) => {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      const ta = document.createElement('textarea');
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  return (
    <button
      onClick={handleCopy}
      className={`inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md transition-all duration-200 ${
        copied
          ? 'bg-teal-50 text-teal-700 border border-teal-200'
          : 'bg-gray-50 text-gray-600 border border-gray-200 hover:bg-gray-100 hover:text-gray-800'
      }`}
    >
      {copied ? (
        <>
          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
          </svg>
          Copied!
        </>
      ) : (
        <>
          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
          </svg>
          {label || 'Copy'}
        </>
      )}
    </button>
  );
};

const TokenCard: React.FC<{
  token: DeploymentToken;
  onRevoke: (id: number) => void;
  revoking: number | null;
}> = ({ token, onRevoke, revoking }) => {
  const [showIntune, setShowIntune] = useState(false);

  const psInstallCmd = `powershell.exe -ExecutionPolicy Bypass -File install_timetracker.ps1 -OrgToken ${token.token}`;
  const uninstallCmd = `"C:\\Program Files\\TimeTracker\\unins000.exe" /VERYSILENT`;
  const detectionPath = `C:\\Program Files\\TimeTracker\\TimeTrackerAgent.exe`;

  const createdDate = new Date(token.created_at).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });

  return (
    <div
      className={`border rounded-lg overflow-hidden transition-all duration-200 ${
        token.is_valid
          ? 'border-gray-200 bg-white'
          : 'border-gray-100 bg-gray-50 opacity-70'
      }`}
    >
      {/* Header */}
      <div className="px-5 py-4 flex items-center justify-between">
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <code className="text-lg font-semibold tracking-wider text-gray-900 bg-teal-50 px-3 py-1 rounded-md border border-teal-100">
              {token.token}
            </code>
            <CopyButton text={token.token} />
          </div>

          {token.is_valid ? (
            <span className="inline-flex items-center gap-1 px-2.5 py-0.5 text-xs font-medium rounded-full bg-teal-50 text-teal-700 border border-teal-100">
              <span className="w-1.5 h-1.5 rounded-full bg-teal-500 animate-pulse" />
              Active
            </span>
          ) : (
            <span className="inline-flex items-center gap-1 px-2.5 py-0.5 text-xs font-medium rounded-full bg-gray-100 text-gray-500 border border-gray-200">
              <span className="w-1.5 h-1.5 rounded-full bg-gray-400" />
              {!token.is_active ? 'Revoked' : 'Expired'}
            </span>
          )}
        </div>

        <div className="flex items-center gap-2">
          {token.is_valid && (
            <button
              onClick={() => setShowIntune(!showIntune)}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md bg-teal-50 text-teal-700 border border-teal-100 hover:bg-teal-100 transition-colors"
            >
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
              {showIntune ? 'Hide' : 'Intune Setup'}
            </button>
          )}
          {token.is_active && (
            <button
              onClick={() => onRevoke(token.id)}
              disabled={revoking === token.id}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md text-red-600 border border-red-100 hover:bg-red-50 transition-colors disabled:opacity-50"
            >
              {revoking === token.id ? 'Revoking...' : 'Revoke'}
            </button>
          )}
        </div>
      </div>

      {/* Meta row */}
      <div className="px-5 pb-3 flex items-center gap-6 text-xs text-gray-500">
        <span>Created {createdDate}</span>
        {token.created_by && <span>by {token.created_by}</span>}
        <span className="font-medium text-teal-700">
          {token.devices_claimed} device{token.devices_claimed !== 1 ? 's' : ''} claimed
        </span>
        {token.max_devices && (
          <span>/ {token.max_devices} max</span>
        )}
        {token.notes && (
          <span className="italic text-gray-400">"{token.notes}"</span>
        )}
      </div>

      {/* Intune instructions */}
      {showIntune && token.is_valid && (
        <div className="border-t border-gray-100 bg-teal-50/30 px-5 py-4">
          <h4 className="text-sm font-semibold text-gray-800 mb-3">Intune Deployment Setup</h4>

          <div className="space-y-3">
            <div>
              <label className="block text-xs font-medium text-gray-500 mb-1">Install command (Intune)</label>
              <div className="flex items-center gap-2">
                <code className="flex-1 text-xs bg-white border border-gray-200 rounded px-3 py-2 text-gray-800 font-mono select-all break-all">
                  {psInstallCmd}
                </code>
                <CopyButton text={psInstallCmd} />
              </div>
            </div>

            <div>
              <label className="block text-xs font-medium text-gray-500 mb-1">Uninstall command</label>
              <div className="flex items-center gap-2">
                <code className="flex-1 text-xs bg-white border border-gray-200 rounded px-3 py-2 text-gray-800 font-mono select-all">
                  {uninstallCmd}
                </code>
                <CopyButton text={uninstallCmd} />
              </div>
            </div>

            <div>
              <label className="block text-xs font-medium text-gray-500 mb-1">Detection rule (file exists)</label>
              <div className="flex items-center gap-2">
                <code className="flex-1 text-xs bg-white border border-gray-200 rounded px-3 py-2 text-gray-800 font-mono select-all">
                  {detectionPath}
                </code>
                <CopyButton text={detectionPath} />
              </div>
            </div>

            <div className="mt-2 p-3 bg-teal-50 border border-teal-100 rounded-md">
              <p className="text-xs text-teal-800 leading-relaxed">
                <strong>Quick setup:</strong> In Intune Admin Center → Apps → Add → Windows app (Win32).
                Upload the <code className="bg-teal-100 px-1 rounded">.intunewin</code> package,
                paste the install command above, set detection rule to "File exists" at the path above,
                and assign to your device group.
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

// ─── Main Component ───

const DeploymentTab: React.FC<DeploymentTabProps> = ({ apiBase = '/api' }) => {
  const [tokens, setTokens] = useState<DeploymentToken[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [revoking, setRevoking] = useState<number | null>(null);

  const [showCreate, setShowCreate] = useState(false);
  const [notes, setNotes] = useState('');
  const [maxDevices, setMaxDevices] = useState('');

  const fetchTokens = useCallback(async () => {
    try {
      const resp = await apiRequest(`${apiBase}/deploy/tokens/`);
      if (resp.ok) {
        const data = await resp.json();
        setTokens(data.tokens || []);
      } else {
        setError('Failed to load deployment tokens');
      }
    } catch (e) {
      setError('Network error loading tokens');
    } finally {
      setLoading(false);
    }
  }, [apiBase]);

  useEffect(() => {
    fetchTokens();
  }, [fetchTokens]);

  const handleCreate = async () => {
    setCreating(true);
    setError(null);
    try {
      const body: any = {};
      if (notes.trim()) body.notes = notes.trim();
      if (maxDevices) body.max_devices = parseInt(maxDevices, 10);

      const resp = await apiRequest(`${apiBase}/deploy/tokens/create/`, {
        method: 'POST',
        body: JSON.stringify(body),
      });

      if (resp.ok) {
        setShowCreate(false);
        setNotes('');
        setMaxDevices('');
        await fetchTokens();
      } else {
        const data = await resp.json();
        setError(data.error || 'Failed to create token');
      }
    } catch {
      setError('Network error creating token');
    } finally {
      setCreating(false);
    }
  };

  const handleRevoke = async (tokenId: number) => {
    if (!window.confirm('Revoke this token? Existing devices will keep working, but no new devices can claim it.')) {
      return;
    }

    setRevoking(tokenId);
    try {
      const resp = await apiRequest(`${apiBase}/deploy/tokens/${tokenId}/revoke/`, {
        method: 'POST',
      });

      if (resp.ok) {
        await fetchTokens();
      } else {
        setError('Failed to revoke token');
      }
    } catch {
      setError('Network error revoking token');
    } finally {
      setRevoking(null);
    }
  };

  const activeTokens = tokens.filter((t) => t.is_active);
  const inactiveTokens = tokens.filter((t) => !t.is_active);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h3 className="text-lg font-semibold text-gray-900">MDM Deployment</h3>
          <p className="mt-1 text-sm text-gray-500">
            Deploy TimeTracker to workstations via Intune or other MDM solutions.
            Generate a token, bake it into the installer, and devices auto-register with your organization.
          </p>
        </div>
        <button
          onClick={() => setShowCreate(!showCreate)}
          className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-lg text-white hover:opacity-90 transition-colors shadow-sm"
          style={{ backgroundColor: '#0d9488' }}
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
          </svg>
          Generate Token
        </button>
      </div>

      {/* Error */}
      {error && (
        <div className="flex items-center gap-2 p-3 text-sm bg-red-50 border border-red-100 text-red-700 rounded-lg">
          <svg className="w-4 h-4 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          {error}
          <button onClick={() => setError(null)} className="ml-auto text-red-400 hover:text-red-600">✕</button>
        </div>
      )}

      {/* Create form */}
      {showCreate && (
        <div className="border border-teal-200 bg-teal-50/50 rounded-lg p-5">
          <h4 className="text-sm font-semibold text-gray-800 mb-4">New Deployment Token</h4>
          <div className="grid grid-cols-2 gap-4 mb-4">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Notes (optional)</label>
              <input
                type="text"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder="e.g., Anderson & Associates rollout"
                className="w-full px-3 py-2 text-sm border border-gray-200 rounded-md focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Max devices (optional)</label>
              <input
                type="number"
                value={maxDevices}
                onChange={(e) => setMaxDevices(e.target.value)}
                placeholder="Unlimited"
                min="1"
                className="w-full px-3 py-2 text-sm border border-gray-200 rounded-md focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent"
              />
            </div>
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={handleCreate}
              disabled={creating}
              className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-md text-white transition-colors disabled:opacity-50"
              style={{ backgroundColor: '#0d9488' }}
            >
              {creating ? (
                <>
                  <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  Creating...
                </>
              ) : (
                'Create Token'
              )}
            </button>
            <button
              onClick={() => {
                setShowCreate(false);
                setNotes('');
                setMaxDevices('');
              }}
              className="px-4 py-2 text-sm font-medium text-gray-600 hover:text-gray-800 transition-colors"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Empty state */}
      {tokens.length === 0 && !loading && (
        <div className="border border-dashed border-teal-300 rounded-lg p-8 text-center bg-teal-50/30">
          <svg className="w-12 h-12 mx-auto text-teal-300 mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 3v2m6-2v2M9 19v2m6-2v2M5 9H3m2 6H3m18-6h-2m2 6h-2M7 19h10a2 2 0 002-2V7a2 2 0 00-2-2H7a2 2 0 00-2 2v10a2 2 0 002 2zM9 9h6v6H9V9z" />
          </svg>
          <h4 className="text-sm font-semibold text-gray-700 mb-1">No deployment tokens yet</h4>
          <p className="text-sm text-gray-500 max-w-md mx-auto mb-4">
            Generate a token to enable silent MDM deployment. The token is included in the installer so
            devices auto-register with your firm — no manual pairing needed.
          </p>
          <button
            onClick={() => setShowCreate(true)}
            className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-lg text-white transition-colors"
            style={{ backgroundColor: '#0d9488' }}
          >
            Generate Your First Token
          </button>
        </div>
      )}

      {/* Loading */}
      {loading && (
        <div className="flex items-center justify-center py-12">
          <svg className="w-6 h-6 animate-spin text-teal-500" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
        </div>
      )}

      {/* Active tokens */}
      {activeTokens.length > 0 && (
        <div className="space-y-3">
          {activeTokens.map((token) => (
            <TokenCard key={token.id} token={token} onRevoke={handleRevoke} revoking={revoking} />
          ))}
        </div>
      )}

      {/* Inactive tokens */}
      {inactiveTokens.length > 0 && (
        <div>
          <button
            onClick={() => {
              const el = document.getElementById('inactive-tokens');
              if (el) el.classList.toggle('hidden');
            }}
            className="text-xs font-medium text-gray-400 hover:text-gray-600 transition-colors mb-2"
          >
            Show {inactiveTokens.length} revoked token{inactiveTokens.length !== 1 ? 's' : ''}
          </button>
          <div id="inactive-tokens" className="hidden space-y-2">
            {inactiveTokens.map((token) => (
              <TokenCard key={token.id} token={token} onRevoke={handleRevoke} revoking={revoking} />
            ))}
          </div>
        </div>
      )}

      {/* How it works */}
      {tokens.length > 0 && (
        <div className="border border-teal-100 rounded-lg bg-teal-50/40 p-5">
          <h4 className="text-sm font-semibold text-gray-700 mb-3">How MDM Deployment Works</h4>
          <div className="grid grid-cols-3 gap-4">
            <div className="flex gap-3">
              <div className="flex-shrink-0 w-7 h-7 rounded-full bg-teal-100 text-teal-700 flex items-center justify-center text-xs font-bold">1</div>
              <div>
                <p className="text-xs font-medium text-gray-700">Generate Token</p>
                <p className="text-xs text-gray-500 mt-0.5">Create a token above and share with your IT admin.</p>
              </div>
            </div>
            <div className="flex gap-3">
              <div className="flex-shrink-0 w-7 h-7 rounded-full bg-teal-100 text-teal-700 flex items-center justify-center text-xs font-bold">2</div>
              <div>
                <p className="text-xs font-medium text-gray-700">Deploy via Intune</p>
                <p className="text-xs text-gray-500 mt-0.5">Upload installer to Intune with the install command containing your token.</p>
              </div>
            </div>
            <div className="flex gap-3">
              <div className="flex-shrink-0 w-7 h-7 rounded-full bg-teal-100 text-teal-700 flex items-center justify-center text-xs font-bold">3</div>
              <div>
                <p className="text-xs font-medium text-gray-700">Auto-Paired</p>
                <p className="text-xs text-gray-500 mt-0.5">Each machine matches to a user by their Windows login email. Zero touch.</p>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default DeploymentTab;