#!/bin/bash
# Build Butler (native Swift menu-bar app) → 自包含 /Applications/Butler.app
# 依赖: swiftc(CLT 自带)。产物内含 server.py + HTML + icns,跑系统 python3,零 pip/venv/brew。
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
APP="/Applications/Butler.app"
BUNDLE_ID="com.agentbutler"
BIN="Butler"

echo "== 1/4 编译 Swift =="
BUILD="$HERE/.build"; mkdir -p "$BUILD"
swiftc -O -o "$BUILD/$BIN" \
  -framework Cocoa -framework WebKit -framework UserNotifications -framework ServiceManagement \
  "$HERE"/Sources/*.swift
echo "✓ $BIN"

echo "== 2/4 组装 .app =="
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$BUILD/$BIN" "$APP/Contents/MacOS/$BIN"
# 数据引擎 + 静态资源打进 bundle(自包含)
cp "$REPO/server.py" "$APP/Contents/Resources/server.py"
cp "$REPO/projects.json" "$APP/Contents/Resources/projects.json" 2>/dev/null || true
cp "$REPO/assets/Butler.icns" "$APP/Contents/Resources/AppIcon.icns"
if [ -d "$HERE/Resources" ]; then
  cp -R "$HERE/Resources/"*.lproj "$APP/Contents/Resources/"
fi

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Butler</string>
  <key>CFBundleDisplayName</key><string>Butler</string>
  <key>CFBundleDevelopmentRegion</key><string>en</string>
  <key>CFBundleAllowMixedLocalizations</key><true/>
  <key>CFBundleLocalizations</key><array>
    <string>en</string>
    <string>zh-Hans</string>
    <string>ja</string>
    <string>ko</string>
    <string>es</string>
  </array>
  <key>CFBundleIdentifier</key><string>$BUNDLE_ID</string>
  <key>CFBundleExecutable</key><string>$BIN</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundleShortVersionString</key><string>4.0</string>
  <key>CFBundleVersion</key><string>4.0</string>
  <key>LSUIElement</key><true/>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>NSHumanReadableCopyright</key><string>Butler · your AI agents, always on call</string>
</dict></plist>
PLIST

echo "== 3/4 stop old instance (open won't relaunch a running app)) =="
pkill -9 -f "Butler.app/Contents/MacOS/Butler" 2>/dev/null || true
kill $(lsof -tiTCP:7788 -sTCP:LISTEN 2>/dev/null) 2>/dev/null || true
sleep 1

echo "== 4/4 签名 =="
codesign --force --deep --sign - "$APP"
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$APP"

echo "== 5/6 Claude 会话引擎(ccm hooks,唯一外部安装) =="
if ! command -v ccm >/dev/null && [ ! -x "$HOME/.npm-global/bin/ccm" ]; then
  if command -v npm >/dev/null; then npm install -g claude-code-monitor >/dev/null 2>&1 || true; fi
fi
CCM="$(command -v ccm || echo "$HOME/.npm-global/bin/ccm")"
[ -x "$CCM" ] && (yes | "$CCM" setup >/dev/null 2>&1 || true) && echo "✓ ccm hooks" || echo "  (未装 ccm:Claude 会话数据将走 transcript 冷启动兜底)"

echo "== 6/6 完成 =="
echo "✓ $APP"
open "$APP"                       # auto-launch the freshly built app (build = deploy)
echo "  已启动 · 手动: open \"$APP\""

# 可选: 打 .dmg 分发包(传 --dmg)
if [ "${1:-}" = "--dmg" ]; then
  echo "== 打包 .dmg =="
  DMG="$REPO/Butler.dmg"; STAGE="$(mktemp -d)"
  cp -R "$APP" "$STAGE/"
  ln -s /Applications "$STAGE/Applications"
  rm -f "$DMG"
  hdiutil create -volname "Butler" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null
  rm -rf "$STAGE"
  echo "✓ $DMG (拖进 Applications 即装)"
fi
