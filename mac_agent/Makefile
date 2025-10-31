SHELL := /bin/bash
.ONESHELL:
.SHELLFLAGS := -eu -o pipefail -c

# ====== Config ======
APP_NAME        := TimeTrackerAgent
BUNDLE_ID       := com.mavops.TimeTrackerAgent
PKG_ID          := com.mavops.timetracker
VERSION         := 1.0.0

CODESIGN_APP    := Developer ID Application: Dan Russell (P3KX4CDFN4)
CODESIGN_INST   := Developer ID Installer: Dan Russell (P3KX4CDFN4)
NOTARY_PROFILE  := mavops-notary

ROOT            := pkgroot
APP_DIR         := $(ROOT)/Applications/$(APP_NAME).app
MACOS_DIR       := $(APP_DIR)/Contents/MacOS
RES_DIR         := $(APP_DIR)/Contents/Resources
DISTDIR         := dist
BUILDDIR        := build

ONEDIR_SRC      := dist/$(APP_NAME)
ONEDIR_DST      := $(RES_DIR)/$(APP_NAME)

DISTRIBUTION_XML:= distribution.xml

COMPONENT_PKG   := $(BUILDDIR)/$(APP_NAME).component.pkg
PRODUCT_PKG     := $(DISTDIR)/$(APP_NAME).pkg
DMG             := $(DISTDIR)/$(APP_NAME).dmg

UNSIGNED_PKG 	:= $(DISTDIR)/$(APP_NAME)-unsigned.pkg

# ====== PyInstaller build ======
PYI_SPEC       := TimeTrackerAgent.spec

.PHONY: pyi
pyi:
	@echo "==> PyInstaller build"
	rm -rf "build" "dist"
	pyinstaller --distpath dist --workpath build $(PYI_SPEC)

# ====== Main ship target ======
ship: pyi pkg dmg
	@echo "✅ Ship artifacts ready:"
	@ls -lh "$(DISTDIR)/$(APP_NAME).pkg" "$(DISTDIR)/$(APP_NAME).dmg"

pkg: prep_app sign_app package sign_pkg notarize_pkg staple_pkg verify_pkg
dmg: dmg_build notarize_dmg staple_dmg verify_dmg

# ====== Stage + sign app ======
prep_app:
	@echo "==> Stage .app bundle"
	test -d "$(APP_DIR)" || { echo "Missing $(APP_DIR)"; exit 1; }
	mkdir -p "$(RES_DIR)" "$(MACOS_DIR)"
	test -d "$(ONEDIR_SRC)" || { echo "Missing $(ONEDIR_SRC)"; exit 1; }

	# Guard: stop if a stray TimeTracker.app snuck into pkgroot
	test ! -e "$(ROOT)/Applications/TimeTracker.app" || { \
		echo "ERROR: Remove stray $(ROOT)/Applications/TimeTracker.app"; exit 1; }

	rm -rf "$(ONEDIR_DST)"; cp -R "$(ONEDIR_SRC)" "$(ONEDIR_DST)"
	# … rest of prep_app …
	# remove anything except our launcher (if present)
	find "$(MACOS_DIR)" -mindepth 1 -maxdepth 1 ! -name "$(APP_NAME)" -exec rm -rf {} +
	@if [ ! -x "$(MACOS_DIR)/$(APP_NAME)" ]; then \
		echo "Building C launcher…"; \
		printf '%s\n' \
		'#include <mach-o/dyld.h>' \
		'#include <unistd.h>' \
		'#include <libgen.h>' \
		'#include <limits.h>' \
		'#include <stdio.h>' \
		'#include <stdint.h>' \
		'int main(int argc, char *argv[]) {' \
		'  char exePath[PATH_MAX]; uint32_t size = sizeof(exePath);' \
		'  if (_NSGetExecutablePath(exePath, &size) != 0) { perror("_NSGetExecutablePath"); return 1; }' \
		'  char *macosDir = dirname(exePath);' \
		'  char target[PATH_MAX];' \
		'  snprintf(target, sizeof(target), "%s/../Resources/$(APP_NAME)/$(APP_NAME)", macosDir);' \
		'  execv(target, argv); perror("execv"); return 1;' \
		'}' \
		> launcher.c; \
		clang -O2 -mmacosx-version-min=13.0 -arch arm64 -o "$(MACOS_DIR)/$(APP_NAME)" launcher.c; \
		rm -f launcher.c; \
		chmod 755 "$(MACOS_DIR)/$(APP_NAME)"; \
	fi
	# De-quarantine everything just in case
	xattr -dr com.apple.quarantine "$(APP_DIR)" || true
	@echo "Contents/MacOS:"; ls -lah "$(MACOS_DIR)"
		
sign_app:
	@echo "==> Codesign nested Mach-Os"
	@find "$(RES_DIR)" -type f -print0 | \
		xargs -0 -I{} sh -c 'file -b "{}" | grep -q "Mach-O" && \
		  echo "codesign: {}" && \
		  codesign --force --options runtime --timestamp -s "$(CODESIGN_APP)" "{}" || true'

	@echo "==> Codesign launcher"
	@codesign --force --options runtime --timestamp -s "$(CODESIGN_APP)" "$(MACOS_DIR)/$(APP_NAME)"

	@echo "==> Codesign .app"
	@codesign --force --options runtime --timestamp -s "$(CODESIGN_APP)" "$(APP_DIR)"
	@codesign --verify --strict --verbose=2 "$(APP_DIR)"

# ====== PKG build + sign + notarize ======
package:
	@echo "==> pkgbuild"
	@mkdir -p "$(BUILDDIR)" "$(DISTDIR)"
	@pkgbuild \
		--root "$(ROOT)" \
		--scripts scripts \
		--identifier "$(PKG_ID)" \
		--version "$(VERSION)" \
		--install-location / \
		"$(COMPONENT_PKG)"
	@echo "==> productbuild"
	@productbuild \
		--distribution "$(DISTRIBUTION_XML)" \
		--resources . \
		--package-path "$(BUILDDIR)" \
		"$(UNSIGNED_PKG)"

sign_pkg:
	@echo "==> productsign"
	@productsign --timestamp --sign "$(CODESIGN_INST)" "$(UNSIGNED_PKG)" "$(PRODUCT_PKG)"

notarize_pkg:
	@echo "==> Notarize PKG"
	xcrun notarytool submit "$(DISTDIR)/$(APP_NAME).pkg" --keychain-profile "$(NOTARY_PROFILE)" --wait

staple_pkg:
	@echo "==> Staple PKG"
	xcrun stapler staple "$(DISTDIR)/$(APP_NAME).pkg" || true

verify_pkg:
	@echo "==> spctl assess (pkg)"
	spctl --assess --type install -vv "$(DISTDIR)/$(APP_NAME).pkg" || true

# ====== Optional DMG ======
dmg_build:
	@echo "==> Build DMG"
	rm -f "$(DMG)"
	hdiutil create -fs APFS -volname "$(APP_NAME)" -srcfolder "$(APP_DIR)" "$(DMG)"

notarize_dmg:
	xcrun notarytool submit "$(DMG)" --keychain-profile "$(NOTARY_PROFILE)" --wait

staple_dmg:
	xcrun stapler staple "$(DMG)" || true

verify_dmg:
	spctl --assess --type open -vv "$(DMG)" || true

clean:
	@echo "==> Clean"
	rm -rf "$(BUILDDIR)" "$(DISTDIR)"