// src/pages/settings/TokenTab.tsx
import { useState } from 'react';
import { Key, Eye, EyeOff, Copy, RefreshCw } from 'lucide-react';
import { safeFetchJson } from '@/lib/api';
import type { InstallToken } from './types';

const RAW_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:7123/api';
const API_BASE = RAW_BASE.endsWith('/api') ? RAW_BASE : `${RAW_BASE.replace(/\/+$/, '')}/api`;

interface Props {
  token: InstallToken | null;
  onRefresh: () => void;
  onSuccess: (msg: string) => void;
  onError: (msg: string) => void;
}

export default function TokenTab({ token, onRefresh, onSuccess, onError }: Props) {
  const [showToken, setShowToken]       = useState(false);
  const [regenerating, setRegenerating] = useState(false);

  const handleCopy = async () => {
    if (!token?.token) return;
    try {
      await navigator.clipboard.writeText(token.token);
      onSuccess('Token copied to clipboard');
    } catch {
      onError('Failed to copy token');
    }
  };

  const handleRegenerate = async () => {
    if (!confirm('Regenerate the install token? Existing tokens will be invalidated.')) return;
    setRegenerating(true);
    try {
      await safeFetchJson(`${API_BASE}/settings/install-token/regenerate/`, { method: 'POST' });
      onSuccess('Token regenerated');
      onRefresh();
    } catch (err: any) {
      onError(err?.message || 'Failed to regenerate');
    } finally {
      setRegenerating(false);
    }
  };

  const maskedToken = token?.token
    ? token.token.substring(0, 8) + '••••••••••••••••' + token.token.slice(-4)
    : '';

  return (
    <div>
      <div className="flex items-center justify-between mb-5">
        <h2 className="text-xl font-extrabold text-slate-900 flex items-center gap-2">
          <Key className="w-5 h-5 text-primary" />
          Install Token
        </h2>
      </div>

      <div className="mb-5 p-4 bg-primary/5 border border-primary/20 rounded-xl">
        <p className="text-sm text-primary/80">
          Use this token when installing the TimeTracker agent. It links devices to your organization automatically.
        </p>
      </div>

      {token ? (
        <div className="space-y-5">
          <div className="p-5 bg-slate-50 border border-border/60 rounded-xl">
            <label className="block text-xs font-semibold text-slate-600 uppercase tracking-wider mb-2">
              Organization Install Token
            </label>
            <div className="flex items-center gap-2">
              <div className="flex-1 bg-white border border-border/60 rounded-lg px-3 py-2.5 font-mono text-sm text-slate-700 overflow-hidden">
                {showToken ? token.token : maskedToken}
              </div>
              <button onClick={() => setShowToken(!showToken)} className="p-2.5 border border-border/60 rounded-lg hover:bg-slate-100 transition-colors">
                {showToken ? <EyeOff className="w-4 h-4 text-slate-500" /> : <Eye className="w-4 h-4 text-slate-500" />}
              </button>
              <button onClick={handleCopy} className="p-2.5 border border-border/60 rounded-lg hover:bg-slate-100 transition-colors">
                <Copy className="w-4 h-4 text-slate-500" />
              </button>
            </div>
            <p className="text-xs text-slate-400 mt-2">Created: {new Date(token.created_at).toLocaleString()}</p>
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={handleRegenerate} disabled={regenerating}
              className="flex items-center gap-1.5 px-4 py-2 border border-red-200 text-red-600 rounded-lg font-semibold text-sm hover:bg-red-50 transition-colors disabled:opacity-50"
            >
              {regenerating ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
              Regenerate Token
            </button>
            <p className="text-xs text-slate-400">⚠️ This will invalidate the current token</p>
          </div>

          <div className="p-4 bg-amber-50 border border-amber-200 rounded-xl">
            <h4 className="font-semibold text-amber-800 text-sm mb-2">Installation Instructions</h4>
            <ol className="text-sm text-amber-700 space-y-1">
              <li>1. Download the TimeTracker agent for your OS</li>
              <li>2. Run the installer</li>
              <li>3. Enter this install token when prompted</li>
              <li>4. The agent links automatically to your organization</li>
            </ol>
          </div>
        </div>
      ) : (
        <div className="text-center py-14">
          <Key className="w-10 h-10 text-slate-200 mx-auto mb-3" />
          <p className="font-semibold text-slate-500">No install token found</p>
          <button onClick={onRefresh} className="mt-3 px-4 py-2 bg-primary text-white rounded-lg font-semibold text-sm hover:opacity-90">
            Generate Token
          </button>
        </div>
      )}
    </div>
  );
}