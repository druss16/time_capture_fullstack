import { useEffect } from 'react';
import { useAuth } from './useAuth'; // or wherever your auth hook is

export interface AICompletionEvent {
  status: 'complete';
  org_id: number;
  user_id: number | null;
  block_ids: number[];
  blocks_processed: number;
  timestamp: string;
}

/**
 * Hook: Subscribe to real-time AI completion events via EventStream.
 * When AI finishes for your org, the callback fires immediately.
 *
 * v2 fixes:
 *  - URL now targets the API host (VITE_API_BASE_URL), not the SPA origin.
 *    The old relative `/api/events/` hit the static frontend, which answered
 *    with index.html ("text/html is not text/event-stream").
 *  - withCredentials so the session cookie rides along cross-origin.
 *  - connect() closes any prior EventSource before opening a new one
 *    (prevents connection leaks during reconnect storms).
 *
 * Usage:
 *   const handleAIComplete = () => {
 *     console.log('AI done! Refetching blocks...');
 *     refetchBlocks();
 *   };
 *   useAICompletion(org_id, handleAIComplete);
 */
export function useAICompletion(
  org_id: number | null,
  onComplete?: (event: AICompletionEvent) => void
) {
  const { user } = useAuth();

  useEffect(() => {
    if (!org_id) return;

    const channel = `org_${org_id}_ai_ready`;

    // Build the URL against the API host — same construction DailyReview uses.
    const RAW_BASE =
      import.meta.env.VITE_API_BASE_URL || 'http://localhost:7123/api';
    const API_BASE = RAW_BASE.endsWith('/api')
      ? RAW_BASE
      : `${RAW_BASE.replace(/\/+$/, '')}/api`;
    const apiUrl = `${API_BASE}/events/?channel=${channel}`;

    let eventSource: EventSource | null = null;
    let reconnectAttempts = 0;
    let cancelled = false;
    const maxReconnectAttempts = 5;

    const connect = () => {
      if (cancelled) return;
      try {
        // Close any prior connection before opening a new one (leak fix).
        eventSource?.close();

        eventSource = new EventSource(apiUrl, { withCredentials: true });

        eventSource.onopen = () => {
          console.log(`[AI-WS] Connected to channel: ${channel}`);
          reconnectAttempts = 0;
        };

        eventSource.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data) as AICompletionEvent;
            console.log(`[AI-WS] Event received:`, data);

            // Filter: only process events for current user (if set)
            if (user?.id && data.user_id && data.user_id !== user.id) {
              console.log(
                `[AI-WS] Skipping event for different user (${data.user_id} vs ${user.id})`
              );
              return;
            }

            onComplete?.(data);
          } catch (err) {
            console.error(`[AI-WS] Failed to parse event:`, err);
          }
        };

        eventSource.onerror = (err) => {
          console.error(`[AI-WS] EventStream error:`, err);

          if (eventSource?.readyState === EventSource.CLOSED) {
            console.log(`[AI-WS] Connection closed, attempting to reconnect...`);
            reconnectAttempts++;

            if (reconnectAttempts <= maxReconnectAttempts) {
              const delay = Math.min(1000 * Math.pow(2, reconnectAttempts), 30000);
              console.log(
                `[AI-WS] Reconnecting in ${delay}ms (attempt ${reconnectAttempts})`
              );
              setTimeout(connect, delay);
            } else {
              console.error(
                `[AI-WS] Max reconnection attempts reached (${maxReconnectAttempts})`
              );
            }
          }
        };
      } catch (err) {
        console.error(`[AI-WS] Failed to create EventSource:`, err);
      }
    };

    connect();

    return () => {
      cancelled = true;
      if (eventSource) {
        eventSource.close();
        console.log(`[AI-WS] Closed connection to channel: ${channel}`);
      }
    };
  }, [org_id, user?.id, onComplete]);
}