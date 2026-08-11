// Firm-wide invoice-narrative section, embedded in Reports (management-gated
// there via the employee-scoped `data` signal). Aggregates ALL staff's committed
// work on a client into a client-ready narrative, per month. Opt-in, read-only,
// propose-for-review. Reuses:
//   GET /api/work-summaries/clients/?start=&end=                 (client list, firm)
//   GET /api/clients/<id>/work-summary/?scope=firm&start=&end=   (per-client draft)
import React, { useState, useEffect, useCallback } from 'react';
import { safeFetchJson, API_BASE } from '@/lib/api';
import { Sparkles, Copy, ChevronLeft, ChevronRight } from 'lucide-react';

type FirmClient = { client_id: number; name: string; hours: number };
type Cell = { loading: boolean; text?: string; empty?: boolean; error?: boolean };

const iso = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const monthStart = (d: Date) => new Date(d.getFullYear(), d.getMonth(), 1);
const monthEnd = (d: Date) => new Date(d.getFullYear(), d.getMonth() + 1, 0);
const monthLabel = (d: Date) => d.toLocaleDateString('en-US', { month: 'long', year: 'numeric' });

const fmtHours = (h: number): string => {
  if (!h) return '—';
  const hrs = Math.floor(h);
  const m = Math.round((h - hrs) * 60);
  if (hrs === 0) return `${m}m`;
  if (m === 0) return `${hrs}h`;
  return `${hrs}h ${m}m`;
};

const WorkSummariesSection: React.FC<{ hideHeading?: boolean }> = ({ hideHeading }) => {
  const [anchor, setAnchor] = useState<Date>(() => new Date());
  const [clients, setClients] = useState<FirmClient[]>([]);
  const [period, setPeriod] = useState('');
  const [loading, setLoading] = useState(true);
  const [cells, setCells] = useState<Record<number, Cell>>({});
  const [copiedKey, setCopiedKey] = useState<string | null>(null);

  const start = iso(monthStart(anchor));
  const end = iso(monthEnd(anchor));
  const isCurrentMonth = monthLabel(anchor) === monthLabel(new Date());

  const fetchClients = useCallback(async () => {
    setLoading(true);
    setCells({});
    try {
      const d = await safeFetchJson<{ clients: FirmClient[]; period: string }>(
        `${API_BASE}/work-summaries/clients/?start=${start}&end=${end}`
      );
      setClients(d.clients || []);
      setPeriod(d.period || '');
    } catch {
      setClients([]);
    } finally {
      setLoading(false);
    }
  }, [start, end]);

  useEffect(() => { fetchClients(); }, [fetchClients]);

  const gen = useCallback(async (clientId: number) => {
    setCells((p) => ({ ...p, [clientId]: { loading: true } }));
    try {
      const d = await safeFetchJson<{ summary: string; empty?: boolean; message?: string }>(
        `${API_BASE}/clients/${clientId}/work-summary/?scope=firm&start=${start}&end=${end}`
      );
      const cell: Cell = d.empty
        ? { loading: false, empty: true, ...(d.message ? { text: d.message } : {}) }
        : { loading: false, text: d.summary || '' };
      setCells((p) => ({ ...p, [clientId]: cell }));
    } catch {
      setCells((p) => ({ ...p, [clientId]: { loading: false, error: true } }));
    }
  }, [start, end]);

  const genAll = () => {
    clients.forEach((c) => {
      if (!cells[c.client_id]?.text && !cells[c.client_id]?.loading) gen(c.client_id);
    });
  };
  const anyBusy = clients.some((c) => cells[c.client_id]?.loading);
  const anyDone = clients.some((c) => cells[c.client_id]?.text);

  const copy = (key: string, text: string) => {
    try {
      navigator.clipboard?.writeText(text);
      setCopiedKey(key);
      window.setTimeout(() => setCopiedKey((k) => (k === key ? null : k)), 1500);
    } catch { /* noop */ }
  };
  const copyAll = () => {
    const parts = clients
      .map((c) => (cells[c.client_id]?.text ? `${c.name}\n${cells[c.client_id]!.text}` : null))
      .filter((x): x is string => !!x);
    if (parts.length) copy('__all__', parts.join('\n\n'));
  };

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        {!hideHeading && (
          <h2 className="flex items-center gap-1.5 text-[15px] font-bold tracking-[-0.01em] text-slate-900">
            <Sparkles className="w-4 h-4 text-primary" /> Work summaries
          </h2>
        )}
        <span className="rounded bg-primary/10 px-2 py-0.5 text-[10.5px] font-medium text-primary">
          AI draft — review before sending
        </span>
        {/* Month nav — invoice narratives are monthly. */}
        <div className="ml-auto flex items-center gap-1 rounded-xl border border-slate-200 bg-white px-1 py-1">
          <button onClick={() => setAnchor((d) => new Date(d.getFullYear(), d.getMonth() - 1, 1))}
            className="p-1.5 rounded-lg hover:bg-slate-100 text-slate-500">
            <ChevronLeft className="w-4 h-4" />
          </button>
          <span className="px-2 text-sm font-semibold text-slate-700 tabular-nums min-w-[8.5rem] text-center">
            {monthLabel(anchor)}
          </span>
          <button onClick={() => setAnchor((d) => new Date(d.getFullYear(), d.getMonth() + 1, 1))}
            disabled={isCurrentMonth}
            className="p-1.5 rounded-lg hover:bg-slate-100 text-slate-500 disabled:opacity-30 disabled:hover:bg-transparent">
            <ChevronRight className="w-4 h-4" />
          </button>
        </div>
      </div>
      <p className="-mt-1 text-xs text-slate-500">
        Client-ready narratives from the whole firm’s work on each client this month.
      </p>

      {!loading && clients.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-slate-500">
            {clients.length} client{clients.length === 1 ? '' : 's'} with work {period ? `· ${period}` : ''}
          </span>
          <span className="flex-1" />
          <button onClick={genAll} disabled={anyBusy}
            className="inline-flex items-center gap-1.5 rounded-lg border border-primary/30 bg-primary/5 px-3 py-1.5 text-xs font-semibold text-primary hover:bg-primary/15 disabled:opacity-40">
            <Sparkles className="w-3.5 h-3.5" /> {anyBusy ? 'Generating…' : 'Generate all'}
          </button>
          {anyDone && (
            <button onClick={copyAll}
              className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-600 hover:bg-slate-50">
              <Copy className="w-3.5 h-3.5" /> {copiedKey === '__all__' ? 'Copied' : 'Copy all'}
            </button>
          )}
        </div>
      )}

      {loading ? (
        <div className="text-center py-10 text-slate-400 text-sm">Loading clients…</div>
      ) : clients.length === 0 ? (
        <div className="rounded-xl border border-slate-200 bg-white px-4 py-8 text-center text-sm text-slate-400">
          No client work in {monthLabel(anchor)}. Pick another month.
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {clients.map((c) => {
            const s = cells[c.client_id];
            const idle = !s || (!s.loading && !s.text && !s.error && !s.empty);
            return (
              <div key={c.client_id} className="rounded-xl border border-slate-200 bg-white p-4">
                <div className="mb-1.5 flex items-center gap-2">
                  <span className="text-sm font-semibold text-slate-800">{c.name}</span>
                  <span className="text-xs tabular-nums text-slate-400">{fmtHours(c.hours)}</span>
                  <span className="flex-1" />
                  {idle ? (
                    <button onClick={() => gen(c.client_id)}
                      className="inline-flex items-center gap-1 rounded-full border border-primary/30 bg-primary/5 px-2.5 py-1 text-[11px] font-semibold text-primary hover:bg-primary/15">
                      <Sparkles className="w-3 h-3" /> Generate
                    </button>
                  ) : s?.text ? (
                    <div className="flex items-center gap-2">
                      <button onClick={() => copy(String(c.client_id), s.text!)}
                        className="inline-flex items-center gap-1 text-[11px] font-medium text-primary hover:underline">
                        <Copy className="w-3 h-3" /> {copiedKey === String(c.client_id) ? 'Copied' : 'Copy'}
                      </button>
                      <button onClick={() => gen(c.client_id)}
                        className="text-[11px] font-medium text-slate-400 hover:text-slate-600">Regenerate</button>
                    </div>
                  ) : null}
                </div>
                {s?.loading ? (
                  <div className="text-[12px] text-slate-400">Writing a summary…</div>
                ) : s?.error ? (
                  <div className="text-[12px] text-slate-500">
                    Couldn’t generate. <button onClick={() => gen(c.client_id)} className="font-medium text-primary hover:underline">Try again</button>
                  </div>
                ) : s?.empty ? (
                  <div className="text-[12px] text-slate-400">{s.text}</div>
                ) : s?.text ? (
                  <div className="whitespace-pre-wrap text-[12.5px] leading-relaxed text-slate-700">{s.text}</div>
                ) : (
                  <div className="text-[12px] text-slate-400">Generate a client-ready summary of {monthLabel(anchor)}’s work.</div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
};

export default WorkSummariesSection;
