# Dashboard 04 · 类目深度

**Source views:** `v_tweet_latest`, `v_dashboard_topic_war`
**Cards:** 3 (per-topic boxplot + posts timeline + topic detail filter)

## Card 4.1 — 类目 ER 分布 (Box Plot)

```sql
SELECT
  topic,
  ROUND((engagement::float / NULLIF(views, 0)) * 100, 2) AS er_pct
FROM v_tweet_latest
WHERE views > 0 AND created_at >= NOW() - INTERVAL '30 days';
```

Visualization: **Box plot**. X = topic, Y = er_pct.
Title: "30 天类目 ER 分布".

## Card 4.2 — 类目发推时间线 (Stacked Bar)

```sql
SELECT
  DATE_TRUNC('day', created_at) AS day,
  topic,
  COUNT(*) AS posts
FROM v_tweet_latest
WHERE created_at >= NOW() - INTERVAL '30 days'
GROUP BY 1, 2
ORDER BY 1;
```

Visualization: **Stacked bar**. X = day, Y = posts, stack = topic.
Title: "30 天发推日历".

## Card 4.3 — 单类目详情 (Table with topic filter)

```sql
SELECT
  LEFT(text, 50) AS preview,
  views, likes, replies, bookmarks, retweets,
  ROUND((engagement::float / NULLIF(views, 0)) * 100, 2) AS er_pct,
  ROUND(EXTRACT(EPOCH FROM (NOW() - created_at)) / 3600 / 24, 1) AS age_d
FROM v_tweet_latest
WHERE topic = {{topic}}
  AND created_at >= NOW() - INTERVAL '30 days'
ORDER BY views DESC
LIMIT 30;
```

Visualization: **Table**. Add **Field filter** parameter `topic` (dropdown from `tweets.topic`).
Title: "选定类目详情 (Top 30 by views)".
