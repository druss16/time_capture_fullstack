import axios from 'axios';
import * as SecureStore from 'expo-secure-store';
import Constants from 'expo-constants';
import type {
  TimeEntry, Client, Category, DraftEntry,
  AISuggestion, VoiceParseResult,
} from '../types';

const BASE_URL = Constants.expoConfig?.extra?.apiBaseUrl ?? 'https://timetracker-api-k375.onrender.com/api';

const api = axios.create({
  baseURL: BASE_URL,
  timeout: 15000,
  headers: { 'Content-Type': 'application/json' },
});

// Attach auth token to every request
api.interceptors.request.use(async (config) => {
  const token = await SecureStore.getItemAsync('auth_token');
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// ─── Auth ────────────────────────────────────────────────────────────────────

export async function login(email: string, password: string): Promise<string> {
  const { data } = await api.post('/auth/login/', { email, password });
  const token = data.token;
  await SecureStore.setItemAsync('auth_token', token);
  return token;
}

export async function logout() {
  await SecureStore.deleteItemAsync('auth_token');
}

export async function getStoredToken(): Promise<string | null> {
  return SecureStore.getItemAsync('auth_token');
}

// ─── Mobile-specific endpoints (new) ────────────────────────────────────────

/** Start a draft time entry on the server, returns entry_id + start_time */
export async function startTimer(client_id?: number): Promise<DraftEntry> {
  const { data } = await api.post('/mobile/start/', {
    client_id: client_id ?? null,
    start_time: new Date().toISOString(),
  });
  return data;
}

/** Stop a draft entry — finalizes with duration, client, category */
export async function stopTimer(params: {
  entry_id: number;
  end_time: string;
  duration_seconds: number;
  client_id: number | null;
  category_id: number | null;
  is_billable: boolean;
  note: string;
}): Promise<TimeEntry> {
  const { data } = await api.post('/mobile/stop/', params);
  return data;
}

/** Last 10 entries + client list — lightweight mobile payload */
export async function getMobileRecents(): Promise<{
  entries: TimeEntry[];
  clients: Client[];
  categories: Category[];
}> {
  const { data } = await api.get('/mobile/recent/');
  return data;
}

/** AI suggestion based on time-of-day + day-of-week + history */
export async function getAISuggestion(): Promise<AISuggestion> {
  const now = new Date();
  const { data } = await api.post('/mobile/ai-suggest/', {
    hour: now.getHours(),
    minute: now.getMinutes(),
    day_of_week: now.getDay(),
    local_time: now.toISOString(),
  });
  return data;
}

/** Parse voice memo transcript into client/category/note */
export async function parseVoice(params: {
  audio_base64: string;
  mime_type: string;
}): Promise<VoiceParseResult> {
  const { data } = await api.post('/mobile/voice-parse/', params);
  return data;
}

/** Parse a calendar event title into a suggested client */
export async function suggestFromCalendar(event_titles: string[]): Promise<
  Array<{ event_title: string; client_id: number | null; client_name: string | null }>
> {
  const { data } = await api.post('/mobile/calendar-suggest/', { event_titles });
  return data;
}

// ─── Existing endpoints (already in your Django app) ─────────────────────────

export async function getClients(): Promise<Client[]> {
  const { data } = await api.get('/clients/');
  return data.results ?? data;
}

export async function getCategories(): Promise<Category[]> {
  const { data } = await api.get('/categories/');
  return data.results ?? data;
}

export async function getTodayEntries(): Promise<TimeEntry[]> {
  const today = new Date().toISOString().slice(0, 10);
  const { data } = await api.get(`/blocks-today/`);
  return data.results ?? data;
}

export default api;
