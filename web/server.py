#!/usr/bin/env python3
"""Local read-only web dashboard for X tweet growth data."""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
from datetime import datetime, timezone, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse


PROJECT_DIR = Path(__file__).resolve().parents[1]
SCRIPT_DIR = PROJECT_DIR / "scripts" / "python"
sys.path.insert(0, str(SCRIPT_DIR))

from dashboard_data import build_status, build_tweets, load_growth_data, sort_tweets  # noqa: E402

_data_dir = Path(os.environ.get("X_DATA_DIR", Path.home() / ".x-data"))
DEFAULT_DATA_FILE = Path(os.environ.get("TWEET_GROWTH_DATA", _data_dir / "data.json"))
DEFAULT_LOG_FILE = _data_dir / "collector.log"
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8787
DEFAULT_ACCOUNT = os.environ.get("X_SCREEN_NAME", "mytwitter")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the local read-only X data dashboard.")
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help="Bind host. Defaults to 0.0.0.0 for LAN access; use 127.0.0.1 for local-only.",
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Bind port.")
    parser.add_argument("--data-file", default=str(DEFAULT_DATA_FILE), help="Growth tracker JSON file.")
    parser.add_argument("--log-file", default=str(DEFAULT_LOG_FILE), help="Collector log file.")
    parser.add_argument("--account", default=DEFAULT_ACCOUNT, help="X account used for status URLs.")
    return parser


class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        handler_class: type[BaseHTTPRequestHandler],
        *,
        data_file: Path,
        log_file: Path,
        account: str,
    ) -> None:
        super().__init__(server_address, handler_class)
        self.data_file = data_file
        self.log_file = log_file
        self.account = account
        self.static_dir = SKILL_DIR / "web" / "static"


class DashboardHandler(BaseHTTPRequestHandler):
    server: DashboardServer
    server_version = "WadeXDataDashboard/0.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self._handle_api(parsed.path, parse_qs(parsed.query))
            return
        self._serve_static(parsed.path)

    def _handle_api(self, path: str, query: dict[str, list[str]]) -> None:
        try:
            if path == "/api/status":
                data = self._load_data()
                payload = build_status(data, log_path=self.server.log_file, account=self.server.account)
                self._send_json(payload)
                return
            if path == "/api/tweets":
                data = self._load_data()
                tweets = build_tweets(data, account=self.server.account)
                sort = _query_one(query, "sort", "created_at")
                order = _query_one(query, "order", "desc")
                limit = _limit(_query_one(query, "limit", "100"))
                age_h_raw = _query_one(query, "age_h", "48")
                tweets = _filter_by_age(tweets, age_h_raw)
                sorted_tweets = sort_tweets(tweets, sort, order)
                payload = {
                    "ok": True,
                    "count": min(limit, len(sorted_tweets)),
                    "total_count": len(sorted_tweets),
                    "tweets": sorted_tweets[:limit],
                }
                self._send_json(payload)
                return
            if path.startswith("/api/tweet/"):
                tweet_id = unquote(path.removeprefix("/api/tweet/")).strip("/")
                if not tweet_id:
                    self._send_json({"ok": False, "error": "missing tweet id"}, HTTPStatus.BAD_REQUEST)
                    return
                data = self._load_data()
                for tweet in build_tweets(data, account=self.server.account):
                    if tweet["tweet_id"] == tweet_id:
                        self._send_json({"ok": True, "tweet": tweet})
                        return
                self._send_json({"ok": False, "error": "tweet not found"}, HTTPStatus.NOT_FOUND)
                return
            if path == "/api/insights":
                from insights import build_insights  # lazy import
                try:
                    payload = build_insights()
                    self._send_json(payload)
                except Exception as e:
                    self._send_json({"ok": False, "error": str(e)}, HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            self._send_json({"ok": False, "error": "unknown API endpoint"}, HTTPStatus.NOT_FOUND)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _load_data(self) -> dict[str, Any]:
        return load_growth_data(self.server.data_file)

    def _serve_static(self, path: str) -> None:
        if path in ("", "/"):
            relative = "index.html"
        elif path.startswith("/static/"):
            relative = path.removeprefix("/static/")
        else:
            relative = path.lstrip("/")
        target = (self.server.static_dir / relative).resolve()
        static_root = self.server.static_dir.resolve()
        try:
            target.relative_to(static_root)
        except ValueError:
            self._send_json({"ok": False, "error": "not found"}, HTTPStatus.NOT_FOUND)
            return
        if not target.is_file():
            self._send_json({"ok": False, "error": "not found"}, HTTPStatus.NOT_FOUND)
            return
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        data = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("%s - - [%s] %s\n" % (self.client_address[0], self.log_date_time_string(), fmt % args))


def _parse_tweet_created_at(tweet: dict[str, Any]) -> "datetime | None":
    """Extract tweet publish time from build_tweets() output dict.
    build_tweets() formats created_at as ISO-8601 via _format_datetime (e.g. '2026-04-28T17:09:39+00:00').
    Falls back to Twitter wire format 'Tue Apr 29 18:00:00 +0000 2026' if needed.
    """
    ca_str = tweet.get("created_at")
    if not ca_str:
        return None
    try:
        dt = datetime.fromisoformat(ca_str.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    try:
        return datetime.strptime(ca_str, "%a %b %d %H:%M:%S +0000 %Y").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _filter_by_age(tweets: list[dict[str, Any]], age_h_raw: str) -> list[dict[str, Any]]:
    """Filter tweets to those published within age_h hours. 'all' disables filter."""
    if age_h_raw.lower() == "all":
        return tweets
    try:
        age_h = float(age_h_raw)
    except ValueError:
        age_h = 48.0
    cutoff = datetime.now(timezone.utc) - timedelta(hours=age_h)
    return [t for t in tweets if (ca := _parse_tweet_created_at(t)) is not None and ca >= cutoff]


def _query_one(query: dict[str, list[str]], key: str, default: str) -> str:
    values = query.get(key)
    if not values:
        return default
    return values[0] or default


def _limit(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError:
        return 100
    return max(1, min(parsed, 2000))


def main() -> int:
    args = build_parser().parse_args()
    server = DashboardServer(
        (args.host, args.port),
        DashboardHandler,
        data_file=Path(args.data_file).expanduser(),
        log_file=Path(args.log_file).expanduser(),
        account=args.account,
    )
    if args.host == "0.0.0.0":
        print(
            f"Serving read-only dashboard on all interfaces at http://0.0.0.0:{args.port} "
            f"(LAN: http://<this-mac-lan-ip>:{args.port})",
            flush=True,
        )
    else:
        print(f"Serving read-only dashboard at http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
