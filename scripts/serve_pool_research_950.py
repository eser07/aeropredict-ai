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
from p9_validation import load_snapshot
from p9_contract_metadata import load_special_contracts
from p9_votes_950 import load_vote_sources, vote_detail_950

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

        if path == "/research-math.js":
            self.reply(200, "text/javascript; charset=utf-8", (HTML.parent / "research-math.js").read_bytes())
            return

        if path == "/api/status":
            self.reply(200, "application/json; charset=utf-8", json.dumps(self.server.snapshot_summary).encode("utf-8"))
            return

        if path == "/api/pairs":
            self.reply(200, "application/json; charset=utf-8", self.server.pairs_bytes)
            return

        if path == "/api/research":
            self.reply(200, "application/json; charset=utf-8",
                       self.server.research_bytes)
            return

        if path in ("/api/weekly", "/api/votes"):
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
                if path == "/api/votes":
                    if self.server.vote_sources is None:
                        self.error_json(503, "Saved vote observations unavailable")
                        return
                    result = vote_detail_950(pool, self.server.vote_sources)
                else:
                    result = weekly_breakdown_950(pool, FOLDER)
            except (OSError, ValueError, KeyError, TypeError):
                self.error_json(503, "Saved weekly data unavailable")
                return
            self.reply(200, "application/json; charset=utf-8",
                       json.dumps(result).encode("utf-8"))
            return

        super().do_GET()

def make_server(port=8768):
    docs, summary = load_snapshot()
    research, pairs, _, _ = docs
    server = ThreadingHTTPServer(("127.0.0.1", port), P9Handler)
    server.research_bytes = json.dumps(research, ensure_ascii=False).encode("utf-8")
    try:
        annotated_pairs = load_special_contracts(pairs, research)
        summary["classified_special_contracts"] = [1130]
        summary["contract_metadata_available"] = True
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        annotated_pairs = pairs
        summary["classified_special_contracts"] = []
        summary["contract_metadata_available"] = False
    summary["unclassified_pair_records"] = [i for i in summary["unresolved_pairs"] if i not in summary["classified_special_contracts"]]
    server.pairs_bytes = json.dumps(annotated_pairs, ensure_ascii=False).encode("utf-8")
    server.snapshot_summary = summary
    server.pool_map = {p["index"]: p for p in research["pools"]}
    try:
        server.vote_sources = load_vote_sources(research)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, ArithmeticError):
        server.vote_sources = None
    summary["recorded_vote_pools"] = len(server.vote_sources["covered"]) if server.vote_sources else None
    server.pair_path = PAIRS
    server.html_path = HTML
    server.js_path = HTML.parent / "research.js"
    server.css_path = HTML.parent / "research.css"
    return server


def main():
    with make_server() as server:
        print("P9 SERVER VERIFIED: 950 pools", flush=True)
        print("http://localhost:8768/", flush=True)
        print("Read-only historical research. Ctrl+C to stop.", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
