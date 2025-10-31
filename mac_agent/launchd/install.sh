#!/usr/bin/env bash
set -euo pipefail

# ------------------------------------------------------------
# Setup paths
# ------------------------------------------------------------
ROOT="$(cd "$(dirname "$0")"/.. && pwd)"
PLIST_TPL="$ROOT/launchd/com.mavops.activityagent.plist.template"
PLIST_DST="$HOME/Library/LaunchAgents/com.mavops.activityagent.plist"

BIN_DST="$HOME/.timetracker/bin"
CFG_DIR="$HOME/.timetracker"
LOG_DIR="$HOME/Library/Logs/ActivityAgent"
AGENT_SRC="$ROOT/dist/TimeTrackerAgent"

# ------------------------------------------------------------
# Ensure prerequisites
# ------------------------------------------------------------
echo "🔧 Setting up MavOps TimeTracker agent..."

if [[ ! -f "$AGENT_SRC" ]]; then
  echo "❌ Missing agent binary at $AGENT_SRC"
  echo "Please ensure TimeTrackerAgent is included in your distribution."
  exit 2
fi

# Create folders if missing
mkdir -p "$BIN_DST" "$CFG_DIR" "$LOG_DIR"

# ------------------------------------------------------------
# Copy & verify the agent binary
# ------------------------------------------------------------
cp -f "$AGENT_SRC" "$BIN_DST/TimeTrackerAgent"
chmod +x "$BIN_DST/TimeTrackerAgent"

# macOS Gatekeeper signature verification
if spctl --assess --type execute -vv "$BIN_DST/TimeTrackerAgent"; then
  echo "✅ Agent signature verified"
else
  echo "⚠️ Warning: Agent signature could not be verified (may still run if notarized DMG)."
fi

# ------------------------------------------------------------
# Write config file (if missing)
# ------------------------------------------------------------
CFG_JSON="$CFG_DIR/config.json"
if [[ ! -f "$CFG_JSON" ]]; then
  cat > "$CFG_JSON" <<JSON
{
  "api_url": "http://localhost:7123/api/raw-events/",
  "api_key": "",
  "poll_seconds": 5,
  "min_dwell_seconds": 15,
  "verbose": true,
  "context_port": 7321
}
JSON
  echo "📝 Created default config at $CFG_JSON"
fi

# Extract config values (jq optional)
API_KEY=$(jq -r '.api_key // ""' "$CFG_JSON" 2>/dev/null || echo "")
POST_URL=$(jq -r '.api_url // ""' "$CFG_JSON" 2>/dev/null || echo "http://localhost:7123/api/raw-events/")
CONTEXT_PORT=$(jq -r '.context_port // 7321' "$CFG_JSON" 2>/dev/null || echo "7321")

# ------------------------------------------------------------
# Render the LaunchAgent plist
# ------------------------------------------------------------
echo "⚙️  Rendering LaunchAgent plist → $PLIST_DST"
sed -e "s|{{BIN}}|$BIN_DST/TimeTrackerAgent|g" \
    -e "s|{{HOME}}|$HOME|g" \
    -e "s|{{LOGDIR}}|$LOG_DIR|g" \
    -e "s|{{API_KEY}}|$API_KEY|g" \
    -e "s|{{POST_URL}}|$POST_URL|g" \
    -e "s|{{CONTEXT_PORT}}|$CONTEXT_PORT|g" \
    "$PLIST_TPL" > "$PLIST_DST"

# ------------------------------------------------------------
# Register with launchd
# ------------------------------------------------------------
echo "🚀 Loading agent via launchctl..."
launchctl bootout gui/$(id -u)/com.mavops.activityagent 2>/dev/null || true
launchctl bootstrap gui/$(id -u) "$PLIST_DST"
launchctl enable gui/$(id -u)/com.mavops.activityagent
launchctl kickstart -k gui/$(id -u)/com.mavops.activityagent

echo ""
echo "✅ Installed & started com.mavops.activityagent"
echo "📂 Logs → $LOG_DIR"
echo "⚙️  Config → $CFG_JSON"
echo ""
echo "To stop:   launchctl bootout gui/$(id -u)/com.mavops.activityagent"
echo "To start:  launchctl bootstrap gui/$(id -u) $PLIST_DST"
echo ""