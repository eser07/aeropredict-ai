"""Offline checks for the separate read-only 928-pool research web server."""
import importlib.util
import json
import sys
from decimal import Decimal
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
SPEC = importlib.util.spec_from_file_location(
    "serve_pool_research", SCRIPTS / "serve_pool_research.py",
)
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


def fixture():
    pools = []
    for i in range(928):
        pools.append({
            "index": i + 1,
            "collection_epoch_utc": m.EPOCHS[0] if i < 375 else m.EPOCHS[1],
            "usd_coverage_complete": i < 885,
            "token_rewards": [],
            "no_observed_rewards": i < 239,
        })
    return {
        "chain_id": 8453,
        "inventory_pool_count": 928,
        "audited_pool_count": 928,
        "audited_usd_complete_pool_count": 885,
        "by_collection_epoch": {
            m.EPOCHS[0]: {"audited_pools": 375},
            m.EPOCHS[1]: {"audited_pools": 553},
        },
        "pools": pools,
    }


class TestResearchServer(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data = self.root / "dataset.json"
        self.data.write_text(json.dumps(fixture()), encoding="utf-8")
        self.html = self.root / "index.html"
        self.html.write_text("<html><body>Local research</body></html>", encoding="utf-8")
        (self.root / "research.js").write_text("// test js", encoding="utf-8")
        (self.root / "research.css").write_text("body{}", encoding="utf-8")
        self.server = m.make_server(port=0, data_path=self.data, html_path=self.html)
        self.pairs = self.root / "pairs.json"
        self.server.pair_path = self.pairs  # Never read user-owned production data.
        self.host = "http://127.0.0.1:" + str(self.server.server_port)
        self.thread = threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.05},
            daemon=True,
        )
        self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.server_close()

    def get(self, path):
        with urllib.request.urlopen(self.host + path, timeout=2) as resp:
            return resp.status, resp.headers, resp.read()

    def test_serves_928_local_research_json(self):
        code, headers, body = self.get("/api/research")
        self.assertEqual(code, 200)
        self.assertIn("application/json", headers["Content-Type"])
        self.assertEqual(json.loads(body)["audited_pool_count"], 928)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertIn("default-src 'none'", headers["Content-Security-Policy"])
        self.assertEqual(self.server.server_address[0], "127.0.0.1")

    def test_pairs_api_serves_saved_contract_labels_and_missing_pair(self):
        records = [
            {
                "index": 1, "pool_address": "0x" + "a" * 40,
                "pair_label": "tBTC / WETH",
            },
            {
                "index": 1130, "pool_address": "0x" + "b" * 40,
                "pair_label": None, "error": "execution reverted",
            },
        ]
        self.pairs.write_text(
            json.dumps({"chain_id": 8453, "pools": records}), encoding="utf-8",
        )
        status, headers, body = self.get("/api/pairs")
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(payload["chain_id"], 8453)
        self.assertEqual(payload["pools"], records)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertIn("application/json", headers["Content-Type"])

    def test_pairs_api_rejects_missing_and_invalid_metadata(self):
        # All these cases must fail closed; none may leak local paths.
        valid = {"index": 1, "pool_address": "0x" + "a" * 40,
                 "pair_label": "tBTC / WETH"}
        examples = [
            None,  # metadata file missing
            {"chain_id": 1, "pools": [valid]},
            {"chain_id": 8453, "pools": "wrong type"},
            {"chain_id": 8453, "pools": [
                valid, dict(valid)]},  # duplicate index + address
            {"chain_id": 8453, "pools": [
                dict(valid, pool_address="not-an-address")]},
            {"chain_id": 8453, "pools": [
                dict(valid, index="1")]},
        ]
        for example in examples:
            with self.subTest(example=example):
                if example is None:
                    self.pairs.unlink(missing_ok=True)
                else:
                    self.pairs.write_text(json.dumps(example), encoding="utf-8")
                with self.assertRaises(urllib.error.HTTPError) as error:
                    self.get("/api/pairs")
                self.assertEqual(error.exception.code, 503)
                message = error.exception.read().decode("utf-8")
                self.assertIn("Saved trading pair metadata unavailable", message)
                self.assertNotIn(str(self.root), message)

    def test_weekly_breakdown_separates_fees_bribes_and_saved_quotes(self):
        pool = fixture()["pools"][0]
        pool.update({
            "address": "0x" + "a" * 40,
            "batch_number": 1,
            "weekly_pool_usd_at_collection_quote": ["20", "10", "5", "0"],
        })
        # Four completed weeks before Oct 8, all with the SAME saved quote.
        source = {
            "chain_id": 8453, "current_epoch_utc": m.EPOCHS[0],
            "prices": {
                "0x" + "c" * 40: {"price_usd": "2"},
                "0x" + "d" * 40: {"price_usd": "5"},
            },
            "pools": [{
                "index": 1, "pool_address": pool["address"],
                "fees": [{
                    "token_address": "0x" + "c" * 40, "decimals": 0,
                    "last_four_weeks": [
                        {"epoch_start_utc": d, "raw": str(n)}
                        for d, n in zip(
                            ["2026-09-10T00:00:00+00:00", "2026-09-17T00:00:00+00:00",
                             "2026-09-24T00:00:00+00:00", "2026-10-01T00:00:00+00:00"],
                            [0, 0, 0, 0]
                        )
                    ],
                }],
                "bribes": [{
                    "token_address": "0x" + "d" * 40, "decimals": 0,
                    "last_four_weeks": [
                        {"epoch_start_utc": d, "raw": str(n)}
                        for d, n in zip(
                            ["2026-09-10T00:00:00+00:00", "2026-09-17T00:00:00+00:00",
                             "2026-09-24T00:00:00+00:00", "2026-10-01T00:00:00+00:00"],
                            [4, 2, 1, 0]
                        )
                    ],
                }],
            }],
        }
        # Add a priced positive FEES week; keep the pool total consistent.
        source["pools"][0]["fees"][0]["last_four_weeks"][2]["raw"] = "2"
        pool["weekly_pool_usd_at_collection_quote"][2] = "9"
        folder = self.root
        (folder / "incentives_batch_001.json").write_text(
            json.dumps(source), encoding="utf-8",
        )
        research = fixture()
        research["pools"][0].update(pool)
        self.data.write_text(json.dumps(research), encoding="utf-8")
        code, headers, body = self.get("/api/weekly?index=1")
        doc = json.loads(body)
        self.assertEqual(code, 200)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual([x["week_start_utc"] for x in doc["weeks"]],
                         ["2026-09-10T00:00:00+00:00", "2026-09-17T00:00:00+00:00",
                          "2026-09-24T00:00:00+00:00", "2026-10-01T00:00:00+00:00"])
        self.assertEqual([Decimal(x["fees_usd"]) for x in doc["weeks"]],
                         [Decimal(0), Decimal(0), Decimal(4), Decimal(0)])
        self.assertEqual([Decimal(x["bribes_usd"]) for x in doc["weeks"]],
                         [Decimal(20), Decimal(10), Decimal(5), Decimal(0)])
        self.assertEqual(doc["weeks"][2]["total_usd"], "9")
        self.assertEqual(doc["trend"]["status"], "available")
        self.assertEqual(doc["trend"]["positive_priced_weeks"], 3)
        self.assertEqual(doc["trend"]["latest_change_state"], "decreased")
        self.assertEqual(doc["trend"]["latest_change_percent"], "-100.00")
        self.assertEqual(len(doc["trend"]["evidence"]), 6)
        self.assertEqual(
            {item["kind"] for item in doc["trend"]["evidence"]},
            {"BRIBES reliance", "Reward concentration", "FEES consistency",
             "Weekly change", "USD quote coverage & timing", "Voting context"},
        )

    def test_p5_weekly_trend_avoids_zero_denominators_and_missing_quotes(self):
        def weeks(fees, bribes):
            return [
                {
                    "week_start_utc": ["2026-09-10", "2026-09-17", "2026-09-24", "2026-10-01"][i] + "T00:00:00+00:00",
                    "fees_usd": str(a), "bribes_usd": str(b),
                    "total_usd": str(Decimal(a) + Decimal(b)),
                }
                for i, (a, b) in enumerate(zip(fees, bribes))
            ]

        series = weeks([10, 20, 0, 30], [10, 0, 0, 30])
        result = m.weekly_trend_summary(series, True)
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["positive_priced_weeks"], 3)
        self.assertEqual(result["fees_four_week_usd"], "60")
        self.assertEqual(result["bribes_four_week_usd"], "40")
        self.assertEqual(result["total_four_week_usd"], "100")
        self.assertEqual(result["fees_share_percent"], "60.00")
        self.assertEqual(result["bribes_share_percent"], "40.00")
        self.assertEqual(result["largest_week_share_percent"], "60.00")
        self.assertEqual(result["latest_change_state"], "new_positive_from_zero")
        self.assertIsNone(result["latest_change_percent"])

        falling = m.weekly_trend_summary(weeks([0, 0, 20, 10], [0, 0, 0, 0]), True)
        self.assertEqual(falling["latest_change_state"], "decreased")
        self.assertEqual(falling["latest_change_percent"], "-50.00")
        self.assertEqual(falling["latest_week_delta_usd"], "-10")

        zeros = m.weekly_trend_summary(weeks([0] * 4, [0] * 4), True)
        self.assertEqual(zeros["latest_change_state"], "both_zero")
        self.assertEqual(zeros["positive_priced_weeks"], 0)
        self.assertIsNone(zeros["fees_share_percent"])
        self.assertIsNone(zeros["largest_week_share_percent"])
        self.assertIsNone(zeros["latest_change_percent"])

        self.assertEqual(
            m.weekly_trend_summary(series, False)["status"],
            "unavailable_incomplete_usd",
        )
        series[1]["fees_usd"] = None
        self.assertEqual(
            m.weekly_trend_summary(series, True)["status"],
            "unavailable_incomplete_usd",
        )
        series[1]["fees_usd"] = "20"
        series[1]["total_usd"] = "999"
        with self.assertRaisesRegex(ValueError, "mismatch"):
            m.weekly_trend_summary(series, True)

    def test_p51_evidence_flags_heavy_bribes_low_baseline_and_fee_presence(self):
        starts = ["2026-09-10", "2026-09-17", "2026-09-24", "2026-10-01"]
        # Four positive total weeks, but FEES and BRIBES each appeared only twice.
        fees = [10, 0, 5, 0]
        bribes = [0, 500, 0, 100]
        weeks = [
            {"week_start_utc": date + "T00:00:00+00:00",
             "fees_usd": str(a), "bribes_usd": str(b),
             "total_usd": str(a + b)}
            for date, a, b in zip(starts, fees, bribes)
        ]
        observed = m.weekly_trend_summary(weeks, True)
        self.assertEqual(observed["positive_priced_weeks"], 4)
        signals = {item["kind"]: item for item in observed["evidence"]}
        self.assertEqual(len(signals), 6)
        self.assertEqual(signals["BRIBES reliance"]["level"], "caution")
        self.assertIn("97.56%", signals["BRIBES reliance"]["text"])
        self.assertIn("2/4 weeks", signals["BRIBES reliance"]["text"])
        self.assertEqual(signals["Reward concentration"]["level"], "caution")
        self.assertIn("81.30%", signals["Reward concentration"]["text"])
        self.assertIn("2/4 weeks", signals["FEES consistency"]["text"])
        self.assertIn("BRIBES in 2/4", signals["FEES consistency"]["text"])
        self.assertEqual(signals["Weekly change"]["level"], "caution")
        self.assertIn("low baseline", signals["Weekly change"]["text"])
        self.assertIn("NOT historical week prices",
                      signals["USD quote coverage & timing"]["text"])
        self.assertIn("other Base blocks", signals["Voting context"]["text"])
        self.assertNotIn("APR", repr(signals))
        self.assertNotIn("forecast return", repr(signals))

    def test_p51_evidence_distinguishes_fees_only_zero_and_unknown(self):
        dates = ["2026-09-10", "2026-09-17", "2026-09-24", "2026-10-01"]
        def series(fees, bribes):
            return [
                {"week_start_utc": d + "T00:00:00+00:00",
                 "fees_usd": str(a), "bribes_usd": str(b),
                 "total_usd": str(a + b)}
                for d, a, b in zip(dates, fees, bribes)
            ]
        steady = m.weekly_trend_summary(series([60] * 4, [0] * 4), True)
        notes = {item["kind"]: item for item in steady["evidence"]}
        self.assertEqual(notes["BRIBES reliance"]["level"], "context")
        self.assertIn("0.00%", notes["BRIBES reliance"]["text"])
        self.assertIn("4/4 weeks", notes["FEES consistency"]["text"])
        self.assertEqual(notes["Reward concentration"]["level"], "context")
        self.assertIn("25.00%", notes["Reward concentration"]["text"])

        zero = m.weekly_trend_summary(series([0] * 4, [0] * 4), True)
        empty = {item["kind"]: item for item in zero["evidence"]}
        self.assertEqual(empty["BRIBES reliance"]["level"], "unknown")
        self.assertEqual(empty["Reward concentration"]["level"], "unknown")
        self.assertIn("undefined", empty["Reward concentration"]["text"])
        self.assertEqual(zero["status"], "available")
        self.assertIsNone(zero["fees_share_percent"])

        from_zero = m.weekly_trend_summary(series([0, 0, 0, 5], [0] * 4), True)
        change = {item["kind"]: item for item in from_zero["evidence"]}
        self.assertIn("undefined", change["Weekly change"]["text"])
        self.assertEqual(from_zero["latest_change_state"], "new_positive_from_zero")

        missing = m.weekly_trend_summary(series([60] * 4, [0] * 4), False)
        self.assertEqual(missing["status"], "unavailable_incomplete_usd")
        self.assertEqual({n["kind"] for n in missing["evidence"]},
                         {"USD quote coverage & timing", "Voting context"})
        self.assertIn("Unknown is not $0", missing["evidence"][0]["text"])

    def test_weekly_breakdown_rejects_invalid_query_and_missing_source(self):
        for path, expected in (
            ("/api/weekly", 400), ("/api/weekly?index=abc", 400),
            ("/api/weekly?index=1&index=2", 400),
            ("/api/weekly?index=1&path=/etc/passwd", 400),
            ("/api/weekly?index=9999", 404),
            ("/api/weekly?index=1", 503),
        ):
            with self.subTest(path=path):
                with self.assertRaises(urllib.error.HTTPError) as err:
                    self.get(path)
                self.assertEqual(err.exception.code, expected)
                self.assertNotIn(str(self.root), err.exception.read().decode("utf-8"))

    def test_weekly_missing_price_is_unknown_not_zero(self):
        record = {
            "index": 1, "address": "0x" + "a" * 40,
            "collection_epoch_utc": m.EPOCHS[1],
            "batch_number": 16, "usd_coverage_complete": False,
        }
        source = {
            "chain_id": 8453, "current_epoch_utc": m.EPOCHS[1],
            "prices": {},
            "pools": [{
                "index": 1, "pool_address": record["address"],
                "fees": [{"token_address": "0x" + "c" * 40, "decimals": 18,
                          "last_four_weeks": [
                              {"epoch_start_utc": date, "raw": raw}
                              for date, raw in zip(
                                  ["2026-09-17T00:00:00+00:00",
                                   "2026-09-24T00:00:00+00:00",
                                   "2026-10-01T00:00:00+00:00",
                                   "2026-10-08T00:00:00+00:00"],
                                  ["0", "1000000000000000000", "0", "0"])
                          ]}],
                "bribes": [],
            }],
        }
        folder = self.root / "epochs" / "2026-10-15"
        folder.mkdir(parents=True)
        (folder / "incentives_batch_016.json").write_text(json.dumps(source), encoding="utf-8")
        result = m.weekly_breakdown(record, self.root)
        self.assertEqual(result["weeks"][0]["fees_usd"], "0")
        self.assertIsNone(result["weeks"][1]["fees_usd"])
        self.assertIsNone(result["weeks"][1]["total_usd"])
        self.assertEqual(result["weeks"][1]["bribes_usd"], "0")

    def rolling_votes_fixture(self):
        research = fixture()
        for p in research["pools"]:
            p["address"] = "0x" + format(p["index"], "040x")
        self.data.write_text(json.dumps(research), encoding="utf-8")
        pages = []
        for start, end, block in [(0, 180, 52646576), (180, 928, 52647814)]:
            pages.append({
                "start_offset": start, "end_offset": end,
                "block_number": block, "block_hash": "0x" + "a" * 64,
                "block_timestamp_utc": "2026-10-15T12:00:00+00:00",
                "total_voting_weight_raw": "1000000000000000000000",
                "source": "preserved_pinned_checkpoint" if start == 0 else "rolling",
                "pools": [
                    {"index": p["index"], "pool_address": p["address"],
                     "weight_raw": "2000000000000000000"}
                    for p in research["pools"][start:end]
                ],
            })
        doc = {
            "chain_id": 8453, "voter": "0x16613524e02ad97eDfeF371bC883F2F5d6C480A5",
            "expected_pools": 928, "next_offset": 928,
            "complete": True, "pages": pages,
        }
        self.server.votes_path = self.root / "votes.json"
        self.server.votes_path.write_text(json.dumps(doc), encoding="utf-8")
        return doc

    def test_votes_api_returns_block_specific_weights_not_reward_yield(self):
        self.rolling_votes_fixture()
        status, headers, body = self.get("/api/votes?index=1")
        first = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(first["block_number"], 52646576)
        self.assertEqual(first["vote_weight_veaero"], "2")
        self.assertEqual(first["voter_share_percent_at_block"], "0.20000000")
        self.assertEqual(first["collection_type"], "preserved_pinned_checkpoint")
        self.assertIs(first["synchronized_with_reward_epochs"], False)
        self.assertNotIn("apr", json.dumps(first).lower())
        self.assertEqual(headers["Cache-Control"], "no-store")
        status, _, body = self.get("/api/votes?index=928")
        last = json.loads(body)
        self.assertEqual(last["block_number"], 52647814)
        self.assertEqual(last["vote_weight_veaero"], "2")

    def test_votes_api_rejects_missing_invalid_and_corrupted_sources(self):
        self.rolling_votes_fixture()
        for path, expected in (
            ("/api/votes", 400), ("/api/votes?index=abc", 400),
            ("/api/votes?index=1&index=2", 400),
            ("/api/votes?index=1&path=x", 400),
            ("/api/votes?index=9999", 404),
        ):
            with self.subTest(path=path):
                with self.assertRaises(urllib.error.HTTPError) as error:
                    self.get(path)
                self.assertEqual(error.exception.code, expected)
        original = json.loads(self.server.votes_path.read_text())
        examples = [
            dict(original, chain_id=1),
            dict(original, complete=False),
            dict(original, next_offset=927),
            {**original, "pages": [dict(original["pages"][0], end_offset=179),
                                   original["pages"][1]]},
        ]
        invalid_address = json.loads(json.dumps(original))
        invalid_address["pages"][1]["pools"][0]["pool_address"] = "0x" + "f" * 40
        examples.append(invalid_address)
        for wrong in examples:
            with self.subTest(invalid=wrong.get("chain_id"), pages=len(wrong["pages"])):
                self.server.votes_path.write_text(json.dumps(wrong))
                with self.assertRaises(urllib.error.HTTPError) as error:
                    self.get("/api/votes?index=1")
                self.assertEqual(error.exception.code, 503)
                self.assertNotIn(str(self.root), error.exception.read().decode())
        self.server.votes_path.unlink()
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.get("/api/votes?index=1")
        self.assertEqual(error.exception.code, 503)

    def test_only_explicit_frontend_routes(self):
        for path, mime in (
            ("/", "text/html"), ("/index.html", "text/html"),
            ("/research.js", "javascript"), ("/research.css", "text/css"),
        ):
            status, headers, _ = self.get(path)
            self.assertEqual(status, 200)
            self.assertIn(mime, headers["Content-Type"])
        for path in ("/.env", "/.git/config", "/../../../.env", "/api/results"):
            with self.assertRaises(urllib.error.HTTPError) as context:
                self.get(path)
            self.assertEqual(context.exception.code, 404)

    def test_malformed_data_503_without_leaking_files(self):
        self.data.write_text('{"chain_id": 8453}', encoding="utf-8")
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.get("/api/research")
        self.assertEqual(error.exception.code, 503)
        body = error.exception.read().decode("utf-8")
        self.assertIn("build_full_pool_research_base.py", body)
        self.assertNotIn(str(self.root), body)

    def test_wrong_chain_and_duplicate_indices_rejected(self):
        doc = fixture()
        doc["chain_id"] = 1
        with self.assertRaisesRegex(ValueError, "Base Mainnet"):
            m.validate_research(doc)
        doc["chain_id"] = 8453
        doc["pools"][1]["index"] = doc["pools"][0]["index"]
        with self.assertRaisesRegex(ValueError, "duplicate pool"):
            m.validate_research(doc)

    def test_post_method_blocked(self):
        req = urllib.request.Request(
            self.host + "/api/research", data=b'{"x":1}', method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(req, timeout=2)
        self.assertEqual(error.exception.code, 405)


if __name__ == "__main__":
    unittest.main()
