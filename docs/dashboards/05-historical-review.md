# Dashboard 05 · 历史复盘

**Source views:** `v_tweet_latest`, `samples`
**Cards:** 3 (monthly trend + topic evolution + viral tweets log)

## Card 5.1 — 月度发推趋势 (Combo)

```sql
SELECT
  DATE_TRUNC('month', created_at) AS month,
  COUNT(*) AS posts,
  SUM(views) AS total_views,
  ROUND(AVG(engagement::float / NULLIF(views, 0)) * 100, 2) AS avg_er_pct
FROM v_tweet_latest
WHERE created_at >= NOW() - INTERVAL '12 months'
GROUP BY 1
ORDER BY 1;
```

Visualization: **Combo chart**. X = month. Bar: posts. Line 1: total_views (right axis). Line 2: avg_er_pct (right axis).
Title: "12 个月发推产能".

## Card 5.2 — 类目热度演化 (Stacked Area)

```sql
SELECT
  DATE_TRUNC('week', created_at) AS week,
  topic,
  COUNT(*) AS posts
FROM v_tweet_latest
WHERE created_at >= NOW() - INTERVAL '6 months'
GROUP BY 1, 2
ORDER BY 1;
```

Visualization: **Stacked area**. X = week, Y = posts, stack = topic.
Title: "6 个月类目热度演化".

## Card 5.3 — 历史爆款一览 (Table)

```sql
SELECT
  TO_CHAR(created_at, 'YYYY-MM-DD') AS published,
  LEFT(text, 60) AS preview,
  topic,
  views,
  likes,
  replies,
  bookmarks,
  ROUND((engagement::float / NULLIF(views, 0)) * 100, 2) AS er_pct
FROM v_tweet_latest
WHERE views >= 10000
ORDER BY views DESC
LIMIT 50;
```

Visualization: **Table**. Highlight: views > 100k row gold.
Title: "历史爆款（≥10k 浏览）".
