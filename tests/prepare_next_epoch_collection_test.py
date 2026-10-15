"""Tests for isolated next-week collection with no old output modification."""
import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location(
    "prepare_next_epoch_collection", SCRIPTS / "prepare_next_epoch_collection.py",
)
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)
EPOCH_OLD = "2026-10-08T00:00:00+00:00"
EPOCH_NEW = "2026-10-15T00:00:00+00:00"
HASH = "abc123"


class TestNextEpochCollection(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.folder = self.root / "block_9001" / "votes_25"
        self.folder.mkdir(parents=True)
        rows = []
        for number in (1, 2, 3):
            pool = {
                "index": number,
                "pool_address": f"0x{number:040x}",
                "gauge_address": f"0x{number + 100:040x}",
                "weight_raw": "1000000000000000000",
                "gauge_active": True,
            }
            self.write(f"batch_{number:03d}.json", {
                "chain_id": 8453,
                "batch_number": number,
                "inventory_sha256": HASH,
                "pools": [pool],
            })
            rows.append({
                "number": number,
                "pool_count": 1,
                "pool_indexes": [number],
                "file": "ORIGINAL",
            })
        self.write("manifest.json", {
            "chain_id": 8453,
            "snapshot_block_number": 9001,
            "batch_count": 3,
            "active_pool_count": 3,
            "all_batches_pool_count": 3,
            "inventory_sha256": HASH,
            "batches": rows,
        })
        for number in (1, 2):
            self.write(f"fee_histories_batch_{number:03d}.json", {
                "current_epoch_start_utc": EPOCH_OLD, "pools": [
                    {"index": number, "pool_address": f"0x{number:040x}"}
                ],
            })
            self.write(f"incentives_batch_{number:03d}.json", {
                "current_epoch_utc": EPOCH_OLD,
            })
            self.write(f"audit_batch_{number:03d}.json", {
                "source_epoch_utc": EPOCH_OLD,
                "pool_count": 1,
                "audited_complete_usd_count": 1,
            })
        self.write("batch_002_status.json", {
            "state": "complete", "batch_number": 2, "expected_pools": 1,
            "epoch_utc": EPOCH_OLD,
            "audited_active_pools": 1, "fully_priced_pools": 1,
        })

    def write(self, filename, contents):
        (self.folder / filename).write_text(json.dumps(contents), encoding="utf-8")

    def test_produces_separate_pinned_plan_without_touching_originals(self):
        original = {p.name: p.read_bytes() for p in self.folder.glob("*.json")}
        with patch.object(m, "BATCH_ROOT", self.root):
            new, manifest, prior = m.prepare(self.folder, 2, "2026-10-15")
        self.assertEqual(new, self.folder / "epochs" / "2026-10-15")
        self.assertEqual(manifest["collection_epoch_utc"], EPOCH_NEW)
        self.assertEqual(manifest["new_epoch_collection_start_batch"], 3)
        self.assertEqual(prior["prior_audited_pools"], 2)
        self.assertEqual(len(list(new.glob("batch_*.json"))), 3)
        self.assertFalse((new / "fee_histories_batch_001.json").exists())
        self.assertFalse((new / "batch_002_status.json").exists())
        self.assertEqual(original, {
            p.name: p.read_bytes() for p in self.folder.glob("*.json")
        })
        with patch.object(m, "BATCH_ROOT", self.root):
            with patch.object(m, "read_json", wraps=m.read_json):
                new_again, _, _ = m.prepare(self.folder, 2, "2026-10-15")
                self.assertEqual(new_again, new)

    def test_new_runner_is_pinned_and_rejects_already_completed_batches(self):
        with patch.object(m, "BATCH_ROOT", self.root):
            new, _, _ = m.prepare(self.folder, 2, "2026-10-15")
        from run_pool_batch_pipeline import run
        with patch("run_pool_batch_pipeline.BATCH_ROOT", self.root):
            with self.assertRaisesRegex(ValueError, "Start batch"):
                run(new, start=2, max_batches=1, dry_run=True)
            with patch("run_pool_batch_pipeline.process_one") as process:
                run(new, start=3, max_batches=1, dry_run=True)
                process.assert_not_called()

    def test_prior_unpublished_batch_rejected(self):
        (self.folder / "batch_002_status.json").unlink()
        with patch.object(m, "BATCH_ROOT", self.root):
            with self.assertRaisesRegex(RuntimeError, "not fully published"):
                m.prepare(self.folder, 2, "2026-10-15")
        self.assertFalse((self.folder / "epochs").exists())

    def test_wrong_new_epoch_and_non_thursday_rejected(self):
        with patch.object(m, "BATCH_ROOT", self.root):
            with self.assertRaisesRegex(ValueError, "Thursday"):
                m.prepare(self.folder, 2, "2026-10-16")
            with self.assertRaisesRegex(ValueError, "exactly one Thursday"):
                m.prepare(self.folder, 2, "2026-10-22")

    def test_inconsistent_old_status_rejected(self):
        status = json.loads((self.folder / "batch_002_status.json").read_text())
        status["fully_priced_pools"] = 17
        self.write("batch_002_status.json", status)
        with patch.object(m, "BATCH_ROOT", self.root):
            with self.assertRaisesRegex(ValueError, "does not match epoch/count"):
                m.prepare(self.folder, 2, "2026-10-15")

    def test_refuses_existing_plan_with_different_epoch(self):
        with patch.object(m, "BATCH_ROOT", self.root):
            created, _, _ = m.prepare(self.folder, 2, "2026-10-15")
        new_manifest = json.loads((created / "manifest.json").read_text())
        new_manifest["collection_epoch_utc"] = "2026-10-22T00:00:00+00:00"
        (created / "manifest.json").write_text(json.dumps(new_manifest))
        with patch.object(m, "BATCH_ROOT", self.root):
            with self.assertRaisesRegex(RuntimeError, "differs"):
                m.prepare(self.folder, 2, "2026-10-15")


if __name__ == "__main__":
    unittest.main()
