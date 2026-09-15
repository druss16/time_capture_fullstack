#!/usr/bin/env bash
#
# TimeTracker Mac Agent - Build, Sign, Notarize
# Usage: ./build_and_release.sh [version]
# Example: ./build_and_release.sh 1.0.1
#
# THIS DOES NOT RELEASE ANYTHING, despite the name. It produces a signed,
# notarized TimeTracker.pkg in this directory and stops. No tag is created,
# no GitHub release is touched, and no agent — Mac or Windows — learns that
# a new version exists. Use it to build and test a package locally.
#
# Shipping goes through a tag on this repo, which runs .github/workflows/
# release.yml: it builds BOTH agents and publishes all four artifacts to
# druss16/timetracker-releases in one release. See the closing notes.
#
# SHIPS AN .app, NOT A BARE BINARY.
# This is not a packaging preference. The agent's notification manager calls
# +[UNUserNotificationCenter currentNotificationCenter], which throws
# NSInternalInconsistencyException ("bundleProxyForCurrentProcess is nil")
# when the process has no bundle. That is an Objective-C exception, so no
# Python try/except catches it: the process aborts with SIGABRT partway
# through startup, right after its first sync. A --onefile binary installed
# to /usr/local/bin could never have run.
#
# This script stages into its own root (PKGROOT below) rather than the
# shared ./pkgroot, which the Makefile owns and fills with TimeTrackerAgent.app.
# Two apps in one root would both end up in the same .pkg.
#
set -euo pipefail
cd "$(dirname "$0")"

# ============================================================
# CONFIGURATION - Update these if needed
# ============================================================
APP_NAME="TimeTracker"
BUNDLE_ID="com.mavops.timetracker"
DEVELOPER_ID="Developer ID Installer: Dan Russell (P3KX4CDFN4)"
APPLE_ID="druss16@gmail.com"  # UPDATE THIS to your Apple ID email
TEAM_ID="P3KX4CDFN4"
# Keychain profile for notarization (set up once with: xcrun notarytool store-credentials)
NOTARY_PROFILE="timetracker-notary"

# Staging root for THIS script. Kept separate from ./pkgroot (the Makefile's,
# which stages TimeTrackerAgent.app) so the two packaging paths cannot mix
# payloads. Rebuilt from scratch on every run — never edit it by hand.
PKGROOT="pkgroot_timetracker"
PKG_SCRIPTS="pkg_scripts"
LAUNCH_LABEL="com.mavops.timetracker"
APP_SIGN_ID="Developer ID Application: Dan Russell (P3KX4CDFN4)"

# ============================================================
# VERSION
# ============================================================
VERSION="${1:-}"
if [ -z "$VERSION" ]; then
    # Try to extract from main.py or default to 1.0.0
    VERSION=$(grep -o 'APP_VERSION.*"[0-9.]*"' main.py | grep -o '[0-9.]*' | head -1 || echo "1.0.0")
    echo "No version specified, using: $VERSION"
    read -p "Continue with this version? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Usage: $0 <version>"
        echo "Example: $0 1.0.1"
        exit 1
    fi
fi

echo "============================================================"
echo "Building TimeTracker v${VERSION}"
echo "============================================================"

# ============================================================
# STEP 1: Clean previous builds
# ============================================================
echo ""
echo "🧹 Cleaning previous builds..."
rm -rf build dist dist_out "${PKGROOT}" *.pkg 2>/dev/null || true

# ============================================================
# STEP 2: Set up virtual environment and build
# ============================================================
echo ""
echo "📦 Setting up Python environment..."
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip wheel -q
pip install -r requirements.txt pyinstaller -q

# The version has to be written BEFORE PyInstaller runs: version.py is
# imported by main.py and frozen into the binary. APP_VERSION rides on every
# event payload as agent_version (fleet visibility) and is what
# update_checker compares against the server, so a build left at "dev" both
# reports nothing useful and never recognises itself as up to date.
echo ""
echo "🏷  Stamping version.py → ${VERSION}"
cat > version.py <<VERSIONPY
# mac_agent/version.py
# Auto-generated during build - DO NOT EDIT MANUALLY
APP_VERSION = "${VERSION}"
VERSIONPY

echo ""
echo "🔨 Building ${APP_NAME}.app with PyInstaller..."
# TimeTracker.spec ends in a BUNDLE step, so this produces a real .app with
# an Info.plist and a bundle identifier — which is the whole point. It also
# names every agent module in datas/hiddenimports; see the Building section
# of PARITY.md for why that list has to be maintained by hand.
pyinstaller --clean --noconfirm --distpath dist --workpath build TimeTracker.spec

test -d "dist/${APP_NAME}.app" || {
    echo "❌ Expected dist/${APP_NAME}.app — PyInstaller did not produce a bundle"
    exit 1
}

# ============================================================
# STEP 2.4: Stamp the version into the bundle
# ============================================================
# Before signing, never after: editing Info.plist breaks the seal over it.
# The spec cannot carry the version because it is a build argument.
echo ""
echo "🏷  Stamping Info.plist → ${VERSION}"
plutil -replace CFBundleShortVersionString -string "${VERSION}" "dist/${APP_NAME}.app/Contents/Info.plist"
plutil -replace CFBundleVersion            -string "${VERSION}" "dist/${APP_NAME}.app/Contents/Info.plist"

# The identifier must not drift: TCC keys Accessibility on it, so a change
# makes macOS treat this as a new app and every user silently loses the
# permission that lets the agent read window titles.
ACTUAL_ID="$(plutil -extract CFBundleIdentifier raw "dist/${APP_NAME}.app/Contents/Info.plist")"
if [[ "$ACTUAL_ID" != "TimeTracker" ]]; then
    echo "❌ Bundle identifier is '${ACTUAL_ID}', expected 'TimeTracker'."
    echo "   Shipping this would reset Accessibility for every existing Mac user."
    echo "   Fix bundle_identifier in TimeTracker.spec."
    exit 1
fi

# ============================================================
# STEP 2.5: Sign the app with hardened runtime
# ============================================================
echo ""
echo "🔐 Signing nested Mach-O binaries..."
# Nested code must be signed before the bundle that contains it, or the
# outer signature seals over unsigned content and notarization rejects it.
find "dist/${APP_NAME}.app/Contents" -type f -print0 | while IFS= read -r -d '' f; do
    if file -b "$f" | grep -q "Mach-O"; then
        codesign --force --options runtime --timestamp --sign "${APP_SIGN_ID}" "$f" 2>/dev/null || true
    fi
done

echo "🔐 Signing ${APP_NAME}.app..."
codesign --force --options runtime --timestamp \
    --sign "${APP_SIGN_ID}" \
    "dist/${APP_NAME}.app"

codesign --verify --strict --verbose=2 "dist/${APP_NAME}.app"

# ============================================================
# STEP 3: Prepare package root
# ============================================================
echo ""
echo "📁 Preparing package structure..."

rm -rf "${PKGROOT}"
mkdir -p "${PKGROOT}/Applications" "${PKGROOT}/Library/LaunchAgents"

# ditto, not cp -R: it is the tool that understands bundles, preserving
# extended attributes and resource forks so the code signature survives the
# copy intact. (The ._ AppleDouble entries visible in `lsbom` afterwards are
# pkgbuild's own encoding of those xattrs, not an artifact of the copy —
# the installer merges them back. cp -R also preserves the signature here;
# ditto is simply the tool Apple documents for moving a signed bundle.)
ditto "dist/${APP_NAME}.app" "${PKGROOT}/Applications/${APP_NAME}.app"

# LaunchAgent pointing at the app's executable INSIDE the bundle. Running the
# inner executable directly still gives the process a main bundle, because
# NSBundle derives it from the executable's path — which is what the working
# install on a real machine does.
cat > "${PKGROOT}/Library/LaunchAgents/${LAUNCH_LABEL}.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${LAUNCH_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Applications/${APP_NAME}.app/Contents/MacOS/${APP_NAME}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
    </dict>
    <key>ProcessType</key>
    <string>Interactive</string>
    <key>ThrottleInterval</key>
    <integer>5</integer>
    <key>StandardOutPath</key>
    <string>/tmp/timetracker.stdout.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/timetracker.stderr.log</string>
</dict>
</plist>
PLIST

echo "   staged:"
find "${PKGROOT}" -maxdepth 3 -mindepth 2 | sed 's|^|     |'

# ============================================================
# STEP 4: Build component package
# ============================================================
echo ""
echo "📦 Building component package..."
pkgbuild \
    --root "${PKGROOT}" \
    --scripts "${PKG_SCRIPTS}" \
    --identifier "${BUNDLE_ID}" \
    --version "${VERSION}" \
    --install-location / \
    TimeTrackerAgent.component.pkg

# ============================================================
# STEP 5: Build distribution package
# ============================================================
echo ""
echo "📦 Building distribution package..."

# Update version in distribution.xml
sed -i '' "/pkg-ref.*version=/s/version=\"[0-9.]*\"/version=\"${VERSION}\"/" distribution.xml

productbuild \
    --distribution distribution.xml \
    --package-path . \
    unsigned.pkg

# ============================================================
# STEP 6: Sign the package
# ============================================================
echo ""
echo "🔐 Signing package..."
productsign \
    --sign "${DEVELOPER_ID}" \
    unsigned.pkg \
    "${APP_NAME}.pkg"

# Verify signature
echo ""
echo "✅ Verifying signature..."
pkgutil --check-signature "${APP_NAME}.pkg"

# ============================================================
# STEP 7: Notarize
# ============================================================
echo ""
echo "🍎 Submitting for notarization (this may take 1-5 minutes)..."
xcrun notarytool submit "${APP_NAME}.pkg" \
    --keychain-profile "${NOTARY_PROFILE}" \
    --wait

# ============================================================
# STEP 8: Staple the notarization ticket
# ============================================================
echo ""
echo "📎 Stapling notarization ticket..."
xcrun stapler staple "${APP_NAME}.pkg"

# ============================================================
# STEP 9: Final verification
# ============================================================
echo ""
echo "🔍 Final verification..."
spctl --assess -v --type install "${APP_NAME}.pkg"

# ============================================================
# CLEANUP
# ============================================================
echo ""
echo "🧹 Cleaning up intermediate files..."
rm -f unsigned.pkg TimeTrackerAgent.component.pkg

# ============================================================
# DONE
# ============================================================
echo ""
echo "============================================================"
echo "✅ SUCCESS! Built ${APP_NAME}.pkg v${VERSION}"
echo "============================================================"
echo ""
echo "Package location: $(pwd)/${APP_NAME}.pkg"
echo "Size: $(du -h ${APP_NAME}.pkg | cut -f1)"
echo ""
echo "After installing, confirm the agent is actually RUNNING — the"
echo "installer reports success for a package whose agent cannot start:"
echo "  launchctl list | grep ${LAUNCH_LABEL}"
echo "A PID in the first column means it is up. A number in the second with"
echo "no PID is the exit status of a job that failed (2 = file not found)."
echo ""
echo "This package has NOT been released. Nothing downstream knows it exists."
echo ""
echo "Test it locally:"
echo "  sudo installer -pkg ${APP_NAME}.pkg -target /"
echo ""
echo "To actually SHIP ${VERSION}, push a tag on this repo:"
echo "  git tag v${VERSION} && git push origin v${VERSION}"
echo ""
echo "That runs .github/workflows/release.yml, which builds the Mac AND"
echo "Windows agents and publishes all four artifacts together to"
echo "druss16/timetracker-releases."
echo ""
echo "⚠️  Do NOT publish this .pkg on its own with \`gh release create\`."
echo "    The server resolves every agent's update against the SAME"
echo "    releases/latest tag and only picks the download URL by platform."
echo "    A release carrying just the .pkg tells Windows agents that"
echo "    ${VERSION} is current, and they then fetch"
echo "    TimeTracker-Windows-Setup.exe from a release that has no such"
echo "    file — a 404, and Windows auto-update stops working."
echo ""