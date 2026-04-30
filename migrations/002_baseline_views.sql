-- ─── Migration 003: 双层基线统计视图 ────────────────────────────────────────
-- 承接 plan x-data-dashboard-warroom-20260429.md 阶段 C.2
-- 幂等：CREATE OR REPLACE VIEW，可重复跑
-- 依赖：v_tweet_latest（001_init_schema.sql 已建）
-- 注意：er = engagement / NULLIF(views, 0)，views=0 时为 NULL，用 FILTER 排除

BEGIN;

-- ─── 视图 1：v_baselines_global（全账号基线，30d / 7d 两窗口）─────────────────
CREATE OR REPLACE VIEW v_baselines_global AS
WITH base_30d AS (
  SELECT *,
    (likes + replies + retweets + bookmarks)::numeric
      / NULLIF(views, 0) AS er
  FROM v_tweet_latest
  WHERE created_at >= NOW() - INTERVAL '30 days'
    AND views IS NOT NULL
),
base_7d AS (
  SELECT *,
    (likes + replies + retweets + bookmarks)::numeric
      / NULLIF(views, 0) AS er
  FROM v_tweet_latest
  WHERE created_at >= NOW() - INTERVAL '7 days'
    AND views IS NOT NULL
)
SELECT
  '30d'                                                           AS window,
  COUNT(*)                                                        AS n,
  PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY views)            AS views_p50,
  PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY views)            AS views_p75,
  PERCENTILE_CONT(0.90) WITHIN GROUP (ORDER BY views)            AS views_p90,
  PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY views)            AS views_p95,
  PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY engagement)       AS engagement_p50,
  PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY engagement)       AS engagement_p75,
  PERCENTILE_CONT(0.90) WITHIN GROUP (ORDER BY engagement)       AS engagement_p90,
  PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY engagement)       AS engagement_p95,
  PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY weighted_score)   AS score_p50,
  PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY weighted_score)   AS score_p75,
  PERCENTILE_CONT(0.90) WITHIN GROUP (ORDER BY weighted_score)   AS score_p90,
  PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY weighted_score)   AS score_p95,
  PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY er)
    FILTER (WHERE er IS NOT NULL)                                 AS er_p50,
  PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY er)
    FILTER (WHERE er IS NOT NULL)                                 AS er_p75,
  PERCENTILE_CONT(0.90) WITHIN GROUP (ORDER BY er)
    FILTER (WHERE er IS NOT NULL)                                 AS er_p90,
  PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY er)
    FILTER (WHERE er IS NOT NULL)                                 AS er_p95
FROM base_30d

UNION ALL

SELECT
  '7d'                                                            AS window,
  COUNT(*)                                                        AS n,
  PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY views)            AS views_p50,
  PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY views)            AS views_p75,
  PERCENTILE_CONT(0.90) WITHIN GROUP (ORDER BY views)            AS views_p90,
  PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY views)            AS views_p95,
  PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY engagement)       AS engagement_p50,
  PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY engagement)       AS engagement_p75,
  PERCENTILE_CONT(0.90) WITHIN GROUP (ORDER BY engagement)       AS engagement_p90,
  PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY engagement)       AS engagement_p95,
  PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY weighted_score)   AS score_p50,
  PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY weighted_score)   AS score_p75,
  PERCENTILE_CONT(0.90) WITHIN GROUP (ORDER BY weighted_score)   AS score_p90,
  PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY weighted_score)   AS score_p95,
  PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY er)
    FILTER (WHERE er IS NOT NULL)                                 AS er_p50,
  PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY er)
    FILTER (WHERE er IS NOT NULL)                                 AS er_p75,
  PERCENTILE_CONT(0.90) WITHIN GROUP (ORDER BY er)
    FILTER (WHERE er IS NOT NULL)                                 AS er_p90,
  PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY er)
    FILTER (WHERE er IS NOT NULL)                                 AS er_p95
FROM base_7d;


-- ─── 视图 2：v_baselines_topic（按 topic 类目基线，30d / 7d 两窗口）────────────
-- P95 不算（类目样本量太小，不稳定），只算 P50 / P75 / P90
CREATE OR REPLACE VIEW v_baselines_topic AS
WITH base AS (
  SELECT *,
    (likes + replies + retweets + bookmarks)::numeric
      / NULLIF(views, 0) AS er
  FROM v_tweet_latest
  WHERE views IS NOT NULL
    AND topic IS NOT NULL
)
SELECT
  topic,
  '30d'                                                                   AS window,
  COUNT(*)                                                                AS n,
  PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY views)                    AS views_p50,
  PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY views)                    AS views_p75,
  PERCENTILE_CONT(0.90) WITHIN GROUP (ORDER BY views)                    AS views_p90,
  PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY engagement)               AS engagement_p50,
  PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY engagement)               AS engagement_p75,
  PERCENTILE_CONT(0.90) WITHIN GROUP (ORDER BY engagement)               AS engagement_p90,
  PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY weighted_score)           AS score_p50,
  PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY weighted_score)           AS score_p75,
  PERCENTILE_CONT(0.90) WITHIN GROUP (ORDER BY weighted_score)           AS score_p90,
  PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY er)
    FILTER (WHERE er IS NOT NULL)                                         AS er_p50,
  PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY er)
    FILTER (WHERE er IS NOT NULL)                                         AS er_p75,
  PERCENTILE_CONT(0.90) WITHIN GROUP (ORDER BY er)
    FILTER (WHERE er IS NOT NULL)                                         AS er_p90
FROM base
WHERE created_at >= NOW() - INTERVAL '30 days'
GROUP BY topic

UNION ALL

SELECT
  topic,
  '7d'                                                                    AS window,
  COUNT(*)                                                                AS n,
  PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY views)                    AS views_p50,
  PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY views)                    AS views_p75,
  PERCENTILE_CONT(0.90) WITHIN GROUP (ORDER BY views)                    AS views_p90,
  PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY engagement)               AS engagement_p50,
  PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY engagement)               AS engagement_p75,
  PERCENTILE_CONT(0.90) WITHIN GROUP (ORDER BY engagement)               AS engagement_p90,
  PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY weighted_score)           AS score_p50,
  PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY weighted_score)           AS score_p75,
  PERCENTILE_CONT(0.90) WITHIN GROUP (ORDER BY weighted_score)           AS score_p90,
  PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY er)
    FILTER (WHERE er IS NOT NULL)                                         AS er_p50,
  PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY er)
    FILTER (WHERE er IS NOT NULL)                                         AS er_p75,
  PERCENTILE_CONT(0.90) WITHIN GROUP (ORDER BY er)
    FILTER (WHERE er IS NOT NULL)                                         AS er_p90
FROM base
WHERE created_at >= NOW() - INTERVAL '7 days'
GROUP BY topic;


-- ─── 视图 3：v_tweet_ranked（每条推在 30d 范围内的 percentile rank）────────────
-- PERCENT_RANK() 返回 0.0（最低）到 1.0（最高）
-- er NULL（views=0）用 COALESCE(er, 0) 处理，排到最低位
CREATE OR REPLACE VIEW v_tweet_ranked AS
WITH recent AS (
  SELECT *,
    (likes + replies + retweets + bookmarks)::numeric
      / NULLIF(views, 0) AS er
  FROM v_tweet_latest
  WHERE created_at >= NOW() - INTERVAL '30 days'
)
SELECT
  *,
  PERCENT_RANK() OVER (ORDER BY views)
    AS views_pct_global,
  PERCENT_RANK() OVER (ORDER BY weighted_score)
    AS score_pct_global,
  PERCENT_RANK() OVER (ORDER BY COALESCE(er, 0))
    AS er_pct_global,
  PERCENT_RANK() OVER (PARTITION BY topic ORDER BY views)
    AS views_pct_topic,
  PERCENT_RANK() OVER (PARTITION BY topic ORDER BY weighted_score)
    AS score_pct_topic,
  PERCENT_RANK() OVER (PARTITION BY topic ORDER BY COALESCE(er, 0))
    AS er_pct_topic
FROM recent;

COMMIT;

-- ─── 验证（手动跑） ───────────────────────────────────────────────────────────
-- 验证 1：SELECT * FROM v_baselines_global;
--   → 2 行（30d / 7d）
-- 验证 2：SELECT topic, window, n, views_p50, views_p90, er_p50
--           FROM v_baselines_topic WHERE window = '30d' ORDER BY n DESC;
-- 验证 3：SELECT tweet_id, topic, weighted_score,
--           ROUND(score_pct_global::numeric, 3), ROUND(score_pct_topic::numeric, 3),
--           ROUND(er_pct_topic::numeric, 3), LEFT(text, 40)
--         FROM v_tweet_ranked ORDER BY weighted_score DESC LIMIT 5;
