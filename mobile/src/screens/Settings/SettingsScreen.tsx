import React from 'react';
import { View, Text, TouchableOpacity, StyleSheet, Alert, ScrollView } from 'react-native';
import * as SecureStore from 'expo-secure-store';
import { Colors, FontSizes, Spacing, Radius } from '../../utils/theme';
import { TimeTrackerWordmark } from '../../../TimeTrackerLogo';

interface Props { onLogout: () => void; }

export default function SettingsScreen({ onLogout }: Props) {
  async function handleLogout() {
    Alert.alert('Sign out', 'Are you sure?', [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Sign out',
        style: 'destructive',
        onPress: async () => {
          await SecureStore.deleteItemAsync('auth_token');
          await SecureStore.deleteItemAsync('tt_active_timer');
          onLogout();
        },
      },
    ]);
  }

  return (
    <ScrollView style={styles.scroll} contentContainerStyle={styles.container}>

      {/* Brand header */}
      <View style={styles.brandHeader}>
        <TimeTrackerWordmark size="sm" theme="light" />
        <Text style={styles.brandSub}>by MavOps</Text>
      </View>

      <View style={styles.section}>
        <Text style={styles.sectionLabel}>Account</Text>
        <View style={styles.card}>
          <View style={styles.row}>
            <Text style={styles.label}>Dashboard</Text>
            <Text style={styles.val}>timetracker.mavops.ai</Text>
          </View>
          <View style={[styles.row, { borderBottomWidth: 0 }]}>
            <Text style={styles.label}>Version</Text>
            <Text style={styles.val}>1.0.0</Text>
          </View>
        </View>
      </View>

      <View style={styles.section}>
        <Text style={styles.sectionLabel}>AI Features</Text>
        <View style={styles.card}>
          <View style={styles.row}><Text style={styles.label}>Smart suggestions</Text><Text style={styles.val}>On</Text></View>
          <View style={styles.row}><Text style={styles.label}>Voice entry</Text><Text style={styles.val}>On</Text></View>
          <View style={styles.row}><Text style={styles.label}>Calendar scan</Text><Text style={styles.val}>On</Text></View>
          <View style={[styles.row, { borderBottomWidth: 0 }]}>
            <Text style={styles.label}>2h timer alert</Text>
            <Text style={styles.val}>On</Text>
          </View>
        </View>
      </View>

      <TouchableOpacity style={styles.logoutBtn} onPress={handleLogout}>
        <Text style={styles.logoutText}>Sign out</Text>
      </TouchableOpacity>

    </ScrollView>
  );
}

const styles = StyleSheet.create({
  scroll: { flex: 1, backgroundColor: Colors.bg },
  container: { padding: Spacing.lg, paddingBottom: 40 },

  brandHeader: {
    alignItems: 'center',
    paddingVertical: Spacing.xl,
    gap: 4,
    marginBottom: Spacing.lg,
  },
  brandSub: {
    fontSize: FontSizes.xs,
    color: Colors.textMuted,
    letterSpacing: 0.5,
  },

  section: { marginBottom: Spacing.xl },
  sectionLabel: {
    fontSize: FontSizes.xs,
    color: Colors.textMuted,
    textTransform: 'uppercase',
    letterSpacing: 0.8,
    marginBottom: Spacing.sm,
  },
  card: {
    backgroundColor: Colors.bgCard,
    borderRadius: Radius.lg,
    borderWidth: 0.5,
    borderColor: Colors.border,
  },
  row: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: Spacing.lg,
    borderBottomWidth: 0.5,
    borderBottomColor: Colors.border,
  },
  label: { fontSize: FontSizes.base, color: Colors.textPrimary },
  val: { fontSize: FontSizes.base, color: Colors.textMuted },
  logoutBtn: {
    borderWidth: 1,
    borderColor: Colors.danger,
    borderRadius: Radius.md,
    padding: Spacing.lg,
    alignItems: 'center',
  },
  logoutText: { color: Colors.danger, fontSize: FontSizes.md, fontWeight: '500' },
});