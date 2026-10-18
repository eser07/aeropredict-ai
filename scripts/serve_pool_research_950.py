#!/usr/bin/env python3
"""P9 unified 950-pool read-only local research server."""
import json
import re
from pathlib import Path
from http.server import ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs

from serve_pool_research import ResearchHandler
from p9_weekly_950 import weekly_breakdown_950
from p10_pilot_status import load_pilot_status

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "data/pool_collection_batches_base/p9_unified_research/block_52731839/registration_25"
DATA = FOLDER / "research_all_950_one_epoch.json"
PAIRS = FOLDER / "pool_pairs_950_base.json"
HTML = ROOT / "research/p9_unified/index.html"

class P9Handler(ResearchHandler):
    def do_GET(self):
        path = urlsplit(self.path).path

        if path == "/api/pilot":
            try:
                body = json.dumps(load_pilot_status(), ensure_ascii=False).encode("utf-8")
            except (OSError, ValueError, KeyError, TypeError):
                self.error_json(503, "Local pilot unavailable")
                return
            self.reply(200, "application/json; charset=utf-8", body)
            return

        if path == "/api/research":
            self.reply(200, "application/json; charset=utf-8",
                       self.server.research_bytes)
            return

        if path == "/api/votes":
            self.error_json(404, "Independent historical P4 vote data not available for all 950 pools")
            return

        if path == "/api/weekly":
            try:
                query = parse_qs(urlsplit(self.path).query, strict_parsing=True)
                if set(query) != {"index"} or len(query["index"]) != 1:
                    raise ValueError()
                raw = query["index"][0]
                if not re.fullmatch(r"[0-9]{1,4}", raw):
                    raise ValueError()
                idx = int(raw)
            except ValueError:
                self.error_json(400, "Invalid pool index")
                return

            pool = self.server.pool_map.get(idx)
            if pool is None:
                self.error_json(404, "Pool not found")
                return
            try:
                result = weekly_breakdown_950(pool, FOLDER)
            except (OSError, ValueError, KeyError, TypeError):
                self.error_json(503, "Saved weekly data unavailable")
                return
            self.reply(200, "application/json; charset=utf-8",
                       json.dumps(result).encode("utf-8"))
            return

        super().do_GET()

def main():
    research = json.loads(DATA.read_text(encoding="utf-8"))
    pairs = json.loads(PAIRS.read_text(encoding="utf-8"))
    rows = research["pools"]
    pair_rows = pairs["pools"]

    assert research["chain_id"] == pairs["chain_id"] == 8453
    assert research["snapshot_block_number"] == 52731839
    assert research["collection_epoch_utc"] == "2026-10-15T00:00:00+00:00"
    assert len(rows) == len(pair_rows) == 950
    assert research["audited_usd_complete_pool_count"] == 904
    assert research["audited_usd_incomplete_pool_count"] == 46

    pool_map = {p["index"]: p for p in rows}
    pair_map = {p["index"]: p for p in pair_rows}
    assert len(pool_map) == len(pair_map) == 950
    assert all(pair_map[i]["pool_address"].lower() == p["address"].lower()
               for i, p in pool_map.items())

    with ThreadingHTTPServer(("127.0.0.1", 8768), P9Handler) as server:
        server.research_bytes = DATA.read_bytes()
        server.pool_map = pool_map
        server.pair_path = PAIRS
        server.html_path = HTML
        server.js_path = HTML.parent / "research.js"
        server.css_path = HTML.parent / "research.css"
        print("P9 SERVER VERIFIED: 950 pools", flush=True)
        print("http://localhost:8768/", flush=True)
        print("Read-only historical research. Ctrl+C to stop.", flush=True)
        server.serve_forever()

if __name__ == "__main__":
    main()
