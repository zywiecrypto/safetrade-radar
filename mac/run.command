#!/bin/bash
# Double-click in Finder: collect fresh SafeTrade data and open the site.
cd "$(dirname "$0")/.." || exit 1
python3 collect.py
status=$?
if [ $status -eq 0 ]; then open index.html; else echo; echo "The collector exited with an error ($status). See the message above."; fi
echo; read -n 1 -s -r -p "Press any key to close this window."
