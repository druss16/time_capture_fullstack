export const API_BASE = (() => {
  const envUrl = import.meta.env.VITE_API_BASE_URL || "";
  if (envUrl) {
    return envUrl.endsWith("/api") ? envUrl : `${envUrl.replace(/\/+$/, "")}/api`;
  }
  return "/api";
})();

export const API_ENDPOINTS = {
  whoami: `${API_BASE}/whoami/`,
  timecardsSummaryDay: `${API_BASE}/timecards/summary/day/`,
  timercardsGenerate: `${API_BASE}/timecards/generate/`,
} as const;
