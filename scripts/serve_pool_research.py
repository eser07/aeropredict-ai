#!/usr/bin/env python3
"""Read-only standalone local UI for the 928-pool, two-epoch P2 research data.

Runs on a SEPARATE loopback port (8766), never changes the existing 8765
dashboard, data, scheduled refresh tasks, or any on-chain state.
Exactly three GET routes; no directory serving and no public binding.
"""
import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "research" / "index.html"
PAIRS = ROOT / "data" / "pool_pairs_928_base.json"
DATA = (ROOT / "data" / "pool_collection_batches_base" /
        "block_52595092" / "votes_25" / "research_all_928_two_epochs.json")
EPOCHS = ("2026-10-08T00:00:00+00:00", "2026-10-15T00:00:00+00:00")


def validate_research(doc):
    if not isinstance(doc, dict) or doc.get("chain_id") != 8453:
        raise ValueError("Expected Base Mainnet research dataset")
    pools = doc.get("pools")
    periods = doc.get("by_collection_epoch")
    if not isinstance(pools, list) or not isinstance(periods, dict):
        raise ValueError("Research pool records or epoch metadata missing")
    if (doc.get("inventory_pool_count") != 928 or
            doc.get("audited_pool_count") != len(pools) or
            set(periods) != set(EPOCHS)):
        raise ValueError("Research dataset inventory and epoch coverage mismatch")
    ids = [p.get("index") for p in pools]
    if len(ids) != len(set(ids)):
        raise ValueError("Research dataset contains duplicate pool indices")
    for pool in pools:
        if (pool.get("collection_epoch_utc") not in EPOCHS or
                type(pool.get("usd_coverage_complete")) is not bool or
                not isinstance(pool.get("token_rewards"), list)):
            raise ValueError("Research dataset contains invalid pool records")
    completed = sum(p["usd_coverage_complete"] for p in pools)
    if doc.get("audited_usd_complete_pool_count") != completed:
        raise ValueError("Research dataset USD coverage count mismatch")
    if sum(periods[e].get("audited_pools", -1) for e in EPOCHS) != len(pools):
        raise ValueError("Research dataset per-epoch counts do not add up")
    for epoch in EPOCHS:
        if (sum(p["collection_epoch_utc"] == epoch for p in pools) !=
                periods[epoch]["audited_pools"]):
            raise ValueError("Research dataset pool epoch mismatch")
    return doc


class ResearchHandler(BaseHTTPRequestHandler):
    server_version = "AeroPredictResearch/0.1"

    def reply(self, code, mime, data):
        self.send_response(code)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; script-src 'self'; "
                         "style-src 'self'; connect-src 'self'; "
                         "img-src 'self' data:; base-uri 'none'; "
                         "form-action 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(data)

    def error_json(self, code, message):
        raw = json.dumps({"error": message}).encode("utf-8")
        self.reply(code, "application/json; charset=utf-8", raw)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path in ("/", "/index.html"):
            try:
                body = self.server.html_path.read_bytes()
            except OSError:
                self.error_json(500, "Research page unavailable")
                return
            self.reply(200, "text/html; charset=utf-8", body)
        elif path == "/research.js":
            try:
                body = self.server.js_path.read_bytes()
            except OSError:
                self.error_json(500, "Research frontend unavailable")
                return
            self.reply(200, "application/javascript; charset=utf-8", body)
        elif path == "/research.css":
            try:
                body = self.server.css_path.read_bytes()
            except OSError:
                self.error_json(500, "Research stylesheet unavailable")
                return
            self.reply(200, "text/css; charset=utf-8", body)
        elif path == "/api/pairs":
            try:
                pair_doc = json.loads(self.server.pair_path.read_text(encoding="utf-8"))
                records = pair_doc.get("pools")
                if pair_doc.get("chain_id") != 8453 or not isinstance(records, list):
                    raise ValueError("Invalid Base pair dataset")
                unique = set()
                for record in records:
                    address = record.get("pool_address")
                    index = record.get("index")
                    if (type(index) is not int or
                            not isinstance(address, str) or
                            len(address) != 42 or
                            not address.startswith("0x")):
                        raise ValueError("Invalid pair record")
                    int(address[2:], 16)
                    if (index, address.lower()) in unique:
                        raise ValueError("Duplicate pair record")
                    unique.add((index, address.lower()))
                body = json.dumps({"chain_id": 8453, "pools": records},
                                  ensure_ascii=False).encode("utf-8")
            except (OSError, ValueError, TypeError, AttributeError, KeyError):
                self.error_json(503, "Saved trading pair metadata unavailable")
                return
            self.reply(200, "application/json; charset=utf-8", body)
        elif path == "/api/research":
            try:
                body = self.server.data_path.read_bytes()
                validate_research(json.loads(body))
            except (OSError, ValueError, TypeError, KeyError):
                self.error_json(
                    503,
                    "Validated research data unavailable. "
                    "Run python scripts/build_full_pool_research_base.py",
                )
                return
            self.reply(200, "application/json; charset=utf-8", body)
        else:
            self.error_json(404, "Not found")

    def do_POST(self):
        self.error_json(405, "Read only")


def make_server(port=8766, data_path=DATA, html_path=HTML):
    server = ThreadingHTTPServer(("127.0.0.1", port), ResearchHandler)
    server.data_path = Path(data_path)
    server.pair_path = PAIRS
    server.html_path = Path(html_path)
    server.js_path = server.html_path.parent / "research.js"
    server.css_path = server.html_path.parent / "research.css"
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Port must be between 1024 and 65535")
    if not DATA.is_file():
        parser.error("Research dataset missing: run python scripts/build_full_pool_research_base.py")
    try:
        validate_research(json.loads(DATA.read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(f"Research dataset invalid: {exc}")
    with make_server(port=args.port) as server:
        print("AeroPredict AI | separate 928-pool read-only research browser", flush=True)
        print(f"Windows browser URL: http://localhost:{args.port}/", flush=True)
        print("Source: two separately labeled October 2026 epochs; no live refresh", flush=True)
        print("Existing 8765 dashboard/hourly automation unchanged; Ctrl+C to stop", flush=True)
        try:
            server.serve_forever(poll_interval=0.2)
        except KeyboardInterrupt:
            print("\nResearch browser stopped.", flush=True)


if __name__ == "__main__":
    try:
        main()
    except OSError as exc:
        print(f"ERROR: Unable to start research browser: {exc}", file=sys.stderr)
        sys.exit(1)
