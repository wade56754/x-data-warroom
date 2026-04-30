"""One-time migration: $X_DATA_DIR/data.json -> Supabase Postgres.

Usage:
    cd /path/to/x-data-warroom
    uv venv .venv && source .venv/bin/activate
    uv pip install 'psycopg[binary]>=3.2'
    set -a; source ~/.x-data/.env; set +a
    python3 migrations/migrate_json_to_supabase.py [--dry-run] [--force]

Idempotent:
    tweets  table: ON CONFLICT (tweet_id) DO UPDATE
    samples table: ON CONFLICT (tweet_id, sampled_at) DO NOTHING
    Safe to re-run without creating duplicates.

Prerequisites:
    - 001_init_schema.sql already applied (psql -f or supabase MCP execute_sql)
    - SUPABASE_DB_URL set in ~/.x-data/.env (or exported in shell)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import psycopg  # type: ignore[import-not-found]
except ImportError:
    sys.exit("[FAIL] 需要 psycopg3，请先在 venv 内: uv pip install 'psycopg[binary]>=3.2'")


_data_dir = Path(os.environ.get("X_DATA_DIR", Path.home() / ".x-data"))
DEFAULT_JSON = Path(os.environ.get("TWEET_GROWTH_DATA", _data_dir / "data.json"))
TWITTER_TS_FMT = "%a %b %d %H:%M:%S %z %Y"
ACCOUNT = os.environ.get("X_SCREEN_NAME", "mytwitter")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data-file", default=str(DEFAULT_JSON), help="JSON 数据文件路径")
    p.add_argument("--dry-run", action="store_true", help="只打印统计不写库")
    p.add_argument("--force", action="store_true", help="即使 tweets 表已有数据也强制 upsert")
    return p.parse_args()


def parse_dt(value: Any) -> datetime | None:
    """解析两种格式：Twitter created_at 'Tue Apr 28 12:26:20 +0000 2026' / ISO 8601."""
    if value is None or value == "":
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        pass
    try:
        return datetime.strptime(str(value).strip(), TWITTER_TS_FMT)
    except ValueError:
        return None


def to_int(value: Any) -> int:
    if value is None or value == "":
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip().replace(",", "")
    multiplier = 1
    if text.lower().endswith("k"):
        multiplier, text = 1_000, text[:-1]
    elif text.lower().endswith("m"):
        multiplier, text = 1_000_000, text[:-1]
    try:
        return int(float(text) * multiplier)
    except ValueError:
        return 0


def collect_tweet_rows(data: dict[str, Any]) -> list[tuple[str, str | None, str | None, datetime | None, str, bool]]:
    """每条推 → (tweet_id, text, label, created_at, url, is_deleted)."""
    rows: list[tuple[str, str | None, str | None, datetime | None, str, bool]] = []
    for tweet_id, record in data.get("tweets", {}).items():
        if not isinstance(record, dict):
            continue
        text = record.get("text")
        # A2 backfill 在 18 条媒体推/RT 上把 FxTwitter 的 nested dict 整个塞进了 text
        # 防御：如果 text 是 dict，解包内层 text 字段；保持媒体推 https://t.co/* 短链如实存储
        if isinstance(text, dict):
            text = text.get("text")
        label = record.get("label")
        latest = record.get("latest") if isinstance(record.get("latest"), dict) else {}
        created_raw = latest.get("created_at") if latest else None
        if not created_raw:
            history = record.get("history") if isinstance(record.get("history"), list) else []
            for sample in history:
                if isinstance(sample, dict) and sample.get("created_at"):
                    created_raw = sample["created_at"]
                    break
        created_at = parse_dt(created_raw)
        url = record.get("url") or f"https://x.com/{ACCOUNT}/status/{tweet_id}"
        is_deleted = bool(record.get("is_deleted", False))
        rows.append((str(tweet_id), text, label, created_at, url, is_deleted))
    return rows


def collect_sample_rows(data: dict[str, Any]) -> list[tuple[str, datetime, int, int, int, int, int]]:
    """history + latest → (tweet_id, sampled_at, views, likes, replies, retweets, bookmarks)."""
    rows: list[tuple[str, datetime, int, int, int, int, int]] = []
    seen: set[tuple[str, datetime]] = set()
    for tweet_id, record in data.get("tweets", {}).items():
        if not isinstance(record, dict):
            continue
        history = record.get("history") if isinstance(record.get("history"), list) else []
        samples = list(history)
        latest = record.get("latest") if isinstance(record.get("latest"), dict) else None
        if latest:
            samples.append(latest)
        for sample in samples:
            if not isinstance(sample, dict):
                continue
            sampled_at = parse_dt(sample.get("ts") or sample.get("sampled_at"))
            if sampled_at is None:
                continue
            if sampled_at.tzinfo is None:
                sampled_at = sampled_at.replace(tzinfo=timezone.utc)
            key = (str(tweet_id), sampled_at)
            if key in seen:
                continue
            seen.add(key)
            rows.append((
                str(tweet_id), sampled_at,
                to_int(sample.get("views")),
                to_int(sample.get("likes")),
                to_int(sample.get("replies")),
                to_int(sample.get("retweets")),
                to_int(sample.get("bookmarks")),
            ))
    return rows


def main() -> int:
    args = parse_args()
    db_url = os.environ.get("SUPABASE_DB_URL")
    if not db_url:
        sys.exit("[FAIL] SUPABASE_DB_URL not set. Run: set -a; source ~/.x-data/.env; set +a")

    data_file = Path(args.data_file).expanduser()
    if not data_file.exists():
        sys.exit(f"[FAIL] 数据文件不存在: {data_file}")

    print(f"[INFO] 加载 {data_file} ...")
    data = json.loads(data_file.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "tweets" not in data:
        sys.exit("[FAIL] JSON 根不是 dict 或缺 tweets 字段")

    tweet_rows = collect_tweet_rows(data)
    sample_rows = collect_sample_rows(data)
    print(f"[INFO] 待迁移: {len(tweet_rows)} 条推 / {len(sample_rows)} 个 samples")

    if args.dry_run:
        if tweet_rows:
            print(f"[DRY-RUN] 第 1 条 tweet 示例: {tweet_rows[0]}")
        if sample_rows:
            print(f"[DRY-RUN] 第 1 个 sample 示例: {sample_rows[0]}")
        print("[DRY-RUN] 不写库，退出。")
        return 0

    print(f"[INFO] 连接 Supabase ...")
    with psycopg.connect(db_url, autocommit=False) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM tweets")
            row = cur.fetchone()
            existing = row[0] if row else 0
            if existing > 0 and not args.force:
                print(f"[WARN] tweets 表已有 {existing} 行；使用 --force 强制 upsert，或先 TRUNCATE")
                return 1

            cur.executemany(
                """
                INSERT INTO tweets (tweet_id, text, label, created_at, url, is_deleted)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (tweet_id) DO UPDATE SET
                    text = EXCLUDED.text,
                    label = EXCLUDED.label,
                    created_at = EXCLUDED.created_at,
                    url = EXCLUDED.url,
                    is_deleted = EXCLUDED.is_deleted
                """,
                tweet_rows,
            )
            print(f"[OK] tweets upsert 完成: {len(tweet_rows)} 行")

            cur.executemany(
                """
                INSERT INTO samples (tweet_id, sampled_at, views, likes, replies, retweets, bookmarks)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (tweet_id, sampled_at) DO NOTHING
                """,
                sample_rows,
            )
            print(f"[OK] samples 插入完成: {len(sample_rows)} 行")

            cur.execute("SELECT COUNT(*) FROM tweets")
            row = cur.fetchone()
            t_count = row[0] if row else 0
            cur.execute("SELECT COUNT(*) FROM samples")
            row = cur.fetchone()
            s_count = row[0] if row else 0
            print(f"[VERIFY] DB 现有: tweets={t_count} / samples={s_count}")

        conn.commit()
    print("[DONE] 迁移完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
