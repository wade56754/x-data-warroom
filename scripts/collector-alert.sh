#!/bin/bash
# collector-alert.sh — x-data-collector health check + Telegram alert
# Triggered every 600s by launchd/cron healthcheck scheduler.
#
# Health check: data.json mtime must be <= 5400s (90 min) old
# Sends one Telegram alert after 3 consecutive failures (avoids spam)

set -euo pipefail

DATA_DIR="${X_DATA_DIR:-${HOME}/.x-data}"
ENV_FILE="${DATA_DIR}/.env"
DATA_FILE="${TWEET_GROWTH_DATA:-${DATA_DIR}/data.json}"
STATE_DIR="${DATA_DIR}"
FAIL_COUNT_FILE="${STATE_DIR}/collector-consecutive-fail-count"
STALE_THRESHOLD=5400   # 秒（90 分钟）
FAIL_THRESHOLD=3

mkdir -p "${STATE_DIR}"

# ─── 健康检查 ─────────────────────────────────────────────────────────────────
is_healthy() {
    if [ ! -f "${DATA_FILE}" ]; then
        echo "[FAIL] 数据文件不存在: ${DATA_FILE}" >&2
        return 1
    fi

    # macOS: stat -f %m 返回 mtime（秒级 epoch）
    MTIME="$(stat -f %m "${DATA_FILE}")"
    NOW="$(date +%s)"
    AGE=$(( NOW - MTIME ))

    if [ "${AGE}" -gt "${STALE_THRESHOLD}" ]; then
        echo "[FAIL] 数据文件 mtime 过期：${AGE}s 前（阈值 ${STALE_THRESHOLD}s）" >&2
        return 1
    fi

    echo "[OK] 数据文件新鲜：${AGE}s 前更新" >&2
    return 0
}

# ─── 加载 Telegram 凭证 ───────────────────────────────────────────────────────
load_env() {
    if [ ! -f "${ENV_FILE}" ]; then
        echo "[ERROR] 找不到 env 文件: ${ENV_FILE}" >&2
        exit 1
    fi
    set -a
    # shellcheck disable=SC1090
    source "${ENV_FILE}"
    set +a
}

# ─── 发送 Telegram 告警 ───────────────────────────────────────────────────────
send_telegram_alert() {
    local age_info="$1"
    load_env

    BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
    CHANNEL="${TELEGRAM_HOME_CHANNEL:-}"

    if [ -z "${BOT_TOKEN}" ] || [ -z "${CHANNEL}" ]; then
        echo "[ERROR] Telegram 凭证未设置（TELEGRAM_BOT_TOKEN / TELEGRAM_HOME_CHANNEL）" >&2
        return 1
    fi

    MSG="[x-data-collector] 健康检查告警
数据文件超过 ${STALE_THRESHOLD}s 未更新。
${age_info}
数据文件: ${DATA_FILE}
时间: $(date '+%Y-%m-%d %H:%M:%S')"

    PAYLOAD="$(python3 -c "
import json, sys
msg = sys.stdin.read().rstrip()
print(json.dumps({'chat_id': '${CHANNEL}', 'text': msg}))
" <<< "${MSG}")"

    HTTP_CODE="$(curl -sS -o /dev/null -w '%{http_code}' \
        -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
        -H "Content-Type: application/json" \
        -d "${PAYLOAD}")"

    if [ "${HTTP_CODE}" = "200" ]; then
        echo "[OK] Telegram 告警已发送（HTTP ${HTTP_CODE}）" >&2
    else
        echo "[WARN] Telegram 告警发送失败（HTTP ${HTTP_CODE}）" >&2
    fi
}

# ─── 主逻辑 ───────────────────────────────────────────────────────────────────

# 读取当前失败计数
COUNT=0
if [ -f "${FAIL_COUNT_FILE}" ]; then
    COUNT="$(cat "${FAIL_COUNT_FILE}" | tr -d '[:space:]')"
    COUNT="${COUNT:-0}"
fi

if is_healthy; then
    # 恢复正常：重置计数器
    echo "0" > "${FAIL_COUNT_FILE}"
    exit 0
fi

# 记录失败详情用于告警消息
if [ -f "${DATA_FILE}" ]; then
    MTIME="$(stat -f %m "${DATA_FILE}")"
    NOW="$(date +%s)"
    AGE=$(( NOW - MTIME ))
    AGE_INFO="当前 mtime 距现在: ${AGE}s"
else
    AGE_INFO="数据文件不存在"
fi

# 递增失败计数
COUNT=$(( COUNT + 1 ))
echo "${COUNT}" > "${FAIL_COUNT_FILE}"
echo "[FAIL] 连续失败计数: ${COUNT}/${FAIL_THRESHOLD}" >&2

if [ "${COUNT}" -lt "${FAIL_THRESHOLD}" ]; then
    # 还没到阈值，等待
    exit 1
elif [ "${COUNT}" -gt "${FAIL_THRESHOLD}" ]; then
    # 超过阈值，已告警过，不重复发
    echo "[SUPPRESS] 已告警，不重复发送（计数=${COUNT}）" >&2
    exit 1
else
    # 恰好到阈值，发告警
    echo "[ALERT] 连续 ${FAIL_THRESHOLD} 次失败，发送 Telegram 告警" >&2
    send_telegram_alert "${AGE_INFO}"
    exit 1
fi
