import axios, { AxiosError } from "axios";

export const API_BASE = import.meta.env.VITE_API_BASE_URL as string;

export const API_ROUTES = {
  login: "/api/auth/jwt/create/",
  refresh: "/api/auth/jwt/refresh/",
  blocksToday: "/api/blocks-today/",
  suggestionsToday: "/api/suggestions-today/",
  labelBlock: "/api/label-block/",
  exportBlocksCsv: "/api/export-blocks-today.csv",
};

export interface JwtPair {
  access: string;
  refresh: string;
}

const api = axios.create({
  baseURL: API_BASE,
});

const ACCESS_KEY = "jwt_access";
const REFRESH_KEY = "jwt_refresh";

export function getAccessToken() {
  return localStorage.getItem(ACCESS_KEY);
}
export function getRefreshToken() {
  return localStorage.getItem(REFRESH_KEY);
}
export function setTokens(tokens: Partial<JwtPair>) {
  if (tokens.access) localStorage.setItem(ACCESS_KEY, tokens.access);
  if (tokens.refresh) localStorage.setItem(REFRESH_KEY, tokens.refresh);
}
export function clearTokens() {
  localStorage.removeItem(ACCESS_KEY);
  localStorage.removeItem(REFRESH_KEY);
}

api.interceptors.request.use((config) => {
  const token = getAccessToken();
  if (token) {
    config.headers = config.headers ?? {};
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

let isRefreshing = false;
let pendingRequests: Array<() => void> = [];

async function refreshAccessToken() {
  isRefreshing = true;
  try {
    const refresh = getRefreshToken();
    if (!refresh) throw new Error("No refresh token");
    const { data } = await axios.post<JwtPair>(API_BASE + API_ROUTES.refresh, { refresh });
    setTokens({ access: data.access });
  } finally {
    isRefreshing = false;
    pendingRequests.forEach((cb) => cb());
    pendingRequests = [];
  }
}

api.interceptors.response.use(
  (resp) => resp,
  async (error: AxiosError) => {
    const original = error.config!;
    const status = error.response?.status;

    if (status === 401 && !original._retry) {
      if (isRefreshing) {
        await new Promise<void>((resolve) => pendingRequests.push(resolve));
      } else {
        original._retry = true;
        try {
          await refreshAccessToken();
        } catch {
          clearTokens();
          window.location.href = "/login";
          return Promise.reject(error);
        }
      }
      const token = getAccessToken();
      if (token) {
        original.headers = original.headers ?? {};
        (original.headers as any).Authorization = `Bearer ${token}`;
      }
      return api(original);
    }
    return Promise.reject(error);
  }
);

export default api;
