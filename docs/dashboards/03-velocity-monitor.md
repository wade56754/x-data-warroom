# Dashboard 03 · 流速监控

**Source views:** `v_dashboard_velocity_top`, `v_tweet_latest`
**Cards:** 2 (velocity table + scatter)

## Card 3.1 — 流速 Top 20 (Table)

```sql
SELECT
  LEFT(text, 50) AS preview,
  topic,
  views,
  velocity_v_per_h,
  ROUND(age_h, 1) AS age_h
FROM v_dashboard_velocity_top
ORDER BY velocity_v_per_h DESC NULLS LAST;
```

Visualization: **Table**. Conditional formatting on velocity_v_per_h:
- ≥ 5000 → red bold
- 500-5000 → amber
- 50-500 → green
- < 50 → gray

Title: "流速 Top 20 (v/h)".

## Card 3.2 — 互动率散点图 (Scatter)

```sql
SELECT
  views,
  ROUND((engagement::float / NULLIF(views, 0)) * 100, 2) AS er_pct,
  replies,
  topic,
  LEFT(text, 30) AS preview
FROM v_tweet_latest
WHERE views > 100
  AND created_at >= NOW() - INTERVAL '7 days';
```

Visualization: **Scatter**. X = views (log scale), Y = er_pct, size = replies, color = topic.

Title: "互动率分布（7d）". X-axis log scale ON.
