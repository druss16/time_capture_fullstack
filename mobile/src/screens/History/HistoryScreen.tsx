import React from 'react';
import { View, Text, StyleSheet, FlatList, RefreshControl } from 'react-native';
import { useQuery } from '@tanstack/react-query';
import { getTodayEntries } from '../../api/client';
import { formatDuration } from '../../store/timerStore';
import { Colors, FontSizes, Spacing, Radius } from '../../utils/theme';

export default function HistoryScreen() {
  const { data: entries, isLoading, refetch } = useQuery({
    queryKey: ['today-entries'],
    queryFn: getTodayEntries,
    staleTime: 30_000,
  });

  const totalSeconds = entries?.reduce((sum, e) => sum + (e.minutes || 0) * 60, 0) ?? 0;
  const billableSeconds = entries?.filter((e) => e.approved).reduce((sum, e) => sum + (e.minutes || 0) * 60, 0) ?? 0;

  return (
    <View style={styles.container}>
      {/* Summary row */}
      <View style={styles.summary}>
        <View style={styles.summaryItem}>
          <Text style={styles.summaryVal}>{formatDuration(billableSeconds)}</Text>
          <Text style={styles.summaryLabel}>Billable</Text>
        </View>
        <View style={styles.summaryDivider} />
        <View style={styles.summaryItem}>
          <Text style={styles.summaryVal}>{formatDuration(totalSeconds - billableSeconds)}</Text>
          <Text style={styles.summaryLabel}>Non-bill</Text>
        </View>
        <View style={styles.summaryDivider} />
        <View style={styles.summaryItem}>
          <Text style={[styles.summaryVal, { color: Colors.textPrimary }]}>{formatDuration(totalSeconds)}</Text>
          <Text style={styles.summaryLabel}>Total</Text>
        </View>
      </View>

      <FlatList
        data={entries ?? []}
        keyExtractor={(e) => String(e.id)}
        contentContainerStyle={styles.list}
        refreshControl={<RefreshControl refreshing={isLoading} onRefresh={refetch} tintColor={Colors.teal} />}
        ItemSeparatorComponent={() => <View style={styles.sep} />}
        ListEmptyComponent={
          !isLoading ? (
            <View style={styles.empty}>
              <Text style={styles.emptyText}>No entries today</Text>
              <Text style={styles.emptyHint}>Tap the timer button to start tracking</Text>
            </View>
          ) : null
        }
        renderItem={({ item }) => (
          <View style={styles.entryCard}>
            <View style={[styles.entryDot, { backgroundColor: item.is_billable ? Colors.teal : Colors.textMuted }]} />
            <View style={styles.entryInfo}>
              <Text style={styles.entryClient}>{item.client_name}</Text>
              <Text style={styles.entryCat}>{item.category_name}{item.note ? ` · ${item.note}` : ''}</Text>
            </View>
            <View style={styles.entryRight}>
              <Text style={styles.entryDur}>{formatDuration(item.duration_seconds)}</Text>
              {item.is_billable && <Text style={styles.billableBadge}>$</Text>}
            </View>
          </View>
        )}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: Colors.bg },

  summary: {
    flexDirection: 'row',
    backgroundColor: Colors.navy,
    paddingVertical: Spacing.lg,
    paddingHorizontal: Spacing.xl,
  },
  summaryItem: { flex: 1, alignItems: 'center' },
  summaryVal: { fontSize: FontSizes.lg, fontWeight: '500', color: Colors.teal },
  summaryLabel: { fontSize: FontSizes.xs, color: 'rgba(255,255,255,0.5)', marginTop: 2 },
  summaryDivider: { width: 0.5, backgroundColor: 'rgba(255,255,255,0.15)', marginHorizontal: Spacing.md },

  list: { padding: Spacing.md, paddingBottom: 40 },
  sep: { height: Spacing.sm },

  entryCard: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: Colors.bgCard,
    borderRadius: Radius.md,
    padding: Spacing.md,
    borderWidth: 0.5,
    borderColor: Colors.border,
    gap: Spacing.sm,
  },
  entryDot: { width: 10, height: 10, borderRadius: 5, flexShrink: 0 },
  entryInfo: { flex: 1 },
  entryClient: { fontSize: FontSizes.base, fontWeight: '500', color: Colors.textPrimary },
  entryCat: { fontSize: FontSizes.xs, color: Colors.textMuted, marginTop: 2 },
  entryRight: { alignItems: 'flex-end', gap: 3 },
  entryDur: { fontSize: FontSizes.base, fontWeight: '500', color: Colors.textPrimary },
  billableBadge: {
    fontSize: FontSizes.xs,
    color: Colors.tealDark,
    backgroundColor: Colors.aiBg,
    borderRadius: Radius.pill,
    paddingHorizontal: 6,
    paddingVertical: 1,
  },

  empty: { alignItems: 'center', paddingTop: 60 },
  emptyText: { fontSize: FontSizes.md, color: Colors.textSecondary, fontWeight: '500' },
  emptyHint: { fontSize: FontSizes.sm, color: Colors.textMuted, marginTop: Spacing.sm },
});
