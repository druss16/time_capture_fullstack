import { create } from 'zustand';
import * as SecureStore from 'expo-secure-store';
import type { TimerState } from '../types';

const TIMER_KEY = 'tt_active_timer';

interface TimerStore extends TimerState {
  // Actions
  startTimer: (entry_id: number, client_id?: number | null, client_name?: string | null) => void;
  stopTimer: () => Promise<{ entry_id: number; duration_seconds: number }>;
  setClient: (id: number, name: string) => void;
  setCategory: (id: number, name: string) => void;
  tick: () => void;
  restoreFromStorage: () => Promise<void>;
}

export const useTimerStore = create<TimerStore>((set, get) => ({
  isRunning: false,
  entry_id: null,
  start_time: null,
  client_id: null,
  client_name: null,
  category_id: null,
  category_name: null,
  elapsed_seconds: 0,

  startTimer: (entry_id, client_id = null, client_name = null) => {
    const start_time = Date.now();
    const state = {
      isRunning: true,
      entry_id,
      start_time,
      client_id,
      client_name,
      category_id: null,
      category_name: null,
      elapsed_seconds: 0,
    };
    set(state);
    // Persist so we survive app kill
    SecureStore.setItemAsync(TIMER_KEY, JSON.stringify(state));
  },

  stopTimer: async () => {
    const { entry_id, start_time, elapsed_seconds } = get();
    const duration = start_time
      ? Math.floor((Date.now() - start_time) / 1000)
      : elapsed_seconds;

    set({
      isRunning: false,
      entry_id: null,
      start_time: null,
      elapsed_seconds: 0,
    });
    await SecureStore.deleteItemAsync(TIMER_KEY);

    return { entry_id: entry_id!, duration_seconds: duration };
  },

  setClient: (id, name) => {
    set({ client_id: id, client_name: name });
    const current = get();
    SecureStore.setItemAsync(TIMER_KEY, JSON.stringify(current));
  },

  setCategory: (id, name) => {
    set({ category_id: id, category_name: name });
  },

  tick: () => {
    const { start_time } = get();
    if (start_time) {
      set({ elapsed_seconds: Math.floor((Date.now() - start_time) / 1000) });
    }
  },

  restoreFromStorage: async () => {
    try {
      const raw = await SecureStore.getItemAsync(TIMER_KEY);
      if (!raw) return;
      const saved = JSON.parse(raw) as TimerState;
      if (saved.isRunning && saved.start_time) {
        const elapsed = Math.floor((Date.now() - saved.start_time) / 1000);
        set({ ...saved, elapsed_seconds: elapsed });
      }
    } catch {
      // storage corrupt — clear it
      SecureStore.deleteItemAsync(TIMER_KEY);
    }
  },
}));

// ─── Helpers ──────────────────────────────────────────────────────────────────

export function formatElapsed(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

export function formatDuration(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (h > 0 && m > 0) return `${h}h ${m}m`;
  if (h > 0) return `${h}h`;
  if (m > 0) return `${m}m`;
  return `${seconds}s`;
}
