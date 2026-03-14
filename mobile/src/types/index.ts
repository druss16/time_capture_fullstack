export interface User {
  id: number;
  email: string;
  first_name: string;
  last_name: string;
  org_name: string;
  role: 'owner' | 'manager' | 'employee';
}

export interface Client {
  id: number;
  name: string;
  color?: string;
  is_active: boolean;
}

export interface Category {
  id: number;
  name: string;
  is_billable_default: boolean;
}

export interface TimeEntry {
  id: number;
  client_id: number;
  client_name: string;
  category_id: number;
  category_name: string;
  start_time: string;       // ISO string
  end_time: string | null;
  duration_seconds: number;
  is_billable: boolean;
  note: string;
  created_at: string;
}

export interface DraftEntry {
  entry_id: number;
  start_time: string;
}

export interface AISuggestion {
  client_id: number | null;
  client_name: string | null;
  category_id: number | null;
  category_name: string | null;
  is_billable: boolean;
  confidence: number;       // 0–1
  reason: string;           // e.g. "You usually track Dauphin at this time on Fridays"
}

export interface VoiceParseResult {
  client_id: number | null;
  client_name: string | null;
  category_id: number | null;
  category_name: string | null;
  note: string;
  is_billable: boolean;
  transcript: string;
}

export interface CalendarEvent {
  id: string;
  title: string;
  startDate: string;
  endDate: string;
  suggested_client_id?: number;
  suggested_client_name?: string;
}

export interface TimerState {
  isRunning: boolean;
  entry_id: number | null;
  start_time: number | null;       // Date.now() timestamp
  client_id: number | null;
  client_name: string | null;
  category_id: number | null;
  category_name: string | null;
  elapsed_seconds: number;
}

export type RootStackParamList = {
  Main: undefined;
  Save: { 
    entry_id: number; 
    duration_seconds: number;
    category_name?: string | null;
    client_id?: number | null;
    client_name?: string | null;
  };

export type TabParamList = {
  Home: undefined;
  History: undefined;
  Settings: undefined;
};
