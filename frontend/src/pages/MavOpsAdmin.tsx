import { useState, useEffect, useCallback } from "react";

const API = "https://timetracker-api-k375.onrender.com/api";

// ─── Types ────────────────────────────────────────────────────────────────────
interface Org {
  id: number;
  name: string;
  plan: string;
  seat_count: number;
  member_count: number;
  active_devices: number;
  last_activity: string | null;
  trial_ends_at: string | null;
}

interface Device {
  id: number;
  device_id: string;
  user: string;
  machine_name: string;
  os: string;
  agent_version: string;
  last_seen: string;
  is_active: boolean;
  org_name: string;
}

interface AgentLog {
  id: number;
  user: string;
  device_id: string;
  hostname: string;
  platform: string;
  app_version: string;
  trigger: string;
  line_count: number;
  created_at: string;
  log_text: string;
  org_name: string;
}

interface AgentError {
  id: number;
  error_type: string;
  error_message: string;
  traceback: string;
  user: string | null;
  hostname: string;
  device_id: string;
  app_version: string;
  created_at: string;
  resolved: boolean;
  org_name: string;
}

interface ErrorSummary {
  total: number;
  unresolved: number;
  by_type: { error_type: string; count: number }[];
  by_org: { org: string; count: number }[];
}

// ─── Password Gate ─────────────────────────────────────────────────────────────
const ADMIN_PASSWORD = import.meta.env.VITE_MAVOPS_ADMIN_PASSWORD || "mavops2024!";

function PasswordGate({ onUnlock }: { onUnlock: () => void }) {
  const [input, setInput] = useState("");
  const [error, setError] = useState(false);
  const [shake, setShake] = useState(false);

  const attempt = () => {
    if (input === ADMIN_PASSWORD) {
      onUnlock();
    } else {
      setError(true);
      setShake(true);
      setTimeout(() => setShake(false), 500);
      setInput("");
    }
  };

  return (
    <div style={{ minHeight: "100vh", background: "#0a0a0f", display: "flex", alignItems: "center", justifyContent: "center", fontFamily: "'DM Mono', monospace" }}>
      <div style={{ border: "1px solid #2b9d90", padding: "48px 56px", maxWidth: 400, width: "100%", animation: shake ? "shake 0.4s ease" : "none" }}>
        <div style={{ color: "#2b9d90", fontSize: 11, letterSpacing: 4, marginBottom: 32, textTransform: "uppercase" as const }}>MavOps Internal</div>
        <div style={{ color: "#fff", fontSize: 22, fontWeight: 700, marginBottom: 8, fontFamily: "'DM Sans', sans-serif" }}>Admin Access</div>
        <div style={{ color: "#666", fontSize: 13, marginBottom: 32 }}>TimeTracker Operations · All Orgs</div>
        <input
          type="password" value={input} autoFocus
          onChange={e => { setInput(e.target.value); setError(false); }}
          onKeyDown={e => e.key === "Enter" && attempt()}
          placeholder="Enter passphrase"
          style={{ width: "100%", background: "transparent", border: `1px solid ${error ? "#ef4444" : "#333"}`, color: "#fff", padding: "12px 16px", fontSize: 14, outline: "none", fontFamily: "'DM Mono', monospace", boxSizing: "border-box" as const, marginBottom: 12 }}
        />
        {error && <div style={{ color: "#ef4444", fontSize: 12, marginBottom: 12 }}>Incorrect passphrase</div>}
        <button onClick={attempt} style={{ width: "100%", background: "#2b9d90", border: "none", color: "#fff", padding: "12px", fontSize: 14, cursor: "pointer", fontFamily: "'DM Mono', monospace", letterSpacing: 2, textTransform: "uppercase" as const }}>
          Authenticate →
        </button>
      </div>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=DM+Sans:wght@400;600;700&display=swap');
        @keyframes shake { 0%,100%{transform:translateX(0)} 20%{transform:translateX(-8px)} 40%{transform:translateX(8px)} 60%{transform:translateX(-4px)} 80%{transform:translateX(4px)} }
        * { box-sizing: border-box; margin: 0; padding: 0; }
      `}</style>
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

const mono = { fontFamily: "'DM Mono', monospace" };
const card: React.CSSProperties = { background: "#0f0f16", border: "1px solid #1a1a24", padding: 20, marginBottom: 12 };

function StatusDot({ active }: { active: boolean }) {
  return <span style={{ display: "inline-block", width: 8, height: 8, borderRadius: "50%", background: active ? "#2b9d90" : "#444", marginRight: 8, boxShadow: active ? "0 0 6px #2b9d90" : "none" }} />;
}
function Badge({ label, color }: { label: string; color: string }) {
  return <span style={{ display: "inline-block", padding: "2px 8px", background: color + "22", color, fontSize: 11, letterSpacing: 1, textTransform: "uppercase" as const }}>{label}</span>;
}
function OrgPill({ name }: { name: string }) {
  return <span style={{ display: "inline-block", padding: "1px 8px", background: "#1a1a2e", color: "#7070a0", fontSize: 11, border: "1px solid #2a2a40" }}>{name}</span>;
}

// ─── Log Modal ─────────────────────────────────────────────────────────────────
function LogModal({ log, onClose }: { log: AgentLog; onClose: () => void }) {
  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.85)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100 }} onClick={onClose}>
      <div style={{ background: "#0f0f16", border: "1px solid #2b9d90", width: "90vw", maxWidth: 900, maxHeight: "80vh", display: "flex", flexDirection: "column" }} onClick={e => e.stopPropagation()}>
        <div style={{ padding: "16px 20px", borderBottom: "1px solid #1a1a24", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <Badge label={log.trigger} color={log.trigger === "error" ? "#ef4444" : log.trigger === "on_demand" ? "#f59e0b" : "#2b9d90"} />
            <OrgPill name={log.org_name} />
            <span style={{ color: "#666", fontSize: 12, ...mono }}>{log.hostname} · v{log.app_version} · {log.line_count} lines · {timeAgo(log.created_at)}</span>
          </div>
          <button onClick={onClose} style={{ background: "none", border: "1px solid #333", color: "#666", cursor: "pointer", padding: "4px 12px", fontSize: 12 }}>✕ close</button>
        </div>
        <pre style={{ flex: 1, overflow: "auto", padding: 20, margin: 0, fontSize: 11, lineHeight: 1.7, color: "#a0a0b0", ...mono, background: "#0a0a0f", whiteSpace: "pre-wrap", wordBreak: "break-all" }}>
          {log.log_text}
        </pre>
      </div>
    </div>
  );
}

// ─── Main Dashboard ────────────────────────────────────────────────────────────
export default function MavOpsAdmin() {
  const [unlocked, setUnlocked] = useState(() => sessionStorage.getItem("mavops_admin") === "1");
  const [token, setToken] = useState(() => localStorage.getItem("auth_token") || "");
  const [tokenInput, setTokenInput] = useState("");
  const [tab, setTab] = useState<"orgs" | "devices" | "logs" | "errors">("orgs");

  const [filterOrg, setFilterOrg] = useState<number | null>(null);
  const [filterHostname, setFilterHostname] = useState("");
  const [filterResolved, setFilterResolved] = useState<"all" | "open" | "resolved">("open");

  const [orgs, setOrgs] = useState<Org[]>([]);
  const [devices, setDevices] = useState<Device[]>([]);
  const [logs, setLogs] = useState<AgentLog[]>([]);
  const [errors, setErrors] = useState<AgentError[]>([]);
  const [errorSummary, setErrorSummary] = useState<ErrorSummary | null>(null);
  const [selectedLog, setSelectedLog] = useState<AgentLog | null>(null);
  const [expandedError, setExpandedError] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [requestingDevice, setRequestingDevice] = useState<string | null>(null);
  const [msg, setMsg] = useState("");

  const handleUnlock = () => { sessionStorage.setItem("mavops_admin", "1"); setUnlocked(true); };
  const flash = (m: string) => { setMsg(m); setTimeout(() => setMsg(""), 4000); };

  const apiFetch = useCallback(async (path: string, opts: RequestInit = {}) => {
    const headers: Record<string, string> = { "Content-Type": "application/json", ...(opts.headers as any || {}) };
    if (token) headers["Authorization"] = `Bearer ${token}`;
    const res = await fetch(`${API}${path}`, { ...opts, headers });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  }, [token]);

  const loadOrgs = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    try { const d = await apiFetch("/mavops/orgs/"); setOrgs(d.orgs || []); }
    catch { flash("Failed — make sure your account has is_staff=True in Django admin."); }
    finally { setLoading(false); }
  }, [token, apiFetch]);

  const loadDevices = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    try {
      const qs = filterOrg ? `?org_id=${filterOrg}` : "";
      const d = await apiFetch(`/mavops/devices/${qs}`);
      setDevices(d.devices || []);
    } catch { flash("Failed to load devices."); }
    finally { setLoading(false); }
  }, [token, apiFetch, filterOrg]);

  const loadLogs = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (filterOrg) params.set("org_id", String(filterOrg));
      if (filterHostname) params.set("hostname", filterHostname);
      const d = await apiFetch(`/mavops/logs/?${params}`);
      setLogs(d.logs || []);
    } catch { flash("Failed to load logs."); }
    finally { setLoading(false); }
  }, [token, apiFetch, filterOrg, filterHostname]);

  const loadErrors = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    try {
      const params = new URLSearchParams({ days: "7", limit: "100" });
      if (filterOrg) params.set("org_id", String(filterOrg));
      if (filterResolved === "open") params.set("resolved", "false");
      if (filterResolved === "resolved") params.set("resolved", "true");
      const d = await apiFetch(`/mavops/errors/?${params}`);
      setErrors(d.errors || []);
      setErrorSummary(d.summary || null);
    } catch { flash("Failed to load errors."); }
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
    try {
      await apiFetch("/mavops/request-logs/", { method: "POST", body: JSON.stringify({ device_id: deviceId }) });
      flash("✓ Log request sent — switch to Logs tab in ~15s.");
    } catch { flash("Failed to request logs."); }
    finally { setRequestingDevice(null); }
  };

  const resolveError = async (id: number) => {
    try {
      await apiFetch(`/mavops/errors/${id}/resolve/`, { method: "POST" });
      setErrors(prev => prev.map(e => e.id === id ? { ...e, resolved: true } : e));
      if (errorSummary) setErrorSummary(p => p ? { ...p, unresolved: p.unresolved - 1 } : p);
    } catch { flash("Failed to resolve."); }
  };

  if (!unlocked) return <PasswordGate onUnlock={handleUnlock} />;

  const TABS = ["orgs", "devices", "logs", "errors"] as const;

  return (
    <div style={{ minHeight: "100vh", background: "#0a0a0f", color: "#e0e0e8", fontFamily: "'DM Sans', sans-serif" }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=DM+Sans:wght@400;600;700&display=swap');
        * { box-sizing: border-box; margin: 0; padding: 0; }
        ::-webkit-scrollbar{width:6px} ::-webkit-scrollbar-track{background:#0a0a0f} ::-webkit-scrollbar-thumb{background:#2b9d90}
        input::placeholder{color:#444} button:hover{opacity:0.85} select{appearance:none}
      `}</style>

      {/* Header */}
      <div style={{ borderBottom: "1px solid #1a1a24", padding: "14px 32px", display: "flex", alignItems: "center", justifyContent: "space-between", background: "#0a0a0f", position: "sticky", top: 0, zIndex: 10 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <div style={{ ...mono, color: "#2b9d90", fontSize: 11, letterSpacing: 3, textTransform: "uppercase" as const }}>MavOps</div>
          <div style={{ color: "#333" }}>|</div>
          <div style={{ fontSize: 13, color: "#666" }}>Operations · All Orgs</div>
          {orgs.length > 0 && <div style={{ ...mono, fontSize: 11, color: "#333" }}>{orgs.length} orgs</div>}
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {orgs.length > 0 && (
            <select value={filterOrg || ""} onChange={e => setFilterOrg(e.target.value ? Number(e.target.value) : null)}
              style={{ background: "#0f0f16", border: "1px solid #222", color: filterOrg ? "#2b9d90" : "#555", padding: "7px 12px", fontSize: 12, outline: "none", cursor: "pointer", ...mono }}>
              <option value="">All orgs</option>
              {orgs.map(o => <option key={o.id} value={o.id}>{o.name}</option>)}
            </select>
          )}
          <input value={tokenInput} onChange={e => setTokenInput(e.target.value)} onKeyDown={e => e.key === "Enter" && setToken(tokenInput)}
            placeholder={token ? "token connected ✓" : "paste bearer token…"}
            style={{ background: "#0f0f16", border: `1px solid ${token ? "#2b9d9066" : "#222"}`, color: token ? "#2b9d90" : "#e0e0e8", padding: "7px 12px", fontSize: 12, width: 220, outline: "none", ...mono }} />
          <button onClick={() => setToken(tokenInput)} style={{ background: "#2b9d90", border: "none", color: "#fff", padding: "7px 14px", fontSize: 12, cursor: "pointer", ...mono }}>
            connect
          </button>
        </div>
      </div>

      {msg && <div style={{ background: "#2b9d9011", borderBottom: "1px solid #2b9d9033", padding: "10px 32px", fontSize: 13, color: "#2b9d90", ...mono }}>{msg}</div>}

      {/* Tabs */}
      <div style={{ borderBottom: "1px solid #1a1a24", padding: "0 32px", display: "flex" }}>
        {TABS.map(t => (
          <button key={t} onClick={() => setTab(t)} style={{ background: "none", border: "none", color: tab === t ? "#2b9d90" : "#555", padding: "13px 20px", fontSize: 13, cursor: "pointer", borderBottom: tab === t ? "2px solid #2b9d90" : "2px solid transparent", textTransform: "capitalize" as const, ...mono, letterSpacing: 1 }}>
            {t}
            {t === "errors" && errorSummary && errorSummary.unresolved > 0 && (
              <span style={{ marginLeft: 6, background: "#ef444422", color: "#ef4444", fontSize: 10, padding: "1px 5px" }}>{errorSummary.unresolved}</span>
            )}
          </button>
        ))}
        <div style={{ flex: 1 }} />
        <button onClick={() => { if (tab === "orgs") loadOrgs(); if (tab === "devices") loadDevices(); if (tab === "logs") loadLogs(); if (tab === "errors") loadErrors(); }}
          style={{ background: "none", border: "none", color: "#333", padding: "13px 20px", fontSize: 12, cursor: "pointer", ...mono }}>
          ↻ refresh
        </button>
      </div>

      <div style={{ padding: "24px 32px", maxWidth: 1200 }}>
        {loading && <div style={{ color: "#333", ...mono, fontSize: 13, paddingBottom: 16 }}>loading…</div>}

        {/* ── ORGS ── */}
        {tab === "orgs" && (
          <div>
            {!token && <div style={{ color: "#333", fontSize: 13, ...mono, paddingTop: 40, textAlign: "center" }}>paste your bearer token above and click connect</div>}
            {orgs.map(org => (
              <div key={org.id} style={card}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <div>
                    <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 6 }}>{org.name}</div>
                    <div style={{ display: "flex", gap: 16, color: "#555", fontSize: 12, ...mono }}>
                      <span style={{ color: org.plan === "trial" ? "#f59e0b" : "#2b9d90" }}>{org.plan}</span>
                      <span>{org.seat_count} seats · {org.member_count} members</span>
                      <span style={{ color: "#2b9d90" }}>{org.active_devices} active devices</span>
                      {org.last_activity && <span>last active {timeAgo(org.last_activity)}</span>}
                      {org.trial_ends_at && <span style={{ color: "#f59e0b" }}>trial ends {new Date(org.trial_ends_at).toLocaleDateString()}</span>}
                    </div>
                  </div>
                  <div style={{ display: "flex", gap: 6 }}>
                    {(["devices", "logs", "errors"] as const).map(t => (
                      <button key={t} onClick={() => { setFilterOrg(org.id); setTab(t); }}
                        style={{ background: "none", border: "1px solid #2a2a40", color: "#666", padding: "5px 12px", fontSize: 11, cursor: "pointer", ...mono }}>
                        {t}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* ── DEVICES ── */}
        {tab === "devices" && (
          <div>
            <div style={{ color: "#444", fontSize: 12, ...mono, marginBottom: 16 }}>
              {devices.length} devices · {filterOrg ? `filtered` : "all orgs"}
              {filterOrg && <button onClick={() => setFilterOrg(null)} style={{ marginLeft: 8, background: "none", border: "none", color: "#2b9d90", cursor: "pointer", fontSize: 11 }}>clear ×</button>}
            </div>
            {devices.map(d => (
              <div key={d.id} style={card}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <div>
                    <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
                      <StatusDot active={d.is_active} />
                      <span style={{ fontSize: 15, fontWeight: 600 }}>{d.machine_name}</span>
                      <OrgPill name={d.org_name} />
                      <span style={{ color: "#555", fontSize: 12, ...mono }}>{d.user}</span>
                    </div>
                    <div style={{ display: "flex", gap: 16, color: "#555", fontSize: 12, ...mono }}>
                      <span>{d.os || "unknown"}</span>
                      <span style={{ color: "#2b9d90" }}>v{d.agent_version || "?"}</span>
                      <span>last seen {timeAgo(d.last_seen)}</span>
                      <span style={{ color: "#2a2a40" }}>{d.device_id?.slice(0, 8)}…</span>
                    </div>
                  </div>
                  <div style={{ display: "flex", gap: 8 }}>
                    <button onClick={() => { setFilterHostname(d.machine_name); setTab("logs"); }}
                      style={{ background: "none", border: "1px solid #2b9d9066", color: "#2b9d90", padding: "6px 14px", fontSize: 12, cursor: "pointer", ...mono }}>
                      view logs
                    </button>
                    <button
                      onClick={() => d.device_id ? requestLogs(d.device_id) : flash("No device_id")}
                      disabled={requestingDevice === d.device_id}
                      style={{ background: requestingDevice === d.device_id ? "#222" : "#2b9d90", border: "none", color: "#fff", padding: "6px 14px", fontSize: 12, cursor: "pointer", ...mono }}>
                      {requestingDevice === d.device_id ? "requesting…" : "request logs"}
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* ── LOGS ── */}
        {tab === "logs" && (
          <div>
            <div style={{ display: "flex", gap: 8, marginBottom: 20 }}>
              <input value={filterHostname} onChange={e => setFilterHostname(e.target.value)}
                placeholder="Filter by hostname…"
                style={{ background: "#0f0f16", border: "1px solid #222", color: "#e0e0e8", padding: "8px 12px", fontSize: 12, width: 240, outline: "none", ...mono }} />
              <button onClick={loadLogs} style={{ background: "#2b9d90", border: "none", color: "#fff", padding: "8px 16px", fontSize: 12, cursor: "pointer", ...mono }}>search</button>
              {(filterHostname || filterOrg) && (
                <button onClick={() => { setFilterHostname(""); setFilterOrg(null); }} style={{ background: "none", border: "1px solid #333", color: "#666", padding: "8px 12px", fontSize: 12, cursor: "pointer", ...mono }}>clear</button>
              )}
            </div>
            {logs.length === 0 && !loading && (
              <div style={{ color: "#333", fontSize: 13, ...mono, paddingTop: 40, textAlign: "center" }}>
                no logs yet — deploy updated agent first<br />
                <span style={{ color: "#2b9d90", marginTop: 8, display: "block" }}>use "request logs" from devices tab to pull immediately</span>
              </div>
            )}
            {logs.map(l => (
              <div key={l.id} style={{ ...card, cursor: "pointer" }} onClick={() => setSelectedLog(l)}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <div>
                    <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
                      <span style={{ fontSize: 14, fontWeight: 600 }}>{l.hostname}</span>
                      <OrgPill name={l.org_name} />
                      <Badge label={l.trigger} color={l.trigger === "error" ? "#ef4444" : l.trigger === "on_demand" ? "#f59e0b" : "#2b9d90"} />
                    </div>
                    <div style={{ color: "#555", fontSize: 12, ...mono }}>{l.user} · v{l.app_version} · {l.line_count} lines · {timeAgo(l.created_at)}</div>
                  </div>
                  <div style={{ color: "#2b9d90", fontSize: 12, ...mono }}>view →</div>
                </div>
                <pre style={{ marginTop: 10, fontSize: 10, color: "#2a2a3a", ...mono, whiteSpace: "pre-wrap", lineHeight: 1.6, maxHeight: 40, overflow: "hidden" }}>
                  {l.log_text.split("\n").slice(-2).join("\n")}
                </pre>
              </div>
            ))}
          </div>
        )}

        {/* ── ERRORS ── */}
        {tab === "errors" && (
          <div>
            {errorSummary && (
              <>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 12, marginBottom: 20 }}>
                  {[
                    { label: "Total (7d)", value: errorSummary.total, color: "#e0e0e8" },
                    { label: "Unresolved", value: errorSummary.unresolved, color: errorSummary.unresolved > 0 ? "#ef4444" : "#2b9d90" },
                    { label: "Error Types", value: errorSummary.by_type.length, color: "#f59e0b" },
                    { label: "Orgs Affected", value: errorSummary.by_org.length, color: "#a78bfa" },
                  ].map(s => (
                    <div key={s.label} style={{ ...card, textAlign: "center", marginBottom: 0 }}>
                      <div style={{ fontSize: 26, fontWeight: 700, color: s.color, ...mono }}>{s.value}</div>
                      <div style={{ color: "#444", fontSize: 11, marginTop: 4, letterSpacing: 1, textTransform: "uppercase" as const }}>{s.label}</div>
                    </div>
                  ))}
                </div>
                {errorSummary.by_org.length > 0 && (
                  <div style={{ ...card, marginBottom: 20 }}>
                    <div style={{ color: "#444", fontSize: 11, letterSpacing: 2, textTransform: "uppercase" as const, marginBottom: 10 }}>By Org</div>
                    <div style={{ display: "flex", gap: 8, flexWrap: "wrap" as const }}>
                      {errorSummary.by_org.map(o => (
                        <div key={o.org} style={{ background: "#1a0a0a", border: "1px solid #ef444433", padding: "3px 12px", fontSize: 12, ...mono }}>
                          <span style={{ color: "#ef4444" }}>{o.count}×</span>
                          <span style={{ color: "#888", marginLeft: 8 }}>{o.org}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </>
            )}
            <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
              {(["all", "open", "resolved"] as const).map(f => (
                <button key={f} onClick={() => setFilterResolved(f)} style={{ background: filterResolved === f ? "#2b9d9022" : "none", border: `1px solid ${filterResolved === f ? "#2b9d90" : "#333"}`, color: filterResolved === f ? "#2b9d90" : "#555", padding: "5px 14px", fontSize: 11, cursor: "pointer", ...mono, textTransform: "capitalize" as const }}>{f}</button>
              ))}
            </div>
            {errors.map(e => (
              <div key={e.id} style={{ ...card, borderColor: e.resolved ? "#1a1a24" : "#ef444433", opacity: e.resolved ? 0.5 : 1 }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                  <div style={{ flex: 1 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
                      <Badge label={e.resolved ? "resolved" : "open"} color={e.resolved ? "#555" : "#ef4444"} />
                      <span style={{ fontSize: 14, fontWeight: 600, ...mono }}>{e.error_type}</span>
                      <OrgPill name={e.org_name} />
                    </div>
                    <div style={{ color: "#888", fontSize: 12, marginBottom: 4 }}>{e.error_message.slice(0, 140)}{e.error_message.length > 140 ? "…" : ""}</div>
                    <div style={{ color: "#444", fontSize: 11, ...mono }}>{e.user || "?"} · {e.hostname} · v{e.app_version} · {timeAgo(e.created_at)}</div>
                  </div>
                  <div style={{ display: "flex", gap: 8, marginLeft: 16 }}>
                    <button onClick={() => setExpandedError(expandedError === e.id ? null : e.id)} style={{ background: "none", border: "1px solid #333", color: "#666", padding: "4px 10px", fontSize: 11, cursor: "pointer", ...mono }}>
                      {expandedError === e.id ? "collapse" : "details"}
                    </button>
                    {!e.resolved && (
                      <button onClick={() => resolveError(e.id)} style={{ background: "none", border: "1px solid #2b9d9066", color: "#2b9d90", padding: "4px 10px", fontSize: 11, cursor: "pointer", ...mono }}>resolve</button>
                    )}
                  </div>
                </div>
                {expandedError === e.id && (
                  <pre style={{ marginTop: 12, padding: 12, background: "#0a0a0f", fontSize: 10, color: "#666", ...mono, whiteSpace: "pre-wrap", wordBreak: "break-all" as const, maxHeight: 200, overflow: "auto", lineHeight: 1.6 }}>
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