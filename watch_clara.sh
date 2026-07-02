#!/bin/bash
# Watch the live output of the running CLARA stack — all logs in ONE window.
# The stack runs detached (start_clara.sh uses nohup), so this is how you see live output
# without 4 separate terminals. Ctrl+C stops *watching* only — the stack keeps running.
#
#   bash watch_clara.sh            # tail all four logs together (labelled by ==> file <==)
#   bash watch_clara.sh whatsapp   # tail just one: backend | whatsapp | hotkey | frontend
#                                   # (use this to see the WhatsApp QR when re-linking)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

# Single-component mode
if [ -n "$1" ]; then
    case "$1" in
        backend|api)       f="api.log" ;;
        whatsapp|wa|qr)    f="whatsapp.log" ;;
        hotkey)            f="hotkey.log" ;;
        frontend|fe|vite)  f="frontend.log" ;;
        *)                 f="$1" ;;
    esac
    if [ ! -f "$f" ]; then echo "[CLARA] $f not found — is that component running?"; exit 1; fi
    echo "[CLARA] Tailing $f  (Ctrl+C to stop watching; the stack keeps running)"
    echo "---"
    tail -n 40 -f "$f"
    exit 0
fi

# All-logs mode
LOGS=()
for f in api.log whatsapp.log hotkey.log frontend.log; do
    [ -f "$f" ] && LOGS+=("$f")
done
if [ ${#LOGS[@]} -eq 0 ]; then
    echo "[CLARA] No logs found — is the stack running?  Start it with: bash start_clara.sh"
    exit 1
fi
echo "[CLARA] Tailing: ${LOGS[*]}  (Ctrl+C to stop watching; the stack keeps running)"
echo "---"
tail -n 15 -f "${LOGS[@]}"
