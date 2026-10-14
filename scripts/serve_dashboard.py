#!/usr/bin/env python3
"""AeroPredict AI read-only local dashboard server.

This only binds to loopback (127.0.0.1), serving two exact routes:
  GET /              -> dashboard/index.html
  GET /api/results   -> existing local JSON backtest output

Unlike running 'python -m http.server' from the repo root, this deliberately
does NOT expose .env, .git or any other repository files to the browser.
No external dependencies; no private keys, contracts or transactions.
"""
import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "dashboard" / "index.html"
RESULTS = ROOT / "data" / "pool_fee_backtest_base.json"


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "AeroPredictLocal/0.1"

    def send_payload(self, status, mime, data):
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(data)

    def json_response(self, status, value):
        self.send_payload(
            status,
            "application/json; charset=utf-8",
            json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8"),
        )

    def do_GET(self):
        path = urlsplit(self.path).path
        if path in ("/", "/index.html"):
            try:
                data = HTML.read_bytes()
            except OSError as exc:
                self.json_response(500, {"error": "Dashboard HTML unavailable", "detail": str(exc)})
                return
            self.send_payload(200, "text/html; charset=utf-8", data)
            return

        if path == "/api/results":
            if not RESULTS.is_file():
                self.json_response(
                    404,
                    {
                        "error": "Backtest results not found",
                        "instruction": "python scripts/backtest_pool_fees.py",
                    },
                )
                return
            try:
                raw = json.loads(RESULTS.read_text(encoding="utf-8"))
                if raw.get("chain_id") != 8453:
                    raise ValueError("Expected Base chain ID 8453")
                if not isinstance(raw.get("results"), list):
                    raise ValueError("Backtest JSON has no results list")
            except (OSError, ValueError, KeyError, TypeError) as exc:
                self.json_response(
                    500, {"error": "Cannot parse local backtest JSON", "detail": str(exc)}
                )
                return
            self.json_response(200, {"backtest": raw})
            return

        self.json_response(404, {"error": "Unknown endpoint"})

    def do_POST(self):
        self.json_response(405, {"error": "Read-only demo"})

    def log_message(self, fmt, *args):
        print("[%s] %s" % (self.log_date_time_string(), fmt % args), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765, help="Loopback port")
    args = parser.parse_args()
    if not (1024 <= args.port <= 65535):
        parser.error("--port must be between 1024 and 65535")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), DashboardHandler)
    print("AeroPredict AI | local read-only dashboard", flush=True)
    print(f"Windows browser URL: http://localhost:{args.port}/", flush=True)
    print(f"Reading results from: {RESULTS}", flush=True)
    print("Dashboard is bound to 127.0.0.1 only. Ctrl+C to stop.", flush=True)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        print("\nDashboard server stopped.", flush=True)


if __name__ == "__main__":
    try:
        main()
    except OSError as exc:
        print(f"ERROR: Unable to start local dashboard: {exc}", file=sys.stderr)
        sys.exit(1)
