// Choosing which matter a block's time belongs to.
//
// Prop-driven rather than context-driven, so it works in any list. The Weekly
// Timesheet still carries its own context-bound copy; that should be collapsed
// into this one, but not in the same change that introduces it.
//
// The menu renders through a portal. Row containers carry `overflow-hidden` for
// their rounded corners, which clips an absolutely-positioned child — a lane
// holding one row is about one row tall, so a menu opened from it showed a few
// pixels and looked like a button that did nothing.

import React, { useState } from 'react';
import { createPortal } from 'react-dom';
import { Briefcase, Check, RefreshCw } from 'lucide-react';
import { safeFetchJson, API_BASE } from '@/lib/api';
import { cn } from '@/lib/design-system';

interface MatterOption {
  project_id: number;
  display_number: string;
  description: string;
  status: string;
  billing_method: string;
  requires_utbms: boolean;
  open_date: string | null;
  responsible_attorney: string;
  practice_area: string;
  last_worked: string | null;
}

/** "opened Mar 2026" — enough to separate two same-named matters, short enough to fit. */
const fmtMatterDate = (iso: string): string => {
  const d = new Date(iso + 'T00:00:00');
  return isNaN(d.getTime())
    ? iso
    : d.toLocaleDateString(undefined, { month: 'short', year: 'numeric' });
};

const MenuPortal: React.FC<{
  anchorEl: HTMLElement | null;
  onClose: () => void;
  children: React.ReactNode;
}> = ({ anchorEl, onClose, children }) => {
  if (!anchorEl) return null;
  const r = anchorEl.getBoundingClientRect();
  const W = 288, MAX_H = 288;
  const openUp = r.bottom + MAX_H > window.innerHeight && r.top > MAX_H;
  return createPortal(
    <>
      <button className="fixed inset-0 z-[60] cursor-default"
              onClick={(e) => { e.stopPropagation(); onClose(); }} aria-label="Close" />
      <div
        style={{
          position: 'fixed',
          left: Math.max(8, Math.min(r.right - W, window.innerWidth - W - 8)),
          width: W,
          maxHeight: MAX_H,
          ...(openUp ? { bottom: window.innerHeight - r.top + 4 } : { top: r.bottom + 4 }),
        }}
        className="z-[61] overflow-auto rounded-lg border border-border bg-white py-1 shadow-xl"
      >
        {children}
      </div>
    </>,
    document.body,
  );
};

export const MatterPicker: React.FC<{
  blockIds: number[];
  label?: string;
  tone?: 'resolved' | 'needed';
  onAssigned?: (projectId: number) => void;
}> = ({ blockIds, label = 'Choose matter', tone = 'needed', onAssigned }) => {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [data, setData] = useState<any | null>(null);
  const [error, setError] = useState<string | null>(null);
  const btnRef = React.useRef<HTMLButtonElement>(null);

  const load = async () => {
    setLoading(true);
    try {
      setData(await safeFetchJson(`${API_BASE}/blocks/${blockIds[0]}/matter-options/`));
    } catch {
      setData({ options: [] });
    } finally {
      setLoading(false);
    }
  };

  const choose = async (projectId: number) => {
    setOpen(false);
    setSaving(true);
    setError(null);
    try {
      // Every block in the row, not just the one the options came from.
      for (const id of blockIds) {
        await safeFetchJson(`${API_BASE}/blocks/${id}/set-matter/`, {
          method: 'POST', body: JSON.stringify({ project_id: projectId }),
        });
      }
      onAssigned?.(projectId);
    } catch (e: any) {
      // Without this the request failed, the row stayed unchanged, and nothing
      // said why — which is exactly how a server-side 500 looked like a button
      // that did not work. A failed correction has to be visible.
      setError(e?.message || 'Could not set the matter');
    } finally {
      setSaving(false);
    }
  };

  return (
    <span className="relative shrink-0">
      <button
        ref={btnRef}
        onClick={(e) => {
          e.stopPropagation();
          const next = !open;
          setOpen(next);
          if (next && !data) load();
        }}
        disabled={saving}
        className={cn(
          'flex shrink-0 items-center gap-1 rounded-md border px-2 py-1 text-[11px] font-semibold transition-colors disabled:opacity-50',
          tone === 'resolved'
            ? 'border-transparent bg-transparent text-muted-foreground hover:bg-muted'
            : 'border-amber-300 bg-amber-50 text-amber-800 hover:bg-amber-100',
        )}
      >
        {saving ? <RefreshCw className="h-3 w-3 animate-spin" /> : <Briefcase className="h-3 w-3" />}
        {error ? 'Failed — retry' : label}
      </button>
      {error && (
        <span className="ml-1 hidden text-[10px] text-red-600 sm:inline" title={error}>
          {error.slice(0, 40)}
        </span>
      )}

      {open && !saving && (
        <MenuPortal anchorEl={btnRef.current} onClose={() => setOpen(false)}>
          <p className="px-3 py-1.5 text-[10px] font-bold uppercase tracking-wider text-slate-400">
            {data?.client_name ? `Matters for ${data.client_name}` : 'Set matter'}
          </p>
          {loading && <p className="px-3 py-2 text-[12px] text-slate-400">Loading…</p>}
          {!loading && data && data.options?.length === 0 && (
            <p className="px-3 py-2 text-[12px] text-slate-500">
              {data.client_id
                ? `${data.client_name || 'This client'} has no open matters in Clio.`
                : 'Assign a client first — a matter belongs to a client.'}
            </p>
          )}
          {!loading && data?.options?.map((o: MatterOption, i: number) => {
            const isCurrent = o.project_id === data.current_project_id;
            const prev = data.options[i - 1];
            const startsRest = !o.last_worked && (i === 0 || prev?.last_worked);
            const facts = [
              o.open_date ? `opened ${fmtMatterDate(o.open_date)}` : null,
              o.responsible_attorney || null,
              o.practice_area || null,
            ].filter(Boolean);
            return (
              <React.Fragment key={o.project_id}>
                {i === 0 && o.last_worked && (
                  <p className="px-3 pt-1 pb-0.5 text-[10px] font-bold uppercase tracking-wider text-slate-400">
                    Recently worked
                  </p>
                )}
                {startsRest && i > 0 && (
                  <p className="mt-1 border-t border-border/50 px-3 pt-2 pb-0.5 text-[10px] font-bold uppercase tracking-wider text-slate-400">
                    Other matters
                  </p>
                )}
                <button
                  onClick={(e) => { e.stopPropagation(); if (!isCurrent) choose(o.project_id); }}
                  className={cn('flex w-full items-start gap-2 px-3 py-1.5 text-left text-[13px] hover:bg-slate-50',
                    isCurrent ? 'text-slate-400' : 'text-slate-700')}
                >
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-semibold">{o.display_number}</span>
                    {o.description && (
                      <span className="block truncate text-[11px] text-slate-500">{o.description}</span>
                    )}
                    {facts.length > 0 && (
                      <span className="block truncate text-[10px] text-slate-400">{facts.join(' · ')}</span>
                    )}
                    {o.requires_utbms && (
                      <span className="block text-[10px] text-amber-600">needs UTBMS codes — will not push</span>
                    )}
                    {(o.billing_method === 'flat' || o.billing_method === 'contingency') && (
                      <span className="block text-[10px] text-amber-600">{o.billing_method} fee — tracked, not pushed</span>
                    )}
                  </span>
                  {isCurrent && <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-300" />}
                </button>
              </React.Fragment>
            );
          })}
          {!loading && data?.options?.length > 0 && (
            <p className="mt-1 border-t border-border/50 px-3 pb-1 pt-1.5 text-[10px] text-slate-400">
              Future work in the same folder goes here automatically.
            </p>
          )}
        </MenuPortal>
      )}
    </span>
  );
};

export default MatterPicker;
