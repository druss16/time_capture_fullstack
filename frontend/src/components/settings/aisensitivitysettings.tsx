// components/settings/AISensitivitySettings.jsx
// Drop this inside your Settings page under an "AI & Automation" section.
// Only rendered when the current user's role is "admin" or "owner".

import React, { useState, useEffect } from "react";
import axios from "axios";

// ── Sensitivity preset labels & descriptions ──────────────────────────────
const PRESETS = [
  {
    value: 10,
    label: "Conservative",
    color: "#6366f1",
    description:
      "Only switches when the full client name appears in a window title. " +
      "Zero false positives — best for firms with very generic client names.",
  },
  {
    value: 35,
    label: "Cautious",
    color: "#3b82f6",
    description:
      "Requires a strong name match. Partial words are ignored. " +
      "Good default for small firms that prefer manual control.",
  },
  {
    value: 50,
    label: "Balanced",
    color: "#10b981",
    description:
      "Default setting. Full-name matches auto-switch; partial words " +
      "show a suggestion toast but don't switch automatically.",
  },
  {
    value: 70,
    label: "Aggressive",
    color: "#f59e0b",
    description:
      'Partial words trigger auto-switch. "Dauphin" in any window title ' +
      'will switch to "Dauphin & Fantacone". Best for firms with unique client names.',
  },
  {
    value: 90,
    label: "Very Aggressive",
    color: "#ef4444",
    description:
      "Very short name fragments trigger switches. Maximises automatic detection " +
      "but may produce occasional false positives for common words.",
  },
];

function sensitivityLabel(value) {
  if (value <= 20) return "Conservative";
  if (value <= 40) return "Cautious";
  if (value <= 60) return "Balanced";
  if (value <= 80) return "Aggressive";
  return "Very Aggressive";
}

function sensitivityColor(value) {
  const preset = PRESETS.reduce((closest, p) =>
    Math.abs(p.value - value) < Math.abs(closest.value - value) ? p : closest
  );
  return preset.color;
}

function sensitivityDescription(value) {
  const preset = PRESETS.reduce((closest, p) =>
    Math.abs(p.value - value) < Math.abs(closest.value - value) ? p : closest
  );
  return preset.description;
}

// ── Threshold preview (mirrors Python _sensitivity_to_thresholds) ─────────
function computeThresholds(s) {
  const pct = Math.max(0, Math.min(100, s)) / 100;
  return {
    local:   Math.round((0.90 - pct * 0.40) * 100),
    ai:      Math.round((0.85 - pct * 0.40) * 100),
    suggest: Math.round((0.70 - pct * 0.35) * 100),
    partial: pct >= 0.40,
    minWord: pct < 0.40 ? null : pct < 0.70 ? 6 : pct < 0.90 ? 4 : 3,
  };
}

// ── Component ─────────────────────────────────────────────────────────────
export default function AISensitivitySettings({ userRole }) {
  const [sensitivity, setSensitivity] = useState(50);
  const [saved, setSaved] = useState(50);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [successMsg, setSuccessMsg] = useState(null);

  const isAdmin = userRole === "admin" || userRole === "owner";

  useEffect(() => {
    axios
      .get("/api/organizations/settings/ai/")
      .then((res) => {
        setSensitivity(res.data.ai_sensitivity ?? 50);
        setSaved(res.data.ai_sensitivity ?? 50);
      })
      .catch(() => setError("Failed to load AI settings."))
      .finally(() => setLoading(false));
  }, []);

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    setSuccessMsg(null);
    try {
      await axios.patch("/api/organizations/settings/ai/", {
        ai_sensitivity: sensitivity,
      });
      setSaved(sensitivity);
      setSuccessMsg("Settings saved. Agents will update at next sync.");
      setTimeout(() => setSuccessMsg(null), 4000);
    } catch {
      setError("Failed to save. Please try again.");
    } finally {
      setSaving(false);
    }
  };

  const thresholds = computeThresholds(sensitivity);
  const color = sensitivityColor(sensitivity);
  const label = sensitivityLabel(sensitivity);
  const hasChanges = sensitivity !== saved;

  if (!isAdmin) return null;

  return (
    <div className="bg-white border border-gray-200 rounded-xl p-6 space-y-6">
      {/* Header */}
      <div>
        <h3 className="text-base font-semibold text-gray-900">
          Client Detection Sensitivity
        </h3>
        <p className="text-sm text-gray-500 mt-1">
          Controls how aggressively the desktop agent matches open windows to
          clients. Higher sensitivity catches more activity automatically but
          may occasionally switch to the wrong client.
        </p>
      </div>

      {loading ? (
        <div className="h-10 bg-gray-100 animate-pulse rounded-lg" />
      ) : (
        <>
          {/* Slider */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-gray-700">Sensitivity</span>
              <span
                className="text-sm font-semibold px-3 py-1 rounded-full text-white"
                style={{ backgroundColor: color }}
              >
                {sensitivity} — {label}
              </span>
            </div>

            <input
              type="range"
              min={0}
              max={100}
              step={1}
              value={sensitivity}
              onChange={(e) => setSensitivity(Number(e.target.value))}
              className="w-full h-2 rounded-full appearance-none cursor-pointer"
              style={{
                background: `linear-gradient(to right, ${color} ${sensitivity}%, #e5e7eb ${sensitivity}%)`,
                accentColor: color,
              }}
            />

            {/* Tick labels */}
            <div className="flex justify-between text-xs text-gray-400 px-0.5">
              <span>Conservative</span>
              <span>Cautious</span>
              <span>Balanced</span>
              <span>Aggressive</span>
              <span>Max</span>
            </div>
          </div>

          {/* Description */}
          <div
            className="text-sm text-gray-600 bg-gray-50 border border-gray-200 rounded-lg p-4"
            style={{ borderLeftColor: color, borderLeftWidth: 3 }}
          >
            {sensitivityDescription(sensitivity)}
          </div>

          {/* Technical preview */}
          <details className="group">
            <summary className="text-xs text-gray-400 cursor-pointer hover:text-gray-600 select-none">
              Show confidence thresholds ▸
            </summary>
            <div className="mt-3 grid grid-cols-2 gap-3 text-xs">
              <ThresholdBadge
                label="Full-name auto-switch"
                value={`≥ ${thresholds.local}%`}
                color={color}
              />
              <ThresholdBadge
                label="AI auto-switch"
                value={`≥ ${thresholds.ai}%`}
                color={color}
              />
              <ThresholdBadge
                label="Suggestion toast"
                value={`≥ ${thresholds.suggest}%`}
                color={color}
              />
              <ThresholdBadge
                label="Partial-word matching"
                value={
                  thresholds.partial
                    ? `On (min ${thresholds.minWord} chars)`
                    : "Off"
                }
                color={thresholds.partial ? color : "#9ca3af"}
              />
            </div>
            <p className="mt-3 text-xs text-gray-400 italic">
              Example: at this sensitivity,{" "}
              {thresholds.partial
                ? `a window titled "Eric Dauphin update" would ${
                    thresholds.local <= 65
                      ? "auto-switch"
                      : "suggest switching"
                  } to "Dauphin & Fantacone".`
                : `the window title would need to contain the full client name 
                   to trigger a switch.`}
            </p>
          </details>

          {/* Preset quick-picks */}
          <div>
            <p className="text-xs font-medium text-gray-500 mb-2 uppercase tracking-wide">
              Quick presets
            </p>
            <div className="flex flex-wrap gap-2">
              {PRESETS.map((p) => (
                <button
                  key={p.value}
                  onClick={() => setSensitivity(p.value)}
                  className="px-3 py-1.5 rounded-full border text-xs font-medium transition-all"
                  style={
                    sensitivity === p.value
                      ? { backgroundColor: p.color, color: "white", borderColor: p.color }
                      : { borderColor: "#d1d5db", color: "#374151" }
                  }
                >
                  {p.label}
                </button>
              ))}
            </div>
          </div>

          {/* Save button + feedback */}
          <div className="flex items-center gap-4 pt-2 border-t border-gray-100">
            <button
              onClick={handleSave}
              disabled={saving || !hasChanges}
              className="px-5 py-2 rounded-lg text-sm font-medium text-white transition-all disabled:opacity-50 disabled:cursor-not-allowed"
              style={{ backgroundColor: hasChanges ? color : "#9ca3af" }}
            >
              {saving ? "Saving…" : "Save Changes"}
            </button>

            {successMsg && (
              <span className="text-sm text-green-600 font-medium">
                ✓ {successMsg}
              </span>
            )}
            {error && (
              <span className="text-sm text-red-500">{error}</span>
            )}
            {hasChanges && !saving && (
              <span className="text-xs text-gray-400 ml-auto">
                Unsaved changes
              </span>
            )}
          </div>
        </>
      )}
    </div>
  );
}

// ── Small helper badge ─────────────────────────────────────────────────────
function ThresholdBadge({ label, value, color }) {
  return (
    <div className="bg-white border border-gray-200 rounded-lg px-3 py-2">
      <div className="text-gray-500">{label}</div>
      <div className="font-semibold mt-0.5" style={{ color }}>
        {value}
      </div>
    </div>
  );
}