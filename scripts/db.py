#!/usr/bin/env python3
"""
db.py — Supabase Postgres shared write module

Provides:
  get_conn()           -> psycopg3 connection, returns None on failure (no raise)
  upsert_tweet()       -> INSERT ... ON CONFLICT DO UPDATE tweets table
  insert_sample()      -> INSERT ... ON CONFLICT DO NOTHING tweet_samples table

On failure all functions:
  - print [WARN] to stderr
  - return False / None
  - never raise to the caller

Environment variables:
  SUPABASE_DB_URL  — PostgreSQL connection URL
  X_DATA_DIR       — data directory containing .env (default: ~/.x-data/)
  Loaded from $X_DATA_DIR/.env first, then os.environ
"""

import os
import sys
from pathlib import Path
from typing import Optional


# ─── .env loading ───────────────────────────────────────────────────────────

def _load_env() -> None:
    """Load env vars from $X_DATA_DIR/.env (does not overwrite existing vars)."""
    _data_dir = Path(os.environ.get("X_DATA_DIR", Path.home() / ".x-data"))
    env_file = _data_dir / ".env"
    if not env_file.exists():
        return
    try:
        with open(env_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                os.environ.setdefault(k, v)
    except Exception as e:
        print(f"[WARN] db: 加载 .env 失败: {e}", file=sys.stderr)


# ─── 连接 ────────────────────────────────────────────────────────────────────

def get_conn():
    """
    返回 psycopg3 连接对象，失败返回 None。
    调用方负责 conn.close()。
    """
    try:
        _load_env()
        url = os.environ.get("SUPABASE_DB_URL", "").strip()
        if not url:
            print("[WARN] db: SUPABASE_DB_URL 未设置，跳过 DB 写入", file=sys.stderr)
            return None
        import psycopg  # psycopg3
        conn = psycopg.connect(url)
        return conn
    except Exception as e:
        print(f"[WARN] db: 连接失败: {e}", file=sys.stderr)
        return None


# ─── 写入 ────────────────────────────────────────────────────────────────────

def _parse_twitter_ts(value):
    """解析 Twitter 的 'Wed Apr 29 13:03:25 +0000 2026' 或 ISO 8601；返回 datetime 或 None。"""
    if value is None or value == "":
        return None
    if hasattr(value, "tzinfo"):
        return value
    from datetime import datetime
    text = str(value).strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        pass
    try:
        return datetime.strptime(text, "%a %b %d %H:%M:%S %z %Y")
    except ValueError:
        return None


def upsert_tweet(conn, tweet_id: str, label: str, text: str,
                 created_at=None, url: str = None) -> bool:
    """INSERT ... ON CONFLICT DO UPDATE tweets 表。失败返回 False，不抛。

    created_at 接受 datetime 或 Twitter / ISO 字符串；url 可选。
    COALESCE 防止重跑时 NULL 覆盖既有值。
    """
    try:
        ca = _parse_twitter_ts(created_at)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO tweets (tweet_id, label, text, created_at, url)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (tweet_id) DO UPDATE
                  SET label      = EXCLUDED.label,
                      text       = EXCLUDED.text,
                      created_at = COALESCE(EXCLUDED.created_at, tweets.created_at),
                      url        = COALESCE(EXCLUDED.url, tweets.url)
                """,
                (tweet_id, label, text, ca, url),
            )
        conn.commit()
        return True
    except Exception as e:
        print(f"[WARN] db: upsert_tweet({tweet_id}) 失败: {e}", file=sys.stderr)
        try:
            conn.rollback()
        except Exception:
            pass
        return False


def insert_sample(conn, tweet_id: str, snap: dict) -> bool:
    """
    INSERT ... ON CONFLICT (tweet_id, sampled_at) DO NOTHING tweet_samples 表。
    snap 必须含 'ts' 字段（ISO 8601 字符串）。
    失败返回 False，不抛出。
    """
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO samples
                  (tweet_id, sampled_at, views, likes, retweets, bookmarks, replies)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (tweet_id, sampled_at) DO NOTHING
                """,
                (
                    tweet_id,
                    snap["ts"],
                    snap.get("views", 0),
                    snap.get("likes", 0),
                    snap.get("retweets", 0),
                    snap.get("bookmarks", 0),
                    snap.get("replies", 0),
                ),
            )
        conn.commit()
        return True
    except Exception as e:
        print(f"[WARN] db: insert_sample({tweet_id}) 失败: {e}", file=sys.stderr)  # noqa: E501
        try:
            conn.rollback()
        except Exception:
            pass
        return False


# ─── 自测 ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("[db self-test] 加载 .env ...")
    _load_env()
    url = os.environ.get("SUPABASE_DB_URL", "")
    if not url:
        print("[db self-test] SUPABASE_DB_URL 未设置 — 跳过连接测试")
        sys.exit(0)

    print(f"[db self-test] 连接 DB（URL 前缀: {url[:30]}...）")
    conn = get_conn()
    if conn is None:
        print("[db self-test] 连接失败，见上方 [WARN]")
        sys.exit(1)

    print("[db self-test] 连接成功，测试 upsert_tweet ...")
    ok = upsert_tweet(conn, "_test_tweet_id_db_self_test", "self-test", "db.py self-test text")
    print(f"[db self-test] upsert_tweet → {ok}")

    print("[db self-test] 测试 insert_sample ...")
    import datetime
    snap = {
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "views": 1, "likes": 0, "retweets": 0, "bookmarks": 0, "replies": 0,
    }
    ok2 = insert_sample(conn, "_test_tweet_id_db_self_test", snap)
    print(f"[db self-test] insert_sample → {ok2}")

    conn.close()
    print("[db self-test] PASS")
