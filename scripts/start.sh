#!/usr/bin/env bash
# Start the Athlete Training API in the background.
# Prerequisites: Python 3.11+, dependencies installed via `pip install -e .`

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOGS_DIR="$PROJECT_ROOT/logs"
PID_FILE="$LOGS_DIR/api.pid"
LOG_FILE="$LOGS_DIR/api.log"
ATHLETE_DIR="$HOME/.athlete"
API_PORT="${ATHLETE_API_PORT:-8000}"

GREEN=$'\033[92m'
RED=$'\033[91m'
YELLOW=$'\033[93m'
BLUE=$'\033[94m'
BOLD=$'\033[1m'
RESET=$'\033[0m'

info()  { echo "${BLUE}[INFO]${RESET} $*"; }
ok()    { echo "${GREEN}[ OK ]${RESET} $*"; }
warn()  { echo "${YELLOW}[WARN]${RESET} $*"; }
fail()  { echo "${RED}[FAIL]${RESET} $*"; exit 1; }

echo "${BOLD}Athlete Training — Startup${RESET}"
echo

# 1. Check Python version
info "Checking Python version..."
if ! command -v python3 >/dev/null 2>&1; then
    fail "python3 not found on PATH"
fi
PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PY_MAJOR=$(python3 -c 'import sys; print(sys.version_info.major)')
PY_MINOR=$(python3 -c 'import sys; print(sys.version_info.minor)')
if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 11 ]; }; then
    fail "Python 3.11+ required, found $PY_VERSION"
fi
ok "Python $PY_VERSION"

# 2. Check virtualenv (warn only)
if [ -z "${VIRTUAL_ENV:-}" ]; then
    warn "No virtualenv active. Using system Python: $(which python3)"
else
    ok "Virtualenv: $VIRTUAL_ENV"
fi

# 3. Verify athlete_mcp package is importable
info "Checking athlete_mcp package..."
if ! python3 -c "import athlete_mcp" 2>/dev/null; then
    fail "athlete_mcp package not installed. Run: pip install -e ."
fi
ok "athlete_mcp package importable"

# 4. Check port 8000 is free
info "Checking port $API_PORT..."
if lsof -i ":$API_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    EXISTING_PID=$(lsof -ti ":$API_PORT" -sTCP:LISTEN | head -1)
    fail "Port $API_PORT already in use (pid: $EXISTING_PID). Stop it with: bash scripts/stop.sh"
fi
ok "Port $API_PORT is free"

# 5. Ensure directories exist
mkdir -p "$ATHLETE_DIR"
mkdir -p "$LOGS_DIR"
ok "Directories ready: $ATHLETE_DIR, $LOGS_DIR"

# 6. Start FastAPI in background
info "Starting FastAPI server..."
cd "$PROJECT_ROOT"
nohup python3 scripts/run_api.py > "$LOG_FILE" 2>&1 &
API_PID=$!
echo "$API_PID" > "$PID_FILE"
info "API started with pid $API_PID (logs: $LOG_FILE)"

# 7. Wait for API to become healthy
info "Waiting for API to become healthy..."
HEALTHY=0
for i in $(seq 1 15); do
    if curl -s "http://localhost:$API_PORT/health" >/dev/null 2>&1; then
        HEALTHY=1
        break
    fi
    sleep 1
done

if [ "$HEALTHY" -ne 1 ]; then
    warn "API did not respond in 15s. Check $LOG_FILE"
    fail "API startup failed"
fi

echo
ok "${BOLD}API ready at http://localhost:$API_PORT${RESET}"
ok "${BOLD}Swagger UI at http://localhost:$API_PORT/docs${RESET}"
ok "Now open Claude Desktop — MCP servers will connect automatically"
echo
info "To stop: bash scripts/stop.sh"
info "Tail logs: tail -f $LOG_FILE"
