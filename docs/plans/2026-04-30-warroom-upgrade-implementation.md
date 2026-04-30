# X Data Warroom Upgrade Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the in-house SVG dashboard with a Metabase-driven BI layer reading from Supabase, ship 5 hand-curated dashboards, all infrastructure-as-code committed.

**Architecture:** Single Docker container (`metabase/metabase:v0.55.5` LTS, 1.5GB JVM heap) connecting to Supabase Postgres via transaction pooler (port 6543). Five pre-built `v_dashboard_*` views act as schema contracts. Metadata persists in `./metabase-data` volume. Reuses existing `~/Projects/x-data-warroom` repo.

**Tech Stack:** Metabase 0.55.5 LTS · Supabase Postgres · Docker Compose · psql migrations · Caddy/auth deferred to VPS phase

**Working directory:** `/Users/wadea/Projects/x-data-warroom`

**Reference:** [Design doc](2026-04-30-warroom-upgrade-design.md) — read first for full context including Decision Log + Case References.

---

## Task 0: Pre-flight check

**Files:**
- Read: `~/Projects/x-data-warroom/.env.example`
- Read: `~/.tweet-growth/.env`

**Step 1: Verify gh + docker installed**

Run: `which gh && gh --version && which docker && docker --version`
Expected: gh ≥ 2.0, docker ≥ 24.0

**Step 2: Verify repo state**

Run: `cd ~/Projects/x-data-warroom && git status && git log --oneline | head -3`
Expected: clean working tree, design-doc commit visible

**Step 3: Verify Supabase pooler URL is constructable**

Run: `grep SUPABASE_DB_URL ~/.tweet-growth/.env | head -1`
Expected: shows direct URL (port 5432). We'll need to derive transaction pooler URL (port 6543, host pattern `aws-0-<region>.pooler.supabase.com`).

**Step 4: Read design doc fully**

Run: `cat ~/Projects/x-data-warroom/docs/plans/2026-04-30-warroom-upgrade-design.md | head -200`
Expected: Decision Log + Components + Risks visible

No commit needed for Task 0.

---

## Task 1: Write migration 004 — dashboard views

**Files:**
- Create: `~/Projects/x-data-warroom/migrations/004_dashboard_views.sql`

**Step 1: Author the SQL file**

Create `migrations/004_dashboard_views.sql` with:

```sql
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
```

**Step 2: Verify SQL syntax (psql --dry-run not available; use SQL parser check)**

Run: `python3 -c "import sqlparse; print(sqlparse.format(open('migrations/004_dashboard_views.sql').read(), reindent=True))" | head -20`
Or skip; psql will report syntax errors at apply time.

**Step 3: Commit migration file**

```bash
cd ~/Projects/x-data-warroom
git add migrations/004_dashboard_views.sql
git commit -m "feat(migrations): add 5 dashboard contract views (004)

Views: v_dashboard_kpi, v_dashboard_topic_war, v_dashboard_actions,
v_dashboard_recent_48h, v_dashboard_velocity_top.

Designed as schema contracts for Metabase cards — underlying tables
can be refactored as long as view signatures are preserved.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Apply migration 004 to Supabase

**Files:**
- (no file changes; remote DB only)

**Step 1: Apply via psql (use existing direct URL from .env)**

Run:
```bash
set -a; source ~/.tweet-growth/.env; set +a
psql "$SUPABASE_DB_URL" -f ~/Projects/x-data-warroom/migrations/004_dashboard_views.sql
```
Expected: `BEGIN`, 5 × `CREATE VIEW`, `COMMIT`. No errors.

**Step 2: Verify each view exists**

Run:
```bash
psql "$SUPABASE_DB_URL" -c "
SELECT viewname FROM pg_views
WHERE schemaname='public' AND viewname LIKE 'v_dashboard_%'
ORDER BY viewname;"
```
Expected: 5 rows showing all `v_dashboard_*` view names.

**Step 3: Smoke-test each view with LIMIT 1**

Run:
```bash
for v in v_dashboard_kpi v_dashboard_topic_war v_dashboard_actions v_dashboard_recent_48h v_dashboard_velocity_top; do
  echo "=== $v ==="
  psql "$SUPABASE_DB_URL" -c "SELECT * FROM $v LIMIT 1"
done
```
Expected: each returns ≥ 1 row (or 0 rows for `v_dashboard_recent_48h` if no recent posts), no errors.

**Step 4: Commit confirmation in repo doc**

No commit (DB-only step). Add a marker in next task's commit message.

---

## Task 3: Write docker-compose.yml

**Files:**
- Create: `~/Projects/x-data-warroom/docker-compose.yml`

**Step 1: Write the compose file**

```yaml
# docker-compose.yml · X Data Warroom — Metabase BI layer
# Pin to 0.55.5 LTS to avoid 0.56.x OOM regression (GitHub#65668).
# Pre-built dashboard views in Supabase serve as Metabase contracts.

services:
  metabase:
    image: metabase/metabase:v0.55.5
    container_name: warroom-metabase
    restart: unless-stopped
    ports:
      - "3000:3000"
    environment:
      # Memory / runtime
      JAVA_OPTS: "-Xmx1500m -Xms512m"
      MB_JAVA_TIMEZONE: Asia/Shanghai

      # Query safety
      MB_DOWNLOAD_ROW_LIMIT: "10000"
      MB_QUERY_DEFAULT_TIMEOUT: "30"

      # Persistence (H2 in volume; sufficient for single-instance dev)
      MB_DB_FILE: "/metabase-data/metabase.db"

    volumes:
      - ./metabase-data:/metabase-data
    deploy:
      resources:
        limits:
          memory: 2G

# Caddy / Tailscale / VPS deployment will be appended in a separate
# compose override file (docker-compose.prod.yml) when production
# phase begins.
```

**Step 2: Verify YAML syntax**

Run: `python3 -c "import yaml; yaml.safe_load(open('docker-compose.yml'))"`
Expected: no output (success).

**Step 3: Verify docker compose can parse**

Run: `cd ~/Projects/x-data-warroom && docker compose config 2>&1 | tail -10`
Expected: rendered compose config, no warnings/errors.

**Step 4: Commit**

```bash
git add docker-compose.yml
git commit -m "feat: docker-compose for Metabase 0.55.5 LTS

Pin to LTS due to 0.56.x OOM regression (GitHub#65668).
1.5GB JVM heap, 30s query timeout, persistent volume.
Production overrides deferred to docker-compose.prod.yml.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Update .env.example + .gitignore

**Files:**
- Modify: `~/Projects/x-data-warroom/.env.example`
- Modify: `~/Projects/x-data-warroom/.gitignore`

**Step 1: Append Metabase Supabase variables to .env.example**

Append to `.env.example`:

```
# === Metabase BI layer ===
# Use Supabase Transaction Pooler (port 6543) — NOT direct (5432).
# Direct connections cap at 5; transaction pooler caps at 200.
# Find pooler host in Supabase Dashboard → Project Settings → Database
# → Connection pooling → Transaction mode.
METABASE_SUPABASE_HOST=aws-0-<region>.pooler.supabase.com
METABASE_SUPABASE_PORT=6543
METABASE_SUPABASE_DB=postgres
METABASE_SUPABASE_USER=postgres.<project-ref>
METABASE_SUPABASE_PASS=<your-supabase-db-password>
# Append ?prepareThreshold=0&sslmode=require when entering JDBC URL in Metabase UI.
```

**Step 2: Add metabase-data to .gitignore**

Append to `.gitignore`:

```
# Metabase H2 metadata persistence
metabase-data/
```

**Step 3: Verify**

Run: `grep METABASE ~/Projects/x-data-warroom/.env.example | head -3 && grep metabase-data ~/Projects/x-data-warroom/.gitignore`
Expected: 3 lines from .env.example + 1 line "metabase-data/" from .gitignore.

**Step 4: Commit**

```bash
git add .env.example .gitignore
git commit -m "feat: env + gitignore for Metabase setup

.env.example documents transaction-pooler variables.
.gitignore excludes metabase-data/ H2 storage.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Write docs/METABASE_SETUP.md

**Files:**
- Create: `~/Projects/x-data-warroom/docs/METABASE_SETUP.md`

**Step 1: Write the setup doc**

Write `docs/METABASE_SETUP.md`:

```markdown
# Metabase Setup

Step-by-step to bring Metabase online for the X Data Warroom.

## Prerequisites

- Docker Desktop running (24+)
- Supabase project active, password known
- Migration `004_dashboard_views.sql` already applied (confirm via psql)

## 1. Get the Supabase transaction pooler URL

Supabase Dashboard → Project Settings → Database → Connection pooling
→ **Transaction mode**.

Copy host (e.g. `aws-0-ap-northeast-1.pooler.supabase.com`).

## 2. Bring up the container

```bash
cd ~/Projects/x-data-warroom
docker compose up -d metabase
docker compose logs -f metabase   # wait for "Metabase Initialization COMPLETE"
```

Visit http://localhost:3000 → first-run setup wizard.

## 3. Connect Supabase as data source

In Metabase Admin → Databases → Add database:

| Field | Value |
|---|---|
| Database type | PostgreSQL |
| Display name | Supabase Warroom |
| Host | `aws-0-<region>.pooler.supabase.com` |
| Port | `6543` |
| Database name | `postgres` |
| Username | `postgres.<project-ref>` |
| Password | (from .env) |
| Use SSL | true |
| Additional JDBC connection string options | `prepareThreshold=0` |

Click **Test connection** → must succeed within 5s.

## 4. X-ray verification (escape hatch)

Browse → `Supabase Warroom` → expand → click `v_dashboard_kpi` →
**X-ray this view**.

Wait 5s for auto-generated dashboard. Inspect default style.

**Decision point:** If Wade likes the default style, proceed to step 5.
If not, abort here — fall back to in-house dashboard improvements.

## 5. Build 5 dashboards

(Templates / queries documented in `docs/dashboards/*.md`. To be authored.)

## 6. (Optional) Email alerts

Admin → Settings → Email → configure SMTP.
Then on any dashboard card → menu → "Set up an alert".
```

**Step 2: Verify file exists**

Run: `ls -la ~/Projects/x-data-warroom/docs/METABASE_SETUP.md`
Expected: file > 1KB.

**Step 3: Commit**

```bash
git add docs/METABASE_SETUP.md
git commit -m "docs: Metabase setup guide

Step-by-step from container up to X-ray verification (escape hatch).
Dashboards templates deferred to Task 7.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Bring Metabase up + X-ray verification (HARD GATE)

**Files:**
- (runtime only)

**Step 1: Start the container**

Run: `cd ~/Projects/x-data-warroom && docker compose up -d metabase`
Expected: `Container warroom-metabase Started`

**Step 2: Wait for Metabase initialization**

Run: `docker compose logs -f metabase | grep -m1 "Metabase Initialization COMPLETE"`
Expected: line appears within 2-3 minutes. Press Ctrl+C after match.

**Step 3: Health check**

Run: `curl -s http://localhost:3000/api/health`
Expected: `{"status":"ok"}`.

**Step 4: Memory check**

Run: `docker stats warroom-metabase --no-stream --format "table {{.Container}}\t{{.MemUsage}}"`
Expected: < 1.5GB resident.

**Step 5: First-run setup (manual, Wade)**

In browser: http://localhost:3000 → admin user creation → skip email → finish.

**Step 6: Connect Supabase data source (manual, Wade)**

Follow `docs/METABASE_SETUP.md` Section 3. Test connection must succeed.

**Step 7: Run X-ray on v_dashboard_kpi**

In Metabase: Databases → Supabase Warroom → v_dashboard_kpi → X-ray.

**Step 8: HARD GATE — Wade decision**

Wade reviews X-ray output:
- ✅ Approves style → continue to Task 7
- ❌ Rejects style → abort, fall back to in-house improvements

**No commit at Task 6** (runtime + manual configuration).

---

## Task 7: Build 5 dashboards (manual via Metabase UI + SQL templates)

**Files:**
- Create: `~/Projects/x-data-warroom/docs/dashboards/01-weekly-warroom.md`
- Create: `~/Projects/x-data-warroom/docs/dashboards/02-action-list.md`
- Create: `~/Projects/x-data-warroom/docs/dashboards/03-velocity-monitor.md`
- Create: `~/Projects/x-data-warroom/docs/dashboards/04-topic-deep-dive.md`
- Create: `~/Projects/x-data-warroom/docs/dashboards/05-historical-review.md`

**Step 1: Write dashboard 01 template**

`docs/dashboards/01-weekly-warroom.md`:

```markdown
# Dashboard 01: 本周战报

**Source view:** `v_dashboard_kpi` + `v_dashboard_topic_war`

## Cards

### Card 1.1: 4 KPI numbers (Big Number × 4)

SQL:
```sql
SELECT tracked_tweets, total_views, views_24h, avg_er FROM v_dashboard_kpi;
```

Visualization: Number, repeated 4 times with different aggregations.

### Card 1.2: 类目战况 (Bar Chart)

SQL:
```sql
SELECT topic, posts_7d, vs_baseline_pct, trend
FROM v_dashboard_topic_war
ORDER BY posts_7d DESC;
```

Visualization: Bar chart, x = topic, y = posts_7d, color by trend.

### Card 1.3: 7 日 views 趋势 (Line Chart)

SQL:
```sql
SELECT DATE_TRUNC('hour', sampled_at) AS hour, SUM(views) AS total_views
FROM samples
WHERE sampled_at >= NOW() - INTERVAL '7 days'
GROUP BY 1 ORDER BY 1;
```

Visualization: Line chart.
```

**Step 2-5: Write dashboards 02-05** (same structure, see template).

(Skipped here for brevity; details in design doc Components section.)

**Step 6: Manual build in Metabase UI (Wade)**

In Metabase, for each dashboard 01-05: New Dashboard → Add card → SQL query → save.

**Step 7: Take screenshots into docs/screenshots/**

After each dashboard built, screenshot into `docs/screenshots/{dashboard-num}.png`.

**Step 8: Commit dashboard templates**

```bash
git add docs/dashboards/ docs/screenshots/
git commit -m "docs: 5 dashboard templates + screenshots

Card SQL queries documented for reproducibility.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Update README with Visualization Layer section

**Files:**
- Modify: `~/Projects/x-data-warroom/README.md`

**Step 1: Insert section after existing "Quick Start" or "Architecture"**

Append:

```markdown
## Visualization Layer (Metabase)

For drag-and-drop dashboards, this repo ships a Metabase container.

```bash
docker compose up -d metabase
```

Then:

1. Visit http://localhost:3000
2. Follow [docs/METABASE_SETUP.md](docs/METABASE_SETUP.md)
3. Pre-built views (`v_dashboard_*`) are read-only contracts;
   see [migrations/004_dashboard_views.sql](migrations/004_dashboard_views.sql).
4. Five hand-curated dashboards documented in
   [docs/dashboards/](docs/dashboards/).

Pinned to Metabase 0.55.5 LTS to avoid the 0.56.x memory leak
([GitHub#65668](https://github.com/metabase/metabase/issues/65668)).
```

**Step 2: Commit**

```bash
git add README.md
git commit -m "docs(README): add Visualization Layer section

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: Push to GitHub + final verification

**Files:**
- (no file changes)

**Step 1: Push all commits**

Run: `cd ~/Projects/x-data-warroom && git push origin main`
Expected: 6+ commits pushed.

**Step 2: Verify on GitHub**

Run: `gh repo view wade56754/x-data-warroom --json url,description,visibility`
Expected: visibility = public, URL accessible.

**Step 3: Verify all dashboard views queryable**

Run:
```bash
psql "$SUPABASE_DB_URL" -c "
SELECT viewname, pg_size_pretty(pg_relation_size(quote_ident(schemaname)||'.'||quote_ident(viewname))) AS size
FROM pg_views WHERE schemaname='public' AND viewname LIKE 'v_dashboard_%';"
```
Expected: 5 rows.

**Step 4: Container running confirmation**

Run: `docker compose ps`
Expected: warroom-metabase status = running, health = healthy.

---

## Total Time Estimate

| Task | Owner | Time |
|---|---|---|
| 0 Pre-flight | CC | 5 min |
| 1 Write 004 migration | CC | 15 min |
| 2 Apply migration | CC | 5 min |
| 3 docker-compose.yml | CC | 10 min |
| 4 .env.example + .gitignore | CC | 5 min |
| 5 METABASE_SETUP.md | CC | 10 min |
| **6 Up + X-ray (HARD GATE)** | Wade | 15 min |
| 7 5 dashboards build + templates | Wade + CC | 1.5 h |
| 8 README update | CC | 5 min |
| 9 Push + verify | CC | 5 min |
| **Total** | | **~2.5-3 h** |

Tasks 0-5 are fully automatable by CC.
Task 6 requires Wade's eyes (X-ray gate).
Task 7 requires Wade's drag-drop in Metabase UI; CC provides templates.
Tasks 8-9 fully automatable.

---

## Reference Skills

- `superpowers:executing-plans` — execute this plan task by task in a separate session.
- `superpowers:subagent-driven-development` — alternative: stay in this session, dispatch fresh subagent per task.
- `superpowers:test-driven-development` — Tasks 1-2 follow TDD-like pattern (write SQL → smoke test → commit).
- `superpowers:verification-before-completion` — Task 6 is an explicit verification gate.

---

## Acknowledgements

- Brainstorming output: [2026-04-30-warroom-upgrade-design.md](2026-04-30-warroom-upgrade-design.md)
- Inspirations: [Icy-Cat/x-viral-monitor](https://github.com/Icy-Cat/x-viral-monitor) algorithms; Metabase community.
