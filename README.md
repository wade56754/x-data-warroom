# x-data-warroom

A self-hosted X (Twitter) tweet growth tracker and analytics dashboard.

Collects engagement metrics for your own tweets every 30 minutes, stores them in
Supabase Postgres, and serves a local read-only dashboard with viral scoring,
ETCH spike detection, and weekly battle-report insights.

---

## Features

- **Automatic collection** — polls tweet metrics every 30 minutes via TikHub API +
  FxTwitter fallback; new tweets (< 48 h) are sampled every 15 minutes
- **ETCH spike detection** — derivative-based algorithm normalised to per-hour rates,
  detects momentum breakouts before they plateau
- **Viral score (0-100)** — four-dimension weighted index: velocity 40 % / engagement
  rate 25 % / retweet ratio 20 % / bookmark ratio 15 %
- **Dual-layer baselines** — P50/P75/P90/P95 percentiles computed globally and
  per-topic via Postgres views; no external analytics service required
- **Auto-discovery** — `auto_discover.py` searches your recent tweets and suggests
  new tracking candidates with AI-generated labels
- **Battle-report insights** — weekly summary, topic breakdown, boost/kill/reply
  action candidates served at `/api/insights`
- **Local-first dashboard** — zero CDN, zero npm, pure Vanilla JS SPA; runs entirely
  on your LAN; accessible from any device on the same network
- **Telegram alerts** — health-check script sends an alert after 3 consecutive
  collection failures

---

## Architecture

```
TikHub API / FxTwitter
        │
        ▼
scripts/collector-cron.sh          (runs every 30 min via launchd)
        │
        ├─ tweet_growth_cli.py      core collection loop
        ├─ auto_discover.py         discovery + label generation
        ├─ topic_classifier.py      topic tagging
        └─ db.py                    Supabase write module (psycopg3)
                │
                ▼
        Supabase Postgres
        ┌─────────────────────────────────────┐
        │ tweets          (main table)        │
        │ samples         (time-series)       │
        │ v_tweet_latest  (latest snapshot)   │
        │ v_tweet_ranked  (scored + ranked)   │
        │ v_baselines_*   (percentile views)  │
        └─────────────────────────────────────┘
                │
                ▼
        web/server.py              (ThreadingHTTPServer, port 8787)
        ├─ /api/status             collector health + last-run info
        ├─ /api/tweets             paginated tweet list with scoring
        ├─ /api/tweet/<id>         single tweet detail
        └─ /api/insights           weekly battle report
                │
                ▼
        web/static/                (Vanilla SPA, no build step)
        ├─ index.html + app.js     main dashboard
        └─ insights.html           battle-report view
```

---

## Quick Start

### 1. Prerequisites

- macOS (launchd scheduling) or any Linux box
- Python 3.11+
- A [Supabase](https://supabase.com/) project (free tier is enough)
- A [TikHub](https://tikhub.io/) API key

### 2. Clone and install

```bash
git clone https://github.com/wade56754/x-data-warroom.git
cd x-data-warroom

# Create virtualenv (uv recommended)
uv venv .venv
source .venv/bin/activate
uv pip install -r requirements.txt
```

### 3. Configure

```bash
mkdir -p ~/.x-data
cp .env.example ~/.x-data/.env
# Edit ~/.x-data/.env and fill in:
#   SUPABASE_DB_URL   — your Supabase connection string
#   TIKHUB_API_KEY    — your TikHub key
#   X_SCREEN_NAME     — your Twitter handle (no @)
```

### 4. Apply database schema

```bash
# Option A: psql
psql "$SUPABASE_DB_URL" -f migrations/001_init_schema.sql
psql "$SUPABASE_DB_URL" -f migrations/002_baseline_views.sql

# Option B: Supabase dashboard SQL editor
#   Paste and run each migration file in order
```

### 5. Start collecting

```bash
# One-time manual run (verify everything works)
X_DATA_DIR=~/.x-data bash scripts/collector-cron.sh

# Schedule with launchd (macOS)
cp launchd/com.xdatawarroom.collector.plist.example \
   ~/Library/LaunchAgents/com.xdatawarroom.collector.plist
# Edit the plist — fill in your username and paths
launchctl load ~/Library/LaunchAgents/com.xdatawarroom.collector.plist
```

### 6. Launch the dashboard

```bash
bash start_dashboard.sh
# Opens at http://127.0.0.1:8787
# LAN access: http://<your-mac-ip>:8787
```

---

## Environment Variables

All configuration is read from `$X_DATA_DIR/.env` (default `~/.x-data/.env`).
Variables can also be exported directly in the shell — shell env takes precedence.

| Variable | Required | Default | Description |
|---|---|---|---|
| `SUPABASE_DB_URL` | Yes | — | PostgreSQL connection URL |
| `TIKHUB_API_KEY` | Yes | — | TikHub API key |
| `X_SCREEN_NAME` | No | `mytwitter` | Your Twitter handle (no @) |
| `X_DATA_DIR` | No | `~/.x-data` | Data directory |
| `TWEET_GROWTH_DATA` | No | `$X_DATA_DIR/data.json` | Growth tracker JSON file |
| `TELEGRAM_BOT_TOKEN` | No | — | Telegram bot token for alerts |
| `TELEGRAM_HOME_CHANNEL` | No | — | Telegram chat/channel ID |
| `DASHBOARD_PORT` | No | `8787` | Dashboard server port |

---

## Repository Layout

```
x-data-warroom/
├── scripts/
│   ├── auto_discover.py        Tweet discovery + label generation
│   ├── collector-cron.sh       Main cron entry point
│   ├── collector-alert.sh      Health check + Telegram alert
│   ├── db.py                   Supabase write module
│   ├── growth_config.py        Algorithm thresholds and weights
│   ├── topic_classifier.py     Topic tagging
│   ├── tweet_growth.py         ETCH core + growth tracking
│   ├── tweet_growth_cli.py     CLI entry point
│   └── python/
│       └── dashboard_data.py   Dashboard data helpers
├── web/
│   ├── server.py               ThreadingHTTPServer + API routes
│   ├── insights.py             Battle-report analytics (Supabase)
│   └── static/
│       ├── index.html          Main dashboard SPA
│       ├── app.js              Dashboard JS (no dependencies)
│       ├── insights.html       Battle-report view
│       └── style.css           Dashboard styles
├── migrations/
│   ├── 001_init_schema.sql     Core tables (tweets, samples, views)
│   ├── 002_baseline_views.sql  Percentile baseline views
│   └── migrate_json_to_supabase.py   One-time JSON → Postgres migration
├── launchd/
│   └── com.xdatawarroom.collector.plist.example
├── .env.example
├── requirements.txt
└── start_dashboard.sh
```

---

## Migrating from a local JSON file

If you already have a `data.json` from a previous collection run:

```bash
# Dry-run first
python3 migrations/migrate_json_to_supabase.py --dry-run

# Live migration
python3 migrations/migrate_json_to_supabase.py --force
```

The migration is idempotent — safe to re-run.

---

## Telegram Alerts

The collector health check fires every 10 minutes (configurable via launchd).
After **3 consecutive failures** (data file not updated in 90 minutes) it sends
one Telegram message and suppresses further alerts until recovery.

Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_HOME_CHANNEL` in `~/.x-data/.env` to
enable alerts.

---

## License

MIT — see [LICENSE](LICENSE).
