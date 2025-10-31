#!/usr/bin/env bash
set -euo pipefail

PLIST="$HOME/Library/LaunchAgents/com.mavops.activityagent.plist"
BIN_DIR="$HOME/.timetracker/bin"
BIN="$BIN_DIR/TimeTrackerAgent"
LOG_DIR="$HOME/Library/Logs/ActivityAgent"
CFG_DIR="$HOME/.timetracker"

KEEP_CFG=0
if [[ "${1:-}" == "--keep-config" || "${1:-}" == "-k" ]]; then
  KEEP_CFG=1
fi

echo "➜ Stopping LaunchAgent (if loaded)…"
# unload for legacy
launchctl unload "$PLIST" 2>/dev/null || true
# and bootout for modern domains
launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true

echo "➜ Removing LaunchAgent plist…"
rm -f "$PLIST"

echo "➜ Removing agent binary…"
rm -f "$BIN"
# cleanup empty bin dir
rmdir "$BIN_DIR" 2>/dev/null || true

echo "➜ Removing logs…"
rm -rf "$LOG_DIR"

if [[ $KEEP_CFG -eq 1 ]]; then
  echo "✓ Kept config at $CFG_DIR"
else
  echo "➜ Removing config…"
  rm -rf "$CFG_DIR"
fi

echo "✅ Uninstall complete."
echo "   (If the menu bar helper app exists, quit it manually or remove /Applications/TimeTracker.app)"