// src/services/onboardingApi.ts
/**
 * API service for self-service onboarding flow
 */

const API_BASE = import.meta.env.VITE_API_URL || '/api';

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

// Helper to get auth token
const getAuthHeaders = (): HeadersInit => {
  const token = localStorage.getItem('authToken');
  return {
    'Content-Type': 'application/json',
    ...(token ? { 'Authorization': `Token ${token}` } : {}),
  };
};

// Generic fetch wrapper with error handling
const apiFetch = async <T>(endpoint: string, options: RequestInit = {}): Promise<T> => {
  const response = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
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
// STEP 1: SIGNUP
// ============================================================================

export interface SignupParams {
  firmName: string;
  email: string;
  password: string;
  ownerName?: string;
  timezone?: string;
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
    }),
  });
  
  if (data.token) {
    localStorage.setItem('authToken', data.token);
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

export const getIntegrations = async (): Promise<IntegrationListResponse> => {
  return apiFetch<IntegrationListResponse>('/onboarding/integrations/');
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

export const getTeamStatus = async (): Promise<TeamStatusResponse> => {
  return apiFetch<TeamStatusResponse>('/onboarding/team/status/');
};

export const skipTeamInvites = async (): Promise<{ ok: boolean; next_step: number }> => {
  return apiFetch('/onboarding/team/skip/', {
    method: 'POST',
  });
};

// ============================================================================
// STEP 4: BILLING RATES
// ============================================================================

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

const onboardingApi = {
  signup,
  getOnboardingStatus,
  getIntegrations,
  connectIntegration,
  disconnectIntegration,
  skipIntegration,
  inviteTeam,
  getTeamStatus,
  skipTeamInvites,
  setDefaultRate,
  skipRates,
  completeOnboarding,
  getDownloadInfo,
};

export default onboardingApi;