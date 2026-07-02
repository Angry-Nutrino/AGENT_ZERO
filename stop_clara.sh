#!/bin/bash
# Stop the FULL CLARA stack — backend + WhatsApp watcher + F10 hotkey + frontend.
# PID files first; command-line search as a fallback for manual starts.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

stop_backend() {
    local pidfile="$SCRIPT_DIR/clara_backend.pid"
    if [ -f "$pidfile" ]; then
        PID=$(cat "$pidfile")
        echo "[CLARA] Stopping backend (PID $PID)..."
        # //T kills the tree too — the backend spawns MCP subprocesses (node DC, markitdown).
        taskkill //PID "$PID" //T //F > /dev/null 2>&1
        rm -f "$pidfile"
        echo "[CLARA] Backend stopped."
    else
        echo "[CLARA] No backend PID file — searching for api.py..."
        powershell.exe -NoProfile -Command "
            \$procs = Get-WmiObject Win32_Process | Where-Object { \$_.Name -like 'python*' -and \$_.CommandLine -like '*api.py*' }
            if (\$procs) { \$procs | ForEach-Object { \$_ | Invoke-WmiMethod -Name Terminate | Out-Null }; Write-Output 'killed' }
            else { Write-Output 'not_found' }
        " 2>/dev/null | grep -q killed && echo "[CLARA] Backend stopped (by search)." || echo "[CLARA] Backend was not running."
    fi
}

# Generic stop for a PID-file-tracked process, with a command-line fallback.
stop_tracked() {
    local label="$1" pidfile="$SCRIPT_DIR/$2" cmdgrep="$3"
    if [ -f "$pidfile" ]; then
        PID=$(cat "$pidfile")
        if taskkill //PID "$PID" //T //F > /dev/null 2>&1; then
            echo "[CLARA] $label stopped (PID $PID)"
        else
            echo "[CLARA] $label not running (PID $PID)"
        fi
        rm -f "$pidfile"
    else
        powershell.exe -NoProfile -Command "
            \$procs = Get-WmiObject Win32_Process | Where-Object { \$_.CommandLine -like '*$cmdgrep*' }
            if (\$procs) { \$procs | ForEach-Object { \$_ | Invoke-WmiMethod -Name Terminate | Out-Null }; Write-Output 'killed' }
            else { Write-Output 'not_found' }
        " 2>/dev/null | grep -q killed && echo "[CLARA] $label stopped (by search)" || echo "[CLARA] $label: no PID file / not running"
    fi
}

stop_backend
stop_tracked "WhatsApp watcher" "clara_whatsapp.pid" "whatsapp_clara.js"
stop_tracked "Hotkey listener"  "clara_hotkey.pid"   "hotkey_listener.py"
stop_tracked "Frontend"         "clara_frontend.pid" "npm run dev"

echo "[CLARA] Stack stopped."
