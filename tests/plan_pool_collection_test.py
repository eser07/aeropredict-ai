"""Offline tests for the P2 full-inventory collection-batch planner."""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location(
    "plan_pool_collection_base", SCRIPTS / "plan_pool_collection_base.py",
)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def sample():
    items = [
        (0, 50),
        (2, 0),
        (4, 90),
    ]
    return {
        "schema_version": 1,
        "chain_id": 8453,
        "voter": module.validate_progress.__globals__["VOTER"],
        "snapshot_block_number": 9001,
        "total_registered": 5,
        "total_voting_weight_raw": "1000",
        "scan_start": 0,
        "next_index": 5,
        "scan_end_exclusive": 5,
        "active_pool_count": 3,
        "complete": True,
        "coverage_percent": 100,
        "fetched_at_utc": "2026-10-14T10:00:00+00:00",
        "pools": [
            {
                "index": i,
                "pool_address": f"0x{100 + i:040x}",
                "gauge_address": f"0x{200 + i:040x}",
                "gauge_active": True,
                "weight_raw": str(weight),
                "vote_share_percent": "0.00000000",
            }
            for i, weight in items
        ],
    }


class TestPlanPoolCollection(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.output = Path(temp.name)

    def test_ranking_is_deterministic_and_all_indices_present(self):
        batches = module.make_batches(sample(), 2, "votes")
        self.assertEqual([[p["index"] for p in b] for b in batches], [[4, 0], [2]])
        self.assertEqual(
            [[p["index"] for p in b] for b in module.make_batches(sample(), 2, "registration")],
            [[0, 2], [4]],
        )

    def test_rejects_partial_or_misreported_coverage(self):
        partial = sample()
        partial["complete"] = False
        with self.assertRaisesRegex(ValueError, "partial"):
            module.make_batches(partial)
        inaccurate = sample()
        inaccurate["coverage_percent"] = 99
        with self.assertRaisesRegex(ValueError, "100%"):
            module.make_batches(inaccurate)

    def test_rejects_duplicate_and_false_active_flag(self):
        duplicate = sample()
        duplicate["pools"][1]["index"] = 0
        with self.assertRaisesRegex(ValueError, "duplicate"):
            module.make_batches(duplicate)
        inactive = sample()
        inactive["pools"][0]["gauge_active"] = False
        with self.assertRaisesRegex(ValueError, "not marked alive"):
            module.make_batches(inactive)

    def test_produces_reusable_scan_input_and_manifest(self):
        inventory = sample()
        manifest, manifest_file = module.prepare_batches(
            inventory, 2, "votes", output_root=self.output,
        )
        self.assertTrue(manifest_file.is_file())
        self.assertEqual(manifest["batch_count"], 2)
        self.assertEqual(manifest["all_batches_pool_count"], 3)
        self.assertEqual(manifest["zero_weight_active_count"], 1)
        saved = sorted(manifest_file.parent.glob("batch_*.json"))
        self.assertEqual(len(saved), 2)
        first = json.loads(saved[0].read_text())
        second = json.loads(saved[1].read_text())
        self.assertEqual([p["index"] for p in first["pools"]], [4, 0])
        self.assertEqual([p["index"] for p in second["pools"]], [2])
        self.assertEqual(first["chain_id"], 8453)
        self.assertEqual(first["active_pool_count"], 2)
        again, path_again = module.prepare_batches(
            inventory, 2, "votes", output_root=self.output,
        )
        self.assertEqual(path_again, manifest_file)
        self.assertEqual(again["inventory_sha256"], manifest["inventory_sha256"])

    def test_refuses_overwrite_if_same_block_source_changes(self):
        inventory = sample()
        _, path = module.prepare_batches(
            inventory, 2, "votes", output_root=self.output,
        )
        original_bytes = path.read_bytes()
        changed = sample()
        changed["pools"][0]["weight_raw"] = "500"
        with self.assertRaisesRegex(RuntimeError, "different inventory"):
            module.prepare_batches(changed, 2, "votes", output_root=self.output)
        self.assertEqual(path.read_bytes(), original_bytes)

    def test_limits_batch_sizes(self):
        with self.assertRaisesRegex(ValueError, "1 and 50"):
            module.make_batches(sample(), 51)
        with self.assertRaisesRegex(ValueError, "1 and 50"):
            module.make_batches(sample(), 0)


if __name__ == "__main__":
    unittest.main()
