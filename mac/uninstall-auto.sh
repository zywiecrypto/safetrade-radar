#!/bin/bash
PL="$HOME/Library/LaunchAgents/com.safetrade-radar.collect.plist"
launchctl unload "$PL" 2>/dev/null; rm -f "$PL"; echo "Disabled."
