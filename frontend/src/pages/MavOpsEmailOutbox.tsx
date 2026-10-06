// src/pages/MavOpsEmailOutbox.tsx
/**
 * Mavops → Email — the hold on every transactional email TimeTracker sends.
 *
 * Every email (invites, reminders, summaries, approvals, password resets…) is
 * recorded in the outbox before SendGrid sees it (server: services/email_outbox.py).
 * The global mode decides what happens next:
 *   · Hold      — nothing goes out; it waits here for review
 *   · Send to me — every email goes to a test inbox instead, recipient named in
 *                  the subject, so a real mail client shows what they'd get
 *   · Live      — sent normally
 * An email type switched Live sends for real even under Hold — the way types go
 * live one at a time once they have been seen.
 */
import { useCallback, useEffect, useMemo, useState, type CSSProperties } from "react";

const T = {
  bg: "#0f1419", surface: "#1a2231", surfaceHi: "#222d3f", border: "#2a3548",
  text: "#f1f5f9", textSub: "#b0bccd", textMuted: "#8593a8",
  teal: "#2dd4bf", yellow: "#fbbf24", red: "#f87171", green: "#34d399", purple: "#c4b5fd",
};
const mono = { fontFamily: "'DM Mono', monospace" };
const card: CSSProperties = { background: T.surface, border: `1px solid ${T.border}`, padding: 20, marginBottom: 12, borderRadius: 8 };

type Mode = "hold" | "redirect" | "live";
type Status = "held" | "redirected" | "sent" | "failed" | "discarded";

interface Settings { mode: Mode; redirect_to: string; live_types: string[]; default_redirect_to: string; }
interface EmailType { key: string; label: string; description: string; live: boolean; held: number; }
interface EmailRow {
  id: number; type: string; to: string; subject: string; org_id: number | null; org_name: string;
  status: Status; sent_to: string; sent_at: string | null; error: string; created_at: string;
}
interface EmailFull extends EmailRow { from_email: string; from_name: string; reply_to: string; html: string; plain: string; }
interface Outbox {
  settings: Settings; sendgrid_configured: boolean; types: EmailType[];
  counts: Partial<Record<Status, number>>; emails: EmailRow[];
}

interface Props {
  apiFetch: (path: string, opts?: RequestInit) => Promise<any>;
  flash: (msg: string, type?: "ok" | "err") => void;
}

const MODES: { key: Mode; label: string; help: string; color: string }[] = [
  { key: "hold", label: "Hold", help: "Nothing is sent. Every email waits here for you.", color: T.yellow },
  { key: "redirect", label: "Send to me", help: "Every email goes to your test inbox instead of the customer.", color: T.purple },
  { key: "live", label: "Live", help: "Every email goes to its real recipient.", color: T.green },
];
const STATUS_COLOR: Record<Status, string> = {
  held: T.yellow, redirected: T.purple, sent: T.green, failed: T.red, discarded: T.textMuted,
};
const STATUS_LABEL: Record<Status, string> = {
  held: "held", redirected: "sent to test inbox", sent: "sent", failed: "failed", discarded: "discarded",
};
const FILTERS: { key: "" | Status; label: string }[] = [
  { key: "held", label: "Held" }, { key: "redirected", label: "Sent to me" }, { key: "sent", label: "Sent" },
  { key: "failed", label: "Failed" }, { key: "discarded", label: "Discarded" }, { key: "", label: "All" },
];
const RELEASABLE: Status[] = ["held", "redirected", "failed"];

function ago(iso: string | null) {
  if (!iso) return "";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

function Button({ label, onClick, color = T.teal, outline = false, disabled = false }: {
  label: string; onClick: () => void; color?: string; outline?: boolean; disabled?: boolean;
}) {
  return (
    <button onClick={onClick} disabled={disabled} style={{
      background: outline ? "transparent" : disabled ? T.textMuted + "33" : color,
      border: `1px solid ${disabled ? T.textMuted + "44" : color}`,
      color: outline ? color : disabled ? T.textMuted : "#0f1419",
      padding: "6px 14px", fontSize: 12, cursor: disabled ? "default" : "pointer",
      borderRadius: 4, ...mono, opacity: disabled ? 0.6 : 1, whiteSpace: "nowrap", fontWeight: 600,
    }}>{label}</button>
  );
}

export default function MavOpsEmailOutbox({ apiFetch, flash }: Props) {
  const [data, setData] = useState<Outbox | null>(null);
  const [unavailable, setUnavailable] = useState("");
  const [status, setStatus] = useState<"" | Status>("held");
  const [type, setType] = useState("");
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [preview, setPreview] = useState<EmailFull | null>(null);
  const [redirectTo, setRedirectTo] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const qs = new URLSearchParams();
    if (status) qs.set("status", status);
    if (type) qs.set("type", type);
    try {
      const d: Outbox = await apiFetch(`/mavops/email/?${qs}`);
      setData(d); setUnavailable("");
      setRedirectTo(prev => prev || d.settings.redirect_to);
      setSelected(prev => new Set([...prev].filter(id => d.emails.some(e => e.id === id))));
    } catch (e: any) {
      setUnavailable(String(e?.message || e).includes("503")
        ? "The email outbox isn't set up on the server yet — run the migration (tracker 0191). Until then NO email is sent."
        : "Failed to load the email outbox.");
    }
  }, [apiFetch, status, type]);
  useEffect(() => { load(); }, [load]);

  const typeLabel = useMemo(() => {
    const m: Record<string, string> = {};
    (data?.types || []).forEach(t => { m[t.key] = t.label; });
    return m;
  }, [data]);

  const saveSettings = async (patch: Partial<Pick<Settings, "mode" | "redirect_to" | "live_types">>, ok: string) => {
    setBusy(true);
    try {
      await apiFetch(`/mavops/email/settings/`, { method: "POST", body: JSON.stringify(patch) });
      flash(ok); await load();
    } catch { flash("Couldn't save the email setting.", "err"); }
    finally { setBusy(false); }
  };

  const setMode = (mode: Mode) => {
    if (!data || mode === data.settings.mode) return;
    if (mode === "live" && !window.confirm(
      "Go LIVE for every email type?\n\nFrom now on every email goes straight to customers. " +
      "Emails already held stay held until you send or discard them.")) return;
    if (mode === "redirect" && !(redirectTo || data.settings.default_redirect_to)) {
      flash("Enter the test inbox first.", "err"); return;
    }
    const patch: any = { mode };
    if (mode === "redirect" && redirectTo !== data.settings.redirect_to) patch.redirect_to = redirectTo;
    saveSettings(patch, `Email mode: ${MODES.find(m => m.key === mode)!.label}.`);
  };

  const toggleType = (t: EmailType) => {
    if (!data) return;
    if (!t.live && !window.confirm(
      `Send "${t.label}" emails to real recipients from now on?\n\n` +
      `New ones go out immediately. The ${t.held} already held stay held until you send them.`)) return;
    const live = new Set(data.settings.live_types);
    if (t.live) live.delete(t.key); else live.add(t.key);
    saveSettings({ live_types: [...live] }, t.live ? `"${t.label}" is held again.` : `"${t.label}" is live.`);
  };

  const open = async (id: number) => {
    try { setPreview(await apiFetch(`/mavops/email/${id}/`)); }
    catch { flash("Couldn't load that email.", "err"); }
  };

  const act = async (e: EmailRow, action: "release" | "test" | "discard") => {
    if (action === "release" && !window.confirm(`Send this to ${e.to} now?`)) return;
    setBusy(true);
    try {
      await apiFetch(`/mavops/email/${e.id}/${action}/`, { method: "POST", body: "{}" });
      flash(action === "release" ? `Sent to ${e.to}.` : action === "test" ? "Copy sent to your inbox." : "Discarded.");
      if (action !== "test") setPreview(null);
      await load();
    } catch {
      flash(action === "discard" ? "Couldn't discard it." : "SendGrid didn't accept it — see the error on the email.", "err");
      await load();
      if (preview?.id === e.id) open(e.id);
    } finally { setBusy(false); }
  };

  const bulk = async (action: "release" | "discard") => {
    const ids = [...selected];
    if (!ids.length) return;
    if (action === "release" && ids.length > 50) { flash("Send at most 50 at a time.", "err"); return; }
    if (!window.confirm(action === "release"
      ? `Send ${ids.length} email${ids.length > 1 ? "s" : ""} to their real recipients now?`
      : `Discard ${ids.length} email${ids.length > 1 ? "s" : ""}? They will never be sent.`)) return;
    setBusy(true);
    try {
      const r = await apiFetch(`/mavops/email/bulk/`, { method: "POST", body: JSON.stringify({ action, ids }) });
      flash(`${r.done.length} ${action === "release" ? "sent" : "discarded"}` +
        (r.failed.length ? `, ${r.failed.length} failed` : ""), r.failed.length ? "err" : "ok");
      setSelected(new Set()); await load();
    } catch { flash("Bulk action failed.", "err"); }
    finally { setBusy(false); }
  };

  if (unavailable) return <div style={{ ...card, color: T.red, ...mono, fontSize: 13 }}>{unavailable}</div>;
  if (!data) return <div style={{ color: T.textMuted, ...mono, fontSize: 13 }}>loading…</div>;

  const s = data.settings;
  const releasable = data.emails.filter(e => RELEASABLE.includes(e.status));
  const allSelected = releasable.length > 0 && releasable.every(e => selected.has(e.id));

  return (
    <div>
      {!data.sendgrid_configured && (
        <div style={{ ...card, borderColor: T.red, color: T.red, ...mono, fontSize: 12.5 }}>
          SENDGRID_API_KEY is not set on this API service — nothing can be sent from here, even when released.
        </div>
      )}

      {/* ── Global mode ── */}
      <div style={card}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 12 }}>
          <span style={{ color: T.text, fontSize: 15, fontWeight: 600 }}>Outgoing email</span>
          <span style={{ color: T.textMuted, fontSize: 12, ...mono }}>applies to every company</span>
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {MODES.map(m => {
            const on = s.mode === m.key;
            return (
              <button key={m.key} disabled={busy} onClick={() => setMode(m.key)} style={{
                flex: "1 1 220px", textAlign: "left", cursor: busy ? "default" : "pointer", borderRadius: 6,
                background: on ? m.color + "1f" : T.bg, border: `1px solid ${on ? m.color : T.border}`, padding: "12px 14px",
              }}>
                <div style={{ color: on ? m.color : T.textSub, fontWeight: 600, fontSize: 13, ...mono }}>
                  {on ? "● " : "○ "}{m.label}
                </div>
                <div style={{ color: T.textMuted, fontSize: 12, marginTop: 4 }}>{m.help}</div>
              </button>
            );
          })}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
          <span style={{ color: T.textSub, fontSize: 12, ...mono }}>test inbox</span>
          <input value={redirectTo} onChange={e => setRedirectTo(e.target.value)}
            placeholder={s.default_redirect_to || "you@mavops.ai"}
            style={{ background: T.bg, border: `1px solid ${T.border}`, color: T.text, padding: "6px 10px", fontSize: 12, width: 260, borderRadius: 4, outline: "none", ...mono }} />
          <Button label="save" outline disabled={busy || redirectTo === s.redirect_to}
            onClick={() => saveSettings({ redirect_to: redirectTo }, "Test inbox saved.")} />
          <span style={{ color: T.textMuted, fontSize: 11.5 }}>
            used by "Send to me" mode{!s.redirect_to && s.default_redirect_to ? ` — blank means ${s.default_redirect_to}` : ""}
          </span>
        </div>
      </div>

      {/* ── Email types ── */}
      <div style={card}>
        <div style={{ color: T.text, fontSize: 15, fontWeight: 600, marginBottom: 4 }}>Email types</div>
        <div style={{ color: T.textMuted, fontSize: 12, marginBottom: 12 }}>
          A type switched <span style={{ color: T.green }}>live</span> goes to real recipients even while the mode above is Hold or Send to me.
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: 8 }}>
          {data.types.map(t => {
            const live = t.live || s.mode === "live";
            return (
              <div key={t.key} style={{ display: "flex", alignItems: "center", gap: 10, background: T.bg, border: `1px solid ${t.live ? T.green + "88" : T.border}`, borderRadius: 6, padding: "9px 12px" }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ color: T.text, fontSize: 13 }}>{t.label}</div>
                  <div style={{ color: T.textMuted, fontSize: 11.5, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={t.description}>{t.description}</div>
                </div>
                {t.held > 0 && (
                  <button onClick={() => { setStatus("held"); setType(t.key); }} style={{ background: T.yellow + "22", border: "none", color: T.yellow, fontSize: 11, padding: "2px 8px", borderRadius: 10, cursor: "pointer", ...mono }}>
                    {t.held} held
                  </button>
                )}
                <button disabled={busy || s.mode === "live"} onClick={() => toggleType(t)}
                  title={s.mode === "live" ? "Everything is live — switch the mode to Hold to control types one by one" : ""}
                  style={{ background: live ? T.green + "22" : "transparent", border: `1px solid ${live ? T.green : T.border}`, color: live ? T.green : T.textMuted, fontSize: 11, padding: "4px 10px", borderRadius: 4, cursor: busy || s.mode === "live" ? "default" : "pointer", minWidth: 58, ...mono }}>
                  {live ? "live" : s.mode === "redirect" ? "to me" : "held"}
                </button>
              </div>
            );
          })}
        </div>
      </div>

      {/* ── Outbox ── */}
      <div style={{ display: "flex", gap: 12, alignItems: "flex-start", flexWrap: "wrap" }}>
        <div style={{ ...card, flex: "1 1 560px", minWidth: 0, padding: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6, padding: "12px 14px", borderBottom: `1px solid ${T.border}`, flexWrap: "wrap" }}>
            {FILTERS.map(f => (
              <button key={f.key || "all"} onClick={() => setStatus(f.key)} style={{
                background: status === f.key ? T.teal + "22" : "transparent", border: `1px solid ${status === f.key ? T.teal : T.border}`,
                color: status === f.key ? T.teal : T.textSub, padding: "4px 10px", fontSize: 11.5, borderRadius: 4, cursor: "pointer", ...mono,
              }}>
                {f.label}{f.key && data.counts[f.key] ? ` ${data.counts[f.key]}` : ""}
              </button>
            ))}
            <select value={type} onChange={e => setType(e.target.value)} style={{ background: T.bg, border: `1px solid ${T.border}`, color: T.textSub, fontSize: 11.5, padding: "4px 6px", borderRadius: 4, ...mono }}>
              <option value="">all types</option>
              {data.types.map(t => <option key={t.key} value={t.key}>{t.label}</option>)}
            </select>
            <div style={{ flex: 1 }} />
            {selected.size > 0 && (
              <>
                <span style={{ color: T.textSub, fontSize: 12, ...mono }}>{selected.size} selected</span>
                <Button label="send to recipients" color={T.green} disabled={busy} onClick={() => bulk("release")} />
                <Button label="discard" color={T.red} outline disabled={busy} onClick={() => bulk("discard")} />
              </>
            )}
          </div>
          {data.emails.length === 0 ? (
            <div style={{ padding: 24, color: T.textMuted, fontSize: 13, ...mono }}>
              {status === "held" ? "Nothing waiting. Emails held from now on will appear here." : "No emails."}
            </div>
          ) : (
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12.5 }}>
              <thead>
                <tr style={{ color: T.textMuted, textAlign: "left", ...mono, fontSize: 11 }}>
                  <th style={{ padding: "8px 6px 8px 14px", width: 24 }}>
                    <input type="checkbox" checked={allSelected} disabled={!releasable.length}
                      onChange={() => setSelected(allSelected ? new Set() : new Set(releasable.map(e => e.id)))} />
                  </th>
                  <th style={{ padding: 8 }}>when</th><th style={{ padding: 8 }}>type</th>
                  <th style={{ padding: 8 }}>to</th><th style={{ padding: 8 }}>subject</th><th style={{ padding: 8 }}>status</th>
                </tr>
              </thead>
              <tbody>
                {data.emails.map(e => {
                  const canSelect = RELEASABLE.includes(e.status);
                  const active = preview?.id === e.id;
                  return (
                    <tr key={e.id} onClick={() => open(e.id)} style={{ borderTop: `1px solid ${T.border}`, cursor: "pointer", background: active ? T.surfaceHi : "transparent" }}>
                      <td style={{ padding: "8px 6px 8px 14px" }} onClick={ev => ev.stopPropagation()}>
                        <input type="checkbox" disabled={!canSelect} checked={selected.has(e.id)} onChange={() => {
                          const n = new Set(selected); if (n.has(e.id)) n.delete(e.id); else n.add(e.id); setSelected(n);
                        }} />
                      </td>
                      <td style={{ padding: 8, color: T.textMuted, whiteSpace: "nowrap", ...mono, fontSize: 11.5 }} title={new Date(e.created_at).toLocaleString()}>{ago(e.created_at)}</td>
                      <td style={{ padding: 8, color: T.textSub, whiteSpace: "nowrap" }}>{typeLabel[e.type] || e.type}</td>
                      <td style={{ padding: 8, color: T.text }}>
                        <div>{e.to}</div>
                        {e.org_name && <div style={{ color: T.textMuted, fontSize: 11 }}>{e.org_name}</div>}
                      </td>
                      <td style={{ padding: 8, color: T.text, width: "100%", maxWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={e.subject}>{e.subject}</td>
                      <td style={{ padding: 8, whiteSpace: "nowrap", color: STATUS_COLOR[e.status], ...mono, fontSize: 11.5 }} title={e.error || e.sent_to}>
                        {STATUS_LABEL[e.status]}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>

        {/* ── Preview ── */}
        <div style={{ ...card, flex: "1 1 440px", minWidth: 0, position: "sticky", top: 12 }}>
          {!preview ? (
            <div style={{ color: T.textMuted, fontSize: 13, ...mono }}>Pick an email to see exactly what the recipient gets.</div>
          ) : (
            <>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 8, marginBottom: 10 }}>
                <div style={{ minWidth: 0 }}>
                  <div style={{ color: T.text, fontSize: 14, fontWeight: 600, overflowWrap: "anywhere" }}>{preview.subject}</div>
                  <div style={{ color: T.textSub, fontSize: 12, marginTop: 4, ...mono, lineHeight: 1.6 }}>
                    to {preview.to}{preview.org_name ? ` · ${preview.org_name}` : ""}<br />
                    from {preview.from_name} &lt;{preview.from_email}&gt;{preview.reply_to ? ` · reply-to ${preview.reply_to}` : ""}<br />
                    <span style={{ color: STATUS_COLOR[preview.status] }}>{STATUS_LABEL[preview.status]}</span>
                    {preview.sent_to && preview.sent_at ? ` · last sent to ${preview.sent_to} ${ago(preview.sent_at)}` : ""}
                  </div>
                  {preview.error && <div style={{ color: T.red, fontSize: 12, marginTop: 6, ...mono, overflowWrap: "anywhere" }}>{preview.error}</div>}
                </div>
                <button onClick={() => setPreview(null)} style={{ background: "none", border: "none", color: T.textMuted, cursor: "pointer", fontSize: 16, alignSelf: "flex-start" }}>×</button>
              </div>
              <div style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
                <Button label="send me a copy" color={T.purple} outline disabled={busy} onClick={() => act(preview, "test")} />
                {RELEASABLE.includes(preview.status) && (
                  <>
                    <Button label={`send to ${preview.to}`} color={T.green} disabled={busy} onClick={() => act(preview, "release")} />
                    <Button label="discard" color={T.red} outline disabled={busy} onClick={() => act(preview, "discard")} />
                  </>
                )}
              </div>
              <iframe title="Email preview" srcDoc={preview.html} sandbox=""
                style={{ width: "100%", height: 640, border: `1px solid ${T.border}`, borderRadius: 6, background: "#fff" }} />
            </>
          )}
        </div>
      </div>
    </div>
  );
}
