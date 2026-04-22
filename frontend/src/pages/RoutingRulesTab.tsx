// ═══════════════════════════════════════════════════════════════════════════
// RoutingRulesTab.tsx — slots into MavOpsAdmin.tsx as a 5th tab
//
// This file contains:
//   1. Types
//   2. RoutingRulesTab component (main view)
//   3. RuleFormModal (create/edit)
//   4. CopyRulesModal (bulk copy from another org)
//
// ═══════════════════════════════════════════════════════════════════════════
//
// HOW TO INTEGRATE INTO MavOpsAdmin.tsx:
//
//   1. Paste this whole file inline inside MavOpsAdmin.tsx, OR save it next
//      to MavOpsAdmin.tsx and import it. Inline is simpler since it shares
//      the T theme object and helpers.
//
//   2. Add "rules" to the TABS array:
//        const TABS = ["orgs", "devices", "logs", "errors", "rules"] as const;
//
//   3. Update the tab type:
//        const [tab, setTab] = useState<"orgs" | "devices" | "logs" | "errors" | "rules">("orgs");
//
//   4. Add a case in the tab effect hook:
//        if (tab === "rules") loadRulesOverview();
//
//   5. Inside the main render's "<div style={{ padding: '24px 32px', ... }}>"
//      block, add the rules tab content:
//        {tab === "rules" && <RoutingRulesTab ... />}
//
//   6. The nav "rules" quick-link on each Org card already exists if you
//      want to jump into a specific org's rules. Pattern:
//        onClick={() => { setFilterOrg(org.id); setTab("rules"); }}
//
// ═══════════════════════════════════════════════════════════════════════════

import { useState, useEffect, useCallback } from "react";

// ─── Shared types (add to existing interfaces in MavOpsAdmin.tsx) ─────────────

interface OrgRuleStats {
  id: number;
  name: string;
  rule_count: number;
  enabled_count: number;
  custom_count: number;
  default_count: number;
  total_fires: number;
  last_fire_at: string | null;
}

interface RoutingRule {
  id: number;
  match_type: "exe" | "exe_family" | "title_contains" | "title_regex" | "file_path_contains";
  match_value: string;
  action: "route_to_client" | "never_switch_away" | "suppress";
  target_client_id: number | null;
  target_client_name: string | null;
  priority: number;
  enabled: boolean;
  description: string;
  is_default: boolean;
  fire_count: number;
  last_fired_at: string | null;
  created_by: string | null;
  created_at: string;
}

interface RuleClient {
  id: number;
  name: string;
}

interface TopRule {
  org_id: number;
  org_name: string;
  rule_id: number;
  match_type: string;
  match_value: string;
  target_client_name: string | null;
  fire_count: number;
  last_fired_at: string | null;
}

interface TestResult {
  input: { title: string; exe: string; file_path: string };
  matches: Array<{
    rule_id: number;
    match_type: string;
    match_value: string;
    action: string;
    target_client_name: string | null;
    priority: number;
    description: string;
  }>;
  winning_rule_id: number | null;
  outcome: {
    action: string;
    message: string;
    target_client_name?: string;
  };
}

// ─── Component ────────────────────────────────────────────────────────────────

interface RoutingRulesTabProps {
  apiFetch: (path: string, opts?: RequestInit) => Promise<any>;
  flash: (msg: string, type?: "ok" | "err") => void;
  filterOrg: number | null;        // if set, drill straight into that org's rules
  setFilterOrg: (id: number | null) => void;
  // Theme + helpers come from parent file scope (T, mono, card, Btn, Badge,
  // OrgPill, StatCard, timeAgo). Since this lives inside MavOpsAdmin.tsx,
  // they're in scope. If you extract to a separate file, pass them as props
  // or import the T constant.
}

export function RoutingRulesTab({
  apiFetch, flash, filterOrg, setFilterOrg,
}: RoutingRulesTabProps) {
  // ── State ──
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

  // Rule tester state
  const [testerInput, setTesterInput] = useState({ title: "", exe: "", file_path: "" });
  const [testerResult, setTesterResult] = useState<TestResult | null>(null);

  // ── Load overview ──
  const loadOverview = useCallback(async () => {
    setLoading(true);
    try {
      const [orgsRes, topRes] = await Promise.all([
        apiFetch("/mavops/routing-rules/orgs/"),
        apiFetch("/mavops/routing-rules/top-firing/").catch(() => ({ rules: [] })),
      ]);
      setOrgStats(orgsRes.orgs || []);
      setTopRules(topRes.rules || []);
    } catch {
      flash("Failed to load rules overview.", "err");
    } finally {
      setLoading(false);
    }
  }, [apiFetch, flash]);

  // ── Load rules for one org ──
  const loadOrgRules = useCallback(async (orgId: number) => {
    setLoadingRules(true);
    try {
      const d = await apiFetch(`/mavops/routing-rules/orgs/${orgId}/`);
      setRulesForOrg(d.rules || []);
      setClientsForOrg(d.clients || []);
      const org = orgStats.find(o => o.id === orgId) || {
        id: orgId, name: d.org?.name || `org #${orgId}`,
        rule_count: 0, enabled_count: 0, custom_count: 0,
        default_count: 0, total_fires: 0, last_fire_at: null,
      };
      setSelectedOrg(org);
    } catch {
      flash("Failed to load rules.", "err");
    } finally {
      setLoadingRules(false);
    }
  }, [apiFetch, flash, orgStats]);

  // Load overview on mount / tab activation
  useEffect(() => { loadOverview(); }, [loadOverview]);

  // If user clicked a "rules" button on an org card, auto-drill in
  useEffect(() => {
    if (filterOrg && !selectedOrg && orgStats.length > 0) {
      loadOrgRules(filterOrg);
    }
  }, [filterOrg, selectedOrg, orgStats.length, loadOrgRules]);

  // ── Actions ──
  const toggleRule = async (rule: RoutingRule) => {
    if (!selectedOrg) return;
    try {
      await apiFetch(`/mavops/routing-rules/orgs/${selectedOrg.id}/${rule.id}/`, {
        method: "PATCH",
        body: JSON.stringify({ enabled: !rule.enabled }),
      });
      loadOrgRules(selectedOrg.id);
    } catch { flash("Toggle failed.", "err"); }
  };

  const deleteRule = async (rule: RoutingRule) => {
    if (!selectedOrg) return;
    if (rule.is_default) { flash("Default rules can only be disabled.", "err"); return; }
    if (!confirm(`Delete rule "${rule.match_value}"?`)) return;
    try {
      await apiFetch(`/mavops/routing-rules/orgs/${selectedOrg.id}/${rule.id}/`, {
        method: "DELETE",
      });
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
      const d = await apiFetch(
        `/mavops/routing-rules/orgs/${selectedOrg.id}/test/`,
        { method: "POST", body: JSON.stringify(testerInput) }
      );
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

  // ═══════════════════════════════════════════════════════════════════════════
  // VIEW: Overview (no org selected)
  // ═══════════════════════════════════════════════════════════════════════════
  if (!selectedOrg) {
    const totalRules = orgStats.reduce((s, o) => s + o.rule_count, 0);
    const totalFires = orgStats.reduce((s, o) => s + o.total_fires, 0);
    const orgsWithRules = orgStats.filter(o => o.rule_count > 0).length;

    return (
      <div>
        {/* Stats */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 12, marginBottom: 20 }}>
          <StatCard label="Orgs with Rules" value={orgsWithRules} color={T.text} />
          <StatCard label="Total Rules" value={totalRules} color={T.purple} />
          <StatCard label="Total Fires" value={totalFires} color={T.green} />
          <StatCard label="Top Firing Rules" value={topRules.length} color={T.teal} />
        </div>

        {/* Top firing rules */}
        {topRules.length > 0 && (
          <div style={{ ...card, marginBottom: 20 }}>
            <div style={{ color: T.textMuted, fontSize: 11, letterSpacing: 2, textTransform: "uppercase" as const, marginBottom: 12, fontWeight: 600 }}>
              Top Firing Rules — All Orgs
            </div>
            <div>
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
                      <span style={{ fontSize: 12, color: T.textMuted, ...mono }}>
                        → {r.target_client_name}
                      </span>
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
          </div>
        )}

        {/* Orgs list */}
        {loading && <div style={{ color: T.textMuted, ...mono, fontSize: 13, paddingTop: 12 }}>loading…</div>}

        {orgStats.length > 0 && (
          <div style={{ ...card }}>
            <div style={{ color: T.textMuted, fontSize: 11, letterSpacing: 2, textTransform: "uppercase" as const, marginBottom: 12, fontWeight: 600 }}>
              All Orgs
            </div>
            <div>
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

  // ═══════════════════════════════════════════════════════════════════════════
  // VIEW: Single org's rules
  // ═══════════════════════════════════════════════════════════════════════════
  return (
    <div>
      {/* Breadcrumb + actions */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          <button onClick={exitOrgView} style={{
            background: "none", border: "none", color: T.textSub,
            fontSize: 13, cursor: "pointer", ...mono,
          }}>← all orgs</button>
          <span style={{ color: T.textMuted }}>/</span>
          <span style={{ fontSize: 16, fontWeight: 700, color: T.text }}>{selectedOrg.name}</span>
          <span style={{ ...mono, fontSize: 11, color: T.textMuted }}>id {selectedOrg.id}</span>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <Btn label="copy from another org" onClick={() => setShowCopyModal(true)} outline color={T.textSub} small />
          <Btn label="+ new rule" onClick={() => { setEditingRule(null); setShowRuleForm(true); }} small />
        </div>
      </div>

      {/* Summary */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 12, marginBottom: 20 }}>
        <StatCard label="Total Rules" value={rulesForOrg.length} color={T.text} />
        <StatCard label="Enabled" value={rulesForOrg.filter(r => r.enabled).length} color={T.green} />
        <StatCard label="Custom" value={rulesForOrg.filter(r => !r.is_default).length} color={T.purple} />
        <StatCard label="Total Fires" value={rulesForOrg.reduce((s, r) => s + r.fire_count, 0)} color={T.teal} />
      </div>

      {/* Rule tester */}
      <div style={{ ...card, marginBottom: 20 }}>
        <div style={{ color: T.textMuted, fontSize: 11, letterSpacing: 2, textTransform: "uppercase" as const, marginBottom: 12, fontWeight: 600 }}>
          Test a Window
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr auto", gap: 8, marginBottom: 10 }}>
          <input
            value={testerInput.title}
            onChange={e => setTesterInput({ ...testerInput, title: e.target.value })}
            placeholder="window title"
            style={{ background: T.bg, border: `1px solid ${T.border}`, color: T.text, padding: "7px 12px", fontSize: 12, outline: "none", borderRadius: 4, ...mono }} />
          <input
            value={testerInput.exe}
            onChange={e => setTesterInput({ ...testerInput, exe: e.target.value })}
            placeholder="exe (e.g. utw25.exe)"
            style={{ background: T.bg, border: `1px solid ${T.border}`, color: T.text, padding: "7px 12px", fontSize: 12, outline: "none", borderRadius: 4, ...mono }} />
          <input
            value={testerInput.file_path}
            onChange={e => setTesterInput({ ...testerInput, file_path: e.target.value })}
            placeholder="file path (optional)"
            style={{ background: T.bg, border: `1px solid ${T.border}`, color: T.text, padding: "7px 12px", fontSize: 12, outline: "none", borderRadius: 4, ...mono }} />
          <Btn label="test" onClick={runTest} small />
        </div>
        {/* Quick tests */}
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

      {/* Rules list */}
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
                  <span style={{ fontSize: 13, color: T.textSub }}>
                    → <strong style={{ color: T.text }}>{r.target_client_name}</strong>
                  </span>
                )}
                {r.action === "never_switch_away" && <Badge label="hold current" color={T.yellow} />}
                {r.action === "suppress" && <Badge label="suppress" color={T.textMuted} />}
                {r.is_default ? (
                  <Badge label="default" color={T.teal} />
                ) : (
                  <Badge label="custom" color={T.purple} />
                )}
              </div>
              <div style={{ display: "flex", gap: 16, alignItems: "center", fontSize: 11, color: T.textMuted, ...mono }}>
                <span>priority {r.priority}</span>
                <span style={{ color: r.fire_count > 0 ? T.green : T.textMuted }}>{r.fire_count} fires</span>
                {r.last_fired_at && <span>last fired {timeAgo(r.last_fired_at)}</span>}
                {r.description && <span style={{ color: T.textSub, fontStyle: "italic" as const }}>"{r.description}"</span>}
              </div>
            </div>
            <div style={{ display: "flex", gap: 6 }}>
              <Btn
                label={r.enabled ? "enabled" : "disabled"}
                onClick={() => toggleRule(r)}
                color={r.enabled ? T.green : T.textMuted}
                outline small
              />
              <Btn label="edit" onClick={() => { setEditingRule(r); setShowRuleForm(true); }} outline color={T.textSub} small />
              {!r.is_default && (
                <Btn label="delete" onClick={() => deleteRule(r)} outline color={T.red} small />
              )}
            </div>
          </div>
        </div>
      ))}

      {/* Modals */}
      {showRuleForm && selectedOrg && (
        <RuleFormModal
          orgId={selectedOrg.id}
          orgName={selectedOrg.name}
          clients={clientsForOrg}
          rule={editingRule}
          apiFetch={apiFetch}
          flash={flash}
          onClose={() => { setShowRuleForm(false); setEditingRule(null); }}
          onSaved={() => {
            setShowRuleForm(false);
            setEditingRule(null);
            loadOrgRules(selectedOrg.id);
          }}
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
          onCopied={() => {
            setShowCopyModal(false);
            loadOrgRules(selectedOrg.id);
          }}
        />
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════
// RuleFormModal — create / edit
// ═══════════════════════════════════════════════════════════════════════════

function RuleFormModal({
  orgId, orgName, clients, rule, apiFetch, flash, onClose, onSaved,
}: {
  orgId: number;
  orgName: string;
  clients: RuleClient[];
  rule: RoutingRule | null;
  apiFetch: (path: string, opts?: RequestInit) => Promise<any>;
  flash: (msg: string, type?: "ok" | "err") => void;
  onClose: () => void;
  onSaved: () => void;
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
      const body = {
        ...form,
        target_client_id: form.target_client_id ? Number(form.target_client_id) : null,
      };
      if (isEdit && rule) {
        await apiFetch(`/mavops/routing-rules/orgs/${orgId}/${rule.id}/`, {
          method: "PATCH",
          body: JSON.stringify(body),
        });
        flash("✓ Rule updated");
      } else {
        await apiFetch(`/mavops/routing-rules/orgs/${orgId}/create/`, {
          method: "POST",
          body: JSON.stringify(body),
        });
        flash("✓ Rule created");
      }
      onSaved();
    } catch (e: any) {
      flash(`Save failed: ${e.message}`, "err");
    } finally {
      setSaving(false);
    }
  };

  const placeholder: Record<string, string> = {
    exe: "utw25.exe",
    exe_family: "taxwise",
    title_contains: "Tax Return",
    title_regex: ".*1040.*",
    file_path_contains: "\\Tax Returns\\",
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
          <div style={{ fontSize: 15, fontWeight: 700, color: T.text }}>
            {isEdit ? "Edit Rule" : "New Rule"}
          </div>
          <div style={{ fontSize: 11, color: T.textMuted, ...mono, marginTop: 2 }}>{orgName}</div>
        </div>

        <div style={{ padding: 20, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
          <div>
            <label style={labelStyle}>Match Type</label>
            <select
              value={form.match_type}
              onChange={e => setForm({ ...form, match_type: e.target.value as any })}
              disabled={rule?.is_default}
              style={input}>
              <option value="exe_family">App Family (e.g. taxwise)</option>
              <option value="exe">Exact Exe Name</option>
              <option value="title_contains">Title Contains</option>
              <option value="title_regex">Title Regex</option>
              <option value="file_path_contains">File Path Contains</option>
            </select>
          </div>
          <div>
            <label style={labelStyle}>Match Value</label>
            <input
              value={form.match_value}
              onChange={e => setForm({ ...form, match_value: e.target.value })}
              placeholder={placeholder[form.match_type]}
              disabled={rule?.is_default}
              style={input} />
          </div>

          <div>
            <label style={labelStyle}>Action</label>
            <select
              value={form.action}
              onChange={e => setForm({ ...form, action: e.target.value as any })}
              style={input}>
              <option value="route_to_client">Route to Client</option>
              <option value="never_switch_away">Never Switch Away</option>
              <option value="suppress">Suppress</option>
            </select>
          </div>

          {form.action === "route_to_client" && (
            <div>
              <label style={labelStyle}>Target Client</label>
              <select
                value={form.target_client_id}
                onChange={e => setForm({ ...form, target_client_id: e.target.value })}
                style={input}>
                <option value="">— select a client —</option>
                {clients.map(c => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
              </select>
            </div>
          )}

          <div>
            <label style={labelStyle}>Priority</label>
            <input
              type="number"
              value={form.priority}
              onChange={e => setForm({ ...form, priority: Number(e.target.value) })}
              style={input} />
            <div style={{ fontSize: 10, color: T.textMuted, ...mono, marginTop: 4 }}>
              500 hard · 300 default · 100 soft
            </div>
          </div>

          <div>
            <label style={labelStyle}>Enabled</label>
            <label style={{ display: "flex", alignItems: "center", gap: 8, paddingTop: 10, color: T.text, fontSize: 13, cursor: "pointer" }}>
              <input
                type="checkbox"
                checked={form.enabled}
                onChange={e => setForm({ ...form, enabled: e.target.checked })} />
              {form.enabled ? "active" : "inactive"}
            </label>
          </div>

          <div style={{ gridColumn: "1 / span 2" }}>
            <label style={labelStyle}>Description (optional)</label>
            <input
              value={form.description}
              onChange={e => setForm({ ...form, description: e.target.value })}
              placeholder="human-readable note"
              style={input} />
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
          <Btn
            label={saving ? "saving…" : isEdit ? "save changes" : "create rule"}
            onClick={save}
            disabled={saving}
            small />
        </div>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════
// CopyRulesModal — copy rules from another org
// ═══════════════════════════════════════════════════════════════════════════

function CopyRulesModal({
  destOrgId, destOrgName, allOrgs, apiFetch, flash, onClose, onCopied,
}: {
  destOrgId: number;
  destOrgName: string;
  allOrgs: OrgRuleStats[];
  apiFetch: (path: string, opts?: RequestInit) => Promise<any>;
  flash: (msg: string, type?: "ok" | "err") => void;
  onClose: () => void;
  onCopied: () => void;
}) {
  const [sourceId, setSourceId] = useState<string>("");
  const [copying, setCopying] = useState(false);

  const copy = async () => {
    if (!sourceId) { flash("Select a source org.", "err"); return; }
    if (!confirm(`Copy rules from source org to ${destOrgName}? Existing rules will not be removed.`)) return;
    setCopying(true);
    try {
      const d = await apiFetch(`/mavops/routing-rules/orgs/${destOrgId}/copy-from/`, {
        method: "POST",
        body: JSON.stringify({ source_org_id: Number(sourceId) }),
      });
      flash(`✓ Copied ${d.copied} rule(s). Skipped: ${d.skipped_duplicates || 0} dup, ${d.skipped_missing_client || 0} missing client.`);
      onCopied();
    } catch (e: any) {
      flash(`Copy failed: ${e.message}`, "err");
    } finally {
      setCopying(false);
    }
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
          <div style={{ fontSize: 11, color: T.textMuted, ...mono, marginTop: 2 }}>
            → <strong>{destOrgName}</strong>
          </div>
        </div>

        <div style={{ padding: 20 }}>
          <label style={{ display: "block", color: T.textMuted, fontSize: 10, letterSpacing: 1.5, textTransform: "uppercase" as const, marginBottom: 6, fontWeight: 600 }}>
            Source Org
          </label>
          <select
            value={sourceId}
            onChange={e => setSourceId(e.target.value)}
            style={input}>
            <option value="">— select source org —</option>
            {allOrgs.filter(o => o.rule_count > 0).map(o => (
              <option key={o.id} value={o.id}>
                {o.name} — {o.rule_count} rule{o.rule_count === 1 ? "" : "s"}
              </option>
            ))}
          </select>

          <div style={{ marginTop: 16, padding: 12, background: T.bg, borderRadius: 4, border: `1px solid ${T.border}`, fontSize: 12, color: T.textSub, lineHeight: 1.6 }}>
            Rules copy as <strong style={{ color: T.purple }}>custom</strong>, not default.
            Duplicates (same match_type + value) and rules with missing target clients
            are skipped.
          </div>
        </div>

        <div style={{ padding: "12px 20px", borderTop: `1px solid ${T.border}`, display: "flex", justifyContent: "flex-end", gap: 8, background: T.bg, borderRadius: "0 0 8px 8px" }}>
          <Btn label="cancel" onClick={onClose} outline color={T.textMuted} small />
          <Btn
            label={copying ? "copying…" : "copy rules"}
            onClick={copy}
            disabled={!sourceId || copying}
            color={T.purple}
            small />
        </div>
      </div>
    </div>
  );
}

// ─── Theme & helpers (declared in parent MavOpsAdmin.tsx — these refs fail
//     if you extract this to its own file without importing them).
//     If you keep this inline in MavOpsAdmin.tsx, no changes needed.
declare const T: any;
declare const mono: React.CSSProperties;
declare const card: React.CSSProperties;
declare function Btn(props: any): JSX.Element;
declare function Badge(props: { label: string; color: string }): JSX.Element;
declare function OrgPill(props: { name: string }): JSX.Element;
declare function StatCard(props: { label: string; value: string | number; color: string }): JSX.Element;
declare function timeAgo(iso: string): string;