#!/bin/bash
# Stop CLARA backend + frontend using saved PIDs

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

stop_pid() {
    local pidfile="$1"
    local name="$2"
    if [ -f "$pidfile" ]; then
        PID=$(cat "$pidfile")
        if taskkill //PID "$PID" //F > /dev/null 2>&1; then
            echo "[CLARA] $name stopped (PID $PID)"
        else
            echo "[CLARA] $name was not running (PID $PID)"
        fi
        rm "$pidfile"
    else
        echo "[CLARA] No PID file for $name"
    fi
}

stop_pid "$SCRIPT_DIR/clara_backend.pid" "Backend"
stop_pid "$SCRIPT_DIR/clara_frontend.pid" "Frontend"
