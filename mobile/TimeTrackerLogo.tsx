import React from "react";
import { View, Text, StyleSheet } from "react-native";
import Svg, {
  Rect,
  Circle,
  Polyline,
  Defs,
  LinearGradient,
  Stop,
} from "react-native-svg";

// ─── Types ───────────────────────────────────────────────────────────────────

type IconVariant = "default" | "mono-white" | "mono-teal" | "teal-bg";
type WordmarkSize = "sm" | "md" | "lg";
type WordmarkTheme = "dark" | "light";

// ─── Icon ────────────────────────────────────────────────────────────────────

interface TimeTrackerIconProps {
  size?: number;
  variant?: IconVariant;
}

const variantStyles: Record<IconVariant, {
  bgColor?: string;
  useGradient?: boolean;
  trackStroke: string;
  arcStroke: string;
  badgeFill: string;
  checkStroke: string;
}> = {
  default: {
    useGradient: true,
    trackStroke: "#1e3a52",
    arcStroke: "#2bb5a0",
    badgeFill: "#2bb5a0",
    checkStroke: "#ffffff",
  },
  "mono-white": {
    trackStroke: "rgba(255,255,255,0.2)",
    arcStroke: "#ffffff",
    badgeFill: "#ffffff",
    checkStroke: "#1a2b3c",
  },
  "mono-teal": {
    trackStroke: "rgba(43,181,160,0.2)",
    arcStroke: "#2bb5a0",
    badgeFill: "#2bb5a0",
    checkStroke: "#ffffff",
  },
  "teal-bg": {
    bgColor: "#2bb5a0",
    trackStroke: "rgba(255,255,255,0.2)",
    arcStroke: "#ffffff",
    badgeFill: "#ffffff",
    checkStroke: "#2bb5a0",
  },
};

// Arc math (based on 64×64 viewBox, r=20)
const RADIUS = 20;
const CIRC = 2 * Math.PI * RADIUS;         // 125.66
const ARC_LEN = CIRC * 0.75;              // 94.2  (~270deg)
const ARC_GAP = CIRC - ARC_LEN;           // 31.46
const ARC_OFFSET = CIRC * 0.25;           // 31.4

export const TimeTrackerIcon: React.FC<TimeTrackerIconProps> = ({
  size = 32,
  variant = "default",
}) => {
  const s = variantStyles[variant];
  const gradId = `tt-grad-${variant}`;

  return (
    <Svg width={size} height={size} viewBox="0 0 64 64" fill="none">
      <Defs>
        <LinearGradient id={gradId} x1="0" y1="0" x2="64" y2="64" gradientUnits="userSpaceOnUse">
          <Stop offset="0%" stopColor="#1a2b3c" />
          <Stop offset="100%" stopColor="#152638" />
        </LinearGradient>
      </Defs>

      {/* Background */}
      {s.useGradient && (
        <Rect width="64" height="64" rx="14" fill={`url(#${gradId})`} />
      )}
      {s.bgColor && (
        <Rect width="64" height="64" rx="14" fill={s.bgColor} />
      )}

      {/* Arc track */}
      <Circle
        cx="32" cy="32" r={RADIUS}
        stroke={s.trackStroke}
        strokeWidth="4.5"
        fill="none"
      />

      {/* Progress arc */}
      <Circle
        cx="32" cy="32" r={RADIUS}
        stroke={s.arcStroke}
        strokeWidth="4.5"
        fill="none"
        strokeLinecap="round"
        strokeDasharray={`${ARC_LEN} ${ARC_GAP}`}
        strokeDashoffset={ARC_OFFSET}
        rotation="-90"
        originX="32"
        originY="32"
      />

      {/* Badge fill */}
      <Circle cx="32" cy="32" r="11" fill={s.badgeFill} />

      {/* Checkmark */}
      <Polyline
        points="25.5,32 30,36.5 38.5,26.5"
        stroke={s.checkStroke}
        strokeWidth="2.8"
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />
    </Svg>
  );
};

// ─── Wordmark ─────────────────────────────────────────────────────────────────

interface TimeTrackerWordmarkProps {
  size?: WordmarkSize;
  theme?: WordmarkTheme;
}

const wordmarkConfig = {
  sm: { iconSize: 24, fontSize: 16, gap: 8 },
  md: { iconSize: 32, fontSize: 20, gap: 10 },
  lg: { iconSize: 40, fontSize: 26, gap: 12 },
};

export const TimeTrackerWordmark: React.FC<TimeTrackerWordmarkProps> = ({
  size = "md",
  theme = "dark",
}) => {
  const { iconSize, fontSize, gap } = wordmarkConfig[size];
  const textColor = theme === "dark" ? "#e8f0f5" : "#0f1e2d";

  return (
    <View style={[styles.row, { gap }]}>
      <TimeTrackerIcon size={iconSize} variant="default" />
      <Text style={[styles.wordmark, { fontSize, color: textColor }]}>
        Time<Text style={styles.accent}>Tracker</Text>
      </Text>
    </View>
  );
};

// ─── Styles ──────────────────────────────────────────────────────────────────

const styles = StyleSheet.create({
  row: {
    flexDirection: "row",
    alignItems: "center",
  },
  wordmark: {
    fontFamily: "Syne_700Bold", // or swap for any bold font in your project
    fontWeight: "800",
    letterSpacing: -0.4,
    lineHeight: undefined,
  },
  accent: {
    color: "#2bb5a0",
  },
});

export default TimeTrackerIcon;