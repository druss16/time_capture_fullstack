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

// ─── Schedule timer alerts ────────────────────────────────────────────────────
// Only schedules alerts for thresholds that haven't been reached yet.
// e.g. if timer already ran 3h, only schedules 4h, 5h, 6h, 7h, 8h + 6pm

export async function scheduleTimerAlert(
  client_name: string,
  entry_id: number,
  alreadyElapsedSeconds: number = 0,
) {
  await Notifications.cancelAllScheduledNotificationsAsync();

  const label = client_name ?? 'a timer';
  const alreadyElapsedHours = alreadyElapsedSeconds / 3600;

  const alerts = [
    {
      hours: 2,
      title: 'Timer still running',
      body: `Still tracking ${label}? Tap to stop or keep going.`,
    },
    {
      hours: 4,
      title: '4 hours tracked',
      body: `${label} timer has been running 4 hours — still with them?`,
    },
    {
      hours: 5,
      title: '5 hours — double check',
      body: `${label} timer running 5h. Did you forget to stop it?`,
    },
    {
      hours: 6,
      title: '⚠️ 6 hours tracked',
      body: `Timer still running for ${label}. Tap to stop now.`,
    },
    {
      hours: 7,
      title: '⚠️ 7 hours — please check',
      body: `${label} has been tracking for 7 hours. Is this correct?`,
    },
    {
      hours: 8,
      title: '🚨 8 hours — timer may be stuck',
      body: `${label} timer running for 8 hours. Tap to stop before you overbill.`,
    },
  ];

  for (const alert of alerts) {
    // Only schedule if we haven't passed this threshold yet
    if (alreadyElapsedHours < alert.hours) {
      const secsFromNow = (alert.hours - alreadyElapsedHours) * 3600;
      await Notifications.scheduleNotificationAsync({
        content: {
          title: alert.title,
          body: alert.body,
          data: { entry_id, action: 'timer_alert' },
          sound: true,
        },
        trigger: { seconds: Math.floor(secsFromNow) },
      });
    }
  }

  // End of day alert at 6pm — only if timer started before 6pm today
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

// ─── Background fetch task ────────────────────────────────────────────────────

TaskManager.defineTask(TIMER_CHECK_TASK, async () => {
  try {
    const raw = await SecureStore.getItemAsync(TIMER_KEY);
    if (!raw) return BackgroundFetch.BackgroundFetchResult.NoData;

    const timer = JSON.parse(raw);
    if (!timer.isRunning || !timer.start_time) {
      return BackgroundFetch.BackgroundFetchResult.NoData;
    }

    const elapsed = (Date.now() - timer.start_time) / 1000 / 3600;
    const lastNotifiedHour = timer.lastNotifiedHour || 0;
    const currentHour = Math.floor(elapsed);

    // Only fire if we've crossed a new hour threshold above 2h
    // and haven't notified for this hour yet
    if (elapsed > 2 && currentHour > lastNotifiedHour) {
      await Notifications.scheduleNotificationAsync({
        content: {
          title: elapsed > 8
            ? '🚨 Timer running very long'
            : `⚠️ ${currentHour}h timer still running`,
          body: `${timer.client_name ?? 'Timer'} has been running ${currentHour}h. Did you forget to stop it?`,
          data: { action: 'timer_alert' },
          sound: true,
        },
        trigger: null, // immediate
      });

      // Mark this hour as notified
      timer.lastNotifiedHour = currentHour;
      await SecureStore.setItemAsync(TIMER_KEY, JSON.stringify(timer));
    }

    return BackgroundFetch.BackgroundFetchResult.NewData;
  } catch {
    return BackgroundFetch.BackgroundFetchResult.Failed;
  }
});

export async function registerBackgroundTask() {
  try {
    await BackgroundFetch.registerTaskAsync(TIMER_CHECK_TASK, {
      minimumInterval: 15 * 60,
      stopOnTerminate: false,
      startOnBoot: true,
    });
  } catch {
    // Already registered
  }
}