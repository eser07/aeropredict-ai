"""P10 local prototype regression tests, no RPC or GenLayer consensus."""
import copy
import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from p10_local_pilot import build_pilot, evaluate, canonical_hash

class PilotTest(unittest.TestCase):
    def test_local_lifecycle(self):
        now=datetime(2026,10,18,tzinfo=timezone.utc)
        doc=build_pilot(now)
        self.assertEqual(len(doc["forecasts"]),5)
        for forecast in doc["forecasts"]:
            c=forecast["commitment"]
            self.assertEqual(evaluate(forecast,None,now)["status"],"pending")
            end=datetime.fromisoformat(c["target_end_utc"])
            self.assertEqual(evaluate(forecast,None,end)["status"],"insufficient_data")
            evidence={key:c[key] for key in ("chain_id","pool_address","token_address","target_start_utc")}
            evidence["actual_raw"]=c["predicted_raw"]
            result=evaluate(forecast,evidence,end)
            self.assertTrue(result["forecast_matched"])
            self.assertFalse(result["genlayer_consensus"])
            evidence["actual_raw"]=str(int(c["predicted_raw"])*2+100)
            self.assertFalse(evaluate(forecast,evidence,end)["forecast_matched"])
            evidence["chain_id"]=1
            self.assertEqual(evaluate(forecast,evidence,end)["status"],"unverifiable")
            bad=copy.deepcopy(forecast);bad["commitment"]["predicted_raw"]="1"
            self.assertEqual(evaluate(bad,None,end)["reason"],"commitment_mismatch")
            bad=copy.deepcopy(forecast);bad["commitment"]["created_at_utc"]=c["target_end_utc"]
            bad["commitment_sha256"]=canonical_hash(bad["commitment"])
            self.assertEqual(evaluate(bad,None,end)["reason"],"late_registration")
if __name__=="__main__":unittest.main()
