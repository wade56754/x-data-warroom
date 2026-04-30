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
