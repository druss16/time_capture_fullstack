import React, { useEffect, useState } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { getStoredToken } from './src/api/client';
import { useTimerStore } from './src/store/timerStore';
import { setupNotifications, registerBackgroundTask } from './src/utils/backgroundTimer';
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
        await restoreTimer();          // restore any in-flight timer
        await setupNotifications();
        await registerBackgroundTask();
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
