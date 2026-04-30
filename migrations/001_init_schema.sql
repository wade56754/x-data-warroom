-- 001_init_schema.sql · X 推文数据 v1 schema
-- 目标：替代本地 JSON 单文件存储，迁入 Supabase Postgres 时间序列
-- 设计要点：时间序列 append-only / TIMESTAMPTZ 时区敏感 / LATERAL JOIN 视图加速
-- 跑法：psql "$SUPABASE_DB_URL" -f 001_init_schema.sql
--      或 supabase MCP execute_sql
-- 幂等：所有 CREATE 用 IF NOT EXISTS，可重复跑

BEGIN;

-- ─── tweets：推文主表 ─────────────────────────────────────────────────────
-- 每条推一行，tweet_id 作为主键
CREATE TABLE IF NOT EXISTS tweets (
  tweet_id        TEXT PRIMARY KEY,
  text            TEXT,                          -- 完整正文（A1 修复后）
  label           TEXT,                          -- auto_discover 生成的 ≤20 字短标签
  created_at      TIMESTAMPTZ,                   -- 推文发布时间（Twitter API 返回值）
  url             TEXT,
  topic           TEXT,                          -- 选题分类（阶段 C 加，初始 NULL）
  is_deleted      BOOLEAN NOT NULL DEFAULT FALSE,
  first_seen_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tweets_topic    ON tweets(topic) WHERE topic IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_tweets_created  ON tweets(created_at DESC);

-- ─── samples：采样快照 ────────────────────────────────────────────────────
-- time series append-only，每次 collector 跑产生 ~398 行
-- BIGSERIAL 防 INT 溢出（一年 700 万行 × 5 年 = 3500 万）
CREATE TABLE IF NOT EXISTS samples (
  id           BIGSERIAL PRIMARY KEY,
  tweet_id     TEXT        NOT NULL REFERENCES tweets(tweet_id) ON DELETE CASCADE,
  sampled_at   TIMESTAMPTZ NOT NULL,
  views        INTEGER     NOT NULL DEFAULT 0,
  likes        INTEGER     NOT NULL DEFAULT 0,
  replies      INTEGER     NOT NULL DEFAULT 0,
  retweets     INTEGER     NOT NULL DEFAULT 0,
  bookmarks    INTEGER     NOT NULL DEFAULT 0,
  CONSTRAINT u_tweet_sample UNIQUE (tweet_id, sampled_at)
);

CREATE INDEX IF NOT EXISTS idx_samples_tweet_time ON samples(tweet_id, sampled_at DESC);
CREATE INDEX IF NOT EXISTS idx_samples_time       ON samples(sampled_at DESC);

-- ─── actions：Wade 行为状态（阶段 D 用） ──────────────────────────────────
-- "已回复 / 不回了 / 归档" 三态，给面板的"行动建议"列表去重
CREATE TABLE IF NOT EXISTS actions (
  tweet_id   TEXT        NOT NULL REFERENCES tweets(tweet_id) ON DELETE CASCADE,
  action     TEXT        NOT NULL CHECK (action IN ('replied', 'dismissed', 'archived')),
  acted_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  note       TEXT,
  PRIMARY KEY (tweet_id, action)
);

CREATE INDEX IF NOT EXISTS idx_actions_acted ON actions(acted_at DESC);

-- ─── 触发器：tweets.updated_at 自动维护 ───────────────────────────────────
CREATE OR REPLACE FUNCTION trg_tweets_updated_at() RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS tweets_set_updated_at ON tweets;
CREATE TRIGGER tweets_set_updated_at
  BEFORE UPDATE ON tweets
  FOR EACH ROW EXECUTE FUNCTION trg_tweets_updated_at();

-- ─── 视图：v_tweet_latest（每条推 + 最新 sample） ─────────────────────────
-- 面板列表视图高频用：替代原 dashboard_data.py 的 normalize_tweet 主路径
CREATE OR REPLACE VIEW v_tweet_latest AS
SELECT
  t.tweet_id, t.text, t.label, t.created_at, t.url, t.topic, t.is_deleted,
  t.first_seen_at, t.updated_at,
  s.sampled_at, s.views, s.likes, s.replies, s.retweets, s.bookmarks,
  (s.likes + s.replies + s.retweets + s.bookmarks) AS engagement,
  (s.likes * 1 + s.replies * 3 + s.retweets * 4 + s.bookmarks * 5) AS weighted_score
FROM tweets t
LEFT JOIN LATERAL (
  SELECT *
  FROM samples
  WHERE tweet_id = t.tweet_id
  ORDER BY sampled_at DESC
  LIMIT 1
) s ON TRUE;

-- ─── 视图：v_tweet_with_prev（最新 + 上一次，算 delta 用） ─────────────────
CREATE OR REPLACE VIEW v_tweet_with_prev AS
SELECT
  t.tweet_id, t.text, t.label, t.created_at, t.topic,
  latest.sampled_at      AS latest_at,
  latest.views, latest.likes, latest.replies, latest.retweets, latest.bookmarks,
  prev.sampled_at        AS prev_at,
  prev.views    AS prev_views,
  prev.likes    AS prev_likes,
  prev.replies  AS prev_replies,
  prev.retweets AS prev_retweets,
  prev.bookmarks AS prev_bookmarks,
  COALESCE(latest.views    - prev.views,    0) AS delta_views,
  COALESCE(latest.likes    - prev.likes,    0) AS delta_likes,
  COALESCE(latest.replies  - prev.replies,  0) AS delta_replies,
  COALESCE(latest.retweets - prev.retweets, 0) AS delta_retweets,
  COALESCE(latest.bookmarks - prev.bookmarks, 0) AS delta_bookmarks
FROM tweets t
LEFT JOIN LATERAL (
  SELECT * FROM samples WHERE tweet_id = t.tweet_id
  ORDER BY sampled_at DESC LIMIT 1
) latest ON TRUE
LEFT JOIN LATERAL (
  SELECT * FROM samples WHERE tweet_id = t.tweet_id
  ORDER BY sampled_at DESC OFFSET 1 LIMIT 1
) prev ON TRUE;

COMMIT;

-- ─── 验证（手动跑） ───────────────────────────────────────────────────────
-- SELECT tablename FROM pg_tables WHERE schemaname = 'public';
-- SELECT viewname  FROM pg_views  WHERE schemaname = 'public';
-- expected: tables=tweets/samples/actions  views=v_tweet_latest/v_tweet_with_prev
