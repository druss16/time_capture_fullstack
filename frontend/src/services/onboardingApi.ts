// src/services/onboardingApi.ts
/**
 * API service for self-service onboarding flow
 * UPDATED: Now includes industry-specific categories support
 */

const RAW_BASE = import.meta.env.VITE_API_BASE_URL || '/api';
const API_BASE = RAW_BASE.endsWith('/api') ? RAW_BASE.replace(/\/api$/, '/api') : `${RAW_BASE.replace(/\/+$/, '')}/api`;

// Helper to get CSRF token
const getCSRFToken = (): string | null => {
  const match = document.cookie.match(/csrftoken=([^;]+)/);
  return match ? match[1] : null;
};

// Types
export interface User {
  id: number;
  email: string;
  username: string;
  name: string;
}

export interface Organization {
  id: number;
  name: string;
  slug: string;
  plan: string;
  trial_ends_at: string | null;
  industry_type?: string;      // ✅ ADD
  industry_name?: string;      // ✅ ADD (human-readable)
}

export interface SignupResponse {
  ok: boolean;
  token: string;
  user: User;
  organization: Organization;
  install_token: string;
  onboarding_step: number;
  errors?: Record<string, string>;
}

export interface OnboardingSteps {
  account_created: boolean;
  integration_connected: boolean;
  team_invited: boolean;
  rates_configured: boolean;
  agent_installed: boolean;
}

export interface OnboardingStatusResponse {
  organization: Organization;
  steps: OnboardingSteps;
  current_step: number;
  progress: {
    completed: number;
    total: number;
    percent: number;
  };
  is_complete: boolean;
}

export interface Integration {
  id: string;
  provider: string;
  name: string;
  description: string;
  icon: string;
  connected: boolean;
  oauth_url: string;
}

export interface IntegrationListResponse {
  integrations: Integration[];
  has_clients: boolean;
  client_count: number;
}

export interface InviteInput {
  email: string;
  role: 'admin' | 'manager' | 'member';
  name?: string;
}

export interface InviteResult {
  email: string;
  success: boolean;
  user_id?: number;
  username?: string;
  temp_password?: string;
  email_sent?: boolean;
  role?: string;
  error?: string;
}

export interface InviteResponse {
  ok: boolean;
  invited: number;
  total: number;
  results: InviteResult[];
}

export interface TeamMember {
  id: number;
  email: string;
  name: string;
  role: string;
  is_you: boolean;
}

export interface TeamStatusResponse {
  count: number;
  members: TeamMember[];
}

export interface DownloadInfo {
  url: string;
  name: string;
  size: string;
  requirements: string;
}

export interface DownloadInfoResponse {
  detected_os: 'macos' | 'windows' | 'unknown';
  downloads: {
    macos: DownloadInfo;
    windows: DownloadInfo;
  };
  instructions: {
    macos: string[];
    windows: string[];
  };
}

export interface ApiError {
  status: number;
  message?: string;
  errors?: Record<string, string>;
  error?: string;
}

// ✅ NEW: Industry types
export interface IndustryOption {
  value: string;
  label: string;
}

export interface IndustryOptionsResponse {
  industries: IndustryOption[];
}

export interface OrgCategoriesResponse {
  industry_type: string;
  industry_name: string;
  categories: string[];
}

// Helper to get auth headers
const getAuthHeaders = (): HeadersInit => {
  const token = localStorage.getItem('auth_token');
  const csrfToken = getCSRFToken();
  
  return {
    'Content-Type': 'application/json',
    ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
    ...(csrfToken ? { 'X-CSRFToken': csrfToken } : {}),
  };
};

// Generic fetch wrapper with error handling
const apiFetch = async <T>(endpoint: string, options: RequestInit = {}): Promise<T> => {
  const url = endpoint.startsWith('http') ? endpoint : `${API_BASE}${endpoint}`;
  
  const response = await fetch(url, {
    ...options,
    credentials: 'include',
    headers: {
      ...getAuthHeaders(),
      ...(options.headers || {}),
    },
  });
  
  const data = await response.json();
  
  if (!response.ok) {
    throw { status: response.status, ...data } as ApiError;
  }
  
  return data as T;
};

// ============================================================================
// ✅ NEW: INDUSTRY OPTIONS (No auth required - for signup page)
// ============================================================================

export const getIndustryOptions = async (): Promise<IndustryOptionsResponse> => {
  const response = await fetch(`${API_BASE}/industries/`, {
    method: 'GET',
    headers: { 'Content-Type': 'application/json' },
  });
  
  if (!response.ok) {
    // Return fallback options if API fails
    return {
      industries: [
        { value: 'cpa', label: 'CPA / Accounting Firm' },
        { value: 'ai_consulting', label: 'AI / Technology Consulting' },
        { value: 'marketing', label: 'Marketing / Creative Agency' },
        { value: 'legal', label: 'Law Firm / Legal Services' },
        { value: 'general', label: 'General Professional Services' },
      ]
    };
  }
  
  return response.json();
};

// ============================================================================
// ✅ NEW: GET ORG CATEGORIES (Requires auth)
// ============================================================================

export const getOrgCategories = async (): Promise<OrgCategoriesResponse> => {
  return apiFetch<OrgCategoriesResponse>('/categories/');
};

// ============================================================================
// STEP 1: SIGNUP - ✅ UPDATED with industry_type
// ============================================================================

export interface SignupParams {
  firmName: string;
  email: string;
  password: string;
  ownerName?: string;
  timezone?: string;
  industryType?: string;  // ✅ ADD
}

export const signup = async (params: SignupParams): Promise<SignupResponse> => {
  const data = await apiFetch<SignupResponse>('/onboarding/signup/', {
    method: 'POST',
    body: JSON.stringify({
      firm_name: params.firmName,
      email: params.email,
      password: params.password,
      owner_name: params.ownerName || '',
      timezone: params.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone,
      industry_type: params.industryType || 'general',  // ✅ ADD
    }),
  });
  
  if (data.token) {
    localStorage.setItem('auth_token', data.token);
  }
  
  return data;
};

// ============================================================================
// ONBOARDING STATUS
// ============================================================================

export const getOnboardingStatus = async (): Promise<OnboardingStatusResponse> => {
  return apiFetch<OnboardingStatusResponse>('/onboarding/status/');
};

// ============================================================================
// STEP 2: INTEGRATIONS
// ============================================================================

export const getIntegrations = async (): Promise<Integration[]> => {
  const response = await apiFetch<IntegrationListResponse | Integration[]>('/onboarding/integrations/');
  // Handle both array and object response formats
  if (Array.isArray(response)) {
    return response;
  }
  return response.integrations || [];
};

export const connectIntegration = async (provider: string): Promise<{ provider: string; oauth_url: string; state: string }> => {
  return apiFetch(`/onboarding/integrations/${provider}/connect/`, {
    method: 'POST',
  });
};

export const disconnectIntegration = async (provider: string): Promise<{ ok: boolean }> => {
  return apiFetch(`/onboarding/integrations/${provider}/disconnect/`, {
    method: 'POST',
  });
};

export const skipIntegration = async (): Promise<{ ok: boolean; next_step: number }> => {
  return apiFetch('/onboarding/integrations/skip/', {
    method: 'POST',
  });
};

// ============================================================================
// STEP 3: TEAM INVITES
// ============================================================================

export const inviteTeam = async (invites: InviteInput[]): Promise<InviteResponse> => {
  return apiFetch<InviteResponse>('/onboarding/team/invite/', {
    method: 'POST',
    body: JSON.stringify({ invites }),
  });
};

// Alias for inviteTeam that accepts simple email array
export const inviteTeamMembers = async (emails: string[]): Promise<InviteResponse> => {
  const invites = emails.map(email => ({ email, role: 'member' as const }));
  return apiFetch<InviteResponse>('/onboarding/team/invite/', {
    method: 'POST',
    body: JSON.stringify({ invites }),
  });
};

export const getTeamStatus = async (): Promise<TeamStatusResponse> => {
  return apiFetch<TeamStatusResponse>('/onboarding/team/status/');
};

export const skipTeamInvites = async (): Promise<{ ok: boolean; next_step: number }> => {
  return apiFetch('/onboarding/team/skip/', {
    method: 'POST',
  });
};

// ============================================================================
// CSV IMPORT
// ============================================================================

export interface CSVImportResponse {
  ok: boolean;
  message: string;
  clients: number;
  projects: number;
  skipped: number;
  errors: string[] | null;
}

export const importClientsCSV = async (file: File): Promise<CSVImportResponse> => {
  const token = localStorage.getItem('auth_token');
  const csrfToken = getCSRFToken();
  
  const formData = new FormData();
  formData.append('file', file);
  
  const response = await fetch(`${API_BASE}/import-clients-csv/`, {
    method: 'POST',
    credentials: 'include',
    headers: {
      ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
      ...(csrfToken ? { 'X-CSRFToken': csrfToken } : {}),
    },
    body: formData,
  });
  
  const data = await response.json();
  
  if (!response.ok) {
    throw { status: response.status, ...data } as ApiError;
  }
  
  return data as CSVImportResponse;
};

// ============================================================================
// STEP 4: BILLING RATES
// ============================================================================

export interface DefaultRates {
  billing_rate: string;
  cost_rate: string;
}

export const getDefaultRates = async (): Promise<DefaultRates> => {
  return apiFetch<DefaultRates>('/onboarding/rates/default/');
};

export const setDefaultRates = async (rates: { billing_rate: string; cost_rate: string }): Promise<{ ok: boolean }> => {
  return apiFetch('/onboarding/rates/default/', {
    method: 'POST',
    body: JSON.stringify(rates),
  });
};

export const setDefaultRate = async (rate: number): Promise<{ ok: boolean; rate: string }> => {
  return apiFetch('/onboarding/rates/default/', {
    method: 'POST',
    body: JSON.stringify({ rate }),
  });
};

export const skipRates = async (): Promise<{ ok: boolean; next_step: number }> => {
  return apiFetch('/onboarding/rates/skip/', {
    method: 'POST',
  });
};

// ============================================================================
// STEP 5: COMPLETE
// ============================================================================

export const completeOnboarding = async (): Promise<{ ok: boolean; install_token: string | null; next_steps: string[] }> => {
  return apiFetch('/onboarding/complete/', {
    method: 'POST',
  });
};

// ============================================================================
// AGENT DOWNLOAD
// ============================================================================

export const getDownloadInfo = async (): Promise<DownloadInfoResponse> => {
  return apiFetch<DownloadInfoResponse>('/onboarding/download/');
};

// Add these lines BEFORE the default export at the bottom

export const getIndustryOptions = async (): Promise<{ industries: { value: string; label: string }[] }> => {
  try {
    return await apiFetch<{ industries: { value: string; label: string }[] }>('/industries/');
  } catch {
    // Fallback if API not ready
    return {
      industries: [
        { value: 'cpa', label: 'CPA / Accounting Firm' },
        { value: 'ai_consulting', label: 'AI / Technology Consulting' },
        { value: 'marketing', label: 'Marketing / Creative Agency' },
        { value: 'legal', label: 'Law Firm / Legal Services' },
        { value: 'general', label: 'General Professional Services' },
      ]
    };
  }
};

// ============================================================================
// DEFAULT EXPORT
// ============================================================================

const onboardingApi = {
  // ✅ NEW: Industry functions
  getIndustryOptions,
  getOrgCategories,
  
  // Existing functions
  signup,
  getOnboardingStatus,
  getIntegrations,
  connectIntegration,
  disconnectIntegration,
  skipIntegration,
  inviteTeam,
  inviteTeamMembers,
  getTeamStatus,
  skipTeamInvites,
  importClientsCSV,
  getDefaultRates,
  setDefaultRates,
  setDefaultRate,
  skipRates,
  completeOnboarding,
  getDownloadInfo,
};



export default onboardingApi;