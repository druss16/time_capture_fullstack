// src/pages/onboard/api.ts
// Client for /api/onboard/ — the Onboarding Console. The server enforces the
// "Onboarding Operator" role on every call; nothing here is a gate.
import { API_BASE, safeFetchJson } from "@/lib/api";

const BASE = `${API_BASE}/onboard`;

export type StepKind = "auto" | "action" | "manual";
export type Who = "us" | "firm" | "firm_it" | "system";

export interface Step {
  key: string; title: string; kind: StepKind; who: Who; help: string; action: string;
  /** True when the step is satisfied by a live check and cannot be ticked by hand. */
  live: boolean;
  done: boolean; not_applicable: boolean; detail: string; error: string | null;
  note: string; marked_by: string | null; marked_at: string | null;
}
export interface Phase { key: string; title: string; steps: Step[]; done: boolean; open: number; }
export interface PhaseSummary { key: string; title: string; done: boolean; open: number; }

export interface ProjectSummary {
  id: number; status: "active" | "paused" | "live" | "cancelled";
  install_path: string; install_path_label: string;
  vertical: string; vertical_label: string;
  org: { id: number; name: string; slug: string; plan: string; seat_count: number };
  owner: { id: number; name: string; email: string } | null;
  target_go_live: string | null; created_at: string; went_live_at: string | null;
  last_activity_at: string;
  progress: { done: number; total: number };
  current_phase: string; phases: PhaseSummary[];
  error?: string;
}

export interface Intake {
  id: number; is_open: boolean; created_at: string; expires_at: string;
  last_saved_at: string | null; submitted_at: string | null; revoked_at: string | null;
  payload: any; url?: string;
  /** Set once the link actually went out (email or marked by hand). */
  sent: { to: string | null; how: string | null; at: string; by: string | null } | null;
}

export interface ProjectDetail extends ProjectSummary {
  contacts: Record<string, Record<string, string>>;
  billing_model: string; coupon_months: number; notes: string;
  terms: Record<string, string>;
  clio_push_trigger: string | null;
  checklist: { phases: Phase[]; progress: { done: number; total: number }; current_phase: string };
  intake: Intake | null;
}

export interface VerifyResult {
  lines: { label: string; state: "ok" | "warn" | "bad"; detail: string }[];
  issues: { label: string; state: "ok" | "warn" | "bad"; fix: string }[];
}

const json = (body: unknown) => ({ body: JSON.stringify(body) });

export const onboardApi = {
  me: () => safeFetchJson<{ authenticated: boolean; is_operator: boolean; user: any }>(`${BASE}/me/`),
  list: (status = "open") => safeFetchJson<{ projects: ProjectSummary[] }>(`${BASE}/projects/?status=${status}`),
  create: (body: Record<string, unknown>) =>
    safeFetchJson<ProjectSummary>(`${BASE}/projects/`, { method: "POST", ...json(body) }),
  adoptable: () => safeFetchJson<{ orgs: { id: number; name: string; slug: string; industry_type: string; plan: string }[] }>(`${BASE}/orgs/adoptable/`),
  get: (id: number) => safeFetchJson<ProjectDetail>(`${BASE}/projects/${id}/`),
  patch: (id: number, body: Record<string, unknown>) =>
    safeFetchJson<ProjectDetail>(`${BASE}/projects/${id}/`, { method: "PATCH", ...json(body) }),
  mark: (id: number, key: string, body: { done?: boolean; not_applicable?: boolean; note?: string }) =>
    safeFetchJson(`${BASE}/projects/${id}/steps/${key}/`, { method: "POST", ...json(body) }),
  verify: (id: number) => safeFetchJson<VerifyResult>(`${BASE}/projects/${id}/verify/`),
  audit: (id: number) => safeFetchJson<{ events: { action: string; detail: any; actor: any; at: string }[] }>(`${BASE}/projects/${id}/audit/`),
  runImport: (id: number, body: { kind: string; csv: string; dry_run: boolean; update?: boolean }) =>
    safeFetchJson<{ ok: boolean; output: string; errors: string }>(`${BASE}/projects/${id}/import/`, { method: "POST", ...json(body) }),
  intakeCsv: (id: number, kind: string) => safeFetchJson<{ csv: string }>(`${BASE}/projects/${id}/intake-csv/${kind}/`),
  mappings: (id: number) => safeFetchJson<{
    rows: { category: string; task_type_id: number | null; source: string | null }[];
    task_types: { id: number; code: string; name: string; is_billable: boolean }[];
  }>(`${BASE}/projects/${id}/mappings/`),
  suggestMappings: (id: number) => safeFetchJson<{
    source: "ai" | "name_match"; warning: string | null;
    rows: { category: string; task_type_code: string | null; confidence: string; reasoning: string }[];
  }>(`${BASE}/projects/${id}/mappings/suggest/`, { method: "POST" }),
  saveMappings: (id: number, selections: Record<string, number>) =>
    safeFetchJson(`${BASE}/projects/${id}/mappings/`, { method: "PUT", ...json({ selections }) }),
  invites: (id: number) => safeFetchJson<{ roster: RosterRow[] }>(`${BASE}/projects/${id}/invites/`),
  sendInvites: (id: number) =>
    safeFetchJson<{ issued: IssuedInvite[]; roster: RosterRow[] }>(`${BASE}/projects/${id}/invites/`, { method: "POST" }),
  token: (id: number) => safeFetchJson<{ token: string; created: boolean }>(`${BASE}/projects/${id}/token/`, { method: "POST" }),
  pairing: (id: number) => safeFetchJson<{
    ok: boolean; summary: string; token: string | null;
    rows: { hostname: string; email: string; display_name: string; windows_username: string; status: string; issues: string[] }[];
  }>(`${BASE}/projects/${id}/pairing/`),
  aliases: (id: number) => safeFetchJson<{ ok: boolean; output: string; errors: string }>(`${BASE}/projects/${id}/aliases/`, { method: "POST" }),
  clioTrigger: (id: number, trigger: string) =>
    safeFetchJson(`${BASE}/projects/${id}/clio-trigger/`, { method: "POST", ...json({ trigger }) }),
  stripe: (id: number) => safeFetchJson<{
    key_configured: boolean; prices: Record<string, boolean>; linked: boolean;
    customer: string | null; subscription: string | null; plan: string; seat_count: number;
    coupon_months: number; billing_email: string;
  }>(`${BASE}/projects/${id}/stripe/`),
  setupStripe: (id: number, body: Record<string, unknown>) =>
    safeFetchJson<{ customer: string; subscription: string; coupon: string | null }>(`${BASE}/projects/${id}/stripe/`, { method: "POST", ...json(body) }),
  deployKit: (id: number) => safeFetchJson<{ token: string; files: KitFile[] }>(`${BASE}/projects/${id}/deploy-kit/`, { method: "POST" }),
  goLive: (id: number) => safeFetchJson(`${BASE}/projects/${id}/go-live/`, { method: "POST" }),
  deleteCheck: (id: number) => safeFetchJson<{ firm_created_here: boolean; blockers: string[]; members: number; clients: number }>(`${BASE}/projects/${id}/delete/`),
  deleteProject: (id: number, body: { confirm_name: string; delete_firm: boolean }) =>
    safeFetchJson(`${BASE}/projects/${id}/delete/`, { method: "POST", ...json(body) }),
  issueIntake: (id: number) => safeFetchJson<Intake>(`${BASE}/projects/${id}/intake/`, { method: "POST" }),
  reopenIntake: (id: number) => safeFetchJson<Intake>(`${BASE}/projects/${id}/intake/reopen/`, { method: "POST" }),
  sendIntake: (id: number, email: string, name: string) =>
    safeFetchJson<Intake & { emailed: boolean; to: string }>(`${BASE}/projects/${id}/intake/send/`, { method: "POST", ...json({ email, name }) }),
  markIntakeSent: (id: number, to: string) =>
    safeFetchJson<Intake>(`${BASE}/projects/${id}/intake/mark-sent/`, { method: "POST", ...json({ to }) }),
  connectLink: (id: number) => safeFetchJson<{ link: ConnectLinkInfo | null; links?: ConnectLinkInfo[] }>(`${BASE}/projects/${id}/connect-link/`),
  issueConnectLink: (id: number, body: { providers: ConnectProvider[]; email: string; name: string }) =>
    safeFetchJson<{ url: string; emailed: boolean; to: string; link: ConnectLinkInfo; links?: ConnectLinkInfo[] }>(
      `${BASE}/projects/${id}/connect-link/`, { method: "POST", ...json(body) }),
};

export type ConnectProvider = "quickbooks" | "qb_time" | "asana";
export interface ConnectLinkInfo {
  id?: number;
  providers: ConnectProvider[]; sent_to: string; created_at: string; expires_at: string; open: boolean;
  qbo_connected_at: string | null; qbt_connected_at: string | null; asana_connected_at?: string | null;
}

export interface RosterRow {
  name: string; email: string; role: string; signed_in: boolean;
  last_login: string | null; link_expires: string | null;
}
export interface IssuedInvite { name: string; email: string; role: string; invite_url: string; expires: string; emailed: string; }
export interface KitFile { name: string; content?: string; url?: string; note: string; }

// ── Public intake (no login) ───────────────────────────────────────────────
// Plain fetch on purpose: the firm's browser has no TimeTracker token, and
// attaching an operator's stale one would be meaningless.
export async function intakeRequest(token: string, body?: unknown) {
  const res = await fetch(`${BASE}/intake/${encodeURIComponent(token)}/`, body === undefined
    ? { headers: { Accept: "application/json" } }
    : { method: "POST", headers: { "Content-Type": "application/json", Accept: "application/json" }, body: JSON.stringify(body) });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Something went wrong (${res.status}).`);
  return data;
}

// ── Public connect link (no login) ─────────────────────────────────────────
export interface ConnectStatus {
  firm: string; expires_at: string; open: boolean;
  providers: {
    key: ConnectProvider; label: string; connected: boolean; configured: boolean;
    clients?: number; sync_status?: string; unmatched?: { name: string; email: string }[];
    projects?: number; projects_linked?: number; people_linked?: number;
  }[];
}

export async function connectRequest(token: string, provider?: ConnectProvider) {
  const url = provider
    ? `${BASE}/connect/${encodeURIComponent(token)}/${provider}/start/`
    : `${BASE}/connect/${encodeURIComponent(token)}/`;
  const res = await fetch(url, provider
    ? { method: "POST", headers: { Accept: "application/json" } }
    : { headers: { Accept: "application/json" } });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Something went wrong (${res.status}).`);
  return data;
}
