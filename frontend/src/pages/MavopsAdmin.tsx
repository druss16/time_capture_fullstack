import { useState, useEffect, useCallback } from "react";

const API = "https://timetracker-api-k375.onrender.com/api";

// ─── Types ────────────────────────────────────────────────────────────────────
interface Device {
  id: number;
  user: string;
  user_id: number;
  machine_name: string;
  os: string;
  agent_version: string;
  last_seen: string;
  is_active: boolean;
  device_id?: string;
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
}

interface AgentError {
  id: number;
  error_type: string;
  error_message: string;
  user: string | null;
  hostname: string;
  device_id: string;
  app_version: string;
  created_at: string;
  resolved: boolean;
}

interface ErrorSummary {
  period_days: number;
  total_errors: number;
  unresolved: number;
  by_error_type: { error_type: string; count: number }[];
  by_app_version: { app_version: string; count: number }[];
  most_affected_users: { user__username: string; hostname: string; count: number }[];
}

interface OrgInfo {
  id: number;
  name: string;
  plan: string;
  seat_count: number;
}

// ─── Password Gate ─────────────────────────────────────────────────────────────
const ADMIN_PASSWORD = "mavops2024!";

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
    <div style={{
      minHeight: "100vh", background: "#0a0a0f",
      display: "flex", alignItems: "center", justifyContent: "center",
      fontFamily: "'DM Mono', monospace",
    }}>
      <div style={{
        border: "1px solid #2b9d90", padding: "48px 56px", maxWidth: 400, width: "100%",
        animation: shake ? "shake 0.4s ease" : "none",
      }}>
        <div style={{ color: "#2b9d90", fontSize: 11, letterSpacing: 4, marginBottom: 32, textTransform: "uppercase" }}>
          MavOps Internal
        </div>
        <div style={{ color: "#fff", fontSize: 22, fontWeight: 700, marginBottom: 8, fontFamily: "'DM Sans', sans-serif" }}>
          Admin Access
        </div>
        <div style={{ color: "#666", fontSize: 13, marginBottom: 32 }}>
          TimeTracker Operations Dashboard
        </div>
        <input
          type="password"
          value={input}
          onChange={e => { setInput(e.target.value); setError(false); }}
          onKeyDown={e => e.key === "Enter" && attempt()}
          placeholder="Enter passphrase"
          autoFocus
          style={{
            width: "100%", background: "transparent", border: `1px solid ${error ? "#ef4444" : "#333"}`,
            color: "#fff", padding: "12px 16px", fontSize: 14, outline: "none",
            fontFamily: "'DM Mono', monospace", boxSizing: "border-box", marginBottom: 12,
          }}
        />
        {error && <div style={{ color: "#ef4444", fontSize: 12, marginBottom: 12 }}>Incorrect passphrase</div>}
        <button
          onClick={attempt}
          style={{
            width: "100%", background: "#2b9d90", border: "none", color: "#fff",
            padding: "12px", fontSize: 14, cursor: "pointer", fontFamily: "'DM Mono', monospace",
            letterSpacing: 2, textTransform: "uppercase",
          }}
        >
          Authenticate →
        </button>
      </div>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=DM+Sans:wght@400;600;700&display=swap');
        @keyframes shake {
          0%,100% { transform: translateX(0); }
          20% { transform: translateX(-8px); }
          40% { transform: translateX(8px); }
          60% { transform: translateX(-4px); }
          80% { transform: translateX(4px); }
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
      `}</style>
    </div>
  );
}

// ─── Helpers ───────────────────────────────────────────────────────────────────
function timeAgo(iso: string) {
  const d = new Date(iso);
  const sec = Math.floor((Date.now() - d.getTime()) / 1000);
  if (sec < 60) return `${sec}s ago`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`;
  return `${Math.floor(sec / 86400)}d ago`;
}

function StatusDot({ active }: { active: boolean }) {
  return (
    <span style={{
      display: "inline-block", width: 8, height: 8, borderRadius: "50%",
      background: active ? "#2b9d90" : "#444", marginRight: 8,
      boxShadow: active ? "0 0 6px #2b9d90" : "none",
    }} />
  );
}

// ─── Log Viewer Modal ──────────────────────────────────────────────────────────
function LogModal({ log, onClose }: { log: AgentLog; onClose: () => void }) {
  return (
    <div style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,0.85)",
      display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100,
    }} onClick={onClose}>
      <div style={{
        background: "#0f0f16", border: "1px solid #2b9d90", width: "90vw", maxWidth: 900,
        maxHeight: "80vh", display: "flex", flexDirection: "column",
      }} onClick={e => e.stopPropagation()}>
        <div style={{
          padding: "16px 20px", borderBottom: "1px solid #1a1a24",
          display: "flex", justifyContent: "space-between", alignItems: "center",
        }}>
          <div>
            <span style={{ color: "#2b9d90", fontSize: 11, letterSpacing: 2, textTransform: "uppercase" }}>
              {log.trigger}
            </span>
            <span style={{ color: "#666", fontSize: 12, marginLeft: 16 }}>
              {log.hostname} · {log.app_version} · {log.line_count} lines · {timeAgo(log.created_at)}
            </span>
          </div>
          <button onClick={onClose} style={{
            background: "none", border: "1px solid #333", color: "#666",
            cursor: "pointer", padding: "4px 12px", fontSize: 12,
          }}>✕ close</button>
        </div>
        <pre style={{
          flex: 1, overflow: "auto", padding: 20, margin: 0,
          fontSize: 11, lineHeight: 1.7, color: "#a0a0b0",
          fontFamily: "'DM Mono', monospace", background: "#0a0a0f",
          whiteSpace: "pre-wrap", wordBreak: "break-all",
        }}>
          {log.log_text}
        </pre>
      </div>
    </div>
  );
}

// ─── Main Dashboard ────────────────────────────────────────────────────────────
export default function MavOpsAdmin() {
  const [unlocked, setUnlocked] = useState(() =>
    sessionStorage.getItem("mavops_admin") === "1"
  );
  const [token, setToken] = useState("");
  const [tokenInput, setTokenInput] = useState("");
  const [tab, setTab] = useState<"devices" | "logs" | "errors">("devices");

  // Data
  const [devices, setDevices] = useState<Device[]>([]);
  const [logs, setLogs] = useState<AgentLog[]>([]);
  const [errors, setErrors] = useState<AgentError[]>([]);
  const [errorSummary, setErrorSummary] = useState<ErrorSummary | null>(null);
  const [selectedLog, setSelectedLog] = useState<AgentLog | null>(null);

  // UI state
  const [loading, setLoading] = useState(false);
  const [requestingDevice, setRequestingDevice] = useState<string | null>(null);
  const [filterHostname, setFilterHostname] = useState("");
  const [expandedError, setExpandedError] = useState<number | null>(null);
  const [msg, setMsg] = useState("");

  const handleUnlock = () => {
    sessionStorage.setItem("mavops_admin", "1");
    setUnlocked(true);
  };

  const apiFetch = useCallback(async (path: string, opts: RequestInit = {}) => {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      ...(opts.headers as Record<string, string> || {}),
    };
    if (token) headers["Authorization"] = `Bearer ${token}`;
    const res = await fetch(`${API}${path}`, { ...opts, headers });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  }, [token]);

  const loadDevices = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    try {
      const data = await apiFetch("/settings/devices/");
      setDevices(data);
    } catch (e) {
      setMsg("Failed to load devices. Check token.");
    } finally {
      setLoading(false);
    }
  }, [token, apiFetch]);

  const loadLogs = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    try {
      const qs = filterHostname ? `?hostname=${filterHostname}` : "";
      const data = await apiFetch(`/agent/logs/view/${qs}`);
      setLogs(data.logs || []);
    } catch (e) {
      setMsg("Failed to load logs.");
    } finally {
      setLoading(false);
    }
  }, [token, apiFetch, filterHostname]);

  const loadErrors = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    try {
      const [errData, summData] = await Promise.all([
        apiFetch("/agent/errors/list/?days=7&limit=50"),
        apiFetch("/agent/errors/summary/?days=7"),
      ]);
      setErrors(errData.errors || []);
      setErrorSummary(summData);
    } catch (e) {
      setMsg("Failed to load errors.");
    } finally {
      setLoading(false);
    }
  }, [token, apiFetch]);

  useEffect(() => {
    if (!token) return;
    if (tab === "devices") loadDevices();
    if (tab === "logs") loadLogs();
    if (tab === "errors") loadErrors();
  }, [tab, token, loadDevices, loadLogs, loadErrors]);

  const requestLogs = async (deviceId: string) => {
    setRequestingDevice(deviceId);
    try {
      await apiFetch("/agent/request-logs/", {
        method: "POST",
        body: JSON.stringify({ device_id: deviceId }),
      });
      setMsg(`✓ Log request sent. Refresh in ~15s.`);
      setTimeout(() => setMsg(""), 4000);
    } catch {
      setMsg("Failed to request logs.");
    } finally {
      setRequestingDevice(null);
    }
  };

  const resolveError = async (errorId: number) => {
    try {
      await apiFetch(`/agent/errors/${errorId}/resolve/`, { method: "POST" });
      setErrors(prev => prev.map(e => e.id === errorId ? { ...e, resolved: true } : e));
    } catch {
      setMsg("Failed to resolve error.");
    }
  };

  if (!unlocked) return <PasswordGate onUnlock={handleUnlock} />;

  const s = {
    page: {
      minHeight: "100vh", background: "#0a0a0f", color: "#e0e0e8",
      fontFamily: "'DM Sans', sans-serif",
    } as React.CSSProperties,
    header: {
      borderBottom: "1px solid #1a1a24", padding: "16px 32px",
      display: "flex", alignItems: "center", justifyContent: "space-between",
      background: "#0a0a0f", position: "sticky" as const, top: 0, zIndex: 10,
    },
    mono: { fontFamily: "'DM Mono', monospace" },
    teal: { color: "#2b9d90" },
    card: {
      background: "#0f0f16", border: "1px solid #1a1a24",
      padding: 20, marginBottom: 12,
    },
    badge: (color: string) => ({
      display: "inline-block", padding: "2px 8px",
      background: color + "22", color, fontSize: 11,
      letterSpacing: 1, textTransform: "uppercase" as const,
    }),
  };

  return (
    <div style={s.page}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=DM+Sans:wght@400;600;700&display=swap');
        * { box-sizing: border-box; margin: 0; padding: 0; }
        ::-webkit-scrollbar { width: 6px; height: 6px; }
        ::-webkit-scrollbar-track { background: #0a0a0f; }
        ::-webkit-scrollbar-thumb { background: #2b9d90; }
        input::placeholder { color: #444; }
        button:hover { opacity: 0.85; }
      `}</style>

      {/* Header */}
      <div style={s.header}>
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <div style={{ ...s.mono, ...s.teal, fontSize: 11, letterSpacing: 3, textTransform: "uppercase" }}>
            MavOps
          </div>
          <div style={{ color: "#333", fontSize: 18 }}>|</div>
          <div style={{ fontSize: 14, color: "#888" }}>Operations Dashboard</div>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <input
            value={tokenInput}
            onChange={e => setTokenInput(e.target.value)}
            onKeyDown={e => e.key === "Enter" && setToken(tokenInput)}
            placeholder="Paste Bearer token…"
            style={{
              background: "#0f0f16", border: "1px solid #222", color: "#e0e0e8",
              padding: "8px 12px", fontSize: 12, width: 280, outline: "none",
              ...s.mono,
            }}
          />
          <button
            onClick={() => setToken(tokenInput)}
            style={{
              background: "#2b9d90", border: "none", color: "#fff",
              padding: "8px 16px", fontSize: 12, cursor: "pointer", ...s.mono,
            }}
          >
            Connect
          </button>
          {token && (
            <span style={{ ...s.badge("#2b9d90") }}>● connected</span>
          )}
        </div>
      </div>

      {msg && (
        <div style={{
          background: "#2b9d9011", borderBottom: "1px solid #2b9d9033",
          padding: "10px 32px", fontSize: 13, color: "#2b9d90", ...s.mono,
        }}>
          {msg}
        </div>
      )}

      {/* Tabs */}
      <div style={{ borderBottom: "1px solid #1a1a24", padding: "0 32px", display: "flex", gap: 0 }}>
        {(["devices", "logs", "errors"] as const).map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            style={{
              background: "none", border: "none", color: tab === t ? "#2b9d90" : "#555",
              padding: "14px 20px", fontSize: 13, cursor: "pointer",
              borderBottom: tab === t ? "2px solid #2b9d90" : "2px solid transparent",
              textTransform: "capitalize", ...s.mono, letterSpacing: 1,
            }}
          >
            {t}
          </button>
        ))}
        <div style={{ flex: 1 }} />
        <button
          onClick={() => {
            if (tab === "devices") loadDevices();
            if (tab === "logs") loadLogs();
            if (tab === "errors") loadErrors();
          }}
          style={{
            background: "none", border: "none", color: "#444",
            padding: "14px 20px", fontSize: 12, cursor: "pointer", ...s.mono,
          }}
        >
          ↻ refresh
        </button>
      </div>

      <div style={{ padding: "24px 32px", maxWidth: 1200 }}>

        {/* ── DEVICES TAB ── */}
        {tab === "devices" && (
          <div>
            <div style={{ marginBottom: 20, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div style={{ color: "#555", fontSize: 13, ...s.mono }}>
                {devices.length} devices registered
              </div>
            </div>

            {loading && <div style={{ color: "#444", ...s.mono, fontSize: 13 }}>loading…</div>}

            {devices.map(d => (
              <div key={d.id} style={s.card}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                  <div>
                    <div style={{ display: "flex", alignItems: "center", marginBottom: 6 }}>
                      <StatusDot active={d.is_active} />
                      <span style={{ fontSize: 15, fontWeight: 600 }}>{d.machine_name}</span>
                      <span style={{ color: "#444", fontSize: 12, marginLeft: 12, ...s.mono }}>
                        {d.user}
                      </span>
                    </div>
                    <div style={{ display: "flex", gap: 16, color: "#555", fontSize: 12, ...s.mono }}>
                      <span>{d.os || "unknown os"}</span>
                      <span style={s.teal}>v{d.agent_version || "?"}</span>
                      <span>last seen {timeAgo(d.last_seen)}</span>
                    </div>
                  </div>
                  <div style={{ display: "flex", gap: 8 }}>
                    <button
                      onClick={() => {
                        setFilterHostname(d.machine_name); // hostname filter still works for display
                        setTab("logs");
                      }}
                      style={{
                        background: "none", border: "1px solid #2b9d9066", color: "#2b9d90",
                        padding: "6px 14px", fontSize: 12, cursor: "pointer", ...s.mono,
                      }}
                    >
                      view logs
                    </button>
                    <button
                      onClick={() => d.device_id ? requestLogs(d.device_id) : setMsg("No device_id for this device")}
                      disabled={requestingDevice === d.device_id}
                      style={{
                        background: requestingDevice === d.machine_name ? "#222" : "#2b9d90",
                        border: "none", color: "#fff",
                        padding: "6px 14px", fontSize: 12, cursor: "pointer", ...s.mono,
                      }}
                    >
                      {requestingDevice === d.device_id ? "requesting…" : "request logs"}
                    </button>
                  </div>
                </div>
              </div>
            ))}

            {!loading && !token && (
              <div style={{ color: "#333", fontSize: 13, ...s.mono, paddingTop: 40, textAlign: "center" }}>
                paste your bearer token above to connect
              </div>
            )}
          </div>
        )}

        {/* ── LOGS TAB ── */}
        {tab === "logs" && (
          <div>
            <div style={{ display: "flex", gap: 8, marginBottom: 20 }}>
              <input
                value={filterHostname}
                onChange={e => setFilterHostname(e.target.value)}
                placeholder="Filter by hostname…"
                style={{
                  background: "#0f0f16", border: "1px solid #222", color: "#e0e0e8",
                  padding: "8px 12px", fontSize: 12, width: 260, outline: "none", ...s.mono,
                }}
              />
              <button
                onClick={loadLogs}
                style={{
                  background: "#2b9d90", border: "none", color: "#fff",
                  padding: "8px 16px", fontSize: 12, cursor: "pointer", ...s.mono,
                }}
              >
                search
              </button>
              {filterHostname && (
                <button
                  onClick={() => { setFilterHostname(""); }}
                  style={{
                    background: "none", border: "1px solid #333", color: "#666",
                    padding: "8px 12px", fontSize: 12, cursor: "pointer", ...s.mono,
                  }}
                >
                  clear
                </button>
              )}
            </div>

            {loading && <div style={{ color: "#444", ...s.mono, fontSize: 13 }}>loading…</div>}

            {logs.length === 0 && !loading && (
              <div style={{ color: "#333", fontSize: 13, ...s.mono, paddingTop: 40, textAlign: "center" }}>
                no logs yet — deploy updated agent and wait for first shipment (every 30 min)
              </div>
            )}

            {logs.map(l => (
              <div key={l.id} style={{ ...s.card, cursor: "pointer" }} onClick={() => setSelectedLog(l)}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <div>
                    <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 4 }}>
                      <span style={{ fontSize: 14, fontWeight: 600 }}>{l.hostname}</span>
                      <span style={s.badge(l.trigger === "error" ? "#ef4444" : l.trigger === "on_demand" ? "#f59e0b" : "#2b9d90")}>
                        {l.trigger}
                      </span>
                    </div>
                    <div style={{ color: "#555", fontSize: 12, ...s.mono }}>
                      {l.user} · v{l.app_version} · {l.line_count} lines · {timeAgo(l.created_at)}
                    </div>
                  </div>
                  <div style={{ color: "#2b9d90", fontSize: 12, ...s.mono }}>
                    view →
                  </div>
                </div>
                <pre style={{
                  marginTop: 10, fontSize: 10, color: "#444", ...s.mono,
                  whiteSpace: "pre-wrap", lineHeight: 1.6,
                  maxHeight: 60, overflow: "hidden",
                }}>
                  {l.log_text.split("\n").slice(-3).join("\n")}
                </pre>
              </div>
            ))}
          </div>
        )}

        {/* ── ERRORS TAB ── */}
        {tab === "errors" && (
          <div>
            {errorSummary && (
              <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12, marginBottom: 24 }}>
                {[
                  { label: "Total (7d)", value: errorSummary.total_errors, color: "#e0e0e8" },
                  { label: "Unresolved", value: errorSummary.unresolved, color: errorSummary.unresolved > 0 ? "#ef4444" : "#2b9d90" },
                  { label: "Error Types", value: errorSummary.by_error_type.length, color: "#f59e0b" },
                ].map(stat => (
                  <div key={stat.label} style={{ ...s.card, textAlign: "center" }}>
                    <div style={{ fontSize: 28, fontWeight: 700, color: stat.color, ...s.mono }}>
                      {stat.value}
                    </div>
                    <div style={{ color: "#555", fontSize: 11, marginTop: 4, letterSpacing: 1, textTransform: "uppercase" }}>
                      {stat.label}
                    </div>
                  </div>
                ))}
              </div>
            )}

            {errorSummary && errorSummary.by_error_type.length > 0 && (
              <div style={{ ...s.card, marginBottom: 24 }}>
                <div style={{ color: "#555", fontSize: 11, letterSpacing: 2, textTransform: "uppercase", marginBottom: 12 }}>
                  By Type
                </div>
                <div style={{ display: "flex", flexWrap: "wrap" as const, gap: 8 }}>
                  {errorSummary.by_error_type.map(t => (
                    <div key={t.error_type} style={{
                      background: "#1a0a0a", border: "1px solid #ef444433",
                      padding: "4px 12px", fontSize: 12, ...s.mono,
                    }}>
                      <span style={{ color: "#ef4444" }}>{t.count}×</span>
                      <span style={{ color: "#888", marginLeft: 8 }}>{t.error_type}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {loading && <div style={{ color: "#444", ...s.mono, fontSize: 13 }}>loading…</div>}

            {errors.map(e => (
              <div key={e.id} style={{
                ...s.card,
                borderColor: e.resolved ? "#1a1a24" : "#ef444433",
                opacity: e.resolved ? 0.5 : 1,
              }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                  <div style={{ flex: 1 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
                      <span style={s.badge(e.resolved ? "#555" : "#ef4444")}>
                        {e.resolved ? "resolved" : "open"}
                      </span>
                      <span style={{ fontSize: 14, fontWeight: 600, ...s.mono, color: "#e0e0e8" }}>
                        {e.error_type}
                      </span>
                    </div>
                    <div style={{ color: "#888", fontSize: 12, marginBottom: 4 }}>
                      {e.error_message.slice(0, 120)}{e.error_message.length > 120 ? "…" : ""}
                    </div>
                    <div style={{ color: "#444", fontSize: 11, ...s.mono }}>
                      {e.user || "?"} · {e.hostname} · v{e.app_version} · {timeAgo(e.created_at)}
                    </div>
                  </div>
                  <div style={{ display: "flex", gap: 8, marginLeft: 16 }}>
                    <button
                      onClick={() => setExpandedError(expandedError === e.id ? null : e.id)}
                      style={{
                        background: "none", border: "1px solid #333", color: "#666",
                        padding: "4px 10px", fontSize: 11, cursor: "pointer", ...s.mono,
                      }}
                    >
                      {expandedError === e.id ? "collapse" : "details"}
                    </button>
                    {!e.resolved && (
                      <button
                        onClick={() => resolveError(e.id)}
                        style={{
                          background: "none", border: "1px solid #2b9d9066", color: "#2b9d90",
                          padding: "4px 10px", fontSize: 11, cursor: "pointer", ...s.mono,
                        }}
                      >
                        resolve
                      </button>
                    )}
                  </div>
                </div>
                {expandedError === e.id && (
                  <pre style={{
                    marginTop: 12, padding: 12, background: "#0a0a0f",
                    fontSize: 10, color: "#666", ...s.mono,
                    whiteSpace: "pre-wrap", wordBreak: "break-all",
                    maxHeight: 200, overflow: "auto", lineHeight: 1.6,
                  }}>
                    {e.error_message}
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