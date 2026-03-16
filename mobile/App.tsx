import React, { useEffect, useState } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { getStoredToken } from './src/api/client';
import { useTimerStore } from './src/store/timerStore';
import { setupNotifications, registerBackgroundTask } from './src/utils/backgroundTimer';
import { syncPendingSaves } from './src/utils/offlineSync';
import AppNavigator from './src/navigation/AppNavigator';
import { View, ActivityIndicator } from 'react-native';
import { Colors } from './src/utils/theme';

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 30_000 } },
});

export default function App() {
  const [isLoggedIn, setIsLoggedIn] = useState(false);
  const [loading, setLoading] = useState(true);
  const restoreTimer = useTimerStore((s) => s.restoreFromStorage);

  useEffect(() => {
    async function init() {
      try {
        const token = await getStoredToken();
        setIsLoggedIn(!!token);
        await restoreTimer();
        await setupNotifications();
        await registerBackgroundTask();

        // Retry any saves that failed due to network/version issues
        if (token) {
          syncPendingSaves().then(({ synced, failed }) => {
            if (synced > 0) console.log(`[App] Auto-synced ${synced} offline entry(s)`);
            if (failed > 0) console.warn(`[App] ${failed} entry(s) still pending`);
          });
        }
      } finally {
        setLoading(false);
      }
    }
    init();
  }, []);

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