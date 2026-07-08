#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="$ROOT_DIR/dist"
FINAL_APP_DIR="$DIST_DIR/Butler Light.app"
BUILD_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/butler-light-app.XXXXXX")"
APP_DIR="$BUILD_ROOT/Butler Light.app"
CONTENTS_DIR="$APP_DIR/Contents"
MACOS_DIR="$CONTENTS_DIR/MacOS"
RESOURCES_DIR="$CONTENTS_DIR/Resources"
trap 'rm -rf "$BUILD_ROOT"' EXIT

clear_bundle_xattrs() {
  local bundle="$1"

  if ! command -v xattr >/dev/null 2>&1; then
    return
  fi

  xattr -cr "$bundle" 2>/dev/null || true
  while IFS= read -r item; do
    xattr -d com.apple.FinderInfo "$item" 2>/dev/null || true
    xattr -d com.apple.provenance "$item" 2>/dev/null || true
    xattr -d 'com.apple.fileprovider.fpfs#P' "$item" 2>/dev/null || true
  done < <(find "$bundle" -print)
}

cd "$ROOT_DIR"
if [[ ! -f "Resources/AppIcon.icns" ]]; then
  python3 scripts/make_icon.py >/dev/null
fi
swift build -c release

mkdir -p "$MACOS_DIR" "$RESOURCES_DIR"
install -m 755 ".build/release/ButlerLight" "$MACOS_DIR/ButlerLight"
install -m 644 "Resources/AppIcon.icns" "$RESOURCES_DIR/AppIcon.icns"
find Resources -maxdepth 1 -name '*.lproj' -type d -exec cp -R {} "$RESOURCES_DIR/" \;

cat > "$CONTENTS_DIR/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key>
  <string>en</string>
  <key>CFBundleExecutable</key>
  <string>ButlerLight</string>
  <key>CFBundleIdentifier</key>
  <string>com.agentbutler.light</string>
  <key>CFBundleInfoDictionaryVersion</key>
  <string>6.0</string>
  <key>CFBundleName</key>
  <string>Butler Light</string>
  <key>CFBundleDisplayName</key>
  <string>Butler Light</string>
  <key>CFBundleAllowMixedLocalizations</key>
  <true/>
  <key>CFBundleLocalizations</key>
  <array>
    <string>en</string>
    <string>zh-Hans</string>
    <string>ja</string>
    <string>ko</string>
  </array>
  <key>CFBundleIconFile</key>
  <string>AppIcon</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>0.1.0</string>
  <key>CFBundleVersion</key>
  <string>1</string>
  <key>LSMinimumSystemVersion</key>
  <string>13.0</string>
  <key>NSBluetoothAlwaysUsageDescription</key>
  <string>Butler Light uses Bluetooth to connect to your ELK-BLEDOM LED strip.</string>
  <key>NSBluetoothPeripheralUsageDescription</key>
  <string>Butler Light uses Bluetooth to control your LED strip.</string>
  <key>NSHighResolutionCapable</key>
  <true/>
</dict>
</plist>
PLIST

if command -v codesign >/dev/null 2>&1; then
  clear_bundle_xattrs "$APP_DIR"
  codesign --force --deep --sign - "$APP_DIR" >/dev/null
  codesign --verify --deep --strict "$APP_DIR"
fi

rm -rf "$FINAL_APP_DIR"
mkdir -p "$DIST_DIR"
if command -v ditto >/dev/null 2>&1; then
  ditto --noextattr --noqtn "$APP_DIR" "$FINAL_APP_DIR"
else
  cp -R "$APP_DIR" "$FINAL_APP_DIR"
fi
clear_bundle_xattrs "$FINAL_APP_DIR"

echo "Created: $FINAL_APP_DIR"
