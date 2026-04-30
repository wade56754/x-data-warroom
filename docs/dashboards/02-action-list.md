# Dashboard 02 · 作战行动

**Source view:** `v_dashboard_actions`
**Cards:** 3 (boost / kill / reply tables)

## Layout

```
+──────────+──────────+──────────+
| 追投 5  | 撤稿 10 | 回复 10  |
+──────────+──────────+──────────+
```

## Card 2.1 — 追投候选 (Table)

```sql
SELECT
  '🔥' AS hint,
  LEFT(text, 40) AS preview,
  topic,
  views,
  ROUND(er * 100, 2) AS er_pct,
  ROUND(age_h, 1) AS age_h
FROM v_dashboard_actions
WHERE kind = 'boost'
ORDER BY er DESC;
```

Visualization: **Table**. Highlight: er_pct > 5 row red.
Title: "🔥 追投候选 (boost)". Click: open tweet_id link in new tab (configure URL field).

## Card 2.2 — 撤稿候选 (Table)

```sql
SELECT
  '✂' AS hint,
  LEFT(text, 40) AS preview,
  topic,
  views,
  ROUND(age_h / 24, 1) AS age_d
FROM v_dashboard_actions
WHERE kind = 'kill'
ORDER BY age_h DESC;
```

Visualization: **Table**. Title: "✂ 撤稿候选 (kill)".
Action button on row: "Mark as deleted in X" (link to tweet_id).

## Card 2.3 — 回复候选 (Table)

```sql
SELECT
  '💬' AS hint,
  LEFT(text, 40) AS preview,
  topic,
  views,
  ROUND(er * 100, 2) AS er_pct,
  ROUND(age_h, 1) AS age_h
FROM v_dashboard_actions
WHERE kind = 'reply'
ORDER BY age_h DESC;
```

Visualization: **Table**. Title: "💬 回复候选".
