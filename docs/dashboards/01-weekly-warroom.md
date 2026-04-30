# Dashboard 01 · 本周战报

**Source views:** `v_dashboard_kpi`, `v_dashboard_topic_war`
**Cards:** 7 (4 KPI + 1 bar + 1 line + 1 trend table)

## Layout (12-col grid)

```
+──────────+──────────+──────────+──────────+
|  KPI 1   |  KPI 2   |  KPI 3   |  KPI 4   |
| 追踪推   | 总浏览   | 24h 增量 | 平均 ER  |
+──────────+──────────+──────────+──────────+
|                                          |
|        Card 5: 类目战况 (Bar)             |
|        Card 6: 7 天 views (Line)          |
|                                          |
+──────────────────────────────────────────+
```

## Card 1.1 — 追踪推数 (Number)

```sql
SELECT tracked_tweets FROM v_dashboard_kpi;
```

Visualization: **Number**. Title: "追踪推数".

## Card 1.2 — 总浏览 (Number)

```sql
SELECT total_views FROM v_dashboard_kpi;
```

Visualization: **Number**. Title: "总浏览". Display: thousands separator.

## Card 1.3 — 24h 浏览增量 (Number)

```sql
SELECT views_24h FROM v_dashboard_kpi;
```

Visualization: **Number**. Title: "24h 增量". Color rule: positive=green, negative=red, zero=gray.

## Card 1.4 — 平均互动率 (Number)

```sql
SELECT ROUND(avg_er * 100, 2) AS avg_er_pct FROM v_dashboard_kpi;
```

Visualization: **Number**. Title: "平均互动率". Suffix: "%".

## Card 1.5 — 类目战况 (Bar)

```sql
SELECT topic, posts_7d, vs_baseline_pct, trend
FROM v_dashboard_topic_war
ORDER BY posts_7d DESC;
```

Visualization: **Bar chart**. X = topic, Y = posts_7d.
Conditional formatting (color):
- vs_baseline_pct > 20 → green
- -20 ≤ vs_baseline_pct ≤ 20 → gray
- vs_baseline_pct < -20 → red

Title: "类目战况（7d）".

## Card 1.6 — 7 天浏览趋势 (Line)

```sql
SELECT DATE_TRUNC('hour', sampled_at) AS hour,
       SUM(views) AS total_views
FROM samples
WHERE sampled_at >= NOW() - INTERVAL '7 days'
GROUP BY 1
ORDER BY 1;
```

Visualization: **Line chart**. X = hour, Y = total_views. Smooth curves on.

Title: "7 天累计浏览".
