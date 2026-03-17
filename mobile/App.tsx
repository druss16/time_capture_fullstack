import React, { useEffect, useState } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import * as Notifications from 'expo-notifications';
import { getStoredToken } from './src/api/client';
import { useTimerStore } from './src/store/timerStore';
import { setupNotifications, registerBackgroundTask } from './src/utils/backgroundTimer';
import { syncPendingSaves } from './src/utils/offlineSync';
import {
  setupMeetingNotificationCategory,
  registerCalendarCheckTask,
  checkCalendarAndNotify,
  handleMeetingNotificationTap,
} from './src/utils/calendarNotifications';
import { startTimer as apiStartTimer } from './src/api/client';
import AppNavigator from './src/navigation/AppNavigator';
import { View, ActivityIndicator } from 'react-native';
import { Colors } from './src/utils/theme';

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 30_000 } },
});

// Configure how notifications appear when app is foregrounded
Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowAlert: true,
    shouldPlaySound: true,
    shouldSetBadge: false,
  }),
});

export default function App() {
  const [isLoggedIn, setIsLoggedIn] = useState(false);
  const [loading, setLoading] = useState(true);
  const restoreTimer = useTimerStore((s) => s.restoreFromStorage);
  const { startTimer: localStart, isRunning } = useTimerStore();

  useEffect(() => {
    async function init() {
      try {
        const token = await getStoredToken();
        setIsLoggedIn(!!token);
        await restoreTimer();
        await setupNotifications();
        await registerBackgroundTask();
        await setupMeetingNotificationCategory();

        if (token) {
          // Sync any offline saves
          syncPendingSaves().then(({ synced }) => {
            if (synced > 0) console.log(`[App] Auto-synced ${synced} offline entry(s)`);
          });

          // Register calendar background check
          await registerCalendarCheckTask();

          // Run an immediate check on launch
          checkCalendarAndNotify();
        }
      } finally {
        setLoading(false);
      }
    }
    init();
  }, []);

  // Handle notification taps
  useEffect(() => {
    const sub = Notifications.addNotificationResponseReceivedListener((response) => {
      handleMeetingNotificationTap(response, {
        onStartTimer: async (clientId, clientName, eventStart, eventEnd, eventTitle) => {
          if (isRunning) return; // Already tracking
          try {
            const draft = await apiStartTimer(clientId ?? undefined);
            localStart(draft.entry_id, clientId, clientName);
          } catch (e) {
            console.warn('[App] Failed to start timer from notification:', e);
          }
        },
        onStopTimer: (clientId, clientName) => {
          // Navigate to save screen — handled by AppNavigator
          console.log('[App] Meeting ended notification tapped');
        },
      });
    });

    return () => sub.remove();
  }, [isRunning]);

  if (loading) {
    return (
      <View style={{ flex: 1, backgroundColor: Colors.navy, alignItems: 'center', justifyContent: 'center' }}>
        <ActivityIndicator color={Colors.teal} size="large" />
      </View>
    );
  }

  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <QueryClientProvider client={queryClient}>
        <AppNavigator
          isLoggedIn={isLoggedIn}
          onLogin={() => setIsLoggedIn(true)}
          onLogout={() => setIsLoggedIn(false)}
        />
      </QueryClientProvider>
    </GestureHandlerRootView>
  );
}