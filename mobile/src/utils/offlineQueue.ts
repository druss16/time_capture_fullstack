import * as SecureStore from 'expo-secure-store';

const QUEUE_KEY = 'tt_pending_saves';

export interface PendingSave {
  id: string;
  entry_id: number;
  end_time: string;
  duration_seconds: number;
  client_id: number | null;
  category_name: string | null;
  is_billable: boolean;
  note: string;
  queued_at: string;
  attempts: number;
}

// ─── Read / Write queue ───────────────────────────────────────────────────────

async function readQueue(): Promise<PendingSave[]> {
  try {
    const raw = await SecureStore.getItemAsync(QUEUE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

async function writeQueue(queue: PendingSave[]): Promise<void> {
  try {
    await SecureStore.setItemAsync(QUEUE_KEY, JSON.stringify(queue));
  } catch (e) {
    console.warn('Failed to write pending save queue:', e);
  }
}

// ─── Public API ───────────────────────────────────────────────────────────────

/** Add a failed save to the retry queue */
export async function enqueueSave(params: Omit<PendingSave, 'id' | 'queued_at' | 'attempts'>): Promise<void> {
  const queue = await readQueue();
  queue.push({
    ...params,
    id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
    queued_at: new Date().toISOString(),
    attempts: 0,
  });
  await writeQueue(queue);
  console.log(`[OfflineQueue] Enqueued save for entry ${params.entry_id}`);
}

/** Get all pending saves */
export async function getPendingSaves(): Promise<PendingSave[]> {
  return readQueue();
}

/** Remove a successfully synced entry from the queue */
export async function removePendingSave(id: string): Promise<void> {
  const queue = await readQueue();
  await writeQueue(queue.filter((s) => s.id !== id));
}

/** Increment attempt count for a pending save */
export async function incrementAttempts(id: string): Promise<void> {
  const queue = await readQueue();
  const updated = queue.map((s) =>
    s.id === id ? { ...s, attempts: s.attempts + 1 } : s
  );
  await writeQueue(updated);
}

/** How many pending saves are waiting */
export async function getPendingCount(): Promise<number> {
  const queue = await readQueue();
  return queue.length;
}

/** Clear entire queue (use with caution) */
export async function clearQueue(): Promise<void> {
  await SecureStore.deleteItemAsync(QUEUE_KEY);
}