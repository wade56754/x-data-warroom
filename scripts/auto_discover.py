#!/usr/bin/env python3
"""
auto_discover.py — Auto-discover new tweets and add them to the Growth Tracker.

Runs before each cron sample to check whether the tracked account has new
tweets (not yet in the DB) and automatically adds them to the tracking list.

Usage:
  python3 auto_discover.py                           # detect and add
  python3 auto_discover.py --dry-run                 # detect only, no writes
  python3 auto_discover.py --screen-name mytwitter   # specify account

Environment variables:
  TIKHUB_API_KEY   — TikHub API key (https://tikhub.io)
  X_SCREEN_NAME    — X account to track (default: mytwitter)
  X_DATA_DIR       — data directory (default: ~/.x-data/)
  ENV_FILE         — path to .env file (default: $X_DATA_DIR/.env)
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Load .env from $X_DATA_DIR/.env (or $ENV_FILE override), silently skip if missing
_data_dir = Path(os.environ.get("X_DATA_DIR", Path.home() / ".x-data"))
ENV_FILE = Path(os.environ.get("ENV_FILE", _data_dir / ".env"))
if ENV_FILE.exists():
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

# Local imports
sys.path.insert(0, os.path.dirname(__file__))
import tweet_growth as tg

TIKHUB_API_KEY = os.environ.get("TIKHUB_API_KEY", "")
DEFAULT_SCREEN_NAME = os.environ.get("X_SCREEN_NAME", "mytwitter")

TIKHUB_USER_TWEETS_URL = (
    "https://api.tikhub.io/api/v1/twitter/web/fetch_user_post_tweet"
    "?screen_name={screen_name}"
)


def fetch_latest_tweets(screen_name: str, max_pages: int = 1) -> list[dict]:
    """用 TikHub API 拉取账号最新推文列表（默认只拉第1页，约20条）"""
    if not TIKHUB_API_KEY:
        print("[ERROR] TIKHUB_API_KEY 未设置", file=sys.stderr)
        return []

    url = TIKHUB_USER_TWEETS_URL.format(screen_name=screen_name)
    all_tweets = []

    for page in range(max_pages):
        try:
            result = subprocess.run(
                ["curl", "-sS", "--connect-timeout", "10", "--max-time", "20",
                 "-H", f"Authorization: Bearer {TIKHUB_API_KEY}",
                 url],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode != 0:
                print(f"[ERROR] curl 失败: {result.stderr[:200]}", file=sys.stderr)
                break

            data = json.loads(result.stdout)
            api_data = data.get("data", {})
            timeline = api_data.get("timeline", [])

            if not timeline:
                break

            for t in timeline:
                # TikHub schema：直接 tweet_id / text；保留 id_str / full_text 兜底兼容
                tweet_id = t.get("tweet_id") or t.get("id_str") or str(t.get("id", ""))
                full_text = t.get("text") or t.get("full_text", "")
                created_at = t.get("created_at", "")

                # 解析发布时间
                try:
                    dt = datetime.strptime(created_at, "%a %b %d %H:%M:%S %z %Y")
                    age_hours = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
                except Exception:
                    age_hours = 999

                all_tweets.append({
                    "tweet_id": tweet_id,
                    "text": full_text,
                    "created_at": created_at,
                    "age_hours": age_hours,
                    "article": t.get("article"),
                    "media": t.get("media"),
                    "entities": t.get("entities"),
                })

            # 翻页
            next_cursor = api_data.get("next_cursor")
            if next_cursor and page < max_pages - 1:
                url = (TIKHUB_USER_TWEETS_URL.format(screen_name=screen_name)
                       + f"&cursor={next_cursor}")
                time.sleep(1)  # 限速
            else:
                break

        except Exception as e:
            print(f"[ERROR] 拉取推文失败: {e}", file=sys.stderr)
            break

    return all_tweets


def generate_label(text: str, article=None, media=None, entities=None) -> str:
    """优先级：正文 → X Article 标题 → 媒体类型 → 引用推作者 → 自动追踪"""
    import re

    # 1. 正文非空（去链接）
    clean = re.sub(r'https?://\S+', '', text or '').strip()
    label = clean[:20].replace("\n", " ").strip()
    if label:
        return label

    # 2. X Article 长文标题（自引长文）
    if article and isinstance(article, dict):
        title = article.get("title", "").strip()
        if title:
            return f"[长文] {title[:16]}"

    # 3. 媒体附件（图/视频）
    if media and isinstance(media, list) and media:
        m = media[0]
        if isinstance(m, dict):
            mtype = m.get("type", "media")
            type_zh = {"photo": "图", "video": "视频", "animated_gif": "动图"}.get(mtype, mtype)
            return f"[{type_zh}] {len(media)} 个"

    # 4. 引用别人推：解析 expanded_url 形如 x.com/{screen_name}/status/{id}
    if entities and isinstance(entities, dict):
        urls = entities.get("urls", []) or []
        for u in urls:
            expanded = u.get("expanded_url", "")
            m = re.search(r'(?:x\.com|twitter\.com)/([^/]+)/status/', expanded)
            if m and m.group(1) not in ("i", os.environ.get("X_SCREEN_NAME", "mytwitter")):
                return f"[引用 @{m.group(1)}]"

    # 5. 兜底
    return "自动追踪"


def auto_discover(screen_name: str = DEFAULT_SCREEN_NAME, dry_run: bool = False,
                  max_age_hours: float = 72) -> list[str]:
    """
    检测新推文并加入追踪。
    
    Args:
        screen_name: X 账号
        dry_run: 只检测不添加
        max_age_hours: 只追踪这个小时数以内的新推文（默认72小时）
    
    Returns:
        新添加的 tweet_id 列表
    """
    tweets = fetch_latest_tweets(screen_name)
    if not tweets:
        print("[INFO] 未获取到推文列表")
        return []

    # 加载已追踪的
    data = tg.load_data()
    existing_ids = set(data.get("tweets", {}).keys())

    added = []
    for t in tweets:
        tid = t["tweet_id"]
        if not tid or tid in existing_ids:
            continue

        # 只追踪 max_age_hours 以内的新推文
        if t["age_hours"] > max_age_hours:
            continue

        label = generate_label(
            t["text"],
            article=t.get("article"),
            media=t.get("media"),
            entities=t.get("entities"),
        )

        if dry_run:
            print(f"[DRY-RUN] 发现新推文: {tid} — 「{label}」 ({t['age_hours']:.1f}h前)")
        else:
            data["tweets"][tid] = {
                "label": label,
                "text": t["text"],
                "created_at": t.get("created_at"),
                "article": t.get("article"),
                "media": t.get("media"),
                "entities": t.get("entities"),
                "latest": {"created_at": t.get("created_at")},
                "history": [],
            }
            added.append(tid)
            print(f"[NEW] 自动追踪: {tid} — 「{label}」 ({t['age_hours']:.1f}h前)")

    if added and not dry_run:
        tg.save_data(data)
        print(f"[OK] 新增 {len(added)} 条推文追踪")
        # DB double-write: upsert newly discovered tweets
        try:
            import db
            conn = db.get_conn()
            if conn:
                tweet_index = {t["tweet_id"]: t for t in tweets}
                for tid in added:
                    rec = data["tweets"][tid]
                    src = tweet_index.get(tid, {})
                    created_at = src.get("created_at")
                    url = f"https://x.com/{screen_name}/status/{tid}"
                    db.upsert_tweet(conn, tid, rec.get("label", ""), rec.get("text", ""),
                                    created_at=created_at, url=url)
                conn.close()
        except Exception as e:
            print(f"[WARN] DB upsert 失败: {e}", file=sys.stderr)

    if not added:
        print("[INFO] 无新推文需要追踪")

    return added


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="自动发现新推文并加入追踪")
    parser.add_argument("--dry-run", action="store_true", help="只检测不添加")
    parser.add_argument("--screen-name", default=DEFAULT_SCREEN_NAME, help="X 账号名")
    parser.add_argument("--max-age", type=float, default=48, help="最大追踪年龄（小时）")
    args = parser.parse_args()

    added = auto_discover(
        screen_name=args.screen_name,
        dry_run=args.dry_run,
        max_age_hours=args.max_age,
    )
    sys.exit(0)
