import { useState, useEffect, useCallback } from "react";

const API = "https://timetracker-api-k375.onrender.com/api";
const SEAT_PRICES: Record<string, number> = { professional: 34.99, executive: 49.99, trial: 0, none: 0 };

// ─── Types ────────────────────────────────────────────────────────────────────
interface Org {
  id: number; name: string; plan: string; seat_count: number;
  member_count: number; active_devices: number;
  last_activity: string | null; trial_ends_at: string | null; created_at: string | null;
}
interface Device {
  id: number; device_id: string; user: string; machine_name: string;
  os: string; agent_version: string; last_seen: string; is_active: boolean; org_name: string;
}
interface AgentLog {
  id: number; user: string; device_id: string; hostname: string; platform: string;
  app_version: string; trigger: string; line_count: number; created_at: string;
  log_text: string; org_name: string;
}
interface AgentError {
  id: number; error_type: string; error_message: string; traceback: string;
  user: string | null; hostname: string; device_id: string; app_version: string;
  created_at: string; resolved: boolean; org_name: string;
}
interface ErrorSummary {
  total: number; unresolved: number;
  by_type: { error_type: string; count: number }[];
  by_org: { org: string; count: number }[];
}

// ─── Theme ────────────────────────────────────────────────────────────────────
const T = {
  bg:        "#111827",   // page background — dark navy, not pure black
  surface:   "#1e2533",   // card background — noticeably lighter than bg
  border:    "#2d3748",   // card borders — visible
  borderHi:  "#4a5568",   // highlighted borders
  text:      "#f0f4f8",   // primary text — near white
  textSub:   "#94a3b8",   // secondary text — light slate
  textMuted: "#64748b",   // muted text
  teal:      "#2b9d90",
  tealHi:    "#34b5a7",
  yellow:    "#f59e0b",
  red:       "#ef4444",
  purple:    "#a78bfa",
  green:     "#10b981",
};

const mono = { fontFamily: "'DM Mono', monospace" };
const card: React.CSSProperties = {
  background: T.surface, border: `1px solid ${T.border}`,
  padding: 20, marginBottom: 10, borderRadius: 6,
};

// ─── Password Gate ─────────────────────────────────────────────────────────────
const ADMIN_PASSWORD = import.meta.env.VITE_MAVOPS_ADMIN_PASSWORD ?? "";

function PasswordGate({ onUnlock }: { onUnlock: () => void }) {
  const [input, setInput] = useState(""); const [error, setError] = useState(false); const [shake, setShake] = useState(false);
  const attempt = () => {
    if (input === ADMIN_PASSWORD) { onUnlock(); }
    else { setError(true); setShake(true); setTimeout(() => setShake(false), 500); setInput(""); }
  };
  return (
    <div style={{ minHeight: "100vh", background: T.bg, display: "flex", alignItems: "center", justifyContent: "center", fontFamily: "'DM Mono', monospace" }}>
      <div style={{ border: `1px solid ${T.teal}`, padding: "48px 56px", maxWidth: 400, width: "100%", borderRadius: 8, background: T.surface, animation: shake ? "shake 0.4s ease" : "none" }}>
        <div style={{ color: T.teal, fontSize: 11, letterSpacing: 4, marginBottom: 32, textTransform: "uppercase" as const }}>MavOps Internal</div>
        <div style={{ color: T.text, fontSize: 22, fontWeight: 700, marginBottom: 8, fontFamily: "'DM Sans', sans-serif" }}>Admin Access</div>
        <div style={{ color: T.textSub, fontSize: 13, marginBottom: 32 }}>TimeTracker Operations · All Orgs</div>
        <input type="password" value={input} autoFocus
          onChange={e => { setInput(e.target.value); setError(false); }}
          onKeyDown={e => e.key === "Enter" && attempt()}
          placeholder="Enter passphrase"
          style={{ width: "100%", background: T.bg, border: `1px solid ${error ? T.red : T.border}`, color: T.text, padding: "12px 16px", fontSize: 14, outline: "none", fontFamily: "'DM Mono', monospace", boxSizing: "border-box" as const, marginBottom: 12, borderRadius: 4 }}
        />
        {error && <div style={{ color: T.red, fontSize: 12, marginBottom: 12 }}>Incorrect passphrase</div>}
        <button onClick={attempt} style={{ width: "100%", background: T.teal, border: "none", color: "#fff", padding: "12px", fontSize: 14, cursor: "pointer", fontFamily: "'DM Mono', monospace", letterSpacing: 2, textTransform: "uppercase" as const, borderRadius: 4 }}>
          Authenticate →
        </button>
      </div>
      <style>{`@import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=DM+Sans:wght@400;600;700&display=swap');@keyframes shake{0%,100%{transform:translateX(0)}20%{transform:translateX(-8px)}40%{transform:translateX(8px)}60%{transform:translateX(-4px)}80%{transform:translateX(4px)}}*{box-sizing:border-box;margin:0;padding:0}`}</style>
    </div>
  );
}

// ─── Helpers ───────────────────────────────────────────────────────────────────
function timeAgo(iso: string) {
  if (!iso) return "never";
  const sec = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (sec < 60) return `${sec}s ago`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`;
  return `${Math.floor(sec / 86400)}d ago`;
}
function daysUntil(iso: string | null): number | null {
  if (!iso) return null;
  return Math.ceil((new Date(iso).getTime() - Date.now()) / 86400000);
}
function parseVersion(v: string) { return (v || "0").replace(/^v/, "").split(".").map(n => parseInt(n) || 0); }
function versionStatus(v: string, latest: string): "current" | "behind" | "outdated" | "dev" {
  if (!v || v === "dev" || v === "vdev") return "dev";
  const cur = parseVersion(v); const lat = parseVersion(latest);
  if (JSON.stringify(cur) === JSON.stringify(lat)) return "current";
  if (lat[0] - cur[0] > 0 || lat[1] - cur[1] > 1) return "outdated";
  return "behind";
}
function calcMRR(orgs: Org[]) { return orgs.reduce((s, o) => s + (SEAT_PRICES[o.plan] || 0) * o.seat_count, 0); }

function StatusDot({ active }: { active: boolean }) {
  return <span style={{ display: "inline-block", width: 9, height: 9, borderRadius: "50%", background: active ? T.green : T.textMuted, marginRight: 8, boxShadow: active ? `0 0 6px ${T.green}` : "none" }} />;
}

function Badge({ label, color }: { label: string; color: string }) {
  return <span style={{ display: "inline-block", padding: "3px 9px", background: color + "30", color, fontSize: 11, letterSpacing: 1, textTransform: "uppercase" as const, borderRadius: 3, border: `1px solid ${color}44`, fontFamily: "'DM Mono', monospace" }}>{label}</span>;
}

function OrgPill({ name }: { name: string }) {
  return <span style={{ display: "inline-block", padding: "2px 10px", background: "#1e2d4a", color: "#7eb3e0", fontSize: 11, border: "1px solid #2d4a6a", borderRadius: 3, fontFamily: "'DM Mono', monospace" }}>{name}</span>;
}

function VersionBadge({ version, latest }: { version: string; latest: string }) {
  const s = versionStatus(version, latest);
  const colors = { current: T.green, behind: T.yellow, outdated: T.red, dev: T.textMuted };
  const labels = { current: `v${version} ✓`, behind: `v${version} ↑`, outdated: `v${version} !!`, dev: version || "?" };
  return <span style={{ display: "inline-block", padding: "3px 9px", background: colors[s] + "25", color: colors[s], fontSize: 11, borderRadius: 3, border: `1px solid ${colors[s]}44`, ...mono }}>{labels[s]}</span>;
}

function SeatBar({ used, total }: { used: number; total: number }) {
  const pct = total > 0 ? Math.min(100, Math.round((used / total) * 100)) : 0;
  const color = pct >= 90 ? T.red : pct >= 70 ? T.yellow : T.teal;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <div style={{ width: 90, height: 5, background: T.bg, borderRadius: 3, overflow: "hidden" }}>
        <div style={{ width: `${pct}%`, height: "100%", background: color, borderRadius: 3 }} />
      </div>
      <span style={{ fontSize: 12, color, ...mono, fontWeight: 600 }}>{used}/{total} seats</span>
    </div>
  );
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const copy = () => { navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 1500); };
  return (
    <button onClick={copy} style={{ background: "none", border: `1px solid ${T.border}`, color: copied ? T.teal : T.textMuted, padding: "2px 8px", fontSize: 10, cursor: "pointer", borderRadius: 3, ...mono }}>
      {copied ? "✓ copied" : "copy id"}
    </button>
  );
}

// ─── Log Modal ─────────────────────────────────────────────────────────────────
function LogModal({ log, onClose }: { log: AgentLog; onClose: () => void }) {
  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.75)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100 }} onClick={onClose}>
      <div style={{ background: T.surface, border: `1px solid ${T.teal}`, width: "90vw", maxWidth: 960, maxHeight: "82vh", display: "flex", flexDirection: "column", borderRadius: 8 }} onClick={e => e.stopPropagation()}>
        <div style={{ padding: "16px 20px", borderBottom: `1px solid ${T.border}`, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <Badge label={log.trigger} color={log.trigger === "error" ? T.red : log.trigger === "on_demand" ? T.yellow : T.teal} />
            <OrgPill name={log.org_name} />
            <span style={{ color: T.textSub, fontSize: 12, ...mono }}>{log.hostname} · v{log.app_version} · {log.line_count} lines · {timeAgo(log.created_at)}</span>
          </div>
          <button onClick={onClose} style={{ background: "none", border: `1px solid ${T.border}`, color: T.textSub, cursor: "pointer", padding: "5px 14px", fontSize: 12, borderRadius: 4 }}>✕ close</button>
        </div>
        <pre style={{ flex: 1, overflow: "auto", padding: 20, margin: 0, fontSize: 11, lineHeight: 1.8, color: "#c8d8e8", ...mono, background: "#0d1117", whiteSpace: "pre-wrap", wordBreak: "break-all", borderRadius: "0 0 8px 8px" }}>
          {log.log_text}
        </pre>
      </div>
    </div>
  );
}

// ─── Stat Card ────────────────────────────────────────────────────────────────
function StatCard({ label, value, color }: { label: string; value: string | number; color: string }) {
  return (
    <div style={{ ...card, textAlign: "center", marginBottom: 0, padding: "18px 12px" }}>
      <div style={{ fontSize: 24, fontWeight: 700, color, ...mono }}>{value}</div>
      <div style={{ color: T.textMuted, fontSize: 11, marginTop: 5, letterSpacing: 1, textTransform: "uppercase" as const }}>{label}</div>
    </div>
  );
}

// ─── Btn ──────────────────────────────────────────────────────────────────────
function Btn({ label, onClick, color = T.teal, outline = false, disabled = false, small = false }: {
  label: string; onClick: () => void; color?: string; outline?: boolean; disabled?: boolean; small?: boolean;
}) {
  return (
    <button onClick={onClick} disabled={disabled} style={{
      background: outline ? T.bg : disabled ? T.textMuted + "33" : color,
      border: `1px solid ${disabled ? T.textMuted + "44" : color}`,
      color: outline ? color : disabled ? T.textMuted : "#fff",
      padding: small ? "5px 12px" : "7px 16px",
      fontSize: small ? 12 : 13, cursor: disabled ? "default" : "pointer",
      borderRadius: 4, ...mono, opacity: disabled ? 0.6 : 1,
      whiteSpace: "nowrap" as const, fontWeight: 500,
    }}>
      {label}
    </button>
  );
}

// ─── Main Dashboard ────────────────────────────────────────────────────────────
export default function MavOpsAdmin() {
  const [latestVersion, setLatestVersion] = useState<string>("0.0.0");
  const [unlocked, setUnlocked] = useState(() => sessionStorage.getItem("mavops_admin") === "1");
  const [token, setToken] = useState(() => localStorage.getItem("auth_token") || "");
  const [tokenInput, setTokenInput] = useState(() => localStorage.getItem("auth_token") || "");
  const [tab, setTab] = useState<"orgs" | "devices" | "logs" | "errors">("orgs");

  const [filterOrg, setFilterOrg] = useState<number | null>(null);
  const [filterHostname, setFilterHostname] = useState("");
  const [filterResolved, setFilterResolved] = useState<"all" | "open" | "resolved">("open");
  const [search, setSearch] = useState("");
  const [showInactiveOnly, setShowInactiveOnly] = useState(false);

  const [orgs, setOrgs] = useState<Org[]>([]);
  const [devices, setDevices] = useState<Device[]>([]);
  const [logs, setLogs] = useState<AgentLog[]>([]);
  const [errors, setErrors] = useState<AgentError[]>([]);
  const [errorSummary, setErrorSummary] = useState<ErrorSummary | null>(null);
  const [selectedLog, setSelectedLog] = useState<AgentLog | null>(null);
  const [expandedError, setExpandedError] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [requestingDevice, setRequestingDevice] = useState<string | null>(null);
  const [restartingDevice, setRestartingDevice] = useState<string | null>(null);
  const [msg, setMsg] = useState("");
  const [msgType, setMsgType] = useState<"ok" | "err">("ok");

  const handleUnlock = () => { sessionStorage.setItem("mavops_admin", "1"); setUnlocked(true); };
  const flash = (m: string, type: "ok" | "err" = "ok") => { setMsg(m); setMsgType(type); setTimeout(() => setMsg(""), 5000); };

  useEffect(() => { if (token && tab === "orgs") loadOrgs(); }, []); // eslint-disable-line

  useEffect(() => {
  fetch("https://api.github.com/repos/druss16/timetracker-releases/releases/latest")
    .then(r => r.json())
    .then(d => {
      const v = (d.tag_name || "").replace(/^v/, "");
      if (v) setLatestVersion(v);
    })
    .catch(() => {}); // fail silently
}, []);

  const apiFetch = useCallback(async (path: string, opts: RequestInit = {}) => {
    const headers: Record<string, string> = { "Content-Type": "application/json", ...(opts.headers as any || {}) };
    if (token) headers["Authorization"] = `Bearer ${token}`;
    const res = await fetch(`${API}${path}`, { ...opts, headers });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  }, [token]);

  const loadOrgs = useCallback(async () => {
    if (!token) return; setLoading(true);
    try { const d = await apiFetch("/mavops/orgs/"); setOrgs(d.orgs || []); }
    catch { flash("Failed — make sure your account has is_staff=True.", "err"); }
    finally { setLoading(false); }
  }, [token, apiFetch]);

  const loadDevices = useCallback(async () => {
    if (!token) return; setLoading(true);
    try { const d = await apiFetch(`/mavops/devices/${filterOrg ? `?org_id=${filterOrg}` : ""}`); setDevices(d.devices || []); }
    catch { flash("Failed to load devices.", "err"); }
    finally { setLoading(false); }
  }, [token, apiFetch, filterOrg]);

  const loadLogs = useCallback(async () => {
    if (!token) return; setLoading(true);
    try {
      const p = new URLSearchParams();
      if (filterOrg) p.set("org_id", String(filterOrg));
      if (filterHostname) p.set("hostname", filterHostname);
      const d = await apiFetch(`/mavops/logs/?${p}`);
      setLogs(d.logs || []);
    } catch { flash("Failed to load logs.", "err"); }
    finally { setLoading(false); }
  }, [token, apiFetch, filterOrg, filterHostname]);

  const loadErrors = useCallback(async () => {
    if (!token) return; setLoading(true);
    try {
      const p = new URLSearchParams({ days: "7", limit: "100" });
      if (filterOrg) p.set("org_id", String(filterOrg));
      if (filterResolved === "open") p.set("resolved", "false");
      if (filterResolved === "resolved") p.set("resolved", "true");
      const d = await apiFetch(`/mavops/errors/?${p}`);
      setErrors(d.errors || []); setErrorSummary(d.summary || null);
    } catch { flash("Failed to load errors.", "err"); }
    finally { setLoading(false); }
  }, [token, apiFetch, filterOrg, filterResolved]);

  useEffect(() => {
    if (!token) return;
    if (tab === "orgs") loadOrgs();
    if (tab === "devices") loadDevices();
    if (tab === "logs") loadLogs();
    if (tab === "errors") loadErrors();
  }, [tab, token, loadOrgs, loadDevices, loadLogs, loadErrors]);

  const requestLogs = async (deviceId: string) => {
    setRequestingDevice(deviceId);
    try { await apiFetch("/mavops/request-logs/", { method: "POST", body: JSON.stringify({ device_id: deviceId }) }); flash("✓ Log request sent — check Logs tab in ~15s."); }
    catch { flash("Failed to request logs.", "err"); }
    finally { setRequestingDevice(null); }
  };

  const restartDevice = async (hostname: string) => {
    setRestartingDevice(hostname);
    try { await apiFetch("/mavops/restart-device/", { method: "POST", body: JSON.stringify({ device_id: hostname }) }); flash("✓ Restart queued — agent will restart within 10s."); }
    catch { flash("Restart failed or not yet implemented.", "err"); }
    finally { setRestartingDevice(null); }
  };

  const resolveError = async (id: number) => {
    try {
      await apiFetch(`/mavops/errors/${id}/resolve/`, { method: "POST" });
      setErrors(prev => prev.map(e => e.id === id ? { ...e, resolved: true } : e));
      if (errorSummary) setErrorSummary(p => p ? { ...p, unresolved: p.unresolved - 1 } : p);
      flash("✓ Error resolved.");
    } catch { flash("Failed to resolve.", "err"); }
  };

  if (!unlocked) return <PasswordGate onUnlock={handleUnlock} />;

  // ── Derived ──
  const mrr = calcMRR(orgs);
  const trialsExpiringSoon = orgs.filter(o => { const d = daysUntil(o.trial_ends_at); return d !== null && d <= 7 && d >= 0; });
  const outdatedDevices = devices.filter(d => versionStatus(d.agent_version, latestVersion) === "outdated");
  const inactiveDevices = devices.filter(d => (Date.now() - new Date(d.last_seen).getTime()) > 7 * 86400000);
  const recentOrgs = [...orgs].filter(o => o.created_at).sort((a, b) => new Date(b.created_at!).getTime() - new Date(a.created_at!).getTime()).slice(0, 5);

  const filteredOrgs = orgs.filter(o => !search || o.name.toLowerCase().includes(search.toLowerCase()));
  const filteredDevices = devices.filter(d => {
    if (showInactiveOnly && (Date.now() - new Date(d.last_seen).getTime()) < 7 * 86400000) return false;
    if (!search) return true;
    return [d.machine_name, d.user, d.org_name].some(s => s.toLowerCase().includes(search.toLowerCase()));
  });

  const TABS = ["orgs", "devices", "logs", "errors"] as const;

  return (
    <div style={{ minHeight: "100vh", background: T.bg, color: T.text, fontFamily: "'DM Sans', sans-serif" }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=DM+Sans:wght@400;600;700&display=swap');
        * { box-sizing: border-box; margin: 0; padding: 0; }
        ::-webkit-scrollbar{width:6px} ::-webkit-scrollbar-track{background:${T.bg}} ::-webkit-scrollbar-thumb{background:${T.teal};border-radius:3px}
        input::placeholder{color:${T.textMuted}} button:hover{opacity:0.85} select{appearance:none}
      `}</style>

      {/* ── Header ── */}
      <div style={{ borderBottom: `1px solid ${T.border}`, padding: "14px 32px", display: "flex", alignItems: "center", justifyContent: "space-between", background: T.surface, position: "sticky", top: 0, zIndex: 10 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <div style={{ ...mono, color: T.teal, fontSize: 12, letterSpacing: 3, textTransform: "uppercase" as const, fontWeight: 600 }}>MavOps</div>
          <div style={{ color: T.border }}>|</div>
          <div style={{ fontSize: 14, color: T.textSub }}>Operations · All Orgs</div>
          {orgs.length > 0 && <div style={{ ...mono, fontSize: 12, color: T.textMuted }}>{orgs.length} orgs</div>}
          {mrr > 0 && <div style={{ ...mono, fontSize: 12, color: T.green, fontWeight: 600 }}>${mrr.toFixed(0)}/mo MRR</div>}
          {trialsExpiringSoon.length > 0 && (
            <div style={{ ...mono, fontSize: 11, color: T.yellow, background: T.yellow + "20", padding: "3px 10px", border: `1px solid ${T.yellow}44`, borderRadius: 4 }}>
              ⚠ {trialsExpiringSoon.length} trial{trialsExpiringSoon.length > 1 ? "s" : ""} expiring
            </div>
          )}
          {outdatedDevices.length > 0 && (
            <div style={{ ...mono, fontSize: 11, color: T.red, background: T.red + "20", padding: "3px 10px", border: `1px solid ${T.red}44`, borderRadius: 4 }}>
              !! {outdatedDevices.length} outdated
            </div>
          )}
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {orgs.length > 0 && (
            <select value={filterOrg || ""} onChange={e => setFilterOrg(e.target.value ? Number(e.target.value) : null)}
              style={{ background: T.bg, border: `1px solid ${T.border}`, color: filterOrg ? T.teal : T.textSub, padding: "7px 12px", fontSize: 12, outline: "none", cursor: "pointer", borderRadius: 4, ...mono }}>
              <option value="">All orgs</option>
              {orgs.map(o => <option key={o.id} value={o.id}>{o.name}</option>)}
            </select>
          )}
          <input value={tokenInput} onChange={e => setTokenInput(e.target.value)} onKeyDown={e => e.key === "Enter" && setToken(tokenInput)}
            placeholder={token ? "token connected ✓" : "paste bearer token…"}
            style={{ background: T.bg, border: `1px solid ${token ? T.teal + "88" : T.border}`, color: token ? T.teal : T.text, padding: "7px 12px", fontSize: 12, width: 200, outline: "none", borderRadius: 4, ...mono }} />
          <button onClick={() => setToken(tokenInput)} style={{ background: T.teal, border: "none", color: "#fff", padding: "7px 16px", fontSize: 12, cursor: "pointer", borderRadius: 4, ...mono, fontWeight: 600 }}>connect</button>
        </div>
      </div>

      {/* ── Flash message ── */}
      {msg && (
        <div style={{ background: msgType === "ok" ? T.teal + "22" : T.red + "22", borderBottom: `1px solid ${msgType === "ok" ? T.teal + "55" : T.red + "55"}`, padding: "10px 32px", fontSize: 13, color: msgType === "ok" ? T.teal : T.red, ...mono, display: "flex", alignItems: "center", gap: 8 }}>
          {msg}
        </div>
      )}

      {/* ── Alert bar ── */}
      {(trialsExpiringSoon.length > 0 || outdatedDevices.length > 0 || inactiveDevices.length > 0) && (
        <div style={{ background: "#1a1e2a", borderBottom: `1px solid ${T.border}`, padding: "10px 32px", display: "flex", gap: 24, flexWrap: "wrap" as const }}>
          {trialsExpiringSoon.map(o => {
            const d = daysUntil(o.trial_ends_at);
            return <span key={o.id} style={{ fontSize: 12, color: T.yellow, ...mono }}>⚠ <strong>{o.name}</strong> trial ends in {d}d</span>;
          })}
          {outdatedDevices.length > 0 && <span style={{ fontSize: 12, color: T.red, ...mono }}>!! <strong>{outdatedDevices.length}</strong> device{outdatedDevices.length > 1 ? "s" : ""} running outdated agent (latest: v{latestVersion})</span>}
          {inactiveDevices.length > 0 && <span style={{ fontSize: 12, color: T.textMuted, ...mono }}>● <strong>{inactiveDevices.length}</strong> device{inactiveDevices.length > 1 ? "s" : ""} inactive 7d+</span>}
        </div>
      )}

      {/* ── Tabs + search ── */}
      <div style={{ borderBottom: `1px solid ${T.border}`, padding: "0 32px", display: "flex", alignItems: "center", background: T.surface }}>
        {TABS.map(t => (
          <button key={t} onClick={() => setTab(t)} style={{ background: "none", border: "none", color: tab === t ? T.teal : T.textMuted, padding: "14px 22px", fontSize: 13, cursor: "pointer", borderBottom: tab === t ? `2px solid ${T.teal}` : "2px solid transparent", textTransform: "capitalize" as const, ...mono, letterSpacing: 1, fontWeight: tab === t ? 600 : 400 }}>
            {t}
            {t === "errors" && errorSummary && errorSummary.unresolved > 0 && (
              <span style={{ marginLeft: 6, background: T.red + "33", color: T.red, fontSize: 10, padding: "2px 6px", borderRadius: 3 }}>{errorSummary.unresolved}</span>
            )}
          </button>
        ))}
        <div style={{ flex: 1 }} />
        <input value={search} onChange={e => setSearch(e.target.value)} placeholder="search orgs, devices…"
          style={{ background: T.bg, border: `1px solid ${T.border}`, color: T.text, padding: "6px 12px", fontSize: 12, width: 200, outline: "none", borderRadius: 4, ...mono, margin: "0 8px" }} />
        <button onClick={() => { if (tab === "orgs") loadOrgs(); if (tab === "devices") loadDevices(); if (tab === "logs") loadLogs(); if (tab === "errors") loadErrors(); }}
          style={{ background: "none", border: `1px solid ${T.border}`, color: T.textSub, padding: "6px 14px", fontSize: 12, cursor: "pointer", borderRadius: 4, ...mono }}>↻ refresh</button>
      </div>

      <div style={{ padding: "24px 32px", maxWidth: 1280 }}>
        {loading && <div style={{ color: T.textMuted, ...mono, fontSize: 13, paddingBottom: 16 }}>loading…</div>}

        {/* ══ ORGS ══ */}
        {tab === "orgs" && (
          <div>
            {!token && <div style={{ color: T.textMuted, fontSize: 14, ...mono, paddingTop: 60, textAlign: "center" }}>paste your bearer token above and click connect</div>}

            {orgs.length > 0 && (
              <div style={{ display: "grid", gridTemplateColumns: "repeat(5,1fr)", gap: 12, marginBottom: 24 }}>
                <StatCard label="Total Orgs" value={orgs.length} color={T.text} />
                <StatCard label="MRR" value={`$${mrr.toFixed(0)}`} color={T.green} />
                <StatCard label="Total Seats" value={orgs.reduce((s, o) => s + o.seat_count, 0)} color={T.purple} />
                <StatCard label="Active Devices" value={orgs.reduce((s, o) => s + o.active_devices, 0)} color={T.teal} />
                <StatCard label="Trials" value={orgs.filter(o => o.plan === "trial").length} color={T.yellow} />
              </div>
            )}

            {recentOrgs.length > 0 && (
              <div style={{ ...card, marginBottom: 20 }}>
                <div style={{ color: T.textMuted, fontSize: 11, letterSpacing: 2, textTransform: "uppercase" as const, marginBottom: 12, fontWeight: 600 }}>Recent Signups</div>
                <div style={{ display: "flex", gap: 10, flexWrap: "wrap" as const }}>
                  {recentOrgs.map(o => (
                    <div key={o.id} style={{ background: T.bg, border: `1px solid ${T.teal}44`, padding: "6px 16px", borderRadius: 4 }}>
                      <span style={{ color: T.text, fontSize: 13, fontWeight: 600 }}>{o.name}</span>
                      <span style={{ color: T.textMuted, marginLeft: 10, fontSize: 12, ...mono }}>{timeAgo(o.created_at!)}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {filteredOrgs.map(org => {
              const trialDays = daysUntil(org.trial_ends_at);
              const trialAlert = trialDays !== null && trialDays <= 7 && trialDays >= 0;
              const mrr_org = (SEAT_PRICES[org.plan] || 0) * org.seat_count;
              return (
                <div key={org.id} style={{ ...card, borderColor: trialAlert ? T.yellow + "66" : T.border }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <div style={{ flex: 1 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
                        <span style={{ fontSize: 16, fontWeight: 700, color: T.text }}>{org.name}</span>
                        <Badge label={org.plan} color={org.plan === "trial" ? T.yellow : org.plan === "executive" ? T.purple : T.teal} />
                        {mrr_org > 0 && <span style={{ ...mono, fontSize: 12, color: T.green, fontWeight: 600 }}>${mrr_org.toFixed(0)}/mo</span>}
                        {trialAlert && <span style={{ ...mono, fontSize: 12, color: T.yellow, fontWeight: 600 }}>⚠ {trialDays}d left</span>}
                      </div>
                      <div style={{ display: "flex", gap: 24, alignItems: "center" }}>
                        <SeatBar used={org.member_count} total={org.seat_count} />
                        <span style={{ color: org.active_devices > 0 ? T.teal : T.textMuted, fontSize: 13, ...mono }}>{org.active_devices} active devices</span>
                        {org.last_activity && <span style={{ color: T.textMuted, fontSize: 12, ...mono }}>last active {timeAgo(org.last_activity)}</span>}
                      </div>
                    </div>
                    <div style={{ display: "flex", gap: 6 }}>
                      {(["devices", "logs", "errors"] as const).map(t => (
                        <Btn key={t} label={t} onClick={() => { setFilterOrg(org.id); setTab(t); }} outline color={T.textSub} small />
                      ))}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* ══ DEVICES ══ */}
        {tab === "devices" && (
          <div>
            <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 16 }}>
              <span style={{ color: T.textSub, fontSize: 13, ...mono, fontWeight: 600 }}>{filteredDevices.length} devices</span>
              {filterOrg && <button onClick={() => setFilterOrg(null)} style={{ background: "none", border: "none", color: T.teal, cursor: "pointer", fontSize: 12, ...mono }}>clear filter ×</button>}
              <div style={{ flex: 1 }} />
              <Btn label={showInactiveOnly ? "● inactive only" : "inactive only"} onClick={() => setShowInactiveOnly(!showInactiveOnly)} outline color={showInactiveOnly ? T.red : T.textMuted} small />
              <div style={{ display: "flex", gap: 10, alignItems: "center", paddingLeft: 8, borderLeft: `1px solid ${T.border}` }}>
                {([["current", T.green], ["behind", T.yellow], ["outdated", T.red], ["dev", T.textMuted]] as const).map(([s, c]) => (
                  <span key={s} style={{ fontSize: 11, color: c, ...mono }}>■ {s}</span>
                ))}
              </div>
            </div>

            {filteredDevices.map(d => {
              const inactiveDays = Math.floor((Date.now() - new Date(d.last_seen).getTime()) / 86400000);
              const isInactive = inactiveDays >= 7;
              const vs = versionStatus(d.agent_version);
              return (
                <div key={d.id} style={{ ...card, opacity: isInactive ? 0.65 : 1, borderColor: vs === "outdated" ? T.red + "55" : T.border }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <div>
                      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
                        <StatusDot active={d.is_active && !isInactive} />
                        <span style={{ fontSize: 15, fontWeight: 700, color: T.text }}>{d.machine_name}</span>
                        <OrgPill name={d.org_name} />
                        <span style={{ color: T.textSub, fontSize: 13, ...mono }}>{d.user}</span>
                        {isInactive && <Badge label={`inactive ${inactiveDays}d`} color={T.textMuted} />}
                      </div>
                      <div style={{ display: "flex", gap: 14, alignItems: "center", color: T.textSub, fontSize: 12, ...mono }}>
                        <span>{d.os || "unknown os"}</span>
                        <VersionBadge version={d.agent_version} latest={latestVersion} />
                        <span>last seen {timeAgo(d.last_seen)}</span>
                        <span style={{ color: T.textMuted }}>{d.device_id?.slice(0, 10)}…</span>
                        <CopyButton text={d.device_id} />
                      </div>
                    </div>
                    <div style={{ display: "flex", gap: 8 }}>
                      <Btn label="view logs" onClick={() => { setFilterHostname(d.machine_name); setTab("logs"); }} outline />
                      <Btn label={requestingDevice === d.device_id ? "requesting…" : "request logs"} onClick={() => d.device_id ? requestLogs(d.device_id) : flash("No device_id", "err")} disabled={requestingDevice === d.device_id} />
                      <Btn label={restartingDevice === d.machine_name ? "restarting…" : "restart"} onClick={() => restartDevice(d.machine_name)} outline color={T.yellow} disabled={restartingDevice === d.machine_name} />
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* ══ LOGS ══ */}
        {tab === "logs" && (
          <div>
            <div style={{ display: "flex", gap: 8, marginBottom: 20 }}>
              <input value={filterHostname} onChange={e => setFilterHostname(e.target.value)} placeholder="Filter by hostname…"
                style={{ background: T.surface, border: `1px solid ${T.border}`, color: T.text, padding: "8px 14px", fontSize: 13, width: 260, outline: "none", borderRadius: 4, ...mono }} />
              <Btn label="search" onClick={loadLogs} />
              {(filterHostname || filterOrg) && <Btn label="clear" onClick={() => { setFilterHostname(""); setFilterOrg(null); }} outline color={T.textMuted} />}
            </div>
            {logs.length === 0 && !loading && (
              <div style={{ color: T.textMuted, fontSize: 14, ...mono, paddingTop: 60, textAlign: "center" }}>
                no logs yet — deploy updated agent first<br />
                <span style={{ color: T.teal, marginTop: 10, display: "block", fontSize: 13 }}>use "request logs" on any device to pull immediately</span>
              </div>
            )}
            {logs.map(l => (
              <div key={l.id} style={{ ...card, cursor: "pointer" }} onClick={() => setSelectedLog(l)}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <div>
                    <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
                      <span style={{ fontSize: 15, fontWeight: 700, color: T.text }}>{l.hostname}</span>
                      <OrgPill name={l.org_name} />
                      <Badge label={l.trigger} color={l.trigger === "error" ? T.red : l.trigger === "on_demand" ? T.yellow : T.teal} />
                    </div>
                    <div style={{ color: T.textSub, fontSize: 12, ...mono }}>{l.user} · v{l.app_version} · {l.line_count} lines · {timeAgo(l.created_at)}</div>
                  </div>
                  <div style={{ color: T.teal, fontSize: 13, ...mono, fontWeight: 600 }}>view →</div>
                </div>
                <pre style={{ marginTop: 10, fontSize: 11, color: T.textMuted, ...mono, whiteSpace: "pre-wrap", lineHeight: 1.6, maxHeight: 44, overflow: "hidden", background: T.bg, padding: "8px 12px", borderRadius: 4 }}>
                  {l.log_text.split("\n").slice(-2).join("\n")}
                </pre>
              </div>
            ))}
          </div>
        )}

        {/* ══ ERRORS ══ */}
        {tab === "errors" && (
          <div>
            {errorSummary && (
              <>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 12, marginBottom: 20 }}>
                  <StatCard label="Total (7d)" value={errorSummary.total} color={T.text} />
                  <StatCard label="Unresolved" value={errorSummary.unresolved} color={errorSummary.unresolved > 0 ? T.red : T.green} />
                  <StatCard label="Error Types" value={errorSummary.by_type.length} color={T.yellow} />
                  <StatCard label="Orgs Affected" value={errorSummary.by_org.length} color={T.purple} />
                </div>
                {errorSummary.by_org.length > 0 && (
                  <div style={{ ...card, marginBottom: 20 }}>
                    <div style={{ color: T.textMuted, fontSize: 11, letterSpacing: 2, textTransform: "uppercase" as const, marginBottom: 12, fontWeight: 600 }}>By Org</div>
                    <div style={{ display: "flex", gap: 8, flexWrap: "wrap" as const }}>
                      {errorSummary.by_org.map(o => (
                        <div key={o.org} style={{ background: T.bg, border: `1px solid ${T.red}44`, padding: "5px 14px", borderRadius: 4, fontSize: 12, ...mono }}>
                          <span style={{ color: T.red, fontWeight: 700 }}>{o.count}×</span>
                          <span style={{ color: T.textSub, marginLeft: 8 }}>{o.org}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </>
            )}

            <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
              {(["all", "open", "resolved"] as const).map(f => (
                <button key={f} onClick={() => setFilterResolved(f)} style={{ background: filterResolved === f ? T.teal + "25" : "transparent", border: `1px solid ${filterResolved === f ? T.teal : T.border}`, color: filterResolved === f ? T.teal : T.textSub, padding: "6px 16px", fontSize: 12, cursor: "pointer", borderRadius: 4, ...mono, textTransform: "capitalize" as const, fontWeight: filterResolved === f ? 600 : 400 }}>{f}</button>
              ))}
            </div>

            {errors.map(e => (
              <div key={e.id} style={{ ...card, borderColor: e.resolved ? T.border : T.red + "55", opacity: e.resolved ? 0.55 : 1 }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                  <div style={{ flex: 1 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
                      <Badge label={e.resolved ? "resolved" : "open"} color={e.resolved ? T.textMuted : T.red} />
                      <span style={{ fontSize: 14, fontWeight: 700, ...mono, color: T.text }}>{e.error_type}</span>
                      <OrgPill name={e.org_name} />
                    </div>
                    <div style={{ color: T.textSub, fontSize: 13, marginBottom: 6 }}>{e.error_message.slice(0, 160)}{e.error_message.length > 160 ? "…" : ""}</div>
                    <div style={{ color: T.textMuted, fontSize: 12, ...mono }}>{e.user || "?"} · {e.hostname} · v{e.app_version} · {timeAgo(e.created_at)}</div>
                  </div>
                  <div style={{ display: "flex", gap: 8, marginLeft: 20 }}>
                    <Btn label={expandedError === e.id ? "collapse" : "details"} onClick={() => setExpandedError(expandedError === e.id ? null : e.id)} outline color={T.textMuted} small />
                    {!e.resolved && <Btn label="resolve" onClick={() => resolveError(e.id)} outline small />}
                  </div>
                </div>
                {expandedError === e.id && (
                  <pre style={{ marginTop: 14, padding: 14, background: "#0d1117", fontSize: 11, color: "#c8d8e8", ...mono, whiteSpace: "pre-wrap", wordBreak: "break-all" as const, maxHeight: 240, overflow: "auto", lineHeight: 1.7, borderRadius: 4 }}>
                    {e.traceback || e.error_message}
                  </pre>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {selectedLog && <LogModal log={selectedLog} onClose={() => setSelectedLog(null)} />}
    </div>
  );
}