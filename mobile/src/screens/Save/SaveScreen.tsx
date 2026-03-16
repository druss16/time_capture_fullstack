import React, { useEffect, useState } from 'react';
import {
  View, Text, TouchableOpacity, StyleSheet,
  TextInput, Switch, ScrollView, ActivityIndicator, Alert,
} from 'react-native';
import { useNavigation, useRoute, RouteProp } from '@react-navigation/native';
import * as Haptics from 'expo-haptics';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { stopTimer as apiStop, getMobileRecents, getAISuggestion } from '../../api/client';
import { useTimerStore, formatDuration } from '../../store/timerStore';
import ClientPicker from '../../components/ClientPicker';
import { Colors, FontSizes, Spacing, Radius } from '../../utils/theme';
import type { RootStackParamList } from '../../types';
import type { StackNavigationProp } from '@react-navigation/stack';

type Nav = StackNavigationProp<RootStackParamList>;
type Route = RouteProp<RootStackParamList, 'Save'>;

export default function SaveScreen() {
  const navigation = useNavigation<Nav>();
  const route = useRoute<Route>();
  const { entry_id, duration_seconds, category_name: routeCategory, client_id: routeClientId, client_name: routeClientName } = route.params;
  const qc = useQueryClient();

  const timerStore = useTimerStore();

  const [clientId, setClientId] = useState<number | null>(routeClientId ?? timerStore.client_id);
  const [clientName, setClientName] = useState<string | null>(routeClientName ?? timerStore.client_name);
  const [categoryId, setCategoryId] = useState<number | null>(null);
  const [categoryName, setCategoryName] = useState<string | null>(
  routeCategory ?? timerStore.category_name ?? 'Meeting'
  );
  const [isBillable, setIsBillable] = useState(true);
  const [note, setNote] = useState('');
  const [saving, setSaving] = useState(false);
  const [showClientPicker, setShowClientPicker] = useState(false);
  const [aiPrefilled, setAiPrefilled] = useState(false);

  const { data: recents } = useQuery({
    queryKey: ['mobile-recents'],
    queryFn: getMobileRecents,
    staleTime: 60_000,
  });

  // If nothing pre-selected, fetch AI suggestion
  useEffect(() => {
    if (!clientId) {
      getAISuggestion()
        .then((s) => {
          if (s.client_id && !clientId) {
            setClientId(s.client_id);
            setClientName(s.client_name);
            setAiPrefilled(true);
          }
          if (s.category_id && !categoryId) {
            setCategoryId(s.category_id);
            setCategoryName(s.category_name);
            setIsBillable(s.confidence > 0.7);
          }
        })
        .catch(() => {});
    } else {
      setAiPrefilled(!!timerStore.client_id);
    }
  }, []);

  async function handleSave() {
    if (!clientId) {
      Alert.alert('Select a client', 'Please select a client before saving.');
      return;
    }
    try {
      setSaving(true);
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);

      await apiStop({
        entry_id,
        end_time: new Date().toISOString(),
        duration_seconds,
        client_id: clientId,
        category_name: categoryName,
        is_billable: isBillable,
        note,
      });

      // Bust caches so dashboard refreshes
      qc.invalidateQueries({ queryKey: ['mobile-recents'] });
      qc.invalidateQueries({ queryKey: ['today-entries'] });

      navigation.navigate('Main');
    } catch (e: any) {
      console.log('Save error:', e?.response?.data, e?.message);
      Alert.alert('Save failed', e?.response?.data ? JSON.stringify(e.response.data) : e?.message);
      navigation.navigate('Main');
    } finally {
      setSaving(false);
    }
  }

  const categories = [
    { id: 0, name: 'Meeting', is_billable_default: true },
    { id: 1, name: 'Phone Call', is_billable_default: true },
    { id: 2, name: 'Site Visit', is_billable_default: true },
    { id: 3, name: 'Admin', is_billable_default: true },
  ];

  return (
    <ScrollView style={styles.scroll} contentContainerStyle={styles.container}>
      <Text style={styles.duration}>{formatDuration(duration_seconds)}</Text>
      <Text style={styles.durationLabel}>tracked</Text>

      {/* AI prefill badge */}
      {aiPrefilled && (
        <View style={styles.aiBanner}>
          <View style={styles.aiDot} />
          <Text style={styles.aiText}>AI filled fields from your tracking patterns</Text>
        </View>
      )}

      {/* Fields */}
      <View style={styles.card}>

        {/* Client */}
        <View style={styles.row}>
          <Text style={styles.label}>Client</Text>
          <TouchableOpacity onPress={() => setShowClientPicker(true)} style={styles.selectPill}>
            <Text style={styles.selectText}>
              {clientName ?? 'Select client'}
            </Text>
            <Text style={styles.chevron}>▼</Text>
          </TouchableOpacity>
        </View>

        {/* Category */}
        <View style={styles.row}>
          <Text style={styles.label}>Category</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.catScroll}>
            {categories.map((cat) => (
              <TouchableOpacity
                key={cat.id}
                style={[styles.catChip, cat.name === categoryName && styles.catChipSel]}
                onPress={() => { setCategoryName(cat.name); Haptics.selectionAsync(); }}
              >
                <Text style={[styles.catChipText, cat.name === categoryName && styles.catChipTextSel]}>
                  {cat.name}
                </Text>
              </TouchableOpacity>
            ))}
          </ScrollView>
        </View>

        {/* Note */}
        <View style={[styles.row, { alignItems: 'flex-start' }]}>
          <Text style={styles.label}>Note</Text>
          <TextInput
            style={styles.noteInput}
            placeholder="Add a note..."
            placeholderTextColor={Colors.textMuted}
            value={note}
            onChangeText={setNote}
            multiline
            maxLength={500}
          />
        </View>

        {/* Billable toggle */}
        <View style={[styles.row, { borderBottomWidth: 0 }]}>
          <Text style={styles.label}>Billable</Text>
          <Switch
            value={isBillable}
            onValueChange={setIsBillable}
            trackColor={{ false: Colors.border, true: Colors.tealLight }}
            thumbColor={isBillable ? Colors.teal : Colors.textMuted}
          />
        </View>
      </View>

      {/* Save button */}
      <TouchableOpacity
        style={[styles.saveBtn, !clientId && styles.saveBtnDisabled]}
        onPress={handleSave}
        disabled={saving || !clientId}
      >
        {saving
          ? <ActivityIndicator color="#fff" />
          : <Text style={styles.saveBtnText}>Save to Dashboard</Text>
        }
      </TouchableOpacity>

      <Text style={styles.syncNote}>Syncs to web dashboard instantly</Text>

      <ClientPicker
        visible={showClientPicker}
        clients={recents?.clients ?? []}
        onSelect={(c) => { setClientId(c.id); setClientName(c.name); setShowClientPicker(false); }}
        onClose={() => setShowClientPicker(false)}
      />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  scroll: { flex: 1, backgroundColor: Colors.bg },
  container: { padding: Spacing.lg, paddingTop: Spacing.xl, alignItems: 'center', paddingBottom: 40 },

  duration: { fontSize: 48, fontWeight: '300', color: Colors.navy },
  durationLabel: { fontSize: FontSizes.base, color: Colors.textMuted, marginBottom: Spacing.lg },

  aiBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: Colors.aiBg,
    borderWidth: 1,
    borderColor: Colors.aiBorder,
    borderRadius: Radius.md,
    padding: Spacing.md,
    marginBottom: Spacing.md,
    gap: Spacing.sm,
    width: '100%',
  },
  aiDot: { width: 7, height: 7, borderRadius: 4, backgroundColor: Colors.teal },
  aiText: { fontSize: FontSizes.sm, color: Colors.aiText, flex: 1 },

  card: {
    backgroundColor: Colors.bgCard,
    borderRadius: Radius.lg,
    borderWidth: 0.5,
    borderColor: Colors.border,
    width: '100%',
    marginBottom: Spacing.lg,
    overflow: 'hidden',
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: Spacing.lg,
    paddingVertical: Spacing.md,
    borderBottomWidth: 0.5,
    borderBottomColor: Colors.border,
    gap: Spacing.md,
  },
  label: { fontSize: FontSizes.sm, color: Colors.textMuted, width: 68 },
  selectPill: {
    flexDirection: 'row',
    alignItems: 'center',
    flex: 1,
    justifyContent: 'flex-end',
    gap: 6,
  },
  selectText: { fontSize: FontSizes.base, color: Colors.textPrimary, fontWeight: '500' },
  chevron: { fontSize: 9, color: Colors.textMuted },

  catScroll: { flex: 1 },
  catChip: {
    borderWidth: 0.5,
    borderColor: Colors.borderMid,
    borderRadius: Radius.pill,
    paddingHorizontal: 12,
    paddingVertical: 5,
    marginRight: 6,
    backgroundColor: Colors.bg,
  },
  catChipSel: { backgroundColor: Colors.aiBg, borderColor: Colors.aiBorder },
  catChipText: { fontSize: FontSizes.xs, color: Colors.textSecondary },
  catChipTextSel: { color: Colors.aiText, fontWeight: '500' },

  noteInput: {
    flex: 1,
    fontSize: FontSizes.base,
    color: Colors.textPrimary,
    textAlignVertical: 'top',
    minHeight: 36,
    paddingTop: 2,
  },

  saveBtn: {
    width: '100%',
    backgroundColor: Colors.teal,
    borderRadius: Radius.md,
    padding: Spacing.lg,
    alignItems: 'center',
  },
  saveBtnDisabled: { backgroundColor: Colors.textMuted },
  saveBtnText: { color: '#fff', fontSize: FontSizes.md, fontWeight: '500' },

  syncNote: { fontSize: FontSizes.xs, color: Colors.teal, marginTop: Spacing.sm },
});
