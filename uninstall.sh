#!/bin/zsh
# Removes Claude Switcher's programs and agents. Your Claude data folders, logins and sessions are left untouched.
set -uo pipefail
uid=$(id -u)
for label in io.github.claude-switcher.menubar io.github.claude-switcher.sync; do
  launchctl bootout "gui/$uid/$label" 2>/dev/null
  rm -f "$HOME/Library/LaunchAgents/$label.plist"
done
rm -rf "$HOME/Applications/Claude Switcher.app" "$HOME/Library/Application Support/claude-switcher/lib"
rm -f "$HOME/.local/bin/claude-switch"
echo "Removed. Kept: ~/.config/claude-switcher (settings), ~/Library/Application Support/claude-switcher (sync log, trash)."
echo "Your second account's data folder (~/Library/Application Support/Claude Second) was not touched."
