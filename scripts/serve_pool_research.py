#!/usr/bin/env python3
"""Read-only standalone local UI for the 928-pool, two-epoch P2 research data.

Runs on a SEPARATE loopback port (8766), never changes the existing 8765
dashboard, data, scheduled refresh tasks, or any on-chain state.
Only explicit read-only GET routes; no directory serving and no public binding.
"""
import argparse
import json
import sys
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation, localcontext
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "research" / "index.html"
PAIRS = ROOT / "data" / "pool_pairs_928_base.json"
VOTES = ROOT / "data" / "p4_rolling_votes_base" / "snapshot.json"
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

def saved_decimal(value):
    """Parse nonnegative, finite quantities without float rounding."""
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("Invalid saved token amount or quote") from exc
    if not number.is_finite() or number < 0:
        raise ValueError("Invalid saved token amount or quote")
    return number


def weekly_trend_summary(weeks, usd_coverage_complete):
    """Descriptive P5 history; never infer APR, forecast or vote-based yield.

    No percentage metrics if ANY reward quote is incomplete. Percent changes
    from a zero baseline are undefined rather than infinite.
    """
    unavailable = {
        "status": "unavailable_incomplete_usd",
        "reason": "Incomplete saved USD quotes prevent a reliable four-week total",
    }
    if not usd_coverage_complete:
        return unavailable
    if not isinstance(weeks, list) or len(weeks) != 4:
        raise ValueError("Expected four saved reward weeks")
    with localcontext() as ctx:
        ctx.prec = 80
        values = []
        for w in weeks:
            if not isinstance(w, dict) or any(
                w.get(name) is None for name in ("fees_usd", "bribes_usd", "total_usd")
            ):
                return unavailable
            fees = saved_decimal(w["fees_usd"])
            bribes = saved_decimal(w["bribes_usd"])
            total = saved_decimal(w["total_usd"])
            if fees + bribes != total:
                raise ValueError("Saved FEES / BRIBES weekly total mismatch")
            values.append((fees, bribes, total))
        fees_sum = sum((w[0] for w in values), Decimal(0))
        bribes_sum = sum((w[1] for w in values), Decimal(0))
        total_sum = fees_sum + bribes_sum

        def percent(num, denominator):
            if not denominator:
                return None
            return format((100 * num / denominator).quantize(Decimal("0.01")), "f")

        last = values[-1][2]
        previous = values[-2][2]
        delta = last - previous
        if previous == 0 and last == 0:
            state = "both_zero"
        elif previous == 0:
            state = "new_positive_from_zero"
        elif delta > 0:
            state = "increased"
        elif delta < 0:
            state = "decreased"
        else:
            state = "unchanged"
        peak = max(range(4), key=lambda i: values[i][2])
        return {
            "status": "available",
            "positive_priced_weeks": sum(w[2] > 0 for w in values),
            "fees_four_week_usd": str(fees_sum),
            "bribes_four_week_usd": str(bribes_sum),
            "total_four_week_usd": str(total_sum),
            "fees_share_percent": percent(fees_sum, total_sum),
            "bribes_share_percent": percent(bribes_sum, total_sum),
            "largest_week_share_percent": percent(values[peak][2], total_sum),
            "largest_week_start_utc": weeks[peak]["week_start_utc"] if total_sum else None,
            "previous_week_usd": str(previous),
            "latest_week_usd": str(last),
            "latest_week_delta_usd": str(delta),
            "latest_change_percent": percent(delta, previous),
            "latest_change_state": state,
            "denominator_policy": "Percent change unavailable if previous week was $0",
            "interpretation": "Past observations priced at the collection-time quote; not yield or forecast",
        }


def weekly_breakdown(pool, batch_root):
    """Reprice four saved reward weeks at their batch's SAVED quote, never live."""
    epoch = pool["collection_epoch_utc"]
    batch = pool.get("batch_number")
    if epoch not in EPOCHS or type(batch) is not int or not 1 <= batch <= 38:
        raise ValueError("Invalid batch identity")
    folder = Path(batch_root)
    if epoch == EPOCHS[1]:
        folder = folder / "epochs" / "2026-10-15"
    source = folder / f"incentives_batch_{batch:03d}.json"
    doc = json.loads(source.read_text(encoding="utf-8"))
    if doc.get("chain_id") != 8453 or doc.get("current_epoch_utc") != epoch:
        raise ValueError("Saved incentives do not match collection epoch")
    rows = doc.get("pools")
    if not isinstance(rows, list):
        raise ValueError("Saved incentives missing pool records")
    matching = [x for x in rows if x.get("index") == pool["index"]]
    if len(matching) != 1 or (
        matching[0].get("pool_address", "").lower() != pool["address"].lower()
    ):
        raise ValueError("Saved pool identity differs from research dataset")
    row = matching[0]
    prices = doc.get("prices")
    if not isinstance(prices, dict):
        raise ValueError("Saved token prices unavailable")
    start = datetime.fromisoformat(epoch)
    expected_weeks = [
        (start - timedelta(days=7 * (4 - i))).isoformat() for i in range(4)
    ]
    weeks = [{"week_start_utc": w, "fees_usd": None,
              "bribes_usd": None, "total_usd": None} for w in expected_weeks]
    with localcontext() as context:
        context.prec = 80
        amounts = {}
        for kind in ("fees", "bribes"):
            tokens = row.get(kind)
            if not isinstance(tokens, list):
                raise ValueError("Saved reward category unavailable")
            values = [Decimal(0) for _ in range(4)]
            unknown = [False] * 4
            for token in tokens:
                address = token.get("token_address")
                decimals = token.get("decimals")
                history = token.get("last_four_weeks")
                if (not isinstance(address, str) or
                    (decimals is not None and
                     (type(decimals) is not int or not 0 <= decimals <= 36)) or
                    not isinstance(history, list) or len(history) != 4):
                    raise ValueError("Malformed saved token history")
                quote = prices.get(address.lower())
                price = None
                if isinstance(quote, dict) and quote.get("price_usd") is not None:
                    price = saved_decimal(quote["price_usd"])
                for i, entry in enumerate(history):
                    if entry.get("epoch_start_utc") != expected_weeks[i]:
                        raise ValueError("Saved reward week mismatch")
                    raw = saved_decimal(entry.get("raw"))
                    if raw and (price is None or decimals is None):
                        unknown[i] = True
                    elif price is not None and decimals is not None:
                        values[i] += raw / (Decimal(10) ** decimals) * price
            amounts[kind] = [None if unknown[i] else values[i] for i in range(4)]
        for i, week in enumerate(weeks):
            fees = amounts["fees"][i]
            bribes = amounts["bribes"][i]
            total = fees + bribes if fees is not None and bribes is not None else None
            week.update({
                "fees_usd": str(fees) if fees is not None else None,
                "bribes_usd": str(bribes) if bribes is not None else None,
                "total_usd": str(total) if total is not None else None,
            })
            if pool["usd_coverage_complete"]:
                saved = pool.get("weekly_pool_usd_at_collection_quote")
                if (not isinstance(saved, list) or len(saved) != 4 or
                    total is None or abs(total - saved_decimal(saved[i])) > Decimal("0.00000001")):
                    raise ValueError("Weekly split does not reconcile with audited pool total")
    return {
        "index": pool["index"],
        "address": pool["address"],
        "collection_epoch_utc": epoch,
        "usd_coverage_complete": pool["usd_coverage_complete"],
        "quote_policy": "Batch-saved token USD prices, not historical week prices",
        "weeks": weeks,
        "trend": weekly_trend_summary(weeks, pool["usd_coverage_complete"]),
    }


def rolling_vote_detail(votes, research, idx):
    """Validate the complete independent rolling cohort before serving one pool.

    Every pool weight is paired ONLY with the Voter totalWeight of its own
    observation block. Neither cross-page sums nor yield estimates are made.
    """
    if (not isinstance(votes, dict) or votes.get("chain_id") != 8453 or
            str(votes.get("voter", "")).lower() != "0x16613524e02ad97edfef371bc883f2f5d6c480a5" or
            votes.get("expected_pools") != 928 or
            votes.get("next_offset") != 928 or votes.get("complete") is not True):
        raise ValueError("Rolling vote dataset is incomplete or on wrong chain")
    pages = votes.get("pages")
    if not isinstance(pages, list) or not pages:
        raise ValueError("Missing rolling vote observation pages")
    known = {p["index"]: p["address"].lower() for p in research["pools"]}
    if len(known) != 928:
        raise ValueError("Research inventory identities missing")
    first = 0
    found = None
    seen = set()
    with localcontext() as ctx:
        ctx.prec = 80
        for page in pages:
            if not isinstance(page, dict):
                raise ValueError("Invalid observation page")
            end = page.get("end_offset")
            number = page.get("block_number")
            rows = page.get("pools")
            hash_value = page.get("block_hash")
            stamp = page.get("block_timestamp_utc")
            total = page.get("total_voting_weight_raw")
            if (type(end) is not int or end <= first or end > 928 or
                    page.get("start_offset") != first or
                    type(number) is not int or number <= 0 or
                    not isinstance(hash_value, str) or
                    re.fullmatch(r"0x[0-9a-fA-F]{64}", hash_value) is None or
                    not isinstance(stamp, str) or
                    not isinstance(rows, list) or len(rows) != end - first or
                    not isinstance(total, str) or not total.isdecimal()):
                raise ValueError("Invalid rolling vote page identity or range")
            datetime.fromisoformat(stamp)
            total_raw = Decimal(total)
            for row in rows:
                if not isinstance(row, dict):
                    raise ValueError("Invalid pool vote observation")
                index = row.get("index")
                address = row.get("pool_address")
                raw = row.get("weight_raw")
                if (type(index) is not int or
                        not isinstance(address, str) or
                        not isinstance(raw, str) or not raw.isdecimal() or
                        known.get(index) != address.lower() or index in seen):
                    raise ValueError("Rolling vote pool does not match research inventory")
                seen.add(index)
                first += 1
                if index == idx:
                    weight = Decimal(raw)
                    found = {
                        "index": index, "address": address.lower(),
                        "block_number": number, "block_timestamp_utc": stamp,
                        "collection_type": page.get("source", "rolling"),
                        "vote_weight_raw": raw,
                        "vote_weight_veaero": format(weight / Decimal(10) ** 18, "f"),
                        "voter_total_weight_raw": total,
                        "voter_total_weight_veaero": format(total_raw / Decimal(10) ** 18, "f"),
                        "voter_share_percent_at_block":
                            format(weight * 100 / total_raw, ".8f") if total_raw else None,
                        "provenance": "rolling per-page pinned block",
                        "synchronized_with_reward_epochs": False,
                    }
            if first != end:
                raise ValueError("Invalid contiguous observation pages")
    if first != 928 or len(seen) != 928 or found is None:
        raise ValueError("Rolling snapshot does not cover all research pools")
    return found


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
        elif path == "/api/votes":
            try:
                query = parse_qs(urlsplit(self.path).query, strict_parsing=True)
                if set(query) != {"index"} or len(query["index"]) != 1:
                    raise ValueError("Invalid query")
                token = query["index"][0]
                if not token.isdecimal() or len(token) > 4:
                    raise ValueError("Invalid index")
                idx = int(token)
            except (ValueError, KeyError):
                self.error_json(400, "Expected one numeric pool index")
                return
            try:
                research = validate_research(
                    json.loads(self.server.data_path.read_text(encoding="utf-8"))
                )
            except (OSError, ValueError, TypeError, KeyError):
                self.error_json(503, "Saved research data unavailable")
                return
            if not any(p["index"] == idx for p in research["pools"]):
                self.error_json(404, "Pool not present in saved research")
                return
            try:
                doc = json.loads(self.server.votes_path.read_text(encoding="utf-8"))
                payload = rolling_vote_detail(doc, research, idx)
            except (OSError, ValueError, TypeError, KeyError, AttributeError, InvalidOperation):
                self.error_json(503, "Validated rolling vote observations unavailable")
                return
            self.reply(200, "application/json; charset=utf-8",
                       json.dumps(payload).encode("utf-8"))
        elif path == "/api/weekly":
            try:
                query = parse_qs(urlsplit(self.path).query, strict_parsing=True)
                if set(query) != {"index"} or len(query["index"]) != 1:
                    raise ValueError("Invalid query")
                token = query["index"][0]
                if not token.isdecimal() or len(token) > 4:
                    raise ValueError("Invalid index")
                idx = int(token)
            except (ValueError, KeyError):
                self.error_json(400, "Expected one numeric pool index")
                return
            try:
                source = json.loads(self.server.data_path.read_text(encoding="utf-8"))
                validate_research(source)
            except (OSError, ValueError, TypeError, KeyError):
                self.error_json(503, "Saved research data unavailable")
                return
            matched = [p for p in source["pools"] if p["index"] == idx]
            if len(matched) != 1:
                self.error_json(404, "Pool not present in saved research")
                return
            try:
                payload = weekly_breakdown(matched[0], self.server.batch_root)
            except (OSError, ValueError, TypeError, KeyError, AttributeError):
                self.error_json(503, "Saved weekly reward breakdown unavailable")
                return
            self.reply(200, "application/json; charset=utf-8",
                       json.dumps(payload).encode("utf-8"))
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
    server.batch_root = server.data_path.parent
    server.pair_path = PAIRS
    server.votes_path = VOTES
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
