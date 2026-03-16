import { stopTimer as apiStop } from '../api/client';
import {
  getPendingSaves,
  removePendingSave,
  incrementAttempts,
  PendingSave,
} from './offlineQueue';

const MAX_ATTEMPTS = 5;

/**
 * Call this on app startup and whenever network comes back.
 * Retries all pending saves against the backend.
 * Returns { synced, failed } counts.
 */
export async function syncPendingSaves(): Promise<{ synced: number; failed: number }> {
  const queue = await getPendingSaves();
  if (queue.length === 0) return { synced: 0, failed: 0 };

  console.log(`[OfflineSync] Found ${queue.length} pending save(s) — retrying...`);

  let synced = 0;
  let failed = 0;

  for (const save of queue) {
    if (save.attempts >= MAX_ATTEMPTS) {
      console.warn(`[OfflineSync] Entry ${save.entry_id} exceeded max attempts — skipping`);
      failed++;
      continue;
    }

    try {
      await apiStop({
        entry_id: save.entry_id,
        end_time: save.end_time,
        duration_seconds: save.duration_seconds,
        client_id: save.client_id,
        category_name: save.category_name,
        is_billable: save.is_billable,
        note: save.note,
      });

      await removePendingSave(save.id);
      synced++;
      console.log(`[OfflineSync] ✓ Synced entry ${save.entry_id}`);
    } catch (e) {
      await incrementAttempts(save.id);
      failed++;
      console.warn(`[OfflineSync] ✗ Failed entry ${save.entry_id} (attempt ${save.attempts + 1}):`, e);
    }
  }

  console.log(`[OfflineSync] Done — ${synced} synced, ${failed} failed`);
  return { synced, failed };
}