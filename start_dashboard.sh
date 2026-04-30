#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
PORT="${DASHBOARD_PORT:-8787}"
VENV_PYTHON="${ROOT}/.venv/bin/python"
SERVER="${ROOT}/web/server.py"
LOGFILE="${ROOT}/dashboard.log"

# --- kill existing server on port ---
existing=$(lsof -ti tcp:${PORT} 2>/dev/null || true)
if [[ -n "$existing" ]]; then
  echo "Killing existing process on port ${PORT}: PID ${existing}"
  kill "$existing" 2>/dev/null || true
  sleep 1
fi

# --- sanity checks ---
if [[ ! -x "$VENV_PYTHON" ]]; then
  echo "ERROR: venv python not found at ${VENV_PYTHON}" >&2
  echo "Run: cd \"${ROOT}\" && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
  echo "Or:  uv venv .venv && uv pip install -r requirements.txt" >&2
  exit 1
fi

if [[ ! -f "$SERVER" ]]; then
  echo "ERROR: server not found at ${SERVER}" >&2
  exit 1
fi

# --- launch ---
echo "Starting dashboard with venv python on port ${PORT}..."
cd "$ROOT"
nohup "$VENV_PYTHON" web/server.py --port "$PORT" > "$LOGFILE" 2>&1 &
SERVER_PID=$!
echo "Launched PID ${SERVER_PID}, log: ${LOGFILE}"

# --- health check ---
for i in 1 2 3 4 5; do
  sleep 1
  if curl -sf "http://127.0.0.1:${PORT}/api/status" > /dev/null 2>&1; then
    echo "Dashboard ready: http://127.0.0.1:${PORT}"
    echo "  Data view:   http://127.0.0.1:${PORT}/"
    echo "  Insights:    http://127.0.0.1:${PORT}/static/insights.html"
    exit 0
  fi
  echo "Waiting for server... (attempt ${i}/5)"
done

echo "WARNING: Server did not respond within 5s. Check ${LOGFILE}" >&2
exit 1
