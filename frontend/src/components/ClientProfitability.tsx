// src/components/ClientProfitability.tsx
// Realization Dashboard — restyled to match WeeklyTimesheet design system
// All original features preserved: Export modal, Import modal (CSV/QB/manual),
// Editable billed cell, Summary stat cards, Realization guide, Invoices tab

import React, { useState, useEffect, useCallback, useRef } from 'react';
import { safeFetchJson, safeUploadFile, API_BASE } from '@/lib/api';
import {
  TrendingUp, TrendingDown, Clock, DollarSign, Calendar,
  RefreshCw, Upload, AlertCircle, CheckCircle2, Target,
  FileSpreadsheet, Link2, X, Download, ExternalLink, Check,
  Square, CheckSquare, Loader2, Pencil, FileDown,
} from 'lucide-react';
import IntegrationStatusBanner from '@/components/IntegrationStatusBanner';
import { cn } from '@/lib/design-system';

// ── Types ─────────────────────────────────────────────────────────────────────

interface ClientRealization {
  client_id: number;
  client_name: string;
  client_code: string;
  billed_hours: number;
  billed_amount: number;
  worked_hours: number;
  variance_hours: number | null;
  realization: number | null;
  status: 'excellent' | 'good' | 'warning' | 'critical' | 'no_data';
}

interface RealizationSummary {
  period_start: string;
  period_end: string;
  clients: ClientRealization[];
  totals: {
    billed_hours: number;
    billed_amount: number;
    worked_hours: number;
    variance_hours: number;
    realization: number | null;
    status: string;
  };
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
  matched: boolean;
}

interface QBInvoice {
  id: string;
  doc_number: string;
  date: string;
  customer_name: string;
  customer_id: string;
  amount: number;
  hours: number | null;
  status: string;
  already_imported: boolean;
  client_matched: boolean;
  client_name: string | null;
}

interface DateRange { start: string; end: string }

interface Integration {
  id: number;
  provider: string;
  is_connected: boolean;
  company_name?: string;
}

// ── Utilities ─────────────────────────────────────────────────────────────────

const fmtCurrency = (n: number) =>
  new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 0, maximumFractionDigits: 0 }).format(n);

const fmtHours = (h: number): string => {
  if (h === 0) return '—';
  const hrs = Math.floor(h);
  const min = Math.round((h - hrs) * 60);
  if (hrs === 0) return `${min}m`;
  if (min === 0) return `${hrs}h`;
  return `${hrs}h ${min}m`;
};

const fmtPct = (v: number | null) => v === null ? '—' : `${v.toFixed(0)}%`;

const STATUS_CLS: Record<string, { text: string; badge: string; bar: string; bg: string }> = {
  excellent: { text: 'text-emerald-600', badge: 'bg-emerald-50 text-emerald-700 border-emerald-200', bar: 'bg-emerald-500', bg: 'bg-emerald-50 border-emerald-200' },
  good:      { text: 'text-primary',    badge: 'bg-primary/8 text-primary border-primary/20',       bar: 'bg-primary',     bg: 'bg-primary/5 border-primary/20'  },
  warning:   { text: 'text-amber-600',  badge: 'bg-amber-50 text-amber-700 border-amber-200',        bar: 'bg-amber-400',   bg: 'bg-amber-50 border-amber-200'    },
  critical:  { text: 'text-red-600',    badge: 'bg-red-50 text-red-600 border-red-200',              bar: 'bg-red-500',     bg: 'bg-red-50 border-red-200'        },
  no_data:   { text: 'text-slate-400',  badge: 'bg-slate-50 text-slate-400 border-border/50',        bar: 'bg-slate-200',   bg: 'bg-slate-50 border-border/50'    },
};

const STATUS_LABEL: Record<string, string> = {
  excellent: 'Excellent', good: 'On Target', warning: 'Over Budget', critical: 'Needs Review', no_data: 'No Data',
};

const calculateRealization = (billed: number, worked: number) => {
  if (worked <= 0 || billed <= 0) return { realization: null, variance: null, status: 'no_data' };
  const r = (billed / worked) * 100;
  return {
    realization: r,
    variance: billed - worked,
    status: r >= 125 ? 'excellent' : r >= 100 ? 'good' : r >= 85 ? 'warning' : 'critical',
  };
};

const getDefaultDates = (): DateRange => {
  const today = new Date();
  return {
    start: new Date(today.getFullYear(), today.getMonth(), 1).toISOString().split('T')[0],
    end:   new Date(today.getFullYear(), today.getMonth() + 1, 0).toISOString().split('T')[0],
  };
};

// ── Client avatar ─────────────────────────────────────────────────────────────

const AVATAR_COLORS = [
  'bg-blue-500','bg-emerald-500','bg-amber-500','bg-rose-500',
  'bg-violet-500','bg-cyan-500','bg-orange-500','bg-indigo-500',
];

const ClientAvatar: React.FC<{ name: string; code: string; status?: string }> = ({ name, code, status }) => {
  const label = (code || name || '??').slice(0, 2).toUpperCase();
  const statusBar = status ? STATUS_CLS[status]?.bar : undefined;
  const color = statusBar || AVATAR_COLORS[(name?.length ?? 0) % AVATAR_COLORS.length];
  return (
    <div className={cn('w-7 h-7 rounded-lg flex items-center justify-center text-white text-[10px] font-bold shrink-0', color)}>
      {label}
    </div>
  );
};

// ── Editable billed cell ──────────────────────────────────────────────────────

const EditableBilledCell: React.FC<{
  clientId: number;
  clientCode: string;
  billedHours: number;
  billedAmount: number;
  onSave: (id: number, hours: number, amount: number) => Promise<void>;
}> = ({ clientId, billedHours, billedAmount, onSave }) => {
  const [editing, setEditing] = useState(false);
  const [hours,   setHours]   = useState(billedHours.toString());
  const [amount,  setAmount]  = useState(billedAmount.toString());
  const [saving,  setSaving]  = useState(false);
  const hoursRef = useRef<HTMLInputElement>(null);

  useEffect(() => { if (editing) { hoursRef.current?.focus(); hoursRef.current?.select(); } }, [editing]);

  const handleSave = async () => {
    setSaving(true);
    try { await onSave(clientId, parseFloat(hours) || 0, parseFloat(amount) || 0); setEditing(false); }
    catch (err) { console.error('Failed to save:', err); }
    finally { setSaving(false); }
  };

  const handleCancel = () => { setHours(billedHours.toString()); setAmount(billedAmount.toString()); setEditing(false); };
  const onKey = (e: React.KeyboardEvent) => { if (e.key === 'Enter') handleSave(); if (e.key === 'Escape') handleCancel(); };

  if (editing) return (
    <div className="flex items-center gap-2 justify-end">
      <div className="space-y-1">
        <div className="flex items-center gap-1">
          <input ref={hoursRef} type="number" value={hours} onChange={e => setHours(e.target.value)} onKeyDown={onKey}
            className="w-14 px-1.5 py-1 text-xs border border-primary/40 rounded focus:outline-none focus:ring-2 focus:ring-primary/20 text-right tabular-nums" step="0.1" min="0" />
          <span className="text-xs text-slate-400">h</span>
        </div>
        <div className="flex items-center gap-1">
          <span className="text-xs text-slate-400">$</span>
          <input type="number" value={amount} onChange={e => setAmount(e.target.value)} onKeyDown={onKey}
            className="w-20 px-1.5 py-1 text-xs border border-border/50 rounded focus:outline-none focus:ring-2 focus:ring-primary/20 text-right tabular-nums" step="1" min="0" />
        </div>
      </div>
      <div className="flex flex-col gap-1">
        <button onClick={handleSave} disabled={saving} className="p-1 text-emerald-600 hover:bg-emerald-50 rounded transition-colors">
          {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
        </button>
        <button onClick={handleCancel} className="p-1 text-slate-300 hover:bg-slate-100 rounded transition-colors">
          <X className="w-3.5 h-3.5" />
        </button>
      </div>
    </div>
  );

  return (
    <div className="flex items-center justify-end gap-1.5 group">
      <div className="text-right">
        <p className="text-sm font-bold text-slate-700 tabular-nums leading-none">{fmtHours(billedHours)}</p>
        <p className="text-xs text-slate-400 tabular-nums mt-0.5">{fmtCurrency(billedAmount)}</p>
      </div>
      <button onClick={() => setEditing(true)}
        className="p-1 rounded text-slate-200 hover:text-primary hover:bg-primary/5 opacity-0 group-hover:opacity-100 transition-all"
        title="Edit billed hours/amount">
        <Pencil className="w-3 h-3" />
      </button>
    </div>
  );
};

// ── Export Modal ──────────────────────────────────────────────────────────────

const ExportModal: React.FC<{
  isOpen: boolean; onClose: () => void; data: RealizationSummary | null; dateRange: DateRange;
}> = ({ isOpen, onClose, data, dateRange }) => {
  const [exporting,   setExporting]   = useState(false);
  const [qbConnected, setQbConnected] = useState(false);

  useEffect(() => {
    if (isOpen) {
      safeFetchJson<any>(`${API_BASE}/integrations/status/`)
        .then(res => setQbConnected(res.integrations?.quickbooks?.connected || false))
        .catch(() => {});
    }
  }, [isOpen]);

  const download = (content: string, filename: string) => {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([content], { type: 'text/csv' }));
    a.download = filename;
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    onClose();
  };

  const exportReport = () => {
    if (!data) return;
    const headers = ['Client Code', 'Client Name', 'Worked Hours', 'Billed Hours', 'Billed Amount', 'Variance Hours', 'Realization %', 'Status'];
    const rows = data.clients.map(c => [c.client_code||'', c.client_name, c.worked_hours.toFixed(2), c.billed_hours.toFixed(2), c.billed_amount.toFixed(2), c.variance_hours?.toFixed(2)||'', c.realization?.toFixed(1)||'', c.status]);
    rows.push(['', 'TOTALS', data.totals.worked_hours.toFixed(2), data.totals.billed_hours.toFixed(2), data.totals.billed_amount.toFixed(2), data.totals.variance_hours.toFixed(2), data.totals.realization?.toFixed(1)||'', data.totals.status]);
    download([`# Realization Report: ${dateRange.start} to ${dateRange.end}`, headers.join(','), ...rows.map(r => r.map(v => `"${v}"`).join(','))].join('\n'), `realization-${dateRange.start}-to-${dateRange.end}.csv`);
  };

  const exportWorked = () => {
    if (!data) return;
    const rows = data.clients.map(c => [c.client_code||'', c.client_name, dateRange.start, dateRange.end, c.worked_hours.toFixed(2)]);
    download(['client_code,client_name,period_start,period_end,worked_hours', ...rows.map(r => r.map(v => `"${v}"`).join(','))].join('\n'), `worked-hours-${dateRange.start}-to-${dateRange.end}.csv`);
  };

  const syncQB = async () => {
    setExporting(true);
    try {
      await safeFetchJson(`${API_BASE}/integrations/quickbooks/push-time/`, {
        method: 'POST',
        body: JSON.stringify({ start_date: dateRange.start, end_date: dateRange.end }),
      });
      onClose();
    } catch (err) { console.error('Failed to sync to QuickBooks:', err); }
    finally { setExporting(false); }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-xl max-w-sm w-full overflow-hidden">
        <div className="px-6 py-4 border-b border-border/50 flex items-start justify-between">
          <div>
            <h3 className="text-base font-bold text-slate-800">Export Data</h3>
            <p className="text-xs text-slate-400 mt-0.5">Download or sync your data</p>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors">
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="p-4 space-y-2">
          {/* Export Worked Hours */}
          <button onClick={exportWorked}
            className="w-full flex items-center gap-3 p-3 rounded-xl border border-border/50 hover:border-emerald-300 hover:bg-emerald-50 transition-all text-left group">
            <div className="w-8 h-8 bg-emerald-50 rounded-lg flex items-center justify-center shrink-0 group-hover:bg-emerald-100 transition-colors">
              <Clock className="w-4 h-4 text-emerald-600" />
            </div>
            <div>
              <p className="text-sm font-semibold text-slate-700">Export Worked Hours</p>
              <p className="text-xs text-slate-400">CSV for import into QB/Xero</p>
            </div>
          </button>
          {/* Export Full Report */}
          <button onClick={exportReport}
            className="w-full flex items-center gap-3 p-3 rounded-xl border border-border/50 hover:border-primary/30 hover:bg-primary/5 transition-all text-left group">
            <div className="w-8 h-8 bg-primary/8 rounded-lg flex items-center justify-center shrink-0 group-hover:bg-primary/12 transition-colors">
              <FileSpreadsheet className="w-4 h-4 text-primary" />
            </div>
            <div>
              <p className="text-sm font-semibold text-slate-700">Export Full Report</p>
              <p className="text-xs text-slate-400">Billed vs Worked comparison</p>
            </div>
          </button>
          {/* Sync to QuickBooks */}
          <button onClick={syncQB} disabled={!qbConnected || exporting}
            className={cn('w-full flex items-center gap-3 p-3 rounded-xl border transition-all text-left group',
              qbConnected ? 'border-border/50 hover:border-emerald-300 hover:bg-emerald-50' : 'border-border/50 opacity-40 cursor-not-allowed')}>
            <div className={cn('w-8 h-8 rounded-lg flex items-center justify-center shrink-0 text-base', qbConnected ? 'bg-emerald-50 group-hover:bg-emerald-100' : 'bg-slate-100')}>📗</div>
            <div className="flex-1">
              <p className="text-sm font-semibold text-slate-700">Sync to QuickBooks</p>
              <p className="text-xs text-slate-400">{qbConnected ? 'Push time entries to QB' : 'Not connected'}</p>
            </div>
            {exporting && <Loader2 className="w-4 h-4 animate-spin text-emerald-600 ml-auto" />}
          </button>
          {/* Xero Coming Soon */}
          <button disabled
            className="w-full flex items-center gap-3 p-3 rounded-xl border border-border/50 opacity-40 cursor-not-allowed text-left">
            <div className="w-8 h-8 bg-slate-100 rounded-lg flex items-center justify-center shrink-0 text-base">📘</div>
            <div>
              <p className="text-sm font-semibold text-slate-700">Sync to Xero</p>
              <p className="text-xs text-slate-400">Coming Soon</p>
            </div>
          </button>
        </div>
        <div className="px-6 py-4 bg-slate-50/60 border-t border-border/50">
          <button onClick={onClose} className="w-full py-2 text-sm font-semibold text-slate-600 hover:bg-slate-200 rounded-lg transition-colors">Cancel</button>
        </div>
      </div>
    </div>
  );
};

// ── Import Modal ──────────────────────────────────────────────────────────────

type ImportSource = 'csv' | 'quickbooks' | 'manual';

const ImportModal: React.FC<{
  isOpen: boolean; onClose: () => void; onSuccess: () => void; dateRange: DateRange;
}> = ({ isOpen, onClose, onSuccess, dateRange }) => {
  const [source,      setSource]      = useState<ImportSource>('csv');
  const [uploading,   setUploading]   = useState(false);
  const [result,      setResult]      = useState<any>(null);
  const [error,       setError]       = useState<string | null>(null);
  const [qbConnected, setQbConnected] = useState(false);
  const [qbCompany,   setQbCompany]   = useState<string | null>(null);
  const [qbInvoices,  setQbInvoices]  = useState<QBInvoice[]>([]);
  const [qbLoading,   setQbLoading]   = useState(false);
  const [selected,    setSelected]    = useState<Set<string>>(new Set());
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (isOpen) {
      safeFetchJson<{ integrations: Integration[] }>(`${API_BASE}/integrations/status/`)
        .then(d => {
          const qb = d.integrations?.find(i => i.provider === 'quickbooks');
          if (qb?.is_connected) { setQbConnected(true); setQbCompany(qb.company_name || 'QuickBooks'); }
        }).catch(() => {});
    }
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) { setResult(null); setError(null); setUploading(false); setQbInvoices([]); setSelected(new Set()); setSource('csv'); }
  }, [isOpen]);

  const handleCSVUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true); setError(null); setResult(null);
    try {
      const data = await safeUploadFile<any>(`${API_BASE}/billing/invoices/import-csv/`, file, 'file');
      setResult(data);
      if (data.summary?.imported > 0) onSuccess();
    } catch (err: any) {
      let msg = 'Upload failed';
      if (err.message) {
        try { const match = err.message.match(/HTTP \d+: (.+)/); if (match) { const p = JSON.parse(match[1]); msg = p.error || p.message || msg; } else msg = err.message; }
        catch { msg = err.message; }
      }
      setError(msg);
    } finally { setUploading(false); }
  };

  const fetchQBInvoices = async () => {
    setQbLoading(true); setError(null);
    try {
      const params = new URLSearchParams({ start_date: dateRange.start, end_date: dateRange.end });
      const data = await safeFetchJson<{ invoices: QBInvoice[]; total: number }>(`${API_BASE}/integrations/quickbooks/invoices/?${params}`);
      setQbInvoices(data.invoices || []);
      setSelected(new Set(data.invoices?.filter(i => !i.already_imported).map(i => i.id) || []));
    } catch (err: any) { setError(err.message || 'Failed to fetch QuickBooks invoices'); }
    finally { setQbLoading(false); }
  };

  const handleQBImport = async () => {
    if (!selected.size) return;
    setUploading(true); setError(null);
    try {
      const data = await safeFetchJson<any>(`${API_BASE}/integrations/quickbooks/import/`, {
        method: 'POST', body: JSON.stringify({ invoice_ids: Array.from(selected) }),
      });
      setResult({ source: 'quickbooks', summary: { imported: data.imported?.length || 0, skipped: data.skipped?.length || 0, errors: data.errors?.length || 0 } });
      if (data.imported?.length > 0) onSuccess();
    } catch (err: any) { setError(err.message || 'Failed to import from QuickBooks'); }
    finally { setUploading(false); }
  };

  const toggleQBInvoice = (id: string) => { const s = new Set(selected); s.has(id) ? s.delete(id) : s.add(id); setSelected(s); };
  const toggleAllQB = () => {
    const importable = qbInvoices.filter(i => !i.already_imported);
    setSelected(selected.size === importable.length ? new Set() : new Set(importable.map(i => i.id)));
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-2xl max-h-[85vh] flex flex-col overflow-hidden">
        {/* Header */}
        <div className="px-6 py-4 border-b border-border/50 shrink-0">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h3 className="text-base font-bold text-slate-800">Import Billed Data</h3>
              <p className="text-xs text-slate-400 mt-0.5">CSV, QuickBooks, or enter manually</p>
            </div>
            <button onClick={onClose} className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors"><X className="w-4 h-4" /></button>
          </div>
          {!result && (
            <div className="flex gap-1 mt-3">
              {([
                { id: 'csv' as ImportSource,        label: 'CSV File',   icon: <FileSpreadsheet className="w-3.5 h-3.5" />, dot: false },
                { id: 'quickbooks' as ImportSource, label: 'QuickBooks', icon: <span className="text-sm leading-none">📗</span>, dot: qbConnected },
                { id: 'manual' as ImportSource,     label: 'Manual',     icon: <Pencil className="w-3.5 h-3.5" />, dot: false },
              ]).map(t => (
                <button key={t.id}
                  onClick={() => { setSource(t.id); if (t.id === 'quickbooks' && qbConnected && !qbInvoices.length) fetchQBInvoices(); }}
                  className={cn('flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg transition-colors',
                    source === t.id ? 'bg-primary text-white' : 'text-slate-500 hover:bg-slate-100')}>
                  {t.icon} {t.label}
                  {t.dot && <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 ml-0.5" />}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          {error && (
            <div className="flex items-start gap-2.5 px-4 py-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
              <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" /> {error}
            </div>
          )}

          {/* CSV */}
          {source === 'csv' && !result && (
            <div className="space-y-4">
              <div className="bg-slate-50 rounded-xl p-4 border border-border/50">
                <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2 flex items-center gap-1.5">
                  <FileSpreadsheet className="w-3.5 h-3.5" /> Expected CSV Format
                </p>
                <code className="text-xs text-slate-600 block bg-white p-3 rounded-lg border border-border/40 font-mono leading-relaxed">
                  client_code,invoice_number,invoice_date,amount,hours_billed<br/>
                  MAVOPS,INV-001,2026-02-01,1500.00,10<br/>
                  DAUPH,INV-002,2026-02-01,2000.00,15
                </code>
                <p className="text-xs text-slate-500 mt-2">
                  <strong>Required:</strong> client_code, invoice_number, invoice_date, amount &nbsp;·&nbsp;
                  <strong>Optional:</strong> hours_billed
                </p>
              </div>
              <div
                onDrop={e => { e.preventDefault(); e.dataTransfer.files[0] && handleCSVUpload({ target: { files: e.dataTransfer.files } } as any); }}
                onDragOver={e => e.preventDefault()}
                onClick={() => fileRef.current?.click()}
                className={cn('border-2 border-dashed rounded-xl p-10 text-center cursor-pointer transition-colors',
                  uploading ? 'border-primary/40 bg-primary/5' : 'border-border/60 hover:border-primary/40 hover:bg-primary/3')}>
                <input ref={fileRef} type="file" accept=".csv" className="hidden" onChange={handleCSVUpload} />
                {uploading ? <Loader2 className="w-8 h-8 text-primary animate-spin mx-auto mb-2" /> : <Upload className="w-8 h-8 text-slate-300 mx-auto mb-2" />}
                <p className="text-sm font-semibold text-slate-600">{uploading ? 'Uploading…' : 'Click to select CSV file'}</p>
                <p className="text-xs text-slate-400 mt-1">or drag and drop</p>
              </div>
            </div>
          )}

          {/* QuickBooks */}
          {source === 'quickbooks' && !result && (
            !qbConnected ? (
              <div className="text-center py-10">
                <div className="w-14 h-14 bg-emerald-50 rounded-full flex items-center justify-center mx-auto mb-4 border border-emerald-200 text-2xl">📗</div>
                <h4 className="font-semibold text-slate-800 mb-1">Connect QuickBooks</h4>
                <p className="text-sm text-slate-400 mb-4">Connect your QuickBooks account to import invoices automatically</p>
                <a href="/settings?tab=integrations" className="inline-flex items-center gap-1.5 px-4 py-2 bg-emerald-600 text-white text-sm font-semibold rounded-lg hover:bg-emerald-700 transition-colors">
                  <ExternalLink className="w-3.5 h-3.5" /> Go to Settings
                </a>
              </div>
            ) : qbLoading ? (
              <div className="flex items-center justify-center py-12"><Loader2 className="w-6 h-6 text-primary animate-spin" /></div>
            ) : qbInvoices.length === 0 ? (
              <div className="text-center py-10">
                <FileSpreadsheet className="w-10 h-10 text-slate-200 mx-auto mb-3" />
                <p className="font-medium text-slate-500">No invoices found</p>
                <p className="text-xs text-slate-400 mt-1">No invoices in QuickBooks for {dateRange.start} to {dateRange.end}</p>
                <button onClick={fetchQBInvoices} className="mt-3 text-xs text-primary hover:underline flex items-center gap-1 mx-auto">
                  <RefreshCw className="w-3 h-3" /> Refresh
                </button>
              </div>
            ) : (
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">{qbInvoices.length} invoices from {qbCompany}</span>
                    <button onClick={fetchQBInvoices} className="p-1 hover:bg-slate-100 rounded transition-colors"><RefreshCw className="w-3.5 h-3.5 text-slate-400" /></button>
                  </div>
                  <button onClick={toggleAllQB} className="text-xs text-primary hover:underline font-medium">
                    {selected.size === qbInvoices.filter(i => !i.already_imported).length ? 'Deselect All' : 'Select All'}
                  </button>
                </div>
                <div className="border border-border/60 rounded-xl overflow-hidden max-h-64 overflow-y-auto">
                  <table className="w-full text-sm border-collapse">
                    <thead className="sticky top-0 bg-slate-50">
                      <tr className="border-b border-border/50">
                        <th className="w-10 px-3 py-2.5" />
                        {['Invoice', 'Customer', 'Amount', 'Status'].map(h => (
                          <th key={h} className="text-left px-3 py-2.5 text-xs font-semibold uppercase tracking-wider text-slate-400">{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border/30">
                      {qbInvoices.map(inv => (
                        <tr key={inv.id} className={cn('hover:bg-slate-50/50', inv.already_imported && 'opacity-50')}>
                          <td className="px-3 py-2.5">
                            {inv.already_imported
                              ? <CheckCircle2 className="w-4 h-4 text-emerald-500" />
                              : <button onClick={() => toggleQBInvoice(inv.id)} className="focus:outline-none">
                                  {selected.has(inv.id) ? <CheckSquare className="w-4 h-4 text-primary" /> : <Square className="w-4 h-4 text-slate-300" />}
                                </button>
                            }
                          </td>
                          <td className="px-3 py-2.5">
                            <p className="font-mono font-semibold text-slate-700 text-xs">{inv.doc_number}</p>
                            <p className="text-[10px] text-slate-400 tabular-nums">{inv.date}</p>
                          </td>
                          <td className="px-3 py-2.5">
                            <p className="text-sm text-slate-600">{inv.customer_name}</p>
                            {inv.client_matched && <p className="text-[10px] text-emerald-600 flex items-center gap-0.5"><Check className="w-2.5 h-2.5" /> Matched</p>}
                          </td>
                          <td className="px-3 py-2.5 font-semibold text-slate-800 tabular-nums text-sm">{fmtCurrency(inv.amount)}</td>
                          <td className="px-3 py-2.5">
                            {inv.already_imported
                              ? <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-slate-100 text-slate-400">Imported</span>
                              : <span className={cn('text-[10px] font-semibold px-2 py-0.5 rounded-full border', inv.status === 'Paid' ? 'bg-emerald-50 text-emerald-700 border-emerald-200' : 'bg-amber-50 text-amber-700 border-amber-200')}>{inv.status}</span>
                            }
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {selected.size > 0 && (
                  <button onClick={handleQBImport} disabled={uploading}
                    className="w-full py-2.5 bg-emerald-600 text-white text-sm font-semibold rounded-lg hover:bg-emerald-700 disabled:opacity-50 flex items-center justify-center gap-2 transition-all">
                    {uploading ? <><Loader2 className="w-4 h-4 animate-spin" /> Importing…</> : <><Download className="w-4 h-4" /> Import {selected.size} Invoice{selected.size !== 1 ? 's' : ''}</>}
                  </button>
                )}
              </div>
            )
          )}

          {/* Manual */}
          {source === 'manual' && !result && (
            <div className="text-center py-10">
              <div className="w-14 h-14 bg-primary/8 rounded-full flex items-center justify-center mx-auto mb-4 border border-primary/20">
                <Pencil className="w-6 h-6 text-primary" />
              </div>
              <h4 className="font-semibold text-slate-800 mb-1">Manual Entry Mode</h4>
              <p className="text-sm text-slate-400 mb-4">
                Close this modal and click the <Pencil className="w-3.5 h-3.5 inline mx-0.5" /> icon next to any client's Billed column to edit directly in the table.
              </p>
              <button onClick={onClose} className="px-5 py-2 bg-primary text-white text-sm font-semibold rounded-lg hover:opacity-90 transition-all">Got it, let me edit</button>
            </div>
          )}

          {/* Result */}
          {result && (
            <div className="text-center py-8">
              <div className="w-14 h-14 bg-emerald-50 rounded-full flex items-center justify-center mx-auto mb-4 border border-emerald-200">
                <CheckCircle2 className="w-7 h-7 text-emerald-500" />
              </div>
              <h4 className="font-bold text-slate-800 mb-4">Import Complete</h4>
              <div className="flex justify-center gap-8">
                {[
                  { label: 'Imported',  val: result.summary?.imported || 0,  cls: 'text-emerald-600' },
                  { label: 'Skipped',   val: result.summary?.skipped  || 0,  cls: 'text-slate-400'   },
                  { label: result.source === 'quickbooks' ? 'Errors' : 'Unmatched', val: result.summary?.unmatched_clients || result.summary?.errors || 0, cls: 'text-amber-600' },
                ].map(({ label, val, cls }) => (
                  <div key={label} className="text-center">
                    <p className={cn('text-2xl font-bold tabular-nums', cls)}>{val}</p>
                    <p className="text-xs text-slate-400 mt-0.5">{label}</p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 bg-slate-50/60 border-t border-border/50 flex justify-end shrink-0">
          <button onClick={onClose} className="px-4 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-200 rounded-lg transition-colors">
            {result ? 'Done' : 'Cancel'}
          </button>
        </div>
      </div>
    </div>
  );
};

// ── Main Component ────────────────────────────────────────────────────────────

const ClientProfitability: React.FC = () => {
  const [loading,    setLoading]    = useState(true);
  const [error,      setError]      = useState<string | null>(null);
  const [data,       setData]       = useState<RealizationSummary | null>(null);
  const [invoices,   setInvoices]   = useState<Invoice[]>([]);
  const [showImport, setShowImport] = useState(false);
  const [showExport, setShowExport] = useState(false);
  const [activeTab,  setActiveTab]  = useState<'realization' | 'invoices'>('realization');
  const [dateRange,  setDateRange]  = useState<DateRange>(getDefaultDates);
  const [localStart, setLocalStart] = useState(getDefaultDates().start);
  const [localEnd,   setLocalEnd]   = useState(getDefaultDates().end);

  const fetchData = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const params = new URLSearchParams({ start_date: dateRange.start, end_date: dateRange.end });
      setData(await safeFetchJson<RealizationSummary>(`${API_BASE}/billing/realization/?${params}`));
    } catch (e) { setError(e instanceof Error ? e.message : 'Failed to load data'); }
    finally { setLoading(false); }
  }, [dateRange]);

  const fetchInvoices = useCallback(async () => {
    try {
      const params = new URLSearchParams({ start_date: dateRange.start, end_date: dateRange.end });
      const r = await safeFetchJson<{ invoices: Invoice[] }>(`${API_BASE}/billing/invoices/?${params}`);
      setInvoices(r.invoices || []);
    } catch (err) { console.error('Failed to load invoices:', err); }
  }, [dateRange]);

  useEffect(() => { fetchData(); fetchInvoices(); }, [fetchData, fetchInvoices]);

  const applyDates = () => setDateRange({ start: localStart, end: localEnd });

  const setPreset = (p: string) => {
    const today = new Date();
    let s: Date, e: Date;
    switch (p) {
      case 'lastMonth':   s = new Date(today.getFullYear(), today.getMonth()-1, 1); e = new Date(today.getFullYear(), today.getMonth(), 0); break;
      case 'thisQuarter': { const q = Math.floor(today.getMonth()/3); s = new Date(today.getFullYear(), q*3, 1); e = new Date(today.getFullYear(), q*3+3, 0); break; }
      case 'thisYear':    s = new Date(today.getFullYear(), 0, 1); e = new Date(today.getFullYear(), 11, 31); break;
      default:            s = new Date(today.getFullYear(), today.getMonth(), 1); e = new Date(today.getFullYear(), today.getMonth()+1, 0);
    }
    const start = s.toISOString().split('T')[0]; const end = e.toISOString().split('T')[0];
    setLocalStart(start); setLocalEnd(end); setDateRange({ start, end });
  };

  const handleSaveBilled = async (clientId: number, hours: number, amount: number) => {
    await safeFetchJson(`${API_BASE}/billing/clients/update-billed/`, {
      method: 'POST',
      body: JSON.stringify({ client_id: clientId, period_start: dateRange.start, period_end: dateRange.end, billed_hours: hours, billed_amount: amount }),
    });
    if (data) {
      const clients = data.clients.map(c => {
        if (c.client_id !== clientId) return c;
        const calc = calculateRealization(hours, c.worked_hours);
        return { ...c, billed_hours: hours, billed_amount: amount, variance_hours: calc.variance, realization: calc.realization, status: calc.status as any };
      });
      const bH = clients.reduce((s,c) => s+c.billed_hours, 0);
      const wH = clients.reduce((s,c) => s+c.worked_hours, 0);
      const calc = calculateRealization(bH, wH);
      setData({ ...data, clients, totals: { ...data.totals, billed_hours: bH, billed_amount: clients.reduce((s,c)=>s+c.billed_amount,0), worked_hours: wH, variance_hours: calc.variance||0, realization: calc.realization, status: calc.status } });
    }
  };

  const totals = data?.totals;

  if (loading && !data) return (
    <div className="flex items-center justify-center min-h-[300px]">
      <RefreshCw className="w-5 h-5 text-slate-300 animate-spin" />
    </div>
  );

  return (
    <div className="flex flex-col h-[calc(100vh-56px-48px-32px)] min-h-0 space-y-2">

      {/* ── ROW 1: Title / Stats / Actions ──────────────────────────── */}
      <div className="bg-white rounded-xl border border-border/60 px-5 h-14 flex items-center justify-between gap-4 shrink-0">
        <div className="flex items-center gap-3 shrink-0">
          <h2 className="text-base font-bold text-slate-800">Realization</h2>
          {totals && (
            <span className={cn('inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-semibold border', STATUS_CLS[totals.status]?.badge || STATUS_CLS.no_data.badge)}>
              {totals.realization !== null ? `${totals.realization.toFixed(0)}%` : 'No data'}
            </span>
          )}
        </div>
        <div className="flex items-center gap-4">
          {totals && (
            <div className="flex items-center gap-5 pr-4 border-r border-border/50">
              <div className="text-right">
                <p className="text-sm font-bold tabular-nums text-primary leading-none">{fmtHours(totals.billed_hours)}</p>
                <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-400 mt-0.5">Billed</p>
              </div>
              <div className="text-right">
                <p className="text-sm font-bold tabular-nums text-slate-500 leading-none">{fmtHours(totals.worked_hours)}</p>
                <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-400 mt-0.5">Worked</p>
              </div>
              <div className="text-right">
                <p className={cn('text-sm font-bold tabular-nums leading-none', (totals.variance_hours ?? 0) >= 0 ? 'text-emerald-600' : 'text-red-500')}>
                  {(totals.variance_hours ?? 0) >= 0 ? '+' : ''}{fmtHours(Math.abs(totals.variance_hours ?? 0))}
                </p>
                <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-400 mt-0.5">Variance</p>
              </div>
              <div className="text-right">
                <p className="text-sm font-bold tabular-nums text-emerald-600 leading-none">{fmtCurrency(totals.billed_amount)}</p>
                <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-400 mt-0.5">Billed $</p>
              </div>
            </div>
          )}
          <div className="flex items-center gap-2">
            <button onClick={() => setShowExport(true)} className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-slate-600 bg-slate-50 hover:bg-slate-100 border border-border/60 rounded-lg transition-colors">
              <FileDown className="w-3.5 h-3.5" /> Export
            </button>
            <button onClick={() => setShowImport(true)} className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold bg-primary text-white rounded-lg hover:opacity-90 transition-all">
              <Upload className="w-3.5 h-3.5" /> Import
            </button>
            <button onClick={() => { fetchData(); fetchInvoices(); }} className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors" title="Refresh">
              <RefreshCw className={cn('w-4 h-4', loading && 'animate-spin')} />
            </button>
          </div>
        </div>
      </div>

      {/* ── ROW 2: Date / Presets / Tabs ─────────────────────────────── */}
      <div className="bg-white rounded-xl border border-border/60 px-4 h-11 flex items-center gap-3 shrink-0">
        <Calendar className="w-3.5 h-3.5 text-slate-400 shrink-0" />
        <input type="date" value={localStart} onChange={e => setLocalStart(e.target.value)}
          className="text-xs px-2 py-1 bg-slate-50 border border-border/50 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/20 tabular-nums" />
        <span className="text-slate-300 text-xs">–</span>
        <input type="date" value={localEnd} onChange={e => setLocalEnd(e.target.value)}
          className="text-xs px-2 py-1 bg-slate-50 border border-border/50 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/20 tabular-nums" />
        <button onClick={applyDates} className="px-2.5 py-1 text-xs font-semibold bg-primary text-white rounded-lg hover:opacity-90 transition-all">Apply</button>
        <div className="flex items-center gap-1 pl-1 border-l border-border/40">
          {[['thisMonth','This Mo.'],['lastMonth','Last Mo.'],['thisQuarter','Quarter'],['thisYear','Year']].map(([p, l]) => (
            <button key={p} onClick={() => setPreset(p)} className="px-2.5 py-1 text-xs font-semibold text-slate-500 hover:bg-slate-100 rounded-lg transition-colors">{l}</button>
          ))}
        </div>
        <div className="flex items-center gap-1 pl-1 border-l border-border/40 ml-auto">
          {[
            { id: 'realization', label: 'Realization',            icon: <Target className="w-3 h-3" /> },
            { id: 'invoices',    label: `Invoices (${invoices.length})`, icon: <FileSpreadsheet className="w-3 h-3" /> },
          ].map(tab => (
            <button key={tab.id} onClick={() => setActiveTab(tab.id as any)}
              className={cn('flex items-center gap-1.5 px-2.5 py-1 text-xs font-semibold rounded-lg transition-colors',
                activeTab === tab.id ? 'bg-primary text-white' : 'text-slate-500 hover:bg-slate-100')}>
              {tab.icon} {tab.label}
            </button>
          ))}
        </div>
      </div>

      {/* ── Error ─────────────────────────────────────────────────────── */}
      {error && (
        <div className="flex items-start gap-3 px-4 py-3 rounded-lg border bg-red-50 border-red-200 text-sm shrink-0">
          <AlertCircle className="w-4 h-4 mt-0.5 text-red-500 shrink-0" /><span className="text-red-700">{error}</span>
        </div>
      )}

      {/* ── Integration banner ─────────────────────────────────────────── */}
      <div className="shrink-0">
        <IntegrationStatusBanner context="profitability" onDataRefresh={() => { fetchData(); fetchInvoices(); }} />
      </div>

      {/* ── Realization Tab ───────────────────────────────────────────── */}
      {activeTab === 'realization' && (
        <>
          {/* Summary stat cards */}
          {data && (
            <div className="grid grid-cols-4 gap-3 shrink-0">
              <div className="bg-white border border-border/60 rounded-xl p-4">
                <div className="flex items-center gap-1.5 text-slate-400 text-xs mb-1.5"><DollarSign className="w-3.5 h-3.5" /> Billed (Budget)</div>
                <p className="text-2xl font-bold text-slate-800">{fmtHours(data.totals.billed_hours)}</p>
                <p className="text-xs text-slate-400 mt-0.5">{fmtCurrency(data.totals.billed_amount)} invoiced</p>
              </div>
              <div className="bg-white border border-border/60 rounded-xl p-4">
                <div className="flex items-center gap-1.5 text-slate-400 text-xs mb-1.5"><Clock className="w-3.5 h-3.5" /> Worked (Actual)</div>
                <p className="text-2xl font-bold text-slate-800">{fmtHours(data.totals.worked_hours)}</p>
                <p className="text-xs text-slate-400 mt-0.5">Billable time tracked</p>
              </div>
              <div className="bg-white border border-border/60 rounded-xl p-4">
                <div className="flex items-center gap-1.5 text-slate-400 text-xs mb-1.5">
                  {(data.totals.variance_hours ?? 0) >= 0 ? <TrendingUp className="w-3.5 h-3.5 text-emerald-500" /> : <TrendingDown className="w-3.5 h-3.5 text-red-500" />}
                  Variance
                </div>
                <p className={cn('text-2xl font-bold', (data.totals.variance_hours ?? 0) >= 0 ? 'text-emerald-600' : 'text-red-600')}>
                  {(data.totals.variance_hours ?? 0) >= 0 ? '+' : ''}{fmtHours(Math.abs(data.totals.variance_hours ?? 0))}
                </p>
                <p className="text-xs text-slate-400 mt-0.5">{(data.totals.variance_hours ?? 0) >= 0 ? 'Under budget' : 'Over budget'}</p>
              </div>
              <div className={cn('rounded-xl p-4 border', STATUS_CLS[data.totals.status]?.bg || STATUS_CLS.no_data.bg)}>
                <div className="flex items-center gap-1.5 text-slate-500 text-xs mb-1.5"><Target className="w-3.5 h-3.5" /> Realization</div>
                <p className={cn('text-2xl font-bold', STATUS_CLS[data.totals.status]?.text || STATUS_CLS.no_data.text)}>{fmtPct(data.totals.realization)}</p>
                <p className={cn('text-xs mt-0.5', STATUS_CLS[data.totals.status]?.text || STATUS_CLS.no_data.text)}>{STATUS_LABEL[data.totals.status] || 'No Data'}</p>
              </div>
            </div>
          )}

          {/* Edit hint */}
          <div className="bg-primary/5 border border-primary/15 rounded-xl px-4 py-2.5 flex items-center gap-2.5 shrink-0">
            <Pencil className="w-3.5 h-3.5 text-primary shrink-0" />
            <p className="text-xs text-primary/80"><strong>Tip:</strong> Hover over any client's Billed column and click the pencil icon to edit hours and amounts directly.</p>
          </div>

          {/* Client table */}
          <div className="bg-white rounded-xl border border-border/60 overflow-hidden flex flex-col flex-1 min-h-0">
            <div className="overflow-auto flex-1">
              <table className="w-full border-collapse text-sm" style={{ minWidth: 680 }}>
                <thead className="sticky top-0 z-20">
                  <tr className="border-b border-border/60 bg-white">
                    <th className="sticky left-0 z-20 text-left px-4 py-3 font-semibold text-slate-500 text-xs uppercase tracking-wider bg-slate-50 min-w-[200px] shadow-[2px_0_4px_-2px_rgba(0,0,0,0.06)]">Client</th>
                    <th className="text-right px-4 py-3 font-semibold text-slate-500 text-xs uppercase tracking-wider bg-slate-50 whitespace-nowrap">
                      <span className="flex items-center justify-end gap-1">Billed <Pencil className="w-2.5 h-2.5 text-slate-300" /></span>
                    </th>
                    <th className="text-right px-4 py-3 font-semibold text-slate-500 text-xs uppercase tracking-wider bg-slate-50">Worked</th>
                    <th className="text-right px-4 py-3 font-semibold text-slate-500 text-xs uppercase tracking-wider bg-slate-50">Variance</th>
                    <th className="text-right px-4 py-3 font-semibold text-slate-500 text-xs uppercase tracking-wider bg-slate-50">Realization</th>
                    <th className="text-center px-4 py-3 font-semibold text-slate-500 text-xs uppercase tracking-wider bg-slate-50">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/30">
                  {!data?.clients.length ? (
                    <tr><td colSpan={6} className="text-center py-16 text-slate-400">
                      <Target className="w-10 h-10 text-slate-200 mx-auto mb-3" />
                      <p className="font-medium text-slate-500">No data for this period</p>
                      <p className="text-sm mt-1">Import invoices or enter billed hours manually</p>
                      <button onClick={() => setShowImport(true)} className="mt-3 px-4 py-2 bg-primary text-white text-xs font-semibold rounded-lg hover:opacity-90 transition-all">Import Billed Data</button>
                    </td></tr>
                  ) : data.clients.map(client => {
                    const scls = STATUS_CLS[client.status] || STATUS_CLS.no_data;
                    return (
                      <tr key={client.client_id} className="hover:bg-slate-50/50 transition-colors">
                        <td className="sticky left-0 z-10 px-4 py-3 bg-white shadow-[2px_0_4px_-2px_rgba(0,0,0,0.06)]">
                          <div className="flex items-center gap-2.5">
                            <ClientAvatar name={client.client_name} code={client.client_code} status={client.status} />
                            <div>
                              <p className="font-semibold text-slate-800 text-sm leading-tight">{client.client_name}</p>
                              {client.client_code && <p className="text-xs text-slate-400">{client.client_code}</p>}
                            </div>
                          </div>
                        </td>
                        <td className="px-4 py-3">
                          <EditableBilledCell clientId={client.client_id} clientCode={client.client_code} billedHours={client.billed_hours} billedAmount={client.billed_amount} onSave={handleSaveBilled} />
                        </td>
                        <td className="px-4 py-3 text-right tabular-nums">
                          <p className="text-sm font-bold text-slate-600 leading-none">{fmtHours(client.worked_hours)}</p>
                        </td>
                        <td className="px-4 py-3 text-right tabular-nums">
                          {client.variance_hours !== null
                            ? <span className={cn('text-sm font-bold', client.variance_hours >= 0 ? 'text-emerald-600' : 'text-red-500')}>
                                {client.variance_hours >= 0 ? '+' : ''}{fmtHours(Math.abs(client.variance_hours))}
                              </span>
                            : <span className="text-slate-300">—</span>}
                        </td>
                        <td className="px-4 py-3 text-right tabular-nums">
                          <span className={cn('text-lg font-bold', scls.text)}>{fmtPct(client.realization)}</span>
                        </td>
                        <td className="px-4 py-3 text-center">
                          <span className={cn('inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-semibold border', scls.badge)}>
                            {client.realization !== null && (client.realization >= 100 ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />)}
                            {STATUS_LABEL[client.status]}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <div className="px-5 py-3 border-t border-border/50 flex items-center justify-between bg-slate-50/40 shrink-0">
              <p className="text-xs text-slate-400 flex items-center gap-1.5">
                <Pencil className="w-3 h-3" /> Hover a row's Billed column to edit hours and amount directly
              </p>
              <div className="flex items-center gap-3 text-[10px] text-slate-400">
                {[['bg-emerald-400','≥125%'],['bg-primary','100–124%'],['bg-amber-400','85–99%'],['bg-red-400','<85%']].map(([bg,label]) => (
                  <span key={label} className="flex items-center gap-1"><span className={cn('w-2 h-2 rounded-full inline-block', bg)} />{label}</span>
                ))}
              </div>
            </div>
          </div>

          {/* Realization guide */}
          <div className="bg-white border border-border/60 rounded-xl p-5 shrink-0">
            <h4 className="text-sm font-semibold text-slate-700 mb-3">Understanding Realization</h4>
            <div className="grid grid-cols-2 gap-6 text-sm">
              <div>
                <p className="text-slate-600 mb-2"><strong>Realization</strong> = Billed Hours ÷ Worked Hours × 100</p>
                <div className="space-y-1.5">
                  {[
                    ['bg-emerald-500', '125%+',    'Excellent! Very efficient'],
                    ['bg-primary',     '100–125%', 'On target or under budget'],
                    ['bg-amber-500',   '85–100%',  'Slightly over budget'],
                    ['bg-red-500',     '<85%',     'Significantly over, needs review'],
                  ].map(([bg, pct, label]) => (
                    <div key={pct} className="flex items-center gap-2">
                      <div className={cn('w-2.5 h-2.5 rounded-full shrink-0', bg)} />
                      <span className="text-slate-600"><strong>{pct}</strong> — {label}</span>
                    </div>
                  ))}
                </div>
              </div>
              <div className="border-l border-border/40 pl-6">
                <p className="text-slate-600 mb-2"><strong>Example:</strong></p>
                <div className="space-y-2 text-slate-600 text-xs">
                  <p>• Billed 10h, Worked 8h → <span className="text-emerald-600 font-semibold">125% ✓</span> (efficient!)</p>
                  <p>• Billed 10h, Worked 10h → <span className="text-primary font-semibold">100%</span> (break even)</p>
                  <p>• Billed 10h, Worked 12h → <span className="text-red-600 font-semibold">83%</span> (over budget)</p>
                </div>
              </div>
            </div>
          </div>
        </>
      )}

      {/* ── Invoices Tab ──────────────────────────────────────────────── */}
      {activeTab === 'invoices' && (
        <div className="bg-white rounded-xl border border-border/60 overflow-hidden flex flex-col flex-1 min-h-0">
          <div className="overflow-auto flex-1">
            <table className="w-full border-collapse text-sm" style={{ minWidth: 560 }}>
              <thead className="sticky top-0 z-20">
                <tr className="border-b border-border/60 bg-white">
                  {['Invoice #', 'Date', 'Client', 'Amount', 'Hours', 'Matched'].map(h => (
                    <th key={h} className={cn('px-4 py-3 font-semibold text-slate-500 text-xs uppercase tracking-wider bg-slate-50',
                      h === 'Amount' || h === 'Hours' ? 'text-right' : h === 'Matched' ? 'text-center' : 'text-left')}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-border/30">
                {invoices.length === 0 ? (
                  <tr><td colSpan={6} className="text-center py-16 text-slate-400">
                    <FileSpreadsheet className="w-10 h-10 text-slate-200 mx-auto mb-3" />
                    <p className="font-medium text-slate-500">No invoices imported yet</p>
                    <p className="text-sm mt-1">Import from CSV, QuickBooks, or enter manually</p>
                    <button onClick={() => setShowImport(true)} className="mt-3 px-4 py-2 bg-primary text-white text-xs font-semibold rounded-lg hover:opacity-90 transition-all">Import Invoices</button>
                  </td></tr>
                ) : invoices.map(inv => (
                  <tr key={inv.id} className="hover:bg-slate-50/50 transition-colors">
                    <td className="px-4 py-3 font-mono font-bold text-slate-800 text-xs">{inv.invoice_number}</td>
                    <td className="px-4 py-3 text-slate-500 text-xs tabular-nums">{inv.invoice_date}</td>
                    <td className="px-4 py-3">
                      <p className="text-sm font-medium text-slate-700">{inv.client_name}</p>
                      {inv.client_code && <p className="text-xs text-slate-400">{inv.client_code}</p>}
                    </td>
                    <td className="px-4 py-3 text-right font-bold text-slate-800 tabular-nums">{fmtCurrency(inv.amount)}</td>
                    <td className="px-4 py-3 text-right text-slate-400 tabular-nums text-xs">{inv.hours_billed ? fmtHours(inv.hours_billed) : '—'}</td>
                    <td className="px-4 py-3 text-center">
                      {inv.matched
                        ? <CheckCircle2 className="w-4 h-4 text-emerald-500 mx-auto" />
                        : <span className="inline-flex items-center gap-1 text-amber-600 text-xs font-semibold">
                            <Link2 className="w-3.5 h-3.5" /> Match
                          </span>
                      }
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="px-5 py-3 border-t border-border/50 bg-slate-50/40 shrink-0">
            <p className="text-xs text-slate-400">{invoices.length} invoice{invoices.length !== 1 ? 's' : ''} · {invoices.filter(i=>i.matched).length} matched</p>
          </div>
        </div>
      )}

      <ImportModal isOpen={showImport} onClose={() => setShowImport(false)} onSuccess={() => { fetchData(); fetchInvoices(); }} dateRange={dateRange} />
      <ExportModal isOpen={showExport} onClose={() => setShowExport(false)} data={data} dateRange={dateRange} />
    </div>
  );
};

export default ClientProfitability;