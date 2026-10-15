"""Offline checks for the separate read-only 928-pool research web server."""
import importlib.util
import json
import sys
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
