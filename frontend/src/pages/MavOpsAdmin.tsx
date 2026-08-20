import { useState, useEffect, useCallback, type CSSProperties } from "react";

import {
  TemplatePickerModal,
  SuggestRulesWizard,
  ExplainBlockModal,
} from "./MavOpsAdminRules";

const API = "https://timetracker-api-k375.onrender.com/api";
const SEAT_PRICES: Record<string, number> = { professional: 34.99, executive: 49.99, trial: 0, none: 0 };

// ─── Types ────────────────────────────────────────────────────────────────────
interface OrgHealth { status: "ok" | "warn" | "critical"; reasons: string[]; grace_days_left?: number | null; }
interface Org {
  id: number; name: string; plan: string; seat_count: number;
  member_count: number; active_devices: number;
  deactivated_devices?: number; mavops_archived?: boolean; show_client_widget?: boolean; health?: OrgHealth;
  industry_type?: string;
  seat_grace_deadline?: string | null;
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
interface OrgMember {
  user_id: number; username: string; email: string;
  first_name: string; last_name: string; role: string;
}

// ─── Routing Rules types ──────────────────────────────────────────────────────
interface OrgRuleStats {
  id: number; name: string;
  rule_count: number; enabled_count: number;
  custom_count: number; default_count: number;
  total_fires: number; last_fire_at: string | null;
}
interface RoutingRule {
  id: number;
  match_type: "exe" | "exe_family" | "title_contains" | "title_regex" | "file_path_contains";
  match_value: string;
  action: "route_to_client" | "never_switch_away" | "suppress";
  target_client_id: number | null;
  target_client_name: string | null;
  priority: number; enabled: boolean; description: string;
  is_default: boolean;
  fire_count: number; last_fired_at: string | null;
  created_by: string | null; created_at: string;
}
interface RuleClient { id: number; name: string; }
interface TopRule {
  org_id: number; org_name: string; rule_id: number;
  match_type: string; match_value: string;
  target_client_name: string | null;
  fire_count: number; last_fired_at: string | null;
}
interface TestResult {
  input: { title: string; exe: string; file_path: string };
  matches: Array<{
    rule_id: number; match_type: string; match_value: string;
    action: string; target_client_name: string | null;
    priority: number; description: string;
  }>;
  winning_rule_id: number | null;
  outcome: { action: string; message: string; target_client_name?: string; };
}

// ─── Theme ────────────────────────────────────────────────────────────────────
// Verticals an org can be set to. Mirrors INDUSTRY_TYPES server-side; the
// server validates, this is only for display order and wording.
const INDUSTRY_LABELS: Record<string, string> = {
  general: "General",
  cpa: "CPA / Accounting",
  legal: "Law Firm",
  ai_consulting: "AI / Tech Consulting",
  marketing: "Marketing Agency",
};

const T = {
  bg:        "#0f1419",   // was "#111827" — slightly deeper, warmer black
  surface:   "#1a2231",   // was "#1e2533" — touch warmer, more depth from bg
  surfaceHi: "#222d3f",   // NEW — for hover states + emphasized cards
  border:    "#2a3548",   // was "#2d3748" — slightly more visible
  borderHi:  "#3d4a63",   // was "#4a5568" — accent borders
  text:      "#f1f5f9",   // was "#f0f4f8" — barely changed, slightly cooler white
  textSub:   "#b0bccd",   // was "#94a3b8" — ⬆ now AA-compliant on bg
  textMuted: "#8593a8",   // was "#64748b" — ⬆ MUCH better readability
  teal:      "#2dd4bf",   // was "#2b9d90" — brighter, more modern teal
  tealHi:    "#5eead4",   // was "#34b5a7" — softer hover variant
  yellow:    "#fbbf24",   // was "#f59e0b" — warmer
  red:       "#f87171",   // was "#ef4444" — softer, less alarming
  purple:    "#c4b5fd",   // was "#a78bfa" — gentler
  green:     "#34d399",   // was "#10b981" — brighter, stays readable
};

const mono = { fontFamily: "'DM Mono', monospace" };
const card: React.CSSProperties = {
  background: T.surface, border: `1px solid ${T.border}`,
  padding: 20, marginBottom: 10, borderRadius: 8,  // was 6
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
function Btn({ label, onClick, color = T.teal, outline = false, disabled = false, small = false, tiny = false }: {
  label: string; onClick: () => void; color?: string; outline?: boolean; disabled?: boolean; small?: boolean; tiny?: boolean;
}) {
  return (
    <button onClick={onClick} disabled={disabled} style={{
      background: outline ? T.bg : disabled ? T.textMuted + "33" : color,
      border: `1px solid ${disabled ? T.textMuted + "44" : color}`,
      color: outline ? color : disabled ? T.textMuted : "#fff",
      padding: tiny ? "4px 9px" : small ? "5px 12px" : "7px 16px",
      fontSize: tiny ? 11 : small ? 12 : 13, cursor: disabled ? "default" : "pointer",
      borderRadius: 4, ...mono, opacity: disabled ? 0.6 : 1,
      whiteSpace: "nowrap" as const, fontWeight: 500,
    }}>
      {label}
    </button>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// ─── Routing Rules Tab (v1.2.95) ────────────────────────────────────────────────
// ═══════════════════════════════════════════════════════════════════════════════

interface RoutingRulesTabProps {
  apiFetch: (path: string, opts?: RequestInit) => Promise<any>;
  flash: (msg: string, type?: "ok" | "err") => void;
  filterOrg: number | null;
  setFilterOrg: (id: number | null) => void;
}

function RoutingRulesTab({ apiFetch, flash, filterOrg, setFilterOrg }: RoutingRulesTabProps) {
  const [orgStats, setOrgStats] = useState<OrgRuleStats[]>([]);
  const [topRules, setTopRules] = useState<TopRule[]>([]);
  const [loading, setLoading] = useState(false);

  const [selectedOrg, setSelectedOrg] = useState<OrgRuleStats | null>(null);
  const [rulesForOrg, setRulesForOrg] = useState<RoutingRule[]>([]);
  const [clientsForOrg, setClientsForOrg] = useState<RuleClient[]>([]);
  const [loadingRules, setLoadingRules] = useState(false);

  const [showRuleForm, setShowRuleForm] = useState(false);
  const [editingRule, setEditingRule] = useState<RoutingRule | null>(null);
  const [showCopyModal, setShowCopyModal] = useState(false);

  const [showTemplatePicker, setShowTemplatePicker] = useState(false);
  const [showSuggestWizard, setShowSuggestWizard] = useState(false);

  const [testerInput, setTesterInput] = useState({ title: "", exe: "", file_path: "" });
  const [testerResult, setTesterResult] = useState<TestResult | null>(null);

  const loadOverview = useCallback(async () => {
    setLoading(true);
    try {
      const [orgsRes, topRes] = await Promise.all([
        apiFetch("/mavops/routing-rules/orgs/"),
        apiFetch("/mavops/routing-rules/top-firing/").catch(() => ({ rules: [] })),
      ]);
      setOrgStats(orgsRes.orgs || []);
      setTopRules(topRes.rules || []);
    } catch { flash("Failed to load rules overview.", "err"); }
    finally { setLoading(false); }
  }, [apiFetch, flash]);

  const loadOrgRules = useCallback(async (orgId: number) => {
    setLoadingRules(true);
    try {
      const d = await apiFetch(`/mavops/routing-rules/orgs/${orgId}/`);
      setRulesForOrg(d.rules || []);
      setClientsForOrg(d.clients || []);
      const existing = orgStats.find(o => o.id === orgId);
      setSelectedOrg(existing || {
        id: orgId, name: d.org?.name || `org #${orgId}`,
        rule_count: d.rules?.length || 0, enabled_count: 0, custom_count: 0,
        default_count: 0, total_fires: 0, last_fire_at: null,
      });
    } catch { flash("Failed to load rules.", "err"); }
    finally { setLoadingRules(false); }
  }, [apiFetch, flash, orgStats]);

  useEffect(() => { loadOverview(); }, [loadOverview]);

  // Auto-drill if user clicked a "rules" quick-link on an org card
  useEffect(() => {
    if (filterOrg && !selectedOrg && orgStats.length > 0) {
      loadOrgRules(filterOrg);
    }
  }, [filterOrg, selectedOrg, orgStats.length, loadOrgRules]);

  const toggleRule = async (rule: RoutingRule) => {
    if (!selectedOrg) return;
    try {
      await apiFetch(`/mavops/routing-rules/orgs/${selectedOrg.id}/${rule.id}/`, {
        method: "PATCH", body: JSON.stringify({ enabled: !rule.enabled }),
      });
      loadOrgRules(selectedOrg.id);
    } catch { flash("Toggle failed.", "err"); }
  };

  const deleteRule = async (rule: RoutingRule) => {
    if (!selectedOrg) return;
    if (rule.is_default) { flash("Default rules can only be disabled.", "err"); return; }
    if (!confirm(`Delete rule "${rule.match_value}"?`)) return;
    try {
      await apiFetch(`/mavops/routing-rules/orgs/${selectedOrg.id}/${rule.id}/`, { method: "DELETE" });
      flash("✓ Rule deleted");
      loadOrgRules(selectedOrg.id);
    } catch (e: any) { flash(`Delete failed: ${e.message}`, "err"); }
  };

  const runTest = async () => {
    if (!selectedOrg) return;
    if (!testerInput.title && !testerInput.exe && !testerInput.file_path) {
      flash("Provide at least title, exe, or file path.", "err");
      return;
    }
    try {
      const d = await apiFetch(`/mavops/routing-rules/orgs/${selectedOrg.id}/test/`, {
        method: "POST", body: JSON.stringify(testerInput),
      });
      setTesterResult(d);
    } catch { flash("Test failed.", "err"); }
  };

  const exitOrgView = () => {
    setSelectedOrg(null);
    setRulesForOrg([]);
    setClientsForOrg([]);
    setTesterResult(null);
    setTesterInput({ title: "", exe: "", file_path: "" });
    setFilterOrg(null);
  };

  // ─── Overview (no org selected) ──
  if (!selectedOrg) {
    const totalRules = orgStats.reduce((s, o) => s + o.rule_count, 0);
    const totalFires = orgStats.reduce((s, o) => s + o.total_fires, 0);
    const orgsWithRules = orgStats.filter(o => o.rule_count > 0).length;

    return (
      <div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 12, marginBottom: 20 }}>
          <StatCard label="Orgs with Rules" value={orgsWithRules} color={T.text} />
          <StatCard label="Total Rules" value={totalRules} color={T.purple} />
          <StatCard label="Total Fires" value={totalFires} color={T.green} />
          <StatCard label="Top Firing Rules" value={topRules.length} color={T.teal} />
        </div>

        {topRules.length > 0 && (
          <div style={{ ...card, marginBottom: 20 }}>
            <div style={{ color: T.textMuted, fontSize: 11, letterSpacing: 2, textTransform: "uppercase" as const, marginBottom: 12, fontWeight: 600 }}>
              Top Firing Rules — All Orgs
            </div>
            {topRules.map(r => (
              <div key={`${r.org_id}-${r.rule_id}`}
                onClick={() => loadOrgRules(r.org_id)}
                style={{
                  display: "flex", alignItems: "center", justifyContent: "space-between",
                  padding: "8px 0", borderBottom: `1px solid ${T.border}`, cursor: "pointer",
                }}>
                <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  <OrgPill name={r.org_name} />
                  <code style={{ fontSize: 12, color: T.textSub, ...mono, background: T.bg, padding: "2px 8px", borderRadius: 3 }}>
                    {r.match_type}={r.match_value}
                  </code>
                  {r.target_client_name && (
                    <span style={{ fontSize: 12, color: T.textMuted, ...mono }}>→ {r.target_client_name}</span>
                  )}
                </div>
                <div style={{ display: "flex", gap: 16, alignItems: "center" }}>
                  <span style={{ ...mono, fontSize: 13, color: T.green, fontWeight: 700 }}>{r.fire_count}×</span>
                  {r.last_fired_at && (
                    <span style={{ ...mono, fontSize: 11, color: T.textMuted }}>{timeAgo(r.last_fired_at)}</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        {loading && <div style={{ color: T.textMuted, ...mono, fontSize: 13, paddingTop: 12 }}>loading…</div>}

        {orgStats.length > 0 && (
          <div style={{ ...card }}>
            <div style={{ color: T.textMuted, fontSize: 11, letterSpacing: 2, textTransform: "uppercase" as const, marginBottom: 12, fontWeight: 600 }}>
              All Orgs
            </div>
            {orgStats.map(o => (
              <div key={o.id}
                onClick={() => loadOrgRules(o.id)}
                style={{
                  display: "flex", alignItems: "center", justifyContent: "space-between",
                  padding: "10px 0", borderBottom: `1px solid ${T.border}`, cursor: "pointer",
                }}>
                <div style={{ display: "flex", alignItems: "center", gap: 10, flex: 1 }}>
                  <span style={{ fontSize: 14, fontWeight: 600, color: T.text }}>{o.name}</span>
                  <span style={{ color: T.textMuted, fontSize: 11, ...mono }}>id {o.id}</span>
                </div>
                <div style={{ display: "flex", gap: 24, alignItems: "center", color: T.textSub, fontSize: 12, ...mono }}>
                  <span>{o.rule_count} rule{o.rule_count === 1 ? "" : "s"}</span>
                  <span style={{ color: o.enabled_count === o.rule_count ? T.green : T.yellow }}>
                    {o.enabled_count} enabled
                  </span>
                  <span>{o.default_count}d / {o.custom_count}c</span>
                  <span style={{ color: T.green, fontWeight: 600 }}>{o.total_fires} fires</span>
                  {o.last_fire_at && <span style={{ color: T.textMuted }}>{timeAgo(o.last_fire_at)}</span>}
                  <span style={{ color: T.teal, fontWeight: 600 }}>manage →</span>
                </div>
              </div>
            ))}
          </div>
        )}

        {orgStats.length === 0 && !loading && (
          <div style={{ color: T.textMuted, fontSize: 14, ...mono, paddingTop: 40, textAlign: "center" }}>
            no orgs with routing rules yet
          </div>
        )}
      </div>
    );
  }

  // ─── Per-org view ──
  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          <button onClick={exitOrgView} style={{ background: "none", border: "none", color: T.textSub, fontSize: 13, cursor: "pointer", ...mono }}>← all orgs</button>
          <span style={{ color: T.textMuted }}>/</span>
          <span style={{ fontSize: 16, fontWeight: 700, color: T.text }}>{selectedOrg.name}</span>
          <span style={{ ...mono, fontSize: 11, color: T.textMuted }}>id {selectedOrg.id}</span>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <Btn label="copy from another org" onClick={() => setShowCopyModal(true)} outline color={T.textSub} small />
          <Btn label="✨ suggest rules" onClick={() => setShowSuggestWizard(true)} color={T.purple} small />
          <Btn label="+ new rule" onClick={() => setShowTemplatePicker(true)} small />
          <Btn label="+ raw" onClick={() => { setEditingRule(null); setShowRuleForm(true); }} outline color={T.textMuted} small />
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 12, marginBottom: 20 }}>
        <StatCard label="Total Rules" value={rulesForOrg.length} color={T.text} />
        <StatCard label="Enabled" value={rulesForOrg.filter(r => r.enabled).length} color={T.green} />
        <StatCard label="Custom" value={rulesForOrg.filter(r => !r.is_default).length} color={T.purple} />
        <StatCard label="Total Fires" value={rulesForOrg.reduce((s, r) => s + r.fire_count, 0)} color={T.teal} />
      </div>

      {/* Tester */}
      <div style={{ ...card, marginBottom: 20 }}>
        <div style={{ color: T.textMuted, fontSize: 11, letterSpacing: 2, textTransform: "uppercase" as const, marginBottom: 12, fontWeight: 600 }}>
          Test a Window
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr auto", gap: 8, marginBottom: 10 }}>
          <input value={testerInput.title} onChange={e => setTesterInput({ ...testerInput, title: e.target.value })}
            placeholder="window title"
            style={{ background: T.bg, border: `1px solid ${T.border}`, color: T.text, padding: "7px 12px", fontSize: 12, outline: "none", borderRadius: 4, ...mono }} />
          <input value={testerInput.exe} onChange={e => setTesterInput({ ...testerInput, exe: e.target.value })}
            placeholder="exe (e.g. utw25.exe)"
            style={{ background: T.bg, border: `1px solid ${T.border}`, color: T.text, padding: "7px 12px", fontSize: 12, outline: "none", borderRadius: 4, ...mono }} />
          <input value={testerInput.file_path} onChange={e => setTesterInput({ ...testerInput, file_path: e.target.value })}
            placeholder="file path (optional)"
            style={{ background: T.bg, border: `1px solid ${T.border}`, color: T.text, padding: "7px 12px", fontSize: 12, outline: "none", borderRadius: 4, ...mono }} />
          <Btn label="test" onClick={runTest} small />
        </div>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" as const }}>
          {[
            { label: "UltraTax (no return)", t: "UltraTax CS", e: "uts25.exe", p: "" },
            { label: "TaxWise return", t: "TaxWise 2024 : 1040 : SMITH, JOHN", e: "utw24.exe", p: "" },
            { label: "QB empty flash", t: " QuickBooks Accountant Desktop Plus 2024", e: "qbw.exe", p: "" },
            { label: "Excel file", t: "Budget.xlsx - Microsoft Excel", e: "excel.exe", p: "C:\\Users\\wayne\\Documents\\Budget.xlsx" },
          ].map(q => (
            <button key={q.label} onClick={() => { setTesterInput({ title: q.t, exe: q.e, file_path: q.p }); setTesterResult(null); }}
              style={{ background: T.bg, border: `1px solid ${T.border}`, color: T.textMuted, padding: "3px 10px", fontSize: 11, cursor: "pointer", borderRadius: 3, ...mono }}>
              {q.label}
            </button>
          ))}
        </div>
        {testerResult && (
          <div style={{ marginTop: 14, padding: 12, background: T.bg, borderRadius: 4, border: `1px solid ${T.border}` }}>
            <div style={{
              padding: "6px 10px", marginBottom: 10, borderRadius: 3,
              background: testerResult.outcome.action === "route_to_client" ? T.green + "20" :
                          testerResult.outcome.action === "never_switch_away" ? T.yellow + "20" :
                          testerResult.outcome.action === "suppress" ? T.textMuted + "20" : T.border,
              color: testerResult.outcome.action === "route_to_client" ? T.green :
                     testerResult.outcome.action === "never_switch_away" ? T.yellow :
                     testerResult.outcome.action === "suppress" ? T.textMuted : T.textSub,
              fontSize: 12, ...mono, fontWeight: 600,
            }}>
              {testerResult.outcome.message}
            </div>
            {testerResult.matches.length > 0 ? (
              <div>
                <div style={{ fontSize: 11, color: T.textMuted, marginBottom: 6, ...mono }}>
                  {testerResult.matches.length} match{testerResult.matches.length === 1 ? "" : "es"} (highest priority wins):
                </div>
                {testerResult.matches.map((m, i) => (
                  <div key={m.rule_id} style={{
                    padding: "6px 10px", fontSize: 12, ...mono,
                    background: i === 0 ? T.teal + "15" : "transparent",
                    borderLeft: i === 0 ? `2px solid ${T.teal}` : "2px solid transparent",
                    color: i === 0 ? T.text : T.textSub, marginBottom: 3,
                  }}>
                    {i === 0 && <span style={{ color: T.teal, marginRight: 6 }}>✓</span>}
                    <code style={{ color: T.text }}>{m.match_type}={m.match_value}</code>
                    {m.target_client_name && <> → <strong>{m.target_client_name}</strong></>}
                    <span style={{ color: T.textMuted, marginLeft: 8 }}>(p{m.priority})</span>
                  </div>
                ))}
              </div>
            ) : (
              <div style={{ fontSize: 12, color: T.textMuted, ...mono }}>
                no match — agent falls through to regex / learned / AI tiers
              </div>
            )}
          </div>
        )}
      </div>

      {loadingRules && <div style={{ color: T.textMuted, ...mono, fontSize: 13 }}>loading…</div>}

      {rulesForOrg.length === 0 && !loadingRules && (
        <div style={{ ...card, textAlign: "center" as const, padding: 40 }}>
          <div style={{ color: T.textMuted, fontSize: 14 }}>no rules yet for this org</div>
          <div style={{ marginTop: 16 }}>
            <Btn label="+ create first rule" onClick={() => { setEditingRule(null); setShowRuleForm(true); }} small />
          </div>
        </div>
      )}

      {rulesForOrg.map(r => (
        <div key={r.id} style={{ ...card, padding: "14px 20px", opacity: r.enabled ? 1 : 0.55 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <div style={{ flex: 1 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
                <code style={{ fontSize: 12, color: T.text, ...mono, background: T.bg, padding: "3px 10px", borderRadius: 3, fontWeight: 600 }}>
                  {r.match_type}={r.match_value}
                </code>
                {r.action === "route_to_client" && r.target_client_name && (
                  <span style={{ fontSize: 13, color: T.textSub }}>→ <strong style={{ color: T.text }}>{r.target_client_name}</strong></span>
                )}
                {r.action === "never_switch_away" && <Badge label="hold current" color={T.yellow} />}
                {r.action === "suppress" && <Badge label="suppress" color={T.textMuted} />}
                {r.is_default ? <Badge label="default" color={T.teal} /> : <Badge label="custom" color={T.purple} />}
              </div>
              <div style={{ display: "flex", gap: 16, alignItems: "center", fontSize: 11, color: T.textMuted, ...mono }}>
                <span>priority {r.priority}</span>
                <span style={{ color: r.fire_count > 0 ? T.green : T.textMuted }}>{r.fire_count} fires</span>
                {r.last_fired_at && <span>last fired {timeAgo(r.last_fired_at)}</span>}
                {r.description && <span style={{ color: T.textSub, fontStyle: "italic" as const }}>"{r.description}"</span>}
              </div>
            </div>
            <div style={{ display: "flex", gap: 6 }}>
              <Btn label={r.enabled ? "enabled" : "disabled"} onClick={() => toggleRule(r)} color={r.enabled ? T.green : T.textMuted} outline small />
              <Btn label="edit" onClick={() => { setEditingRule(r); setShowRuleForm(true); }} outline color={T.textSub} small />
              {!r.is_default && <Btn label="delete" onClick={() => deleteRule(r)} outline color={T.red} small />}
            </div>
          </div>
        </div>
      ))}

      {showRuleForm && selectedOrg && (
        <RuleFormModal
          orgId={selectedOrg.id}
          orgName={selectedOrg.name}
          clients={clientsForOrg}
          rule={editingRule}
          apiFetch={apiFetch}
          flash={flash}
          onClose={() => { setShowRuleForm(false); setEditingRule(null); }}
          onSaved={() => { setShowRuleForm(false); setEditingRule(null); loadOrgRules(selectedOrg.id); }}
        />
      )}

      {showCopyModal && selectedOrg && (
        <CopyRulesModal
          destOrgId={selectedOrg.id}
          destOrgName={selectedOrg.name}
          allOrgs={orgStats.filter(o => o.id !== selectedOrg.id)}
          apiFetch={apiFetch}
          flash={flash}
          onClose={() => setShowCopyModal(false)}
          onCopied={() => { setShowCopyModal(false); loadOrgRules(selectedOrg.id); }}
        />
      )}

      {showTemplatePicker && selectedOrg && (
        <TemplatePickerModal
          orgId={selectedOrg.id}
          orgName={selectedOrg.name}
          apiFetch={apiFetch}
          flash={flash}
          onClose={() => setShowTemplatePicker(false)}
          onRuleCreated={() => loadOrgRules(selectedOrg.id)}
        />
      )}

      {showSuggestWizard && selectedOrg && (
        <SuggestRulesWizard
          orgId={selectedOrg.id}
          orgName={selectedOrg.name}
          apiFetch={apiFetch}
          flash={flash}
          onClose={() => setShowSuggestWizard(false)}
          onRulesCreated={(count) => {
            flash(`✓ Created ${count} rule${count === 1 ? "" : "s"}`);
            loadOrgRules(selectedOrg.id);
          }}
        />
      )}
    </div>
  );
}

// ─── RuleFormModal ───────────────────────────────────────────────────────────

function RuleFormModal({
  orgId, orgName, clients, rule, apiFetch, flash, onClose, onSaved,
}: {
  orgId: number; orgName: string; clients: RuleClient[]; rule: RoutingRule | null;
  apiFetch: (path: string, opts?: RequestInit) => Promise<any>;
  flash: (msg: string, type?: "ok" | "err") => void;
  onClose: () => void; onSaved: () => void;
}) {
  const isEdit = !!rule;
  const [form, setForm] = useState({
    match_type: rule?.match_type || "exe_family",
    match_value: rule?.match_value || "",
    action: rule?.action || "route_to_client",
    target_client_id: rule?.target_client_id?.toString() || "",
    priority: rule?.priority ?? 100,
    description: rule?.description || "",
    enabled: rule?.enabled ?? true,
  });
  const [saving, setSaving] = useState(false);

  const save = async () => {
    if (!form.match_value.trim()) { flash("Match value required.", "err"); return; }
    if (form.action === "route_to_client" && !form.target_client_id) {
      flash("Target client required when action is route_to_client.", "err");
      return;
    }
    setSaving(true);
    try {
      const body = { ...form, target_client_id: form.target_client_id ? Number(form.target_client_id) : null };
      if (isEdit && rule) {
        await apiFetch(`/mavops/routing-rules/orgs/${orgId}/${rule.id}/`, { method: "PATCH", body: JSON.stringify(body) });
        flash("✓ Rule updated");
      } else {
        await apiFetch(`/mavops/routing-rules/orgs/${orgId}/create/`, { method: "POST", body: JSON.stringify(body) });
        flash("✓ Rule created");
      }
      onSaved();
    } catch (e: any) { flash(`Save failed: ${e.message}`, "err"); }
    finally { setSaving(false); }
  };

  const placeholder: Record<string, string> = {
    exe: "utw25.exe", exe_family: "taxwise", title_contains: "Tax Return",
    title_regex: ".*1040.*", file_path_contains: "\\Tax Returns\\",
  };
  const input: React.CSSProperties = {
    width: "100%", background: T.bg, border: `1px solid ${T.border}`,
    color: T.text, padding: "8px 12px", fontSize: 13, outline: "none",
    borderRadius: 4, ...mono, boxSizing: "border-box" as const,
  };
  const labelStyle: React.CSSProperties = {
    display: "block", color: T.textMuted, fontSize: 10,
    letterSpacing: 1.5, textTransform: "uppercase" as const,
    marginBottom: 6, fontWeight: 600,
  };

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.75)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100 }} onClick={onClose}>
      <div style={{ background: T.surface, border: `1px solid ${T.teal}`, width: "90vw", maxWidth: 640, borderRadius: 8, maxHeight: "90vh", overflowY: "auto" as const }} onClick={e => e.stopPropagation()}>
        <div style={{ padding: "16px 20px", borderBottom: `1px solid ${T.border}` }}>
          <div style={{ fontSize: 15, fontWeight: 700, color: T.text }}>{isEdit ? "Edit Rule" : "New Rule"}</div>
          <div style={{ fontSize: 11, color: T.textMuted, ...mono, marginTop: 2 }}>{orgName}</div>
        </div>

        <div style={{ padding: 20, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
          <div>
            <label style={labelStyle}>Match Type</label>
            <select value={form.match_type} onChange={e => setForm({ ...form, match_type: e.target.value as any })}
              disabled={rule?.is_default} style={input}>
              <option value="exe_family">App Family (e.g. taxwise)</option>
              <option value="exe">Exact Exe Name</option>
              <option value="title_contains">Title Contains</option>
              <option value="title_regex">Title Regex</option>
              <option value="file_path_contains">File Path Contains</option>
            </select>
          </div>
          <div>
            <label style={labelStyle}>Match Value</label>
            <input value={form.match_value} onChange={e => setForm({ ...form, match_value: e.target.value })}
              placeholder={placeholder[form.match_type]} disabled={rule?.is_default} style={input} />
          </div>

          <div>
            <label style={labelStyle}>Action</label>
            <select value={form.action} onChange={e => setForm({ ...form, action: e.target.value as any })} style={input}>
              <option value="route_to_client">Route to Client</option>
              <option value="never_switch_away">Never Switch Away</option>
              <option value="suppress">Suppress</option>
            </select>
          </div>

          {form.action === "route_to_client" && (
            <div>
              <label style={labelStyle}>Target Client</label>
              <select value={form.target_client_id} onChange={e => setForm({ ...form, target_client_id: e.target.value })} style={input}>
                <option value="">— select a client —</option>
                {clients.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </div>
          )}

          <div>
            <label style={labelStyle}>Priority</label>
            <input type="number" value={form.priority} onChange={e => setForm({ ...form, priority: Number(e.target.value) })} style={input} />
            <div style={{ fontSize: 10, color: T.textMuted, ...mono, marginTop: 4 }}>
              500 hard · 300 default · 100 soft
            </div>
          </div>

          <div>
            <label style={labelStyle}>Enabled</label>
            <label style={{ display: "flex", alignItems: "center", gap: 8, paddingTop: 10, color: T.text, fontSize: 13, cursor: "pointer" }}>
              <input type="checkbox" checked={form.enabled} onChange={e => setForm({ ...form, enabled: e.target.checked })} />
              {form.enabled ? "active" : "inactive"}
            </label>
          </div>

          <div style={{ gridColumn: "1 / span 2" }}>
            <label style={labelStyle}>Description (optional)</label>
            <input value={form.description} onChange={e => setForm({ ...form, description: e.target.value })}
              placeholder="human-readable note" style={input} />
          </div>

          {rule?.is_default && (
            <div style={{ gridColumn: "1 / span 2", padding: 12, background: T.teal + "15", border: `1px solid ${T.teal}44`, borderRadius: 4, fontSize: 12, color: T.textSub }}>
              <strong style={{ color: T.teal }}>Default rule:</strong> match_type and match_value are locked.
              You can still change the target, priority, description, or enabled state.
            </div>
          )}
        </div>

        <div style={{ padding: "12px 20px", borderTop: `1px solid ${T.border}`, display: "flex", justifyContent: "flex-end", gap: 8, background: T.bg, borderRadius: "0 0 8px 8px" }}>
          <Btn label="cancel" onClick={onClose} outline color={T.textMuted} small />
          <Btn label={saving ? "saving…" : isEdit ? "save changes" : "create rule"} onClick={save} disabled={saving} small />
        </div>
      </div>
    </div>
  );
}

// ─── CopyRulesModal ──────────────────────────────────────────────────────────

function CopyRulesModal({
  destOrgId, destOrgName, allOrgs, apiFetch, flash, onClose, onCopied,
}: {
  destOrgId: number; destOrgName: string; allOrgs: OrgRuleStats[];
  apiFetch: (path: string, opts?: RequestInit) => Promise<any>;
  flash: (msg: string, type?: "ok" | "err") => void;
  onClose: () => void; onCopied: () => void;
}) {
  const [sourceId, setSourceId] = useState<string>("");
  const [copying, setCopying] = useState(false);

  const copy = async () => {
    if (!sourceId) { flash("Select a source org.", "err"); return; }
    if (!confirm(`Copy rules from source org to ${destOrgName}? Existing rules will not be removed.`)) return;
    setCopying(true);
    try {
      const d = await apiFetch(`/mavops/routing-rules/orgs/${destOrgId}/copy-from/`, {
        method: "POST", body: JSON.stringify({ source_org_id: Number(sourceId) }),
      });
      flash(`✓ Copied ${d.copied} rule(s). Skipped: ${d.skipped_duplicates || 0} dup, ${d.skipped_missing_client || 0} missing client.`);
      onCopied();
    } catch (e: any) { flash(`Copy failed: ${e.message}`, "err"); }
    finally { setCopying(false); }
  };

  const input: React.CSSProperties = {
    width: "100%", background: T.bg, border: `1px solid ${T.border}`,
    color: T.text, padding: "8px 12px", fontSize: 13, outline: "none",
    borderRadius: 4, ...mono, boxSizing: "border-box" as const,
  };

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.75)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100 }} onClick={onClose}>
      <div style={{ background: T.surface, border: `1px solid ${T.purple}`, width: "90vw", maxWidth: 480, borderRadius: 8 }} onClick={e => e.stopPropagation()}>
        <div style={{ padding: "16px 20px", borderBottom: `1px solid ${T.border}` }}>
          <div style={{ fontSize: 15, fontWeight: 700, color: T.text }}>Copy Rules From Another Org</div>
          <div style={{ fontSize: 11, color: T.textMuted, ...mono, marginTop: 2 }}>→ <strong>{destOrgName}</strong></div>
        </div>
        <div style={{ padding: 20 }}>
          <label style={{ display: "block", color: T.textMuted, fontSize: 10, letterSpacing: 1.5, textTransform: "uppercase" as const, marginBottom: 6, fontWeight: 600 }}>
            Source Org
          </label>
          <select value={sourceId} onChange={e => setSourceId(e.target.value)} style={input}>
            <option value="">— select source org —</option>
            {allOrgs.filter(o => o.rule_count > 0).map(o => (
              <option key={o.id} value={o.id}>{o.name} — {o.rule_count} rule{o.rule_count === 1 ? "" : "s"}</option>
            ))}
          </select>
          <div style={{ marginTop: 16, padding: 12, background: T.bg, borderRadius: 4, border: `1px solid ${T.border}`, fontSize: 12, color: T.textSub, lineHeight: 1.6 }}>
            Rules copy as <strong style={{ color: T.purple }}>custom</strong>, not default.
            Duplicates (same match_type + value) and rules with missing target clients are skipped.
          </div>
        </div>
        <div style={{ padding: "12px 20px", borderTop: `1px solid ${T.border}`, display: "flex", justifyContent: "flex-end", gap: 8, background: T.bg, borderRadius: "0 0 8px 8px" }}>
          <Btn label="cancel" onClick={onClose} outline color={T.textMuted} small />
          <Btn label={copying ? "copying…" : "copy rules"} onClick={copy} disabled={!sourceId || copying} color={T.purple} small />
        </div>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// ─── Mismatches Tab — client-name QA (title names a different client than booked) ─
// ═══════════════════════════════════════════════════════════════════════════════
//
// Reuses the same `T`, `mono`, `card`, `Btn`, `Badge`, `OrgPill`, `StatCard`
// already defined in this file.
//
// Reads: GET /api/mavops/mismatches/?org_id=&days=   (via apiFetch)
// The response splits into two buckets:
//   client   — real client<->client mismatches (billing-impacting, e.g. UltraTax
//              forward-fill). The verdict + histogram lead with THIS.
//   internal — firm/admin bucket noise (Internal - Tax ↔ Internal - Accounting,
//              CS Connect firm window). Real + accurate, but not a billing error;
//              shown collapsed below so it never inflates the client signal.

interface MismatchRow {
  block_id: number;
  org_id: number;
  org_name: string | null;
  user: string | null;
  date: string;
  window_title: string;
  app_name: string;
  booked_client_id: number;
  booked_client_name: string;
  looks_like_client_id: number;
  looks_like_client_name: string;
  bucket: "client" | "internal";
  confidence: {
    looks_like_coverage: number;
    abs_hit: number;
    booked_coverage: number;
    top_token_weight: number;
  };
}
interface MismatchBucket {
  total: number;
  returned: number;
  histogram: { date: string; count: number }[];
  top_pairs: { pair: string; count: number }[];
  mismatches: MismatchRow[];
}
interface MismatchResponse {
  params: { org_id: number | null; days: number };
  scanned_blocks: number;
  client: MismatchBucket;
  internal: MismatchBucket;
}

interface MismatchesTabProps {
  apiFetch: (path: string, opts?: RequestInit) => Promise<any>;
  flash: (msg: string, type?: "ok" | "err") => void;
  filterOrg: number | null;
}

// Shared renderer for one bucket's histogram + pairs + flagged list.
// `onReconcile` is only passed for the client bucket (the internal bucket is
// never reconciled). `clientFilter` narrows the flagged list to one booked
// client name (or "" for all).
function BucketDetail({
  bucket, tone, clientFilter, onReconcile, reconcileBusy, hideBulkButton,
}: {
  bucket: MismatchBucket;
  tone: string;
  clientFilter?: string;
  onReconcile?: (blockIds: number[], label: string) => void;
  reconcileBusy?: boolean;
  hideBulkButton?: boolean;
}) {
  const peak = bucket.histogram.length ? Math.max(...bucket.histogram.map(h => h.count)) : 1;
  const rows = clientFilter
    ? bucket.mismatches.filter(m => m.booked_client_name === clientFilter)
    : bucket.mismatches;
  const rowIds = rows.map(r => r.block_id);
  return (
    <>
      {bucket.histogram.length > 0 && (
        <div style={{ ...card, marginBottom: 20 }}>
          <div style={{ color: T.textMuted, fontSize: 11, letterSpacing: 2, textTransform: "uppercase" as const, marginBottom: 14, fontWeight: 600 }}>
            Mismatches per day — clustering in the past = already fixed
          </div>
          <div style={{ display: "flex", alignItems: "flex-end", gap: 3, height: 90 }}>
            {bucket.histogram.map(h => (
              <div key={h.date} title={`${h.date}: ${h.count}`}
                style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: 4 }}>
                <div style={{ width: "100%", height: `${Math.max(6, (h.count / peak) * 74)}px`, background: tone, borderRadius: "2px 2px 0 0", minWidth: 3 }} />
              </div>
            ))}
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", marginTop: 8, color: T.textMuted, fontSize: 10, ...mono }}>
            <span>{bucket.histogram[0].date}</span>
            <span>{bucket.histogram[bucket.histogram.length - 1].date}</span>
          </div>
        </div>
      )}

      {bucket.top_pairs.length > 0 && (
        <div style={{ ...card, marginBottom: 20 }}>
          <div style={{ color: T.textMuted, fontSize: 11, letterSpacing: 2, textTransform: "uppercase" as const, marginBottom: 12, fontWeight: 600 }}>
            Worst pairs — booked → looks like
          </div>
          {bucket.top_pairs.map((p, i) => (
            <div key={i} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "7px 0", borderBottom: i < bucket.top_pairs.length - 1 ? `1px solid ${T.border}` : "none" }}>
              <span style={{ fontSize: 13, color: T.textSub, ...mono }}>{p.pair}</span>
              <span style={{ ...mono, fontSize: 13, color: tone, fontWeight: 700 }}>{p.count}×</span>
            </div>
          ))}
        </div>
      )}

      {rows.length > 0 && (
        <>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, marginBottom: 10 }}>
            <div style={{ color: T.textMuted, fontSize: 11, letterSpacing: 2, textTransform: "uppercase" as const, fontWeight: 600, ...mono }}>
              Flagged blocks ({rows.length}{clientFilter ? ` · ${clientFilter}` : ` of ${bucket.total}`})
            </div>
            {onReconcile && rowIds.length > 0 && !hideBulkButton && (
              <button
                disabled={reconcileBusy}
                onClick={() => onReconcile(rowIds, clientFilter || "all shown")}
                style={{
                  background: tone + "18", border: `1px solid ${tone}`, color: tone,
                  padding: "6px 14px", fontSize: 12, cursor: reconcileBusy ? "default" : "pointer",
                  borderRadius: 4, ...mono, fontWeight: 700, opacity: reconcileBusy ? 0.5 : 1,
                }}>
                {reconcileBusy ? "reconciling…" : `⟲ Reconcile ${rowIds.length} block${rowIds.length > 1 ? "s" : ""}`}
              </button>
            )}
          </div>
          {rows.map(m => (
            <div key={m.block_id} style={{ ...card, padding: "14px 20px" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8, flexWrap: "wrap" as const }}>
                {m.org_name && <OrgPill name={m.org_name} />}
                <span style={{ fontSize: 11, color: T.textMuted, ...mono }}>block {m.block_id}</span>
                <span style={{ fontSize: 11, color: T.textMuted, ...mono }}>{m.date}</span>
                {m.user && <span style={{ fontSize: 11, color: T.textSub, ...mono }}>{m.user}</span>}
                <div style={{ flex: 1 }} />
                {onReconcile && (
                  <button
                    disabled={reconcileBusy}
                    onClick={() => onReconcile([m.block_id], `block ${m.block_id}`)}
                    style={{
                      background: "transparent", border: `1px solid ${T.border}`, color: T.textSub,
                      padding: "3px 10px", fontSize: 11, cursor: reconcileBusy ? "default" : "pointer",
                      borderRadius: 4, ...mono,
                    }}>
                    ⟲ fix
                  </button>
                )}
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8, flexWrap: "wrap" as const }}>
                <span style={{ fontSize: 11, color: T.textMuted, ...mono }}>booked</span>
                <Badge label={m.booked_client_name} color={T.yellow} />
                <span style={{ color: tone, fontSize: 14 }}>→</span>
                <span style={{ fontSize: 11, color: T.textMuted, ...mono }}>title says</span>
                <Badge label={m.looks_like_client_name} color={tone} />
              </div>
              <code style={{ display: "block", fontSize: 12, color: T.textSub, ...mono, background: T.bg, padding: "8px 12px", borderRadius: 4, wordBreak: "break-all" as const }}>
                {m.app_name && <span style={{ color: T.textMuted }}>{m.app_name} — </span>}
                {m.window_title}
              </code>
              <div style={{ display: "flex", gap: 14, marginTop: 8, fontSize: 10, color: T.textMuted, ...mono }}>
                <span>coverage {(m.confidence.looks_like_coverage * 100).toFixed(0)}%</span>
                <span>vs booked {(m.confidence.booked_coverage * 100).toFixed(0)}%</span>
                <span>strength {m.confidence.abs_hit.toFixed(1)}</span>
              </div>
            </div>
          ))}
        </>
      )}
    </>
  );
}

function MismatchesTab({ apiFetch, flash, filterOrg }: MismatchesTabProps) {
  const [data, setData] = useState<MismatchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [days, setDays] = useState(120);
  const [showInternal, setShowInternal] = useState(false);
  const [reconcileBusy, setReconcileBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const p = new URLSearchParams({ days: String(days) });
      if (filterOrg) p.set("org_id", String(filterOrg));
      const d = await apiFetch(`/mavops/mismatches/?${p}`);
      setData(d);
    } catch {
      flash("Failed to load mismatches.", "err");
    } finally {
      setLoading(false);
    }
  }, [apiFetch, flash, filterOrg, days]);

  useEffect(() => { load(); }, [load]);

  // Reconcile: dry-run first (server re-derives the target client from each
  // block's title), show the plan, confirm, then commit. Requires an org
  // (reconcile is per-org). The server ignores any client id we might send —
  // it re-detects from the title — so this is safe.
  const reconcile = useCallback(async (blockIds: number[], label: string) => {
    const org = filterOrg;
    if (!org) {
      flash("Pick a single org (filter) before reconciling.", "err");
      return;
    }
    setReconcileBusy(true);
    try {
      // 1) dry-run
      const dry = await apiFetch(`/mavops/mismatches/reconcile/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ org_id: org, block_ids: blockIds, confirm: false }),
      });
      const n = dry.would_reassign || 0;
      if (n === 0) {
        flash(`Nothing to reconcile for ${label} (${dry.skipped} skipped).`);
        return;
      }
      const catNote = dry.category_will_be_set
        ? `Category will be set to "${dry.category_will_be_set}".`
        : `Category unchanged (only the client is reassigned).`;
      const ok = window.confirm(
        `Reconcile ${n} block${n > 1 ? "s" : ""} for ${label}?\n\n` +
        `Each will be reassigned to the client its title names. ${catNote}\n` +
        `${dry.skipped} block(s) skipped (title no longer names one clear client).`
      );
      if (!ok) return;
      // 2) commit
      const res = await apiFetch(`/mavops/mismatches/reconcile/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ org_id: org, block_ids: blockIds, confirm: true }),
      });
      flash(`Reconciled ${res.reassigned} block${res.reassigned !== 1 ? "s" : ""}.`, "ok");
      await load();
    } catch {
      flash("Reconcile failed.", "err");
    } finally {
      setReconcileBusy(false);
    }
  }, [apiFetch, flash, filterOrg, load]);

  // Verdict runs on the CLIENT bucket only — the money bucket. Internal noise
  // must never trigger the "ongoing" alarm.
  const verdict = (() => {
    if (!data || data.client.histogram.length === 0) return null;
    const newest = data.client.histogram[data.client.histogram.length - 1].date;
    const ageDays = Math.floor((Date.now() - new Date(newest).getTime()) / 86400000);
    return { newest, ageDays, ongoing: ageDays <= 3 };
  })();

  return (
    <div>
      <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 16 }}>
        <span style={{ color: T.textSub, fontSize: 13, ...mono, fontWeight: 600 }}>Client-name mismatches</span>
        {filterOrg && <OrgPill name={`org ${filterOrg}`} />}
        <div style={{ flex: 1 }} />
        <span style={{ color: T.textMuted, fontSize: 12, ...mono }}>lookback</span>
        {[30, 60, 90, 120, 180].map(d => (
          <button key={d} onClick={() => setDays(d)}
            style={{
              background: days === d ? T.teal + "25" : "transparent",
              border: `1px solid ${days === d ? T.teal : T.border}`,
              color: days === d ? T.teal : T.textSub,
              padding: "5px 12px", fontSize: 12, cursor: "pointer", borderRadius: 4, ...mono,
              fontWeight: days === d ? 600 : 400,
            }}>
            {d}d
          </button>
        ))}
        <Btn label="↻ rescan" onClick={load} outline color={T.textSub} small />
      </div>

      {/* No org selected → point at the navbar selector (reconcile is per-org). */}
      {!filterOrg && (
        <div style={{
          ...card, marginBottom: 18, padding: "12px 16px",
          borderColor: T.yellow + "55", background: T.yellow + "0e",
          display: "flex", alignItems: "center", gap: 10,
        }}>
          <span style={{ fontSize: 16 }}>↗</span>
          <span style={{ color: T.yellow, fontSize: 13, ...mono, fontWeight: 600 }}>
            Pick an org in the selector at the top of the page to enable reconcile.
          </span>
          <span style={{ color: T.textMuted, fontSize: 12, ...mono }}>
            Viewing all orgs — reconcile acts on one org at a time.
          </span>
        </div>
      )}

      {loading && <div style={{ color: T.textMuted, ...mono, fontSize: 13, paddingTop: 12 }}>scanning…</div>}

      {data && !loading && (
        <>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 12, marginBottom: 20 }}>
            <StatCard label="Blocks Scanned" value={data.scanned_blocks.toLocaleString()} color={T.text} />
            <StatCard label="Client Mismatches" value={data.client.total} color={data.client.total > 0 ? T.red : T.green} />
            <StatCard label="Internal (noise)" value={data.internal.total} color={T.textMuted} />
            <StatCard label="Lookback" value={`${data.params.days}d`} color={T.teal} />
          </div>

          {verdict && (
            <div style={{
              ...card, marginBottom: 20,
              borderColor: verdict.ongoing ? T.red + "66" : T.green + "66",
              background: verdict.ongoing ? T.red + "12" : T.green + "12",
            }}>
              <div style={{ fontSize: 13, color: verdict.ongoing ? T.red : T.green, ...mono, fontWeight: 600 }}>
                {verdict.ongoing
                  ? `⚠ ONGOING — most recent CLIENT mismatch was ${verdict.ageDays}d ago (${verdict.newest}). Needs a live classifier fix.`
                  : `✓ Likely HISTORICAL — newest CLIENT mismatch was ${verdict.ageDays}d ago (${verdict.newest}). No recent recurrences; consider a one-time recategorization cleanup.`}
              </div>
            </div>
          )}

          {/* CLIENT bucket — the money bucket. Scope is driven by the top org
              selector (filterOrg); no per-client dropdown needed. */}
          {data.client.total > 0 ? (
            <>
              {/* ── Prominent reconcile action bar (top of the money bucket) ── */}
              <div style={{
                ...card, marginBottom: 20,
                display: "flex", alignItems: "center", justifyContent: "space-between",
                gap: 16, flexWrap: "wrap" as const,
                borderColor: filterOrg ? T.red + "55" : T.border,
                background: filterOrg ? T.red + "0e" : T.surface,
              }}>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontSize: 14, color: T.text, ...mono, fontWeight: 700 }}>
                    {data.client.total} client mismatch{data.client.total === 1 ? "" : "es"} to reconcile
                  </div>
                  <div style={{ fontSize: 12, color: T.textMuted, ...mono, marginTop: 3 }}>
                    Reassigns each block to the client its title names, and logs an audit.
                  </div>
                </div>
                {filterOrg ? (
                  <button
                    disabled={reconcileBusy}
                    onClick={() => reconcile(data.client.mismatches.map(m => m.block_id), "all client mismatches")}
                    style={{
                      background: T.red, border: `1px solid ${T.red}`, color: "#fff",
                      padding: "10px 20px", fontSize: 13, cursor: reconcileBusy ? "default" : "pointer",
                      borderRadius: 6, ...mono, fontWeight: 700, opacity: reconcileBusy ? 0.5 : 1, whiteSpace: "nowrap" as const,
                    }}>
                    {reconcileBusy ? "reconciling…" : `⟲ Reconcile all ${data.client.mismatches.length}`}
                  </button>
                ) : (
                  <span style={{ color: T.yellow, fontSize: 12, ...mono, fontWeight: 600, whiteSpace: "nowrap" as const }}>
                    ↑ pick a single org above to reconcile
                  </span>
                )}
              </div>

              <BucketDetail
                bucket={data.client}
                tone={T.red}
                onReconcile={filterOrg ? reconcile : undefined}
                reconcileBusy={reconcileBusy}
                hideBulkButton
              />
            </>
          ) : (
            <div style={{ ...card, textAlign: "center" as const, padding: 40 }}>
              <div style={{ color: T.green, fontSize: 14, ...mono }}>no client-name mismatches in this window ✓</div>
            </div>
          )}

          {/* INTERNAL bucket — collapsed, secondary */}
          {data.internal.total > 0 && (
            <div style={{ marginTop: 24 }}>
              <button onClick={() => setShowInternal(v => !v)}
                style={{ width: "100%", ...card, marginBottom: showInternal ? 20 : 10, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "space-between", background: T.surface, textAlign: "left" as const, border: `1px solid ${T.border}` }}>
                <span style={{ fontSize: 13, color: T.textSub, ...mono, fontWeight: 600 }}>
                  {showInternal ? "▾" : "▸"} Internal / admin mismatches ({data.internal.total})
                  <span style={{ color: T.textMuted, marginLeft: 10, fontWeight: 400 }}>
                    — firm buckets & CS Connect; real but not billing errors
                  </span>
                </span>
                <span style={{ ...mono, fontSize: 12, color: T.textMuted }}>{showInternal ? "hide" : "show"}</span>
              </button>
              {showInternal && <BucketDetail bucket={data.internal} tone={T.textMuted} />}
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// ─── Main Dashboard ────────────────────────────────────────────────────────────
// ═══════════════════════════════════════════════════════════════════════════════

// ═══════════════════════════════════════════════════════════════════════════════
// ─── Daily Review Tab (firm-wide accuracy audit) ────────────────────────────────
// ═══════════════════════════════════════════════════════════════════════════════

interface DRCategory {
  name: string; hours: number; block_count: number; unique_activities: number;
  sample_activities: string[]; task_type_code: string | null; task_type_name: string | null;
}
interface DRUserCard { user_id: number; name: string; total_hours: number; categories: DRCategory[]; }
interface DRClient { client_id: number | null; client: string; total_hours: number; users: DRUserCard[]; }
interface DRUserSummary {
  user_id: number; name: string; email: string; role: string;
  billable_hours: number; non_billable_hours: number; total_hours: number; needs_review_hours: number;
}
interface DRAnomaly {
  block_id: number; user: string | null; window_title: string; app_name: string;
  booked_client_id: number; booked_client_name: string;
  looks_like_client_id: number; looks_like_client_name: string;
  bucket: "client" | "internal";
}
interface DRResponse {
  org_id: number; org_name: string; timezone: string;
  window: { mode: "day" | "range"; start: string; end: string };
  totals: { billable_hours: number; non_billable_hours: number; total_hours: number; needs_review_hours: number };
  user_summary: DRUserSummary[];
  clients: DRClient[];
  anomalies: DRAnomaly[];
  flagged_blocks: Record<string, string>;
  anomaly_counts: { client: number; internal: number };
}

interface DailyReviewTabProps {
  apiFetch: (path: string, opts?: RequestInit) => Promise<any>;
  flash: (msg: string, type?: "ok" | "err") => void;
  filterOrg: number | null;
  setFilterOrg: (id: number | null) => void;
  orgs: Org[];
}

const fmtH = (n: number) => `${(n || 0).toFixed(2)}h`;
const cleanActivity = (s: string) => s.replace(/^\[id:[^\]]*\]\s*/, "");
const clientKey = (c: DRClient) => (c.client_id != null ? `id:${c.client_id}` : `name:${c.client}`);
const activityBlockIds = (s: string): string[] => {
  const m = s.match(/^\[id:([^\]]*)\]/);
  return m ? m[1].split(",").map(x => x.trim()).filter(Boolean) : [];
};

function DailyReviewTab({ apiFetch, flash, filterOrg, setFilterOrg, orgs }: DailyReviewTabProps) {
  const today = new Date().toISOString().slice(0, 10);
  const [rangeMode, setRangeMode] = useState(false);
  const [date, setDate] = useState(today);
  const [startDate, setStartDate] = useState(today);
  const [endDate, setEndDate] = useState(today);
  const [data, setData] = useState<DRResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const load = useCallback(async () => {
    if (!filterOrg) { flash("Select a firm above first.", "err"); return; }
    setLoading(true);
    try {
      const p = new URLSearchParams({ org_id: String(filterOrg) });
      if (rangeMode) { p.set("start", startDate); p.set("end", endDate); }
      else { p.set("date", date); }
      const d: DRResponse = await apiFetch(`/mavops/daily-review/?${p.toString()}`);
      setData(d);
      setExpanded(new Set());
    } catch { flash("Failed to load daily review.", "err"); }
    finally { setLoading(false); }
  }, [apiFetch, flash, filterOrg, rangeMode, date, startDate, endDate]);

  // Auto-load when the firm changes (date changes require the Load button).
  useEffect(() => { if (filterOrg) load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [filterOrg]);

  const toggle = (key: string) => setExpanded(prev => {
    const next = new Set(prev);
    if (next.has(key)) next.delete(key); else next.add(key);
    return next;
  });

  const inputStyle: React.CSSProperties = {
    background: T.bg, border: `1px solid ${T.border}`, color: T.text,
    padding: "7px 10px", fontSize: 12, outline: "none", borderRadius: 4, ...mono,
  };

  // Client names that have at least one billing-impacting (client-bucket) anomaly.
  const flaggedClientNames = new Set(
    (data?.anomalies || []).filter(a => a.bucket === "client").map(a => a.booked_client_name)
  );

  return (
    <div>
      {/* ── Controls ── */}
      <div style={{ ...card, display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" as const }}>
        <span style={{ color: T.textMuted, fontSize: 11, letterSpacing: 1, textTransform: "uppercase" as const, fontWeight: 600 }}>Firm</span>
        <select value={filterOrg || ""} onChange={e => setFilterOrg(e.target.value ? Number(e.target.value) : null)} style={{ ...inputStyle, cursor: "pointer", color: filterOrg ? T.teal : T.textSub }}>
          <option value="">— select firm —</option>
          {orgs.map(o => <option key={o.id} value={o.id}>{o.name}</option>)}
        </select>

        <div style={{ width: 1, height: 24, background: T.border }} />

        {rangeMode ? (
          <>
            <input type="date" value={startDate} onChange={e => setStartDate(e.target.value)} style={inputStyle} />
            <span style={{ color: T.textMuted, fontSize: 12 }}>→</span>
            <input type="date" value={endDate} onChange={e => setEndDate(e.target.value)} style={inputStyle} />
          </>
        ) : (
          <input type="date" value={date} onChange={e => setDate(e.target.value)} style={inputStyle} />
        )}

        <label style={{ display: "flex", alignItems: "center", gap: 6, color: T.textSub, fontSize: 12, cursor: "pointer", ...mono }}>
          <input type="checkbox" checked={rangeMode} onChange={e => setRangeMode(e.target.checked)} style={{ cursor: "pointer" }} />
          date range
        </label>

        <Btn label={loading ? "loading…" : "load"} onClick={load} disabled={loading || !filterOrg} />
      </div>

      {!filterOrg && (
        <div style={{ color: T.textMuted, fontSize: 14, ...mono, paddingTop: 48, textAlign: "center" }}>
          select a firm to audit its clients across every user
        </div>
      )}

      {data && (
        <>
          {/* ── Header + firm totals ── */}
          <div style={{ display: "flex", alignItems: "baseline", gap: 12, margin: "20px 0 12px" }}>
            <span style={{ fontSize: 18, fontWeight: 700, color: T.text }}>{data.org_name}</span>
            <span style={{ ...mono, fontSize: 12, color: T.textMuted }}>
              {data.window.mode === "range" ? `${data.window.start} → ${data.window.end}` : data.window.start} · {data.timezone}
            </span>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 12, marginBottom: 20 }}>
            <StatCard label="Billable" value={fmtH(data.totals.billable_hours)} color={T.green} />
            <StatCard label="Non-billable" value={fmtH(data.totals.non_billable_hours)} color={T.textSub} />
            <StatCard label="Total" value={fmtH(data.totals.total_hours)} color={T.text} />
            <StatCard label="Needs Review" value={fmtH(data.totals.needs_review_hours)} color={data.totals.needs_review_hours > 0 ? T.yellow : T.textMuted} />
          </div>

          {/* ── Anomalies: titles that clearly name a different client than booked ── */}
          {data.anomalies.length > 0 && (
            <div style={{ ...card, marginBottom: 20, borderColor: T.red + "66", background: T.red + "0c" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
                <span style={{ color: T.red, fontSize: 13, fontWeight: 700 }}>⚠ Anomalies</span>
                <span style={{ ...mono, fontSize: 12, color: T.red }}>{data.anomaly_counts.client} client</span>
                {data.anomaly_counts.internal > 0 && (
                  <span style={{ ...mono, fontSize: 12, color: T.textMuted }}>· {data.anomaly_counts.internal} internal</span>
                )}
                <span style={{ ...mono, fontSize: 11, color: T.textMuted }}>— title names a different client than the one it's booked to</span>
              </div>
              <table style={{ width: "100%", borderCollapse: "collapse" as const, fontSize: 12, ...mono }}>
                <tbody>
                  {data.anomalies.map(a => (
                    <tr key={a.block_id} style={{ borderTop: `1px solid ${T.border}` }}>
                      <td style={{ padding: "5px 8px", color: T.textMuted, whiteSpace: "nowrap" as const, verticalAlign: "top" }}>{a.user || "—"}</td>
                      <td style={{ padding: "5px 8px", whiteSpace: "nowrap" as const, verticalAlign: "top" }}>
                        <span style={{ color: T.text }}>{a.booked_client_name}</span>
                        <span style={{ color: T.red, margin: "0 6px" }}>→</span>
                        <span style={{ color: T.yellow }}>{a.looks_like_client_name}</span>
                        {a.bucket === "internal" && <span style={{ color: T.textMuted, marginLeft: 6, fontSize: 10 }}>(internal)</span>}
                      </td>
                      <td style={{ padding: "5px 8px", color: T.textSub, verticalAlign: "top" }}>{a.window_title}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* ── Per-user summary ── */}
          {data.user_summary.length > 0 && (
            <div style={{ ...card, marginBottom: 20 }}>
              <div style={{ color: T.textMuted, fontSize: 11, letterSpacing: 2, textTransform: "uppercase" as const, marginBottom: 12, fontWeight: 600 }}>By User</div>
              <table style={{ width: "100%", borderCollapse: "collapse" as const, fontSize: 12, ...mono }}>
                <thead>
                  <tr style={{ color: T.textMuted, textAlign: "left" as const }}>
                    <th style={{ padding: "4px 8px", fontWeight: 500 }}>User</th>
                    <th style={{ padding: "4px 8px", fontWeight: 500 }}>Role</th>
                    <th style={{ padding: "4px 8px", fontWeight: 500, textAlign: "right" as const }}>Billable</th>
                    <th style={{ padding: "4px 8px", fontWeight: 500, textAlign: "right" as const }}>Non-bill</th>
                    <th style={{ padding: "4px 8px", fontWeight: 500, textAlign: "right" as const }}>Total</th>
                    <th style={{ padding: "4px 8px", fontWeight: 500, textAlign: "right" as const }}>Needs Review</th>
                  </tr>
                </thead>
                <tbody>
                  {data.user_summary.map(u => (
                    <tr key={u.user_id} style={{ borderTop: `1px solid ${T.border}` }}>
                      <td style={{ padding: "5px 8px", color: T.text }}>{u.name}</td>
                      <td style={{ padding: "5px 8px", color: T.textMuted }}>{u.role}</td>
                      <td style={{ padding: "5px 8px", textAlign: "right" as const, color: T.green }}>{fmtH(u.billable_hours)}</td>
                      <td style={{ padding: "5px 8px", textAlign: "right" as const, color: T.textSub }}>{fmtH(u.non_billable_hours)}</td>
                      <td style={{ padding: "5px 8px", textAlign: "right" as const, color: T.text }}>{fmtH(u.total_hours)}</td>
                      <td style={{ padding: "5px 8px", textAlign: "right" as const, color: u.needs_review_hours > 0 ? T.yellow : T.textMuted }}>{fmtH(u.needs_review_hours)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* ── Clients (client-major) ── */}
          <div style={{ color: T.textMuted, fontSize: 11, letterSpacing: 2, textTransform: "uppercase" as const, marginBottom: 10, fontWeight: 600 }}>
            Clients · {data.clients.length}
          </div>

          {data.clients.length === 0 && (
            <div style={{ color: T.textMuted, fontSize: 13, ...mono, padding: "20px 0" }}>no client time in this window</div>
          )}

          {data.clients.map(c => {
            const key = clientKey(c);
            const isOpen = expanded.has(key);
            const unassigned = c.client_id == null;
            return (
              <div key={key} style={{ ...card, marginBottom: 8, padding: 0, overflow: "hidden", borderColor: unassigned ? T.yellow + "55" : T.border }}>
                <div onClick={() => toggle(key)} style={{ display: "flex", alignItems: "center", gap: 12, padding: "14px 18px", cursor: "pointer", background: unassigned ? T.yellow + "0e" : "transparent" }}>
                  <span style={{ color: T.textMuted, fontSize: 12, width: 12 }}>{isOpen ? "▾" : "▸"}</span>
                  <span style={{ fontSize: 14, fontWeight: 600, color: unassigned ? T.yellow : T.text, fontStyle: unassigned ? "italic" as const : "normal" as const }}>
                    {c.client}{unassigned ? "  (unattributed)" : ""}
                  </span>
                  {flaggedClientNames.has(c.client) && (
                    <span title="A title booked here clearly names a different client" style={{ color: T.red, fontSize: 12, background: T.red + "1e", border: `1px solid ${T.red}55`, padding: "1px 7px", borderRadius: 3, ...mono }}>⚠ mismatch</span>
                  )}
                  <div style={{ flex: 1 }} />
                  <span style={{ ...mono, fontSize: 12, color: T.textMuted }}>{c.users.length} user{c.users.length > 1 ? "s" : ""}</span>
                  <span style={{ ...mono, fontSize: 13, color: T.teal, fontWeight: 600 }}>{fmtH(c.total_hours)}</span>
                </div>

                {isOpen && (
                  <div style={{ borderTop: `1px solid ${T.border}`, padding: "6px 18px 14px 42px" }}>
                    {c.users.map(u => (
                      <div key={u.user_id} style={{ padding: "10px 0", borderBottom: `1px solid ${T.border}55` }}>
                        <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginBottom: 6 }}>
                          <span style={{ fontSize: 13, fontWeight: 600, color: T.text }}>{u.name}</span>
                          <span style={{ ...mono, fontSize: 12, color: T.teal }}>{fmtH(u.total_hours)}</span>
                        </div>
                        {u.categories.map((cat, i) => (
                          <div key={i} style={{ marginBottom: 6, paddingLeft: 12 }}>
                            <div style={{ display: "flex", alignItems: "baseline", gap: 8, fontSize: 12, ...mono }}>
                              <span style={{ color: T.purple }}>{cat.name}</span>
                              <span style={{ color: T.textSub }}>{fmtH(cat.hours)}</span>
                              <span style={{ color: T.textMuted }}>· {cat.block_count} block{cat.block_count > 1 ? "s" : ""}</span>
                              {cat.task_type_name && <span style={{ color: T.textMuted }}>· {cat.task_type_name}</span>}
                            </div>
                            {cat.sample_activities.length > 0 && (
                              <ul style={{ listStyle: "none", margin: "3px 0 0", padding: 0 }}>
                                {cat.sample_activities.map((s, j) => {
                                  const looksLike = activityBlockIds(s).map(id => data.flagged_blocks[id]).find(Boolean);
                                  return (
                                    <li key={j} style={{ color: looksLike ? T.text : T.textMuted, fontSize: 11.5, ...mono, padding: "1px 0 1px 14px" }}>
                                      · {cleanActivity(s)}
                                      {looksLike && (
                                        <span title={`Title clearly names "${looksLike}"`} style={{ color: T.red, marginLeft: 8, fontSize: 10.5, background: T.red + "1e", border: `1px solid ${T.red}55`, padding: "0 6px", borderRadius: 3 }}>⚠ looks like {looksLike}</span>
                                      )}
                                    </li>
                                  );
                                })}
                              </ul>
                            )}
                          </div>
                        ))}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </>
      )}
    </div>
  );
}

// ─── QBO Mapping tab ──────────────────────────────────────────────────────
interface QboMapRow {
  realm_id: string; client_id: number | null; client_name: string | null;
  suggested_name: string; times_seen: number; last_seen_at: string | null;
}
interface QboMappingData {
  org: { id: number; name: string };
  summary: {
    total_clients: number; clients_matched: number; clients_unmatched: number;
    companies_seen: number; companies_mapped: number; companies_queued: number; coverage_pct: number;
  };
  mapped: QboMapRow[];
  queued: QboMapRow[];
  unmatched_clients: { id: number; name: string }[];
}
interface QboMappingTabProps {
  apiFetch: (path: string, opts?: RequestInit) => Promise<any>;
  flash: (msg: string, type?: "ok" | "err") => void;
  orgs: Org[];
}

function QboMappingTab({ apiFetch, flash, orgs }: QboMappingTabProps) {
  const [orgId, setOrgId] = useState<number | null>(null);
  const [data, setData] = useState<QboMappingData | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async (id: number) => {
    setLoading(true);
    try { setData(await apiFetch(`/mavops/qbo-mappings/?org_id=${id}`)); }
    catch { flash("Failed to load QBO mappings.", "err"); }
    finally { setLoading(false); }
  }, [apiFetch, flash]);

  useEffect(() => { if (orgId) load(orgId); }, [orgId, load]);

  const allClients = data
    ? [
        ...data.unmatched_clients,
        ...data.mapped.filter(m => m.client_id).map(m => ({ id: m.client_id as number, name: m.client_name || "" })),
      ].filter((c, i, arr) => arr.findIndex(x => x.id === c.id) === i)
       .sort((a, b) => a.name.localeCompare(b.name))
    : [];

  const setMapping = async (realmId: string, clientId: number | "") => {
    if (!orgId) return;
    try {
      await apiFetch(`/mavops/qbo-map/`, {
        method: "POST",
        body: JSON.stringify({ org_id: orgId, realm_id: realmId, client_id: clientId === "" ? null : clientId }),
      });
      flash("Mapping saved.", "ok");
      load(orgId);
    } catch { flash("Failed to save mapping.", "err"); }
  };

  const th: CSSProperties = { textAlign: "left", padding: "8px 10px", color: T.textMuted, fontSize: 11, letterSpacing: 1, textTransform: "uppercase", borderBottom: `1px solid ${T.border}`, ...mono };
  const td: CSSProperties = { padding: "8px 10px", color: T.text, fontSize: 13, borderBottom: `1px solid ${T.border}`, ...mono };
  const sel: CSSProperties = { background: T.bg, border: `1px solid ${T.border}`, color: T.text, padding: "5px 8px", fontSize: 12, borderRadius: 4, ...mono, maxWidth: 220 };

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 20 }}>
        <span style={{ color: T.textSub, fontSize: 13, ...mono }}>Org:</span>
        <select value={orgId ?? ""} onChange={e => setOrgId(e.target.value ? Number(e.target.value) : null)} style={sel}>
          <option value="">— select an org —</option>
          {[...orgs].sort((a, b) => a.name.localeCompare(b.name)).map(o => (
            <option key={o.id} value={o.id}>{o.name}</option>
          ))}
        </select>
        {orgId && <button onClick={() => load(orgId)} style={{ background: "none", border: `1px solid ${T.border}`, color: T.textSub, padding: "5px 12px", fontSize: 12, cursor: "pointer", borderRadius: 4, ...mono }}>↻ refresh</button>}
      </div>

      {!orgId && <div style={{ color: T.textMuted, fontSize: 14, ...mono, paddingTop: 40, textAlign: "center" }}>select an org to see its QuickBooks Online auto-match coverage</div>}
      {loading && <div style={{ color: T.textMuted, ...mono, fontSize: 13 }}>loading…</div>}

      {orgId && data && !loading && (
        <>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 12, marginBottom: 24 }}>
            <StatCard label="Coverage" value={`${data.summary.coverage_pct}%`} color={data.summary.coverage_pct >= 80 ? T.green : data.summary.coverage_pct >= 40 ? T.yellow : T.red} />
            <StatCard label="Clients Matched" value={`${data.summary.clients_matched}/${data.summary.total_clients}`} color={T.green} />
            <StatCard label="Companies Seen" value={data.summary.companies_seen} color={T.text} />
            <StatCard label="Needs Mapping" value={data.summary.companies_queued} color={data.summary.companies_queued ? T.yellow : T.textMuted} />
          </div>

          {/* QUEUE — seen but not auto-matched */}
          <div style={{ marginBottom: 28 }}>
            <div style={{ color: T.yellow, fontSize: 13, fontWeight: 600, marginBottom: 8, ...mono, letterSpacing: 1 }}>NEEDS MAPPING — {data.queued.length} compan{data.queued.length === 1 ? "y" : "ies"} seen, no client match</div>
            {data.queued.length === 0 ? (
              <div style={{ color: T.textMuted, fontSize: 13, ...mono }}>None — every QBO company seen so far auto-matched. 🎉</div>
            ) : (
              <table style={{ width: "100%", borderCollapse: "collapse" as const, background: T.surface, borderRadius: 6, overflow: "hidden" }}>
                <thead><tr><th style={th}>Company (from QBO)</th><th style={th}>Realm ID</th><th style={th}>Seen</th><th style={th}>Map to client</th></tr></thead>
                <tbody>
                  {data.queued.map(r => (
                    <tr key={r.realm_id}>
                      <td style={td}>{r.suggested_name || <span style={{ color: T.textMuted }}>(no name)</span>}</td>
                      <td style={{ ...td, color: T.textMuted }}>{r.realm_id}</td>
                      <td style={{ ...td, color: T.textMuted }}>{r.times_seen}×</td>
                      <td style={td}>
                        <select defaultValue="" onChange={e => setMapping(r.realm_id, e.target.value ? Number(e.target.value) : "")} style={sel}>
                          <option value="">— pick client —</option>
                          {allClients.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                        </select>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          {/* MATCHED */}
          <div>
            <div style={{ color: T.green, fontSize: 13, fontWeight: 600, marginBottom: 8, ...mono, letterSpacing: 1 }}>AUTO-MATCHED — {data.mapped.length} compan{data.mapped.length === 1 ? "y" : "ies"} → client</div>
            {data.mapped.length === 0 ? (
              <div style={{ color: T.textMuted, fontSize: 13, ...mono }}>No companies mapped yet.</div>
            ) : (
              <table style={{ width: "100%", borderCollapse: "collapse" as const, background: T.surface, borderRadius: 6, overflow: "hidden" }}>
                <thead><tr><th style={th}>Company (from QBO)</th><th style={th}>Client</th><th style={th}>Realm ID</th><th style={th}>Seen</th><th style={th}></th></tr></thead>
                <tbody>
                  {data.mapped.map(r => (
                    <tr key={r.realm_id}>
                      <td style={td}>{r.suggested_name || <span style={{ color: T.textMuted }}>—</span>}</td>
                      <td style={{ ...td, color: T.teal }}>{r.client_name}</td>
                      <td style={{ ...td, color: T.textMuted }}>{r.realm_id}</td>
                      <td style={{ ...td, color: T.textMuted }}>{r.times_seen}×</td>
                      <td style={td}><button onClick={() => setMapping(r.realm_id, "")} style={{ background: "none", border: `1px solid ${T.border}`, color: T.textMuted, padding: "3px 8px", fontSize: 11, cursor: "pointer", borderRadius: 3, ...mono }}>unmap</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </>
      )}
    </div>
  );
}

export default function MavOpsAdmin() {
  const [latestVersion, setLatestVersion] = useState<string>("0.0.0");
  const [unlocked, setUnlocked] = useState(() => sessionStorage.getItem("mavops_admin") === "1");
  const [token, setToken] = useState(() => localStorage.getItem("auth_token") || "");
  const [tokenInput, setTokenInput] = useState(() => localStorage.getItem("auth_token") || "");
  const [tab, setTab] = useState<"orgs" | "devices" | "logs" | "errors" | "rules" | "mismatches" | "daily-review" | "qbo-mapping">("orgs");

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

  const [showArchived, setShowArchived] = useState(false);
  const [archivingOrg, setArchivingOrg] = useState<number | null>(null);
  const [widgetOrg, setWidgetOrg] = useState<number | null>(null);
  const [industryOrg, setIndustryOrg] = useState<number | null>(null);

  const [impersonatingOrg, setImpersonatingOrg] = useState<{ id: number; name: string } | null>(null);
  const [viewAsPickerOrg, setViewAsPickerOrg] = useState<number | null>(null);
  const [orgMembers, setOrgMembers] = useState<Record<number, OrgMember[]>>({});
  const [membersLoading, setMembersLoading] = useState<number | null>(null);

  const handleUnlock = () => { sessionStorage.setItem("mavops_admin", "1"); setUnlocked(true); };
  // Memoized: tabs put `flash` in their load() dep array, so an unstable
  // identity made every parent render (including this banner's own setMsg,
  // and its 5s clear) refire their fetch effect — a refetch loop that turned
  // one failed scan into a permanent red banner.
  const flash = useCallback((m: string, type: "ok" | "err" = "ok") => {
    setMsg(m); setMsgType(type); setTimeout(() => setMsg(""), 5000);
  }, []);

  const apiFetch = useCallback(async (path: string, opts: RequestInit = {}) => {
    const headers: Record<string, string> = { "Content-Type": "application/json", ...(opts.headers as any || {}) };
    if (token) headers["Authorization"] = `Bearer ${token}`;
    const res = await fetch(`${API}${path}`, { ...opts, headers });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  }, [token]);

  const loadOrgMembers = useCallback(async (orgId: number) => {
    if (orgMembers[orgId]) return;
    setMembersLoading(orgId);
    try {
      const d = await apiFetch(`/mavops/orgs/${orgId}/members/`);
      setOrgMembers(prev => ({ ...prev, [orgId]: d.members || [] }));
    } catch { flash("Failed to load members.", "err"); }
    finally { setMembersLoading(null); }
  }, [apiFetch, orgMembers]);

  useEffect(() => { if (token && tab === "orgs") loadOrgs(); }, [showArchived]); // eslint-disable-line

  useEffect(() => {
    fetch("https://api.github.com/repos/druss16/timetracker-releases/releases/latest")
      .then(r => r.json())
      .then(d => { const v = (d.tag_name || "").replace(/^v/, ""); if (v) setLatestVersion(v); })
      .catch(() => {});
  }, []);

  const loadOrgs = useCallback(async () => {
    if (!token) return; setLoading(true);
    try { const d = await apiFetch(`/mavops/orgs/${showArchived ? "?include_archived=1" : ""}`); setOrgs(d.orgs || []); }
    catch { flash("Failed — make sure your account has is_staff=True.", "err"); }
    finally { setLoading(false); }
  }, [token, apiFetch, showArchived]);

  const archiveOrg = useCallback(async (org: Org, archived: boolean) => {
    setArchivingOrg(org.id);
    try {
      await apiFetch(`/mavops/orgs/${org.id}/archive/`, {
        method: "POST",
        body: JSON.stringify({ archived }),
      });
      flash(archived ? `Archived "${org.name}" — hidden from the list.` : `Restored "${org.name}".`);
      await loadOrgs();
    } catch { flash("Failed to update archive state.", "err"); }
    finally { setArchivingOrg(null); }
  }, [apiFetch, loadOrgs]);

  const setOrgIndustry = useCallback(async (org: Org, industry: string) => {
    if (industry === (org.industry_type || "general")) return;
    setIndustryOrg(org.id);
    try {
      const res = await apiFetch(`/mavops/orgs/${org.id}/industry/`, {
        method: "POST",
        body: JSON.stringify({ industry_type: industry, seed_task_types: true }),
      });
      const seeded = (res?.task_types_created || []).length;
      // Say what the firm will actually SEE, not the enum we stored.
      flash(
        `"${org.name}" is now ${INDUSTRY_LABELS[industry] || industry}` +
        ` — work is called "${res?.terminology?.project || "Project"}"` +
        (seeded ? `, ${seeded} task type(s) added.` : ".")
      );
      await loadOrgs();
    } catch { flash("Failed to change vertical.", "err"); }
    finally { setIndustryOrg(null); }
  }, [apiFetch, loadOrgs]);

  const setShowWidget = useCallback(async (org: Org, show: boolean) => {
    setWidgetOrg(org.id);
    try {
      await apiFetch(`/mavops/orgs/${org.id}/show-client-widget/`, {
        method: "POST",
        body: JSON.stringify({ show_client_widget: show }),
      });
      flash(show
        ? `Ticker ON for "${org.name}" — agents show it after next sync (demo mode).`
        : `Ticker OFF for "${org.name}" — hands-off after next sync.`);
      await loadOrgs();
    } catch { flash("Failed to update ticker visibility.", "err"); }
    finally { setWidgetOrg(null); }
  }, [apiFetch, loadOrgs]);

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

  const restartDevice = async (deviceId: string) => {
    setRestartingDevice(deviceId);
    try { await apiFetch("/mavops/restart-device/", { method: "POST", body: JSON.stringify({ device_id: deviceId }) }); flash("✓ Restart queued — agent will restart within 10s."); }
    catch { flash("Restart failed.", "err"); }
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

  const impersonateOrg = (org: Org, userId: number, username: string) => {
    localStorage.setItem("impersonating_org_id", String(org.id));
    localStorage.setItem("impersonating_org_name", org.name);
    localStorage.setItem("impersonating_user_id", String(userId));
    localStorage.setItem("impersonating_user_name", username);
    setImpersonatingOrg({ id: org.id, name: org.name });
    setViewAsPickerOrg(null);
    window.open("/daily", "_blank");
    flash(`✓ Opening as ${username} @ ${org.name}`);
  };

  const clearImpersonation = () => {
    localStorage.removeItem("impersonating_org_id");
    localStorage.removeItem("impersonating_org_name");
    localStorage.removeItem("impersonating_user_id");
    localStorage.removeItem("impersonating_user_name");
    setImpersonatingOrg(null);
    setViewAsPickerOrg(null);
    flash("✓ Impersonation cleared");
  };

  useEffect(() => {
    if (!viewAsPickerOrg) return;
    const handler = (e: MouseEvent) => {
      const target = e.target as HTMLElement;
      if (!target.closest("[data-picker]")) setViewAsPickerOrg(null);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [viewAsPickerOrg]);

  if (!unlocked) return <PasswordGate onUnlock={handleUnlock} />;

  const mrr = calcMRR(orgs);
  const trialsExpiringSoon = orgs.filter(o => { const d = daysUntil(o.trial_ends_at); return d !== null && d <= 7 && d >= 0; });
  const outdatedDevices = devices.filter(d => versionStatus(d.agent_version, latestVersion) === "outdated");
  const inactiveDevices = devices.filter(d => (Date.now() - new Date(d.last_seen).getTime()) > 7 * 86400000);
  const recentOrgs = [...orgs].filter(o => o.created_at).sort((a, b) => new Date(b.created_at!).getTime() - new Date(a.created_at!).getTime()).slice(0, 5);
  const filteredOrgs = orgs.filter(o => !search || o.name.toLowerCase().includes(search.toLowerCase()));
  // ONE grid template shared by the header row AND every data row. Each row is
  // its own grid, so all tracks are fixed widths (no content-sized `auto`) or
  // columns won't line up across rows. Col 1 (name) flexes; STATUS holds the
  // health/grace/archived badges so they never crowd the name; ACTIONS is a
  // fixed width sized to the 6-button cluster, right-aligned.
  // Columns: ORG | STATUS | PLAN | MRR | SEATS | DEVICES | ACTIVE | ACTIONS
  const ORG_GRID = "minmax(150px, 1.2fr) 136px 98px 78px 90px 86px 72px 352px";
  const filteredDevices = devices.filter(d => {
    if (showInactiveOnly && (Date.now() - new Date(d.last_seen).getTime()) < 7 * 86400000) return false;
    if (!search) return true;
    return [d.machine_name, d.user, d.org_name].some(s => s.toLowerCase().includes(search.toLowerCase()));
  });

  const TABS = ["orgs", "devices", "logs", "errors", "rules", "mismatches", "daily-review", "qbo-mapping"] as const;
  const TAB_LABELS: Record<string, string> = { "daily-review": "Daily Review", "qbo-mapping": "QBO Mapping" };

  return (
    <div style={{ minHeight: "100vh", background: T.bg, color: T.text, fontFamily: "'DM Sans', sans-serif" }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=DM+Sans:wght@400;600;700&display=swap');
        * { box-sizing: border-box; margin: 0; padding: 0; }
        ::-webkit-scrollbar{width:6px} ::-webkit-scrollbar-track{background:${T.bg}} ::-webkit-scrollbar-thumb{background:${T.teal};border-radius:3px}
        input::placeholder{color:${T.textMuted}} 
        button:hover{opacity:0.9; transition:opacity 0.15s ease}  /* was 0.85, no transition */
        select{appearance:none}
        
        /* NEW — smoother card hovers (kicks in for cards with cursor:pointer) */
        [style*="cursor: pointer"]:hover { transition: background 0.15s ease, border-color 0.15s ease; }
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

      {impersonatingOrg && (
        <div style={{ background: "#92400e", borderBottom: `1px solid ${T.yellow}`, padding: "10px 32px", display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 13, color: "#fef3c7", ...mono, position: "sticky", top: 57, zIndex: 9 }}>
          <span>
            👁 Viewing as <strong>{localStorage.getItem("impersonating_user_name") || "?"}</strong> @ <strong>{impersonatingOrg.name}</strong> (org #{impersonatingOrg.id}) —{" "}
            <a href={`/analytics?org_id=${impersonatingOrg.id}&user_id=${localStorage.getItem("impersonating_user_id") || ""}`} target="_blank" rel="noreferrer" style={{ color: T.yellow, textDecoration: "underline" }}>open analytics</a>
          </span>
          <button onClick={clearImpersonation} style={{ background: "none", border: `1px solid ${T.yellow}`, color: "#fef3c7", padding: "4px 14px", fontSize: 12, cursor: "pointer", borderRadius: 4, ...mono }}>exit ×</button>
        </div>
      )}

      {msg && (
        <div style={{ background: msgType === "ok" ? T.teal + "22" : T.red + "22", borderBottom: `1px solid ${msgType === "ok" ? T.teal + "55" : T.red + "55"}`, padding: "10px 32px", fontSize: 13, color: msgType === "ok" ? T.teal : T.red, ...mono, display: "flex", alignItems: "center", gap: 8 }}>
          {msg}
        </div>
      )}

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

      <div style={{ borderBottom: `1px solid ${T.border}`, padding: "0 32px", display: "flex", alignItems: "center", background: T.surface }}>
        {TABS.map(t => (
          <button key={t} onClick={() => setTab(t)} style={{ background: "none", border: "none", color: tab === t ? T.teal : T.textMuted, padding: "14px 22px", fontSize: 13, cursor: "pointer", borderBottom: tab === t ? `2px solid ${T.teal}` : "2px solid transparent", textTransform: "capitalize" as const, ...mono, letterSpacing: 1, fontWeight: tab === t ? 600 : 400 }}>
            {TAB_LABELS[t] || t}
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

      <div style={{ padding: "24px 32px", maxWidth: 1480 }}>
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

            {/* List controls — health summary + show-archived toggle */}
            {orgs.length > 0 && (
              <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12, paddingLeft: 4 }}>
                {(() => {
                  const flagged = filteredOrgs.filter(o => o.health && o.health.status !== "ok").length;
                  return flagged > 0 ? (
                    <span style={{ ...mono, fontSize: 12, color: T.yellow, fontWeight: 600 }}>
                      ⚠ {flagged} org{flagged === 1 ? "" : "s"} need attention
                    </span>
                  ) : (
                    <span style={{ ...mono, fontSize: 12, color: T.textMuted }}>all orgs healthy</span>
                  );
                })()}
                <div style={{ flex: 1 }} />
                <Btn
                  label={showArchived ? "● showing archived" : "show archived"}
                  onClick={() => setShowArchived(v => !v)}
                  outline
                  color={showArchived ? T.teal : T.textMuted}
                  small
                />
              </div>
            )}

            {/* Column headers */}
            {filteredOrgs.length > 0 && (
              <div style={{
                display: "grid",
                gridTemplateColumns: ORG_GRID,
                alignItems: "center",
                gap: 12,
                padding: "8px 21px",
                color: T.textMuted,
                fontSize: 10,
                letterSpacing: 1.5,
                textTransform: "uppercase" as const,
                fontWeight: 600,
                ...mono,
              }}>
                <div style={{ textAlign: "left" as const }}>Org</div>
                <div style={{ textAlign: "left" as const }}>Status</div>
                <div style={{ textAlign: "left" as const }}>Plan</div>
                <div style={{ textAlign: "right" as const }}>MRR</div>
                <div style={{ textAlign: "right" as const }}>Seats</div>
                <div style={{ textAlign: "right" as const }}>Devices</div>
                <div style={{ textAlign: "right" as const }}>Active</div>
                <div></div>
              </div>
            )}

            {filteredOrgs.map(org => {
              const trialDays = daysUntil(org.trial_ends_at);
              const trialAlert = trialDays !== null && trialDays <= 7 && trialDays >= 0;
              const mrr_org = (SEAT_PRICES[org.plan] || 0) * org.seat_count;
              const isViewing = impersonatingOrg?.id === org.id;
              const isPickerOpen = viewAsPickerOrg === org.id;
              const members = orgMembers[org.id];
              
              // Health signals
              const seatPct = org.seat_count > 0 ? (org.member_count / org.seat_count) : 0;
              const seatsHealth = seatPct >= 1 ? "full" : seatPct >= 0.85 ? "near" : "ok";
              const devicesHealth = org.active_devices === 0 && org.member_count > 0 ? "warn" : "ok";
              const seatColor = seatsHealth === "full" ? T.red : seatsHealth === "near" ? T.yellow : T.teal;
              const deviceColor = devicesHealth === "warn" ? T.red : org.active_devices > 0 ? T.green : T.textMuted;

              return (
                <div
                  key={org.id}
                  style={{
                    ...card,
                    padding: "16px 20px",
                    borderColor: isViewing ? T.purple + "99" : trialAlert ? T.yellow + "66" : T.border,
                    transition: "border-color 0.15s ease, background 0.15s ease",
                  }}
                  onMouseEnter={e => {
                    if (!isViewing && !trialAlert) e.currentTarget.style.borderColor = T.borderHi;
                  }}
                  onMouseLeave={e => {
                    if (!isViewing && !trialAlert) e.currentTarget.style.borderColor = T.border;
                  }}
                >
                  <div style={{
                    display: "grid",
                    gridTemplateColumns: ORG_GRID,
                    alignItems: "center",
                    gap: 12,
                  }}>
                    {/* COL 1 — name */}
                    <div style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0 }}>
                      <span style={{
                        fontSize: 16, fontWeight: 700, color: T.text, minWidth: 0,
                        whiteSpace: "nowrap" as const, overflow: "hidden" as const, textOverflow: "ellipsis" as const,
                      }}>
                        {org.name}
                      </span>
                      {isViewing && (
                        <Badge label="viewing" color={T.purple} />
                      )}
                    </div>

                    {/* COL 2 — status badges */}
                    <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" as const }}>
                      {org.health && org.health.status !== "ok" && (
                        <span
                          title={org.health.reasons.join(" · ")}
                          style={{
                            ...mono, fontSize: 11, fontWeight: 700, whiteSpace: "nowrap" as const,
                            padding: "2px 8px", borderRadius: 3, cursor: "help",
                            color: org.health.status === "critical" ? T.red : T.yellow,
                            background: (org.health.status === "critical" ? T.red : T.yellow) + "22",
                            border: `1px solid ${(org.health.status === "critical" ? T.red : T.yellow)}55`,
                          }}
                        >
                          {org.health.status === "critical" ? "⚠ blocked" : "⚠ check"}
                        </span>
                      )}
                      {org.health?.grace_days_left != null && (
                        <span
                          title="Seat overage — grace period before excess members are paused"
                          style={{
                            ...mono, fontSize: 11, fontWeight: 700, whiteSpace: "nowrap" as const,
                            padding: "2px 8px", borderRadius: 3, cursor: "help",
                            color: T.yellow, background: T.yellow + "18", border: `1px solid ${T.yellow}44`,
                          }}
                        >
                          ⏳ grace {org.health.grace_days_left}d
                        </span>
                      )}
                      {trialAlert && (
                        <span style={{ ...mono, fontSize: 11, color: T.yellow, fontWeight: 600, whiteSpace: "nowrap" as const }}>
                          ⚠ {trialDays}d
                        </span>
                      )}
                      {org.mavops_archived && (
                        <Badge label="archived" color={T.textMuted} />
                      )}
                    </div>

                    {/* COL 3 — plan badge */}
                    <div>
                      <Badge label={org.plan} color={org.plan === "trial" ? T.yellow : org.plan === "executive" ? T.purple : T.teal} />
                    </div>

                    {/* COL 4 — MRR */}
                    <div style={{ ...mono, fontSize: 12, fontWeight: 600, textAlign: "right" as const,
                         color: mrr_org > 0 ? T.green : T.textMuted }}>
                      {mrr_org > 0 ? `$${mrr_org.toFixed(0)}/mo` : "—"}
                    </div>

                    {/* COL 5 — seats */}
                    <div style={{ ...mono, fontSize: 12, fontWeight: 600, textAlign: "right" as const, color: seatColor }}>
                      {org.member_count}/{org.seat_count} seats
                    </div>

                    {/* COL 6 — devices */}
                    <div style={{ ...mono, fontSize: 12, fontWeight: 600, textAlign: "right" as const, color: deviceColor }}>
                      {org.active_devices} {org.active_devices === 1 ? "device" : "devices"}
                    </div>

                    {/* COL 7 — activity */}
                    <div style={{ ...mono, fontSize: 11, color: T.textMuted, textAlign: "right" as const }}>
                      {org.last_activity ? timeAgo(org.last_activity) : "—"}
                    </div>

                    {/* COL 8 — actions */}
                    <div style={{ display: "flex", gap: 4, alignItems: "center", justifyContent: "flex-end" }}>
                      <div style={{ position: "relative" }} data-picker>
                        {isViewing ? (
                          <Btn label="✓ exit" onClick={clearImpersonation} color={T.green} outline tiny />
                        ) : (
                          <Btn
                            label={isPickerOpen ? "view ▴" : "view ▾"}
                            onClick={() => {
                              if (isPickerOpen) setViewAsPickerOrg(null);
                              else { setViewAsPickerOrg(org.id); loadOrgMembers(org.id); }
                            }}
                            color={T.purple}
                            outline
                            tiny
                          />
                        )}

                        {isPickerOpen && (
                          <div data-picker style={{
                            position: "absolute", top: "calc(100% + 6px)", right: 0,
                            background: T.surface, border: `1px solid ${T.purple}66`,
                            borderRadius: 6, zIndex: 50, minWidth: 260,
                            boxShadow: "0 8px 32px rgba(0,0,0,0.6)",
                          }}>
                            <div style={{ padding: "8px 14px", borderBottom: `1px solid ${T.border}`, fontSize: 10, color: T.textMuted, ...mono, letterSpacing: 1.5, textTransform: "uppercase" as const }}>
                              Select user to view as
                            </div>
                            {membersLoading === org.id && <div style={{ padding: "14px 16px", color: T.textMuted, fontSize: 12, ...mono }}>loading members…</div>}
                            {members && members.length === 0 && <div style={{ padding: "14px 16px", color: T.textMuted, fontSize: 12, ...mono }}>no members found</div>}
                            {members && members.map((member, idx) => (
                              <button key={member.user_id} onClick={() => impersonateOrg(org, member.user_id, member.username)}
                                style={{
                                  display: "flex", alignItems: "center", justifyContent: "space-between",
                                  width: "100%", padding: "10px 14px", background: "none", border: "none",
                                  borderBottom: idx < members.length - 1 ? `1px solid ${T.border}` : "none",
                                  cursor: "pointer", textAlign: "left" as const,
                                }}
                                onMouseEnter={e => (e.currentTarget.style.background = T.bg)}
                                onMouseLeave={e => (e.currentTarget.style.background = "none")}>
                                <div>
                                  <div style={{ color: T.text, fontSize: 13, fontWeight: 600 }}>{member.username}</div>
                                  <div style={{ color: T.textMuted, fontSize: 11, ...mono, marginTop: 2 }}>
                                    {member.first_name || member.last_name ? `${member.first_name} ${member.last_name}`.trim() : member.email || "no email"}
                                  </div>
                                </div>
                                <span style={{ fontSize: 10, color: T.textMuted, ...mono, background: T.bg, padding: "2px 8px", borderRadius: 3, border: `1px solid ${T.border}`, flexShrink: 0, marginLeft: 12 }}>
                                  {member.role}
                                </span>
                              </button>
                            ))}
                            <div style={{ borderTop: `1px solid ${T.border}` }}>
                              <button onClick={() => setViewAsPickerOrg(null)}
                                style={{ width: "100%", padding: "8px 14px", background: "none", border: "none", color: T.textMuted, cursor: "pointer", fontSize: 11, ...mono, textAlign: "center" as const }}
                                onMouseEnter={e => (e.currentTarget.style.color = T.text)}
                                onMouseLeave={e => (e.currentTarget.style.color = T.textMuted)}>
                                cancel
                              </button>
                            </div>
                          </div>
                        )}
                      </div>

                      {(["devices", "logs", "errors", "rules"] as const).map(t => (
                        <Btn
                          key={t}
                          label={t}
                          onClick={() => { setFilterOrg(org.id); setTab(t); }}
                          outline
                          color={T.textSub}
                          tiny
                        />
                      ))}
                      <select
                        value={org.industry_type || "general"}
                        disabled={industryOrg === org.id}
                        onChange={(e) => setOrgIndustry(org, e.target.value)}
                        title="Vertical — changes task types, wording (Matter vs Engagement) and which integrations lead"
                        style={{
                          background: "transparent",
                          color: (org.industry_type && org.industry_type !== "general") ? T.teal : T.textMuted,
                          border: `1px solid ${T.border}`,
                          borderRadius: 6,
                          fontSize: 11,
                          padding: "2px 6px",
                          cursor: industryOrg === org.id ? "wait" : "pointer",
                        }}
                      >
                        {Object.entries(INDUSTRY_LABELS).map(([v, label]) => (
                          <option key={v} value={v}>{label}</option>
                        ))}
                      </select>
                      <Btn
                        label={widgetOrg === org.id ? "…" : org.show_client_widget ? "ticker on" : "ticker off"}
                        onClick={() => setShowWidget(org, !org.show_client_widget)}
                        outline
                        color={org.show_client_widget ? T.teal : T.textMuted}
                        tiny
                      />
                      <Btn
                        label={archivingOrg === org.id ? "…" : org.mavops_archived ? "restore" : "archive"}
                        onClick={() => archiveOrg(org, !org.mavops_archived)}
                        outline
                        color={org.mavops_archived ? T.teal : T.textMuted}
                        tiny
                      />
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
              const vs = versionStatus(d.agent_version, latestVersion);
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
                      <Btn label={restartingDevice === d.device_id ? "restarting…" : "restart"} onClick={() => restartDevice(d.device_id)} outline color={T.yellow} disabled={restartingDevice === d.device_id} />
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

        {/* ══ RULES ══ */}
        {tab === "rules" && (
          <RoutingRulesTab
            apiFetch={apiFetch}
            flash={flash}
            filterOrg={filterOrg}
            setFilterOrg={setFilterOrg}
          />
        )}

        {tab === "mismatches" && (
          <MismatchesTab apiFetch={apiFetch} flash={flash} filterOrg={filterOrg} />
        )}

        {tab === "qbo-mapping" && (
          <QboMappingTab apiFetch={apiFetch} flash={flash} orgs={orgs} />
        )}

        {/* ══ DAILY REVIEW (firm-wide accuracy audit) ══ */}
        {tab === "daily-review" && (
          <DailyReviewTab apiFetch={apiFetch} flash={flash} filterOrg={filterOrg} setFilterOrg={setFilterOrg} orgs={orgs} />
        )}
      </div>

      {selectedLog && <LogModal log={selectedLog} onClose={() => setSelectedLog(null)} />}
    </div>
  );
}