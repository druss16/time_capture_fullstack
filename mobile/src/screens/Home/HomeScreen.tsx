import React, { useEffect, useRef, useState } from 'react';
import {
  View, Text, TouchableOpacity, StyleSheet,
  Animated, ActivityIndicator, StatusBar, Alert,
} from 'react-native';
import { useNavigation } from '@react-navigation/native';
import * as Haptics from 'expo-haptics';
import { useQuery } from '@tanstack/react-query';
import { useTimerStore, formatDuration } from '../../store/timerStore';
import { startTimer, getMobileRecents, getAISuggestion } from '../../api/client';
import { scheduleTimerAlert } from '../../utils/backgroundTimer';
import { TimeTrackerIcon } from '../../../TimeTrackerLogo';
import type { RootStackParamList } from '../../types';
import type { StackNavigationProp } from '@react-navigation/stack';

type Nav = StackNavigationProp<RootStackParamList>;

const BTN = 160;

export default function HomeScreen() {
  const navigation = useNavigation<Nav>();
  const { isRunning, startTimer: localStart, client_id: activeClientId } = useTimerStore();
  const [starting, setStarting] = useState(false);

  const ring1 = useRef(new Animated.Value(0)).current;
  const ring2 = useRef(new Animated.Value(0)).current;
  const ring3 = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    const animate = (anim: Animated.Value, delay: number) => {
      Animated.loop(
        Animated.sequence([
          Animated.delay(delay),
          Animated.timing(anim, { toValue: 1, duration: 2400, useNativeDriver: true }),
          Animated.timing(anim, { toValue: 0, duration: 0, useNativeDriver: true }),
        ]),
      ).start();
    };
    animate(ring1, 0);
    animate(ring2, 600);
    animate(ring3, 1200);
  }, []);

  const makeRingStyle = (anim: Animated.Value, maxScale: number) => ({
    transform: [{ scale: anim.interpolate({ inputRange: [0, 1], outputRange: [1, maxScale] }) }],
    opacity: anim.interpolate({ inputRange: [0, 0.3, 1], outputRange: [0, 0.15, 0] }),
  });

  const { data: recents } = useQuery({
    queryKey: ['mobile-recents'],
    queryFn: getMobileRecents,
    staleTime: 30_000,
  });

  const { data: aiSuggestion } = useQuery({
    queryKey: ['ai-suggestion'],
    queryFn: getAISuggestion,
    staleTime: 5 * 60_000,
    retry: false,
  });

  async function handleTap() {
    if (isRunning) {
      navigation.navigate('Main', { screen: 'Recording' } as any);
      return;
    }
    try {
      setStarting(true);
      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Heavy);
      const client_id = aiSuggestion?.client_id ?? undefined;
      const client_name = aiSuggestion?.client_name ?? undefined;
      const draft = await startTimer(client_id);
      localStart(draft.entry_id, client_id ?? null, client_name ?? null);
      if (client_name) scheduleTimerAlert(client_name, draft.entry_id);
      navigation.navigate('Main', { screen: 'Recording' } as any);
    } catch (e: any) {
      Alert.alert('Error', e?.response?.data?.detail || e?.message || 'Failed to start timer');
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning);
    } finally {
      setStarting(false);
    }
  }

  // Only show AI suggestion if:
  // - Not already running a timer
  // - No client already selected
  // - Confidence is high enough
  // - Suggestion is for a different client than "Internal"
  const showAiPill =
    aiSuggestion &&
    aiSuggestion.confidence > 0.6 &&
    !isRunning &&
    !activeClientId &&
    aiSuggestion.client_name?.toLowerCase() !== 'internal';

  return (
    <View style={styles.container}>
      <StatusBar barStyle="light-content" />

      {/* AI suggestion pill — only shown when relevant */}
      {showAiPill && (
        <View style={styles.suggestionPill}>
          <View style={styles.pillDot} />
          <Text style={styles.pillText} numberOfLines={1}>{aiSuggestion.reason}</Text>
        </View>
      )}

      {/* Button + rings */}
      <View style={styles.buttonArea}>
        <Animated.View style={[styles.ring, makeRingStyle(ring1, 2.2)]} pointerEvents="none" />
        <Animated.View style={[styles.ring, makeRingStyle(ring2, 2.8)]} pointerEvents="none" />
        <Animated.View style={[styles.ring, makeRingStyle(ring3, 3.4)]} pointerEvents="none" />

        <TouchableOpacity
          onPress={handleTap}
          activeOpacity={0.85}
          disabled={starting}
          style={styles.button}
        >
          {starting ? (
            <ActivityIndicator color="#fff" size="large" />
          ) : (
            <TimeTrackerIcon size={BTN} variant="default" />
          )}
        </TouchableOpacity>
      </View>

      <Text style={styles.tapLabel}>
        {isRunning ? 'Timer running' : 'Tap to start'}
      </Text>

      {recents?.entries && recents.entries.length > 0 && (
        <View style={styles.recentsArea}>
          <Text style={styles.recentsLabel}>Recent</Text>
          {recents.entries.slice(0, 4).map((entry, i) => (
            <View key={entry.id} style={[styles.recentRow, i === 3 && { borderBottomWidth: 0 }]}>
              <View style={styles.recentDot} />
              <View style={{ flex: 1 }}>
                <Text style={styles.recentClient}>{entry.client_name}</Text>
                <Text style={styles.recentCat}>{entry.category_name}</Text>
              </View>
              <Text style={styles.recentDur}>{formatDuration(entry.duration_seconds)}</Text>
            </View>
          ))}
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0d1b2e',
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 24,
  },
  suggestionPill: {
    position: 'absolute',
    top: 60,
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: 'rgba(255,255,255,0.07)',
    borderRadius: 99,
    paddingHorizontal: 16,
    paddingVertical: 8,
    gap: 8,
    maxWidth: 320,
  },
  pillDot: { width: 6, height: 6, borderRadius: 3, backgroundColor: '#2bb5a0' },
  pillText: { fontSize: 12, color: 'rgba(255,255,255,0.7)', flex: 1 },
  buttonArea: {
    width: BTN,
    height: BTN,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 32,
  },
  ring: {
    position: 'absolute',
    width: BTN,
    height: BTN,
    borderRadius: BTN / 2,
    backgroundColor: '#2bb5a0',
  },
  button: {
    width: BTN,
    height: BTN,
    borderRadius: BTN / 2,
    overflow: 'hidden',
    zIndex: 10,
    elevation: 10,
  },
  tapLabel: {
    fontSize: 15,
    color: 'rgba(255,255,255,0.35)',
    letterSpacing: 0.5,
    marginBottom: 60,
  },
  recentsArea: {
    position: 'absolute',
    bottom: 40,
    left: 24,
    right: 24,
    backgroundColor: 'rgba(255,255,255,0.04)',
    borderRadius: 16,
    borderWidth: 0.5,
    borderColor: 'rgba(255,255,255,0.08)',
    paddingHorizontal: 16,
    paddingTop: 12,
    paddingBottom: 4,
  },
  recentsLabel: {
    fontSize: 10,
    color: 'rgba(255,255,255,0.3)',
    textTransform: 'uppercase',
    letterSpacing: 1,
    marginBottom: 8,
  },
  recentRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 9,
    borderBottomWidth: 0.5,
    borderBottomColor: 'rgba(255,255,255,0.06)',
    gap: 10,
  },
  recentDot: { width: 6, height: 6, borderRadius: 3, backgroundColor: 'rgba(255,255,255,0.2)' },
  recentClient: { fontSize: 13, fontWeight: '500', color: 'rgba(255,255,255,0.8)' },
  recentCat: { fontSize: 11, color: 'rgba(255,255,255,0.35)', marginTop: 1 },
  recentDur: { fontSize: 12, color: 'rgba(255,255,255,0.4)' },
});