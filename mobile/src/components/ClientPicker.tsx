import React, { useState } from 'react';
import {
  View, Text, TouchableOpacity, StyleSheet,
  TextInput, FlatList, Modal, SafeAreaView,
} from 'react-native';
import { Colors, FontSizes, Spacing, Radius } from '../utils/theme';
import type { Client } from '../types';

interface Props {
  visible: boolean;
  clients: Client[];
  onSelect: (client: Client) => void;
  onClose: () => void;
}

export default function ClientPicker({ visible, clients, onSelect, onClose }: Props) {
  const [search, setSearch] = useState('');

  const filtered = clients.filter((c) =>
    c.name.toLowerCase().includes(search.toLowerCase()),
  );

  return (
    <Modal visible={visible} animationType="slide" presentationStyle="pageSheet" onRequestClose={onClose}>
      <SafeAreaView style={styles.container}>
        <View style={styles.header}>
          <Text style={styles.title}>Select client</Text>
          <TouchableOpacity onPress={onClose} style={styles.closeBtn}>
            <Text style={styles.closeText}>Done</Text>
          </TouchableOpacity>
        </View>

        <View style={styles.searchRow}>
          <TextInput
            style={styles.searchInput}
            placeholder="Search clients..."
            placeholderTextColor={Colors.textMuted}
            value={search}
            onChangeText={setSearch}
            autoFocus
            clearButtonMode="always"
          />
        </View>

        <FlatList
          data={filtered}
          keyExtractor={(c) => String(c.id)}
          ItemSeparatorComponent={() => <View style={styles.sep} />}
          renderItem={({ item }) => (
            <TouchableOpacity style={styles.clientRow} onPress={() => { setSearch(''); onSelect(item); }}>
              <View style={[styles.dot, { backgroundColor: Colors.teal }]} />
              <Text style={styles.clientName}>{item.name}</Text>
            </TouchableOpacity>
          )}
          ListEmptyComponent={
            <View style={styles.empty}>
              <Text style={styles.emptyText}>No clients found</Text>
            </View>
          }
        />
      </SafeAreaView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: Colors.bg },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: Spacing.lg,
    borderBottomWidth: 0.5,
    borderBottomColor: Colors.border,
    backgroundColor: Colors.navy,
  },
  title: { fontSize: FontSizes.md, fontWeight: '500', color: '#fff' },
  closeBtn: { paddingHorizontal: Spacing.md, paddingVertical: Spacing.sm },
  closeText: { fontSize: FontSizes.base, color: Colors.teal, fontWeight: '500' },

  searchRow: { padding: Spacing.md, backgroundColor: Colors.bgCard, borderBottomWidth: 0.5, borderBottomColor: Colors.border },
  searchInput: {
    backgroundColor: Colors.bg,
    borderRadius: Radius.md,
    paddingHorizontal: Spacing.md,
    paddingVertical: Spacing.sm,
    fontSize: FontSizes.base,
    color: Colors.textPrimary,
    borderWidth: 0.5,
    borderColor: Colors.border,
  },

  clientRow: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: Spacing.lg,
    backgroundColor: Colors.bgCard,
    gap: Spacing.md,
  },
  dot: { width: 10, height: 10, borderRadius: 5 },
  clientName: { fontSize: FontSizes.md, color: Colors.textPrimary },
  sep: { height: 0.5, backgroundColor: Colors.border },

  empty: { padding: Spacing.xxl, alignItems: 'center' },
  emptyText: { color: Colors.textMuted, fontSize: FontSizes.base },
});
