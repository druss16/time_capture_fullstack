// src/components/InvoiceManager.tsx
// All-in-one invoice tab — restyled to match WeeklyTimesheet design system

import React, { useState, useEffect, useCallback, useRef } from 'react';
import { safeFetchJson, API_BASE } from '@/lib/api';
import {
  Upload, Download, AlertTriangle, CheckCircle2, XCircle,
  RefreshCw, Search, X, FileText, Loader2, AlertCircle,
  Trash2, ChevronDown, Clock,
} from 'lucide-react';
import { cn } from '@/lib/design-system';

// ── Types ─────────────────────────────────────────────────────────────────────

interface Client     { id: number; name: string; code: string }
interface Invoice {
  id: number; invoice_number: string; invoice_date: string;
  amount: number; hours_billed: number | null;
  client_id: number | null; client_name: string; client_code: string;
  source: 'csv' | 'quickbooks' | 'xero' | 'manual';
  status: 'draft' | 'sent' | 'paid' | 'voided' | 'overdue';
  matched: boolean;
}
interface Conflict {
  id: number; invoice_number: string;
  tt_amount: number; source_amount: number;
  source: string; detected_at: string;
}
interface PreviewRow {
  row: number; invoice_number: string; invoice_date: string;
  amount: number; hours_billed: number | null; status: string;
  client_code: string; client_id: number | null; client_name: string | null;
  match_score: number; needs_review: boolean;
  suggestions: { client_id: number; client_name: string; client_code: string; score: number }[];
  is_duplicate: boolean; will_import: boolean;
}
interface PreviewSummary {
  total_rows: number; will_import: number; matched: number;
  unmatched: number; duplicates: number; parse_errors: number;
}
interface Props { filter?: string; onFilterClear?: () => void }

// ── Utilities ─────────────────────────────────────────────────────────────────

const SOURCE_LABELS: Record<string, string> = {
  csv: 'CSV', quickbooks: 'QuickBooks', xero: 'Xero', manual: 'Manual',
};

const STATUS_CLS: Record<string, string> = {
  paid:    'bg-emerald-50 text-emerald-700 border-emerald-200',
  sent:    'bg-primary/8 text-primary border-primary/20',
  draft:   'bg-slate-100 text-slate-500 border-slate-200',
  voided:  'bg-red-50 text-red-500 border-red-200',
  overdue: 'bg-amber-50 text-amber-700 border-amber-200',
};

const fmtCurrency = (n: number) =>
  new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(n);

const fmtDate = (s: string) =>
  new Date(s + 'T00:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });

const fmtHours = (h: number | null) => {
  if (h === null) return '—';
  const hrs = Math.floor(h);
  const min = Math.round((h - hrs) * 60);
  if (hrs === 0) return `${min}m`;
  if (min === 0) return `${hrs}h`;
  return `${hrs}h ${min}m`;
};

// ── Auth helpers ──────────────────────────────────────────────────────────────

function getAuthToken(): string {
  return (
    localStorage.getItem('auth_token') ||
    localStorage.getItem('tt_auth_token') ||
    localStorage.getItem('authToken') ||
    localStorage.getItem('token') ||
    ''
  );
}

async function authFetch(url: string, options: RequestInit = {}): Promise<Response> {
  const token = getAuthToken();
  return fetch(url, {
    ...options,
    credentials: 'include',
    headers: {
      ...(options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.headers || {}),
    },
  });
}

// ── Unmatched Queue ───────────────────────────────────────────────────────────

const UnmatchedQueue: React.FC<{
  invoices: Invoice[]; clients: Client[]; onMatched: () => void;
}> = ({ invoices, clients, onMatched }) => {
  const [matching,   setMatching]   = useState<Record<number, boolean>>({});
  const [selections, setSelections] = useState<Record<number, string>>({});

  const handleMatch = async (id: number) => {
    const clientId = selections[id];
    if (!clientId) return;
    setMatching(m => ({ ...m, [id]: true }));
    try {
      await authFetch(`${API_BASE}/billing/invoices/match/`, {
        method: 'POST',
        body: JSON.stringify({ invoice_id: id, client_id: Number(clientId) }),
      });
      onMatched();
    } finally {
      setMatching(m => ({ ...m, [id]: false }));
    }
  };

  return (
    <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 space-y-2 shrink-0">
      <div className="flex items-center gap-2 mb-1">
        <AlertTriangle className="w-3.5 h-3.5 text-amber-600" />
        <p className="text-xs font-semibold text-amber-800 uppercase tracking-wider">
          {invoices.length} unmatched invoice{invoices.length !== 1 ? 's' : ''} — assign a client to include in reports
        </p>
      </div>
      {invoices.map(inv => (
        <div key={inv.id} className="flex items-center gap-3 bg-white rounded-lg border border-amber-100 px-3 py-2 flex-wrap">
          <span className="font-mono text-sm font-bold text-slate-700 w-32 truncate">{inv.invoice_number}</span>
          <span className="text-xs text-slate-400 tabular-nums">{fmtDate(inv.invoice_date)}</span>
          <span className="text-sm font-semibold text-slate-700 tabular-nums">{fmtCurrency(inv.amount)}</span>
          <span className="text-[10px] font-mono px-1.5 py-0.5 bg-slate-100 text-slate-500 rounded">{inv.client_code || '—'}</span>
          <div className="flex items-center gap-2 ml-auto">
            <select
              className="text-xs border border-border/60 rounded-lg px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-primary/20"
              value={selections[inv.id] || ''}
              onChange={e => setSelections(s => ({ ...s, [inv.id]: e.target.value }))}
            >
              <option value="">Assign to client…</option>
              {clients.map(c => (
                <option key={c.id} value={c.id}>{c.name}{c.code ? ` (${c.code})` : ''}</option>
              ))}
            </select>
            <button
              onClick={() => handleMatch(inv.id)}
              disabled={!selections[inv.id] || matching[inv.id]}
              className="px-2.5 py-1.5 bg-amber-500 text-white text-xs font-semibold rounded-lg hover:bg-amber-600 disabled:opacity-40 transition-colors"
            >
              {matching[inv.id] ? <Loader2 className="w-3 h-3 animate-spin" /> : 'Match'}
            </button>
          </div>
        </div>
      ))}
    </div>
  );
};

// ── Conflict Queue ────────────────────────────────────────────────────────────

const ConflictQueue: React.FC<{
  conflicts: Conflict[]; onResolved: () => void;
}> = ({ conflicts, onResolved }) => {
  const [resolving, setResolving] = useState<Record<number, boolean>>({});

  const resolve = async (id: number, resolution: 'accept_source' | 'keep_tt') => {
    setResolving(r => ({ ...r, [id]: true }));
    try {
      await authFetch(`${API_BASE}/billing/invoices/conflicts/${id}/resolve/`, {
        method: 'POST',
        body: JSON.stringify({ resolution }),
      });
      onResolved();
    } finally {
      setResolving(r => ({ ...r, [id]: false }));
    }
  };

  return (
    <div className="bg-red-50 border border-red-200 rounded-xl p-4 space-y-2 shrink-0">
      <div className="flex items-center gap-2 mb-1">
        <AlertCircle className="w-3.5 h-3.5 text-red-600" />
        <p className="text-xs font-semibold text-red-800 uppercase tracking-wider">
          {conflicts.length} amount conflict{conflicts.length !== 1 ? 's' : ''} — invoice amounts differ between sources
        </p>
      </div>
      {conflicts.map(c => (
        <div key={c.id} className="flex items-center gap-4 bg-white rounded-lg border border-red-100 px-3 py-2 flex-wrap">
          <span className="font-mono text-sm font-bold text-slate-700 w-32 truncate">{c.invoice_number}</span>
          <div className="flex items-center gap-3 text-sm">
            <div className="text-center">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">TimeTracker</p>
              <p className="font-bold text-slate-800 tabular-nums">{fmtCurrency(c.tt_amount)}</p>
            </div>
            <span className="text-slate-300 text-xs font-bold">vs</span>
            <div className="text-center">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">{SOURCE_LABELS[c.source] || c.source}</p>
              <p className="font-bold text-slate-800 tabular-nums">{fmtCurrency(c.source_amount)}</p>
            </div>
          </div>
          <div className="flex items-center gap-2 ml-auto">
            <button
              onClick={() => resolve(c.id, 'keep_tt')}
              disabled={resolving[c.id]}
              className="px-2.5 py-1.5 text-xs font-semibold border border-border/60 text-slate-600 rounded-lg hover:bg-slate-50 disabled:opacity-40 transition-colors"
            >
              Keep TT
            </button>
            <button
              onClick={() => resolve(c.id, 'accept_source')}
              disabled={resolving[c.id]}
              className="px-2.5 py-1.5 text-xs font-semibold bg-primary text-white rounded-lg hover:opacity-90 disabled:opacity-40 transition-all"
            >
              {resolving[c.id] ? <Loader2 className="w-3 h-3 animate-spin" /> : `Use ${SOURCE_LABELS[c.source] || c.source}`}
            </button>
          </div>
        </div>
      ))}
    </div>
  );
};

// ── CSV Import Modal ──────────────────────────────────────────────────────────

const CsvImportModal: React.FC<{
  clients: Client[]; onClose: () => void; onImported: () => void;
}> = ({ clients, onClose, onImported }) => {
  type Step = 'upload' | 'preview' | 'done';
  const [step,        setStep]        = useState<Step>('upload');
  const [uploading,   setUploading]   = useState(false);
  const [committing,  setCommitting]  = useState(false);
  const [preview,     setPreview]     = useState<{ rows: PreviewRow[]; summary: PreviewSummary } | null>(null);
  const [editedRows,  setEditedRows]  = useState<PreviewRow[]>([]);
  const [commitResult,setCommitResult]= useState<any>(null);
  const [error,       setError]       = useState('');
  const fileRef = useRef<HTMLInputElement>(null);

  const handleFile = async (file: File) => {
    setError('');
    setUploading(true);
    try {
      const form = new FormData();
      form.append('file', file);
      const token = getAuthToken();
      const res = await fetch(`${API_BASE}/billing/invoices/import-csv/`, {
        method: 'POST',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        credentials: 'include',
        body: form,
      });
      const data = await res.json();
      if (!res.ok) { setError(data.error || 'Upload failed'); return; }
      setPreview(data);
      setEditedRows(data.rows);
      setStep('preview');
    } catch (e: any) {
      setError(e.message || 'Upload failed');
    } finally {
      setUploading(false);
    }
  };

  const updateRowClient = (i: number, clientId: number) => {
    setEditedRows(rows => rows.map((row, idx) => {
      if (idx !== i) return row;
      const client = clients.find(c => c.id === clientId);
      return { ...row, client_id: clientId, client_name: client?.name || null, needs_review: false, will_import: !row.is_duplicate };
    }));
  };

  const handleCommit = async () => {
    setCommitting(true);
    try {
      const res = await authFetch(`${API_BASE}/billing/invoices/import-csv/commit/`, {
        method: 'POST',
        body: JSON.stringify({ rows: editedRows.filter(r => !r.is_duplicate) }),
      });
      setCommitResult(await res.json());
      setStep('done');
    } catch (e: any) {
      setError(e.message || 'Commit failed');
    } finally {
      setCommitting(false);
    }
  };

  const downloadTemplate = async () => {
    const token = getAuthToken();
    const res = await fetch(`${API_BASE}/billing/invoices/import-csv/template/`, {
      credentials: 'include',
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) return;
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = 'invoice_import_template.csv';
    document.body.appendChild(a); a.click();
    document.body.removeChild(a); URL.revokeObjectURL(url);
  };

  const importCount = editedRows.filter(r => !r.is_duplicate && !r.needs_review).length;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-4xl max-h-[90vh] flex flex-col overflow-hidden">

        {/* Header */}
        <div className="px-6 py-4 border-b border-border/50 shrink-0">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h3 className="text-base font-bold text-slate-800">Import Invoices from CSV</h3>
              <p className="text-xs text-slate-400 mt-0.5">
                {step === 'upload'  && 'Upload a CSV file to preview before importing'}
                {step === 'preview' && 'Review matched invoices and fix any unmatched rows'}
                {step === 'done'    && 'Import complete'}
              </p>
            </div>
            <button onClick={onClose} className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors">
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          {error && (
            <div className="flex items-start gap-2.5 px-4 py-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
              <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" /> {error}
            </div>
          )}

          {/* Upload */}
          {step === 'upload' && (
            <div className="space-y-4">
              <div
                onDrop={e => { e.preventDefault(); e.dataTransfer.files[0] && handleFile(e.dataTransfer.files[0]); }}
                onDragOver={e => e.preventDefault()}
                onClick={() => fileRef.current?.click()}
                className={cn(
                  'border-2 border-dashed rounded-xl p-12 text-center cursor-pointer transition-colors',
                  uploading ? 'border-primary/40 bg-primary/5' : 'border-border/60 hover:border-primary/40 hover:bg-primary/3'
                )}
              >
                <input ref={fileRef} type="file" accept=".csv" className="hidden"
                  onChange={e => e.target.files?.[0] && handleFile(e.target.files[0])} />
                {uploading
                  ? <Loader2 className="w-9 h-9 text-primary animate-spin mx-auto mb-3" />
                  : <Upload className="w-9 h-9 text-slate-300 mx-auto mb-3" />
                }
                <p className="font-semibold text-slate-700 text-sm mb-1">
                  {uploading ? 'Parsing CSV…' : 'Drop your CSV here or click to browse'}
                </p>
                <p className="text-xs text-slate-400">Required: client_code, invoice_number, invoice_date, amount</p>
              </div>
              <div className="text-center">
                <button onClick={downloadTemplate} className="inline-flex items-center gap-1.5 text-xs font-semibold text-primary hover:underline">
                  <Download className="w-3.5 h-3.5" /> Download template with your client codes pre-filled
                </button>
              </div>
            </div>
          )}

          {/* Preview */}
          {step === 'preview' && preview && (
            <div className="space-y-4">
              {/* Summary pills */}
              <div className="flex gap-2 flex-wrap">
                <span className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-emerald-50 border border-emerald-200 rounded-lg text-xs font-semibold text-emerald-700">
                  <CheckCircle2 className="w-3.5 h-3.5" /> {preview.summary.will_import} will import
                </span>
                {preview.summary.unmatched > 0 && (
                  <span className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-amber-50 border border-amber-200 rounded-lg text-xs font-semibold text-amber-700">
                    <AlertTriangle className="w-3.5 h-3.5" /> {preview.summary.unmatched} needs review
                  </span>
                )}
                {preview.summary.duplicates > 0 && (
                  <span className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-slate-50 border border-border/50 rounded-lg text-xs font-semibold text-slate-500">
                    <XCircle className="w-3.5 h-3.5" /> {preview.summary.duplicates} skipped (duplicate)
                  </span>
                )}
                {preview.summary.parse_errors > 0 && (
                  <span className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-red-50 border border-red-200 rounded-lg text-xs font-semibold text-red-600">
                    <AlertCircle className="w-3.5 h-3.5" /> {preview.summary.parse_errors} parse errors
                  </span>
                )}
              </div>

              {/* Preview table */}
              <div className="border border-border/60 rounded-xl overflow-hidden">
                <table className="w-full text-sm border-collapse">
                  <thead>
                    <tr className="border-b border-border/50 bg-slate-50">
                      {['Invoice #', 'Date', 'Amount', 'Code', 'Matched Client', 'Status'].map(h => (
                        <th key={h} className="text-left px-4 py-2.5 text-xs font-semibold uppercase tracking-wider text-slate-500">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border/30">
                    {editedRows.map((row, i) => (
                      <tr key={i} className={cn('transition-colors', row.is_duplicate ? 'opacity-40 bg-slate-50' : 'hover:bg-slate-50/50')}>
                        <td className="px-4 py-2.5 font-mono font-semibold text-slate-700 text-xs">{row.invoice_number}</td>
                        <td className="px-4 py-2.5 text-slate-500 text-xs tabular-nums">{fmtDate(row.invoice_date)}</td>
                        <td className="px-4 py-2.5 font-semibold text-slate-800 tabular-nums text-xs">{fmtCurrency(row.amount)}</td>
                        <td className="px-4 py-2.5 font-mono text-[10px] text-slate-400">{row.client_code}</td>
                        <td className="px-4 py-2.5">
                          {row.is_duplicate ? (
                            <span className="text-slate-300 text-xs italic">—</span>
                          ) : row.needs_review ? (
                            <select
                              className="text-xs border border-amber-300 rounded-lg px-2 py-1 bg-amber-50 focus:outline-none focus:ring-2 focus:ring-amber-200 max-w-[200px]"
                              value={row.client_id || ''}
                              onChange={e => updateRowClient(i, Number(e.target.value))}
                            >
                              <option value="">— Select client —</option>
                              {row.suggestions.length > 0 && (
                                <optgroup label="Suggested matches">
                                  {row.suggestions.map(s => (
                                    <option key={s.client_id} value={s.client_id}>{s.client_name} ({s.client_code}) — {s.score}%</option>
                                  ))}
                                </optgroup>
                              )}
                              <optgroup label="All clients">
                                {clients.map(c => <option key={c.id} value={c.id}>{c.name}{c.code ? ` (${c.code})` : ''}</option>)}
                              </optgroup>
                            </select>
                          ) : (
                            <span className="text-xs font-semibold text-emerald-700">{row.client_name}</span>
                          )}
                        </td>
                        <td className="px-4 py-2.5">
                          {row.is_duplicate ? (
                            <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-slate-100 text-slate-400">Skip</span>
                          ) : row.needs_review ? (
                            <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-amber-50 text-amber-700 border border-amber-200">Review</span>
                          ) : (
                            <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200">Import</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Done */}
          {step === 'done' && commitResult && (
            <div className="text-center py-10">
              <div className="w-14 h-14 bg-emerald-50 rounded-full flex items-center justify-center mx-auto mb-4 border border-emerald-200">
                <CheckCircle2 className="w-7 h-7 text-emerald-500" />
              </div>
              <h3 className="text-base font-bold text-slate-800 mb-4">Import Complete</h3>
              <div className="flex justify-center gap-8">
                {[
                  { label: 'Imported', val: commitResult.summary.imported, cls: 'text-emerald-600' },
                  { label: 'Skipped',  val: commitResult.summary.skipped,  cls: 'text-slate-400'   },
                  ...(commitResult.summary.errors > 0 ? [{ label: 'Errors', val: commitResult.summary.errors, cls: 'text-red-500' }] : []),
                ].map(({ label, val, cls }) => (
                  <div key={label} className="text-center">
                    <p className={cn('text-2xl font-bold tabular-nums', cls)}>{val}</p>
                    <p className="text-xs text-slate-400 font-medium mt-0.5">{label}</p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 bg-slate-50/60 border-t border-border/50 flex items-center justify-between shrink-0">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-200 rounded-lg transition-colors"
          >
            {step === 'done' ? 'Close' : 'Cancel'}
          </button>
          <div className="flex items-center gap-2">
            {step === 'preview' && (
              <button onClick={() => setStep('upload')} className="px-4 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-200 rounded-lg transition-colors">
                Back
              </button>
            )}
            {step === 'preview' && (
              <button
                onClick={handleCommit}
                disabled={committing || importCount === 0}
                className="px-5 py-2 bg-primary text-white text-sm font-semibold rounded-lg hover:opacity-90 transition-all disabled:opacity-50 flex items-center gap-2"
              >
                {committing && <Loader2 className="w-4 h-4 animate-spin" />}
                Confirm Import ({importCount})
              </button>
            )}
            {step === 'done' && (
              <button onClick={() => { onImported(); onClose(); }} className="px-5 py-2 bg-primary text-white text-sm font-semibold rounded-lg hover:opacity-90 transition-all">
                View Invoices
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

// ── Main Component ────────────────────────────────────────────────────────────

const InvoiceManager: React.FC<Props> = ({ filter = '', onFilterClear }) => {
  const [invoices,   setInvoices]   = useState<Invoice[]>([]);
  const [clients,    setClients]    = useState<Client[]>([]);
  const [conflicts,  setConflicts]  = useState<Conflict[]>([]);
  const [loading,    setLoading]    = useState(true);
  const [showImport, setShowImport] = useState(false);
  const [syncing,    setSyncing]    = useState(false);
  const [deleting,   setDeleting]   = useState<Record<number, boolean>>({});

  const [search,        setSearch]        = useState('');
  const [sourceFilter,  setSourceFilter]  = useState('');
  const [statusFilter,  setStatusFilter]  = useState('');
  const [matchedFilter, setMatchedFilter] = useState<'' | 'matched' | 'unmatched'>(
    filter === 'unmatched' ? 'unmatched' : ''
  );
  const searchRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (filter === 'unmatched') setMatchedFilter('unmatched');
  }, [filter]);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    try {
      const [invData, clientData, conflictData] = await Promise.all([
        safeFetchJson<{ invoices: Invoice[] }>(`${API_BASE}/billing/invoices/`),
        safeFetchJson<{ clients: Client[] } | Client[]>(`${API_BASE}/options/clients/`),
        safeFetchJson<{ count: number; conflicts?: Conflict[] }>(`${API_BASE}/billing/invoices/conflicts/`),
      ]);
      setInvoices(invData.invoices || []);
      setClients(Array.isArray(clientData) ? clientData : (clientData as any).clients || []);
      setConflicts((conflictData as any).conflicts || []);
    } catch (e) {
      console.error('Failed to load invoice data', e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  const handleDelete = async (id: number) => {
    if (!window.confirm('Delete this invoice? This cannot be undone.')) return;
    setDeleting(d => ({ ...d, [id]: true }));
    try {
      await authFetch(`${API_BASE}/billing/invoices/${id}/delete/`, { method: 'DELETE' });
      setInvoices(inv => inv.filter(i => i.id !== id));
    } finally {
      setDeleting(d => ({ ...d, [id]: false }));
    }
  };

  const handleSyncQB = async () => {
    setSyncing(true);
    try {
      await authFetch(`${API_BASE}/integrations/qb/sync-invoices/`, { method: 'POST' });
      await new Promise(r => setTimeout(r, 2000));
      await fetchAll();
    } finally {
      setSyncing(false);
    }
  };

  const unmatchedInvoices = invoices.filter(i => !i.matched);

  const filteredInvoices = invoices.filter(inv => {
    if (search) {
      const q = search.toLowerCase();
      if (!inv.invoice_number.toLowerCase().includes(q) &&
          !inv.client_name.toLowerCase().includes(q) &&
          !inv.client_code.toLowerCase().includes(q)) return false;
    }
    if (sourceFilter  && inv.source  !== sourceFilter)  return false;
    if (statusFilter  && inv.status  !== statusFilter)  return false;
    if (matchedFilter === 'matched'   && !inv.matched)  return false;
    if (matchedFilter === 'unmatched' &&  inv.matched)  return false;
    return true;
  });

  const totalAmount    = filteredInvoices.reduce((s, i) => s + i.amount, 0);
  const totalHours     = filteredInvoices.reduce((s, i) => s + (i.hours_billed ?? 0), 0);
  const hasActiveFilter = search || sourceFilter || statusFilter || matchedFilter;

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[300px]">
        <RefreshCw className="w-5 h-5 text-slate-300 animate-spin" />
      </div>
    );
  }

  return (
    <div className="flex flex-col h-[calc(100vh-56px-48px-32px)] min-h-0 space-y-2">

      {/* ── ROW 1: Title / Stats / Actions ────────────────────────────── */}
      <div className="bg-white rounded-xl border border-border/60 px-5 h-14 flex items-center justify-between gap-4 shrink-0">
        <div className="flex items-center gap-3 shrink-0">
          <h2 className="text-base font-bold text-slate-800">Invoices</h2>
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold border bg-slate-50 text-slate-600 border-border/50">
            {invoices.length} total
          </span>
          {unmatchedInvoices.length > 0 && (
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold border bg-amber-50 text-amber-700 border-amber-200">
              <span className="w-1.5 h-1.5 bg-amber-500 rounded-full animate-pulse" />
              {unmatchedInvoices.length} unmatched
            </span>
          )}
          {conflicts.length > 0 && (
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold border bg-red-50 text-red-600 border-red-200">
              <span className="w-1.5 h-1.5 bg-red-500 rounded-full animate-pulse" />
              {conflicts.length} conflict{conflicts.length !== 1 ? 's' : ''}
            </span>
          )}
        </div>

        <div className="flex items-center gap-3">
          {/* Aggregate stats */}
          {filteredInvoices.length > 0 && (
            <div className="flex items-center gap-5 pr-4 border-r border-border/50">
              <div className="text-right">
                <p className="text-sm font-bold tabular-nums text-emerald-600 leading-none">{fmtCurrency(totalAmount)}</p>
                <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-400 mt-0.5">Total</p>
              </div>
              {totalHours > 0 && (
                <div className="text-right">
                  <p className="text-sm font-bold tabular-nums text-primary leading-none">{fmtHours(totalHours)}</p>
                  <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-400 mt-0.5">Hours</p>
                </div>
              )}
            </div>
          )}

          <button
            onClick={handleSyncQB}
            disabled={syncing}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-slate-600 bg-slate-50 hover:bg-slate-100 border border-border/60 rounded-lg transition-colors disabled:opacity-50"
          >
            {syncing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5 text-emerald-500" />}
            {syncing ? 'Syncing…' : 'Sync QB'}
          </button>
          <button
            onClick={() => setShowImport(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold bg-primary text-white rounded-lg hover:opacity-90 transition-all"
          >
            <Upload className="w-3.5 h-3.5" /> Import CSV
          </button>
          <button onClick={fetchAll} className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors" title="Refresh">
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* ── ROW 2: Search / Filters ────────────────────────────────────── */}
      <div className="bg-white rounded-xl border border-border/60 px-4 h-11 flex items-center gap-3 shrink-0">
        <div className="relative w-56">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400 pointer-events-none" />
          <input
            ref={searchRef}
            type="text"
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search invoices…"
            className="w-full pl-8 pr-7 py-1.5 text-sm bg-slate-50 border border-border/50 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary/40 transition-all"
          />
          {search && (
            <button onClick={() => setSearch('')} className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600">
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </div>

        {/* Dropdowns */}
        {[
          { value: sourceFilter,  setter: setSourceFilter,  opts: [['', 'All sources'], ['csv','CSV'], ['quickbooks','QuickBooks'], ['xero','Xero'], ['manual','Manual']] },
          { value: statusFilter,  setter: setStatusFilter,  opts: [['', 'All statuses'], ['paid','Paid'], ['sent','Sent'], ['draft','Draft'], ['voided','Voided'], ['overdue','Overdue']] },
          { value: matchedFilter, setter: setMatchedFilter, opts: [['', 'All invoices'], ['matched','Matched'], ['unmatched','Unmatched']] },
        ].map(({ value, setter, opts }, idx) => (
          <select
            key={idx}
            value={value}
            onChange={e => setter(e.target.value as any)}
            className={cn(
              'text-xs font-semibold px-3 py-1.5 rounded-lg border transition-all focus:outline-none focus:ring-2 focus:ring-primary/20',
              value
                ? 'bg-primary/8 text-primary border-primary/25'
                : 'bg-slate-50 text-slate-600 border-border/50 hover:bg-slate-100'
            )}
          >
            {opts.map(([val, label]) => <option key={val} value={val}>{label}</option>)}
          </select>
        ))}

        {/* Active filter pill from URL */}
        {filter && (
          <span className="inline-flex items-center gap-1 px-2.5 py-1 bg-primary/8 text-primary rounded-full text-[10px] font-bold border border-primary/20">
            {filter}
            <button onClick={() => { setMatchedFilter(''); setSourceFilter(''); onFilterClear?.(); }}>
              <X className="w-3 h-3" />
            </button>
          </span>
        )}

        {/* Count */}
        <span className="text-xs text-slate-400 ml-1">
          {filteredInvoices.length === invoices.length
            ? `${invoices.length} invoice${invoices.length !== 1 ? 's' : ''}`
            : <><span className="font-semibold text-slate-600">{filteredInvoices.length}</span> of {invoices.length}</>
          }
          {hasActiveFilter && filteredInvoices.length < invoices.length && (
            <button onClick={() => { setSearch(''); setSourceFilter(''); setStatusFilter(''); setMatchedFilter(''); }} className="ml-2 text-primary hover:underline font-medium">
              Clear
            </button>
          )}
        </span>
      </div>

      {/* ── Queues ────────────────────────────────────────────────────── */}
      {conflicts.length > 0 && (
        <ConflictQueue conflicts={conflicts} onResolved={fetchAll} />
      )}
      {unmatchedInvoices.length > 0 && matchedFilter !== 'matched' && (
        <UnmatchedQueue invoices={unmatchedInvoices} clients={clients} onMatched={fetchAll} />
      )}

      {/* ── Table ──────────────────────────────────────────────────────── */}
      <div className="bg-white rounded-xl border border-border/60 overflow-hidden flex flex-col flex-1 min-h-0">
        <div className="overflow-auto flex-1">
          <table className="w-full border-collapse text-sm" style={{ minWidth: 700 }}>

            <thead className="sticky top-0 z-20">
              <tr className="border-b border-border/60 bg-white">
                <th className="sticky left-0 z-20 text-left px-5 py-3 font-semibold text-slate-500 text-xs uppercase tracking-wider bg-slate-50 min-w-[160px] shadow-[2px_0_4px_-2px_rgba(0,0,0,0.06)]">
                  Invoice #
                </th>
                <th className="text-left px-4 py-3 font-semibold text-slate-500 text-xs uppercase tracking-wider bg-slate-50 whitespace-nowrap">Date</th>
                <th className="text-left px-4 py-3 font-semibold text-slate-500 text-xs uppercase tracking-wider bg-slate-50">Client</th>
                <th className="text-right px-4 py-3 font-semibold text-slate-500 text-xs uppercase tracking-wider bg-slate-50 whitespace-nowrap">Amount</th>
                <th className="text-right px-4 py-3 font-semibold text-slate-500 text-xs uppercase tracking-wider bg-slate-50 whitespace-nowrap">Hours</th>
                <th className="text-center px-4 py-3 font-semibold text-slate-500 text-xs uppercase tracking-wider bg-slate-50">Source</th>
                <th className="text-center px-4 py-3 font-semibold text-slate-500 text-xs uppercase tracking-wider bg-slate-50">Status</th>
                <th className="px-4 py-3 bg-slate-50 w-8" />
              </tr>
            </thead>

            <tbody className="divide-y divide-border/30">
              {filteredInvoices.length === 0 ? (
                <tr>
                  <td colSpan={8} className="text-center py-16 text-slate-400">
                    <FileText className="w-10 h-10 text-slate-200 mx-auto mb-3" />
                    <p className="font-medium text-slate-500">
                      {invoices.length === 0 ? 'No invoices yet' : 'No invoices match your filters'}
                    </p>
                    <p className="text-sm mt-1">
                      {invoices.length === 0
                        ? 'Import a CSV or sync from QuickBooks to get started'
                        : <button onClick={() => { setSearch(''); setSourceFilter(''); setStatusFilter(''); setMatchedFilter(''); }} className="text-primary hover:underline">Clear filters</button>
                      }
                    </p>
                  </td>
                </tr>
              ) : (
                filteredInvoices.map(inv => (
                  <tr key={inv.id} className="hover:bg-slate-50/50 transition-colors group">
                    {/* Invoice # */}
                    <td className="sticky left-0 z-10 px-5 py-3 bg-white shadow-[2px_0_4px_-2px_rgba(0,0,0,0.06)]">
                      <span className="font-mono font-bold text-slate-800 text-xs">{inv.invoice_number}</span>
                    </td>
                    {/* Date */}
                    <td className="px-4 py-3 text-sm text-slate-500 tabular-nums whitespace-nowrap">{fmtDate(inv.invoice_date)}</td>
                    {/* Client */}
                    <td className="px-4 py-3">
                      {inv.matched ? (
                        <span className="text-sm font-medium text-slate-700">{inv.client_name}</span>
                      ) : (
                        <div className="flex items-center gap-1.5">
                          <AlertTriangle className="w-3.5 h-3.5 text-amber-500 shrink-0" />
                          <span className="text-sm font-medium text-amber-700">{inv.client_code || 'Unmatched'}</span>
                        </div>
                      )}
                    </td>
                    {/* Amount */}
                    <td className="px-4 py-3 text-right font-bold text-slate-800 tabular-nums text-sm">{fmtCurrency(inv.amount)}</td>
                    {/* Hours */}
                    <td className="px-4 py-3 text-right text-slate-400 tabular-nums text-sm">{fmtHours(inv.hours_billed)}</td>
                    {/* Source */}
                    <td className="px-4 py-3 text-center">
                      <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold bg-slate-100 text-slate-500 border border-border/40">
                        {SOURCE_LABELS[inv.source] || inv.source}
                      </span>
                    </td>
                    {/* Status */}
                    <td className="px-4 py-3 text-center">
                      <span className={cn(
                        'inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold border',
                        STATUS_CLS[inv.status] || STATUS_CLS.sent
                      )}>
                        {inv.status ? inv.status.charAt(0).toUpperCase() + inv.status.slice(1) : 'Sent'}
                      </span>
                    </td>
                    {/* Delete */}
                    <td className="px-4 py-3 text-right">
                      <button
                        onClick={() => handleDelete(inv.id)}
                        disabled={deleting[inv.id]}
                        className="opacity-0 group-hover:opacity-100 transition-opacity p-1 rounded-lg text-slate-300 hover:text-red-500 hover:bg-red-50"
                        title="Delete"
                      >
                        {deleting[inv.id] ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Trash2 className="w-3.5 h-3.5" />}
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Footer */}
        <div className="px-5 py-3 border-t border-border/50 flex items-center justify-between bg-slate-50/40 shrink-0">
          <p className="text-xs text-slate-400 flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-primary inline-block" />
            {filteredInvoices.length} invoice{filteredInvoices.length !== 1 ? 's' : ''}
            {filteredInvoices.length !== invoices.length && ` (filtered from ${invoices.length})`}
          </p>
          <p className="text-xs font-semibold text-emerald-600 tabular-nums">
            {fmtCurrency(totalAmount)}
          </p>
        </div>
      </div>

      {/* CSV Import Modal */}
      {showImport && (
        <CsvImportModal clients={clients} onClose={() => setShowImport(false)} onImported={fetchAll} />
      )}
    </div>
  );
};

export default InvoiceManager;