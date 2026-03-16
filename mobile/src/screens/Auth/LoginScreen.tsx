import React, { useState } from 'react';
import {
  View, Text, TextInput, TouchableOpacity,
  StyleSheet, ActivityIndicator, KeyboardAvoidingView,
  Platform, Alert,
} from 'react-native';
import { login } from '../../api/client';
import { Colors, FontSizes, Spacing, Radius } from '../../utils/theme';
import { TimeTrackerIcon, TimeTrackerWordmark } from '../../../TimeTrackerLogo';

interface Props { onLogin: () => void; }

export default function LoginScreen({ onLogin }: Props) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);

  async function handleLogin() {
    if (!email || !password) return;
    try {
      setLoading(true);
      await login(email.trim(), password);
      onLogin();
    } catch {
      Alert.alert('Login failed', 'Check your email and password.');
    } finally {
      setLoading(false);
    }
  }

  return (
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      {/* Header */}
      <View style={styles.header}>
        <TimeTrackerIcon size={72} variant="default" />
        <View style={styles.wordmarkRow}>
          <TimeTrackerWordmark size="lg" theme="dark" />
        </View>
        <Text style={styles.byLine}>by MavOps</Text>
      </View>

      {/* Form */}
      <View style={styles.form}>
        <TextInput
          style={styles.input}
          placeholder="Email"
          placeholderTextColor={Colors.textMuted}
          value={email}
          onChangeText={setEmail}
          keyboardType="email-address"
          autoCapitalize="none"
          autoComplete="email"
        />
        <TextInput
          style={styles.input}
          placeholder="Password"
          placeholderTextColor={Colors.textMuted}
          value={password}
          onChangeText={setPassword}
          secureTextEntry
          autoComplete="password"
        />
        <TouchableOpacity
          style={[styles.btn, (!email || !password) && styles.btnDisabled]}
          onPress={handleLogin}
          disabled={loading || !email || !password}
        >
          {loading
            ? <ActivityIndicator color="#fff" />
            : <Text style={styles.btnText}>Sign in</Text>
          }
        </TouchableOpacity>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: Colors.navy,
    alignItems: 'center',
    justifyContent: 'center',
    padding: Spacing.xxl,
  },
  header: { alignItems: 'center', marginBottom: 48, gap: 16 },
  wordmarkRow: { marginTop: 4 },
  byLine: { fontSize: FontSizes.sm, color: 'rgba(255,255,255,0.35)', marginTop: -8 },

  form: { width: '100%', gap: Spacing.md },
  input: {
    backgroundColor: 'rgba(255,255,255,0.08)',
    borderRadius: Radius.md,
    padding: Spacing.lg,
    fontSize: FontSizes.md,
    color: '#fff',
    borderWidth: 0.5,
    borderColor: 'rgba(255,255,255,0.15)',
  },
  btn: {
    backgroundColor: Colors.teal,
    borderRadius: Radius.md,
    padding: Spacing.lg,
    alignItems: 'center',
    marginTop: Spacing.sm,
  },
  btnDisabled: { opacity: 0.5 },
  btnText: { color: '#fff', fontSize: FontSizes.md, fontWeight: '500' },
});