/**
 * CreateRuleDialog.tsx — the confirm step for turning a blind-spot into an
 * OrgRoutingRule. Deliberately a REVIEW dialog, not a one-click action:
 * creating a rule writes something that acts on future data, so the user
 * picks how it matches, what it does, and (crucially) defaults to suggest-only.
 *
 * Safety behaviors baked in:
 *   - Defaults to "Suggest only" (server proposes, human reviews) — never
 *     silent auto-commit.
 *   - For browser apps (MSEdge/Chrome/etc.) the app-match option is disabled
 *     with an explanation, steering to title-keyword matching.
 *   - Requires a client when action is route_to_client.
 *
 * Props:
 *   open, onClose
 *   theme        — the blind-spot group { label, appHint, titleHint }
 *   clients      — [{id, name}] for the route dropdown
 *   orgIdOverride
 *   onCreated    — callback(message) after success
 */
import { useState } from "react";
import { X, Sparkles, AlertTriangle } from "lucide-react";
import { API_BASE } from "@/lib/api";

function getAuthToken(): string | null {
  return (
    localStorage.getItem("auth_token") ||
    localStorage.getItem("tt_auth_token") ||
    localStorage.getItem("authToken") ||
    localStorage.getItem("token")
  );
}

const BROWSER_HINTS = ["msedge", "chrome", "firefox", "brave", "opera"];

export interface RuleTheme {
  label: string;       // display label e.g. "Outlook.Exe — Inbox"
  appHint: string;     // e.g. "outlook.exe" or "msedge.exe"
  titleHint: string;   // e.g. "Inbox"
}

interface ClientOpt { id: number; name: string; }

export default function CreateRuleDialog({
  open, onClose, theme, clients, orgIdOverride, onCreated,
}: {
  open: boolean;
  onClose: () => void;
  theme: RuleTheme | null;
  clients: ClientOpt[];
  orgIdOverride?: number | null;
  onCreated: (message: string) => void;
}) {
  const [matchOn, setMatchOn] = useState<"title" | "exe">("title");
  const [actionType, setActionType] = useState<"route_to_client" | "assign_category" | "mark_non_billable" | "suppress">("route_to_client");
  const [clientId, setClientId] = useState<number | "">("");
  const [category, setCategory] = useState("");
  const [suggestOnly, setSuggestOnly] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!open || !theme) return null;

  const isBrowser = BROWSER_HINTS.some((b) => (theme.appHint || "").toLowerCase().includes(b));
  // Force title matching for browsers (exe match would be too broad).
  const effectiveMatchOn = isBrowser ? "title" : matchOn;

  const matchValue = effectiveMatchOn === "title" ? theme.titleHint : theme.appHint;

  const submit = async () => {
    setError(null);
    if (actionType === "route_to_client" && !clientId) {
      setError("Pick a client to route to.");
      return;
    }
    if (actionType === "assign_category" && !category.trim()) {
      setError("Enter a category name.");
      return;
    }
    if (!matchValue) {
      setError("No match value available for this activity.");
      return;
    }
    setSaving(true);
    try {
      const token = getAuthToken();
      const body: any = {
        match_type: effectiveMatchOn === "title" ? "title_contains" : "exe",
        match_value: matchValue,
        action: actionType,
        suggest_only: suggestOnly,
      };
      if (orgIdOverride) body.org_id = orgIdOverride;
      if (actionType === "route_to_client") body.target_client_id = clientId;
      if (actionType === "assign_category") body.target_category = category.trim();

      const res = await fetch(`${API_BASE}/reports/create-rule/`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        credentials: "include",
        body: JSON.stringify(body),
      });
      const json = await res.json();
      if (!res.ok) throw new Error(json.error || `Failed (${res.status})`);
      onCreated(json.message || "Rule created.");
      onClose();
    } catch (e: any) {
      setError(e.message || "Failed to create rule");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-slate-900/40 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-md bg-white rounded-2xl shadow-2xl">
        <div className="flex items-start justify-between px-5 py-4 border-b border-slate-100">
          <div className="flex items-center gap-2">
            <span className="inline-flex h-7 w-7 items-center justify-center rounded-lg bg-violet-50 text-violet-600">
              <Sparkles className="h-4 w-4" />
            </span>
            <h2 className="text-sm font-semibold text-slate-900">Create a rule</h2>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-slate-100 text-slate-400">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="px-5 py-4 space-y-4">
          <div className="text-xs text-slate-500">
            From activity: <span className="font-medium text-slate-700">{theme.label}</span>
          </div>

          {/* Match on */}
          <div>
            <label className="text-xs font-medium text-slate-600">Match when</label>
            {isBrowser ? (
              <div className="mt-1 rounded-lg border border-amber-200 bg-amber-50 p-2.5 flex items-start gap-2">
                <AlertTriangle className="h-3.5 w-3.5 text-amber-600 shrink-0 mt-0.5" />
                <div className="text-[11px] text-amber-800">
                  This is a browser. Matching the whole app would catch unrelated tabs,
                  so we'll match the title keyword <span className="font-semibold">"{theme.titleHint}"</span> instead.
                </div>
              </div>
            ) : (
              <div className="mt-1 inline-flex rounded-lg border border-slate-200 p-0.5 w-full">
                <button
                  onClick={() => setMatchOn("title")}
                  className={"flex-1 px-3 py-1.5 text-xs font-medium rounded-md " + (matchOn === "title" ? "bg-slate-900 text-white" : "text-slate-600")}
                >
                  Title contains "{theme.titleHint}"
                </button>
                <button
                  onClick={() => setMatchOn("exe")}
                  className={"flex-1 px-3 py-1.5 text-xs font-medium rounded-md " + (matchOn === "exe" ? "bg-slate-900 text-white" : "text-slate-600")}
                >
                  App is {theme.appHint}
                </button>
              </div>
            )}
          </div>

          {/* Action */}
          <div>
            <label className="text-xs font-medium text-slate-600">Then</label>
            <select
              value={actionType}
              onChange={(e) => setActionType(e.target.value as any)}
              className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
            >
              <option value="route_to_client">Route to a client</option>
              <option value="assign_category">Assign a category</option>
              <option value="mark_non_billable">Mark non-billable</option>
              <option value="suppress">Ignore (don't track)</option>
            </select>
          </div>

          {actionType === "route_to_client" && (
            <div>
              <label className="text-xs font-medium text-slate-600">Client</label>
              <select
                value={clientId}
                onChange={(e) => setClientId(e.target.value ? Number(e.target.value) : "")}
                className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
              >
                <option value="">Select a client…</option>
                {clients.map((c) => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
              </select>
            </div>
          )}

          {actionType === "assign_category" && (
            <div>
              <label className="text-xs font-medium text-slate-600">Category</label>
              <input
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                placeholder="e.g. Email/Communication"
                className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
              />
            </div>
          )}

          {/* Suggest-only toggle */}
          <label className="flex items-start gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={suggestOnly}
              onChange={(e) => setSuggestOnly(e.target.checked)}
              className="mt-0.5 rounded border-slate-300"
            />
            <span className="text-xs text-slate-600">
              <span className="font-medium">Suggest only</span> — future matches are proposed for review, not auto-applied.
              <span className="block text-[11px] text-slate-400 mt-0.5">
                Recommended. Uncheck only once you trust this rule.
              </span>
            </span>
          </label>

          {error && (
            <div className="rounded-lg border border-rose-200 bg-rose-50/40 p-2.5 text-xs text-rose-700">
              {error}
            </div>
          )}
        </div>

        <div className="flex justify-end gap-2 px-5 py-4 border-t border-slate-100">
          <button onClick={onClose} className="px-3 py-2 text-xs font-medium text-slate-600 hover:bg-slate-50 rounded-lg">
            Cancel
          </button>
          <button
            onClick={submit}
            disabled={saving}
            className="px-4 py-2 text-xs font-medium text-white bg-slate-900 hover:bg-slate-800 rounded-lg disabled:opacity-50"
          >
            {saving ? "Creating…" : "Create rule"}
          </button>
        </div>
      </div>
    </div>
  );
}