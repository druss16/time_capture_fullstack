/**
 * InvoiceManager.tsx
 *
 * All-in-one invoice tab. Sections:
 *   1. Unmatched queue (amber banner, shown when unmatched > 0)
 *   2. Conflict queue (amber banner, shown when conflicts > 0 or filter==='conflicts')
 *   3. Invoice table with filters (source, status, date range, search)
 *   4. CSV import modal (two-step: preview → commit)
 *   5. Conflict resolution modal
 *
 * Props:
 *   filter       – pre-applied filter from URL (?filter=conflicts | ?filter=unmatched)
 *   onFilterClear – callback to clear the URL filter param
 */

import React, { useState, useEffect, useCallback, useRef } from 'react';
import { safeFetchJson, API_BASE } from '@/lib/api';
import {
  Upload,
  Download,
  AlertTriangle,
  CheckCircle,
  XCircle,
  RefreshCw,
  Search,
  ChevronDown,
  X,
  FileText,
  Link2,
  Loader2,
  AlertCircle,
  Eye,
  Trash2,
} from 'lucide-react';
import { cn } from '@/lib/design-system';

// ─── Types ───────────────────────────────────────────────────────────────────

interface Client {
  id: number;
  name: string;
  code: string;
}

interface Invoice {
  id: number;
  invoice_number: string;
  invoice_date: string;
  amount: number;
  hours_billed: number | null;
  client_id: number | null;
  client_name: string;
  client_code: string;
  source: 'csv' | 'quickbooks' | 'xero' | 'manual';
  status: 'draft' | 'sent' | 'paid' | 'voided' | 'overdue';
  matched: boolean;
}

interface Conflict {
  id: number;
  invoice_number: string;
  tt_amount: number;
  source_amount: number;
  source: string;
  detected_at: string;
}

interface PreviewRow {
  row: number;
  invoice_number: string;
  invoice_date: string;
  amount: number;
  hours_billed: number | null;
  status: string;
  client_code: string;
  client_id: number | null;
  client_name: string | null;
  match_score: number;
  needs_review: boolean;
  suggestions: { client_id: number; client_name: string; client_code: string; score: number }[];
  is_duplicate: boolean;
  will_import: boolean;
}

interface PreviewSummary {
  total_rows: number;
  will_import: number;
  matched: number;
  unmatched: number;
  duplicates: number;
  parse_errors: number;
}

interface Props {
  filter?: string;
  onFilterClear?: () => void;
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

const SOURCE_LABELS: Record<string, string> = {
  csv: 'CSV',
  quickbooks: 'QuickBooks',
  xero: 'Xero',
  manual: 'Manual',
};

const STATUS_COLORS: Record<string, string> = {
  paid:    'bg-green-100 text-green-700',
  sent:    'bg-blue-100 text-blue-700',
  draft:   'bg-slate-100 text-slate-600',
  voided:  'bg-red-100 text-red-500',
  overdue: 'bg-orange-100 text-orange-700',
};

const fmtCurrency = (n: number) =>
  new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(n);

const fmtDate = (s: string) =>
  new Date(s + 'T00:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });

// ─── Unmatched Queue ──────────────────────────────────────────────────────────

const UnmatchedQueue: React.FC<{
  invoices: Invoice[];
  clients: Client[];
  onMatched: () => void;
}> = ({ invoices, clients, onMatched }) => {
  const [matching, setMatching] = useState<Record<number, boolean>>({});
  const [selections, setSelections] = useState<Record<number, string>>({});

  const handleMatch = async (invoiceId: number) => {
    const clientId = selections[invoiceId];
    if (!clientId) return;
    setMatching((m) => ({ ...m, [invoiceId]: true }));
    try {
      await fetch(`${API_BASE}/billing/invoices/match/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrf() },
        credentials: 'include',
        body: JSON.stringify({ invoice_id: invoiceId, client_id: Number(clientId) }),
      });
      onMatched();
    } finally {
      setMatching((m) => ({ ...m, [invoiceId]: false }));
    }
  };

  return (
    <div className="bg-amber-50 border-2 border-amber-200 rounded-2xl p-4 mb-6">
      <div className="flex items-center gap-2 mb-3">
        <AlertTriangle className="w-4 h-4 text-amber-600" />
        <h3 className="font-bold text-amber-800 text-sm">
          {invoices.length} Unmatched Invoice{invoices.length !== 1 ? 's' : ''} — assign a client to include in reports
        </h3>
      </div>
      <div className="space-y-2">
        {invoices.map((inv) => (
          <div
            key={inv.id}
            className="flex items-center gap-3 bg-white rounded-xl border border-amber-200 px-4 py-2.5 flex-wrap"
          >
            <span className="font-mono text-sm font-bold text-slate-700 w-32 truncate">
              {inv.invoice_number}
            </span>
            <span className="text-xs text-slate-500 w-20">{fmtDate(inv.invoice_date)}</span>
            <span className="font-semibold text-slate-700 text-sm w-24">{fmtCurrency(inv.amount)}</span>
            <span className="text-xs px-2 py-0.5 rounded bg-slate-100 text-slate-500 font-mono">
              {inv.client_code || '—'}
            </span>
            <div className="flex items-center gap-2 ml-auto">
              <select
                className="text-sm border-2 border-slate-200 rounded-lg px-2 py-1 bg-white focus:border-primary outline-none"
                value={selections[inv.id] || ''}
                onChange={(e) => setSelections((s) => ({ ...s, [inv.id]: e.target.value }))}
              >
                <option value="">Assign to client…</option>
                {clients.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}{c.code ? ` (${c.code})` : ''}
                  </option>
                ))}
              </select>
              <button
                onClick={() => handleMatch(inv.id)}
                disabled={!selections[inv.id] || matching[inv.id]}
                className="px-3 py-1.5 bg-amber-500 text-white text-xs font-bold rounded-lg hover:bg-amber-600 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                {matching[inv.id] ? <Loader2 className="w-3 h-3 animate-spin" /> : 'Match'}
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

// ─── Conflict Queue ───────────────────────────────────────────────────────────

const ConflictQueue: React.FC<{
  conflicts: Conflict[];
  onResolved: () => void;
}> = ({ conflicts, onResolved }) => {
  const [resolving, setResolving] = useState<Record<number, boolean>>({});

  const resolve = async (conflictId: number, resolution: 'accept_source' | 'keep_tt') => {
    setResolving((r) => ({ ...r, [conflictId]: true }));
    try {
      await fetch(`${API_BASE}/billing/invoices/conflicts/${conflictId}/resolve/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrf() },
        credentials: 'include',
        body: JSON.stringify({ resolution }),
      });
      onResolved();
    } finally {
      setResolving((r) => ({ ...r, [conflictId]: false }));
    }
  };

  return (
    <div className="bg-red-50 border-2 border-red-200 rounded-2xl p-4 mb-6">
      <div className="flex items-center gap-2 mb-3">
        <AlertCircle className="w-4 h-4 text-red-600" />
        <h3 className="font-bold text-red-800 text-sm">
          {conflicts.length} Amount Conflict{conflicts.length !== 1 ? 's' : ''} — invoice amounts differ between sources
        </h3>
      </div>
      <div className="space-y-2">
        {conflicts.map((c) => (
          <div
            key={c.id}
            className="bg-white rounded-xl border border-red-200 px-4 py-3 flex items-center gap-4 flex-wrap"
          >
            <span className="font-mono text-sm font-bold text-slate-700 w-32 truncate">
              {c.invoice_number}
            </span>
            <div className="flex items-center gap-4 text-sm">
              <div className="text-center">
                <div className="text-xs text-slate-500 mb-0.5">TimeTracker</div>
                <div className="font-bold text-slate-800">{fmtCurrency(c.tt_amount)}</div>
              </div>
              <div className="text-slate-300 font-bold">vs</div>
              <div className="text-center">
                <div className="text-xs text-slate-500 mb-0.5">{SOURCE_LABELS[c.source] || c.source}</div>
                <div className="font-bold text-slate-800">{fmtCurrency(c.source_amount)}</div>
              </div>
            </div>
            <div className="flex items-center gap-2 ml-auto">
              <button
                onClick={() => resolve(c.id, 'keep_tt')}
                disabled={resolving[c.id]}
                className="px-3 py-1.5 text-xs font-bold border-2 border-slate-300 text-slate-700 rounded-lg hover:border-slate-400 hover:bg-slate-50 disabled:opacity-40 transition-colors"
              >
                Keep TT
              </button>
              <button
                onClick={() => resolve(c.id, 'accept_source')}
                disabled={resolving[c.id]}
                className="px-3 py-1.5 text-xs font-bold bg-primary text-white rounded-lg hover:opacity-90 disabled:opacity-40 transition-colors"
              >
                {resolving[c.id] ? <Loader2 className="w-3 h-3 animate-spin" /> : `Use ${SOURCE_LABELS[c.source] || c.source}`}
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

// ─── CSV Import Modal ─────────────────────────────────────────────────────────

const CsvImportModal: React.FC<{
  clients: Client[];
  onClose: () => void;
  onImported: () => void;
}> = ({ clients, onClose, onImported }) => {
  type Step = 'upload' | 'preview' | 'done';
  const [step, setStep] = useState<Step>('upload');
  const [uploading, setUploading] = useState(false);
  const [committing, setCommitting] = useState(false);
  const [preview, setPreview] = useState<{ rows: PreviewRow[]; summary: PreviewSummary } | null>(null);
  const [editedRows, setEditedRows] = useState<PreviewRow[]>([]);
  const [commitResult, setCommitResult] = useState<any>(null);
  const [error, setError] = useState('');
  const fileRef = useRef<HTMLInputElement>(null);

  const handleFile = async (file: File) => {
    setError('');
    setUploading(true);
    try {
      const form = new FormData();
      form.append('file', file);
      const res = await fetch(`${API_BASE}/billing/invoices/import-csv/`, {
        method: 'POST',
        headers: { 'X-CSRFToken': getCsrf() },
        credentials: 'include',
        body: form,
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data.error || 'Upload failed');
        return;
      }
      setPreview(data);
      setEditedRows(data.rows);
      setStep('preview');
    } catch (e: any) {
      setError(e.message || 'Upload failed');
    } finally {
      setUploading(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    const file = e.dataTransfer.files[0];
    if (file) handleFile(file);
  };

  const updateRowClient = (rowIndex: number, clientId: number) => {
    setEditedRows((rows) =>
      rows.map((row, i) => {
        if (i !== rowIndex) return row;
        const client = clients.find((c) => c.id === clientId);
        return {
          ...row,
          client_id: clientId,
          client_name: client?.name || null,
          needs_review: false,
          will_import: !row.is_duplicate,
        };
      })
    );
  };

  const handleCommit = async () => {
    setCommitting(true);
    try {
      const rowsToSend = editedRows.filter((r) => !r.is_duplicate);
      const res = await fetch(`${API_BASE}/billing/invoices/import-csv/commit/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrf() },
        credentials: 'include',
        body: JSON.stringify({ rows: rowsToSend }),
      });
      const data = await res.json();
      setCommitResult(data);
      setStep('done');
    } catch (e: any) {
      setError(e.message || 'Commit failed');
    } finally {
      setCommitting(false);
    }
  };

  const downloadTemplate = () => {
    window.location.href = `${API_BASE}/billing/invoices/import-csv/template/`;
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
      <div className="bg-white rounded-2xl shadow-2xl border-2 border-slate-200 w-full max-w-4xl max-h-[90vh] flex flex-col">
        {/* Modal header */}
        <div className="flex items-center justify-between p-5 border-b-2 border-slate-100">
          <div>
            <h2 className="text-lg font-extrabold text-slate-900">Import Invoices from CSV</h2>
            <p className="text-sm text-slate-500 font-medium mt-0.5">
              {step === 'upload' && 'Upload a CSV file to preview before importing'}
              {step === 'preview' && 'Review matched invoices and fix any unmatched rows'}
              {step === 'done' && 'Import complete'}
            </p>
          </div>
          <button
            onClick={onClose}
            className="w-8 h-8 rounded-lg flex items-center justify-center text-slate-400 hover:bg-slate-100 hover:text-slate-600 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-5">
          {/* Step: Upload */}
          {step === 'upload' && (
            <div className="space-y-4">
              {error && (
                <div className="flex items-start gap-2 bg-red-50 border border-red-200 text-red-700 rounded-xl p-3 text-sm">
                  <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
                  <span>{error}</span>
                </div>
              )}
              <div
                onDrop={handleDrop}
                onDragOver={(e) => e.preventDefault()}
                onClick={() => fileRef.current?.click()}
                className={cn(
                  'border-2 border-dashed rounded-2xl p-12 text-center cursor-pointer transition-colors',
                  uploading
                    ? 'border-primary/50 bg-primary/5'
                    : 'border-slate-300 hover:border-primary hover:bg-primary/5'
                )}
              >
                <input
                  ref={fileRef}
                  type="file"
                  accept=".csv"
                  className="hidden"
                  onChange={(e) => e.target.files?.[0] && handleFile(e.target.files[0])}
                />
                {uploading ? (
                  <Loader2 className="w-10 h-10 text-primary animate-spin mx-auto mb-3" />
                ) : (
                  <Upload className="w-10 h-10 text-slate-400 mx-auto mb-3" />
                )}
                <p className="font-bold text-slate-700 mb-1">
                  {uploading ? 'Parsing CSV…' : 'Drop your CSV here or click to browse'}
                </p>
                <p className="text-sm text-slate-500">
                  Required columns: client_code, invoice_number, invoice_date, amount
                </p>
              </div>
              <div className="flex items-center justify-center">
                <button
                  onClick={downloadTemplate}
                  className="flex items-center gap-2 text-sm font-semibold text-primary hover:underline"
                >
                  <Download className="w-4 h-4" />
                  Download template with your client codes pre-filled
                </button>
              </div>
            </div>
          )}

          {/* Step: Preview */}
          {step === 'preview' && preview && (
            <div className="space-y-4">
              {error && (
                <div className="flex items-start gap-2 bg-red-50 border border-red-200 text-red-700 rounded-xl p-3 text-sm">
                  <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
                  <span>{error}</span>
                </div>
              )}

              {/* Summary bar */}
              <div className="flex gap-4 flex-wrap">
                <div className="flex items-center gap-2 bg-green-50 border border-green-200 rounded-xl px-4 py-2">
                  <CheckCircle className="w-4 h-4 text-green-600" />
                  <span className="text-sm font-bold text-green-800">{preview.summary.will_import} will import</span>
                </div>
                {preview.summary.unmatched > 0 && (
                  <div className="flex items-center gap-2 bg-amber-50 border border-amber-200 rounded-xl px-4 py-2">
                    <AlertTriangle className="w-4 h-4 text-amber-600" />
                    <span className="text-sm font-bold text-amber-800">{preview.summary.unmatched} needs review</span>
                  </div>
                )}
                {preview.summary.duplicates > 0 && (
                  <div className="flex items-center gap-2 bg-slate-50 border border-slate-200 rounded-xl px-4 py-2">
                    <XCircle className="w-4 h-4 text-slate-500" />
                    <span className="text-sm font-bold text-slate-600">{preview.summary.duplicates} skipped (duplicate)</span>
                  </div>
                )}
                {preview.summary.parse_errors > 0 && (
                  <div className="flex items-center gap-2 bg-red-50 border border-red-200 rounded-xl px-4 py-2">
                    <AlertCircle className="w-4 h-4 text-red-500" />
                    <span className="text-sm font-bold text-red-700">{preview.summary.parse_errors} parse errors</span>
                  </div>
                )}
              </div>

              {/* Preview table */}
              <div className="border-2 border-slate-200 rounded-xl overflow-hidden">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 border-b-2 border-slate-200">
                    <tr>
                      <th className="text-left px-4 py-2.5 font-bold text-slate-600">Invoice #</th>
                      <th className="text-left px-4 py-2.5 font-bold text-slate-600">Date</th>
                      <th className="text-right px-4 py-2.5 font-bold text-slate-600">Amount</th>
                      <th className="text-left px-4 py-2.5 font-bold text-slate-600">Code</th>
                      <th className="text-left px-4 py-2.5 font-bold text-slate-600">Matched Client</th>
                      <th className="text-center px-4 py-2.5 font-bold text-slate-600">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {editedRows.map((row, i) => (
                      <tr
                        key={i}
                        className={cn(
                          'transition-colors',
                          row.is_duplicate ? 'opacity-40 bg-slate-50' : 'hover:bg-slate-50'
                        )}
                      >
                        <td className="px-4 py-2.5 font-mono font-semibold text-slate-700">
                          {row.invoice_number}
                        </td>
                        <td className="px-4 py-2.5 text-slate-600">{fmtDate(row.invoice_date)}</td>
                        <td className="px-4 py-2.5 text-right font-semibold text-slate-800">
                          {fmtCurrency(row.amount)}
                        </td>
                        <td className="px-4 py-2.5 font-mono text-xs text-slate-500">{row.client_code}</td>
                        <td className="px-4 py-2.5">
                          {row.is_duplicate ? (
                            <span className="text-slate-400 text-xs italic">—</span>
                          ) : row.needs_review ? (
                            <select
                              className="text-sm border-2 border-amber-300 rounded-lg px-2 py-1 bg-amber-50 focus:border-primary outline-none max-w-[200px]"
                              value={row.client_id || ''}
                              onChange={(e) => updateRowClient(i, Number(e.target.value))}
                            >
                              <option value="">— Select client —</option>
                              {row.suggestions.length > 0 && (
                                <optgroup label="Suggested matches">
                                  {row.suggestions.map((s) => (
                                    <option key={s.client_id} value={s.client_id}>
                                      {s.client_name} ({s.client_code}) — {s.score}%
                                    </option>
                                  ))}
                                </optgroup>
                              )}
                              <optgroup label="All clients">
                                {clients.map((c) => (
                                  <option key={c.id} value={c.id}>
                                    {c.name}{c.code ? ` (${c.code})` : ''}
                                  </option>
                                ))}
                              </optgroup>
                            </select>
                          ) : (
                            <span className="text-green-700 font-semibold">{row.client_name}</span>
                          )}
                        </td>
                        <td className="px-4 py-2.5 text-center">
                          {row.is_duplicate ? (
                            <span className="text-xs px-2 py-0.5 rounded-full bg-slate-100 text-slate-400 font-semibold">
                              Skip
                            </span>
                          ) : row.needs_review ? (
                            <span className="text-xs px-2 py-0.5 rounded-full bg-amber-100 text-amber-700 font-semibold">
                              Review
                            </span>
                          ) : (
                            <span className="text-xs px-2 py-0.5 rounded-full bg-green-100 text-green-700 font-semibold">
                              Import
                            </span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Step: Done */}
          {step === 'done' && commitResult && (
            <div className="text-center py-12">
              <div className="w-16 h-16 bg-green-100 rounded-full flex items-center justify-center mx-auto mb-4">
                <CheckCircle className="w-8 h-8 text-green-500" />
              </div>
              <h3 className="text-xl font-extrabold text-slate-900 mb-2">Import Complete</h3>
              <div className="flex gap-6 justify-center mt-6 text-sm">
                <div className="text-center">
                  <div className="text-2xl font-extrabold text-green-600">{commitResult.summary.imported}</div>
                  <div className="text-slate-500 font-medium">Imported</div>
                </div>
                <div className="text-center">
                  <div className="text-2xl font-extrabold text-slate-400">{commitResult.summary.skipped}</div>
                  <div className="text-slate-500 font-medium">Skipped</div>
                </div>
                {commitResult.summary.errors > 0 && (
                  <div className="text-center">
                    <div className="text-2xl font-extrabold text-red-500">{commitResult.summary.errors}</div>
                    <div className="text-slate-500 font-medium">Errors</div>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Modal footer */}
        <div className="p-5 border-t-2 border-slate-100 flex items-center justify-between">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm font-bold text-slate-600 border-2 border-slate-200 rounded-xl hover:bg-slate-50 transition-colors"
          >
            {step === 'done' ? 'Close' : 'Cancel'}
          </button>
          {step === 'preview' && (
            <div className="flex items-center gap-3">
              <button
                onClick={() => setStep('upload')}
                className="px-4 py-2 text-sm font-bold text-slate-600 border-2 border-slate-200 rounded-xl hover:bg-slate-50 transition-colors"
              >
                Back
              </button>
              <button
                onClick={handleCommit}
                disabled={committing || editedRows.filter((r) => !r.is_duplicate).length === 0}
                className="px-6 py-2 text-sm font-bold bg-primary text-white rounded-xl hover:opacity-90 disabled:opacity-40 disabled:cursor-not-allowed transition-all flex items-center gap-2"
              >
                {committing && <Loader2 className="w-4 h-4 animate-spin" />}
                Confirm Import ({editedRows.filter((r) => !r.is_duplicate && !r.needs_review).length} invoices)
              </button>
            </div>
          )}
          {step === 'done' && (
            <button
              onClick={() => { onImported(); onClose(); }}
              className="px-6 py-2 text-sm font-bold bg-primary text-white rounded-xl hover:opacity-90 transition-all"
            >
              View Invoices
            </button>
          )}
        </div>
      </div>
    </div>
  );
};

// ─── CSRF helper ─────────────────────────────────────────────────────────────

function getCsrf(): string {
  return document.cookie
    .split('; ')
    .find((row) => row.startsWith('csrftoken='))
    ?.split('=')[1] || '';
}

// ─── Main Component ───────────────────────────────────────────────────────────

const InvoiceManager: React.FC<Props> = ({ filter = '', onFilterClear }) => {
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [clients, setClients] = useState<Client[]>([]);
  const [conflicts, setConflicts] = useState<Conflict[]>([]);
  const [loading, setLoading] = useState(true);
  const [showImport, setShowImport] = useState(false);

  // Filters
  const [search, setSearch] = useState('');
  const [sourceFilter, setSourceFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [matchedFilter, setMatchedFilter] = useState<'' | 'matched' | 'unmatched'>(
    filter === 'unmatched' ? 'unmatched' : ''
  );

  const [deleting, setDeleting] = useState<Record<number, boolean>>({});

  // When filter prop changes (e.g. from URL), sync into state
  useEffect(() => {
    if (filter === 'conflicts') setMatchedFilter('unmatched'); // show relevant rows
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
      // options/clients may return array or {clients:[]}
      setClients(Array.isArray(clientData) ? clientData : (clientData as any).clients || []);
      setConflicts((conflictData as any).conflicts || []);
    } catch (e) {
      console.error('Failed to load invoice data', e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  const handleDelete = async (invoiceId: number) => {
    if (!window.confirm('Delete this invoice? This cannot be undone.')) return;
    setDeleting((d) => ({ ...d, [invoiceId]: true }));
    try {
      await fetch(`${API_BASE}/billing/invoices/${invoiceId}/delete/`, {
        method: 'DELETE',
        headers: { 'X-CSRFToken': getCsrf() },
        credentials: 'include',
      });
      setInvoices((inv) => inv.filter((i) => i.id !== invoiceId));
    } finally {
      setDeleting((d) => ({ ...d, [invoiceId]: false }));
    }
  };

  // Derived data
  const unmatchedInvoices = invoices.filter((i) => !i.matched);

  const filteredInvoices = invoices.filter((inv) => {
    if (search) {
      const q = search.toLowerCase();
      if (
        !inv.invoice_number.toLowerCase().includes(q) &&
        !inv.client_name.toLowerCase().includes(q) &&
        !inv.client_code.toLowerCase().includes(q)
      ) return false;
    }
    if (sourceFilter && inv.source !== sourceFilter) return false;
    if (statusFilter && inv.status !== statusFilter) return false;
    if (matchedFilter === 'matched' && !inv.matched) return false;
    if (matchedFilter === 'unmatched' && inv.matched) return false;
    return true;
  });

  const totalAmount = filteredInvoices.reduce((sum, i) => sum + i.amount, 0);

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-extrabold text-slate-900 tracking-tight">Invoices</h2>
          <p className="text-sm text-slate-500 font-medium mt-0.5">
            All imported, synced, and manual invoices
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={fetchAll}
            className="flex items-center gap-2 px-3 py-2 text-sm font-bold text-slate-600 border-2 border-slate-200 rounded-xl hover:bg-slate-100 transition-colors"
          >
            <RefreshCw className="w-4 h-4" />
            Refresh
          </button>
          <button
            onClick={() => setShowImport(true)}
            className="flex items-center gap-2 px-4 py-2 text-sm font-bold bg-primary text-white rounded-xl hover:opacity-90 transition-all shadow-lg shadow-primary/25"
          >
            <Upload className="w-4 h-4" />
            Import CSV
          </button>
        </div>
      </div>

      {/* Conflict queue (shown when filter=conflicts or conflicts exist) */}
      {(filter === 'conflicts' || conflicts.length > 0) && conflicts.length > 0 && (
        <ConflictQueue conflicts={conflicts} onResolved={fetchAll} />
      )}

      {/* Unmatched queue */}
      {unmatchedInvoices.length > 0 && matchedFilter !== 'matched' && (
        <UnmatchedQueue
          invoices={unmatchedInvoices}
          clients={clients}
          onMatched={fetchAll}
        />
      )}

      {/* Active filter pill if filter came from URL */}
      {filter && (
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold text-slate-500">Filtered by:</span>
          <span className="inline-flex items-center gap-1.5 px-3 py-1 bg-primary/10 text-primary rounded-full text-xs font-bold">
            {filter}
            <button
              onClick={() => { setMatchedFilter(''); setSourceFilter(''); onFilterClear?.(); }}
              className="hover:text-primary/70 transition-colors"
            >
              <X className="w-3 h-3" />
            </button>
          </span>
        </div>
      )}

      {/* Filters bar */}
      <div className="flex items-center gap-3 flex-wrap">
        <div className="relative flex-1 min-w-[220px]">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
          <input
            type="text"
            placeholder="Search invoices…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-9 pr-4 py-2 text-sm border-2 border-slate-200 rounded-xl bg-white focus:border-primary outline-none"
          />
        </div>

        <select
          value={sourceFilter}
          onChange={(e) => setSourceFilter(e.target.value)}
          className="text-sm border-2 border-slate-200 rounded-xl px-3 py-2 bg-white focus:border-primary outline-none font-medium text-slate-600"
        >
          <option value="">All sources</option>
          <option value="csv">CSV</option>
          <option value="quickbooks">QuickBooks</option>
          <option value="xero">Xero</option>
          <option value="manual">Manual</option>
        </select>

        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="text-sm border-2 border-slate-200 rounded-xl px-3 py-2 bg-white focus:border-primary outline-none font-medium text-slate-600"
        >
          <option value="">All statuses</option>
          <option value="paid">Paid</option>
          <option value="sent">Sent</option>
          <option value="draft">Draft</option>
          <option value="voided">Voided</option>
          <option value="overdue">Overdue</option>
        </select>

        <select
          value={matchedFilter}
          onChange={(e) => setMatchedFilter(e.target.value as any)}
          className="text-sm border-2 border-slate-200 rounded-xl px-3 py-2 bg-white focus:border-primary outline-none font-medium text-slate-600"
        >
          <option value="">All invoices</option>
          <option value="matched">Matched only</option>
          <option value="unmatched">Unmatched only</option>
        </select>
      </div>

      {/* Invoice table */}
      <div className="bg-white border-2 border-slate-200 rounded-2xl overflow-hidden">
        {/* Table header summary */}
        <div className="flex items-center justify-between px-5 py-3 border-b-2 border-slate-100 bg-slate-50">
          <span className="text-sm font-bold text-slate-600">
            {filteredInvoices.length} invoice{filteredInvoices.length !== 1 ? 's' : ''}
            {filteredInvoices.length !== invoices.length && (
              <span className="text-slate-400 font-medium"> (filtered from {invoices.length})</span>
            )}
          </span>
          <span className="text-sm font-bold text-slate-800">
            Total: <span className="text-primary">{fmtCurrency(totalAmount)}</span>
          </span>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-16">
            <Loader2 className="w-6 h-6 text-primary animate-spin" />
          </div>
        ) : filteredInvoices.length === 0 ? (
          <div className="text-center py-16">
            <FileText className="w-10 h-10 text-slate-300 mx-auto mb-3" />
            <p className="font-bold text-slate-500">No invoices found</p>
            <p className="text-sm text-slate-400 mt-1">
              {invoices.length === 0
                ? 'Import a CSV or sync from QuickBooks to get started'
                : 'Try adjusting your filters'}
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-b-2 border-slate-100">
                <tr>
                  <th className="text-left px-5 py-3 font-bold text-slate-500 text-xs uppercase tracking-wide">
                    Invoice #
                  </th>
                  <th className="text-left px-4 py-3 font-bold text-slate-500 text-xs uppercase tracking-wide">
                    Date
                  </th>
                  <th className="text-left px-4 py-3 font-bold text-slate-500 text-xs uppercase tracking-wide">
                    Client
                  </th>
                  <th className="text-right px-4 py-3 font-bold text-slate-500 text-xs uppercase tracking-wide">
                    Amount
                  </th>
                  <th className="text-right px-4 py-3 font-bold text-slate-500 text-xs uppercase tracking-wide">
                    Hours
                  </th>
                  <th className="text-center px-4 py-3 font-bold text-slate-500 text-xs uppercase tracking-wide">
                    Source
                  </th>
                  <th className="text-center px-4 py-3 font-bold text-slate-500 text-xs uppercase tracking-wide">
                    Status
                  </th>
                  <th className="px-4 py-3" />
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {filteredInvoices.map((inv) => (
                  <tr key={inv.id} className="hover:bg-slate-50 transition-colors group">
                    <td className="px-5 py-3">
                      <span className="font-mono font-bold text-slate-800">{inv.invoice_number}</span>
                    </td>
                    <td className="px-4 py-3 text-slate-600">{fmtDate(inv.invoice_date)}</td>
                    <td className="px-4 py-3">
                      {inv.matched ? (
                        <span className="font-semibold text-slate-800">{inv.client_name}</span>
                      ) : (
                        <div className="flex items-center gap-1.5">
                          <AlertTriangle className="w-3.5 h-3.5 text-amber-500 flex-shrink-0" />
                          <span className="text-amber-700 font-semibold">
                            {inv.client_code || 'Unmatched'}
                          </span>
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-3 text-right font-bold text-slate-900">
                      {fmtCurrency(inv.amount)}
                    </td>
                    <td className="px-4 py-3 text-right text-slate-500">
                      {inv.hours_billed != null ? `${inv.hours_billed}h` : '—'}
                    </td>
                    <td className="px-4 py-3 text-center">
                      <span className="text-xs px-2 py-0.5 rounded-full bg-slate-100 text-slate-600 font-semibold">
                        {SOURCE_LABELS[inv.source] || inv.source}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-center">
                      <span className={cn(
                        'text-xs px-2.5 py-0.5 rounded-full font-bold',
                        STATUS_COLORS[inv.status ?? ''] || 'bg-slate-100 text-slate-600'
                      )}>
                        {inv.status ? inv.status.charAt(0).toUpperCase() + inv.status.slice(1) : 'Unknown'}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right">
                      <button
                        onClick={() => handleDelete(inv.id)}
                        disabled={deleting[inv.id]}
                        className="opacity-0 group-hover:opacity-100 transition-opacity p-1.5 text-slate-400 hover:text-red-500 hover:bg-red-50 rounded-lg"
                        title="Delete invoice"
                      >
                        {deleting[inv.id]
                          ? <Loader2 className="w-4 h-4 animate-spin" />
                          : <Trash2 className="w-4 h-4" />}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* CSV Import Modal */}
      {showImport && (
        <CsvImportModal
          clients={clients}
          onClose={() => setShowImport(false)}
          onImported={fetchAll}
        />
      )}
    </div>
  );
};

export default InvoiceManager;