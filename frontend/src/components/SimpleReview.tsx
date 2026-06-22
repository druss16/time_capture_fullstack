/**
 * SimpleReview.tsx — "Fisher-Price" one-block-at-a-time categorize flow.
 *
 * Shows ONE uncategorized block at a time, full width, as a small set of big
 * tappable choices. No dropdowns, no event wall, no context paragraph by
 * default — everything secondary hides behind a single "Something else" sheet.
 *
 * Per-block the user sees at most ~3 big buttons, chosen by what the block
 * actually offers:
 *   - AI confident (>= CONFIDENT)     -> one green "yes" button + "No, change it"
 *   - context neighbours available    -> teal/slate neighbour buttons + Personal + change
 *   - nothing                         -> Personal + "It's work — pick a client"
 *
 * On a choice we call onCategorize(...) (same signature ManualCategorization
 * already passes to BlockRow), then advance to the next block.
 *
 * FUTURE (auto-commit): to stop showing confident blocks entirely, filter them
 * out of `blocks` before they reach here — the flow needs no other change.
 *
 * Data shapes mirror BlockRow.tsx exactly so this drops into the same parent.
 */

import { useState, useMemo, useEffect } from 'react';
import { Check, ArrowRight, Loader2, X, Search } from 'lucide-react';
import { cn } from '@/lib/design-system';
import { safeFetchJson } from '@/lib/api';

const RAW_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:7123/api';
const API_BASE = RAW_BASE.endsWith('/api')
  ? RAW_BASE
  : `${RAW_BASE.replace(/\/+$/, '')}/api`;

const CONFIDENT = 0.8; // >= this, the AI's own suggestion is offered as a "yes" button

interface Suggestion {
  client: string;
  category: string;
  confidence: number;
  reasoning?: string;
}

interface Block {
  id: number;
  block_ids?: number[];
  block_count?: number;
  start: string;
  end: string;
  duration_minutes: number;
  app_name: string;
  window_title: string;
  current_client: string | null;
  current_client_id: number | null;
  suggestions?: Suggestion[];
  display?: { title: string; app: string; duration: string };
}

interface Client {
  id: number;
  name: string;
  code: string;
}

// One neighbour from the /evidence/ endpoint (before/after the block)
interface Neighbor {
  client_id: number;
  client_name: string | null;
  is_billable: boolean;
  category: string;
  gap_seconds: number | null;
}

interface SimpleReviewProps {
  blocks: Block[];
  clients: Client[];
  categories: string[];
  internalCategories?: string[];
  onCategorize: (
    blockId: number,
    blockIds: number[],
    clientId: number | null,
    category: string,
    notes?: string,
  ) => Promise<any>;
  onAllDone?: () => void;
}

const NON_BILLABLE = new Set(['Personal/Non-Billable', 'Idle', 'Uncategorized']);
const isNonBillable = (c: string) =>
  NON_BILLABLE.has(c) || c.toLowerCase().includes('personal');

const fmtTime = (s: string) =>
  new Date(s).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });

const fmtGap = (sec: number | null, side: 'before' | 'after') => {
  if (sec === null) return side;
  const m = Math.round(sec / 60);
  if (m < 1) return `just ${side}`;
  if (m < 60) return `${m} min ${side}`;
  const h = Math.floor(m / 60);
  return `${h}h ${side}`;
};

export default function SimpleReview({
  blocks,
  clients,
  categories,
  internalCategories,
  onCategorize,
  onAllDone,
}: SimpleReviewProps) {
  const [idx, setIdx] = useState(0);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sheet, setSheet] = useState<null | 'client' | 'category'>(null);
  const [search, setSearch] = useState('');
  const [neighbors, setNeighbors] = useState<Neighbor[]>([]);
  const [pendingClientId, setPendingClientId] = useState<number | null>(null);

  const block = blocks[idx];
  const top = block?.suggestions?.[0];
  const aiConfident = (top?.confidence ?? 0) >= CONFIDENT && !!top?.client;

  // Pull the before/after neighbours for context buttons (only when no client yet)
  useEffect(() => {
    setNeighbors([]);
    setError(null);
    setSheet(null);
    setSearch('');
    setPendingClientId(null);
    if (!block || block.current_client_id) return;

    let cancelled = false;
    safeFetchJson<any>(`${API_BASE}/blocks/${block.id}/evidence/`)
      .then((res) => {
        if (cancelled) return;
        const s = res?.surrounding;
        const out: Neighbor[] = [];
        const seen = new Set<number>();
        for (const n of [s?.before, s?.after]) {
          if (n && n.client_id && !seen.has(n.client_id)) {
            seen.add(n.client_id);
            out.push({
              client_id: n.client_id,
              client_name: n.client_name,
              is_billable: !!n.is_billable,
              category: n.category || '',
              gap_seconds: n.gap_seconds ?? null,
            });
          }
        }
        setNeighbors(out);
      })
      .catch(() => { if (!cancelled) setNeighbors([]); });

    return () => { cancelled = true; };
  }, [block?.id]);

  const commit = async (clientId: number | null, category: string) => {
    if (!block || saving) return;
    setSaving(true);
    setError(null);
    try {
      await onCategorize(
        block.id,
        block.block_ids || [block.id],
        clientId,
        category,
      );
      // advance
      if (idx + 1 >= blocks.length) {
        onAllDone?.();
      } else {
        setIdx((i) => i + 1);
      }
    } catch (e: any) {
      setError(e?.message || 'Could not save');
    } finally {
      setSaving(false);
    }
  };

  const filteredClients = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return clients;
    return clients.filter(
      (c) =>
        c.name.toLowerCase().includes(q) ||
        (c.code || '').toLowerCase().includes(q),
    );
  }, [clients, search]);

  const catsForPending = useMemo(() => {
    const c = clients.find((x) => x.id === pendingClientId);
    return c?.name === 'Internal' && internalCategories ? internalCategories : categories;
  }, [pendingClientId, clients, categories, internalCategories]);

  // ── all done ──
  if (!block) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-center">
        <div className="w-14 h-14 rounded-full bg-emerald-100 flex items-center justify-center mb-4">
          <Check className="w-7 h-7 text-emerald-600" />
        </div>
        <div className="text-lg font-semibold text-foreground">All caught up</div>
        <div className="text-sm text-muted-foreground mt-1">Nothing left to review.</div>
      </div>
    );
  }

  // ── client search sheet ──
  if (sheet === 'client') {
    return (
      <SheetShell title="Which client?" onClose={() => setSheet(null)}>
        <div className="relative mb-3">
          <Search className="w-4 h-4 text-muted-foreground absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            autoFocus
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search clients…"
            className="w-full pl-9 pr-3 py-3 rounded-lg border border-border bg-card text-base
                       focus:border-primary focus:outline-none"
          />
        </div>
        <div className="flex flex-col gap-1 max-h-[50vh] overflow-y-auto">
          {filteredClients.map((c) => (
            <button
              key={c.id}
              onClick={() => { setPendingClientId(c.id); setSheet('category'); setSearch(''); }}
              className="text-left px-4 py-3 rounded-lg hover:bg-muted text-base"
            >
              {c.name}
              {c.code ? <span className="text-muted-foreground"> ({c.code})</span> : null}
            </button>
          ))}
          {filteredClients.length === 0 && (
            <div className="px-4 py-6 text-center text-sm text-muted-foreground">No matches</div>
          )}
        </div>
      </SheetShell>
    );
  }

  // ── category sheet (after picking a client manually) ──
  if (sheet === 'category') {
    const cname = clients.find((c) => c.id === pendingClientId)?.name || '';
    return (
      <SheetShell title={`What kind of work for ${cname}?`} onClose={() => setSheet('client')}>
        <div className="flex flex-col gap-1 max-h-[60vh] overflow-y-auto">
          {catsForPending.map((cat) => (
            <button
              key={cat}
              onClick={() => commit(pendingClientId, cat)}
              disabled={saving}
              className="text-left px-4 py-3 rounded-lg hover:bg-muted text-base disabled:opacity-50"
            >
              {cat}
            </button>
          ))}
        </div>
      </SheetShell>
    );
  }

  // ── main one-block screen ──
  const total = blocks.length;
  return (
    <div className="max-w-xl mx-auto">
      {/* progress */}
      <div className="flex items-center justify-between mb-4">
        <div className="text-sm text-muted-foreground">
          {idx + 1} of {total}
        </div>
        <div className="h-1.5 flex-1 mx-4 rounded-full bg-muted overflow-hidden">
          <div
            className="h-full bg-emerald-500 transition-all"
            style={{ width: `${((idx) / total) * 100}%` }}
          />
        </div>
      </div>

      {/* the block */}
      <div className="rounded-xl border border-border bg-card p-5">
        <div className="text-xs text-muted-foreground uppercase tracking-wide mb-1">
          {fmtTime(block.start)} · {block.duration_minutes} min · {block.display?.app || block.app_name}
        </div>
        <div className="text-lg text-foreground mb-5 break-words">
          {block.display?.title || block.window_title || '(no title)'}
        </div>

        <div className="flex flex-col gap-3">
          {/* 1. AI confident → one big yes */}
          {aiConfident && (
            <BigButton
              tone="billable"
              onClick={() => commit(
                clients.find((c) => c.name === top!.client)?.id ?? null,
                top!.category,
              )}
              disabled={saving}
              primary
              title={`${top!.client} — ${top!.category}`}
              sub="looks right · tap yes"
              icon={<Check className="w-5 h-5" />}
            />
          )}

          {/* 2. context neighbours → teal/slate buttons */}
          {!aiConfident && neighbors.map((n) => (
            <BigButton
              key={n.client_id}
              tone={n.is_billable ? 'billable' : 'internal'}
              onClick={() => commit(n.client_id, n.category || (n.is_billable ? 'General Client Work' : 'Personal/Non-Billable'))}
              disabled={saving}
              title={n.client_name || 'Client'}
              sub={`${fmtGap(n.gap_seconds, 'before')} · ${n.is_billable ? 'billable' : 'non-billable'} · tap to use`}
            />
          ))}

          {/* 3. Personal — always available */}
          <BigButton
            tone="internal"
            onClick={() => commit(null, 'Personal/Non-Billable')}
            disabled={saving}
            title="Personal"
            sub="not work · tap"
          />
        </div>

        {/* the single escape hatch */}
        <div className="flex items-center justify-center gap-6 mt-5 pt-4 border-t border-border/50">
          <button
            onClick={() => setSheet('client')}
            disabled={saving}
            className="text-sm text-muted-foreground hover:text-foreground disabled:opacity-50"
          >
            {aiConfident ? 'No, change it…' : 'Pick a client…'}
          </button>
          <button
            onClick={() => { if (idx + 1 >= total) onAllDone?.(); else setIdx((i) => i + 1); }}
            disabled={saving}
            className="text-sm text-muted-foreground hover:text-foreground disabled:opacity-50"
          >
            Skip for now
          </button>
        </div>

        {error && (
          <div className="mt-3 text-sm text-destructive text-center">{error}</div>
        )}
        {saving && (
          <div className="mt-3 flex items-center justify-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="w-4 h-4 animate-spin" /> Saving…
          </div>
        )}
      </div>
    </div>
  );
}

// ── big tappable choice button ──
function BigButton({
  tone,
  title,
  sub,
  onClick,
  disabled,
  primary,
  icon,
}: {
  tone: 'billable' | 'internal';
  title: string;
  sub: string;
  onClick: () => void;
  disabled?: boolean;
  primary?: boolean;
  icon?: React.ReactNode;
}) {
  const s =
    tone === 'billable'
      ? { bg: '#E1F5EE', border: '#5DCAA5', text: '#04342C', sub: '#0F6E56' }
      : { bg: '#F1EFE8', border: '#B4B2A9', text: '#2C2C2A', sub: '#5F5E5A' };
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className="w-full flex items-center justify-between gap-3 px-5 py-4 rounded-lg text-left disabled:opacity-50 transition-transform active:scale-[0.99]"
      style={{ background: s.bg, border: `${primary ? 2 : 0.5}px solid ${s.border}` }}
    >
      <span className="flex items-center gap-2">
        {icon && <span style={{ color: s.sub }}>{icon}</span>}
        <span className="text-base font-medium" style={{ color: s.text }}>{title}</span>
      </span>
      <span className="text-xs font-medium whitespace-nowrap" style={{ color: s.sub }}>{sub}</span>
    </button>
  );
}

// ── slide-up sheet shell ──
function SheetShell({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="max-w-xl mx-auto">
      <div className="rounded-xl border border-border bg-card p-5">
        <div className="flex items-center justify-between mb-4">
          <div className="text-base font-semibold text-foreground">{title}</div>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground">
            <X className="w-5 h-5" />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}