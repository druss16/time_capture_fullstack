// src/pages/settings/ClientsTab.tsx
import { useState, useMemo, useRef } from 'react';
import {
  Briefcase, Plus, Pencil, Trash2, Upload, Search, X, Tag,
  ChevronDown, Check, RefreshCw, CheckSquare, Square,
  MinusSquare, UserPlus, UserMinus, FileSpreadsheet,
  Copy, AlertCircle, CheckCircle2, Loader2, Download, Receipt,
} from 'lucide-react';
import { cn } from '@/lib/design-system';
import { safeFetchJson } from '@/lib/api';
import { getUserDisplayName } from './types';
import type { Client, TeamMember, RoleType } from './types';
import ClientImportWizard from '@/components/ClientImportWizard';
import ClientTaskTypesPanel from '@/components/ClientTaskTypesPanel';
import ClientBillingProfilePanel from '@/components/ClientBillingProfilePanel';
import BulkBillingModal from '@/components/BulkBillingModal';
import { SettingsPage, SettingsSection, inputClass, labelClass, primaryBtnClass, secondaryBtnClass } from './ui';


const RAW_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:7123/api';
const API_BASE = RAW_BASE.endsWith('/api') ? RAW_BASE : `${RAW_BASE.replace(/\/+$/, '')}/api`;

// ── Bulk Assign Modal ─────────────────────────────────────────────────────────

function BulkAssignModal({ isOpen, onClose, selectedClients, users, onSuccess }: {
  isOpen: boolean; onClose: () => void;
  selectedClients: Client[]; users: TeamMember[];
  onSuccess: () => void;
}) {
  const [selectedUserIds, setSelectedUserIds] = useState<Set<number>>(new Set());
  const [role,    setRole]    = useState('Staff');
  const [mode,    setMode]    = useState<'add' | 'replace'>('add');
  const [loading, setLoading] = useState(false);
  const [error,   setError]   = useState<string | null>(null);
  const [result,  setResult]  = useState<any>(null);

  const handleToggleUser = (userId: number) => {
    const next = new Set(selectedUserIds);
    next.has(userId) ? next.delete(userId) : next.add(userId);
    setSelectedUserIds(next);
  };

  const handleSubmit = async () => {
    if (selectedUserIds.size === 0) { setError('Select at least one employee'); return; }
    setLoading(true); setError(null);
    try {
      const response = await safeFetchJson<any>(`${API_BASE}/clients/bulk-assign/`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ client_ids: selectedClients.map(c => c.id), user_ids: Array.from(selectedUserIds), role, mode }),
      });
      setResult(response);
      setTimeout(() => { onSuccess(); handleClose(); }, 2000);
    } catch (err: any) {
      setError(err.message || 'Failed to assign');
    } finally {
      setLoading(false);
    }
  };

  const handleClose = () => { setSelectedUserIds(new Set()); setRole('Staff'); setMode('add'); setError(null); setResult(null); onClose(); };
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-lg mx-4 overflow-hidden">
        <div className="flex items-center justify-between px-6 py-4 border-b border-border/50">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 bg-primary/10 rounded-xl flex items-center justify-center"><UserPlus className="w-4 h-4 text-primary" /></div>
            <div>
              <h2 className="text-base font-bold text-slate-900">Bulk Assign Team</h2>
              <p className="text-xs text-slate-400">{selectedClients.length} client{selectedClients.length !== 1 ? 's' : ''} selected</p>
            </div>
          </div>
          <button onClick={handleClose} className="p-1.5 hover:bg-slate-100 rounded-lg transition-colors"><X className="w-4 h-4 text-slate-400" /></button>
        </div>

        <div className="p-6 max-h-[60vh] overflow-y-auto">
          {result ? (
            <div className="text-center py-8">
              <div className="w-14 h-14 bg-emerald-50 rounded-full flex items-center justify-center mx-auto mb-4"><CheckCircle2 className="w-7 h-7 text-emerald-500" /></div>
              <h3 className="text-base font-bold text-slate-900 mb-1">Assignment Complete!</h3>
              <p className="text-sm text-slate-500">{result.created} assignments created{result.updated > 0 && `, ${result.updated} updated`}</p>
            </div>
          ) : (
            <>
              {error && (
                <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg flex items-center gap-2">
                  <AlertCircle className="w-4 h-4 text-red-500 shrink-0" />
                  <p className="text-sm text-red-700">{error}</p>
                </div>
              )}
              <div className="mb-5">
                <label className="block text-xs font-semibold text-slate-600 uppercase tracking-wider mb-2">Assignment Mode</label>
                <div className="grid grid-cols-2 gap-2">
                  {[
                    { key: 'add',     label: 'Add to Team',    desc: 'Keep existing, add new' },
                    { key: 'replace', label: 'Replace Team',   desc: 'Remove existing, assign only selected' },
                  ].map(opt => (
                    <button key={opt.key} onClick={() => setMode(opt.key as any)}
                      className={cn('p-3 border rounded-xl text-left transition-all', mode === opt.key ? 'border-primary bg-primary/5' : 'border-border/60 hover:border-slate-300')}
                    >
                      <p className={cn('font-semibold text-sm', mode === opt.key ? 'text-primary' : 'text-slate-700')}>{opt.label}</p>
                      <p className="text-xs text-slate-400 mt-0.5">{opt.desc}</p>
                    </button>
                  ))}
                </div>
              </div>
              <div className="mb-5">
                <label className="block text-xs font-semibold text-slate-600 uppercase tracking-wider mb-2">Default Role</label>
                <select value={role} onChange={e => setRole(e.target.value)} className="w-full border border-border/60 rounded-lg px-3 py-2 text-sm bg-white focus:border-primary focus:outline-none">
                  {['Staff', 'Manager', 'Partner', 'Lead'].map(r => <option key={r} value={r}>{r}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-xs font-semibold text-slate-600 uppercase tracking-wider mb-2">Select Team Members</label>
                <div className="border border-border/60 rounded-xl max-h-56 overflow-y-auto">
                  {users.map(user => {
                    const name = getUserDisplayName(user);
                    return (
                      <button key={user.id} onClick={() => handleToggleUser(user.id)}
                        className={cn('w-full flex items-center gap-3 px-4 py-2.5 hover:bg-slate-50 transition-colors border-b border-border/30 last:border-b-0', selectedUserIds.has(user.id) && 'bg-primary/3')}
                      >
                        {selectedUserIds.has(user.id) ? <CheckSquare className="w-4 h-4 text-primary shrink-0" /> : <Square className="w-4 h-4 text-slate-300 shrink-0" />}
                        <div className="w-7 h-7 rounded-full bg-primary/10 flex items-center justify-center shrink-0">
                          <span className="text-xs font-bold text-primary">{name[0].toUpperCase()}</span>
                        </div>
                        <div className="flex-1 text-left">
                          <p className="font-semibold text-slate-800 text-sm">{name}</p>
                          <p className="text-xs text-slate-400">{user.email || `@${user.username}`}</p>
                        </div>
                      </button>
                    );
                  })}
                  {users.length === 0 && <div className="text-center py-6 text-slate-400 text-sm">No team members</div>}
                </div>
                {selectedUserIds.size > 0 && <p className="mt-2 text-xs text-primary font-semibold">{selectedUserIds.size} member{selectedUserIds.size !== 1 ? 's' : ''} selected</p>}
              </div>
            </>
          )}
        </div>

        {!result && (
          <div className="flex items-center justify-end gap-2 px-6 py-4 border-t border-border/50 bg-slate-50/60">
            <button onClick={handleClose} className="px-4 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-200 rounded-lg transition-colors">Cancel</button>
            <button onClick={handleSubmit} disabled={loading || selectedUserIds.size === 0}
              className="flex items-center gap-1.5 px-4 py-2 bg-primary text-white text-sm font-semibold rounded-lg hover:opacity-90 disabled:opacity-50 transition-all"
            >
              {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <UserPlus className="w-3.5 h-3.5" />}
              Assign to {selectedClients.length} Client{selectedClients.length !== 1 ? 's' : ''}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

// ── CSV Import Modal ──────────────────────────────────────────────────────────

function CSVImportModal({ isOpen, onClose, onSuccess }: { isOpen: boolean; onClose: () => void; onSuccess: () => void; }) {
  const [file,    setFile]    = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [error,   setError]   = useState<string | null>(null);
  const [result,  setResult]  = useState<any>(null);
  const [preview, setPreview] = useState<any[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (!f) return;
    setFile(f); setError(null);
    const reader = new FileReader();
    reader.onload = ev => {
      const lines = (ev.target?.result as string).split('\n').slice(0, 6);
      setPreview(lines.map(l => l.split(',').map(c => c.trim().replace(/"/g, ''))));
    };
    reader.readAsText(f);
  };

  const handleDownloadTemplate = async () => {
    try {
      const response = await fetch(`${API_BASE}/clients/assignment-template/`, { credentials: 'include' });
      const blob = await response.blob();
      const url  = window.URL.createObjectURL(blob);
      const a    = document.createElement('a');
      a.href = url; a.download = 'client_assignments_template.csv';
      document.body.appendChild(a); a.click();
      window.URL.revokeObjectURL(url); document.body.removeChild(a);
    } catch { setError('Failed to download template'); }
  };

  const handleSubmit = async () => {
    if (!file) return;
    setLoading(true); setError(null);
    try {
      const formData = new FormData();
      formData.append('file', file);
      const response = await fetch(`${API_BASE}/clients/import-assignments/`, { method: 'POST', credentials: 'include', body: formData });
      if (!response.ok) { const d = await response.json(); throw new Error(d.error || 'Import failed'); }
      const data = await response.json();
      setResult(data);
      setTimeout(() => { onSuccess(); handleClose(); }, 2000);
    } catch (err: any) { setError(err.message || 'Failed to import'); }
    finally { setLoading(false); }
  };

  const handleClose = () => { setFile(null); setError(null); setResult(null); setPreview([]); onClose(); };
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-xl mx-4 overflow-hidden">
        <div className="flex items-center justify-between px-6 py-4 border-b border-border/50">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 bg-blue-50 rounded-xl flex items-center justify-center"><FileSpreadsheet className="w-4 h-4 text-blue-500" /></div>
            <div>
              <h2 className="text-base font-bold text-slate-900">Import Assignments from CSV</h2>
              <p className="text-xs text-slate-400">Bulk assign team members via spreadsheet</p>
            </div>
          </div>
          <button onClick={handleClose} className="p-1.5 hover:bg-slate-100 rounded-lg"><X className="w-4 h-4 text-slate-400" /></button>
        </div>
        <div className="p-6">
          {result ? (
            <div className="text-center py-8">
              <div className="w-14 h-14 bg-emerald-50 rounded-full flex items-center justify-center mx-auto mb-4"><CheckCircle2 className="w-7 h-7 text-emerald-500" /></div>
              <h3 className="text-base font-bold text-slate-900 mb-1">Import Complete!</h3>
              <p className="text-sm text-slate-500">{result.created} assignments created, {result.updated} updated</p>
            </div>
          ) : (
            <>
              {error && <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">{error}</div>}
              <div className="mb-4 p-4 bg-blue-50 border border-blue-200 rounded-xl flex items-center justify-between">
                <div>
                  <p className="font-semibold text-blue-800 text-sm">Download Template</p>
                  <p className="text-xs text-blue-600">Pre-filled CSV with your clients and team</p>
                </div>
                <button onClick={handleDownloadTemplate} className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 text-white rounded-lg font-semibold text-xs hover:bg-blue-700">
                  <Download className="w-3.5 h-3.5" /> Template
                </button>
              </div>
              <div
                onClick={() => fileInputRef.current?.click()}
                className={cn('border-2 border-dashed rounded-xl p-6 text-center cursor-pointer transition-all', file ? 'border-emerald-300 bg-emerald-50' : 'border-slate-200 hover:border-primary/40 hover:bg-primary/3')}
              >
                <input ref={fileInputRef} type="file" accept=".csv" onChange={handleFileChange} className="hidden" />
                {file ? (
                  <><CheckCircle2 className="w-8 h-8 text-emerald-500 mx-auto mb-2" /><p className="font-semibold text-emerald-700 text-sm">{file.name}</p></>
                ) : (
                  <><Upload className="w-8 h-8 text-slate-300 mx-auto mb-2" /><p className="font-semibold text-slate-600 text-sm">Click to select a CSV file</p></>
                )}
              </div>
              {preview.length > 0 && (
                <div className="mt-4 border border-border/60 rounded-xl overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead className="bg-slate-50"><tr>{preview[0]?.map((h: string, i: number) => <th key={i} className="px-3 py-2 text-left font-semibold text-slate-600 whitespace-nowrap">{h}</th>)}</tr></thead>
                    <tbody>{preview.slice(1).map((row, i) => <tr key={i} className="border-t border-border/30">{row.map((c: string, j: number) => <td key={j} className="px-3 py-2 text-slate-500 whitespace-nowrap">{c}</td>)}</tr>)}</tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </div>
        {!result && (
          <div className="flex justify-end gap-2 px-6 py-4 border-t border-border/50 bg-slate-50/60">
            <button onClick={handleClose} className="px-4 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-200 rounded-lg">Cancel</button>
            <button onClick={handleSubmit} disabled={loading || !file}
              className="flex items-center gap-1.5 px-4 py-2 bg-primary text-white text-sm font-semibold rounded-lg hover:opacity-90 disabled:opacity-50"
            >
              {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Upload className="w-3.5 h-3.5" />}
              Import Assignments
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Copy Assignments Modal ────────────────────────────────────────────────────

function CopyAssignmentsModal({ isOpen, onClose, clients, onSuccess }: { isOpen: boolean; onClose: () => void; clients: Client[]; onSuccess: () => void; }) {
  const [sourceClientId,  setSourceClientId]  = useState<number | null>(null);
  const [targetClientIds, setTargetClientIds] = useState<Set<number>>(new Set());
  const [loading, setLoading] = useState(false);
  const [error,   setError]   = useState<string | null>(null);
  const [result,  setResult]  = useState<any>(null);
  const [searchSource, setSearchSource] = useState('');
  const [searchTarget, setSearchTarget] = useState('');

  const filteredSource = clients.filter(c => c.name.toLowerCase().includes(searchSource.toLowerCase()) || c.code?.toLowerCase().includes(searchSource.toLowerCase()));
  const filteredTarget = clients.filter(c => c.id !== sourceClientId && (c.name.toLowerCase().includes(searchTarget.toLowerCase()) || c.code?.toLowerCase().includes(searchTarget.toLowerCase())));

  const handleToggleTarget = (id: number) => {
    const next = new Set(targetClientIds);
    next.has(id) ? next.delete(id) : next.add(id);
    setTargetClientIds(next);
  };

  const handleSubmit = async () => {
    if (!sourceClientId || targetClientIds.size === 0) return;
    setLoading(true); setError(null);
    try {
      const response = await safeFetchJson<any>(`${API_BASE}/clients/copy-assignments/`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source_client_id: sourceClientId, target_client_ids: Array.from(targetClientIds) }),
      });
      setResult(response);
      setTimeout(() => { onSuccess(); handleClose(); }, 2000);
    } catch (err: any) { setError(err.message || 'Failed to copy'); }
    finally { setLoading(false); }
  };

  const handleClose = () => { setSourceClientId(null); setTargetClientIds(new Set()); setError(null); setResult(null); setSearchSource(''); setSearchTarget(''); onClose(); };
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-lg mx-4 overflow-hidden">
        <div className="flex items-center justify-between px-6 py-4 border-b border-border/50">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 bg-purple-50 rounded-xl flex items-center justify-center"><Copy className="w-4 h-4 text-purple-500" /></div>
            <div>
              <h2 className="text-base font-bold text-slate-900">Copy Team Assignments</h2>
              <p className="text-xs text-slate-400">Clone team from one client to others</p>
            </div>
          </div>
          <button onClick={handleClose} className="p-1.5 hover:bg-slate-100 rounded-lg"><X className="w-4 h-4 text-slate-400" /></button>
        </div>
        <div className="p-6 max-h-[60vh] overflow-y-auto">
          {result ? (
            <div className="text-center py-8">
              <div className="w-14 h-14 bg-emerald-50 rounded-full flex items-center justify-center mx-auto mb-4"><CheckCircle2 className="w-7 h-7 text-emerald-500" /></div>
              <h3 className="text-base font-bold text-slate-900 mb-1">Copy Complete!</h3>
              <p className="text-sm text-slate-500">{result.created} assignments created across {result.clients_updated} clients</p>
            </div>
          ) : (
            <>
              {error && <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">{error}</div>}
              <div className="mb-5">
                <label className="block text-xs font-semibold text-slate-600 uppercase tracking-wider mb-2">Copy From</label>
                <input type="text" placeholder="Search clients..." value={searchSource} onChange={e => setSearchSource(e.target.value)} className="w-full border border-border/60 rounded-lg px-3 py-2 text-sm mb-2 focus:border-primary focus:outline-none" />
                <div className="border border-border/60 rounded-xl max-h-36 overflow-y-auto">
                  {filteredSource.map(c => (
                    <button key={c.id} onClick={() => { setSourceClientId(c.id); setTargetClientIds(new Set()); }}
                      className={cn('w-full flex items-center gap-2 px-3 py-2.5 hover:bg-slate-50 text-left border-b border-border/20 last:border-b-0', sourceClientId === c.id && 'bg-purple-50')}
                    >
                      {sourceClientId === c.id ? <CheckSquare className="w-4 h-4 text-purple-500 shrink-0" /> : <Square className="w-4 h-4 text-slate-300 shrink-0" />}
                      <p className="font-semibold text-slate-800 text-sm">{c.name}</p>
                      {c.code && <span className="text-xs text-slate-400 font-mono">{c.code}</span>}
                    </button>
                  ))}
                </div>
              </div>
              {sourceClientId && (
                <div>
                  <label className="block text-xs font-semibold text-slate-600 uppercase tracking-wider mb-2">Copy To</label>
                  <input type="text" placeholder="Search clients..." value={searchTarget} onChange={e => setSearchTarget(e.target.value)} className="w-full border border-border/60 rounded-lg px-3 py-2 text-sm mb-2 focus:border-primary focus:outline-none" />
                  <div className="border border-border/60 rounded-xl max-h-40 overflow-y-auto">
                    {filteredTarget.map(c => (
                      <button key={c.id} onClick={() => handleToggleTarget(c.id)}
                        className={cn('w-full flex items-center gap-2 px-3 py-2.5 hover:bg-slate-50 text-left border-b border-border/20 last:border-b-0', targetClientIds.has(c.id) && 'bg-primary/3')}
                      >
                        {targetClientIds.has(c.id) ? <CheckSquare className="w-4 h-4 text-primary shrink-0" /> : <Square className="w-4 h-4 text-slate-300 shrink-0" />}
                        <p className="font-semibold text-slate-800 text-sm">{c.name}</p>
                        {c.code && <span className="text-xs text-slate-400 font-mono">{c.code}</span>}
                      </button>
                    ))}
                  </div>
                  {targetClientIds.size > 0 && <p className="mt-2 text-xs text-primary font-semibold">{targetClientIds.size} client{targetClientIds.size !== 1 ? 's' : ''} selected</p>}
                </div>
              )}
            </>
          )}
        </div>
        {!result && (
          <div className="flex justify-end gap-2 px-6 py-4 border-t border-border/50 bg-slate-50/60">
            <button onClick={handleClose} className="px-4 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-200 rounded-lg">Cancel</button>
            <button onClick={handleSubmit} disabled={loading || !sourceClientId || targetClientIds.size === 0}
              className="flex items-center gap-1.5 px-4 py-2 bg-primary text-white text-sm font-semibold rounded-lg hover:opacity-90 disabled:opacity-50"
            >
              {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Copy className="w-3.5 h-3.5" />}
              Copy to {targetClientIds.size || 0} Client{targetClientIds.size !== 1 ? 's' : ''}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Main ClientsTab ───────────────────────────────────────────────────────────

interface Props {
  clients: Client[];
  currentUserRole: RoleType;
  users: TeamMember[];
  onRefresh: () => void;
  onSuccess: (msg: string) => void;
  onError: (msg: string) => void;
}

export default function ClientsTab({ clients, currentUserRole, users, onRefresh, onSuccess, onError }: Props) {
  const [showAdd,            setShowAdd]            = useState(false);
  const [showImportWizard,   setShowImportWizard]   = useState(false);
  const [editingId,          setEditingId]          = useState<number | null>(null);
  const [form,               setForm]               = useState({ name: '', code: '', visibility: 'all', aliases: [] as string[] });
  const [saving,             setSaving]             = useState(false);
  const [aliasInput,         setAliasInput]         = useState('');
  const [selectedClientIds,  setSelectedClientIds]  = useState<Set<number>>(new Set());
  const [showBulkAssignModal,setShowBulkAssignModal]= useState(false);
  const [showBulkBillingModal,setShowBulkBillingModal]= useState(false);
  const [showCSVImportModal, setShowCSVImportModal] = useState(false);
  const [showCopyModal,      setShowCopyModal]      = useState(false);
  const [showImportDropdown, setShowImportDropdown] = useState(false);
  const [search,             setSearch]             = useState('');
  const [statusFilter,       setStatusFilter]       = useState<'all' | 'active' | 'inactive'>('active');
  const [taskTypeClientId, setTaskTypeClientId] = useState<number | null>(null);
  const [billingClientId, setBillingClientId] = useState<number | null>(null);

  const canManage = ['owner', 'admin'].includes(currentUserRole);

  const filteredClients = useMemo(() => {
    let list = clients;
    if (search.trim()) {
      const q = search.toLowerCase();
      list = list.filter(c => c.name.toLowerCase().includes(q) || c.code?.toLowerCase().includes(q) || c.aliases?.some(a => a.toLowerCase().includes(q)));
    }
    if (statusFilter === 'active')   list = list.filter(c => c.is_active);
    if (statusFilter === 'inactive') list = list.filter(c => !c.is_active);
    return list;
  }, [clients, search, statusFilter]);

  const toggleSelect    = (id: number) => { const next = new Set(selectedClientIds); next.has(id) ? next.delete(id) : next.add(id); setSelectedClientIds(next); };
  const toggleSelectAll = () => setSelectedClientIds(selectedClientIds.size === filteredClients.length ? new Set() : new Set(filteredClients.map(c => c.id)));
  const clearSelection  = () => setSelectedClientIds(new Set());
  const selectedClients = clients.filter(c => selectedClientIds.has(c.id));

  const resetForm = () => { setForm({ name: '', code: '', visibility: 'all', aliases: [] }); setAliasInput(''); setShowAdd(false); setEditingId(null); };

  const handleSave = async () => {
    if (!form.name.trim()) return;
    // Flush any alias typed but not yet committed with Enter/Add, so it isn't silently dropped on save.
    const pending = aliasInput.trim();
    const aliases = pending && !form.aliases.includes(pending) ? [...form.aliases, pending] : form.aliases;
    const payload = { ...form, aliases };
    setSaving(true);
    try {
      if (editingId) {
        await safeFetchJson(`${API_BASE}/settings/clients/${editingId}/`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
        onSuccess('Client updated');
      } else {
        await safeFetchJson(`${API_BASE}/settings/clients/`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
        onSuccess('Client added');
      }
      resetForm(); onRefresh();
    } catch (err: any) { onError(err?.message || 'Failed to save'); }
    finally { setSaving(false); }
  };

  const handleEdit = (client: Client) => {
    if (!canManage) return;
    setForm({ name: client.name, code: client.code || '', visibility: client.visibility || 'all', aliases: client.aliases || [] });
    setEditingId(client.id); setShowAdd(true);
  };

  const handleDelete = async (clientId: number, clientName: string) => {
    if (!canManage || !confirm(`Delete client "${clientName}"?`)) return;
    try {
      await safeFetchJson(`${API_BASE}/settings/clients/${clientId}/`, { method: 'DELETE' });
      onSuccess('Client deleted'); onRefresh();
    } catch (err: any) { onError(err?.message || 'Failed to delete'); }
  };

  const handleBulkUnassign = async () => {
    if (!confirm(`Remove all team assignments from ${selectedClientIds.size} clients?`)) return;
    try {
      await safeFetchJson(`${API_BASE}/clients/bulk-unassign/`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ client_ids: Array.from(selectedClientIds) }) });
      onSuccess(`Removed team from ${selectedClientIds.size} clients`); onRefresh(); clearSelection();
    } catch (err: any) { onError(err?.message || 'Failed'); }
  };

  const addAlias = () => {
    const val = aliasInput.trim();
    if (val && !form.aliases.includes(val)) setForm({ ...form, aliases: [...form.aliases, val] });
    setAliasInput('');
  };

  const visibilityConfig = {
    all:          { label: 'All',          cls: 'bg-emerald-50 text-emerald-700 border-emerald-200' },
    assigned:     { label: 'Assigned',     cls: 'bg-amber-50 text-amber-700 border-amber-200' },
    confidential: { label: 'Confidential', cls: 'bg-red-50 text-red-600 border-red-200' },
  };

  return (
    <SettingsPage
      title="Clients"
      subtitle="Manage your client list, aliases, visibility, and team assignments."
      actions={canManage && (
        <>
          <div className="relative">
            <button onClick={() => setShowImportDropdown(!showImportDropdown)} className={secondaryBtnClass}>
              <Upload className="w-3.5 h-3.5" /> Import <ChevronDown className="w-3 h-3" />
            </button>
            {showImportDropdown && (
              <>
                <div className="fixed inset-0 z-10" onClick={() => setShowImportDropdown(false)} />
                <div className="absolute right-0 top-full mt-1 bg-white border border-border/60 rounded-xl shadow-lg z-20 min-w-[200px] overflow-hidden py-1">
                  {[
                    { icon: <Upload className="w-3.5 h-3.5 text-emerald-500" />, label: 'Import Clients', sub: 'From QuickBooks or Xero', action: () => { setShowImportWizard(true); setShowImportDropdown(false); } },
                    { icon: <FileSpreadsheet className="w-3.5 h-3.5 text-blue-500" />, label: 'Import Assignments', sub: 'CSV file upload', action: () => { setShowCSVImportModal(true); setShowImportDropdown(false); } },
                    { icon: <Copy className="w-3.5 h-3.5 text-purple-500" />, label: 'Copy Team', sub: 'From another client', action: () => { setShowCopyModal(true); setShowImportDropdown(false); } },
                  ].map(item => (
                    <button key={item.label} onClick={item.action} className="w-full flex items-center gap-3 px-4 py-2.5 hover:bg-slate-50 text-left transition-colors border-b border-border/20 last:border-b-0">
                      {item.icon}
                      <div><p className="font-semibold text-slate-800 text-sm">{item.label}</p><p className="text-xs text-slate-400">{item.sub}</p></div>
                    </button>
                  ))}
                </div>
              </>
            )}
          </div>
          <button onClick={() => { resetForm(); setShowAdd(true); }} className={primaryBtnClass}>
            <Plus className="w-3.5 h-3.5" /> Add Client
          </button>
        </>
      )}
    >
      {/* Search + filter */}
      <div className="flex items-center gap-3 mb-4">
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400 pointer-events-none" />
          <input type="text" value={search} onChange={e => setSearch(e.target.value)} placeholder="Search by name, code, or alias..."
            className="w-full pl-8 pr-8 py-2 text-sm bg-slate-50 border border-border/50 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary/40 transition-all"
          />
          {search && <button onClick={() => setSearch('')} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"><X className="w-3.5 h-3.5" /></button>}
        </div>
        <div className="flex items-center gap-1 bg-slate-100 rounded-lg p-0.5">
          {(['all', 'active', 'inactive'] as const).map(f => (
            <button key={f} onClick={() => setStatusFilter(f)}
              className={cn('px-3 py-1.5 text-xs font-semibold rounded-md transition-all', statusFilter === f ? 'bg-white text-slate-800 shadow-sm' : 'text-slate-500 hover:text-slate-700')}
            >
              {f.charAt(0).toUpperCase() + f.slice(1)}
            </button>
          ))}
        </div>
        <span className="text-xs text-slate-400 ml-auto">
          {filteredClients.length === clients.length ? `${clients.length} clients` : <><span className="font-semibold text-slate-600">{filteredClients.length}</span> of {clients.length}</>}
          {(search || statusFilter !== 'all') && filteredClients.length < clients.length && (
            <button onClick={() => { setSearch(''); setStatusFilter('all'); }} className="ml-2 text-primary hover:underline font-medium">Clear</button>
          )}
        </span>
      </div>

      {/* Add/edit form */}
      {showAdd && canManage && (
        <SettingsSection title={editingId ? 'Edit client' : 'New client'} className="mb-5">
          <div className="grid grid-cols-3 gap-4 mb-4">
            <div>
              <label className={labelClass}>Name *</label>
              <input type="text" value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} placeholder="Acme Corporation"
                className={inputClass}
              />
            </div>
            <div>
              <label className={labelClass}>Code</label>
              <input type="text" value={form.code} onChange={e => setForm({ ...form, code: e.target.value.toUpperCase() })} placeholder="ACME" maxLength={10}
                className={`${inputClass} font-mono uppercase`}
              />
            </div>
            <div>
              <label className={labelClass}>Visibility</label>
              <select value={form.visibility} onChange={e => setForm({ ...form, visibility: e.target.value })}
                className={inputClass}
              >
                <option value="all">All Team Members</option>
                <option value="assigned">Assigned Only</option>
                <option value="confidential">Confidential</option>
              </select>
            </div>
          </div>
          <div className="mb-4">
            <label className={labelClass}>
              AI Aliases <span className="text-[10px] font-normal text-slate-400 normal-case">Alternative names the AI uses for matching</span>
            </label>
            <div className="flex flex-wrap gap-1.5 mb-2">
              {form.aliases.map((alias, i) => (
                <span key={i} className="inline-flex items-center gap-1 bg-primary/10 text-primary px-2.5 py-1 rounded-full text-xs font-semibold">
                  {alias}
                  <button onClick={() => setForm({ ...form, aliases: form.aliases.filter((_, j) => j !== i) })} className="hover:text-red-500 transition-colors"><X className="w-3 h-3" /></button>
                </span>
              ))}
            </div>
            <div className="flex gap-2">
              <input type="text" value={aliasInput} onChange={e => setAliasInput(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addAlias(); } }}
                placeholder="Type alias and press Enter..."
                className={`${inputClass} flex-1`}
              />
              <button onClick={addAlias} disabled={!aliasInput.trim()} className="px-3 py-2 text-sm font-semibold bg-slate-100 text-slate-700 rounded-lg hover:bg-slate-200 disabled:opacity-40 transition-all">Add</button>
            </div>
          </div>
          <div className="flex gap-2 pt-4 border-t border-slate-200/70">
            <button onClick={handleSave} disabled={saving || !form.name.trim()} className={primaryBtnClass}>
              {saving ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
              {editingId ? 'Update Client' : 'Add Client'}
            </button>
            <button onClick={resetForm} className={secondaryBtnClass}>Cancel</button>
          </div>
        </SettingsSection>
      )}

      {/* Table with internal scroll */}
      <div className="rounded-2xl border border-slate-200/70 overflow-hidden flex flex-col" style={{ maxHeight: 'calc(100vh - 280px)' }}>
        <div className="overflow-auto flex-1">
          <table className="w-full text-sm border-collapse">
            <thead className="sticky top-0 z-10">
              <tr className="border-b border-border/60 bg-slate-50/80">
                {canManage && (
                  <th className="w-10 px-4 py-3">
                    <button onClick={toggleSelectAll} className="p-0.5 hover:bg-slate-200 rounded transition-colors">
                      {selectedClientIds.size === filteredClients.length && filteredClients.length > 0
                        ? <CheckSquare className="w-4 h-4 text-primary" />
                        : selectedClientIds.size > 0 ? <MinusSquare className="w-4 h-4 text-primary" />
                        : <Square className="w-4 h-4 text-slate-400" />
                      }
                    </button>
                  </th>
                )}
                {['Client', 'Code', 'Aliases', 'Visibility', 'Status', ...(canManage ? ['Actions'] : [])].map(h => (
                  <th key={h} className={cn('px-4 py-3 text-xs font-semibold uppercase tracking-wider text-slate-500', h === 'Actions' ? 'text-right' : 'text-left')}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-border/30">
              {filteredClients.length === 0 ? (
                <tr>
                  <td colSpan={canManage ? 7 : 5} className="text-center py-14">
                    <Briefcase className="w-10 h-10 text-slate-200 mx-auto mb-3" />
                    {search || statusFilter !== 'all' ? (
                      <>
                        <p className="font-semibold text-slate-500">No clients match your filter</p>
                        <button onClick={() => { setSearch(''); setStatusFilter('all'); }} className="mt-2 text-sm text-primary hover:underline">Clear filters</button>
                      </>
                    ) : (
                      <>
                        <p className="font-semibold text-slate-500">No clients yet</p>
                        {canManage && <button onClick={() => setShowImportWizard(true)} className="mt-3 px-4 py-2 bg-primary text-white rounded-lg font-semibold text-sm hover:opacity-90"><Upload className="w-3.5 h-3.5 inline mr-1.5" />Import Clients</button>}
                      </>
                    )}
                  </td>
                </tr>
              ) : filteredClients.map(client => {
                const vis = visibilityConfig[client.visibility as keyof typeof visibilityConfig] || visibilityConfig.all;
                return (
                  <tr key={client.id} className={cn('hover:bg-slate-50/60 transition-colors', selectedClientIds.has(client.id) && 'bg-primary/3')}>
                    {canManage && (
                      <td className="px-4 py-3">
                        <button onClick={() => toggleSelect(client.id)} className="p-0.5 hover:bg-slate-200 rounded transition-colors">
                          {selectedClientIds.has(client.id) ? <CheckSquare className="w-4 h-4 text-primary" /> : <Square className="w-4 h-4 text-slate-300" />}
                        </button>
                      </td>
                    )}
                    <td className="px-4 py-3 font-semibold text-slate-800">{client.name}</td>
                    <td className="px-4 py-3 font-mono text-xs text-slate-500">{client.code || '—'}</td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap gap-1">
                        {client.aliases?.length
                          ? client.aliases.map((a, i) => <span key={i} className="text-[10px] px-2 py-0.5 bg-primary/8 text-primary rounded-full font-semibold">{a}</span>)
                          : <span className="text-slate-300 text-xs">—</span>
                        }
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <span className={cn('text-xs px-2 py-0.5 rounded-full font-semibold border', vis.cls)}>{vis.label}</span>
                    </td>
                    <td className="px-4 py-3">
                      <span className={cn('text-xs px-2 py-0.5 rounded-full font-semibold border', client.is_active ? 'bg-emerald-50 text-emerald-700 border-emerald-200' : 'bg-slate-100 text-slate-400 border-slate-200')}>
                        {client.is_active ? 'Active' : 'Inactive'}
                      </span>
                    </td>
                    {canManage && (
                      <td className="px-4 py-3 text-right">
                        <div className="flex items-center justify-end gap-1">
                          <button onClick={() => setBillingClientId(client.id)} title="Billing profile" className="p-1.5 text-slate-400 hover:text-primary hover:bg-primary/8 rounded-lg transition-colors"><Receipt className="w-3.5 h-3.5" /></button>
                          <button onClick={() => setTaskTypeClientId(client.id)} title="Task Types" className="p-1.5 text-slate-400 hover:text-primary hover:bg-primary/8 rounded-lg transition-colors"><Tag className="w-3.5 h-3.5" /></button>
                          <button onClick={() => handleEdit(client)} className="p-1.5 text-slate-400 hover:text-primary hover:bg-primary/8 rounded-lg transition-colors"><Pencil className="w-3.5 h-3.5" /></button>
                          <button onClick={() => handleDelete(client.id, client.name)} className="p-1.5 text-slate-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors"><Trash2 className="w-3.5 h-3.5" /></button>
                        </div>
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Bulk action floating bar */}
      {selectedClientIds.size > 0 && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 bg-slate-900 text-white px-5 py-3 rounded-2xl shadow-2xl flex items-center gap-4 z-40 animate-in slide-in-from-bottom">
          <span className="font-semibold text-sm">{selectedClientIds.size} client{selectedClientIds.size !== 1 ? 's' : ''} selected</span>
          <div className="w-px h-5 bg-slate-700" />
          <button onClick={() => setShowBulkAssignModal(true)} className="flex items-center gap-1.5 px-3 py-1.5 bg-emerald-600 hover:bg-emerald-700 rounded-lg font-semibold text-sm transition-colors">
            <UserPlus className="w-3.5 h-3.5" /> Assign Team
          </button>
          <button onClick={() => setShowBulkBillingModal(true)} className="flex items-center gap-1.5 px-3 py-1.5 bg-primary hover:opacity-90 rounded-lg font-semibold text-sm transition-colors">
            <Receipt className="w-3.5 h-3.5" /> Set Billing
          </button>
          <button onClick={handleBulkUnassign} className="flex items-center gap-1.5 px-3 py-1.5 bg-red-600 hover:bg-red-700 rounded-lg font-semibold text-sm transition-colors">
            <UserMinus className="w-3.5 h-3.5" /> Remove Team
          </button>
          <button onClick={clearSelection} className="p-1.5 hover:bg-slate-700 rounded-lg transition-colors"><X className="w-4 h-4" /></button>
        </div>
      )}

      {/* Modals */}
      {showImportWizard   && <ClientImportWizard onClose={() => setShowImportWizard(false)} onSuccess={() => { onRefresh(); onSuccess('Clients imported!'); }} users={users} />}
      {showBulkAssignModal && <BulkAssignModal isOpen={showBulkAssignModal} onClose={() => setShowBulkAssignModal(false)} selectedClients={selectedClients} users={users} onSuccess={() => { onRefresh(); clearSelection(); onSuccess('Team assigned!'); }} />}
      {showBulkBillingModal && <BulkBillingModal isOpen={showBulkBillingModal} onClose={() => setShowBulkBillingModal(false)} clientIds={Array.from(selectedClientIds)} onSuccess={(m) => { setShowBulkBillingModal(false); clearSelection(); onSuccess(m); }} onError={onError} />}
        {taskTypeClientId !== null && (
        <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-2xl overflow-hidden flex flex-col" style={{ maxHeight: '90vh' }}>
            <div className="flex items-center justify-between px-6 py-4 border-b border-border/50 shrink-0">
              <div>
                <h2 className="text-base font-bold text-slate-900">
                  Task Types · {clients.find(c => c.id === taskTypeClientId)?.name}
                </h2>
                <p className="text-xs text-slate-400">Configure which task types apply to this client</p>
              </div>
              <button onClick={() => setTaskTypeClientId(null)} className="p-1.5 hover:bg-slate-100 rounded-lg transition-colors">
                <X className="w-4 h-4 text-slate-400" />
              </button>
            </div>
            <div className="overflow-y-auto p-5">
              <ClientTaskTypesPanel
                clientId={taskTypeClientId}
                canManage={canManage}
                onSuccess={onSuccess}
                onError={onError}
              />
            </div>
          </div>
        </div>
      )}
      {billingClientId !== null && (
        <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-2xl overflow-hidden flex flex-col" style={{ maxHeight: '90vh' }}>
            <div className="flex items-center justify-between px-6 py-4 border-b border-border/50 shrink-0">
              <div>
                <h2 className="text-base font-bold text-slate-900">
                  Billing profile · {clients.find(c => c.id === billingClientId)?.name}
                </h2>
                <p className="text-xs text-slate-400">How this client is billed and where its time exports to</p>
              </div>
              <button onClick={() => setBillingClientId(null)} className="p-1.5 hover:bg-slate-100 rounded-lg transition-colors">
                <X className="w-4 h-4 text-slate-400" />
              </button>
            </div>
            <div className="overflow-y-auto p-5">
              <ClientBillingProfilePanel
                clientId={billingClientId}
                canManage={canManage}
                onSuccess={(m) => { onSuccess(m); setBillingClientId(null); }}
                onError={onError}
              />
            </div>
          </div>
        </div>
      )}
      {showCSVImportModal  && <CSVImportModal isOpen={showCSVImportModal} onClose={() => setShowCSVImportModal(false)} onSuccess={() => { onRefresh(); onSuccess('Assignments imported!'); }} />}
      {showCopyModal       && <CopyAssignmentsModal isOpen={showCopyModal} onClose={() => setShowCopyModal(false)} clients={clients} onSuccess={() => { onRefresh(); onSuccess('Team copied!'); }} />}
    </SettingsPage>
  );
}