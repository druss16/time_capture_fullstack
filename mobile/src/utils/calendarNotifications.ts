import * as Calendar from 'expo-calendar';
import * as Notifications from 'expo-notifications';
import * as TaskManager from 'expo-task-manager';
import * as BackgroundFetch from 'expo-background-fetch';
import { suggestFromCalendar } from '../api/client';

const TASK_NAME = 'CALENDAR_MEETING_CHECK';
const NOTIF_CATEGORY = 'MEETING_TIMER';

// ─── Setup notification categories (call once on app start) ──────────────────

export async function setupMeetingNotificationCategory() {
  await Notifications.setNotificationCategoryAsync(NOTIF_CATEGORY, [
    {
      identifier: 'START_TIMER',
      buttonTitle: '▶ Start Timer',
      options: { opensAppToForeground: true },
    },
    {
      identifier: 'DISMISS',
      buttonTitle: 'Dismiss',
      options: { opensAppToForeground: false, isDestructive: true },
    },
  ]);
}

// ─── Get today's upcoming calendar events ────────────────────────────────────

async function getUpcomingEvents() {
  try {
    const { status } = await Calendar.requestCalendarPermissionsAsync();
    if (status !== 'granted') return [];

    const calendars = await Calendar.getCalendarsAsync(Calendar.EntityTypes.EVENT);
    const calendarIds = calendars.map((c) => c.id);

    const now = new Date();
    const lookAhead = new Date(now.getTime() + 30 * 60 * 1000); // next 30 min

    const events = await Calendar.getEventsAsync(calendarIds, now, lookAhead);
    return events.filter((e) => !e.allDay && new Date(e.endDate) > now);
  } catch {
    return [];
  }
}

// ─── Check if we already sent a notification for this event ──────────────────

const notifiedEvents = new Set<string>();

// ─── Main check function ──────────────────────────────────────────────────────

export async function checkCalendarAndNotify() {
  try {
    const events = await getUpcomingEvents();
    if (events.length === 0) return;

    const now = new Date();

    for (const event of events) {
      // Skip if already notified
      if (notifiedEvents.has(event.id)) continue;

      const eventStart = new Date(event.startDate);
      const minsUntilStart = (eventStart.getTime() - now.getTime()) / 60000;

      // Notify if event starts within 2 minutes OR has already started (within last 5 min)
      const isStartingSoon = minsUntilStart >= -5 && minsUntilStart <= 2;
      if (!isStartingSoon) continue;

      // Match event title to a client
      let clientName: string | null = null;
      let clientId: number | null = null;

      try {
        const suggestions = await suggestFromCalendar([event.title]);
        const match = suggestions.find((s) => s.event_title === event.title);
        if (match?.client_id) {
          clientId = match.client_id;
          clientName = match.client_name;
        }
      } catch {}

      // Build notification
      const title = clientName
        ? `${clientName} meeting starting`
        : `Meeting starting: ${event.title}`;

      const body = clientName
        ? `Tap to start tracking time for ${clientName}`
        : `Tap to start the timer for this meeting`;

      await Notifications.scheduleNotificationAsync({
        content: {
          title,
          body,
          categoryIdentifier: NOTIF_CATEGORY,
          data: {
            type: 'MEETING_START',
            eventId: event.id,
            eventTitle: event.title,
            eventStart: event.startDate,
            eventEnd: event.endDate,
            clientId,
            clientName,
          },
          sound: true,
        },
        trigger: null, // Send immediately
      });

      notifiedEvents.add(event.id);

      // Also schedule an end notification
      const eventEnd = new Date(event.endDate);
      const secsUntilEnd = (eventEnd.getTime() - now.getTime()) / 1000;

      if (secsUntilEnd > 0 && secsUntilEnd < 4 * 3600) {
        await Notifications.scheduleNotificationAsync({
          content: {
            title: clientName ? `${clientName} meeting ended` : 'Meeting ended',
            body: 'Tap to save your time entry',
            categoryIdentifier: NOTIF_CATEGORY,
            data: {
              type: 'MEETING_END',
              eventId: event.id,
              eventTitle: event.title,
              eventStart: event.startDate,
              eventEnd: event.endDate,
              clientId,
              clientName,
            },
            sound: true,
          },
          trigger: { seconds: Math.floor(secsUntilEnd) },
        });
      }
    }
  } catch (e) {
    console.warn('[CalendarNotify] Error:', e);
  }
}

// ─── Background task definition ───────────────────────────────────────────────

TaskManager.defineTask(TASK_NAME, async () => {
  try {
    await checkCalendarAndNotify();
    return BackgroundFetch.BackgroundFetchResult.NewData;
  } catch {
    return BackgroundFetch.BackgroundFetchResult.Failed;
  }
});

// ─── Register background task ─────────────────────────────────────────────────

export async function registerCalendarCheckTask() {
  try {
    const isRegistered = await TaskManager.isTaskRegisteredAsync(TASK_NAME);
    if (!isRegistered) {
      await BackgroundFetch.registerTaskAsync(TASK_NAME, {
        minimumInterval: 60, // Check every 60 seconds
        stopOnTerminate: false,
        startOnBoot: true,
      });
    }
  } catch (e) {
    console.warn('[CalendarNotify] Could not register background task:', e);
  }
}

// ─── Handle notification tap ──────────────────────────────────────────────────

export function handleMeetingNotificationTap(
  response: Notifications.NotificationResponse,
  callbacks: {
    onStartTimer: (clientId: number | null, clientName: string | null, eventStart: string, eventEnd: string, eventTitle: string) => void;
    onStopTimer: (clientId: number | null, clientName: string | null) => void;
  }
) {
  const data = response.notification.request.content.data as any;
  const actionId = response.actionIdentifier;

  if (actionId === 'START_TIMER' || actionId === Notifications.DEFAULT_ACTION_IDENTIFIER) {
    if (data?.type === 'MEETING_START') {
      callbacks.onStartTimer(
        data.clientId,
        data.clientName,
        data.eventStart,
        data.eventEnd,
        data.eventTitle,
      );
    } else if (data?.type === 'MEETING_END') {
      callbacks.onStopTimer(data.clientId, data.clientName);
    }
  }
}