import * as TaskManager from 'expo-task-manager';
import * as BackgroundFetch from 'expo-background-fetch';
import * as Notifications from 'expo-notifications';
import * as SecureStore from 'expo-secure-store';

export const TIMER_CHECK_TASK = 'TIMER_BACKGROUND_CHECK';
const TIMER_KEY = 'tt_active_timer';

// ─── Notification setup ──────────────────────────────────────────────────────

export async function setupNotifications() {
  const { status } = await Notifications.requestPermissionsAsync();
  if (status !== 'granted') return;
  Notifications.setNotificationHandler({
    handleNotification: async () => ({
      shouldShowAlert: true,
      shouldPlaySound: true,
      shouldSetBadge: true,
    }),
  });
}

// ─── Schedule a cascade of timer alerts ──────────────────────────────────────
// Fires at: 2h, 4h, 5h, 6h, 7h, 8h + end of day 6pm nudge

export async function scheduleTimerAlert(client_name: string, entry_id: number) {
  await Notifications.cancelAllScheduledNotificationsAsync();

  const label = client_name ?? 'a timer';

  const alerts = [
    {
      seconds: 2 * 3600,
      title: 'Timer still running',
      body: `Still tracking ${label}? Tap to stop or keep going.`,
    },
    {
      seconds: 4 * 3600,
      title: '4 hours tracked',
      body: `${label} timer has been running 4 hours — still with them?`,
    },
    {
      seconds: 5 * 3600,
      title: '5 hours — double check',
      body: `${label} timer running 5h. Did you forget to stop it?`,
    },
    {
      seconds: 6 * 3600,
      title: '⚠️ 6 hours tracked',
      body: `Timer still running for ${label}. Tap to stop now.`,
    },
    {
      seconds: 7 * 3600,
      title: '⚠️ 7 hours — please check',
      body: `${label} has been tracking for 7 hours. Is this correct?`,
    },
    {
      seconds: 8 * 3600,
      title: '🚨 8 hours — timer may be stuck',
      body: `${label} timer running for 8 hours. Tap to stop before you overbill.`,
    },
  ];

  for (const alert of alerts) {
    await Notifications.scheduleNotificationAsync({
      content: {
        title: alert.title,
        body: alert.body,
        data: { entry_id, action: 'timer_alert' },
        sound: true,
      },
      trigger: { seconds: alert.seconds },
    });
  }

  // End of day alert — if timer is still running at 6pm today
  const now = new Date();
  const sixPm = new Date();
  sixPm.setHours(18, 0, 0, 0);
  const secsUntil6pm = (sixPm.getTime() - now.getTime()) / 1000;

  if (secsUntil6pm > 60) {
    await Notifications.scheduleNotificationAsync({
      content: {
        title: '🌆 End of day — timer still running',
        body: `Heading out? Stop the ${label} timer before you go.`,
        data: { entry_id, action: 'timer_alert' },
        sound: true,
      },
      trigger: { seconds: Math.floor(secsUntil6pm) },
    });
  }
}

export async function cancelTimerAlert() {
  await Notifications.cancelAllScheduledNotificationsAsync();
}

// ─── Background fetch task (checks for stale timers) ─────────────────────────

TaskManager.defineTask(TIMER_CHECK_TASK, async () => {
  try {
    const raw = await SecureStore.getItemAsync(TIMER_KEY);
    if (!raw) return BackgroundFetch.BackgroundFetchResult.NoData;

    const timer = JSON.parse(raw);
    if (!timer.isRunning || !timer.start_time) {
      return BackgroundFetch.BackgroundFetchResult.NoData;
    }

    const elapsed = (Date.now() - timer.start_time) / 1000 / 3600;

    // Fire immediate alerts for thresholds that may have been missed
    // (e.g. phone was off, background task was delayed)
    const missedThresholds = [2, 4, 6, 8].filter((h) => elapsed > h);

    if (missedThresholds.length > 0) {
      const hours = Math.round(elapsed);
      await Notifications.scheduleNotificationAsync({
        content: {
          title: elapsed > 8
            ? '🚨 Timer running very long'
            : `⚠️ ${hours}h timer still running`,
          body: `${timer.client_name ?? 'Timer'} has been running ${hours}h. Did you forget to stop it?`,
          data: { action: 'timer_alert' },
          sound: true,
        },
        trigger: null, // immediate
      });
    }

    return BackgroundFetch.BackgroundFetchResult.NewData;
  } catch {
    return BackgroundFetch.BackgroundFetchResult.Failed;
  }
});

export async function registerBackgroundTask() {
  try {
    await BackgroundFetch.registerTaskAsync(TIMER_CHECK_TASK, {
      minimumInterval: 15 * 60, // check every 15 minutes
      stopOnTerminate: false,
      startOnBoot: true,
    });
  } catch {
    // Already registered — fine
  }
}