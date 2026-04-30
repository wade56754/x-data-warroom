#!/usr/bin/env python3
"""Pure data helpers for the local X data dashboard."""
from __future__ import annotations

import json
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any


import os

METRIC_KEYS = ("views", "likes", "replies", "bookmarks", "retweets")
WEIGHTS = {"likes": 1, "replies": 3, "retweets": 4, "bookmarks": 5}
DEFAULT_ACCOUNT = os.environ.get("X_SCREEN_NAME", "mytwitter")
TWITTER_CREATED_AT = "%a %b %d %H:%M:%S %z %Y"


def load_growth_data(path: Path) -> dict[str, Any]:
    """Load the tweet-growth tracker JSON file."""
    with Path(path).expanduser().open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("growth data root must be a JSON object")
    data.setdefault("tweets", {})
    if not isinstance(data["tweets"], dict):
        raise ValueError("growth data field 'tweets' must be an object")
    return data


def normalize_tweet(tweet_id: str, record: dict[str, Any], account: str = DEFAULT_ACCOUNT) -> dict[str, Any]:
    """Normalize one growth-tracker tweet record into an API row."""
    if not isinstance(record, dict):
        record = {}
    history_raw, latest_raw = _history_and_latest(record)
    history = [_normalize_sample(sample, index) for index, sample in enumerate(history_raw)]
    history = _sort_history(history)
    latest_sample = history[-1] if history else _normalize_sample(latest_raw, 0)
    previous_sample = history[-2] if len(history) >= 2 else None

    metrics = {key: latest_sample["metrics"][key] for key in METRIC_KEYS}
    engagement = _engagement(metrics)
    metrics["engagement"] = engagement
    er = _rate(engagement, metrics["views"])
    weighted_score = _weighted_score(metrics)
    deltas = _deltas(latest_sample, previous_sample)
    created_dt = _parse_datetime(latest_sample.get("created_at_raw"))
    sampled_dt = _parse_datetime(latest_sample.get("sampled_at"))
    age_hours = _age_hours(created_dt, sampled_dt)
    velocity = _velocity(latest_sample, previous_sample)

    viral_score = _viral_score(metrics, velocity)
    velocity_avg = _velocity_avg(metrics.get("views", 0), created_dt, sampled_dt)

    tweet = {
        "tweet_id": str(tweet_id),
        "url": _tweet_url(account, str(tweet_id), record),
        "text": _text(record, latest_raw),
        "created_at": _format_datetime(created_dt) if created_dt else _string_or_none(latest_sample.get("created_at_raw")),
        "sampled_at": _format_datetime(sampled_dt) if sampled_dt else _string_or_none(latest_sample.get("sampled_at")),
        "age_hours": age_hours,
        "metrics": metrics,
        "deltas": deltas,
        "delta_available": previous_sample is not None,
        "velocity": velocity,
        "velocity_avg": velocity_avg,
        "er": er,
        "weighted_score": weighted_score,
        "viral_score": viral_score,
        "status_label": "stable",
        "history": history,
    }
    tweet["status_label"] = _status_label(tweet, reference_time=sampled_dt)
    return tweet


def build_tweets(data: dict[str, Any], *, account: str = DEFAULT_ACCOUNT) -> list[dict[str, Any]]:
    """Build normalized tweet rows from a growth-tracker payload."""
    tweets_obj = data.get("tweets") if isinstance(data, dict) else {}
    if not isinstance(tweets_obj, dict):
        return []
    tweets = [normalize_tweet(str(tweet_id), record, account=account) for tweet_id, record in tweets_obj.items()]
    if not tweets:
        return []

    views = [tweet["metrics"]["views"] for tweet in tweets]
    engagements = [tweet["metrics"]["engagement"] for tweet in tweets]
    bookmark_rates = [
        _rate(tweet["metrics"]["bookmarks"], tweet["metrics"]["views"])
        for tweet in tweets
        if tweet["metrics"]["views"] > 0
    ]
    median_views = median(views) if views else None
    median_engagement = median(engagements) if engagements else None
    median_bookmark_rate = median(bookmark_rates) if bookmark_rates else None
    reference_time = _max_datetime(tweet.get("sampled_at") for tweet in tweets)
    for tweet in tweets:
        tweet["status_label"] = _status_label(
            tweet,
            median_views=median_views,
            median_engagement=median_engagement,
            median_bookmark_rate=median_bookmark_rate,
            reference_time=reference_time,
        )
    return tweets


def build_status(
    data: dict[str, Any],
    *,
    log_path: Path | None = None,
    account: str = DEFAULT_ACCOUNT,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build account-level dashboard status from the growth-tracker payload."""
    tweets = build_tweets(data, account=account)
    now_dt = _ensure_aware(now or datetime.now(timezone.utc))
    sample_times = [_parse_datetime(tweet.get("sampled_at")) for tweet in tweets]
    latest_sample_dt = max((dt for dt in sample_times if dt is not None), default=None)
    latest_sample_ts = _format_datetime(latest_sample_dt) if latest_sample_dt else None
    total_samples = _total_samples(data)
    totals = {key: sum(tweet["metrics"][key] for tweet in tweets) for key in METRIC_KEYS}
    ers = [tweet["er"] for tweet in tweets if tweet["er"] is not None]
    avg_er = round(mean(ers), 6) if ers else None
    collector = read_collector_health(log_path) if log_path else {"ok": None, "last_run_at": None, "log_file": None}
    warnings = _status_warnings(latest_sample_dt, collector, now_dt)

    return {
        "ok": True,
        "account": account,
        "tracked_tweets": len(tweets),
        "total_samples": total_samples,
        "latest_sample_ts": latest_sample_ts,
        "collector": collector,
        "totals": totals,
        "total_engagement": sum(tweet["metrics"]["engagement"] for tweet in tweets),
        "avg_er": avg_er,
        "growth": {
            **_growth(tweets, 24),
            **_growth(tweets, 24 * 7),
        },
        "top": {
            "by_views": _top_items(tweets, "views"),
            "by_score": _top_items(tweets, "score"),
            "by_replies": _top_items(tweets, "replies"),
            "by_bookmarks": _top_items(tweets, "bookmarks"),
        },
        "warnings": warnings,
        "hourly_series": _hourly_series(tweets, now_dt),
    }


def read_collector_health(log_path: Path) -> dict[str, Any]:
    """Read the last collector result from the local collector log."""
    path = Path(log_path).expanduser()
    base = {"ok": False, "last_run_at": None, "log_file": str(path), "last_line": None}
    if not path.exists():
        return {**base, "error": "collector log not found"}

    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    for line in reversed(lines):
        text = line.strip()
        if not text:
            continue
        parsed = _parse_json_object(text)
        if parsed is not None:
            commands = parsed.get("commands") if isinstance(parsed.get("commands"), list) else []
            command_ok = all(command.get("returncode") == 0 for command in commands if isinstance(command, dict))
            ok = bool(parsed.get("ok", command_ok))
            ran_at = parsed.get("ran_at") or parsed.get("last_run_at")
            last_run = _format_datetime(_parse_datetime(ran_at)) if _parse_datetime(ran_at) else _string_or_none(ran_at)
            return {
                "ok": ok and command_ok,
                "last_run_at": last_run,
                "log_file": str(path),
                "tracked_tweets": parsed.get("tracked_tweets"),
                "total_samples": parsed.get("total_samples"),
                "latest_sample_ts": _format_maybe_datetime(parsed.get("latest_sample_ts")),
                "last_line": text[:500],
                "error": parsed.get("err") or parsed.get("error"),
            }
        timestamp = _parse_bracket_timestamp(text)
        if timestamp is not None:
            lowered = text.lower()
            return {
                **base,
                "ok": not any(marker in lowered for marker in ("error", "failed", "失败")),
                "last_run_at": timestamp,
                "last_line": text[:500],
            }
    return {**base, "error": "collector log is empty"}


def _viral_score(metrics: dict, velocity: float | None) -> int:
    """0-100 综合爆款指数：四维加权（流速 40 / ER 25 / 转发比 20 / 收藏比 15）"""
    views = metrics.get("views", 0) or 0

    # 流速分（cap 50000 v/h → 满分 40）
    v_score = 0.0
    if velocity is not None and velocity > 0:
        v_score = min(velocity / 50000.0, 1.0) * 40

    # 互动率分（cap 10% → 满分 25）
    er = metrics.get("engagement", 0) / views if views > 0 else 0
    er_score = min(er / 0.10, 1.0) * 25

    # 转发比分（cap 50% → 满分 20）
    rt_ratio = metrics.get("retweets", 0) / views if views > 0 else 0
    rt_score = min(rt_ratio / 0.50, 1.0) * 20

    # 收藏比分（cap 30% → 满分 15）
    bm_ratio = metrics.get("bookmarks", 0) / views if views > 0 else 0
    bm_score = min(bm_ratio / 0.30, 1.0) * 15

    total = v_score + er_score + rt_score + bm_score
    return min(round(total), 100)


def _velocity_avg(views: int, created_at: datetime | None, sampled_at: datetime | None) -> float | None:
    """累计均速 = views / age_hours since publication"""
    if not created_at or not sampled_at:
        return None
    age_hours = (sampled_at - created_at).total_seconds() / 3600
    if age_hours <= 0:
        return None
    return round(views / age_hours, 1)


def sort_tweets(tweets: list[dict[str, Any]], sort: str, order: str) -> list[dict[str, Any]]:
    """Return tweets sorted by one of the dashboard API fields."""
    reverse = str(order).lower() != "asc"
    sort_key = str(sort or "created_at")

    def key(tweet: dict[str, Any]) -> Any:
        metrics = tweet.get("metrics", {})
        deltas = tweet.get("deltas", {})
        if sort_key == "score":
            return _finite(tweet.get("weighted_score"))
        if sort_key == "views":
            return _finite(metrics.get("views"))
        if sort_key == "replies":
            return _finite(metrics.get("replies"))
        if sort_key == "delta_views":
            return _finite(deltas.get("views"))
        if sort_key == "velocity":
            return _finite(tweet.get("velocity"))
        if sort_key == "viral_score":
            return _finite(tweet.get("viral_score"))
        if sort_key == "velocity_avg":
            return _finite(tweet.get("velocity_avg"))
        if sort_key == "created_at":
            dt = _parse_datetime(tweet.get("created_at"))
            return dt.timestamp() if dt else -math.inf
        return _finite(tweet.get(sort_key))

    keyed: list[tuple[Any, dict[str, Any]]] = []
    missing: list[dict[str, Any]] = []
    for tweet in tweets:
        value = key(tweet)
        if value == -math.inf:
            missing.append(tweet)
        else:
            keyed.append((value, tweet))
    return [tweet for _, tweet in sorted(keyed, key=lambda item: item[0], reverse=reverse)] + missing


def _history_and_latest(record: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    history = record.get("history") if isinstance(record.get("history"), list) else []
    history = [sample for sample in history if isinstance(sample, dict)]
    latest = record.get("latest") if isinstance(record.get("latest"), dict) else None
    if latest is None:
        latest = history[-1] if history else {}
    if not history and latest:
        history = [latest]
    elif latest:
        latest_ts = _string_or_none(latest.get("ts"))
        if latest_ts and all(_string_or_none(sample.get("ts")) != latest_ts for sample in history):
            history = [*history, latest]
    return history, latest


def _normalize_sample(sample: dict[str, Any], index: int) -> dict[str, Any]:
    if not isinstance(sample, dict):
        sample = {}
    metrics = {key: _number(sample.get(key)) for key in METRIC_KEYS}
    engagement = _engagement(metrics)
    metrics["engagement"] = engagement
    return {
        "index": index,
        "sampled_at": _format_maybe_datetime(sample.get("ts") or sample.get("sampled_at")),
        "created_at": _format_maybe_datetime(sample.get("created_at")),
        "created_at_raw": sample.get("created_at"),
        "metrics": metrics,
        "er": _rate(engagement, metrics["views"]),
        "weighted_score": _weighted_score(metrics),
    }


def _sort_history(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def key(sample: dict[str, Any]) -> tuple[int, float, int]:
        dt = _parse_datetime(sample.get("sampled_at"))
        if dt is None:
            return (1, math.inf, int(sample.get("index") or 0))
        return (0, dt.timestamp(), int(sample.get("index") or 0))

    return sorted(history, key=key)


def _deltas(latest: dict[str, Any], previous: dict[str, Any] | None) -> dict[str, int]:
    if previous is None:
        return {key: 0 for key in METRIC_KEYS}
    latest_metrics = latest.get("metrics", {})
    previous_metrics = previous.get("metrics", {})
    return {key: _number(latest_metrics.get(key)) - _number(previous_metrics.get(key)) for key in METRIC_KEYS}


def _velocity(latest: dict[str, Any], previous: dict[str, Any] | None) -> float | None:
    if previous is None:
        return None
    latest_dt = _parse_datetime(latest.get("sampled_at"))
    previous_dt = _parse_datetime(previous.get("sampled_at"))
    if latest_dt is None or previous_dt is None:
        return None
    hours_elapsed = (latest_dt - previous_dt).total_seconds() / 3600
    if hours_elapsed <= 0:
        return None
    delta_views = _number(latest.get("metrics", {}).get("views")) - _number(previous.get("metrics", {}).get("views"))
    return round(delta_views / hours_elapsed, 1)


def _growth(tweets: list[dict[str, Any]], hours: int) -> dict[str, int]:
    reference = _max_datetime(tweet.get("sampled_at") for tweet in tweets)
    suffix = "24h" if hours == 24 else "7d" if hours == 24 * 7 else f"{hours}h"
    totals = {f"{key}_{suffix}": 0 for key in METRIC_KEYS}
    if reference is None:
        return totals
    cutoff = reference - timedelta(hours=hours)
    for tweet in tweets:
        history = tweet.get("history") if isinstance(tweet.get("history"), list) else []
        if not history:
            continue
        latest = history[-1]
        base = _baseline_sample(history, cutoff)
        for key in METRIC_KEYS:
            totals[f"{key}_{suffix}"] += max(0, _number(latest.get("metrics", {}).get(key)) - _number(base.get("metrics", {}).get(key)))
    return totals


def _baseline_sample(history: list[dict[str, Any]], cutoff: datetime) -> dict[str, Any]:
    eligible: list[dict[str, Any]] = []
    for sample in history:
        dt = _parse_datetime(sample.get("sampled_at"))
        if dt is not None and dt <= cutoff:
            eligible.append(sample)
    if eligible:
        return eligible[-1]
    return history[0]


def _hourly_series(tweets: list[dict[str, Any]], now: datetime, hours: int = 48) -> dict[str, Any]:
    """Aggregate tweet history into per-hour buckets over the past `hours` hours.

    Each bucket contains the sum of the latest known metric values across all
    tracked tweets at that hour.  Empty buckets are forward-filled with the
    previous known value so the sparkline stays connected.
    """
    now_utc = now.astimezone(timezone.utc)
    # Build bucket labels (ISO hour strings) oldest-first
    labels: list[str] = []
    for i in range(hours - 1, -1, -1):
        bucket_dt = now_utc.replace(minute=0, second=0, microsecond=0) - timedelta(hours=i)
        labels.append(bucket_dt.strftime("%Y-%m-%dT%H:%M"))

    # For each tweet collect (sampled_at_dt, views, engagement) from history
    all_samples: list[tuple[datetime, int, int]] = []
    for tweet in tweets:
        history = tweet.get("history") if isinstance(tweet.get("history"), list) else []
        for sample in history:
            dt = _parse_datetime(sample.get("sampled_at"))
            if dt is None:
                continue
            m = sample.get("metrics") or {}
            views = _number(m.get("views"))
            engagement = _number(m.get("engagement")) or sum(
                _number(m.get(k)) for k in ("likes", "replies", "bookmarks", "retweets")
            )
            all_samples.append((dt.astimezone(timezone.utc), views, engagement))

    cutoff = now_utc - timedelta(hours=hours)

    # For each bucket hour, find the sum of latest-known values per tweet
    # Simpler approach: bin all samples into hour buckets, sum within bucket
    bucket_views: dict[str, int] = {}
    bucket_eng: dict[str, int] = {}
    for dt, views, eng in all_samples:
        if dt < cutoff:
            continue
        bucket_key = dt.replace(minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M")
        bucket_views[bucket_key] = bucket_views.get(bucket_key, 0) + views
        bucket_eng[bucket_key] = bucket_eng.get(bucket_key, 0) + eng

    # Build ordered arrays with last-known-good forward fill
    views_arr: list[int] = []
    eng_arr: list[int] = []
    last_v = 0
    last_e = 0
    for label in labels:
        if label in bucket_views:
            last_v = bucket_views[label]
            last_e = bucket_eng.get(label, last_e)
        views_arr.append(last_v)
        eng_arr.append(last_e)

    return {"labels": labels, "views": views_arr, "engagement": eng_arr}


def _top_items(tweets: list[dict[str, Any]], sort_key: str, limit: int = 5) -> list[dict[str, Any]]:
    items = sort_tweets(tweets, sort_key, "desc")[:limit]
    result = []
    for tweet in items:
        metrics = tweet["metrics"]
        value = tweet["weighted_score"] if sort_key == "score" else metrics.get(sort_key, 0)
        result.append(
            {
                "tweet_id": tweet["tweet_id"],
                "url": tweet["url"],
                "text": tweet["text"],
                "created_at": tweet["created_at"],
                "sampled_at": tweet["sampled_at"],
                "value": value,
                "metrics": {key: metrics[key] for key in METRIC_KEYS},
                "er": tweet["er"],
                "weighted_score": tweet["weighted_score"],
                "status_label": tweet["status_label"],
            }
        )
    return result


def _status_warnings(latest_sample: datetime | None, collector: dict[str, Any], now: datetime) -> list[str]:
    warnings: list[str] = []
    if latest_sample is None:
        warnings.append("no tweet samples found")
    else:
        age_minutes = (now.astimezone(timezone.utc) - latest_sample.astimezone(timezone.utc)).total_seconds() / 60
        if age_minutes > 90:
            warnings.append(f"latest sample is {round(age_minutes)} minutes old")
    if collector.get("ok") is False:
        error = collector.get("error")
        warnings.append(f"collector not healthy: {error}" if error else "collector not healthy")
    return warnings


def _total_samples(data: dict[str, Any]) -> int:
    tweets_obj = data.get("tweets") if isinstance(data, dict) else {}
    if not isinstance(tweets_obj, dict):
        return 0
    total = 0
    for record in tweets_obj.values():
        if not isinstance(record, dict):
            continue
        history = record.get("history")
        if isinstance(history, list) and history:
            total += len([sample for sample in history if isinstance(sample, dict)])
        elif isinstance(record.get("latest"), dict):
            total += 1
    return total


def _status_label(
    tweet: dict[str, Any],
    *,
    median_views: float | None = None,
    median_engagement: float | None = None,
    median_bookmark_rate: float | None = None,
    reference_time: datetime | None = None,
) -> str:
    metrics = tweet["metrics"]
    if metrics["replies"] > 0:
        return "needs_reply"
    bookmark_rate = _rate(metrics["bookmarks"], metrics["views"])
    if metrics["bookmarks"] > 0 and (
        metrics["bookmarks"] >= metrics["likes"]
        or (median_bookmark_rate is not None and bookmark_rate is not None and bookmark_rate > median_bookmark_rate)
    ):
        return "high_bookmark"
    sampled_at = _parse_datetime(tweet.get("sampled_at"))
    recent = True
    if sampled_at is not None and reference_time is not None:
        recent = (reference_time.astimezone(timezone.utc) - sampled_at.astimezone(timezone.utc)) <= timedelta(hours=24)
    if tweet["deltas"].get("views", 0) > 0 and recent:
        return "rising"
    if median_views is not None:
        low_views = metrics["views"] < median_views
    else:
        low_views = metrics["views"] == 0
    if median_engagement is not None:
        low_engagement = metrics["engagement"] <= median_engagement
    else:
        low_engagement = metrics["engagement"] == 0
    if low_views and low_engagement:
        return "cold"
    return "stable"


def _text(record: dict[str, Any], latest: dict[str, Any]) -> str:
    for source in (record, latest):
        for key in ("label", "text", "full_text", "content"):
            value = source.get(key) if isinstance(source, dict) else None
            if value is not None:
                return str(value)
    return ""


def _tweet_url(account: str, tweet_id: str, record: dict[str, Any]) -> str:
    for key in ("url", "tweet_url"):
        value = record.get(key) if isinstance(record, dict) else None
        if value:
            return str(value)
    return f"https://x.com/{account}/status/{tweet_id}"


def _number(value: Any) -> int:
    if value is None or value == "":
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip().replace(",", "")
    multiplier = 1
    if text.lower().endswith("k"):
        multiplier = 1_000
        text = text[:-1]
    elif text.lower().endswith("m"):
        multiplier = 1_000_000
        text = text[:-1]
    try:
        return int(float(text) * multiplier)
    except ValueError:
        return 0


def _engagement(metrics: dict[str, Any]) -> int:
    return sum(_number(metrics.get(key)) for key in ("likes", "replies", "retweets", "bookmarks"))


def _weighted_score(metrics: dict[str, Any]) -> int:
    return (
        _number(metrics.get("likes")) * WEIGHTS["likes"]
        + _number(metrics.get("replies")) * WEIGHTS["replies"]
        + _number(metrics.get("retweets")) * WEIGHTS["retweets"]
        + _number(metrics.get("bookmarks")) * WEIGHTS["bookmarks"]
    )


def _rate(top: int | float, bottom: int | float) -> float | None:
    if not bottom:
        return None
    return round(float(top) / float(bottom), 6)


def _age_hours(created_at: datetime | None, sampled_at: datetime | None) -> float | None:
    if created_at is None or sampled_at is None:
        return None
    hours = (sampled_at.astimezone(timezone.utc) - created_at.astimezone(timezone.utc)).total_seconds() / 3600
    return round(max(0.0, hours), 2)


def _parse_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return _ensure_aware(value)
    text = str(value).strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        return _ensure_aware(datetime.fromisoformat(normalized))
    except ValueError:
        pass
    try:
        return _ensure_aware(datetime.strptime(text, TWITTER_CREATED_AT))
    except ValueError:
        return None


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _format_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat(timespec="seconds")


def _format_maybe_datetime(value: Any) -> str | None:
    parsed = _parse_datetime(value)
    if parsed is not None:
        return _format_datetime(parsed)
    return _string_or_none(value)


def _max_datetime(values: Any) -> datetime | None:
    parsed = [_parse_datetime(value) for value in values]
    return max((value for value in parsed if value is not None), default=None)


def _finite(value: Any) -> float:
    if value is None:
        return -math.inf
    try:
        return float(value)
    except (TypeError, ValueError):
        return -math.inf


def _string_or_none(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


def _parse_json_object(text: str) -> dict[str, Any] | None:
    if not text.startswith("{"):
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _parse_bracket_timestamp(text: str) -> str | None:
    match = re.search(r"\[(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}(?::\d{2})?)\]", text)
    return match.group(1) if match else None
