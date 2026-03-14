import * as TaskManager from 'expo-task-manager';
import * as BackgroundFetch from 'expo-background-fetch';
import * as Notifications from 'expo-notifications';
import * as SecureStore from 'expo-secure-store';

export const TIMER_CHECK_TASK = 'TIMER_BACKGROUND_CHECK';
const TIMER_KEY = 'tt_active_timer';
const NOTIF_THRESHOLD_HOURS = 2;

// ─── Notification setup ──────────────────────────────────────────────────────

export async function setupNotifications() {
  const { status } = await Notifications.requestPermissionsAsync();
  if (status !== 'granted') return;

  Notifications.setNotificationHandler({
    handleNotification: async () => ({
      shouldShowAlert: true,
      shouldPlaySound: false,
      shouldSetBadge: false,
    }),
  });
}

export async function scheduleTimerAlert(client_name: string, entry_id: number) {
  await Notifications.cancelAllScheduledNotificationsAsync();
  await Notifications.scheduleNotificationAsync({
    content: {
      title: 'Timer still running',
      body: `Still tracking ${client_name ?? 'time'}? Tap to stop or keep going.`,
      data: { entry_id, action: 'timer_alert' },
    },
    trigger: { seconds: NOTIF_THRESHOLD_HOURS * 3600 },
  });
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
    if (elapsed > NOTIF_THRESHOLD_HOURS) {
      await Notifications.scheduleNotificationAsync({
        content: {
          title: 'Timer still running',
          body: `${Math.round(elapsed)}h on ${timer.client_name ?? 'a timer'} — still going?`,
          data: { action: 'timer_alert' },
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
      minimumInterval: 15 * 60, // 15 minutes
      stopOnTerminate: false,
      startOnBoot: true,
    });
  } catch {
    // Already registered — fine
  }
}
