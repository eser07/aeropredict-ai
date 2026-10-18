"""P9 saved-data, missing-data and HTTP regression suite. No RPC or dataset writes."""
import copy
import json
import sys
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from p9_validation import FOLDER, load_snapshot, validate_snapshot
from p9_weekly_950 import weekly_breakdown_950
from serve_pool_research_950 import make_server


class SnapshotTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.docs, cls.summary = load_snapshot()

    def test_canonical_inventory_and_counts(self):
        self.assertEqual(self.summary["active_pools"], 950)
        self.assertEqual(self.summary["usd_complete"], 904)
        self.assertEqual(self.summary["unresolved_pairs"], [1130])

    def test_wrong_chain(self):
        docs=copy.deepcopy(self.docs);docs[0]["chain_id"]=1
        with self.assertRaises(ValueError):validate_snapshot(*docs)

    def test_duplicate_pool(self):
        docs=copy.deepcopy(self.docs);docs[0]["pools"][1]=docs[0]["pools"][0]
        with self.assertRaises(ValueError):validate_snapshot(*docs)

    def test_wrong_pair_address(self):
        docs=copy.deepcopy(self.docs);docs[1]["pools"][0]["pool_address"]="0x"+"f"*40
        with self.assertRaises(ValueError):validate_snapshot(*docs)

    def test_wrong_collection_week(self):
        docs=copy.deepcopy(self.docs);docs[0]["collection_epoch_utc"]="2026-10-08T00:00:00+00:00"
        with self.assertRaises(ValueError):validate_snapshot(*docs)

    def test_wrong_summary_count(self):
        docs=copy.deepcopy(self.docs);docs[0]["no_observed_rewards_pool_count"]=0
        with self.assertRaises(ValueError):validate_snapshot(*docs)

    def test_incomplete_usd_not_full_average(self):
        docs=copy.deepcopy(self.docs);pool=next(p for p in docs[0]["pools"] if not p["usd_coverage_complete"]);pool["avg_pool_usd_per_week_at_collection_quote"]="0"
        with self.assertRaises(ValueError):validate_snapshot(*docs)

    def test_wrong_manifest_assignment(self):
        docs=copy.deepcopy(self.docs);docs[3]["batches"][0]["pool_indexes"][0]=9999
        with self.assertRaises(ValueError):validate_snapshot(*docs)


class WeeklyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        docs,_=load_snapshot();cls.pool=next(p for p in docs[0]["pools"] if p["index"]==64)
        cls.source=json.loads((FOLDER/"incentives_batch_001.json").read_text(encoding="utf-8"))
        cls.fees=json.loads((FOLDER/"fee_histories_batch_001.json").read_text(encoding="utf-8"))

    def read(self,doc,pool=None):
        return weekly_breakdown_950(pool or self.pool,FOLDER,lambda path: self.fees if path.name.startswith("fee_histories") else doc)

    def token(self,doc):
        row=next(p for p in doc["pools"] if p["index"]==64)
        return next(t for t in row["fees"] if any(int(w["raw"])>0 for w in t["last_four_weeks"]))

    def test_64_verified_shares_and_times(self):
        result=self.read(self.source)
        self.assertEqual(result["trend"]["bribes_share_percent"],"0.06")
        self.assertTrue(result["source_times"]["fees_file_collected_at_utc"])

    def test_unrelated_pool_quote_time_excluded(self):
        doc=copy.deepcopy(self.source)
        doc["prices"]["0x"+"f"*40]={"price_usd":"1", "price_timestamp_utc":"2099-12-31T00:00:00+00:00"}
        self.assertNotEqual(self.read(doc)["source_times"]["latest_quote_utc"],"2099-12-31T00:00:00+00:00")

    def test_fractional_raw_rejected(self):
        doc=copy.deepcopy(self.source);self.token(doc)["last_four_weeks"][0]["raw"]="0.5"
        with self.assertRaises(ValueError):self.read(doc)

    def test_uint256_overflow_rejected(self):
        doc=copy.deepcopy(self.source);self.token(doc)["last_four_weeks"][0]["raw"]=str(2**256)
        with self.assertRaises(ValueError):self.read(doc)

    def test_wrong_week_rejected(self):
        doc=copy.deepcopy(self.source);self.token(doc)["last_four_weeks"][0]["epoch_start_utc"]="2026-01-01T00:00:00+00:00"
        with self.assertRaises(ValueError):self.read(doc)

    def test_missing_price_remains_unknown(self):
        doc=copy.deepcopy(self.source);token=self.token(doc);doc["prices"][token["token_address"].lower()]["price_usd"]=None
        pool=copy.deepcopy(self.pool);pool["usd_coverage_complete"]=False
        result=self.read(doc,pool)
        self.assertIsNone(result["weeks"][0]["fees_usd"])
        self.assertIsNone(result["weeks"][0]["total_usd"])
        self.assertNotEqual(result["trend"]["status"],"available")

    def test_nonpositive_price_does_not_fabricate_zero(self):
        doc=copy.deepcopy(self.source);doc["prices"][self.token(doc)["token_address"].lower()]["price_usd"]="0"
        pool=copy.deepcopy(self.pool);pool["usd_coverage_complete"]=False
        self.assertIsNone(self.read(doc,pool)["weeks"][0]["fees_usd"])

    def test_zero_reward_without_price_is_known_zero(self):
        doc=copy.deepcopy(self.source);row=next(p for p in doc["pools"] if p["index"]==64)
        for token in row["fees"]+row["bribes"]:
            for week in token["last_four_weeks"]:week["raw"]="0"
        doc["prices"]={}
        pool=copy.deepcopy(self.pool);pool["weekly_pool_usd_at_collection_quote"]=["0"]*4
        result=self.read(doc,pool)
        self.assertEqual(result["trend"]["total_four_week_usd"],"0")
        self.assertIsNone(result["trend"]["bribes_share_percent"])


class HttpTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=make_server(0);cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.url="http://127.0.0.1:"+str(cls.server.server_address[1])

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join()

    def request(self,path,method="GET"):
        try:
            with urlopen(Request(self.url+path,method=method),timeout=10) as response:return response.status,response.read()
        except HTTPError as error:return error.code,error.read()

    def test_saved_metadata_endpoint(self):
        code,body=self.request("/api/status");self.assertEqual(code,200);self.assertEqual(json.loads(body)["active_pools"],950)

    def test_snapshot_apis(self):
        for path in ("/api/research","/api/pairs"):
            with self.subTest(path=path):self.assertEqual(len(json.loads(self.request(path)[1])["pools"]),950)

    def test_valid_weekly(self):
        self.assertEqual(json.loads(self.request("/api/weekly?index=35")[1])["trend"]["bribes_share_percent"],"94.61")

    def test_invalid_queries(self):
        for path in ("/api/weekly","/api/weekly?index=-1","/api/weekly?index=35&index=64","/api/weekly?index=64&foo=1"):
            with self.subTest(path=path):self.assertEqual(self.request(path)[0],400)

    def test_unknown_pool_and_secret_path(self):
        for path in ("/api/weekly?index=9999","/.env","/../.git/config"):
            with self.subTest(path=path):self.assertEqual(self.request(path)[0],404)

    def test_write_requests_rejected(self):
        self.assertEqual(self.request("/api/research","POST")[0],405)

    def test_math_asset(self):
        code,body=self.request("/research-math.js");self.assertEqual(code,200);self.assertIn(b"validateWeekly",body)


if __name__=="__main__":unittest.main(verbosity=2)
