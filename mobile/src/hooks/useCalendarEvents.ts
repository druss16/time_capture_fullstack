import { useState, useEffect } from 'react';
import * as Calendar from 'expo-calendar';
import { suggestFromCalendar } from '../api/client';
import type { CalendarEvent } from '../types';

export function useCalendarEvents() {
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    loadTodayEvents();
  }, []);

  async function loadTodayEvents() {
    try {
      setLoading(true);
      const { status } = await Calendar.requestCalendarPermissionsAsync();
      if (status !== 'granted') return;

      const calendars = await Calendar.getCalendarsAsync(Calendar.EntityTypes.EVENT);
      const calendarIds = calendars.map((c) => c.id);

      const start = new Date();
      start.setHours(0, 0, 0, 0);
      const end = new Date();
      end.setHours(23, 59, 59, 999);

      const rawEvents = await Calendar.getEventsAsync(calendarIds, start, end);

      // Filter to upcoming/current events only
      const now = new Date();
      const upcoming = rawEvents
        .filter((e) => new Date(e.endDate) > now)
        .map((e) => ({
          id: e.id,
          title: e.title,
          startDate: e.startDate as string,
          endDate: e.endDate as string,
        }))
        .slice(0, 10);

      if (upcoming.length === 0) return;

      // Ask backend to match event titles → clients
      const suggestions = await suggestFromCalendar(upcoming.map((e) => e.title));
      const enriched: CalendarEvent[] = upcoming.map((e) => {
        const match = suggestions.find((s) => s.event_title === e.title);
        return {
          ...e,
          suggested_client_id: match?.client_id ?? undefined,
          suggested_client_name: match?.client_name ?? undefined,
        };
      });

      setEvents(enriched);
    } catch {
      // Calendar permission denied or error — silent fail
    } finally {
      setLoading(false);
    }
  }

  return { events, loading, reload: loadTodayEvents };
}
