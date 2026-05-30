#!/bin/bash
# Start CLARA backend + frontend, detached from terminal (survives session close)
# Usage: bash start_clara.sh
# Logs: api.log and frontend.log in project root

# Derive the script's own directory so this works regardless of where the repo
# lives or how the drive is mounted (Git Bash /e/..., not the same as WSL /mnt/e/...).
# The old hardcoded "/e/ML PROJECTS/AGENT_ZERO" broke when run from a shell that
# mounts the drive differently — every path resolved to "No such file or directory".
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$SCRIPT_DIR/jarvis_v2/Scripts/activate"
INTERFACE_DIR="$SCRIPT_DIR/interface"

# WSL cannot run this: jarvis_v2 is a Windows venv (CRLF activate + Windows-built
# binaries). The file exists under /mnt/e/... so a plain -f check passes, then
# `source` fails with $'\r' / syntax errors. Detect WSL explicitly and bail clearly.
if grep -qiE "microsoft|wsl" /proc/version 2>/dev/null; then
    echo "[CLARA] ERROR: You are running under WSL. The Windows venv (jarvis_v2) cannot be"
    echo "[CLARA] sourced from WSL. Start CLARA from one of these instead:"
    echo "[CLARA]   PowerShell:  .\\jarvis_v2\\Scripts\\python.exe -u api.py"
    echo "[CLARA]   Git Bash:    bash start_clara.sh"
    exit 1
fi

if [ ! -f "$VENV" ]; then
    echo "[CLARA] ERROR: venv activate not found at $VENV"
    echo "[CLARA] Expected a Windows venv at jarvis_v2/. Run from Git Bash or use PowerShell."
    exit 1
fi

echo "[CLARA] Starting..."

# Backend
source "$VENV"
nohup python "$SCRIPT_DIR/api.py" > "$SCRIPT_DIR/api.log" 2>&1 &
BACKEND_PID=$!
echo "[CLARA] Backend started (PID $BACKEND_PID) → api.log"

# Frontend — run via cmd /c to give Vite a proper shell context (nohup alone causes silent exit on Windows)
cd "$INTERFACE_DIR"
nohup cmd /c "npm run dev" > "$SCRIPT_DIR/frontend.log" 2>&1 &
FRONTEND_PID=$!
echo "[CLARA] Frontend started (PID $FRONTEND_PID) → frontend.log"

# Save PIDs so you can kill them later
echo "$BACKEND_PID" > "$SCRIPT_DIR/clara_backend.pid"
echo "$FRONTEND_PID" > "$SCRIPT_DIR/clara_frontend.pid"

echo "[CLARA] Both processes running. To stop: bash stop_clara.sh"
