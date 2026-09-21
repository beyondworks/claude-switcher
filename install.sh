#!/bin/zsh
# Claude Switcher installer (macOS). Re-running it upgrades in place.
set -euo pipefail

HERE="${0:A:h}"
SUPPORT="$HOME/Library/Application Support/claude-switcher"
LIB="$SUPPORT/lib"
BIN="$HOME/.local/bin"
APP="$HOME/Applications/Claude Switcher.app"
MENU_LABEL="io.github.claude-switcher.menubar"
MENU_PLIST="$HOME/Library/LaunchAgents/$MENU_LABEL.plist"

say() { print -P "%F{cyan}==>%f $*"; }
die() { print -P "%F{red}error:%f $*" >&2; exit 1; }

[[ "$(uname)" == "Darwin" ]] || die "macOS only for now."
[[ -d /Applications/Claude.app ]] || die "Claude desktop app not found in /Applications."
xcode-select -p >/dev/null 2>&1 || die "Xcode Command Line Tools are required (python3, swiftc). Run: xcode-select --install"

say "Installing CLI and sync engine"
mkdir -p "$LIB" "$BIN"
cp "$HERE"/src/*.py "$LIB/"
chmod +x "$LIB/claude_switch.py" "$LIB/cs_sync.py"
ln -sf "$LIB/claude_switch.py" "$BIN/claude-switch"

say "Building menu bar app"
mkdir -p "$APP/Contents/MacOS"
swiftc -O "$HERE/menubar/main.swift" -o "$APP/Contents/MacOS/ClaudeSwitcher"
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Claude Switcher</string>
  <key>CFBundleIdentifier</key><string>io.github.claude-switcher</string>
  <key>CFBundleExecutable</key><string>ClaudeSwitcher</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>$(cat "$HERE/VERSION")</string>
  <key>LSUIElement</key><true/>
</dict></plist>
PLIST
codesign --force -s - "$APP" >/dev/null 2>&1 || true

say "Starting menu bar app at login"
cat > "$MENU_PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$MENU_LABEL</string>
  <key>ProgramArguments</key><array><string>$APP/Contents/MacOS/ClaudeSwitcher</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
  <key>ProcessType</key><string>Interactive</string>
</dict></plist>
PLIST
launchctl bootout "gui/$(id -u)/$MENU_LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$MENU_PLIST"

case ":$PATH:" in *":$BIN:"*) ;; *) say "Add $BIN to your PATH to use 'claude-switch' in a terminal.";; esac

say "Detecting session folders"
"$BIN/claude-switch" setup || true

cat <<'DONE'

Installed. Next:
  1. If you have not added your second account yet:  claude-switch add
  2. After logging in there (and opening the Code tab once):  claude-switch setup
  3. Switch with ⌘ + Page Down, the menu bar star, or:  claude-switch
DONE
