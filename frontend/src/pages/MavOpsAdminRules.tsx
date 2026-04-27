// src/MavOpsAdminRules.tsx
//
// PR #3 components, written in MavOpsAdmin's inline-style theme (T.teal, mono, etc.)
// Single file by design — keeps integration simple, mirrors the pattern used by
// RuleFormModal/CopyRulesModal in MavOpsAdmin.tsx.
//
// Exports:
//   - TemplatePickerModal    : the new "+ new rule" flow (two-step: pick → fill)
//   - SuggestRulesWizard     : LLM #1 — firm context → suggestions → bulk create
//   - ExplainBlockModal      : LLM #3 — "why was this block categorized?"
//
// Each component is self-contained. They share the theme constants below
// (duplicated from MavOpsAdmin so this file has no cross-file imports).
//
// Wires to PR #2 backend endpoints:
//   GET  /mavops/rule-templates/?org_id=<id>
//   POST /mavops/orgs/<id>/rules/from-template/
//   POST /mavops/orgs/<id>/rules/from-template/bulk/
//   POST /mavops/orgs/<id>/rules/suggest/         (LLM #1)
//   POST /mavops/orgs/<id>/rules/parse/           (LLM #2)
//   GET  /mavops/blocks/<id>/explain/             (LLM #3)

import { useState, useEffect, useCallback } from "react";

// ─── Theme ────────────────────────────────────────────────────────────────────
// Mirrors MavOpsAdmin.tsx — keep these in sync when changing colors.
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
  padding: 20, marginBottom: 10, borderRadius: 8,  // was 6, matches dashboard
};

// ─── Types (mirror PR #2 API responses) ──────────────────────────────────────

export interface TemplateField {
  name: string;
  label: string;
  type: "string" | "int" | "enum";
  options_key?: string;
  maps_to: string;
  required?: boolean;
  placeholder?: string;
}

export interface RuleTemplate {
  id: string;
  label: string;
  emoji: string;
  category: "routing" | "categorization" | "billing" | "flagging";
  runs_at: "agent" | "classifier" | "compaction" | "post_save";
  description: string;
  example: string;
  fixed: Record<string, string>;
  user_fields: TemplateField[];
  card_template: string;
}

export interface TemplateOptions {
  exe_families: string[];
  org_clients: { id: number; name: string }[];
  org_categories: string[];
}

export interface RuleSuggestion {
  template_id: string;
  params: Record<string, string | number>;
  reasoning: string;
  priority: number;
  preview_card: string;
}

interface ParseRuleResponse {
  matched: boolean;
  template_id?: string;
  params?: Record<string, string | number>;
  confidence?: number;
  reasoning?: string;
  explanation?: string;
  suggested_templates?: string[];
}

interface BlockExplanation {
  summary: string;
  details: string;
  fires: Array<{
    rule_id: number;
    rule_match: string;
    rule_action: string;
    engine: string;
    context: Record<string, unknown>;
    outcome: Record<string, unknown>;
    fired_at: string;
  }>;
  near_misses: Array<{
    rule_id: number;
    rule_match: string;
    rule_action: string;
    priority: number;
    reason_skipped: string;
  }>;
}

// ─── Shared mini-components (Btn, Badge — match MavOpsAdmin's look) ──────────

function Btn({
  label, onClick, color = T.teal, outline = false, disabled = false, small = false,
}: {
  label: string; onClick: () => void; color?: string;
  outline?: boolean; disabled?: boolean; small?: boolean;
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
    }}>{label}</button>
  );
}

function Badge({ label, color }: { label: string; color: string }) {
  return (
    <span style={{
      display: "inline-block", padding: "3px 9px",
      background: color + "30", color, fontSize: 11,
      letterSpacing: 1, textTransform: "uppercase" as const,
      borderRadius: 3, border: `1px solid ${color}44`, ...mono,
    }}>{label}</span>
  );
}

// ─── Modal shell (matches RuleFormModal / CopyRulesModal pattern) ────────────

function ModalShell({
  title, subtitle, accentColor = T.teal, onClose, children, maxWidth = 640,
}: {
  title: string;
  subtitle?: string;
  accentColor?: string;
  onClose: () => void;
  children: React.ReactNode;
  maxWidth?: number;
}) {
  return (
    <div style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,0.75)",
      display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100,
    }} onClick={onClose}>
      <div
        style={{
          background: T.surface, border: `1px solid ${accentColor}`,
          width: "90vw", maxWidth, borderRadius: 8,
          maxHeight: "90vh", overflowY: "auto" as const,
        }}
        onClick={e => e.stopPropagation()}
      >
        <div style={{ padding: "16px 20px", borderBottom: `1px solid ${T.border}` }}>
          <div style={{ fontSize: 15, fontWeight: 700, color: T.text }}>{title}</div>
          {subtitle && (
            <div style={{ fontSize: 11, color: T.textMuted, ...mono, marginTop: 2 }}>
              {subtitle}
            </div>
          )}
        </div>
        {children}
      </div>
    </div>
  );
}

// ═════════════════════════════════════════════════════════════════════════════
// ─── 1. TemplatePickerModal — replaces RuleFormModal as "+ new rule" entry ───
// ═════════════════════════════════════════════════════════════════════════════

const CATEGORY_COLOR: Record<RuleTemplate["category"], string> = {
  routing: "#7eb3e0",
  categorization: T.green,
  billing: T.yellow,
  flagging: T.red,
};

const CATEGORY_LABEL: Record<RuleTemplate["category"], string> = {
  routing: "Routing",
  categorization: "Categorization",
  billing: "Billing",
  flagging: "Flagging",
};

interface TemplatePickerModalProps {
  orgId: number;
  orgName: string;
  apiFetch: (path: string, opts?: RequestInit) => Promise<any>;
  flash: (msg: string, type?: "ok" | "err") => void;
  onClose: () => void;
  onRuleCreated: () => void;
}

export function TemplatePickerModal({
  orgId, orgName, apiFetch, flash, onClose, onRuleCreated,
}: TemplatePickerModalProps) {
  const [step, setStep] = useState<"pick" | "fill">("pick");
  const [templates, setTemplates] = useState<RuleTemplate[]>([]);
  const [options, setOptions] = useState<TemplateOptions | null>(null);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<RuleTemplate | null>(null);
  const [prefill, setPrefill] = useState<Record<string, string | number>>({});

  useEffect(() => {
    apiFetch(`/mavops/rule-templates/?org_id=${orgId}`)
      .then(d => {
        setTemplates(d.templates || []);
        setOptions(d.options || null);
      })
      .catch(() => flash("Failed to load templates.", "err"))
      .finally(() => setLoading(false));
  }, [orgId, apiFetch, flash]);

  const grouped: Record<string, RuleTemplate[]> = {
    categorization: [], routing: [], billing: [], flagging: [],
  };
  templates.forEach(t => grouped[t.category]?.push(t));

  const handlePick = (t: RuleTemplate) => {
    setSelected(t);
    setPrefill({});
    setStep("fill");
  };

  const handleParsed = (template_id: string, params: Record<string, string | number>) => {
    const t = templates.find(x => x.id === template_id);
    if (t) {
      setSelected(t);
      setPrefill(params);
      setStep("fill");
    }
  };

  return (
    <ModalShell
      title={step === "pick" ? "New Rule" : selected?.label ?? "New Rule"}
      subtitle={orgName}
      onClose={onClose}
      maxWidth={720}
    >
      {loading && (
        <div style={{ padding: 40, textAlign: "center" as const, color: T.textMuted, ...mono, fontSize: 13 }}>
          loading templates…
        </div>
      )}

      {/* STEP 1 — PICKER */}
      {!loading && step === "pick" && options && (
        <div style={{ padding: 20 }}>
          <div style={{ color: T.textMuted, fontSize: 11, letterSpacing: 2, textTransform: "uppercase" as const, marginBottom: 12, fontWeight: 600 }}>
            What kind of rule?
          </div>

          {(["categorization", "routing", "billing", "flagging"] as const).map(cat => {
            const items = grouped[cat];
            if (!items || items.length === 0) return null;
            return (
              <div key={cat} style={{ marginBottom: 16 }}>
                <div style={{ fontSize: 10, color: CATEGORY_COLOR[cat], ...mono, letterSpacing: 1.5, textTransform: "uppercase" as const, marginBottom: 8, fontWeight: 600 }}>
                  {CATEGORY_LABEL[cat]}
                </div>
                <div style={{ display: "flex", flexDirection: "column" as const, gap: 6 }}>
                  {items.map(t => (
                    <button
                      key={t.id}
                      onClick={() => handlePick(t)}
                      style={{
                        background: T.bg, border: `1px solid ${T.border}`,
                        padding: "10px 14px", borderRadius: 4, cursor: "pointer",
                        textAlign: "left" as const, color: T.text, ...mono,
                      }}
                      onMouseEnter={e => (e.currentTarget.style.borderColor = T.teal + "88")}
                      onMouseLeave={e => (e.currentTarget.style.borderColor = T.border)}
                    >
                      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
                        <span style={{ fontSize: 18 }}>{t.emoji}</span>
                        <span style={{ fontSize: 13, fontWeight: 600, color: T.text }}>
                          {t.label}
                        </span>
                      </div>
                      <div style={{ fontSize: 11, color: T.textSub, marginLeft: 28 }}>
                        {t.description}
                      </div>
                      <div style={{ fontSize: 11, color: T.textMuted, marginLeft: 28, marginTop: 2, fontStyle: "italic" as const }}>
                        e.g. {t.example}
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            );
          })}

          {/* LLM #2 — natural language input */}
          <div style={{ marginTop: 20 }}>
            <NaturalLanguageInput
              orgId={orgId}
              apiFetch={apiFetch}
              flash={flash}
              onParsed={handleParsed}
            />
          </div>
        </div>
      )}

      {/* STEP 2 — FORM */}
      {!loading && step === "fill" && selected && options && (
        <TemplateForm
          template={selected}
          options={options}
          orgId={orgId}
          initialParams={prefill}
          apiFetch={apiFetch}
          flash={flash}
          onBack={() => setStep("pick")}
          onCancel={onClose}
          onSaved={() => { onRuleCreated(); onClose(); }}
        />
      )}
    </ModalShell>
  );
}

// ─── Natural-language input (LLM #2) ─────────────────────────────────────────

function NaturalLanguageInput({
  orgId, apiFetch, flash, onParsed,
}: {
  orgId: number;
  apiFetch: (path: string, opts?: RequestInit) => Promise<any>;
  flash: (msg: string, type?: "ok" | "err") => void;
  onParsed: (template_id: string, params: Record<string, string | number>) => void;
}) {
  const [text, setText] = useState("");
  const [parsing, setParsing] = useState(false);
  const [feedback, setFeedback] = useState("");

  const handleParse = async () => {
    if (!text.trim() || parsing) return;
    setParsing(true);
    setFeedback("");
    try {
      const res: ParseRuleResponse = await apiFetch(`/mavops/orgs/${orgId}/rules/parse/`, {
        method: "POST",
        body: JSON.stringify({ text }),
      });
      if (res.matched && res.template_id && res.params) {
        onParsed(res.template_id, res.params);
        setText("");
      } else {
        setFeedback(res.explanation || "Couldn't map that to a template — try a card above.");
      }
    } catch (e: any) {
      setFeedback(e.message || "parse failed");
      flash("LLM parse failed.", "err");
    } finally {
      setParsing(false);
    }
  };

  return (
    <div style={{
      background: T.bg, border: `1px solid ${T.border}`,
      padding: 12, borderRadius: 4,
    }}>
      <div style={{ fontSize: 10, color: T.textMuted, ...mono, letterSpacing: 1.5, textTransform: "uppercase" as const, marginBottom: 8, fontWeight: 600 }}>
        ✨ or describe in plain English
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <input
          value={text}
          onChange={e => setText(e.target.value)}
          onKeyDown={e => e.key === "Enter" && handleParse()}
          placeholder="Flag any block over 4 hours for partner review"
          disabled={parsing}
          style={{
            flex: 1, background: T.surface, border: `1px solid ${T.border}`,
            color: T.text, padding: "7px 12px", fontSize: 12, outline: "none",
            borderRadius: 4, ...mono,
          }}
        />
        <Btn
          label={parsing ? "…" : "parse"}
          onClick={handleParse}
          disabled={parsing || !text.trim()}
          small
        />
      </div>
      {feedback && (
        <div style={{ fontSize: 11, color: T.yellow, ...mono, marginTop: 8 }}>
          {feedback}
        </div>
      )}
    </div>
  );
}

// ─── TemplateForm (step 2 of picker, dynamically renders fields) ────────────

function TemplateForm({
  template, options, orgId, initialParams,
  apiFetch, flash, onBack, onCancel, onSaved,
}: {
  template: RuleTemplate;
  options: TemplateOptions;
  orgId: number;
  initialParams: Record<string, string | number>;
  apiFetch: (path: string, opts?: RequestInit) => Promise<any>;
  flash: (msg: string, type?: "ok" | "err") => void;
  onBack: () => void;
  onCancel: () => void;
  onSaved: () => void;
}) {
  const [params, setParams] = useState<Record<string, string | number>>(initialParams);
  const [priority, setPriority] = useState(300);
  const [enabled, setEnabled] = useState(true);
  const [description, setDescription] = useState("");
  const [saving, setSaving] = useState(false);

  const updateParam = (name: string, value: string | number) => {
    setParams(p => ({ ...p, [name]: value }));
  };

  const getOptionsForField = (
    optionsKey: string | undefined
  ): { value: string | number; label: string }[] => {
    if (!optionsKey) return [];
    if (optionsKey === "exe_families") {
      return options.exe_families.map(e => ({ value: e, label: e }));
    }
    if (optionsKey === "org_clients") {
      return options.org_clients.map(c => ({ value: c.id, label: c.name }));
    }
    if (optionsKey === "org_categories") {
      return options.org_categories.map(c => ({ value: c, label: c }));
    }
    return [];
  };

  const handleSubmit = async () => {
    // Validate required
    for (const field of template.user_fields) {
      if (field.required !== false) {
        const v = params[field.name];
        if (v === undefined || v === "" || v === null) {
          flash(`${field.label} is required.`, "err");
          return;
        }
      }
    }
    setSaving(true);
    try {
      await apiFetch(`/mavops/orgs/${orgId}/rules/from-template/`, {
        method: "POST",
        body: JSON.stringify({
          template_id: template.id,
          params,
          priority,
          enabled,
          description,
        }),
      });
      flash("✓ Rule created");
      onSaved();
    } catch (e: any) {
      flash(`Save failed: ${e.message}`, "err");
    } finally {
      setSaving(false);
    }
  };

  const inputStyle: React.CSSProperties = {
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
    <>
      <div style={{ padding: 20 }}>
        <button onClick={onBack} style={{
          background: "none", border: "none", color: T.textSub,
          fontSize: 12, cursor: "pointer", ...mono, marginBottom: 14,
        }}>← back to templates</button>

        <div style={{
          display: "flex", alignItems: "center", gap: 10,
          padding: "10px 14px", background: T.bg, border: `1px solid ${T.border}`,
          borderRadius: 4, marginBottom: 18,
        }}>
          <span style={{ fontSize: 22 }}>{template.emoji}</span>
          <div>
            <div style={{ fontSize: 13, fontWeight: 600, color: T.text }}>{template.label}</div>
            <div style={{ fontSize: 11, color: T.textSub }}>{template.description}</div>
          </div>
        </div>

        {/* Dynamic fields */}
        {template.user_fields.length === 0 ? (
          <div style={{
            padding: 12, background: T.bg, border: `1px solid ${T.border}`,
            borderRadius: 4, fontSize: 12, color: T.textSub, ...mono,
          }}>
            This rule has no parameters. It applies as-is when its conditions are met.
          </div>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
            {template.user_fields.map(field => {
              const fieldStyle = (template.user_fields.length === 1) ? { gridColumn: "1 / span 2" } : {};
              return (
                <div key={field.name} style={fieldStyle}>
                  <label style={labelStyle}>
                    {field.label}
                    {field.required !== false && <span style={{ color: T.red, marginLeft: 4 }}>*</span>}
                  </label>
                  {field.type === "enum" ? (
                    <select
                      value={String(params[field.name] ?? "")}
                      onChange={e => {
                        const raw = e.target.value;
                        const opts = getOptionsForField(field.options_key);
                        const match = opts.find(o => String(o.value) === raw);
                        updateParam(
                          field.name,
                          typeof match?.value === "number" ? match.value : raw
                        );
                      }}
                      style={inputStyle}
                    >
                      <option value="">— select —</option>
                      {getOptionsForField(field.options_key).map(opt => (
                        <option key={String(opt.value)} value={String(opt.value)}>
                          {opt.label}
                        </option>
                      ))}
                    </select>
                  ) : field.type === "int" ? (
                    <input
                      type="number"
                      value={(params[field.name] as number | string) ?? ""}
                      onChange={e => updateParam(field.name, parseInt(e.target.value, 10) || 0)}
                      placeholder={field.placeholder}
                      style={inputStyle}
                    />
                  ) : (
                    <input
                      type="text"
                      value={(params[field.name] as string) ?? ""}
                      onChange={e => updateParam(field.name, e.target.value)}
                      placeholder={field.placeholder}
                      style={inputStyle}
                    />
                  )}
                </div>
              );
            })}
          </div>
        )}

        {/* Priority + Enabled + Description */}
        <div style={{
          marginTop: 18, paddingTop: 18, borderTop: `1px solid ${T.border}`,
          display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16,
        }}>
          <div>
            <label style={labelStyle}>Priority</label>
            <select
              value={priority}
              onChange={e => setPriority(Number(e.target.value))}
              style={inputStyle}
            >
              <option value={500}>500 (hard)</option>
              <option value={300}>300 (default)</option>
              <option value={100}>100 (soft)</option>
            </select>
          </div>
          <div>
            <label style={labelStyle}>Enabled</label>
            <label style={{
              display: "flex", alignItems: "center", gap: 8,
              paddingTop: 10, color: T.text, fontSize: 13, cursor: "pointer",
            }}>
              <input
                type="checkbox"
                checked={enabled}
                onChange={e => setEnabled(e.target.checked)}
              />
              {enabled ? "active" : "inactive"}
            </label>
          </div>
          <div style={{ gridColumn: "1 / span 2" }}>
            <label style={labelStyle}>Description (optional)</label>
            <input
              value={description}
              onChange={e => setDescription(e.target.value)}
              placeholder="human-readable note"
              style={inputStyle}
            />
          </div>
        </div>
      </div>

      <div style={{
        padding: "12px 20px", borderTop: `1px solid ${T.border}`,
        display: "flex", justifyContent: "flex-end", gap: 8,
        background: T.bg, borderRadius: "0 0 8px 8px",
      }}>
        <Btn label="cancel" onClick={onCancel} outline color={T.textMuted} small />
        <Btn
          label={saving ? "creating…" : "create rule"}
          onClick={handleSubmit}
          disabled={saving}
          small
        />
      </div>
    </>
  );
}

// ═════════════════════════════════════════════════════════════════════════════
// ─── 2. SuggestRulesWizard — LLM #1 (firm context → suggestions → bulk) ─────
// ═════════════════════════════════════════════════════════════════════════════

interface SuggestRulesWizardProps {
  orgId: number;
  orgName: string;
  apiFetch: (path: string, opts?: RequestInit) => Promise<any>;
  flash: (msg: string, type?: "ok" | "err") => void;
  onClose: () => void;
  onRulesCreated: (count: number) => void;
}

export function SuggestRulesWizard({
  orgId, orgName, apiFetch, flash, onClose, onRulesCreated,
}: SuggestRulesWizardProps) {
  const [step, setStep] = useState<"context" | "review" | "done">("context");
  const [generating, setGenerating] = useState(false);
  const [creating, setCreating] = useState(false);
  const [suggestions, setSuggestions] = useState<RuleSuggestion[]>([]);
  const [approved, setApproved] = useState<Set<number>>(new Set());
  const [createdCount, setCreatedCount] = useState(0);

  // Form state
  const [firmName, setFirmName] = useState(orgName);
  const [industry, setIndustry] = useState("CPA / Tax");
  const [taxSoftware, setTaxSoftware] = useState("UltraTax, TaxWise");
  const [accountingSoftware, setAccountingSoftware] = useState("QuickBooks");
  const [billingModel, setBillingModel] = useState(
    "hourly billing with fixed-fee tax returns"
  );
  const [notes, setNotes] = useState("");

  const inputStyle: React.CSSProperties = {
    width: "100%", background: T.bg, border: `1px solid ${T.border}`,
    color: T.text, padding: "8px 12px", fontSize: 13, outline: "none",
    borderRadius: 4, ...mono, boxSizing: "border-box" as const,
  };
  const labelStyle: React.CSSProperties = {
    display: "block", color: T.textMuted, fontSize: 10,
    letterSpacing: 1.5, textTransform: "uppercase" as const,
    marginBottom: 6, fontWeight: 600,
  };

  const handleGenerate = async () => {
    setGenerating(true);
    try {
      const res = await apiFetch(`/mavops/orgs/${orgId}/rules/suggest/`, {
        method: "POST",
        body: JSON.stringify({
          firm_context: {
            firm_name: firmName,
            industry,
            tax_software: taxSoftware.split(",").map(s => s.trim()).filter(Boolean),
            accounting_software: accountingSoftware.split(",").map(s => s.trim()).filter(Boolean),
            billing_model: billingModel,
            notes,
          },
          max_suggestions: 25,
        }),
      });
      const list = res.suggestions || [];
      setSuggestions(list);
      // Default to all approved
      setApproved(new Set(list.map((_: RuleSuggestion, i: number) => i)));
      setStep("review");
    } catch (e: any) {
      flash(`LLM suggest failed: ${e.message}`, "err");
    } finally {
      setGenerating(false);
    }
  };

  const handleApprove = async () => {
    const toCreate = suggestions.filter((_, i) => approved.has(i));
    if (toCreate.length === 0) {
      flash("Select at least one rule to create.", "err");
      return;
    }
    setCreating(true);
    try {
      const res = await apiFetch(`/mavops/orgs/${orgId}/rules/from-template/bulk/`, {
        method: "POST",
        body: JSON.stringify({
          suggestions: toCreate.map(s => ({
            template_id: s.template_id,
            params: s.params,
            priority: s.priority,
            enabled: true,
            description: s.reasoning.slice(0, 200),
          })),
        }),
      });
      setCreatedCount(res.created_count || 0);
      onRulesCreated(res.created_count || 0);
      setStep("done");
    } catch (e: any) {
      flash(`Bulk create failed: ${e.message}`, "err");
    } finally {
      setCreating(false);
    }
  };

  const toggleApproved = (idx: number) => {
    setApproved(prev => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  };

  return (
    <ModalShell
      title="✨ Suggest Rules"
      subtitle={`${orgName} · LLM-assisted rule generation`}
      accentColor={T.purple}
      onClose={onClose}
      maxWidth={780}
    >
      {/* STEP 1 — CONTEXT */}
      {step === "context" && (
        <>
          <div style={{ padding: 20 }}>
            <div style={{ fontSize: 12, color: T.textSub, marginBottom: 16, ...mono }}>
              Describe the firm so the LLM can suggest tailored rules. The more specific
              you are, the better the suggestions.
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
              <div>
                <label style={labelStyle}>Firm Name</label>
                <input value={firmName} onChange={e => setFirmName(e.target.value)} style={inputStyle} />
              </div>
              <div>
                <label style={labelStyle}>Industry</label>
                <input value={industry} onChange={e => setIndustry(e.target.value)} style={inputStyle} />
              </div>
              <div>
                <label style={labelStyle}>Tax Software</label>
                <input
                  value={taxSoftware}
                  onChange={e => setTaxSoftware(e.target.value)}
                  placeholder="UltraTax, TaxWise, Lacerte"
                  style={inputStyle}
                />
              </div>
              <div>
                <label style={labelStyle}>Accounting Software</label>
                <input
                  value={accountingSoftware}
                  onChange={e => setAccountingSoftware(e.target.value)}
                  placeholder="QuickBooks, Xero"
                  style={inputStyle}
                />
              </div>
              <div style={{ gridColumn: "1 / span 2" }}>
                <label style={labelStyle}>Billing Model</label>
                <input value={billingModel} onChange={e => setBillingModel(e.target.value)} style={inputStyle} />
              </div>
              <div style={{ gridColumn: "1 / span 2" }}>
                <label style={labelStyle}>Notes / Quirks (free-form)</label>
                <textarea
                  value={notes}
                  onChange={e => setNotes(e.target.value)}
                  rows={4}
                  placeholder="Wants TaxWise → Internal-Tax. Flag blocks > 4h. Partner Wayne reviews everything…"
                  style={{ ...inputStyle, resize: "vertical" as const, fontFamily: "'DM Mono', monospace" }}
                />
              </div>
            </div>
          </div>

          <div style={{
            padding: "12px 20px", borderTop: `1px solid ${T.border}`,
            display: "flex", justifyContent: "flex-end", gap: 8,
            background: T.bg, borderRadius: "0 0 8px 8px",
          }}>
            <Btn label="cancel" onClick={onClose} outline color={T.textMuted} small />
            <Btn
              label={generating ? "generating…" : "✨ generate suggestions"}
              onClick={handleGenerate}
              disabled={generating || !firmName.trim()}
              color={T.purple}
              small
            />
          </div>
        </>
      )}

      {/* STEP 2 — REVIEW */}
      {step === "review" && (
        <>
          <div style={{ padding: 20 }}>
            <button onClick={() => setStep("context")} style={{
              background: "none", border: "none", color: T.textSub,
              fontSize: 12, cursor: "pointer", ...mono, marginBottom: 14,
            }}>← back to context</button>

            {suggestions.length === 0 ? (
              <div style={{
                padding: 16, background: T.yellow + "15",
                border: `1px solid ${T.yellow}44`, borderRadius: 4,
                fontSize: 13, color: T.yellow, ...mono,
              }}>
                No suggestions returned. Try adding more detail to the firm context.
              </div>
            ) : (
              <>
                <div style={{
                  display: "flex", justifyContent: "space-between", alignItems: "center",
                  paddingBottom: 12, borderBottom: `1px solid ${T.border}`, marginBottom: 12,
                }}>
                  <div style={{ fontSize: 12, color: T.textSub, ...mono }}>
                    <strong style={{ color: T.text }}>{approved.size}</strong> of {suggestions.length} selected
                  </div>
                  <div style={{ display: "flex", gap: 6 }}>
                    <button
                      onClick={() => setApproved(new Set(suggestions.map((_, i) => i)))}
                      style={{
                        background: "none", border: "none", color: T.textSub,
                        fontSize: 11, cursor: "pointer", ...mono, letterSpacing: 1,
                        textTransform: "uppercase" as const,
                      }}
                    >select all</button>
                    <span style={{ color: T.textMuted }}>·</span>
                    <button
                      onClick={() => setApproved(new Set())}
                      style={{
                        background: "none", border: "none", color: T.textSub,
                        fontSize: 11, cursor: "pointer", ...mono, letterSpacing: 1,
                        textTransform: "uppercase" as const,
                      }}
                    >clear</button>
                  </div>
                </div>

                <div style={{ display: "flex", flexDirection: "column" as const, gap: 6, maxHeight: "55vh", overflowY: "auto" as const }}>
                  {suggestions.map((s, i) => {
                    const isApproved = approved.has(i);
                    return (
                      <div
                        key={`${s.template_id}-${i}`}
                        onClick={() => toggleApproved(i)}
                        style={{
                          padding: "10px 14px",
                          background: isApproved ? T.bg : T.bg,
                          border: `1px solid ${isApproved ? T.green + "55" : T.border}`,
                          borderRadius: 4, cursor: "pointer",
                          opacity: isApproved ? 1 : 0.55,
                          display: "flex", alignItems: "flex-start", gap: 10,
                        }}
                      >
                        <input
                          type="checkbox"
                          checked={isApproved}
                          onChange={() => toggleApproved(i)}
                          onClick={e => e.stopPropagation()}
                          style={{ marginTop: 3, cursor: "pointer" }}
                        />
                        <div style={{ flex: 1 }}>
                          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, marginBottom: 4 }}>
                            <code style={{
                              fontSize: 12, color: T.text, ...mono,
                              background: T.surface, padding: "2px 8px", borderRadius: 3,
                              fontWeight: 600,
                            }}>{s.preview_card}</code>
                            <span style={{
                              fontSize: 10, color: T.textMuted, ...mono,
                              background: T.surface, border: `1px solid ${T.border}`,
                              padding: "1px 6px", borderRadius: 3,
                            }}>p{s.priority}</span>
                          </div>
                          <div style={{ fontSize: 11, color: T.textSub, ...mono }}>
                            {s.reasoning}
                          </div>
                          <div style={{ fontSize: 10, color: T.textMuted, ...mono, marginTop: 2 }}>
                            {s.template_id}
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </>
            )}
          </div>

          <div style={{
            padding: "12px 20px", borderTop: `1px solid ${T.border}`,
            display: "flex", justifyContent: "flex-end", gap: 8,
            background: T.bg, borderRadius: "0 0 8px 8px",
          }}>
            <Btn label="cancel" onClick={onClose} outline color={T.textMuted} small />
            <Btn
              label={creating ? "creating…" : `create ${approved.size} rule${approved.size === 1 ? "" : "s"}`}
              onClick={handleApprove}
              disabled={creating || approved.size === 0}
              color={T.purple}
              small
            />
          </div>
        </>
      )}

      {/* STEP 3 — DONE */}
      {step === "done" && (
        <>
          <div style={{ padding: 40, textAlign: "center" as const }}>
            <div style={{ fontSize: 36, marginBottom: 14 }}>✅</div>
            <div style={{ fontSize: 15, color: T.green, fontWeight: 700, marginBottom: 8 }}>
              Created {createdCount} {createdCount === 1 ? "rule" : "rules"} for {orgName}
            </div>
            <div style={{ fontSize: 12, color: T.textSub, ...mono }}>
              You can edit, disable, or delete any of them from the rules list.
            </div>
          </div>
          <div style={{
            padding: "12px 20px", borderTop: `1px solid ${T.border}`,
            display: "flex", justifyContent: "flex-end",
            background: T.bg, borderRadius: "0 0 8px 8px",
          }}>
            <Btn label="done" onClick={onClose} color={T.purple} small />
          </div>
        </>
      )}
    </ModalShell>
  );
}

// ═════════════════════════════════════════════════════════════════════════════
// ─── 3. ExplainBlockModal — LLM #3 ("Why was this categorized?") ─────────────
// ═════════════════════════════════════════════════════════════════════════════

interface ExplainBlockModalProps {
  blockId: number;
  apiFetch: (path: string, opts?: RequestInit) => Promise<any>;
  onClose: () => void;
}

export function ExplainBlockModal({
  blockId, apiFetch, onClose,
}: ExplainBlockModalProps) {
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState<BlockExplanation | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    apiFetch(`/mavops/blocks/${blockId}/explain/`)
      .then(setData)
      .catch((e: any) => setError(e.message || "explain failed"))
      .finally(() => setLoading(false));
  }, [blockId, apiFetch]);

  return (
    <ModalShell
      title="Why was this categorized?"
      subtitle={`Block #${blockId}`}
      onClose={onClose}
      maxWidth={780}
    >
      <div style={{ padding: 20 }}>
        {loading && (
          <div style={{ padding: 30, textAlign: "center" as const, color: T.textMuted, ...mono, fontSize: 13 }}>
            analyzing audit log…
          </div>
        )}

        {error && (
          <div style={{
            padding: 12, background: T.red + "15",
            border: `1px solid ${T.red}44`, borderRadius: 4,
            fontSize: 12, color: T.red, ...mono,
          }}>{error}</div>
        )}

        {data && (
          <>
            {/* LLM summary */}
            <div style={{
              ...card, marginBottom: 16,
              borderColor: T.teal + "55", background: T.teal + "10",
            }}>
              <div style={{ fontSize: 14, color: T.text, lineHeight: 1.6, marginBottom: data.details ? 8 : 0 }}>
                {data.summary}
              </div>
              {data.details && (
                <div style={{ fontSize: 12, color: T.textSub, lineHeight: 1.7, ...mono }}>
                  {data.details}
                </div>
              )}
            </div>

            {/* Fires */}
            <div style={{ marginBottom: 16 }}>
              <div style={{ color: T.textMuted, fontSize: 11, letterSpacing: 2, textTransform: "uppercase" as const, marginBottom: 8, fontWeight: 600 }}>
                Rules That Fired ({data.fires.length})
              </div>
              {data.fires.length === 0 ? (
                <div style={{
                  padding: 12, background: T.bg, border: `1px solid ${T.border}`,
                  borderRadius: 4, fontSize: 12, color: T.textSub, ...mono, fontStyle: "italic" as const,
                }}>
                  No org rules fired on this block. Classification came from default logic.
                </div>
              ) : (
                <div style={{ display: "flex", flexDirection: "column" as const, gap: 6 }}>
                  {data.fires.map((f, i) => (
                    <div key={i} style={{
                      padding: "10px 14px", background: T.bg,
                      border: `1px solid ${T.border}`, borderRadius: 4,
                    }}>
                      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, marginBottom: 4 }}>
                        <code style={{ fontSize: 12, color: T.text, ...mono, fontWeight: 600 }}>
                          rule #{f.rule_id} · {f.rule_match}
                        </code>
                        <Badge label={f.engine} color={T.teal} />
                      </div>
                      <div style={{ fontSize: 11, color: T.textSub, ...mono }}>
                        action: <span style={{ color: T.text }}>{f.rule_action}</span>
                      </div>
                      {f.outcome?.reasoning != null && (
                        <div style={{ fontSize: 11, color: T.textMuted, ...mono, fontStyle: "italic" as const, marginTop: 4 }}>
                          {String(f.outcome.reasoning)}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Near-misses */}
            {data.near_misses.length > 0 && (
              <div>
                <div style={{ color: T.textMuted, fontSize: 11, letterSpacing: 2, textTransform: "uppercase" as const, marginBottom: 8, fontWeight: 600 }}>
                  Rules That Almost Fired ({data.near_misses.length})
                </div>
                <div style={{ display: "flex", flexDirection: "column" as const, gap: 6 }}>
                  {data.near_misses.map((n, i) => (
                    <div key={i} style={{
                      padding: "10px 14px", background: T.bg,
                      border: `1px solid ${T.border}`, borderRadius: 4, opacity: 0.7,
                    }}>
                      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, marginBottom: 4 }}>
                        <code style={{ fontSize: 12, color: T.textSub, ...mono }}>
                          rule #{n.rule_id} · {n.rule_match}
                        </code>
                        <span style={{ fontSize: 10, color: T.textMuted, ...mono, background: T.surface, border: `1px solid ${T.border}`, padding: "1px 6px", borderRadius: 3 }}>
                          p{n.priority}
                        </span>
                      </div>
                      <div style={{ fontSize: 11, color: T.textMuted, ...mono }}>
                        {n.reason_skipped}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </div>

      <div style={{
        padding: "12px 20px", borderTop: `1px solid ${T.border}`,
        display: "flex", justifyContent: "flex-end",
        background: T.bg, borderRadius: "0 0 8px 8px",
      }}>
        <Btn label="close" onClick={onClose} outline color={T.textMuted} small />
      </div>
    </ModalShell>
  );
}