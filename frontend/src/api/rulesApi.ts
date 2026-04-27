/**
 * src/api/rulesApi.ts
 *
 * Single API module for all rule-system endpoints.
 *
 * Auth assumption: your existing dashboard uses an `auth_token` from
 * localStorage with fallbacks (per your memory notes). This module
 * mirrors that pattern. If your existing API client uses a different
 * auth approach, swap _getAuthHeaders for whatever you use elsewhere.
 */

// ─── Types ─────────────────────────────────────────────────────────

export interface TemplateField {
  name: string;
  label: string;
  type: 'string' | 'int' | 'enum';
  options_key?: string;     // for type=enum: which options list to use
  maps_to: string;          // which OrgRule field this writes to
  required?: boolean;
  placeholder?: string;
}

export interface RuleTemplate {
  id: string;
  label: string;
  emoji: string;
  category: 'routing' | 'categorization' | 'billing' | 'flagging';
  runs_at: 'agent' | 'classifier' | 'compaction' | 'post_save';
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

export interface ListTemplatesResponse {
  templates: RuleTemplate[];
  options: TemplateOptions;
  org: { id: number; name: string } | null;
}

export interface CreateRuleParams {
  template_id: string;
  params: Record<string, string | number>;
  priority?: number;
  enabled?: boolean;
  description?: string;
}

export interface RuleSuggestion {
  template_id: string;
  params: Record<string, string | number>;
  reasoning: string;
  priority: number;
  preview_card: string;
}

export interface SuggestRulesResponse {
  org: { id: number; name: string };
  suggestions: RuleSuggestion[];
  count: number;
}

export interface ParseRuleResponse {
  matched: boolean;
  template_id?: string;
  params?: Record<string, string | number>;
  confidence?: number;
  reasoning?: string;
  explanation?: string;
  suggested_templates?: string[];
}

export interface BlockExplanation {
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

// ─── Auth helper ───────────────────────────────────────────────────

function _getAuthHeaders(): HeadersInit {
  // Mirrors your existing fallback chain per the ExecutiveDashboard pattern.
  const token =
    localStorage.getItem('auth_token') ||
    localStorage.getItem('tt_auth_token') ||
    localStorage.getItem('authToken') ||
    localStorage.getItem('token');

  // Mavops admin secret (used by the impersonation system).
  const adminSecret = localStorage.getItem('mavops_admin_secret') || '';

  const headers: HeadersInit = {
    'Content-Type': 'application/json',
  };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  if (adminSecret) {
    headers['X-Admin-Secret'] = adminSecret;
  }
  return headers;
}

const API_BASE =
  (import.meta as { env?: { VITE_API_BASE?: string } })?.env?.VITE_API_BASE ||
  '';

// ─── Generic fetch wrapper ─────────────────────────────────────────

async function _fetch<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: { ..._getAuthHeaders(), ...(options.headers || {}) },
  });
  if (!res.ok) {
    let body = '';
    try {
      body = await res.text();
    } catch {
      // Ignore parse errors
    }
    throw new Error(`${res.status} ${res.statusText}: ${body}`);
  }
  return res.json() as Promise<T>;
}

// ─── Templates API ─────────────────────────────────────────────────

export async function listRuleTemplates(
  orgId?: number
): Promise<ListTemplatesResponse> {
  const qs = orgId ? `?org_id=${orgId}` : '';
  return _fetch<ListTemplatesResponse>(`/api/mavops/rule-templates/${qs}`);
}

export async function createRuleFromTemplate(
  orgId: number,
  body: CreateRuleParams
): Promise<{ ok: boolean; rule_id: number }> {
  return _fetch(`/api/mavops/orgs/${orgId}/rules/from-template/`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export async function bulkCreateRulesFromTemplates(
  orgId: number,
  suggestions: CreateRuleParams[]
): Promise<{
  ok: boolean;
  created_count: number;
  failed_count: number;
  created: { rule_id: number; template_id: string }[];
  failed: { template_id: string; error: string }[];
}> {
  return _fetch(`/api/mavops/orgs/${orgId}/rules/from-template/bulk/`, {
    method: 'POST',
    body: JSON.stringify({ suggestions }),
  });
}

// ─── LLM #1: Suggest rules from firm context ───────────────────────

export interface FirmContext {
  firm_name?: string;
  industry?: string;
  tax_software?: string[];
  accounting_software?: string[];
  billing_model?: string;
  client_count?: number;
  folder_convention?: string;
  notes?: string;
}

export async function suggestRules(
  orgId: number,
  firmContext: FirmContext,
  maxSuggestions = 25
): Promise<SuggestRulesResponse> {
  return _fetch(`/api/mavops/orgs/${orgId}/rules/suggest/`, {
    method: 'POST',
    body: JSON.stringify({
      firm_context: firmContext,
      max_suggestions: maxSuggestions,
    }),
  });
}

// ─── LLM #2: Parse natural language ────────────────────────────────

export async function parseRule(
  orgId: number,
  text: string
): Promise<ParseRuleResponse> {
  return _fetch(`/api/mavops/orgs/${orgId}/rules/parse/`, {
    method: 'POST',
    body: JSON.stringify({ text }),
  });
}

// ─── LLM #3: Explain a block ───────────────────────────────────────

export async function explainBlock(blockId: number): Promise<BlockExplanation> {
  return _fetch(`/api/mavops/blocks/${blockId}/explain/`);
}