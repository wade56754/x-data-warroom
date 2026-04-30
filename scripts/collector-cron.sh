#!/bin/bash
# collector-cron.sh — x-data-collector cron entry point
# Triggered every 30 minutes by the launchd/cron scheduler.
#
# Run order:
#   1. auto_discover.py              — discover new tweets
#   2. tweet_growth_cli.py --run --fast  — sample (fast mode for new tweets)
#
# Appends a JSON log line to $X_DATA_DIR/collector.log on each run.

set -euo pipefail

# Data directory — set X_DATA_DIR to override (default: ~/.x-data/)
DATA_DIR="${X_DATA_DIR:-${HOME}/.x-data}"

# Load .env (contains SUPABASE_DB_URL, etc.), silently skip if missing
set -a; source "${DATA_DIR}/.env" 2>/dev/null || true; set +a

# Data file: $TWEET_GROWTH_DATA overrides; default to data.json in DATA_DIR
export TWEET_GROWTH_DATA="${TWEET_GROWTH_DATA:-${DATA_DIR}/data.json}"

# Screen name: $X_SCREEN_NAME overrides; default falls through to auto_discover default
export X_SCREEN_NAME="${X_SCREEN_NAME:-mytwitter}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Use venv python (includes psycopg3 and other deps)
PYTHON="${SCRIPT_DIR}/../.venv/bin/python"

LOG_FILE="${DATA_DIR}/collector.log"
mkdir -p "$(dirname "${LOG_FILE}")"

RAN_AT="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
COMMANDS=()
OVERALL_OK=true

# ─── Step 1: auto_discover ────────────────────────────────────────────────────
CMD1_START="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
CMD1_LOG=""
if "${PYTHON}" auto_discover.py --max-age 48 2>&1; then
    CMD1_STATUS="ok"
else
    CMD1_STATUS="error"
    OVERALL_OK=false
fi

COMMANDS+=("{\"cmd\":\"auto_discover\",\"status\":\"${CMD1_STATUS}\"}")

# ─── Step 2: tweet_growth_cli --run --fast ────────────────────────────────────
if "${PYTHON}" tweet_growth_cli.py --run --fast 2>&1; then
    CMD2_STATUS="ok"
else
    CMD2_STATUS="error"
    OVERALL_OK=false
fi

COMMANDS+=("{\"cmd\":\"tweet_growth_cli --run --fast\",\"status\":\"${CMD2_STATUS}\"}")

# ─── JSON ログ行を追記 ─────────────────────────────────────────────────────────
CMDS_JSON="[$(IFS=,; echo "${COMMANDS[*]}")]"

if [ "${OVERALL_OK}" = "true" ]; then
    OK_VAL="true"
else
    OK_VAL="false"
fi

LOG_LINE="{\"ok\":${OK_VAL},\"ran_at\":\"${RAN_AT}\",\"commands\":${CMDS_JSON}}"
echo "${LOG_LINE}" >> "${LOG_FILE}"

# ─── 标准输出（launchd stderr 会捕获）────────────────────────────────────────
echo "[$(date '+%Y-%m-%d %H:%M:%S')] collector-cron finished: ok=${OK_VAL}" >&2

exit 0
