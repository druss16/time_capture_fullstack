import { useEffect, useCallback } from 'react';
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
    const apiUrl = `/api/events/?channel=${channel}`;
 
    let eventSource: EventSource | null = null;
    let reconnectAttempts = 0;
    const maxReconnectAttempts = 5;
 
    const connect = () => {
      try {
        eventSource = new EventSource(apiUrl);
 
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
 
            // Call the callback
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
              console.log(`[AI-WS] Reconnecting in ${delay}ms (attempt ${reconnectAttempts})`);
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
      if (eventSource) {
        eventSource.close();
        console.log(`[AI-WS] Closed connection to channel: ${channel}`);
      }
    };
  }, [org_id, user?.id, onComplete]);
}