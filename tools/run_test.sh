#!/bin/sh
# Starts a test instance, plays the virtual gamepad commands and stops it again.
# A running daemon is paused meanwhile (otherwise the virtual Guide button would
# open both) and restarted afterwards.
# Usage: tools/run_test.sh <log file> <virtual_pad commands...>
cd "$(dirname "$0")/.." || exit 1
log="$1"; shift
daemon=$(pgrep -f '^python3 [^ ]*caelestia-bigscreen --daemon$')
[ -n "$daemon" ] && kill $daemon
BIGSCREEN_TEST=1 python3 bin/caelestia-bigscreen --daemon >"$log" 2>&1 &
pid=$!
sleep 2.5
python3 tools/virtual_pad.py "$@"
kill "$pid" 2>/dev/null
wait "$pid" 2>/dev/null
if [ -n "$daemon" ] && command -v hyprctl >/dev/null; then
    hyprctl dispatch "hl.dsp.exec_cmd(\"$HOME/.local/bin/caelestia-bigscreen --daemon\")" >/dev/null
fi
