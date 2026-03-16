import React from 'react';
import {
  View, Text, StyleSheet, FlatList,
  RefreshControl, TouchableOpacity, StatusBar,
} from 'react-native';
import { useQuery } from '@tanstack/react-query';
import { getMobileRecents } from '../../api/client';
import { Colors, FontSizes, Spacing, Radius } from '../../utils/theme';

function fmtDuration(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (h > 0 && m > 0) return `${h}h ${m}m`;
  if (h > 0) return `${h}h`;
  if (m > 0) return `${m}m`;
  return `<1m`;
}

function fmtTime(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  } catch { return ''; }
}

const CAT_COLORS: Record<string, string> = {
  'Meeting':    '#1D9E75',
  'Phone Call': '#185FA5',
  'Site Visit': '#D85A30',
  'Admin':      '#888780',
};

function catColor(cat: string) {
  return CAT_COLORS[cat] ?? '#1D9E75';
}

export default function HistoryScreen() {
  const { data: recents, isLoading, refetch } = useQuery({
    queryKey: ['mobile-recents'],
    queryFn: getMobileRecents,
    staleTime: 30_000,
  });

  const entries = recents?.entries ?? [];

  // duration_seconds comes from API as minutes * 60
  const totalSeconds = entries.reduce((sum, e) => sum + (e.duration_seconds || 0), 0);
  const billableSeconds = entries.filter((e) => e.is_billable).reduce((sum, e) => sum + (e.duration_seconds || 0), 0);
  const nonBillableSeconds = totalSeconds - billableSeconds;

  return (
    <View style={styles.container}>
      <StatusBar barStyle="light-content" />

      {/* Summary bar */}
      <View style={styles.summaryBar}>
        <View style={styles.summaryItem}>
          <Text style={styles.summaryVal}>{fmtDuration(billableSeconds)}</Text>
          <Text style={styles.summaryLabel}>Billable</Text>
        </View>
        <View style={styles.summaryDivider} />
        <View style={styles.summaryItem}>
          <Text style={[styles.summaryVal, { color: 'rgba(255,255,255,0.5)' }]}>{fmtDuration(nonBillableSeconds)}</Text>
          <Text style={styles.summaryLabel}>Non-bill</Text>
        </View>
        <View style={styles.summaryDivider} />
        <View style={styles.summaryItem}>
          <Text style={[styles.summaryVal, { color: '#fff' }]}>{fmtDuration(totalSeconds)}</Text>
          <Text style={styles.summaryLabel}>Total</Text>
        </View>
      </View>

      <FlatList
        data={entries}
        keyExtractor={(e) => String(e.id)}
        contentContainerStyle={styles.list}
        refreshControl={
          <RefreshControl refreshing={isLoading} onRefresh={refetch} tintColor={Colors.teal} />
        }
        ListEmptyComponent={
          !isLoading ? (
            <View style={styles.empty}>
              <Text style={styles.emptyIcon}>⏱</Text>
              <Text style={styles.emptyTitle}>No entries today</Text>
              <Text style={styles.emptyHint}>Tap the timer to start tracking</Text>
            </View>
          ) : null
        }
        renderItem={({ item }) => {
          const dur = item.duration_seconds || 0;
          const color = catColor(item.category_name);
          return (
            <View style={styles.card}>
              <View style={[styles.cardAccent, { backgroundColor: color }]} />
              <View style={styles.cardBody}>
                <View style={styles.cardTop}>
                  <Text style={styles.clientName} numberOfLines={1}>{item.client_name || '—'}</Text>
                  <Text style={styles.duration}>{fmtDuration(dur)}</Text>
                </View>
                <View style={styles.cardBottom}>
                  <View style={[styles.catPill, { backgroundColor: color + '18' }]}>
                    <Text style={[styles.catText, { color }]}>{item.category_name || 'Uncategorized'}</Text>
                  </View>
                  <View style={styles.cardMeta}>
                    {item.note ? <Text style={styles.note} numberOfLines={1}>{item.note}</Text> : null}
                    <Text style={styles.time}>{fmtTime(item.start_time)}</Text>
                  </View>
                </View>
              </View>
              {item.is_billable && (
                <View style={styles.billableDot}>
                  <Text style={styles.billableText}>$</Text>
                </View>
              )}
            </View>
          );
        }}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#f4f6f8' },

  summaryBar: {
    flexDirection: 'row',
    backgroundColor: Colors.navy,
    paddingVertical: 16,
    paddingHorizontal: 24,
  },
  summaryItem: { flex: 1, alignItems: 'center' },
  summaryVal: { fontSize: 18, fontWeight: '500', color: Colors.teal },
  summaryLabel: { fontSize: 10, color: 'rgba(255,255,255,0.4)', marginTop: 2, textTransform: 'uppercase', letterSpacing: 0.5 },
  summaryDivider: { width: 0.5, backgroundColor: 'rgba(255,255,255,0.1)', marginHorizontal: 8 },

  list: { padding: 16, paddingBottom: 40, gap: 10 },

  card: {
    flexDirection: 'row',
    backgroundColor: '#fff',
    borderRadius: 14,
    overflow: 'hidden',
    borderWidth: 0.5,
    borderColor: '#e8ecef',
  },
  cardAccent: { width: 4 },
  cardBody: { flex: 1, padding: 14 },
  cardTop: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 },
  clientName: { fontSize: 15, fontWeight: '500', color: Colors.navy, flex: 1, marginRight: 8 },
  duration: { fontSize: 15, fontWeight: '600', color: Colors.navy },
  cardBottom: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  catPill: { borderRadius: 99, paddingHorizontal: 10, paddingVertical: 3 },
  catText: { fontSize: 11, fontWeight: '500' },
  cardMeta: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  note: { fontSize: 11, color: '#9aa5b1', maxWidth: 120 },
  time: { fontSize: 11, color: '#9aa5b1' },
  billableDot: {
    width: 28,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#e1f5ee',
  },
  billableText: { fontSize: 12, fontWeight: '600', color: Colors.teal },

  empty: { alignItems: 'center', paddingTop: 80 },
  emptyIcon: { fontSize: 40, marginBottom: 12 },
  emptyTitle: { fontSize: 17, fontWeight: '500', color: Colors.navy },
  emptyHint: { fontSize: 13, color: '#9aa5b1', marginTop: 6 },
});