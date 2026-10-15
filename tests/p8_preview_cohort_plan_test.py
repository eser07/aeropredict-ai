"""P8.2 unit tests: inspect a frozen historical subset with no side effects."""
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from p8_preview_cohort_plan import (  # noqa: E402
    choose_epoch, plan_frozen_subset,
)


def old_manifest():
    groups = []
    for i in range(38):
        ids = list(range(i * 25, min((i + 1) * 25, 928)))
        groups.append({"number": i + 1, "pool_count": len(ids), "pool_indexes": ids})
    return {
        "chain_id": 8453, "snapshot_block_number": 52595092,
        "inventory_sha256": "a" * 64, "batch_count": 38,
        "all_batches_pool_count": 928, "batches": groups,
    }


NOW = datetime(2026, 10, 15, 20, 33, tzinfo=timezone.utc)


class P8PreviewTests(unittest.TestCase):
    def test_week_preview_defaults_to_next_thursday(self):
        self.assertEqual(choose_epoch(None, NOW).isoformat(),
                         "2026-10-22T00:00:00+00:00")
        self.assertEqual(choose_epoch("2026-10-22", NOW).isoformat(),
                         "2026-10-22T00:00:00+00:00")

    def test_prevents_old_and_non_thursday_cohorts(self):
        for invalid in ("2026-10-15", "2026-10-14", "2026-10-16", "2026/10/22"):
            with self.subTest(epoch=invalid):
                with self.assertRaises(ValueError):
                    choose_epoch(invalid, NOW)

    def test_fixed_historical_identity_coverage_and_isolated_path(self):
        cohort = plan_frozen_subset(
            old_manifest(), choose_epoch("2026-10-22", NOW), NOW
        )
        self.assertEqual(cohort["total_pools"], 928)
        self.assertEqual(cohort["total_batches"], 38)
        self.assertEqual(cohort["max_pools_per_batch"], 25)
        self.assertEqual(cohort["input_identity_count"], 928)
        self.assertIn("p8_research_cohorts", cohort["target_preview_only"])
        self.assertIn("epoch_2026-10-22", cohort["target_preview_only"])
        self.assertIn("frozen_block_52595092", cohort["target_preview_only"])
        self.assertIn("NOT verified currently active", cohort["scope"])
        self.assertFalse(cohort["new_live_collection_enabled"])

    def test_rejects_duplicate_missing_and_wrong_network(self):
        base = old_manifest()
        duplicate = old_manifest()
        duplicate["batches"][1]["pool_indexes"][0] = 0
        incomplete = old_manifest()
        incomplete["all_batches_pool_count"] = 927
        wrong_chain = old_manifest()
        wrong_chain["chain_id"] = 1
        wrong_block = old_manifest()
        wrong_block["snapshot_block_number"] = 999
        for doc in (duplicate, incomplete, wrong_chain, wrong_block):
            with self.subTest(doc=doc["batches"][1]["pool_indexes"][0]):
                with self.assertRaises(ValueError):
                    plan_frozen_subset(doc, choose_epoch(None, NOW), NOW)
        self.assertEqual(base["all_batches_pool_count"], 928)

    def test_never_collects_or_writes(self):
        code = (ROOT / "scripts" / "p8_preview_cohort_plan.py").read_text(
            encoding="utf-8"
        )
        for disallowed in (
            "save_atomic(", ".write_text(", ".write_bytes(", ".mkdir(",
            "subprocess.run(", "requests.get(", "rpc_checked(",
        ):
            self.assertNotIn(disallowed, code)
        for required in (
            "No RPC, no writes, no scheduler",
            "FROZEN INVENTORY",
            "current active status UNKNOWN",
            "REQUIRED BEFORE LIVE",
        ):
            self.assertIn(required, code)


if __name__ == "__main__":
    unittest.main()
