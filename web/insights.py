#!/usr/bin/env python3
"""build_insights() — 作战简报聚合，直连 Supabase Postgres 返回 JSON-serializable dict."""
from __future__ import annotations

import json
import os
import statistics
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# DB connection
# ---------------------------------------------------------------------------

def _load_db_url() -> str:
    # Check os.environ first (set by shell or .env loader)
    url = os.environ.get("SUPABASE_DB_URL", "").strip()
    if url:
        return url
    # Fall back to reading $X_DATA_DIR/.env
    _data_dir = Path(os.environ.get("X_DATA_DIR", Path.home() / ".x-data"))
    env_path = _data_dir / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("SUPABASE_DB_URL="):
                val = line[len("SUPABASE_DB_URL="):]
                # strip surrounding quotes if present
                if val and val[0] in ('"', "'") and val[-1] == val[0]:
                    val = val[1:-1]
                return val
    raise RuntimeError(f"SUPABASE_DB_URL not set and not found in {env_path}")


def _get_conn():
    import psycopg
    url = _load_db_url()
    return psycopg.connect(url, connect_timeout=10)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _safe_pct(numerator: float, denominator: float) -> float | None:
    if not denominator:
        return None
    return round(numerator / denominator * 100, 1)


def _round2(v: Any) -> Any:
    if v is None:
        return None
    try:
        return round(float(v), 4)
    except (TypeError, ValueError):
        return v


def _trend(current_er: float | None, prev_er: float | None) -> str:
    """rising / stable / falling based on ±10% threshold."""
    if current_er is None or prev_er is None:
        return "insufficient_data"
    if prev_er == 0:
        return "rising" if current_er > 0 else "stable"
    delta_pct = (current_er - prev_er) / abs(prev_er)
    if delta_pct > 0.10:
        return "rising"
    if delta_pct < -0.10:
        return "falling"
    return "stable"


# ---------------------------------------------------------------------------
# Sub-queries
# ---------------------------------------------------------------------------

def _weekly_summary(cur) -> dict:
    """7-day post count, impressions, vs prev-7d impressions."""
    # current 7d
    cur.execute("""
        SELECT
            COUNT(*)                              AS total_posts,
            COALESCE(SUM(views), 0)               AS total_impressions
        FROM v_tweet_latest
        WHERE created_at >= NOW() - INTERVAL '7 days'
          AND is_deleted = FALSE
    """)
    row = cur.fetchone()
    total_posts = int(row[0])
    total_impressions = int(row[1])

    # prev 7d impressions (days -14 to -7)
    cur.execute("""
        SELECT COALESCE(SUM(views), 0) AS prev_impressions
        FROM v_tweet_latest
        WHERE created_at >= NOW() - INTERVAL '14 days'
          AND created_at <  NOW() - INTERVAL '7 days'
          AND is_deleted = FALSE
    """)
    prev_imp = int(cur.fetchone()[0])

    if prev_imp > 0:
        delta = (total_impressions - prev_imp) / prev_imp
        vs_prev = f"{'+' if delta >= 0 else ''}{round(delta * 100)}%"
    else:
        vs_prev = "N/A"

    return {
        "total_posts": total_posts,
        "total_impressions": total_impressions,
        "vs_prev_week": vs_prev,
    }


def _topic_breakdown(cur) -> list[dict]:
    """Per-topic: 7d post count, median ER, vs global ER baseline, trend."""
    # 7d posts with er from v_tweet_ranked
    cur.execute("""
        SELECT
            topic,
            COUNT(*)                        AS posts,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY er) AS median_er
        FROM v_tweet_ranked
        WHERE created_at >= NOW() - INTERVAL '7 days'
          AND is_deleted = FALSE
          AND topic IS NOT NULL
        GROUP BY topic
        ORDER BY posts DESC
    """)
    rows_7d = cur.fetchall()

    # prev 7d per topic
    cur.execute("""
        SELECT
            topic,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY er) AS prev_median_er
        FROM v_tweet_ranked
        WHERE created_at >= NOW() - INTERVAL '14 days'
          AND created_at <  NOW() - INTERVAL '7 days'
          AND is_deleted = FALSE
          AND topic IS NOT NULL
        GROUP BY topic
    """)
    prev_map: dict[str, float] = {r[0]: float(r[1]) for r in cur.fetchall() if r[1] is not None}

    # global 7d ER baseline (P50)
    cur.execute("""
        SELECT er_p50
        FROM v_baselines_global
        WHERE "window" = '7d'
        LIMIT 1
    """)
    baseline_row = cur.fetchone()
    global_baseline_er = float(baseline_row[0]) if baseline_row and baseline_row[0] is not None else None

    result = []
    for topic, posts, median_er in rows_7d:
        med_er_f = float(median_er) if median_er is not None else None
        prev_med = prev_map.get(topic)

        # vs_baseline: compare median_er to global baseline
        if med_er_f is not None and global_baseline_er and global_baseline_er > 0:
            diff_pct = (med_er_f - global_baseline_er) / global_baseline_er
            vs_baseline = f"{'+' if diff_pct >= 0 else ''}{round(diff_pct * 100)}%"
        else:
            vs_baseline = "N/A"

        result.append({
            "topic": topic,
            "posts": int(posts),
            "median_er": _round2(med_er_f),
            "vs_baseline": vs_baseline,
            "trend": _trend(med_er_f, prev_med),
        })

    return result


def _viral_pattern(cur) -> dict:
    """Top-10 score threshold features placeholder + topic distribution."""
    # top 10 posts by weighted_score in last 30 days
    cur.execute("""
        SELECT tweet_id, text, topic, weighted_score
        FROM v_tweet_latest
        WHERE created_at >= NOW() - INTERVAL '30 days'
          AND is_deleted = FALSE
          AND text IS NOT NULL
          AND text != ''
        ORDER BY weighted_score DESC NULLS LAST
        LIMIT 10
    """)
    top_rows = cur.fetchall()

    # bottom 10 (worst performers in last 30d, min 3d age to exclude brand-new)
    cur.execute("""
        SELECT tweet_id, text, topic, weighted_score
        FROM v_tweet_latest
        WHERE created_at >= NOW() - INTERVAL '30 days'
          AND created_at <  NOW() - INTERVAL '3 days'
          AND is_deleted = FALSE
          AND text IS NOT NULL
          AND text != ''
        ORDER BY weighted_score ASC NULLS LAST
        LIMIT 10
    """)
    bottom_rows = cur.fetchall()

    # score threshold (P90 of top-10 set)
    top_scores = [float(r[3]) for r in top_rows if r[3] is not None]
    score_threshold = round(statistics.median(top_scores), 2) if top_scores else None

    # topic distribution in top-10
    topic_dist: dict[str, int] = {}
    for r in top_rows:
        t = r[2] or "未分类"
        topic_dist[t] = topic_dist.get(t, 0) + 1

    return {
        "score_threshold_median_top10": score_threshold,
        "top_topic_distribution": topic_dist,
        "top_posts": [
            {"tweet_id": r[0], "topic": r[2], "score": _round2(r[3])}
            for r in top_rows
        ],
        "bottom_posts": [
            {"tweet_id": r[0], "topic": r[2], "score": _round2(r[3])}
            for r in bottom_rows
        ],
    }


def _actions(cur) -> dict:
    """boost / kill / reply candidates."""
    # --- boost candidates ---
    # boost_candidates v1.1（2026-04-29）：
    # v1.0 阈值"24h 发推 + er_pct_global >= 75"有两个 bug：
    # 1) er_pct_global 是 0-1 小数（max=1.0），>= 75 永远不命中；
    # 2) 24h 窗口过严——Wade 不每天发推，7d 内无新推时返回空。
    # v1.1 改为"age < 7d + er_pct_global >= 0.70 + delta_views > 0"。
    cur.execute("""
        SELECT
            r.tweet_id,
            r.text,
            r.topic,
            r.er,
            r.er_pct_global,
            r.views,
            wp.delta_views
        FROM v_tweet_ranked r
        LEFT JOIN v_tweet_with_prev wp ON r.tweet_id = wp.tweet_id
        WHERE r.created_at >= NOW() - INTERVAL '7 days'
          AND r.is_deleted = FALSE
          AND r.er_pct_global >= 0.70
          AND wp.delta_views > 0
        ORDER BY r.er_pct_global DESC
        LIMIT 10
    """)
    boost_rows = cur.fetchall()

    boost_candidates = [
        {
            "tweet_id": r[0],
            "text_snippet": (r[1] or "")[:80],
            "topic": r[2],
            "er": _round2(r[3]),
            "er_pct_global": _round2(r[4]),
            "views": r[5],
            "delta_views_24h": r[6],
            "suggestion": "写续篇 / 转长文",
        }
        for r in boost_rows
    ]

    # --- kill candidates ---
    # kill_candidates v1.1（2026-04-29）：
    # v1.0 用 er_pct_global < 25，因 er_pct_global 是 0-1 小数（max=1.0），
    # < 25 永远命中全表（偶然"有效"但语义错误）。
    # v1.1 改为正确阈值 < 0.25，语义：全局 ER 排名低于 P25 的旧推。
    cur.execute("""
        SELECT
            tweet_id,
            text,
            topic,
            er,
            er_pct_global,
            views,
            created_at
        FROM v_tweet_ranked
        WHERE created_at < NOW() - INTERVAL '7 days'
          AND is_deleted = FALSE
          AND er_pct_global < 0.25
        ORDER BY er_pct_global ASC
        LIMIT 10
    """)
    kill_rows = cur.fetchall()

    kill_candidates = [
        {
            "tweet_id": r[0],
            "text_snippet": (r[1] or "")[:80],
            "topic": r[2],
            "er": _round2(r[3]),
            "er_pct_global": _round2(r[4]),
            "views": r[5],
            "created_at": r[6].isoformat() if r[6] else None,
            "suggestion": "考虑撤稿或改写",
        }
        for r in kill_rows
    ]

    # --- reply candidates ---
    # reply_candidates v1.1（2026-04-29）：
    # v1.0 用"delta_replies >= 3 + latest_at >= 24h"，但 latest_at 是采集器
    # 运行时间戳（全量推文每次都更新），实质等于"24h 内被采集"≈全表，
    # 而 delta_replies 增量窗口只对最近两次采集有意义，导致不稳定。
    # v1.1 改为"总回复数 >= 5 + 推文年龄 < 14d"，稳定可重复。
    cur.execute("""
        SELECT
            wp.tweet_id,
            wp.text,
            wp.topic,
            wp.replies,
            wp.delta_replies,
            wp.created_at
        FROM v_tweet_with_prev wp
        WHERE wp.replies >= 5
          AND wp.created_at >= NOW() - INTERVAL '14 days'
          AND wp.tweet_id NOT IN (
              SELECT tweet_id FROM v_tweet_latest WHERE is_deleted = TRUE
          )
        ORDER BY wp.replies DESC
        LIMIT 10
    """)
    reply_rows = cur.fetchall()

    reply_candidates = [
        {
            "tweet_id": r[0],
            "text_snippet": (r[1] or "")[:80],
            "topic": r[2],
            "total_replies": r[3],
            "new_replies_24h": r[4],
            "created_at": r[5].isoformat() if r[5] else None,
            "suggestion": "24h 内新增评论，建议回复",
        }
        for r in reply_rows
    ]

    return {
        "boost_candidates": boost_candidates,
        "kill_candidates": kill_candidates,
        "reply_candidates": reply_candidates,
    }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def build_insights() -> dict:
    """Return structured 作战简报 as a JSON-serializable dict.

    On DB failure returns {"ok": False, "error": "..."}.
    """
    try:
        conn = _get_conn()
    except Exception as exc:
        return {"ok": False, "error": f"DB connection failed: {exc}"}

    try:
        with conn.cursor() as cur:
            weekly = _weekly_summary(cur)
            breakdown = _topic_breakdown(cur)
            viral = _viral_pattern(cur)
            action = _actions(cur)

            # top topic by 7d post count
            top_topic = breakdown[0]["topic"] if breakdown else None

        return {
            "ok": True,
            "weekly_summary": {
                **weekly,
                "top_topic": top_topic,
                "topic_breakdown": breakdown,
            },
            "viral_pattern": viral,
            "actions": action,
        }
    except Exception as exc:
        return {"ok": False, "error": f"Query failed: {exc}"}
    finally:
        try:
            conn.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    print("Running build_insights() self-test...", flush=True)
    result = build_insights()
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

    if not result.get("ok"):
        print(f"\nSELF-TEST FAILED: {result.get('error')}", file=sys.stderr)
        sys.exit(1)

    ws = result.get("weekly_summary", {})
    assert "total_posts" in ws, "missing total_posts"
    assert "total_impressions" in ws, "missing total_impressions"
    assert "topic_breakdown" in ws, "missing topic_breakdown"
    assert "viral_pattern" in result, "missing viral_pattern"
    assert "actions" in result, "missing actions"
    acts = result["actions"]
    assert "boost_candidates" in acts, "missing boost_candidates"
    assert "kill_candidates" in acts, "missing kill_candidates"
    assert "reply_candidates" in acts, "missing reply_candidates"

    print("\nSELF-TEST PASSED", flush=True)
    sys.exit(0)
