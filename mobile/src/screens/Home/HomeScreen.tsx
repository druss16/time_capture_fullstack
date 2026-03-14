import React, { useEffect, useRef, useState } from 'react';
import {
  View, Text, TouchableOpacity, StyleSheet,
  Animated, ScrollView, ActivityIndicator,
} from 'react-native';
import { useNavigation } from '@react-navigation/native';
import * as Haptics from 'expo-haptics';
import { useQuery } from '@tanstack/react-query';
import { useTimerStore, formatDuration } from '../../store/timerStore';
import { startTimer, getMobileRecents, getAISuggestion } from '../../api/client';
import { scheduleTimerAlert } from '../../utils/backgroundTimer';
import { useCalendarEvents } from '../../hooks/useCalendarEvents';
import { Colors, FontSizes, Spacing, Radius } from '../../utils/theme';
import type { RootStackParamList } from '../../types';
import type { StackNavigationProp } from '@react-navigation/stack';

type Nav = StackNavigationProp<RootStackParamList>;

export default function HomeScreen() {
  const navigation = useNavigation<Nav>();
  const { isRunning, startTimer: localStart } = useTimerStore();
  const [starting, setStarting] = useState(false);

  // Pulse animation rings
  const ring1 = useRef(new Animated.Value(0)).current;
  const ring2 = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    const pulse = () => {
      Animated.loop(
        Animated.sequence([
          Animated.timing(ring1, { toValue: 1, duration: 1800, useNativeDriver: true }),
          Animated.timing(ring1, { toValue: 0, duration: 0, useNativeDriver: true }),
        ]),
      ).start();
      setTimeout(() => {
        Animated.loop(
          Animated.sequence([
            Animated.timing(ring2, { toValue: 1, duration: 1800, useNativeDriver: true }),
            Animated.timing(ring2, { toValue: 0, duration: 0, useNativeDriver: true }),
          ]),
        ).start();
      }, 500);
    };
    pulse();
  }, []);

  const ringScale1 = ring1.interpolate({ inputRange: [0, 1], outputRange: [1, 1.6] });
  const ringOpacity1 = ring1.interpolate({ inputRange: [0, 1], outputRange: [0.5, 0] });
  const ringScale2 = ring2.interpolate({ inputRange: [0, 1], outputRange: [1, 2] });
  const ringOpacity2 = ring2.interpolate({ inputRange: [0, 1], outputRange: [0.3, 0] });

  // Data queries
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

  const { events: calEvents } = useCalendarEvents();

  async function handleTap() {
    if (isRunning) {
      navigation.navigate('Main'); // goes to Recording tab
      return;
    }
    try {
      setStarting(true);
      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Heavy);
      const client_id = aiSuggestion?.client_id ?? undefined;
      const client_name = aiSuggestion?.client_name ?? undefined;
      const draft = await startTimer(client_id);
      localStart(draft.entry_id, client_id ?? null, client_name ?? null);
      if (client_name) {
        scheduleTimerAlert(client_name, draft.entry_id);
      }
      navigation.navigate('Main', { screen: 'Recording' });
    } catch (e) {
      // If server unreachable, start locally — will sync on stop
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning);
    } finally {
      setStarting(false);
    }
  }

  async function handleAcceptSuggestion() {
    if (!aiSuggestion?.client_id) return;
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    try {
      setStarting(true);
      const draft = await startTimer(aiSuggestion.client_id);
      localStart(draft.entry_id, aiSuggestion.client_id, aiSuggestion.client_name);
      if (aiSuggestion.client_name) {
        scheduleTimerAlert(aiSuggestion.client_name, draft.entry_id);
      }
      navigation.navigate('Main');
    } finally {
      setStarting(false);
    }
  }

  // Upcoming calendar event within 15 minutes
  const upcomingEvent = calEvents.find((e) => {
    const diff = (new Date(e.startDate).getTime() - Date.now()) / 60000;
    return diff >= -5 && diff <= 15;
  });

  return (
    <ScrollView style={styles.scroll} contentContainerStyle={styles.container}>

      {/* AI suggestion banner */}
      {aiSuggestion && aiSuggestion.confidence > 0.6 && !isRunning && (
        <View style={styles.aiBanner}>
          <View style={styles.aiDot} />
          <Text style={styles.aiText} numberOfLines={2}>
            {aiSuggestion.reason}
          </Text>
          <TouchableOpacity onPress={handleAcceptSuggestion} style={styles.aiYes}>
            <Text style={styles.aiYesText}>Start</Text>
          </TouchableOpacity>
        </View>
      )}

      {/* Calendar event banner */}
      {upcomingEvent && !aiSuggestion && !isRunning && (
        <View style={styles.aiBanner}>
          <View style={styles.aiDot} />
          <Text style={styles.aiText} numberOfLines={2}>
            "{upcomingEvent.title}" is coming up
            {upcomingEvent.suggested_client_name ? ` — ${upcomingEvent.suggested_client_name}` : ''}
          </Text>
          <TouchableOpacity
            onPress={() => {
              if (upcomingEvent.suggested_client_id) {
                startTimer(upcomingEvent.suggested_client_id).then((d) => {
                  localStart(d.entry_id, upcomingEvent.suggested_client_id, upcomingEvent.suggested_client_name);
                });
              }
            }}
            style={styles.aiYes}
          >
            <Text style={styles.aiYesText}>Start</Text>
          </TouchableOpacity>
        </View>
      )}

      {/* The big button */}
      <View style={styles.btnArea}>
        <TouchableOpacity onPress={handleTap} activeOpacity={0.85} disabled={starting}>
          <View style={styles.btnOuter}>
            <Animated.View
              style={[styles.ring, { transform: [{ scale: ringScale1 }], opacity: ringOpacity1 }]}
            />
            <Animated.View
              style={[styles.ring, { transform: [{ scale: ringScale2 }], opacity: ringOpacity2 }]}
            />
            <View style={styles.btn}>
              {starting ? (
                <ActivityIndicator color="#fff" size="large" />
              ) : (
                <TimerIcon />
              )}
            </View>
          </View>
        </TouchableOpacity>
        <Text style={styles.hint}>
          {isRunning ? 'Timer running — tap Recording' : 'Tap to start tracking'}
        </Text>
      </View>

      {/* Recent entries */}
      {recents?.entries && recents.entries.length > 0 && (
        <View style={styles.recents}>
          <Text style={styles.sectionLabel}>Recent</Text>
          {recents.entries.slice(0, 5).map((entry, i) => (
            <View key={entry.id} style={[styles.recentRow, i === 4 && { borderBottomWidth: 0 }]}>
              <View style={[styles.recentDot, { backgroundColor: dotColor(i) }]} />
              <View style={styles.recentInfo}>
                <Text style={styles.recentClient}>{entry.client_name}</Text>
                <Text style={styles.recentCat}>{entry.category_name}</Text>
              </View>
              <Text style={styles.recentDur}>{formatDuration(entry.duration_seconds)}</Text>
            </View>
          ))}
        </View>
      )}
    </ScrollView>
  );
}

function TimerIcon() {
  return (
    <View style={{ alignItems: 'center', justifyContent: 'center', width: 36, height: 36 }}>
      {/* Simple clock icon in pure RN */}
      <View style={{ width: 30, height: 30, borderRadius: 15, borderWidth: 2, borderColor: '#fff', alignItems: 'center', justifyContent: 'center' }}>
        <View style={{ position: 'absolute', width: 2, height: 10, backgroundColor: '#fff', borderRadius: 1, top: 4, left: 13 }} />
        <View style={{ position: 'absolute', width: 8, height: 2, backgroundColor: '#fff', borderRadius: 1, top: 13, left: 13 }} />
      </View>
    </View>
  );
}

const dotColors = [Colors.teal, Colors.navy, Colors.tealLight, Colors.textSecondary, Colors.tealDark];
function dotColor(i: number) { return dotColors[i % dotColors.length]; }

const styles = StyleSheet.create({
  scroll: { flex: 1, backgroundColor: Colors.bg },
  container: { padding: Spacing.lg, paddingTop: Spacing.xl, paddingBottom: 40 },

  aiBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: Colors.aiBg,
    borderWidth: 1,
    borderColor: Colors.aiBorder,
    borderRadius: Radius.md,
    padding: Spacing.md,
    marginBottom: Spacing.lg,
    gap: Spacing.sm,
  },
  aiDot: { width: 8, height: 8, borderRadius: 4, backgroundColor: Colors.teal, flexShrink: 0 },
  aiText: { flex: 1, fontSize: FontSizes.sm, color: Colors.aiText, lineHeight: 16 },
  aiYes: {
    backgroundColor: Colors.teal,
    borderRadius: Radius.pill,
    paddingHorizontal: 12,
    paddingVertical: 5,
  },
  aiYesText: { color: '#fff', fontSize: FontSizes.xs, fontWeight: '600' },

  btnArea: { alignItems: 'center', marginVertical: Spacing.xxl },
  btnOuter: { width: 120, height: 120, alignItems: 'center', justifyContent: 'center' },
  ring: {
    position: 'absolute',
    width: 120,
    height: 120,
    borderRadius: 60,
    borderWidth: 1.5,
    borderColor: Colors.teal,
  },
  btn: {
    width: 90,
    height: 90,
    borderRadius: 45,
    backgroundColor: Colors.teal,
    alignItems: 'center',
    justifyContent: 'center',
    zIndex: 1,
  },
  hint: { marginTop: Spacing.md, fontSize: FontSizes.sm, color: Colors.textMuted },

  recents: {
    backgroundColor: Colors.bgCard,
    borderRadius: Radius.lg,
    borderWidth: 0.5,
    borderColor: Colors.border,
    padding: Spacing.lg,
  },
  sectionLabel: {
    fontSize: FontSizes.xs,
    color: Colors.textMuted,
    textTransform: 'uppercase',
    letterSpacing: 0.8,
    marginBottom: Spacing.sm,
  },
  recentRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: Spacing.sm,
    borderBottomWidth: 0.5,
    borderBottomColor: Colors.border,
    gap: Spacing.sm,
  },
  recentDot: { width: 8, height: 8, borderRadius: 4 },
  recentInfo: { flex: 1 },
  recentClient: { fontSize: FontSizes.sm, fontWeight: '500', color: Colors.textPrimary },
  recentCat: { fontSize: FontSizes.xs, color: Colors.textMuted },
  recentDur: { fontSize: FontSizes.sm, color: Colors.textPrimary },
});
