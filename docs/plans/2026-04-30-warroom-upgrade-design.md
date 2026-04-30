# X Data Warroom Upgrade — Design Document

**Date**: 2026-04-30
**Status**: Approved (brainstorming Phase 6 complete, awaiting writing-plans)
**Author**: Wade × Claude Code
**Approval**: User confirmed B.3 path with all 5 risk mitigations.

---

## Context

The current vanilla SVG dashboard at `web/static/` was assembled in 18+ improvised iterations on 2026-04-29 + 2026-04-30. The user feedback after that day:

1. **Visuals are not professional** — Information density too high, table-driven, "exhausting to read".
2. **Insights too shallow** — `viral_score` capping at 4/100, no topic-strategy guidance.
3. **Engineering quality unstable** — 9 latent bugs surfaced and fixed across collector / DB / frontend during one session, indicating the hand-rolled stack lacks discipline.

The user requested: "modularize the project, prefer open-source over hand-rolled where possible".

After running the **brainstorming** skill (Anthropic Superpowers), gating evidence revealed:

- Wade's KB already contains ~70% of required capabilities across 22 skills (`xhs-analytics`, `x-trending-digest`, `wade-content-article-viralizing`, `sentinel`, `x-writer`, `x-algorithm-judge`, `cdp-publish`, etc.).
- No mature open-source X-creator dashboards exist (top alternatives have ≤25 stars, mostly Jupyter).
- **Metabase** (40k stars) is the strongest fit for the "BI consumption" gap — Postgres-native, drag-and-drop, single-user-friendly, 350MB Docker image, 30-min learning curve.

The remaining 30% gap is **dashboard / visualization layer + a few topic-strategy modules**, not "rebuild from scratch".

---

## Goals

| # | Goal | Acceptance |
|---|---|---|
| G1 | Replace the in-house SVG visualization layer with a professional BI tool | Wade prefers Metabase output to current `/static/insights.html` after X-ray demo |
| G2 | Maintain Supabase Postgres as the single source of truth | No data migration; only views are added |
| G3 | Lock the deployment to a known-stable Metabase release | Pin to 0.55.5 LTS — avoids 0.56.x OOM regression |
| G4 | Pre-build dashboard-specific Postgres views as contracts | Schema evolution does not break Metabase cards |
| G5 | Persist Metabase metadata across container restarts | Volume `./metabase-data:/metabase-data` mandatory |
| G6 | All infrastructure-as-code in the repo | `docker-compose.yml`, `migrations/004_dashboard_views.sql`, `docs/METABASE_SETUP.md` committed |
| G7 | One escape hatch built in | Step 4 X-ray verification — if visual style still fails, fall back without sunk cost |

**Out of scope** (this iteration):
- Production deployment to VPS (deferred per user's "先把项目开发完吧")
- Caddy / Let's Encrypt / DNS / public-internet auth
- LLM-driven topic strategy (separate brainstorming track)
- Migration of in-house `/api/*` endpoints — Metabase reads Supabase directly

---

## Decision Log

### Decision 1: Metabase vs alternatives

**Considered**:
- **Streamlit** (7.5/10) — Python-native, fast iteration, no drag-drop UI; rejected because user complaint is "visual not professional", which Streamlit does not solve better than vanilla SVG.
- **Apache Superset** (7.0/10) — Most feature-complete BI, but multi-container deploy (Redis + Postgres + App, 1.2GB image), single-user overkill.
- **Grafana** (6.0/10) — Time-series-first, Postgres datasource via plugin (non-native), preferred for monitoring not BI.
- **Lightdash** (5.5/10) — Hard dbt dependency, user has no dbt project.
- **Observable Framework** (4.5/10) — Static generation, no scheduled reports / alerts.
- **Metabase Cloud free tier** — Rejected: data must leave self-hosted Supabase; conflicts with user's "Supabase is single source of truth" preference.

**Selected**: **Metabase 0.55.5 LTS** (8.5/10).

**Rationale**:
- Postgres-native JDBC connector
- Drag-drop dashboard editor (the "professional visuals" gap)
- Built-in scheduled email reports + SQL alerts (no extension needed)
- 350MB Docker image, 1-1.5GB JVM heap for 60K rows/year scale
- 40k stars, monthly releases, corp-backed (Altimeter Capital)

### Decision 2: Pin to 0.55.5 LTS, not latest

**Evidence**: [GitHub Issue #65668 "OOM every couple days since metabase 56"](https://github.com/metabase/metabase/issues/65668) — production users with 4 datasources hitting OOM every 2 days on 0.56.x even with 4GB JVM heap. Confirmed memory leak regression. Mitigation upstream is in progress for 0.57.

**Decision**: Pin to 0.55.5 LTS until 0.57+ ships with verified leak fix.

**Trade-off**: Manual version pinning forever. Acceptable because Wade's data flow is single-source (Supabase only) so the regression less likely to bite us than the multi-source case in #65668, but the pin is conservative defense.

### Decision 3: B.3 (pre-built views + LTS) vs B.1 (raw views) vs B.2 (pre-built only)

**Considered**:
- **B.1** (1h) — Latest Metabase, direct Supabase, drag from existing `v_tweet_latest` etc. Cheapest. Risk: complex queries slow, "today's actions" requires hand-written SQL.
- **B.2** (½ day) — Same as B.1 + pre-built `v_dashboard_*` views. Better performance. Doesn't address LTS pinning.
- **B.3** (1 day) — B.2 + pin 0.55.5 LTS + statement_timeout + alpine + docker-compose committed. Best resilience for daily use.

**Selected**: **B.3**.

### Decision 4: Pre-build 5 views as contracts

**Why not let Metabase write SQL directly against existing views**: Each Metabase card binds to specific column names. If we add `viral_score` later, hand-rolled cards break silently. Pre-built `v_dashboard_*` views act as a contract layer — Wade can refactor underlying tables freely as long as the view signatures are preserved.

**Trade-off**: 30-min one-time SQL work. Negligible vs the alternative of rebuilding cards on every schema change.

### Decision 5: Supabase pooler — transaction mode (port 6543)

**Evidence**: Supabase free-tier session pooler caps at **15 connections**; transaction pooler caps at **200**. Metabase's default JDBC pool is 15. Direct connection limit is 5.

**Decision**: Force `?prepareThreshold=0&pgbouncer=true` via transaction pooler URL.

**Trade-off**: Transaction pooler does not support session-level features like `LISTEN/NOTIFY` or temp tables — irrelevant for read-only BI queries.

### Decision 6: Defer production deployment

**Original plan**: Develop locally, deploy to VPS (B.3-Server) immediately.

**User redirection**: "先把项目开发完吧。生产环境后面再到部署那一步。" — Develop the dashboard fully on local Mac mini first; VPS / Caddy / domain / auth deferred to a separate ticket.

**Rationale**: Local development is free of public-internet attack surface and can iterate faster. Once dashboard content is locked, lift-and-shift to VPS is mostly mechanical (compose.yml + Caddyfile + DNS).

### Decision 7: Step 4 X-ray as escape hatch

**The fragile assumption**: Metabase's default UI / theme will resolve "visuals not professional".

**Counterargument**: Metabase default style is its own aesthetic; if Wade's complaint is information architecture (not just CSS), Metabase may not solve it.

**Decision**: Step 4 of the workflow is a 10-minute X-ray auto-generated dashboard. If Wade approves the look, continue. If not, fall back without writing the 5 hand-curated dashboards.

---

## Architecture

```
                         ┌─────────────────────────────────────┐
                         │  Supabase Postgres (project ref:    │
                         │  cmlqmjpfgoeoktxfqgpo)              │
                         │                                     │
                         │  Tables:    tweets, samples, actions │
                         │  Views:     v_tweet_latest,         │
                         │             v_baselines_global,     │
                         │             v_baselines_topic,      │
                         │             v_tweet_ranked,         │
                         │             v_tweet_with_prev       │
                         │  + NEW:     v_dashboard_kpi,        │
                         │             v_dashboard_topic_war,  │
                         │             v_dashboard_actions,    │
                         │             v_dashboard_recent_48h, │
                         │             v_dashboard_velocity_top│
                         └────────────┬────────────────────────┘
                                      │ JDBC, transaction pooler
                                      │ port 6543, sslmode=require
                                      │
                         ┌────────────▼────────────────────────┐
                         │  Metabase 0.55.5 LTS (Docker)       │
                         │  - 1.5GB JVM heap                   │
                         │  - statement_timeout=30s            │
                         │  - MB_DOWNLOAD_ROW_LIMIT=10000      │
                         │  - MB_JAVA_TIMEZONE=Asia/Shanghai   │
                         │  - volume: ./metabase-data          │
                         │  - port: 3000                       │
                         └────────────┬────────────────────────┘
                                      │ HTTP
                                      │
                         ┌────────────▼────────────────────────┐
                         │  Wade browser  (local: localhost)   │
                         │  5 dashboards:                      │
                         │   1. 本周战报 (KPI + topic war)      │
                         │   2. 作战行动 (boost/kill/reply)     │
                         │   3. 流速监控 (velocity top + scatter)│
                         │   4. 类目深度 (per-topic boxplot)    │
                         │   5. 历史复盘 (monthly trend)        │
                         └─────────────────────────────────────┘

Existing in-house dashboard at port 8787 stays parallel for now.
After Wade prefers Metabase, in-house will be archived (not deleted).
```

---

## Components

### 1. `migrations/004_dashboard_views.sql` (new)

Idempotent `CREATE OR REPLACE VIEW` for 5 dashboard contract views:

| View | Purpose | Sample fields |
|---|---|---|
| `v_dashboard_kpi` | 4 core numbers as 1-row | tracked_tweets, total_views, views_24h, avg_er |
| `v_dashboard_topic_war` | 9 topics × metrics | topic, posts_7d, median_er_7d, vs_baseline_pct, trend |
| `v_dashboard_actions` | union of boost/kill/reply candidates | tweet_id, text, kind (boost/kill/reply), velocity, viral_score, age_h |
| `v_dashboard_recent_48h` | tweets posted in last 48h | tweet_id, text, topic, views, velocity, viral_score, created_at |
| `v_dashboard_velocity_top` | top 20 by velocity | tweet_id, text, velocity, views, age_h |

### 2. `docker-compose.yml` (new at repo root)

```yaml
services:
  metabase:
    image: metabase/metabase:v0.55.5
    container_name: warroom-metabase
    restart: unless-stopped
    ports:
      - "3000:3000"
    environment:
      MB_JAVA_TIMEZONE: Asia/Shanghai
      MB_DOWNLOAD_ROW_LIMIT: "10000"
      MB_QUERY_DEFAULT_TIMEOUT: "30"
      JAVA_OPTS: "-Xmx1500m -Xms512m"
    volumes:
      - ./metabase-data:/metabase-data
    deploy:
      resources:
        limits:
          memory: 2G
```

### 3. `.env.example` updates

```
# Existing X_DATA_DIR / SUPABASE_DB_URL etc.

# Metabase Postgres (use transaction pooler, NOT direct port 5432)
METABASE_SUPABASE_HOST=aws-0-<region>.pooler.supabase.com
METABASE_SUPABASE_PORT=6543
METABASE_SUPABASE_DB=postgres
METABASE_SUPABASE_USER=postgres.cmlqmjpfgoeoktxfqgpo
METABASE_SUPABASE_PASS=<your-supabase-db-password>
METABASE_JDBC_OPTS=?prepareThreshold=0&sslmode=require
```

### 4. `docs/METABASE_SETUP.md` (new)

Step-by-step:
1. Run migration `004_dashboard_views.sql` (psql or via Supabase MCP)
2. `docker compose up -d metabase`
3. Visit `http://localhost:3000`, complete first-run setup
4. Add Supabase as data source (use transaction pooler URL)
5. Run X-ray on `v_dashboard_kpi` to preview default style
6. Build 5 dashboards (templates linked)
7. Configure email alerts (optional)

### 5. `README.md` updates

Add "Visualization Layer (Metabase)" section pointing to `docs/METABASE_SETUP.md`.

### 6. `.gitignore` additions

```
metabase-data/
.env
```

---

## Data Flow

1. Existing collector continues writing to Supabase Postgres tables (`tweets`, `samples`).
2. Existing trigger / views continue computing (`v_tweet_latest`, `v_baselines_*`).
3. **New**: 5 `v_dashboard_*` views materialize per query (not materialized-view, just regular CREATE VIEW) — read by Metabase.
4. Metabase reads via transaction pooler, caches at default 60s TTL (override to 600s if egress concern).
5. Wade browses dashboards at `localhost:3000`.

No write path. Read-only consumer.

---

## Risks & Mitigations (Phase 5 Red-team)

| # | Risk | P×S | Mitigation |
|---|---|---|---|
| R1 | Supabase pooler misconfigured (session vs transaction) → 50% chance of immediate connection-cap death | M×H | Force port 6543 + prepareThreshold=0; documented in METABASE_SETUP.md |
| R2 | 0.55.5 LTS has undiscovered OOM | L×H | 1.5GB heap (50% headroom); observe 1 week; fallback ready (upgrade to 0.57 when released) |
| R3 | **Metabase default UI does not solve "visuals not professional"** | M×M | **Step 4 X-ray = 10-min escape hatch**; if Wade rejects, abort hand-curated dashboards |
| R4 | Volume not mounted → restart loses all dashboards / config | L×H | docker-compose explicitly mounts `./metabase-data` |
| R5 | Schema evolution breaks dashboard cards | M×L | Pre-built `v_dashboard_*` views as contracts |

Production-deployment risks (R6-R10 in earlier draft) are deferred until VPS phase.

---

## Verification

### Build verification

- [ ] `psql "$SUPABASE_DB_URL" -f migrations/004_dashboard_views.sql` succeeds
- [ ] `SELECT * FROM v_dashboard_kpi LIMIT 1` returns 1 row with 4 columns
- [ ] `SELECT COUNT(*) FROM v_dashboard_topic_war` returns 9
- [ ] `SELECT COUNT(*) FROM v_dashboard_recent_48h` ≥ 30 (after current 4-29/4-30 backfill)

### Container verification

- [ ] `docker compose up -d metabase` starts cleanly
- [ ] `docker stats warroom-metabase` shows < 1.5GB resident memory after 2-min warmup
- [ ] `curl http://localhost:3000/api/health` returns `{"status":"ok"}`
- [ ] `docker compose restart metabase` preserves first-run admin user (volume mounted)

### Functional verification

- [ ] Connect Supabase via transaction pooler → "Test connection" succeeds
- [ ] X-ray on `v_dashboard_kpi` produces 1+ chart
- [ ] **Wade approves X-ray output style** (gate to continue)
- [ ] All 5 dashboards built and visible
- [ ] One scheduled email alert configured (optional)

### Repo verification

- [ ] `docker-compose.yml` + `migrations/004_dashboard_views.sql` + `docs/METABASE_SETUP.md` + `.env.example` updated all committed
- [ ] `metabase-data/` not committed (in .gitignore)
- [ ] README links to METABASE_SETUP.md

---

## Case Reference

| Case | Source | Key data | Lesson for us |
|---|---|---|---|
| **cambá.coop metabase-compose** | https://github.com/cambalab/metabase-compose | Production team, 512MB-1GB Docker, 10+ dashboards | docker-compose template proves stable for small teams; H2→Postgres metadata migration unnecessary for our single-instance |
| **Tinitto compose-postgres-metabase** | https://github.com/tinitto/compose-postgres-metabase | Single-developer PoC, 256-512MB worked, postgres:alpine saved 50% mem | Confirms 1GB heap is conservative for our 60K-rows/year scale; alpine recommendation noted |
| **Supabase + Metabase user (synthesized)** | Multiple Reddit / dev.to threads | Pooler mandatory, sslmode=require mandatory, pre-built views give 10x query speed | All 3 patterns adopted in our design |
| **GitHub Issue #65668 (failure)** | https://github.com/metabase/metabase/issues/65668 | Enterprise user, 0.56.x OOM every 2 days even at 4GB heap | **Decisive evidence to pin 0.55.5 LTS** |
| **Metabase official scaling guide** | https://www.metabase.com/learn/metabase-basics/administration/administration-and-operation/metabase-at-scale | "Single core, 2GB RAM sufficient for individual / small team" | Validates our 1.5GB heap + 2GB compose limit |

---

## Implementation Sequence (handed to writing-plans)

| Step | Owner | Time |
|---|---|---|
| 1 | Run migration `004_dashboard_views.sql` (CC via supabase MCP) | 5 min |
| 2 | Write `docker-compose.yml`, `.env.example`, `.gitignore` updates (CC) | 10 min |
| 3 | `docker compose up -d` (Wade) | 5 min |
| 4 | **X-ray verification** (Wade), Wade approves or aborts | 10 min |
| 5 | Hand-build 5 dashboards (Wade in Metabase UI; CC writes templates / SQL helpers in `docs/dashboards/*.md`) | 1.5 h |
| 6 | Test verification checklist + screenshots into `docs/screenshots/` | 30 min |
| 7 | `git add . && git commit && git push` | 10 min |
| **Total** | | **~3 hours** (excluding Wade's drag-drop time at Step 5) |

Step 4 is a hard gate. Either Step 4 passes and we proceed to Step 5+, or we fall back to in-house dashboard improvements.

---

## Acknowledgements

- [Icy-Cat/x-viral-monitor](https://github.com/Icy-Cat/x-viral-monitor) — velocity-threshold and viral-score formulas adopted earlier in repo.
- [Metabase](https://github.com/metabase/metabase) — chosen visualization layer.
- Brainstorming workflow: Anthropic Superpowers `brainstorming` skill (8-step gated).
