// ============================================================================
// REPLACEMENT: OrganizationTab
// Drop-in replacement for the OrganizationTab function in Settings.tsx.
// Also replaces the separate <AISensitivitySettings> card — remove that
// from the render block and just use this component alone.
//
// Changes:
//  - Single unified card with clear section dividers
//  - 3-column info grid (no wasted vertical space)
//  - Plan + billing rate in a compact inline strip
//  - AI sensitivity section integrated natively at the bottom
//  - Edit mode stays within the same card (no layout shift)
// ============================================================================

import { useEffect, useState } from "react";
import {
  Building2, DollarSign, Sparkles, Pencil, Check, RefreshCw,
  Brain, ChevronDown,
} from "lucide-react";
import { cn } from "@/lib/design-system";
import { safeFetchJson } from "@/lib/api";

const RAW_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:7123/api";
const API_BASE = RAW_BASE.endsWith("/api") ? RAW_BASE : `${RAW_BASE.replace(/\/+$/, "")}/api`;

// ── Sensitivity helpers (mirrors Python _sensitivity_to_thresholds) ──────────
const SENSITIVITY_PRESETS = [
  { value: 10,  label: "Conservative",    color: "#6366f1" },
  { value: 35,  label: "Cautious",        color: "#3b82f6" },
  { value: 50,  label: "Balanced",        color: "#10b981" },
  { value: 70,  label: "Aggressive",      color: "#f59e0b" },
  { value: 90,  label: "Very Aggressive", color: "#ef4444" },
];

const SENSITIVITY_DESCRIPTIONS: Record<string, string> = {
  Conservative:    "Only switches when the full client name appears in a window title. Zero false positives — best for firms with very generic client names.",
  Cautious:        "Requires a strong name match. Partial words are ignored. Good default for small firms that prefer manual control.",
  Balanced:        "Default setting. Full-name matches auto-switch; partial words show a suggestion toast but don't switch automatically.",
  Aggressive:      'Partial words trigger auto-switch. "Dauphin" in any window title will switch to "Dauphin & Fantacone". Best for firms with unique client names.',
  "Very Aggressive": "Very short name fragments trigger switches. Maximises automatic detection but may produce occasional false positives.",
};

function getSensitivityLabel(v: number) {
  if (v <= 20) return "Conservative";
  if (v <= 40) return "Cautious";
  if (v <= 60) return "Balanced";
  if (v <= 80) return "Aggressive";
  return "Very Aggressive";
}

function getSensitivityColor(v: number) {
  return SENSITIVITY_PRESETS.reduce((closest, p) =>
    Math.abs(p.value - v) < Math.abs(closest.value - v) ? p : closest
  ).color;
}

function computeThresholds(s: number) {
  const pct = Math.max(0, Math.min(100, s)) / 100;
  return {
    local:   Math.round((0.90 - pct * 0.40) * 100),
    ai:      Math.round((0.85 - pct * 0.40) * 100),
    suggest: Math.round((0.70 - pct * 0.35) * 100),
    partial: pct >= 0.40,
    minWord: pct < 0.40 ? null : pct < 0.70 ? 6 : pct < 0.90 ? 4 : 3,
  };
}

// ── Types (reuse from parent) ─────────────────────────────────────────────
type PlanType = "professional" | "executive" | "none";
type OrgInfo = {
  id: number; name: string; slug?: string; plan: PlanType;
  trial_ends_at: string | null; billing_email: string;
  billing_contact: string; billing_rate_default: string; created_at: string;
};

// ── Main component ────────────────────────────────────────────────────────
export default function OrganizationTab({
  orgInfo, orgPlan, onUpdate, onSuccess, onError,
  currentUserRole,
}: {
  orgInfo: OrgInfo | null;
  orgPlan: PlanType;
  onUpdate: (org: OrgInfo) => void;
  onSuccess: (msg: string) => void;
  onError: (msg: string) => void;
  currentUserRole: string;
}) {
  // ── Org form state ──────────────────────────────────────────────────────
  const [editing, setEditing]   = useState(false);
  const [saving, setSaving]     = useState(false);
  const [form, setForm]         = useState({
    name: "", billing_email: "", billing_contact: "", billing_rate_default: "150.00",
  });

  useEffect(() => {
    if (orgInfo) {
      setForm({
        name:                 orgInfo.name || "",
        billing_email:        orgInfo.billing_email || "",
        billing_contact:      orgInfo.billing_contact || "",
        billing_rate_default: orgInfo.billing_rate_default || "150.00",
      });
    }
  }, [orgInfo]);

  const handleOrgSave = async () => {
    setSaving(true);
    try {
      const updated = await safeFetchJson<OrgInfo>(`${API_BASE}/settings/org/`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });
      onUpdate(updated);
      setForm({
        name: updated.name || "", billing_email: updated.billing_email || "",
        billing_contact: updated.billing_contact || "",
        billing_rate_default: updated.billing_rate_default || "150.00",
      });
      setEditing(false);
      onSuccess("Organization updated");
    } catch (err: any) {
      onError(err?.message || "Failed to update");
    } finally {
      setSaving(false);
    }
  };

  // ── Sensitivity state ────────────────────────────────────────────────────
  const isAdmin = currentUserRole === "admin" || currentUserRole === "owner";
  const [sensitivity,    setSensitivity]    = useState(50);
  const [savedSens,      setSavedSens]      = useState(50);
  const [sensLoading,    setSensLoading]    = useState(true);
  const [sensSaving,     setSensSaving]     = useState(false);
  const [showThresholds, setShowThresholds] = useState(false);

  useEffect(() => {
    const v = (orgInfo as any)?.ai_sensitivity ?? 50;
    setSensitivity(v);
    setSavedSens(v);
    setSensLoading(false);
  }, [orgInfo, isAdmin]);

  const handleSensSave = async () => {
    setSensSaving(true);
    try {
      await safeFetchJson(`${API_BASE}/settings/org/`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ai_sensitivity: sensitivity }),
      });
      setSavedSens(sensitivity);
      onSuccess("Sensitivity saved. Agents will update at next sync.");
    } catch {
      onError("Failed to save sensitivity.");
    } finally {
      setSensSaving(false);
    }
  };

  // ── Derived values ────────────────────────────────────────────────────────
  if (!orgInfo) return <div className="text-slate-500 font-medium p-4">No organization data</div>;

  const planLabel = orgPlan === "executive" ? "💎 Executive" : orgPlan === "professional" ? "⭐ Professional" : "🚫 No Plan";
  const sensLabel = getSensitivityLabel(sensitivity);
  const sensColor = getSensitivityColor(sensitivity);
  const thresholds = computeThresholds(sensitivity);
  const sensDesc = SENSITIVITY_DESCRIPTIONS[sensLabel] ?? "";
  const sensChanged = sensitivity !== savedSens;

  return (
    <div className="space-y-0">

      {/* ── Header row ─────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-extrabold text-slate-900 flex items-center gap-2">
          <Building2 className="w-5 h-5 text-primary" />
          Organization
        </h2>
        {!editing && (
          <button
            onClick={() => setEditing(true)}
            className="flex items-center gap-2 px-4 py-2 text-sm border-2 border-slate-200 rounded-xl font-bold text-slate-700 hover:bg-slate-100 transition-all"
          >
            <Pencil className="w-3.5 h-3.5" />
            Edit
          </button>
        )}
      </div>

      {/* ── Section 1: Org Info ─────────────────────────────────────────── */}
      {editing ? (
        /* Edit mode */
        <div className="bg-slate-50 border-2 border-dashed border-slate-300 rounded-2xl p-6 mb-6">
          <p className="text-xs font-bold text-slate-500 uppercase tracking-widest mb-5">Edit Organization Info</p>
          <div className="grid grid-cols-2 gap-5">
            <div className="col-span-2 sm:col-span-1">
              <label className="block text-sm font-bold text-slate-700 mb-1.5">Organization Name</label>
              <input
                type="text" value={form.name}
                onChange={e => setForm({ ...form, name: e.target.value })}
                className="w-full border-2 border-slate-200 rounded-xl px-4 py-2.5 font-medium text-slate-900 focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none transition-all"
              />
            </div>
            <div className="col-span-2 sm:col-span-1">
              <label className="block text-sm font-bold text-slate-700 mb-1.5">Billing Email</label>
              <input
                type="email" value={form.billing_email}
                onChange={e => setForm({ ...form, billing_email: e.target.value })}
                className="w-full border-2 border-slate-200 rounded-xl px-4 py-2.5 font-medium text-slate-900 focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none transition-all"
              />
            </div>
            <div>
              <label className="block text-sm font-bold text-slate-700 mb-1.5">Billing Contact</label>
              <input
                type="text" value={form.billing_contact}
                onChange={e => setForm({ ...form, billing_contact: e.target.value })}
                className="w-full border-2 border-slate-200 rounded-xl px-4 py-2.5 font-medium text-slate-900 focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none transition-all"
              />
            </div>
            <div>
              <label className="block text-sm font-bold text-slate-700 mb-1.5">Default Hourly Rate</label>
              <div className="relative">
                <span className="absolute left-4 top-1/2 -translate-y-1/2 text-slate-500 font-bold text-sm">$</span>
                <input
                  type="number" step="0.01" min="0" value={form.billing_rate_default}
                  onChange={e => setForm({ ...form, billing_rate_default: e.target.value })}
                  className="w-full pl-8 pr-4 py-2.5 border-2 border-slate-200 rounded-xl font-semibold text-slate-900 focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none transition-all"
                />
              </div>
            </div>
          </div>
          <div className="flex gap-3 mt-5 pt-5 border-t-2 border-slate-200">
            <button
              onClick={handleOrgSave} disabled={saving}
              className="flex items-center gap-2 px-5 py-2.5 bg-primary text-white rounded-xl font-bold hover:opacity-90 disabled:opacity-50 shadow-lg shadow-primary/20 transition-all"
            >
              {saving ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
              Save Changes
            </button>
            <button
              onClick={() => setEditing(false)}
              className="px-5 py-2.5 border-2 border-slate-200 rounded-xl font-bold text-slate-700 hover:bg-white transition-all"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        /* View mode */
        <div className="mb-6">
          {/* Top info strip */}
          <div className="grid grid-cols-3 gap-px bg-slate-200 rounded-2xl overflow-hidden border-2 border-slate-200 mb-4">
            {[
              { label: "Organization",    value: orgInfo.name },
              { label: "Billing Email",   value: orgInfo.billing_email || "—" },
              { label: "Billing Contact", value: orgInfo.billing_contact || "—" },
            ].map(({ label, value }) => (
              <div key={label} className="bg-white px-5 py-4">
                <p className="text-xs font-bold text-slate-400 uppercase tracking-widest mb-1">{label}</p>
                <p className="font-bold text-slate-900 text-sm truncate">{value}</p>
              </div>
            ))}
          </div>

          {/* Plan + Rate side-by-side */}
          <div className="grid grid-cols-2 gap-4">
            {/* Plan card */}
            <div className={cn(
              "rounded-2xl border-2 px-5 py-4 flex items-center justify-between",
              orgPlan === "executive" ? "bg-primary/5 border-primary/20" : "bg-amber-50 border-amber-200"
            )}>
              <div>
                <p className={cn("text-xs font-bold uppercase tracking-widest mb-1",
                  orgPlan === "executive" ? "text-primary/60" : "text-amber-600"
                )}>Current Plan</p>
                <p className={cn("text-lg font-extrabold",
                  orgPlan === "executive" ? "text-primary" : "text-amber-700"
                )}>{planLabel}</p>
              </div>
              {orgPlan !== "executive" && (
                <a
                  href="/account/billing"
                  className="flex items-center gap-1.5 px-4 py-2 bg-primary text-white text-sm font-bold rounded-xl hover:opacity-90 shadow-lg shadow-primary/20 transition-all"
                >
                  <Sparkles className="w-3.5 h-3.5" />
                  Upgrade
                </a>
              )}
            </div>

            {/* Billing rate card */}
            <div className="rounded-2xl border-2 border-emerald-200 bg-emerald-50 px-5 py-4 flex items-center justify-between">
              <div>
                <p className="text-xs font-bold text-emerald-600/70 uppercase tracking-widest mb-1 flex items-center gap-1.5">
                  <DollarSign className="w-3 h-3" />Default Rate
                </p>
                <p className="text-lg font-extrabold text-emerald-700">
                  ${parseFloat(orgInfo.billing_rate_default || "150.00").toFixed(2)}<span className="text-sm font-semibold text-emerald-600/70">/hr</span>
                </p>
              </div>
              <span className="text-xs bg-emerald-100 text-emerald-700 font-bold px-2.5 py-1 rounded-full">Firm Default</span>
            </div>
          </div>
        </div>
      )}

      {/* ── Divider ─────────────────────────────────────────────────────── */}
      {isAdmin && (
        <>
          <div className="flex items-center gap-3 my-6">
            <div className="flex-1 h-px bg-slate-200" />
            <span className="flex items-center gap-1.5 text-xs font-bold text-slate-400 uppercase tracking-widest">
              <Brain className="w-3.5 h-3.5" />AI Settings
            </span>
            <div className="flex-1 h-px bg-slate-200" />
          </div>

          {/* ── Section 2: AI Sensitivity ──────────────────────────────── */}
          <div>
            <div className="flex items-start justify-between mb-5">
              <div>
                <h3 className="text-base font-bold text-slate-900">Client Detection Sensitivity</h3>
                <p className="text-sm text-slate-500 mt-0.5">
                  How aggressively the desktop agent matches windows to clients.
                </p>
              </div>
              {/* Live label pill */}
              {!sensLoading && (
                <span
                  className="text-sm font-bold px-3 py-1 rounded-full text-white shrink-0 ml-4"
                  style={{ backgroundColor: sensColor }}
                >
                  {sensitivity} — {sensLabel}
                </span>
              )}
            </div>

            {sensLoading ? (
              <div className="h-10 bg-slate-100 animate-pulse rounded-xl" />
            ) : (
              <>
                {/* Slider */}
                <div className="mb-4">
                  <input
                    type="range" min={0} max={100} step={1} value={sensitivity}
                    onChange={e => setSensitivity(Number(e.target.value))}
                    className="w-full h-2 rounded-full appearance-none cursor-pointer"
                    style={{
                      background: `linear-gradient(to right, ${sensColor} ${sensitivity}%, #e2e8f0 ${sensitivity}%)`,
                      accentColor: sensColor,
                    }}
                  />
                  <div className="flex justify-between mt-2 px-0.5">
                    {["Conservative","Cautious","Balanced","Aggressive","Max"].map(t => (
                      <span key={t} className="text-xs text-slate-400 font-medium">{t}</span>
                    ))}
                  </div>
                </div>

                {/* Description box */}
                <div
                  className="text-sm text-slate-600 bg-slate-50 rounded-xl px-4 py-3 mb-4 border-l-4"
                  style={{ borderLeftColor: sensColor }}
                >
                  {sensDesc}
                </div>

                {/* Quick presets */}
                <div className="flex flex-wrap gap-2 mb-4">
                  {SENSITIVITY_PRESETS.map(p => (
                    <button
                      key={p.value}
                      onClick={() => setSensitivity(p.value)}
                      className="px-3 py-1.5 rounded-full border text-xs font-bold transition-all"
                      style={sensitivity === p.value
                        ? { backgroundColor: p.color, color: "white", borderColor: p.color }
                        : { borderColor: "#cbd5e1", color: "#475569" }
                      }
                    >
                      {p.label}
                    </button>
                  ))}
                </div>

                {/* Collapsible thresholds */}
                <button
                  onClick={() => setShowThresholds(v => !v)}
                  className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-600 transition-colors mb-3 select-none"
                >
                  <ChevronDown className={cn("w-3.5 h-3.5 transition-transform", showThresholds && "rotate-180")} />
                  {showThresholds ? "Hide" : "Show"} confidence thresholds
                </button>

                {showThresholds && (
                  <div className="grid grid-cols-2 gap-3 mb-4 text-xs">
                    {[
                      { label: "Full-name auto-switch", value: `≥ ${thresholds.local}%` },
                      { label: "AI auto-switch",        value: `≥ ${thresholds.ai}%` },
                      { label: "Suggestion toast",      value: `≥ ${thresholds.suggest}%` },
                      {
                        label: "Partial-word matching",
                        value: thresholds.partial ? `On (min ${thresholds.minWord} chars)` : "Off",
                      },
                    ].map(({ label, value }) => (
                      <div key={label} className="bg-slate-50 border border-slate-200 rounded-xl px-3 py-2.5">
                        <div className="text-slate-500">{label}</div>
                        <div className="font-bold mt-0.5" style={{ color: sensColor }}>{value}</div>
                      </div>
                    ))}
                    <p className="col-span-2 text-xs text-slate-400 italic">
                      {thresholds.partial
                        ? `At this sensitivity, "Eric Dauphin update" would ${thresholds.local <= 65 ? "auto-switch" : "suggest switching"} to "Dauphin & Fantacone".`
                        : `The window title must contain the full client name to trigger a switch.`
                      }
                    </p>
                  </div>
                )}

                {/* Save row */}
                <div className="flex items-center gap-4 pt-4 border-t-2 border-slate-100">
                  <button
                    onClick={handleSensSave}
                    disabled={sensSaving || !sensChanged}
                    className="px-5 py-2.5 rounded-xl text-sm font-bold text-white transition-all disabled:opacity-40 disabled:cursor-not-allowed"
                    style={{ backgroundColor: sensChanged ? sensColor : "#94a3b8" }}
                  >
                    {sensSaving ? "Saving…" : "Save Sensitivity"}
                  </button>
                  {sensChanged && !sensSaving && (
                    <span className="text-xs text-slate-400">Unsaved changes</span>
                  )}
                </div>
              </>
            )}
          </div>
        </>
      )}
    </div>
  );
}