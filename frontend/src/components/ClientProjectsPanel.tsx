// A client's projects, for firms that work Client → Project (agencies).
//
// Kept deliberately small: add, rename, archive. Archive rather than delete,
// because a project with time on it is part of the record — the server only
// hard-deletes one that never collected an hour. The hours column is what makes
// "is this safe to archive?" answerable without leaving the page.
//
// The bulk path is ImportProjectsModal below: a two-column client,project list,
// previewed before anything is written, which is how an agency's existing list
// (Asana, QuickBooks Time, a spreadsheet) arrives on day one.

import { useCallback, useEffect, useState } from 'react';
import { Archive, Check, Loader2, Pencil, Plus, RotateCcw, Upload, X } from 'lucide-react';
import { safeFetchJson, API_BASE } from '@/lib/api';
import { cn } from '@/lib/design-system';
import { useTerminology } from '@/lib/terminology';

type ProjectRow = {
  id: number; name: string; client_id: number; is_active: boolean; hours?: number;
  /** 'local', or the integration it mirrors ('qb_time', 'clio'). */
  source?: string;
  estimated_hours?: number | null;
};

const SOURCE_LABEL: Record<string, string> = { qb_time: 'QB Time', clio: 'Clio' };

export function ClientProjectsPanel({ clientId, canManage, onChanged, onError }: {
  clientId: number;
  canManage: boolean;
  onChanged?: () => void;
  onError: (msg: string) => void;
}) {
  const terms = useTerminology();
  const word = terms.project.toLowerCase();
  const [rows, setRows] = useState<ProjectRow[] | null>(null);
  const [newName, setNewName] = useState('');
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<number | null>(null);
  const [editName, setEditName] = useState('');
  const [showArchived, setShowArchived] = useState(false);

  const load = useCallback(async () => {
    try {
      setRows(await safeFetchJson(`${API_BASE}/projects/?client_id=${clientId}&include_archived=1`));
    } catch (e: any) {
      setRows([]);
      onError(e?.message || `Could not load ${terms.projects.toLowerCase()}`);
    }
  }, [clientId, onError, terms.projects]);

  useEffect(() => { load(); }, [load]);

  const add = async () => {
    const name = newName.trim();
    if (!name) return;
    setBusy(true);
    try {
      await safeFetchJson(`${API_BASE}/projects/create/`, {
        method: 'POST', body: JSON.stringify({ client_id: clientId, name }),
      });
      setNewName('');
      await load();
      onChanged?.();
    } catch (e: any) { onError(e?.message || `Could not add the ${word}`); }
    finally { setBusy(false); }
  };

  const update = async (id: number, body: Partial<ProjectRow>) => {
    setBusy(true);
    try {
      await safeFetchJson(`${API_BASE}/projects/${id}/`, { method: 'PUT', body: JSON.stringify(body) });
      setEditing(null);
      await load();
      onChanged?.();
    } catch (e: any) { onError(e?.message || `Could not update the ${word}`); }
    finally { setBusy(false); }
  };

  if (rows === null) {
    return <div className="flex items-center gap-2 py-6 text-sm text-slate-400"><Loader2 className="h-4 w-4 animate-spin" /> Loading…</div>;
  }

  const active = rows.filter((r) => r.is_active);
  const archived = rows.filter((r) => !r.is_active);
  const visible = showArchived ? rows : active;

  return (
    <div className="flex flex-col gap-3">
      {canManage && (
        <form onSubmit={(e) => { e.preventDefault(); add(); }} className="flex items-center gap-2">
          <input
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder={`New ${word} name`}
            maxLength={200}
            className="min-w-0 flex-1 rounded-lg border border-border/60 px-3 py-2 text-sm focus:border-primary focus:outline-none"
          />
          <button type="submit" disabled={busy || !newName.trim()}
            className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-40">
            <Plus className="h-3.5 w-3.5" /> Add
          </button>
        </form>
      )}

      {visible.length === 0 ? (
        <p className="py-4 text-sm text-slate-400">
          No {terms.projects.toLowerCase()} yet. Time for this client lands in “Needs a {word}” in Daily Review until it has one.
        </p>
      ) : (
        <div className="divide-y divide-border/40 rounded-xl border border-border/60">
          {visible.map((p) => (
            <div key={p.id} className={cn('flex items-center gap-2 px-3 py-2', !p.is_active && 'opacity-60')}>
              {editing === p.id ? (
                <form className="flex min-w-0 flex-1 items-center gap-1.5"
                  onSubmit={(e) => { e.preventDefault(); if (editName.trim()) update(p.id, { name: editName.trim() }); }}>
                  <input autoFocus value={editName} onChange={(e) => setEditName(e.target.value)} maxLength={200}
                    className="min-w-0 flex-1 rounded border border-border/60 px-2 py-1 text-sm focus:border-primary focus:outline-none" />
                  <button type="submit" className="p-1 text-primary"><Check className="h-4 w-4" /></button>
                  <button type="button" onClick={() => setEditing(null)} className="p-1 text-slate-400"><X className="h-4 w-4" /></button>
                </form>
              ) : (
                <span className="min-w-0 flex-1 truncate text-sm font-medium text-slate-800">{p.name}</span>
              )}
              {p.source && p.source !== 'local' && (
                <span className="shrink-0 rounded-full bg-teal-50 px-2 py-0.5 text-[10px] font-semibold text-teal-700"
                  title={`Kept in ${SOURCE_LABEL[p.source] || p.source} — rename or close it there`}>
                  {SOURCE_LABEL[p.source] || p.source}
                </span>
              )}
              <span className={cn('shrink-0 font-mono text-xs tabular-nums',
                  p.estimated_hours != null && (p.hours ?? 0) > p.estimated_hours
                    ? 'font-semibold text-amber-600' : 'text-slate-400')}
                title={p.estimated_hours != null ? 'Tracked of estimated hours' : 'Tracked hours'}>
                {(p.hours ?? 0).toFixed(1)}{p.estimated_hours != null ? ` / ${p.estimated_hours.toFixed(1)}` : ''}h
              </span>
              {!p.is_active && <span className="shrink-0 rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-semibold text-slate-500">Archived</span>}
              {/* A synced project's name and status belong to its source;
                  edited here, the next hourly sync would quietly put them back. */}
              {canManage && editing !== p.id && (!p.source || p.source === 'local') && (
                <>
                  <button title="Rename" onClick={() => { setEditing(p.id); setEditName(p.name); }}
                    className="rounded-lg p-1.5 text-slate-400 hover:bg-primary/8 hover:text-primary"><Pencil className="h-3.5 w-3.5" /></button>
                  <button title={p.is_active ? 'Archive' : 'Restore'} disabled={busy}
                    onClick={() => update(p.id, { is_active: !p.is_active })}
                    className="rounded-lg p-1.5 text-slate-400 hover:bg-primary/8 hover:text-primary">
                    {p.is_active ? <Archive className="h-3.5 w-3.5" /> : <RotateCcw className="h-3.5 w-3.5" />}
                  </button>
                </>
              )}
            </div>
          ))}
        </div>
      )}

      {archived.length > 0 && (
        <button onClick={() => setShowArchived((v) => !v)} className="self-start text-xs font-medium text-slate-500 hover:text-slate-800">
          {showArchived ? 'Hide archived' : `Show ${archived.length} archived`}
        </button>
      )}
    </div>
  );
}

type ImportResult = {
  dry_run: boolean;
  created: { client: string; project: string }[];
  reactivated: { client: string; project: string }[];
  unchanged: { client: string; project: string }[];
  unmatched_clients: { line: number; client: string; project: string }[];
  skipped_lines: { line: number; text: string }[];
};

export function ImportProjectsModal({ onClose, onDone, onError }: {
  onClose: () => void;
  onDone: (msg: string) => void;
  onError: (msg: string) => void;
}) {
  const terms = useTerminology();
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState<ImportResult | null>(null);

  const run = async (dryRun: boolean) => {
    setBusy(true);
    try {
      const res: ImportResult = await safeFetchJson(`${API_BASE}/projects/import/`, {
        method: 'POST', body: JSON.stringify({ text, dry_run: dryRun }),
      });
      if (dryRun) setPreview(res);
      else {
        onDone(`${res.created.length} ${terms.projects.toLowerCase()} added` +
          (res.reactivated.length ? `, ${res.reactivated.length} restored` : ''));
        onClose();
      }
    } catch (e: any) { onError(e?.message || 'Import failed'); }
    finally { setBusy(false); }
  };

  const onFile = async (f: File | undefined) => {
    if (!f) return;
    setText(await f.text());
    setPreview(null);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 backdrop-blur-sm">
      <div className="flex w-full max-w-2xl flex-col overflow-hidden rounded-2xl bg-white shadow-xl" style={{ maxHeight: '90vh' }}>
        <div className="flex shrink-0 items-center justify-between border-b border-border/50 px-6 py-4">
          <div>
            <h2 className="text-base font-bold text-slate-900">Import {terms.projects}</h2>
            <p className="text-xs text-slate-400">Two columns — client, then {terms.project.toLowerCase()} — one per line. Clients must already exist.</p>
          </div>
          <button onClick={onClose} className="rounded-lg p-1.5 hover:bg-slate-100"><X className="h-4 w-4 text-slate-400" /></button>
        </div>
        <div className="flex flex-col gap-3 overflow-y-auto p-5">
          <textarea
            value={text}
            onChange={(e) => { setText(e.target.value); setPreview(null); }}
            rows={8}
            placeholder={'Client,Project\nAcme Motors,Spring Launch\nAcme Motors,Website Refresh'}
            className="w-full rounded-lg border border-border/60 px-3 py-2 font-mono text-xs focus:border-primary focus:outline-none"
          />
          <label className="flex cursor-pointer items-center gap-2 self-start text-xs font-medium text-slate-500 hover:text-slate-800">
            <Upload className="h-3.5 w-3.5" /> Or choose a .csv file
            <input type="file" accept=".csv,text/csv,text/plain" className="hidden" onChange={(e) => onFile(e.target.files?.[0])} />
          </label>

          {preview && (
            <div className="rounded-xl border border-border/60 p-3 text-sm">
              <p className="font-semibold text-slate-800">
                {preview.created.length} new · {preview.reactivated.length} restored · {preview.unchanged.length} already there
              </p>
              {preview.unmatched_clients.length > 0 && (
                <div className="mt-2">
                  <p className="text-xs font-semibold text-amber-700">
                    {preview.unmatched_clients.length} line{preview.unmatched_clients.length === 1 ? '' : 's'} name a client we don’t have — skipped:
                  </p>
                  <ul className="mt-1 max-h-32 overflow-y-auto text-xs text-slate-500">
                    {preview.unmatched_clients.slice(0, 50).map((u) => (
                      <li key={u.line}>line {u.line}: “{u.client}” → {u.project}</li>
                    ))}
                  </ul>
                </div>
              )}
              {preview.created.length > 0 && (
                <ul className="mt-2 max-h-40 overflow-y-auto text-xs text-slate-600">
                  {preview.created.slice(0, 100).map((c, i) => <li key={i}>{c.client} → <b>{c.project}</b></li>)}
                </ul>
              )}
            </div>
          )}

          <div className="flex justify-end gap-2">
            <button onClick={() => run(true)} disabled={busy || !text.trim()}
              className="rounded-lg border border-border/60 px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-40">
              Preview
            </button>
            <button onClick={() => run(false)} disabled={busy || !preview || preview.created.length + preview.reactivated.length === 0}
              className="rounded-lg bg-primary px-3 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-40">
              {busy ? 'Working…' : 'Import'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default ClientProjectsPanel;
