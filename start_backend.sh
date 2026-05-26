#!/bin/bash
# Start CLARA backend only — no frontend.
# Used by the daily test harness and remote dispatch.

SCRIPT_DIR="/e/ML PROJECTS/AGENT_ZERO"
VENV="$SCRIPT_DIR/jarvis_v2/Scripts/activate"

echo "[CLARA] Starting backend..."

source "$VENV"
nohup python "$SCRIPT_DIR/api.py" > "$SCRIPT_DIR/api.log" 2>&1 &
BACKEND_PID=$!
echo "$BACKEND_PID" > "$SCRIPT_DIR/clara_backend.pid"

echo "[CLARA] Backend started (PID $BACKEND_PID) → api.log"
