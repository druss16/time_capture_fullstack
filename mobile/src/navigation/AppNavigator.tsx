import React from 'react';
import { NavigationContainer } from '@react-navigation/native';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { createStackNavigator } from '@react-navigation/stack';
import { View, Text } from 'react-native';
import HomeScreen from '../screens/Home/HomeScreen';
import RecordingScreen from '../screens/Recording/RecordingScreen';
import HistoryScreen from '../screens/History/HistoryScreen';
import SettingsScreen from '../screens/Settings/SettingsScreen';
import SaveScreen from '../screens/Save/SaveScreen';
import LoginScreen from '../screens/Auth/LoginScreen';
import { Colors, FontSizes } from '../utils/theme';
import type { TabParamList, RootStackParamList } from '../types';
import { useTimerStore } from '../store/timerStore';

const Tab = createBottomTabNavigator<TabParamList>();
const Stack = createStackNavigator<RootStackParamList>();

function TabIcon({ name, focused }: { name: string; focused: boolean }) {
  const icons: Record<string, string> = { Home: '⏱', Recording: '●', History: '≡', Settings: '⚙' };
  return (
    <Text style={{ fontSize: 18, opacity: focused ? 1 : 0.45 }}>{icons[name] ?? '•'}</Text>
  );
}

function MainTabs() {
  const { isRunning, elapsed_seconds } = useTimerStore();

  return (
    <Tab.Navigator
      screenOptions={({ route }) => ({
        tabBarIcon: ({ focused }) => <TabIcon name={route.name} focused={focused} />,
        tabBarActiveTintColor: Colors.teal,
        tabBarInactiveTintColor: 'rgba(255,255,255,0.45)',
        tabBarStyle: {
          backgroundColor: Colors.navy,
          borderTopWidth: 0,
          height: 60,
          paddingBottom: 8,
        },
        tabBarLabelStyle: { fontSize: FontSizes.xs },
        headerStyle: { backgroundColor: Colors.navy },
        headerTintColor: '#fff',
        headerTitleStyle: { fontWeight: '500', fontSize: FontSizes.md },
      })}
    >
      <Tab.Screen
        name="Home"
        component={HomeScreen}
        options={{ title: 'TimeTracker', tabBarLabel: 'Home' }}
      />
      <Tab.Screen
        name="Recording"
        component={RecordingScreen}
        options={{
          title: isRunning ? 'Recording' : 'Timer',
          tabBarLabel: isRunning ? 'Recording' : 'Timer',
          tabBarBadge: isRunning ? '●' : undefined,
          tabBarBadgeStyle: { backgroundColor: Colors.danger, color: Colors.danger, fontSize: 6 },
        }}
      />
      <Tab.Screen
        name="History"
        component={HistoryScreen}
        options={{ title: "Today's Entries", tabBarLabel: 'History' }}
      />
      <Tab.Screen
        name="Settings"
        component={SettingsScreen}
        options={{ title: 'Settings', tabBarLabel: 'Settings' }}
      />
    </Tab.Navigator>
  );
}

export default function AppNavigator({ isLoggedIn, onLogin, onLogout }: { isLoggedIn: boolean; onLogin: () => void; onLogout: () => void }) {
  return (
    <NavigationContainer>
      <Stack.Navigator screenOptions={{ headerShown: false }}>
        {isLoggedIn ? (
          <>
            <Stack.Screen name="Main" component={MainTabs} />
            <Stack.Screen
              name="Save"
              component={SaveScreen}
              options={{
                headerShown: true,
                title: 'Save Entry',
                presentation: 'modal',
                headerStyle: { backgroundColor: Colors.navy },
                headerTintColor: '#fff',
              }}
            />
          </>
        ) : (
          <Stack.Screen name="Login">{() => <LoginScreen onLogin={onLogin} />}</Stack.Screen>
        )}
      </Stack.Navigator>
    </NavigationContainer>
  );
}
