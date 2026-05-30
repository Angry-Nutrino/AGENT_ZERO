#!/bin/bash
# Stop CLARA backend + frontend using saved PIDs, with WMI fallback for manual starts

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

stop_backend() {
    local pidfile="$SCRIPT_DIR/clara_backend.pid"

    if [ -f "$pidfile" ]; then
        PID=$(cat "$pidfile")
        echo "[CLARA] Stopping backend (PID $PID from PID file)..."
        powershell.exe -NoProfile -Command "
            \$result = Get-WmiObject Win32_Process -Filter 'ProcessId=$PID' | Invoke-WmiMethod -Name Terminate
            if (\$result.ReturnValue -eq 0) {
                Write-Output 'killed'
            } else {
                Write-Output 'failed'
            }
        " 2>/dev/null
        rm -f "$pidfile"
        echo "[CLARA] Backend stopped."
    else
        echo "[CLARA] No PID file found — searching for running api.py process..."
        RESULT=$(powershell.exe -NoProfile -Command "
            \$procs = Get-WmiObject Win32_Process | Where-Object { \$_.Name -like 'python*' -and \$_.CommandLine -like '*api.py*' }
            if (\$procs) {
                \$procs | ForEach-Object {
                    Write-Output \"Found PID \$(\$_.ProcessId)\"
                    \$_ | Invoke-WmiMethod -Name Terminate | Out-Null
                }
                Write-Output 'killed'
            } else {
                Write-Output 'not_found'
            }
        " 2>/dev/null)
        echo "$RESULT"
        if echo "$RESULT" | grep -q "killed"; then
            echo "[CLARA] Backend stopped via process search."
        else
            echo "[CLARA] Backend was not running."
        fi
    fi
}

stop_frontend() {
    local pidfile="$SCRIPT_DIR/clara_frontend.pid"
    if [ -f "$pidfile" ]; then
        PID=$(cat "$pidfile")
        if taskkill //PID "$PID" //F > /dev/null 2>&1; then
            echo "[CLARA] Frontend stopped (PID $PID)"
        else
            echo "[CLARA] Frontend was not running (PID $PID)"
        fi
        rm -f "$pidfile"
    else
        echo "[CLARA] No PID file for Frontend"
    fi
}

stop_backend
stop_frontend
