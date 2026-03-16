import React from 'react';
import { NavigationContainer } from '@react-navigation/native';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { createStackNavigator } from '@react-navigation/stack';
import { View } from 'react-native';
import HomeScreen from '../screens/Home/HomeScreen';
import RecordingScreen from '../screens/Recording/RecordingScreen';
import HistoryScreen from '../screens/History/HistoryScreen';
import SettingsScreen from '../screens/Settings/SettingsScreen';
import SaveScreen from '../screens/Save/SaveScreen';
import LoginScreen from '../screens/Auth/LoginScreen';
import { Colors, FontSizes } from '../utils/theme';
import type { TabParamList, RootStackParamList } from '../types';
import { useTimerStore } from '../store/timerStore';
import Svg, { Circle, Path } from 'react-native-svg';
import { TimeTrackerIcon } from '../../TimeTrackerLogo';

const Tab = createBottomTabNavigator<TabParamList>();
const Stack = createStackNavigator<RootStackParamList>();

const TEAL = '#2bb5a0';
const TEAL_DIM = 'rgba(255,255,255,0.35)';
const TEAL_BG = 'rgba(43,181,160,0.15)';

function TabIcon({ name, focused }: { name: string; focused: boolean }) {
  const color = focused ? TEAL : TEAL_DIM;

  if (name === 'Home') {
    return (
      <View style={{
        alignItems: 'center',
        justifyContent: 'center',
        width: 48,
        height: 32,
        borderRadius: 16,
        backgroundColor: focused ? TEAL_BG : 'transparent',
      }}>
        <TimeTrackerIcon size={22} variant={focused ? 'default' : 'mono-white'} />
      </View>
    );
  }

  const icons: Record<string, React.ReactNode> = {
    Recording: (
      <Svg width="22" height="22" viewBox="0 0 24 24" fill="none">
        <Circle cx="12" cy="12" r="10" stroke={color} strokeWidth="1.8"/>
        <Circle cx="12" cy="12" r={focused ? "5" : "4"} fill={focused ? TEAL : color}/>
      </Svg>
    ),
    History: (
      <Svg width="22" height="22" viewBox="0 0 24 24" fill="none">
        <Path d="M4 6h16M4 12h10M4 18h7" stroke={color} strokeWidth="1.8" strokeLinecap="round"/>
      </Svg>
    ),
    Settings: (
      <Svg width="22" height="22" viewBox="0 0 24 24" fill="none">
        <Circle cx="12" cy="12" r="3" stroke={color} strokeWidth="1.8"/>
        <Path d="M12 2v2M12 20v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M2 12h2M20 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42" stroke={color} strokeWidth="1.8" strokeLinecap="round"/>
      </Svg>
    ),
  };

  return (
    <View style={{
      alignItems: 'center',
      justifyContent: 'center',
      width: 48,
      height: 32,
      borderRadius: 16,
      backgroundColor: focused ? TEAL_BG : 'transparent',
    }}>
      {icons[name]}
    </View>
  );
}

function MainTabs() {
  const { isRunning } = useTimerStore();

  return (
    <Tab.Navigator
      screenOptions={({ route }) => ({
        tabBarIcon: ({ focused }) => <TabIcon name={route.name} focused={focused} />,
        tabBarActiveTintColor: TEAL,
        tabBarInactiveTintColor: TEAL_DIM,
        tabBarStyle: {
          backgroundColor: '#0d1b2e',
          borderTopWidth: 0.5,
          borderTopColor: 'rgba(255,255,255,0.06)',
          height: 72,
          paddingBottom: 12,
          paddingTop: 8,
        },
        tabBarLabelStyle: {
          fontSize: 10,
          letterSpacing: 0.3,
          fontWeight: '500',
        },
        headerStyle: { backgroundColor: Colors.navy },
        headerTintColor: '#fff',
        headerTitleStyle: { fontWeight: '500', fontSize: 16 },
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

export default function AppNavigator({
  isLoggedIn,
  onLogin,
  onLogout,
}: {
  isLoggedIn: boolean;
  onLogin: () => void;
  onLogout: () => void;
}) {
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