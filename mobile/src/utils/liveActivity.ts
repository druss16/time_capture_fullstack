/**
 * liveActivity.ts
 * Wrapper around expo-live-activity for TimeTracker timer pill.
 *
 * Shows in Dynamic Island + lock screen:
 *   ⏱ Aurelia · 2h 14m  [tap to open]
 *
 * Requires native build — not available in Expo Go.
 */

import { Platform } from 'react-native';

// Safe import — won't crash on Android or if not installed
let LiveActivity: any = null;
try {
  LiveActivity = require('expo-live-activity');
} catch {
  // Not installed or not native build
}

// Store the active Live Activity ID
let activeActivityId: string | null = null;

// Brand colors
const NAVY   = '131f2e';
const TEAL   = '2bb5a0';
const WHITE  = 'FFFFFF';

// ─── Start Live Activity when timer starts ────────────────────────────────────

export async function startLiveActivity(
  clientName: string | null,
  startTime: number, // epoch ms
  entryId: number,
): Promise<void> {
  if (Platform.OS !== 'ios' || !LiveActivity) return;

  try {
    const label = clientName ?? 'Timer';

    const state: any = {
      title: `${label}`,
      subtitle: 'TimeTracker · tap to open',
      progressBar: {
        elapsedTimer: {
          startDate: startTime,
        },
      },
    };

    const config: any = {
      backgroundColor: `#${NAVY}`,
      titleColor: `#${WHITE}`,
      subtitleColor: `#${TEAL}`,
      progressViewTint: `#${TEAL}`,
      progressViewLabelColor: `#${WHITE}`,
      timerType: 'digital',
      deepLinkUrl: '/recording',
      padding: { horizontal: 16, top: 12, bottom: 12 },
    };

    activeActivityId = LiveActivity.startActivity(state, config);
    console.log('[LiveActivity] Started:', activeActivityId);
  } catch (e) {
    console.warn('[LiveActivity] Failed to start:', e);
  }
}

// ─── Update Live Activity (e.g. client changes mid-session) ──────────────────

export async function updateLiveActivity(
  clientName: string | null,
  startTime: number,
): Promise<void> {
  if (Platform.OS !== 'ios' || !LiveActivity || !activeActivityId) return;

  try {
    const label = clientName ?? 'Timer';

    await LiveActivity.updateActivity(activeActivityId, {
      title: `${label}`,
      subtitle: 'TimeTracker · tap to open',
      progressBar: {
        elapsedTimer: { startDate: startTime },
      },
    });
  } catch (e) {
    console.warn('[LiveActivity] Failed to update:', e);
  }
}

// ─── Stop Live Activity when timer stops ──────────────────────────────────────

export async function stopLiveActivity(
  clientName: string | null,
  durationSeconds: number,
): Promise<void> {
  if (Platform.OS !== 'ios' || !LiveActivity || !activeActivityId) return;

  try {
    const label = clientName ?? 'Timer';
    const h = Math.floor(durationSeconds / 3600);
    const m = Math.floor((durationSeconds % 3600) / 60);
    const durationStr = h > 0 ? `${h}h ${m}m` : `${m}m`;

    await LiveActivity.stopActivity(activeActivityId, {
      title: `${label} · ${durationStr}`,
      subtitle: 'Session saved ✓',
      progressBar: { progress: 1 },
    });

    activeActivityId = null;
    console.log('[LiveActivity] Stopped');
  } catch (e) {
    console.warn('[LiveActivity] Failed to stop:', e);
  }
}

// ─── Check if a Live Activity is running ─────────────────────────────────────

export function isLiveActivityActive(): boolean {
  return activeActivityId !== null;
}