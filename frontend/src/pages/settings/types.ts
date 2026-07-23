// src/pages/settings/types.ts
// Shared types for all Settings tab components

export type PlanType = 'professional' | 'executive' | 'none';
export type RoleType = 'owner' | 'admin' | 'manager' | 'member';

export type Tab =
  | 'organization' | 'team' | 'clients' | 'assignments' | 'groups'
  | 'integrations' | 'billing' | 'costs' | 'devices' | 'token' | 'deployment'
  | 'task-types' | 'task-type-sets';

export interface TabConfig {
  id: Tab;
  label: string;
  icon: React.ReactNode;
  requiredPlan?: PlanType[];
  requiredRole?: ('owner' | 'admin' | 'manager')[];
}

export type OrgInfo = {
  id: number;
  name: string;
  slug?: string;
  plan: PlanType;
  trial_ends_at: string | null;
  billing_email: string;
  billing_contact: string;
  billing_rate_default: string;
  cost_rate_default?: string;
  created_at: string;
};

export type TeamMember = {
  id: number;
  username: string;
  email: string;
  first_name: string;
  last_name: string;
  is_active: boolean;
  role: 'owner' | 'admin' | 'manager' | 'member';
  last_login: string | null;
  date_joined: string;
};

export type Client = {
  id: number;
  name: string;
  code: string;
  is_active: boolean;
  visibility: 'all' | 'assigned' | 'confidential';
  aliases: string[];
  created_at: string;
};

export type Device = {
  id: number;
  user: string;
  user_id: number;
  machine_name: string;
  os: string;
  os_version: string;
  agent_version: string;
  first_seen: string;
  last_seen: string;
  is_active: boolean;
};

export type InstallToken = {
  token: string;
  created_at: string;
  is_active: boolean;
};

export type BillingRate = {
  id: number;
  user: number | null;
  user_name: string;
  client: number | null;
  client_name: string;
  task_type: number | null;
  task_type_name: string;
  rate: string;
  hourly_rate?: string;
  effective_date: string;
  end_date: string | null;
  is_default: boolean;
};

export type EmployeeCostRate = {
  id: number;
  user: number;
  user_name: string;
  cost_rate: string;
  effective_date: string;
  end_date: string | null;
};

// Helper
export const getUserDisplayName = (user: TeamMember): string => {
  const fullName = `${user.first_name || ''} ${user.last_name || ''}`.trim();
  if (fullName) return fullName;
  if (user.username) return user.username;
  if (user.email) return user.email;
  return `User ${user.id}`;
};

export const PROFESSIONAL_PLANS: PlanType[] = ['professional', 'executive'];
export const EXECUTIVE_PLANS: PlanType[] = ['executive'];

/**
 * Plan tiers in ascending order of capability. To add a new tier, add it to
 * PlanType above and drop it into this list at the right position — gates
 * expressed as "tier X and above" (see planRank / hasAnalyticsAccess) will
 * pick it up automatically, no gate logic to change.
 */
export const PLAN_TIER_ORDER: PlanType[] = ['none', 'professional', 'executive'];

/** Ordinal rank of a plan; unknown / missing plans rank at the bottom. */
export function planRank(plan: PlanType | null | undefined): number {
  const idx = PLAN_TIER_ORDER.indexOf((plan ?? 'none') as PlanType);
  return idx === -1 ? 0 : idx;
}

/**
 * Analytics is unlocked for the Executive tier and anything above it.
 * Professional and no-plan orgs are locked.
 */
export function hasAnalyticsAccess(plan: PlanType | null | undefined): boolean {
  return planRank(plan) >= planRank('executive');
}