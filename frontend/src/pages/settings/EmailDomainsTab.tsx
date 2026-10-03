/**
 * EmailDomainsTab — map a counterparty email domain to a client.
 *
 * Mail (Gmail + Outlook) and calendar attendees attribute to a client at 0.95
 * when the other party's domain is mapped here. Without a mapping, mail only
 * matches when a client's name is spelled out in the subject line, which is
 * why connected mailboxes were attributing almost nothing.
 *
 * Backend: /api/settings/email-domains/ (tracker/views_mail_domains.py, logic
 * in tracker/services/mail_domains.py). Owners/admins only.
 *
 * A mapping is an EXACT domain: acme.com does not cover mail.acme.com. Each
 * subdomain shows up as its own row under "Seen but not mapped".
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AtSign, Check, EyeOff, Inbox, Plus, RefreshCw, Search, Sparkles, Trash2, X,
} from 'lucide-react';
import { API_BASE, safeFetchJson } from '@/lib/api';
import {
  SettingsPage, SettingsSection, inputClass, labelClass, primaryBtnClass, secondaryBtnClass,
} from './ui';

const BASE = `${API_BASE}/settings/email-domains/`;

interface ClientOpt { id: number; name: string }

interface Mapping {
  id: number;
  domain: string;
  client_id: number;
  client_name: string | null;
  messages: number;
  messages_attributed: number;
}

interface Suggestion {
  client_id: number;
  client_name: string;
  reason: string;
  /** 'domain' | 'name' | 'token' | 'initials' — weakest last. */
  tier?: string;
}

interface Observed {
  domain: string;
  messages: number;
  inbound?: number;
  outbound?: number;
  events: number;
  users: number;
  last_seen: string | null;
  /** Server ranks by this: meetings and sent mail first, inbound-only bulk last. */
  score?: number;
  /** Vendor / bulk sender. Never true with a meeting or sent mail. */
  automated?: boolean;
  automated_reason?: string;
  suggestion: Suggestion | null;
}

interface Ignored { id: number; domain: string }

function fmtDate(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

// ── Client picker ────────────────────────────────────────────────────────────
// A firm can have hundreds of clients, so this is a type-to-narrow list rather
// than a <select>. Same behaviour as the Daily Review / Mavops pickers, in the
// Settings look.

function ClientPicker({
  clients, onPick, onCancel, placeholder,
}: {
  clients: ClientOpt[];
  onPick: (c: ClientOpt) => void;
  onCancel?: (() => void) | undefined;
  placeholder?: string | undefined;
}) {
  const [q, setQ] = useState('');
  const matches = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const list = needle ? clients.filter(c => c.name.toLowerCase().includes(needle)) : clients;
    return list.slice(0, 50);
  }, [clients, q]);

  return (
    <div className="relative w-full min-w-[220px]">
      <div className="relative">
        <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
        <input
          autoFocus
          value={q}
          onChange={e => setQ(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Escape') onCancel?.();
            if (e.key === 'Enter' && matches.length === 1 && matches[0]) onPick(matches[0]);
          }}
          placeholder={placeholder ?? 'Find a client…'}
          className={`${inputClass} pl-8 pr-8`}
        />
        {onCancel && (
          <button type="button" onClick={onCancel}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
                  aria-label="Cancel">
            <X className="w-3.5 h-3.5" />
          </button>
        )}
      </div>
      <div className="absolute z-20 mt-1 w-full max-h-56 overflow-y-auto rounded-lg border border-border/60 bg-white shadow-lg">
        {matches.length === 0 ? (
          <p className="px-3 py-2 text-[12px] text-slate-400">
            {clients.length === 0 ? 'Loading clients…' : 'No clients match'}
          </p>
        ) : matches.map(c => (
          <button key={c.id} type="button" onClick={() => onPick(c)}
                  className="w-full text-left px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50">
            {c.name}
          </button>
        ))}
      </div>
    </div>
  );
}

// ── Tab ─────────────────────────────────────────────────────────────────────

export default function EmailDomainsTab({
  onSuccess, onError,
}: {
  onSuccess: (m: string) => void;
  onError: (m: string) => void;
}) {
  const [mappings, setMappings] = useState<Mapping[]>([]);
  const [observed, setObserved] = useState<Observed[]>([]);
  const [ignored, setIgnored] = useState<Ignored[]>([]);
  const [windowDays, setWindowDays] = useState(90);
  const [clients, setClients] = useState<ClientOpt[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [rematchNote, setRematchNote] = useState<string | null>(null);
  const noteTimer = useRef<number | null>(null);

  // Manual add
  const [newDomain, setNewDomain] = useState('');
  const [newClient, setNewClient] = useState<ClientOpt | null>(null);
  const [pickingNew, setPickingNew] = useState(false);
  // Row whose "Map to…" / "Change" picker is open (domain for observed, id for mapped)
  const [pickFor, setPickFor] = useState<string | null>(null);

  // The parent hands a fresh onError every render; reading it through a ref
  // keeps `load` stable so the fetch effect below runs once, not per toast.
  const onErrorRef = useRef(onError);
  onErrorRef.current = onError;

  const load = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    try {
      const [m, o, ig] = await Promise.all([
        safeFetchJson<{ mappings: Mapping[] }>(BASE),
        safeFetchJson<{ observed: Observed[]; window_days: number }>(`${BASE}observed/`),
        safeFetchJson<{ ignored: Ignored[] }>(`${BASE}ignored/`).catch(() => ({ ignored: [] })),
      ]);
      setMappings(m.mappings || []);
      setObserved(o.observed || []);
      setWindowDays(o.window_days || 90);
      setIgnored(ig.ignored || []);
    } catch (e: any) {
      onErrorRef.current(e?.message || 'Failed to load email domains');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    safeFetchJson<ClientOpt[]>(`${API_BASE}/settings/my-clients/`)
      .then(cl => setClients((cl || []).map(c => ({ id: c.id, name: c.name }))))
      .catch(() => setClients([]));
  }, []);
  useEffect(() => () => { if (noteTimer.current) window.clearTimeout(noteTimer.current); }, []);

  // After any map/unmap the server re-matches stored mail in the background.
  // Say so, and refresh once shortly after so the attributed counts move.
  const announceRematch = (msg: string) => {
    setRematchNote(msg);
    if (noteTimer.current) window.clearTimeout(noteTimer.current);
    noteTimer.current = window.setTimeout(() => load(true), 6000);
  };

  const mapDomain = async (domain: string, client: ClientOpt) => {
    setBusy(domain);
    try {
      await safeFetchJson(BASE, {
        method: 'POST',
        body: JSON.stringify({ domain, client_id: client.id }),
      });
      onSuccess(`${domain} → ${client.name}`);
      announceRematch(
        `Mapped ${domain} to ${client.name}. Past mail and meetings from ${domain} are being re-matched in the background.`,
      );
      setPickFor(null);
      await load(true);
      return true;
    } catch (e: any) {
      onError(e?.message || 'Could not map that domain');
      return false;
    } finally {
      setBusy(null);
    }
  };

  const changeClient = async (m: Mapping, client: ClientOpt) => {
    setBusy(m.domain);
    try {
      await safeFetchJson(`${BASE}${m.id}/`, {
        method: 'PATCH',
        body: JSON.stringify({ client_id: client.id }),
      });
      onSuccess(`${m.domain} → ${client.name}`);
      announceRematch(`${m.domain} now maps to ${client.name}. Past mail and meetings are being re-matched.`);
      setPickFor(null);
      await load(true);
    } catch (e: any) {
      onError(e?.message || 'Could not change that mapping');
    } finally {
      setBusy(null);
    }
  };

  const removeMapping = async (m: Mapping) => {
    if (!window.confirm(`Stop attributing mail from ${m.domain} to ${m.client_name ?? 'this client'}?`)) return;
    setBusy(m.domain);
    try {
      await safeFetchJson(`${BASE}${m.id}/`, { method: 'DELETE' });
      onSuccess(`Removed ${m.domain}`);
      announceRematch(`Removed ${m.domain}. Past mail from it is being re-matched without the mapping.`);
      await load(true);
    } catch (e: any) {
      onError(e?.message || 'Could not remove that mapping');
    } finally {
      setBusy(null);
    }
  };

  const acceptAll = async () => {
    const items = observed.filter(o => o.suggestion)
      .map(o => ({ domain: o.domain, client_id: o.suggestion!.client_id }));
    if (!items.length) return;
    setBusy('__bulk__');
    try {
      const r = await safeFetchJson<{ created: Mapping[]; failed: { domain: string; error: string }[] }>(
        `${BASE}bulk/`, { method: 'POST', body: JSON.stringify({ mappings: items }) },
      );
      onSuccess(`Mapped ${r.created.length} domain${r.created.length === 1 ? '' : 's'}`);
      if (r.failed.length) onError(`${r.failed.length} could not be mapped: ${r.failed[0]?.error ?? ''}`);
      if (r.created.length) {
        announceRematch(`Mapped ${r.created.length} domains. Past mail and meetings from them are being re-matched in the background.`);
      }
      await load(true);
    } catch (e: any) {
      onError(e?.message || 'Could not accept suggestions');
    } finally {
      setBusy(null);
    }
  };

  const ignore = async (domain: string) => {
    setBusy(domain);
    try {
      await safeFetchJson(`${BASE}ignored/`, { method: 'POST', body: JSON.stringify({ domain }) });
      await load(true);
    } catch (e: any) {
      onError(e?.message || 'Could not ignore that domain');
    } finally {
      setBusy(null);
    }
  };

  const unignore = async (ig: Ignored) => {
    setBusy(ig.domain);
    try {
      await safeFetchJson(`${BASE}ignored/${ig.id}/`, { method: 'DELETE' });
      await load(true);
    } catch (e: any) {
      onError(e?.message || 'Could not restore that domain');
    } finally {
      setBusy(null);
    }
  };

  const submitNew = async () => {
    if (!newDomain.trim() || !newClient) return;
    const ok = await mapDomain(newDomain.trim(), newClient);
    if (ok) { setNewDomain(''); setNewClient(null); }
  };

  const ignoreAll = async (rows: Observed[]) => {
    if (!rows.length) return;
    if (!window.confirm(`Ignore all ${rows.length} probably-automated domains? You can restore any of them from "Ignored domains".`)) return;
    setBusy('__ignore_all__');
    try {
      const r = await safeFetchJson<{ ignored: Ignored[]; failed: { domain: string; error: string }[] }>(
        `${BASE}ignored/bulk/`, { method: 'POST', body: JSON.stringify({ domains: rows.map(o => o.domain) }) },
      );
      onSuccess(`Ignored ${r.ignored.length} domain${r.ignored.length === 1 ? '' : 's'}`);
      if (r.failed.length) onError(`${r.failed.length} could not be ignored: ${r.failed[0]?.error ?? ''}`);
      await load(true);
    } catch (e: any) {
      onError(e?.message || 'Could not ignore those domains');
    } finally {
      setBusy(null);
    }
  };

  const suggestionCount = observed.filter(o => o.suggestion).length;
  const nothingYet = !loading && mappings.length === 0 && observed.length === 0;
  // Server order is already signal-first; split keeps that order in each part.
  const people = observed.filter(o => !o.automated);
  const automated = observed.filter(o => o.automated);

  // One table for both parts. overflow-x-auto + a min width: in a narrow
  // settings column the table scrolls inside its card instead of crushing
  // every cell to a few characters.
  const renderObservedTable = (rows: Observed[]) => (
    <div className="border border-border/70 rounded-lg bg-white overflow-x-auto">
      <table className="w-full min-w-[720px] text-sm">
        <thead>
          <tr className="text-left text-[11px] uppercase tracking-wider text-slate-400 border-b border-border/70">
            <th className="px-3 py-2 font-medium">Domain</th>
            <th className="px-3 py-2 font-medium text-right">Messages</th>
            <th className="px-3 py-2 font-medium text-right">Meetings</th>
            <th className="px-3 py-2 font-medium text-right">People</th>
            <th className="px-3 py-2 font-medium">Last seen</th>
            <th className="px-3 py-2 font-medium">Client</th>
            <th className="px-3 py-2 font-medium" />
          </tr>
        </thead>
        <tbody>
          {rows.map(o => {
            const picking = pickFor === `o:${o.domain}`;
            const rowBusy = busy === o.domain;
            const sent = o.outbound ?? 0;
            return (
              <tr key={o.domain} className="border-b border-border/40 last:border-0 align-top">
                <td className="px-3 py-2 font-mono text-[12.5px] text-slate-800">
                  {o.domain}
                  {o.automated && o.automated_reason && (
                    <span className="block font-sans text-[11px] text-slate-400 mt-0.5">{o.automated_reason}</span>
                  )}
                </td>
                <td className="px-3 py-2 text-right tabular-nums text-slate-600 whitespace-nowrap"
                    title={`${o.inbound ?? o.messages} received, ${sent} sent`}>
                  {o.messages || '—'}
                  {sent > 0 && <span className="block text-[11px] text-emerald-600">{sent} sent</span>}
                </td>
                <td className="px-3 py-2 text-right tabular-nums text-slate-600">{o.events || '—'}</td>
                <td className="px-3 py-2 text-right tabular-nums text-slate-600">{o.users}</td>
                <td className="px-3 py-2 text-slate-500 whitespace-nowrap">{fmtDate(o.last_seen)}</td>
                <td className="px-3 py-2">
                  {picking ? (
                    <ClientPicker clients={clients}
                                  onPick={c => mapDomain(o.domain, c)}
                                  onCancel={() => setPickFor(null)} />
                  ) : o.suggestion ? (
                    <>
                      <button
                        className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-primary/8 text-primary text-[12.5px] font-semibold hover:bg-primary/15 disabled:opacity-50"
                        title={o.suggestion.reason}
                        disabled={busy !== null}
                        onClick={() => mapDomain(o.domain, { id: o.suggestion!.client_id, name: o.suggestion!.client_name })}
                      >
                        <Check className="w-3.5 h-3.5" />
                        Map to {o.suggestion.client_name}
                      </button>
                      {o.suggestion.tier === 'initials' && (
                        <span className="block text-[11px] text-slate-400 mt-0.5">
                          Matches initials of {o.suggestion.client_name}
                        </span>
                      )}
                    </>
                  ) : (
                    <span className="text-[12px] text-slate-300">No suggestion</span>
                  )}
                </td>
                <td className="px-3 py-2 text-right whitespace-nowrap">
                  {rowBusy ? (
                    <RefreshCw className="w-3.5 h-3.5 text-slate-400 animate-spin inline" />
                  ) : (
                    <>
                      <button className="text-[12px] text-slate-500 hover:text-slate-800 mr-3"
                              disabled={busy !== null}
                              onClick={() => setPickFor(picking ? null : `o:${o.domain}`)}>
                        {o.suggestion ? 'Other client…' : 'Map to…'}
                      </button>
                      <button className="inline-flex items-center gap-1 text-[12px] text-slate-400 hover:text-slate-700"
                              title="Not a client (a bank, a vendor…). Hides it from this list; it changes no matching."
                              disabled={busy !== null}
                              onClick={() => ignore(o.domain)}>
                        <EyeOff className="w-3.5 h-3.5" /> Ignore
                      </button>
                    </>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );

  return (
    <SettingsPage
      title="Email domains"
      subtitle="Tell TimeTracker which client an email domain belongs to. Mail and meetings with anyone at that domain are then attributed to that client, for everyone in your firm."
      actions={
        <button className={secondaryBtnClass} onClick={() => load()} disabled={loading}>
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      }
    >
      <div className="space-y-5">
        {rematchNote && (
          <div className="flex items-start gap-2.5 rounded-xl border border-emerald-200 bg-emerald-50/70 px-4 py-3 text-[12.5px] text-emerald-800">
            <RefreshCw className="w-3.5 h-3.5 mt-0.5 shrink-0" />
            <p className="flex-1">
              {rematchNote} Time already reviewed is not changed; the counts below update as it finishes.
            </p>
            <button onClick={() => setRematchNote(null)} className="text-emerald-600 hover:text-emerald-800" aria-label="Dismiss">
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        )}

        {nothingYet && (
          <div className="rounded-2xl border border-dashed border-slate-200 px-6 py-8 text-center">
            <Inbox className="w-6 h-6 text-slate-300 mx-auto mb-3" />
            <p className="text-sm font-semibold text-slate-700">No email domains yet</p>
            <p className="text-[12.5px] text-slate-500 mt-1.5 max-w-lg mx-auto leading-relaxed">
              Once someone in your firm connects Gmail, Outlook or their calendar, the domains your
              clients write from appear here with a suggested client. You can also add one below,
              e.g. <span className="font-mono">acmecorp.com</span> → Acme Corp. Public addresses like
              gmail.com or outlook.com can't be mapped, because everyone shares them.
            </p>
          </div>
        )}

        {/* ── Mapped ── */}
        <SettingsSection
          icon={<AtSign className="w-3.5 h-3.5" />}
          title="Mapped domains"
          sub="Exact domains only: acme.com does not cover mail.acme.com. Public domains (gmail.com, outlook.com…) and your own firm's domain can't be mapped."
        >
          <div className="flex flex-wrap items-end gap-3 mb-4">
            <div className="w-full sm:w-56">
              <label className={labelClass}>Domain</label>
              <input
                value={newDomain}
                onChange={e => setNewDomain(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter') submitNew(); }}
                placeholder="acmecorp.com"
                className={inputClass}
              />
            </div>
            <div className="w-full sm:w-72">
              <label className={labelClass}>Client</label>
              {pickingNew ? (
                <ClientPicker
                  clients={clients}
                  onPick={c => { setNewClient(c); setPickingNew(false); }}
                  onCancel={() => setPickingNew(false)}
                />
              ) : (
                <button type="button" onClick={() => setPickingNew(true)}
                        className={`${inputClass} text-left ${newClient ? '' : 'text-slate-400'}`}>
                  {newClient ? newClient.name : 'Choose a client…'}
                </button>
              )}
            </div>
            <button className={primaryBtnClass}
                    disabled={!newDomain.trim() || !newClient || busy !== null}
                    onClick={submitNew}>
              <Plus className="w-3.5 h-3.5" />
              Map
            </button>
          </div>

          {mappings.length === 0 ? (
            <p className="text-[12.5px] text-slate-400">Nothing mapped yet.</p>
          ) : (
            <div className="border border-border/70 rounded-lg bg-white overflow-x-auto">
              <table className="w-full min-w-[560px] text-sm">
                <thead>
                  <tr className="text-left text-[11px] uppercase tracking-wider text-slate-400 border-b border-border/70">
                    <th className="px-3 py-2 font-medium">Domain</th>
                    <th className="px-3 py-2 font-medium">Client</th>
                    <th className="px-3 py-2 font-medium text-right">Messages attributed</th>
                    <th className="px-3 py-2 font-medium" />
                  </tr>
                </thead>
                <tbody>
                  {mappings.map(m => (
                    <tr key={m.id} className="border-b border-border/40 last:border-0 align-top">
                      <td className="px-3 py-2 font-mono text-[12.5px] text-slate-800">{m.domain}</td>
                      <td className="px-3 py-2 text-slate-800">
                        {pickFor === `m:${m.id}` ? (
                          <ClientPicker clients={clients}
                                        onPick={c => changeClient(m, c)}
                                        onCancel={() => setPickFor(null)} />
                        ) : (m.client_name ?? '—')}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums text-slate-500">
                        {m.messages === 0 ? '—' : `${m.messages_attributed} of ${m.messages}`}
                      </td>
                      <td className="px-3 py-2 text-right whitespace-nowrap">
                        <button className="text-[12px] text-slate-500 hover:text-slate-800 mr-3"
                                disabled={busy !== null}
                                onClick={() => setPickFor(pickFor === `m:${m.id}` ? null : `m:${m.id}`)}>
                          Change
                        </button>
                        <button className="inline-flex items-center gap-1 text-[12px] text-rose-600 hover:text-rose-700"
                                disabled={busy !== null}
                                onClick={() => removeMapping(m)}>
                          <Trash2 className="w-3.5 h-3.5" /> Remove
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </SettingsSection>

        {/* ── Observed ── */}
        <SettingsSection
          icon={<Inbox className="w-3.5 h-3.5" />}
          title="Seen but not mapped"
          sub={`Domains in your firm's mail and calendars over the last ${windowDays} days. Public and internal domains are left out. Suggestions are only shown when one client clearly matches, and nothing is mapped until you click.`}
          actions={suggestionCount > 1 ? (
            <button className={secondaryBtnClass} disabled={busy !== null} onClick={acceptAll}>
              <Sparkles className="w-3.5 h-3.5" />
              Accept {suggestionCount} suggestions
            </button>
          ) : undefined}
        >
          {loading ? (
            <div className="flex justify-center py-8"><RefreshCw className="w-4 h-4 text-primary animate-spin" /></div>
          ) : observed.length === 0 ? (
            <p className="text-[12.5px] text-slate-400">
              Nothing waiting. New domains appear here as connected mailboxes and calendars sync.
            </p>
          ) : people.length === 0 ? (
            <p className="text-[12.5px] text-slate-400">
              Everything seen lately looks automated (vendors, newsletters, notifications). It's listed below.
            </p>
          ) : (
            <>
              <p className="text-[12px] text-slate-400 mb-2">
                People you've met with or written to come first.
              </p>
              {renderObservedTable(people)}
            </>
          )}
        </SettingsSection>

        {!loading && automated.length > 0 && (
          <SettingsSection
            icon={<Inbox className="w-3.5 h-3.5" />}
            title={`Probably automated (${automated.length})`}
            sub="Software vendors, newsletters and notification senders, inbound only. Anyone you've met with or emailed is never put here."
            collapsible
          >
            <div className="flex justify-end mb-3">
              <button className={secondaryBtnClass} disabled={busy !== null} onClick={() => ignoreAll(automated)}>
                {busy === '__ignore_all__'
                  ? <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                  : <EyeOff className="w-3.5 h-3.5" />}
                Ignore all {automated.length}
              </button>
            </div>
            {renderObservedTable(automated)}
          </SettingsSection>
        )}

        {ignored.length > 0 && (
          <SettingsSection
            icon={<EyeOff className="w-3.5 h-3.5" />}
            title={`Ignored domains (${ignored.length})`}
            sub="Hidden from the list above. Restore one to see it again."
            collapsible
          >
            <div className="flex flex-wrap gap-2">
              {ignored.map(ig => (
                <span key={ig.id}
                      className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md border border-border/60 text-[12.5px] font-mono text-slate-600">
                  {ig.domain}
                  <button className="text-slate-400 hover:text-slate-700" disabled={busy !== null}
                          onClick={() => unignore(ig)} aria-label={`Restore ${ig.domain}`}>
                    <X className="w-3 h-3" />
                  </button>
                </span>
              ))}
            </div>
          </SettingsSection>
        )}
      </div>
    </SettingsPage>
  );
}
