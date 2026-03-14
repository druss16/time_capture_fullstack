import { useState, useRef } from 'react';
import { Audio } from 'expo-av';
import * as FileSystem from 'expo-file-system';
import * as Haptics from 'expo-haptics';
import { parseVoice } from '../api/client';
import type { VoiceParseResult } from '../types';

type VoiceState = 'idle' | 'recording' | 'processing' | 'done' | 'error';

export function useVoiceEntry() {
  const [state, setState] = useState<VoiceState>('idle');
  const [result, setResult] = useState<VoiceParseResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const recording = useRef<Audio.Recording | null>(null);

  async function startRecording() {
    try {
      setError(null);
      const { status } = await Audio.requestPermissionsAsync();
      if (status !== 'granted') {
        setError('Microphone permission denied');
        return;
      }

      await Audio.setAudioModeAsync({
        allowsRecordingIOS: true,
        playsInSilentModeIOS: true,
      });

      const { recording: rec } = await Audio.Recording.createAsync(
        Audio.RecordingOptionsPresets.HIGH_QUALITY,
      );
      recording.current = rec;
      setState('recording');
      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    } catch {
      setError('Could not start recording');
      setState('error');
    }
  }

  async function stopRecording(): Promise<VoiceParseResult | null> {
    if (!recording.current) return null;
    try {
      setState('processing');
      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);

      await recording.current.stopAndUnloadAsync();
      const uri = recording.current.getURI();
      recording.current = null;

      if (!uri) throw new Error('No recording URI');

      // Read as base64
      const base64 = await FileSystem.readAsStringAsync(uri, {
        encoding: FileSystem.EncodingType.Base64,
      });

      const parsed = await parseVoice({
        audio_base64: base64,
        mime_type: 'audio/m4a',
      });

      setResult(parsed);
      setState('done');
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
      return parsed;
    } catch {
      setError('Could not parse voice entry');
      setState('error');
      return null;
    }
  }

  function reset() {
    setState('idle');
    setResult(null);
    setError(null);
  }

  return { state, result, error, startRecording, stopRecording, reset };
}
