import React, { useEffect, useRef, useState } from 'react';
import {
  View, Text, TouchableOpacity, StyleSheet,
  ScrollView, Animated,
} from 'react-native';
import { useNavigation } from '@react-navigation/native';
import * as Haptics from 'expo-haptics';
import { useQuery } from '@tanstack/react-query';
import { useTimerStore, formatElapsed } from '../../store/timerStore';
import { stopTimer as apiStop, getMobileRecents } from '../../api/client';
import { cancelTimerAlert } from '../../utils/backgroundTimer';
import { useVoiceEntry } from '../../hooks/useVoiceEntry';
import ClientPicker from '../../components/ClientPicker';
import { Colors, FontSizes, Spacing, Radius } from '../../utils/theme';
import type { RootStackParamList } from '../../types';
import type { StackNavigationProp } from '@react-navigation/stack';


type Nav = StackNavigationProp<RootStackParamList>;

const QUICK_CATEGORIES = ['Meeting', 'Phone Call', 'Site Visit', 'Admin'];

export default function RecordingScreen() {
  const navigation = useNavigation<any>();
  const {
    isRunning, entry_id, start_time, elapsed_seconds,
    client_id, client_name, category_id, category_name,
    tick, setClient, setCategory, stopTimer: localStop,
  } = useTimerStore();

  const [showClientPicker, setShowClientPicker] = useState(false);
  const [stopping, setStopping] = useState(false);
  const blinkAnim = useRef(new Animated.Value(1)).current;
  const tickInterval = useRef<ReturnType<typeof setInterval> | null>(null);


  // Voice entry
  const voice = useVoiceEntry();

  // Tick every second
  useEffect(() => {
    if (!isRunning) return;
    tickInterval.current = setInterval(tick, 1000);
    return () => {
      if (tickInterval.current) clearInterval(tickInterval.current);
    };
  }, [isRunning]);

  // Blink the live dot
  useEffect(() => {
    Animated.loop(
      Animated.sequence([
        Animated.timing(blinkAnim, { toValue: 0.3, duration: 600, useNativeDriver: true }),
        Animated.timing(blinkAnim, { toValue: 1, duration: 600, useNativeDriver: true }),
      ]),
    ).start();
  }, []);

  // Apply voice parse results
  useEffect(() => {
    if (voice.result) {
      if (voice.result.client_id) setClient(voice.result.client_id, voice.result.client_name ?? '');
      if (voice.result.category_id) setCategory(voice.result.category_id, voice.result.category_name ?? '');
    }
  }, [voice.result]);

  const { data: recents } = useQuery({
    queryKey: ['mobile-recents'],
    queryFn: getMobileRecents,
    staleTime: 60_000,
  });

  const categories = QUICK_CATEGORIES;

  async function handleStop() {
    setStopping(false); // always reset first
    try {
      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Heavy);
      if (tickInterval.current) clearInterval(tickInterval.current);

      const duration = start_time
        ? Math.floor((Date.now() - start_time) / 1000)
        : elapsed_seconds;

      const savedEntryId = entry_id;
      const savedCategory = category_name;
      const savedClientId = client_id;
      const savedClientName = client_name;

      cancelTimerAlert();
      await localStop();

      navigation.getParent()?.navigate('Save', {
        entry_id: savedEntryId,
        duration_seconds: duration,
        category_name: savedCategory,
        client_id: savedClientId,
        client_name: savedClientName,
      });
    } catch (e) {
      console.log('handleStop error:', e);
    } finally {
      setStopping(false);
    }
  }

  async function handleVoiceTap() {
    if (voice.state === 'recording') {
      await voice.stopRecording();
    } else {
      await voice.startRecording();
    }
  }

  if (!isRunning) {
    return (
      <View style={styles.empty}>
        <Text style={styles.emptyText}>No active timer</Text>
        <Text style={styles.emptyHint}>Go to Home and tap the button</Text>
      </View>
    );
  }

  return (
    <ScrollView style={styles.scroll} contentContainerStyle={styles.container}>

      {/* Timer display */}
      <View style={styles.timerArea}>
        <Text style={styles.timerText}>{formatElapsed(elapsed_seconds)}</Text>
        <View style={styles.liveRow}>
          <Animated.View style={[styles.liveDot, { opacity: blinkAnim }]} />
          <Text style={styles.liveText}>Live — tap button to stop</Text>
        </View>
      </View>

      {/* Stop button */}
      <TouchableOpacity
        onPress={handleStop}
        activeOpacity={0.85}
        disabled={stopping}
        style={styles.stopBtn}
      >
        <View style={styles.stopSquare} />
      </TouchableOpacity>

      {/* Client selector */}
      <TouchableOpacity
        style={styles.clientTag}
        onPress={() => setShowClientPicker(true)}
      >
        <Text style={styles.clientTagText}>
          {client_name ?? 'Tap to select client  ▼'}
        </Text>
        {client_name && <Text style={styles.clientTagEdit}>  ▼</Text>}
      </TouchableOpacity>

      {/* Quick category chips */}
      <Text style={styles.sectionLabel}>Category</Text>
      <View style={styles.chips}>
        {categories.map((cat) => {
          const sel = cat === category_name;
          const matchedCat = recents?.categories?.find((c) => c.name === cat);
          return (
            <TouchableOpacity
              key={cat}
              style={[styles.chip, sel && styles.chipSel]}
              onPress={() => {
                Haptics.selectionAsync();
                if (matchedCat) {
                  setCategory(matchedCat.id, cat);
                } else {
                  // fallback: use 0 as temp id, backend handles name lookup
                  setCategory(0, cat);
                }
              }}
            >
              <Text style={[styles.chipText, sel && styles.chipTextSel]}>{cat}</Text>
            </TouchableOpacity>
          );
        })}
      </View>

      {/* Voice input row */}
      <TouchableOpacity
        style={[styles.voiceRow, voice.state === 'recording' && styles.voiceRowActive]}
        onPress={handleVoiceTap}
      >
        <View style={[styles.micDot, voice.state === 'recording' && styles.micDotActive]} />
        <Text style={styles.voiceText}>
          {voice.state === 'idle' && 'Say client + category to log by voice...'}
          {voice.state === 'recording' && 'Listening... tap to stop'}
          {voice.state === 'processing' && 'AI is parsing your entry...'}
          {voice.state === 'done' && `Logged: "${voice.result?.transcript}"`}
          {voice.state === 'error' && 'Could not parse — try again'}
        </Text>
      </TouchableOpacity>

      {/* Voice AI result preview */}
      {voice.state === 'done' && voice.result && (
        <View style={styles.aiBanner}>
          <View style={styles.aiDot} />
          <Text style={styles.aiText}>
            AI set: {voice.result.client_name ?? '—'} · {voice.result.category_name ?? '—'}
            {voice.result.note ? ` · "${voice.result.note}"` : ''}
          </Text>
        </View>
      )}

      <ClientPicker
        visible={showClientPicker}
        clients={recents?.clients ?? []}
        onSelect={(c) => { setClient(c.id, c.name); setShowClientPicker(false); }}
        onClose={() => setShowClientPicker(false)}
      />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  scroll: { flex: 1, backgroundColor: Colors.bg },
  container: { padding: Spacing.lg, paddingTop: Spacing.xxl, alignItems: 'center' },
  empty: { flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: Colors.bg },
  emptyText: { fontSize: FontSizes.lg, color: Colors.textPrimary, fontWeight: '500' },
  emptyHint: { fontSize: FontSizes.sm, color: Colors.textMuted, marginTop: Spacing.sm },

  timerArea: { alignItems: 'center', marginBottom: Spacing.xl },
  timerText: { fontSize: 52, fontWeight: '300', color: Colors.navy, letterSpacing: 2 },
  liveRow: { flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 4 },
  liveDot: { width: 7, height: 7, borderRadius: 3.5, backgroundColor: Colors.danger },
  liveText: { fontSize: FontSizes.sm, color: Colors.textMuted },

  stopBtn: {
    width: 80,
    height: 80,
    borderRadius: 40,
    backgroundColor: Colors.danger,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: Spacing.xl,
  },
  stopSquare: { width: 26, height: 26, backgroundColor: '#fff', borderRadius: 6 },

  clientTag: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: Colors.aiBg,
    borderRadius: Radius.pill,
    paddingHorizontal: 16,
    paddingVertical: 8,
    marginBottom: Spacing.lg,
    borderWidth: 1,
    borderColor: Colors.aiBorder,
  },
  clientTagText: { fontSize: FontSizes.base, color: Colors.aiText, fontWeight: '500' },
  clientTagEdit: { fontSize: FontSizes.sm, color: Colors.teal },

  sectionLabel: {
    alignSelf: 'flex-start',
    fontSize: FontSizes.xs,
    color: Colors.textMuted,
    textTransform: 'uppercase',
    letterSpacing: 0.8,
    marginBottom: Spacing.sm,
  },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: Spacing.sm, justifyContent: 'flex-start', width: '100%', marginBottom: Spacing.lg },
  chip: {
    borderWidth: 0.5,
    borderColor: Colors.borderMid,
    borderRadius: Radius.pill,
    paddingHorizontal: 14,
    paddingVertical: 7,
    backgroundColor: Colors.bgCard,
  },
  chipSel: { backgroundColor: Colors.aiBg, borderColor: Colors.aiBorder },
  chipText: { fontSize: FontSizes.sm, color: Colors.textSecondary },
  chipTextSel: { color: Colors.aiText, fontWeight: '500' },

  voiceRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.sm,
    borderWidth: 0.5,
    borderColor: Colors.borderMid,
    borderRadius: Radius.md,
    padding: Spacing.md,
    backgroundColor: Colors.bgCard,
    width: '100%',
    marginBottom: Spacing.md,
  },
  voiceRowActive: { borderColor: Colors.danger, backgroundColor: '#fff5f5' },
  micDot: { width: 16, height: 16, borderRadius: 8, backgroundColor: Colors.teal },
  micDotActive: { backgroundColor: Colors.danger },
  voiceText: { fontSize: FontSizes.sm, color: Colors.textMuted, flex: 1 },

  aiBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: Colors.aiBg,
    borderWidth: 1,
    borderColor: Colors.aiBorder,
    borderRadius: Radius.md,
    padding: Spacing.md,
    width: '100%',
    gap: Spacing.sm,
  },
  aiDot: { width: 8, height: 8, borderRadius: 4, backgroundColor: Colors.teal },
  aiText: { flex: 1, fontSize: FontSizes.sm, color: Colors.aiText },
});
