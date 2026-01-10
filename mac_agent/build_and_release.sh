#!/usr/bin/env bash
#
# TimeTracker Mac Agent - Build, Sign, Notarize
# Usage: ./build_and_release.sh [version]
# Example: ./build_and_release.sh 1.0.1
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
rm -rf build dist dist_out *.pkg 2>/dev/null || true

# ============================================================
# STEP 2: Set up virtual environment and build
# ============================================================
echo ""
echo "📦 Setting up Python environment..."
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip wheel -q
pip install -r requirements.txt pyinstaller -q

echo ""
echo "🔨 Building with PyInstaller..."
pyinstaller \
    --onefile \
    --name TimeTrackerAgent \
    --clean \
    --noconfirm \
    main.py

# ============================================================
# STEP 2.5: Sign the binary with hardened runtime
# ============================================================
echo ""
echo "🔐 Signing binary with hardened runtime..."
codesign --force --options runtime --timestamp \
    --sign "Developer ID Application: Dan Russell (P3KX4CDFN4)" \
    dist/TimeTrackerAgent

# Verify binary signature
codesign --verify --verbose dist/TimeTrackerAgent

# ============================================================
# STEP 3: Prepare pkgroot structure
# ============================================================
echo ""
echo "📁 Preparing package structure..."

# Clear and recreate pkgroot/usr/local/bin
rm -rf pkgroot/usr/local/bin
mkdir -p pkgroot/usr/local/bin

# Copy the built binary
cp dist/TimeTrackerAgent pkgroot/usr/local/bin/
chmod +x pkgroot/usr/local/bin/TimeTrackerAgent

# ============================================================
# STEP 4: Build component package
# ============================================================
echo ""
echo "📦 Building component package..."
pkgbuild \
    --root pkgroot \
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
echo "Next steps:"
echo "  1. Test locally: sudo installer -pkg ${APP_NAME}.pkg -target /"
echo "  2. Push to GitHub:"
echo "     gh release create v${VERSION} ${APP_NAME}.pkg \\"
echo "         --repo YOUR_USERNAME/timetracker-releases \\"
echo "         --title \"TimeTracker v${VERSION}\" \\"
echo "         --notes \"Release notes here\""
echo ""