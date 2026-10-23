#!/bin/bash
# Verify the GNOME Shell extension in a throwaway shell, without logging out.
#
# GNOME Shell 50 REMOVED `--nested`; nesting is now `--devkit`. The old flag fails with
# "Unknown option --nested", and because the shell then never starts, every D-Bus call fails with
# ServiceUnknown — which looks exactly like a broken extension. It cost an hour to notice.
#
# Usage: tools/verify_extension.sh
set -u
UUID=gesture-os@anurag.local
LOG=$(mktemp /tmp/gesture-os-shell-XXXX.log)

cp -r "$(dirname "$0")/../extension/$UUID" ~/.local/share/gnome-shell/extensions/ 2>/dev/null || true

export WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-wayland-0}
export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}

gnome-shell --devkit --virtual-monitor 1920x1080 > "$LOG" 2>&1 &
PID=$!
trap 'kill $PID 2>/dev/null' EXIT

for _ in $(seq 1 40); do
    gdbus introspect --session -d org.gnome.Shell -o /org/gnome/Shell >/dev/null 2>&1 && break
    sleep 0.5
done
if ! gdbus introspect --session -d org.gnome.Shell -o /org/gnome/Shell >/dev/null 2>&1; then
    echo "FAIL: nested shell did not start. Log:"; head -5 "$LOG"; exit 1
fi

gnome-extensions enable "$UUID" 2>&1
D="--session -d org.gestureos.Shell -o /org/gestureos/Shell"

echo "GetApiVersion: $(timeout 8 gdbus call $D -m org.gestureos.Shell.GetApiVersion 2>&1)"

# The devkit shell creates its OWN Wayland socket. An app launched with the host's
# WAYLAND_DISPLAY connects to the host compositor instead and never appears in the session under
# test — which looks like "the extension cannot see windows".
NESTED_DISPLAY=$(ls -t "$XDG_RUNTIME_DIR"/wayland-* 2>/dev/null | grep -v '\.lock$' \
    | grep -v "/${WAYLAND_DISPLAY}$" | head -1 | xargs -r basename)
if [ -z "$NESTED_DISPLAY" ]; then
    echo "FAIL: could not find the nested shell's Wayland socket"; exit 1
fi
echo "nested display: $NESTED_DISPLAY"
WAYLAND_DISPLAY="$NESTED_DISPLAY" gnome-text-editor >/dev/null 2>&1 &
APP=$!
trap 'kill $APP $PID 2>/dev/null' EXIT

WID=""
for _ in $(seq 1 25); do
    WID=$(timeout 5 gdbus call $D -m org.gestureos.Shell.ListWindows 2>/dev/null | python3 -c "
import sys,json,ast
try:
    ws = json.loads(ast.literal_eval(sys.stdin.read().strip())[0]); print(ws[0]['id'] if ws else '')
except Exception: print('')
")
    [ -n "$WID" ] && break
    sleep 1
done
if [ -z "$WID" ]; then echo "FAIL: no window appeared in the nested session"; exit 1; fi

geom() { timeout 5 gdbus call $D -m org.gestureos.Shell.ListWindows 2>/dev/null | python3 -c "
import sys,json,ast
ws = json.loads(ast.literal_eval(sys.stdin.read().strip())[0]); print(ws[0]['rect'] if ws else 'none')"; }

echo "window:        $WID"
echo "before:        $(geom)"
echo "MoveWindowTo:  $(timeout 8 gdbus call $D -m org.gestureos.Shell.MoveWindowTo "$WID" 120 140 640 480 2>&1)"
sleep 1
AFTER=$(geom)
echo "after:         $AFTER"
echo "unknown id:    $(timeout 8 gdbus call $D -m org.gestureos.Shell.MoveWindowTo 999999 0 0 10 10 2>&1)"

case "$AFTER" in
    *"'width': 640"*) echo; echo "PASS: the extension moved a real window." ;;
    *) echo; echo "FAIL: geometry did not change to 640x480"; exit 1 ;;
esac
