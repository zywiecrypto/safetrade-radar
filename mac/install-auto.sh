#!/bin/bash
# Optional: collect in the background every 30 minutes while the Mac is on (launchd).
# Run once:  bash mac/install-auto.sh      Turn off:  bash mac/uninstall-auto.sh
set -e
DIR="$(cd "$(dirname "$0")/.." && pwd)"
PL="$HOME/Library/LaunchAgents/com.safetrade-radar.collect.plist"
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PL" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.safetrade-radar.collect</string>
  <key>ProgramArguments</key><array><string>/usr/bin/env</string><string>python3</string><string>$DIR/collect.py</string></array>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>StartInterval</key><integer>1800</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$DIR/collect.log</string>
  <key>StandardErrorPath</key><string>$DIR/collect.log</string>
</dict></plist>
PLIST
launchctl unload "$PL" 2>/dev/null || true
launchctl load "$PL"
echo "Enabled: data is collected every 30 minutes. Log: $DIR/collect.log"
