-- 004_dashboard_views.sql · X Data Warroom dashboard contract views
-- Run with: psql "$SUPABASE_DB_URL" -f 004_dashboard_views.sql
-- All views are CREATE OR REPLACE (idempotent).
-- Dependencies: tweets, samples, actions tables + v_tweet_latest, v_baselines_topic, v_tweet_ranked views.

BEGIN;

-- ───────────────────────────────────────────────────────────
-- v_dashboard_kpi: 4 core KPI numbers as a single row
-- ───────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW v_dashboard_kpi AS
SELECT
  (SELECT COUNT(*) FROM tweets WHERE NOT is_deleted) AS tracked_tweets,
  (SELECT COALESCE(SUM(views), 0) FROM v_tweet_latest) AS total_views,
  (SELECT COALESCE(SUM(s_latest.views - COALESCE(s_prev.views, 0)), 0)
     FROM (SELECT DISTINCT ON (tweet_id) tweet_id, views, sampled_at FROM samples
           WHERE sampled_at > NOW() - INTERVAL '24 hours'
           ORDER BY tweet_id, sampled_at DESC) s_latest
     LEFT JOIN LATERAL (SELECT views FROM samples
       WHERE samples.tweet_id = s_latest.tweet_id AND sampled_at < NOW() - INTERVAL '24 hours'
       ORDER BY sampled_at DESC LIMIT 1) s_prev ON TRUE) AS views_24h,
  (SELECT ROUND(AVG(er)::numeric, 4) FROM v_tweet_latest WHERE er IS NOT NULL) AS avg_er;

-- ───────────────────────────────────────────────────────────
-- v_dashboard_topic_war: per-topic 7d posts/median ER vs baseline
-- ───────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW v_dashboard_topic_war AS
WITH topic_7d AS (
  SELECT topic,
    COUNT(*) AS posts_7d,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY er) AS median_er_7d,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY views) AS median_views_7d
  FROM v_tweet_latest
  WHERE created_at >= NOW() - INTERVAL '7 days' AND views > 0
  GROUP BY topic
),
baseline_30d AS (
  SELECT topic,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY er) AS median_er_30d
  FROM v_tweet_latest
  WHERE created_at >= NOW() - INTERVAL '30 days' AND views > 0
  GROUP BY topic
)
SELECT
  COALESCE(t.topic, b.topic) AS topic,
  COALESCE(t.posts_7d, 0) AS posts_7d,
  ROUND(COALESCE(t.median_er_7d, 0)::numeric, 4) AS median_er_7d,
  ROUND(COALESCE(t.median_views_7d, 0)::numeric, 0) AS median_views_7d,
  CASE
    WHEN b.median_er_30d > 0 AND t.median_er_7d IS NOT NULL
      THEN ROUND(((t.median_er_7d - b.median_er_30d) / b.median_er_30d * 100)::numeric, 1)
    ELSE 0
  END AS vs_baseline_pct,
  CASE
    WHEN t.median_er_7d > b.median_er_30d * 1.10 THEN 'rising'
    WHEN t.median_er_7d < b.median_er_30d * 0.90 THEN 'falling'
    ELSE 'stable'
  END AS trend
FROM topic_7d t
FULL OUTER JOIN baseline_30d b ON t.topic = b.topic
WHERE COALESCE(t.topic, b.topic) IS NOT NULL
ORDER BY posts_7d DESC NULLS LAST;

-- ───────────────────────────────────────────────────────────
-- v_dashboard_actions: union of boost/kill/reply candidates
-- ───────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW v_dashboard_actions AS
WITH ranked AS (
  SELECT * FROM v_tweet_ranked
)
SELECT 'boost' AS kind, tweet_id, text, topic, views, er,
       NULL::numeric AS velocity, viral_score,
       EXTRACT(EPOCH FROM (NOW() - created_at)) / 3600 AS age_h
FROM ranked
WHERE created_at >= NOW() - INTERVAL '7 days'
  AND er_pct_global >= 0.70
ORDER BY er_pct_global DESC LIMIT 5
UNION ALL
SELECT 'kill' AS kind, tweet_id, text, topic, views, er, NULL::numeric, viral_score,
       EXTRACT(EPOCH FROM (NOW() - created_at)) / 3600 AS age_h
FROM ranked
WHERE er_pct_global < 0.25
  AND created_at < NOW() - INTERVAL '7 days'
ORDER BY age_h DESC LIMIT 10
UNION ALL
SELECT 'reply' AS kind, tweet_id, text, topic, views, er, NULL::numeric, viral_score,
       EXTRACT(EPOCH FROM (NOW() - created_at)) / 3600 AS age_h
FROM v_tweet_latest
WHERE replies >= 5 AND created_at >= NOW() - INTERVAL '14 days'
ORDER BY replies DESC LIMIT 10;

-- ───────────────────────────────────────────────────────────
-- v_dashboard_recent_48h: tweets posted in last 48h
-- ───────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW v_dashboard_recent_48h AS
SELECT tweet_id, text, label, topic, url,
       views, likes, replies, bookmarks, retweets,
       er, weighted_score,
       created_at, sampled_at,
       EXTRACT(EPOCH FROM (NOW() - created_at)) / 3600 AS age_h
FROM v_tweet_latest
WHERE created_at >= NOW() - INTERVAL '48 hours'
ORDER BY created_at DESC;

-- ───────────────────────────────────────────────────────────
-- v_dashboard_velocity_top: top 20 by velocity in last 7d
-- (velocity = views/hour over last 24h)
-- ───────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW v_dashboard_velocity_top AS
WITH recent_pair AS (
  SELECT s_now.tweet_id,
    s_now.views AS views_now,
    COALESCE(s_24h.views, 0) AS views_24h_ago,
    EXTRACT(EPOCH FROM (s_now.sampled_at - COALESCE(s_24h.sampled_at, s_now.sampled_at - INTERVAL '24 hours'))) / 3600 AS hours_elapsed
  FROM (SELECT DISTINCT ON (tweet_id) tweet_id, views, sampled_at FROM samples ORDER BY tweet_id, sampled_at DESC) s_now
  LEFT JOIN LATERAL (
    SELECT views, sampled_at FROM samples
    WHERE samples.tweet_id = s_now.tweet_id AND sampled_at < s_now.sampled_at - INTERVAL '23 hours'
    ORDER BY sampled_at DESC LIMIT 1
  ) s_24h ON TRUE
)
SELECT t.tweet_id, t.text, t.topic, t.url, l.views,
  ROUND(((rp.views_now - rp.views_24h_ago) / NULLIF(rp.hours_elapsed, 0))::numeric, 1) AS velocity_v_per_h,
  EXTRACT(EPOCH FROM (NOW() - t.created_at)) / 3600 AS age_h
FROM tweets t
JOIN recent_pair rp ON rp.tweet_id = t.tweet_id
LEFT JOIN v_tweet_latest l ON l.tweet_id = t.tweet_id
WHERE t.created_at >= NOW() - INTERVAL '7 days'
  AND rp.hours_elapsed > 0
ORDER BY velocity_v_per_h DESC NULLS LAST
LIMIT 20;

COMMIT;
