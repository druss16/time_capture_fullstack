#!/usr/bin/env bash
set -euo pipefail

IDENTITY='Developer ID Application: Dan Russell (P3KX4CDFN4)'
APP="dist/TimeTracker.app"
BIN="$APP/Contents/MacOS/TimeTracker"

if [ ! -d "$APP" ]; then
  echo "❌ App bundle not found at $APP"
  exit 1
fi

echo "→ Fix Info.plist identifiers (required for notarization)"
/usr/libexec/PlistBuddy -c "Set :CFBundleIdentifier com.mavops.timetracker" "$APP/Contents/Info.plist" || true
/usr/libexec/PlistBuddy -c "Set :CFBundleName TimeTracker" "$APP/Contents/Info.plist" || true

echo "→ Remove quarantine xattrs"
xattr -dr com.apple.quarantine "$APP" || true

echo "→ Sign nested binaries (.dylib/.so/executables) in Frameworks"
if [ -d "$APP/Contents/Frameworks" ]; then
  find "$APP/Contents/Frameworks" -type f \( -name "*.dylib" -o -name "*.so" -o -perm -111 \) -print0 \
  | xargs -0 -I{} codesign --force --options runtime --timestamp -s "$IDENTITY" "{}"
fi

echo "→ Sign nested binaries in Resources (PyInstaller often drops .so here)"
if [ -d "$APP/Contents/Resources" ]; then
  find "$APP/Contents/Resources" -type f \( -name "*.dylib" -o -name "*.so" -o -perm -111 \) -print0 \
  | xargs -0 -I{} codesign --force --options runtime --timestamp -s "$IDENTITY" "{}"
fi

echo "→ Sign main executable"
codesign --force --options runtime --timestamp -s "$IDENTITY" "$BIN"

echo "→ Sign the .app bundle (deep last)"
codesign --deep --force --options runtime --timestamp -s "$IDENTITY" "$APP"

echo "→ Verify signature & hardened runtime"
codesign --verify --deep --strict --verbose=2 "$APP"
codesign -dv --verbose=4 "$BIN" 2>&1 | sed -n '1,120p'

echo "→ Create fresh notarization ZIP"
rm -f TimeTracker.app.zip
ditto -c -k --keepParent "$APP" TimeTracker.app.zip
ls -lh TimeTracker.app.zip
