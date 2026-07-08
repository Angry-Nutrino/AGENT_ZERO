#!/bin/bash
# Start the FULL CLARA stack — backend + WhatsApp watcher + F10 hotkey + frontend —
# detached from the terminal (survives session close).
#   Usage:  bash start_clara.sh        Stop:  bash stop_clara.sh
#   Logs (project root): api.log, whatsapp.log, hotkey.log, frontend.log
#
# The WhatsApp watcher + hotkey listener are best-effort: if their file/dep is missing
# the script warns and keeps going (so a partial setup still brings up backend+frontend).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$SCRIPT_DIR/jarvis_v2/Scripts/python.exe"
INTERFACE_DIR="$SCRIPT_DIR/interface"
WHATSAPP_DIR="$SCRIPT_DIR/whatsapp_service"

# Repo-local HuggingFace cache — writable by every context (the user-profile cache got
# permission-walled to non-interactive shells, 2026-06-21). api.py also sets this, but
# export here so the launch environment is unambiguous.
export HF_HOME="$SCRIPT_DIR/.hf_cache"

# WSL guard — the Windows venv (jarvis_v2) cannot be sourced from WSL (CRLF + win binaries).
# NOTE: in PowerShell, a bare `bash` resolves to the WSL launcher, which is how people land
# here by accident. The fix is the wrapper: `.\start_clara.ps1` (invokes Git Bash explicitly).
if grep -qiE "microsoft|wsl" /proc/version 2>/dev/null; then
    echo "[CLARA] ERROR: running under WSL ('bash' in PowerShell = the WSL launcher)."
    echo "[CLARA] From PowerShell run:  .\\start_clara.ps1"
    echo "[CLARA] Or from a Git Bash terminal:  bash start_clara.sh"
    exit 1
fi
if [ ! -f "$PY" ]; then
    echo "[CLARA] ERROR: venv python not found at $PY (expected the Windows venv jarvis_v2/)."
    exit 1
fi
# Defensive nohup shim — some launch contexts (stripped-PATH bashes) lack /usr/bin.
command -v nohup >/dev/null 2>&1 || nohup() { "$@"; }

echo "[CLARA] Starting full stack..."
# NO `source activate` — the Windows venv's activate writes a WINDOWS-style path into PATH
# ("E:\...\Scripts:..."), and bash splits PATH on ":" so the drive letter becomes a bogus
# entry and command lookup goes NONDETERMINISTIC (2026-07-08: nohup "not found" on some lines,
# found on others, varying per launch context). The project rule applies here too: call the
# venv python by ABSOLUTE PATH, never activate.

# 1) Backend (FastAPI + WebSocket, port 8001)
nohup "$PY" "$SCRIPT_DIR/api.py" > "$SCRIPT_DIR/api.log" 2>&1 &
echo "$!" > "$SCRIPT_DIR/clara_backend.pid"
echo "[CLARA] Backend started (PID $(cat "$SCRIPT_DIR/clara_backend.pid")) -> api.log"

# 2) WhatsApp watcher (read-only) — MUST run from whatsapp_service/ so whatsapp-web.js
#    finds its saved .wwebjs_auth session (LocalAuth uses a CWD-relative path).
if [ -f "$WHATSAPP_DIR/whatsapp_clara.js" ] && command -v node >/dev/null 2>&1; then
    ( cd "$WHATSAPP_DIR" && nohup node whatsapp_clara.js > "$SCRIPT_DIR/whatsapp.log" 2>&1 & echo "$!" > "$SCRIPT_DIR/clara_whatsapp.pid" )
    echo "[CLARA] WhatsApp watcher started (PID $(cat "$SCRIPT_DIR/clara_whatsapp.pid")) -> whatsapp.log"
else
    echo "[CLARA] WhatsApp watcher SKIPPED (whatsapp_service/whatsapp_clara.js or node missing)."
fi

# 3) F10 hotkey listener (own-mic-on-press push-to-talk -> /voice_query)
if [ -f "$SCRIPT_DIR/hotkey_listener.py" ]; then
    nohup "$PY" "$SCRIPT_DIR/hotkey_listener.py" > "$SCRIPT_DIR/hotkey.log" 2>&1 &
    echo "$!" > "$SCRIPT_DIR/clara_hotkey.pid"
    echo "[CLARA] Hotkey listener started (PID $(cat "$SCRIPT_DIR/clara_hotkey.pid")) -> hotkey.log"
else
    echo "[CLARA] Hotkey listener SKIPPED (hotkey_listener.py missing)."
fi

# 4) Frontend (Vite dev, port 5173) — npm's sh-shim directly. NOT `cmd /c`: Git Bash's
# MSYS path conversion mangles `/c` into `C:\`, so cmd got a bogus arg and sat at an
# interactive prompt — vite never launched (2026-07-08; the log was a bare cmd banner).
( cd "$INTERFACE_DIR" && nohup npm run dev > "$SCRIPT_DIR/frontend.log" 2>&1 & echo "$!" > "$SCRIPT_DIR/clara_frontend.pid" )
echo "[CLARA] Frontend started (PID $(cat "$SCRIPT_DIR/clara_frontend.pid")) -> frontend.log"

echo "[CLARA] Full stack running (detached — no terminal windows)."
echo "[CLARA]   Watch live output:  bash watch_clara.sh   (or: bash watch_clara.sh whatsapp)"
echo "[CLARA]   Stop everything:    bash stop_clara.sh"
