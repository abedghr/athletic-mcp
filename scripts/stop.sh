#!/usr/bin/env bash
# Stop the Athlete Training API (background process).

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_FILE="$PROJECT_ROOT/logs/api.pid"
API_PORT="${ATHLETE_API_PORT:-8000}"

GREEN=$'\033[92m'
RED=$'\033[91m'
YELLOW=$'\033[93m'
BLUE=$'\033[94m'
RESET=$'\033[0m'

info()  { echo "${BLUE}[INFO]${RESET} $*"; }
ok()    { echo "${GREEN}[ OK ]${RESET} $*"; }
warn()  { echo "${YELLOW}[WARN]${RESET} $*"; }

echo "Athlete Training — Stop"
echo

STOPPED=0

if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        info "Stopping API (pid $PID)..."
        kill "$PID"
        # Wait up to 5 seconds
        for i in 1 2 3 4 5; do
            if ! kill -0 "$PID" 2>/dev/null; then break; fi
            sleep 1
        done
        if kill -0 "$PID" 2>/dev/null; then
            warn "Graceful shutdown timed out, forcing..."
            kill -9 "$PID" 2>/dev/null || true
        fi
        ok "API stopped"
        STOPPED=1
    else
        warn "Pid file exists but process $PID is not running"
    fi
    rm -f "$PID_FILE"
fi

# Fallback: find any process on port 8000
if [ "$STOPPED" -eq 0 ] && lsof -i ":$API_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    FALLBACK_PID=$(lsof -ti ":$API_PORT" -sTCP:LISTEN | head -1)
    info "Stopping fallback process on port $API_PORT (pid $FALLBACK_PID)..."
    kill "$FALLBACK_PID" 2>/dev/null || true
    sleep 1
    if kill -0 "$FALLBACK_PID" 2>/dev/null; then
        kill -9 "$FALLBACK_PID" 2>/dev/null || true
    fi
    ok "Process stopped"
    STOPPED=1
fi

if [ "$STOPPED" -eq 0 ]; then
    info "Nothing to stop — API was not running"
fi
