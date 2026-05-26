#!/bin/bash
# Start CLARA backend + frontend, detached from terminal (survives session close)
# Usage: bash start_clara.sh
# Logs: api.log and frontend.log in project root

SCRIPT_DIR="/e/ML PROJECTS/AGENT_ZERO"
VENV="$SCRIPT_DIR/jarvis_v2/Scripts/activate"
INTERFACE_DIR="$SCRIPT_DIR/interface"

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
