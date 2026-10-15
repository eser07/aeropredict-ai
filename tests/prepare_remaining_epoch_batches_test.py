"""Offline tests: a new weekly epoch must not overwrite old 375-pool audits."""
import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location(
    "prepare_remaining_epoch_batches_base",
    SCRIPTS / "prepare_remaining_epoch_batches_base.py",
)
p = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(p)
OLD_EPOCH = "2026-10-08T00:00:00+00:00"
NEW_TIME = datetime(2026, 10, 15, 3, 20, tzinfo=timezone.utc)
HASH = "abc123"


class TestNewEpochPlan(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source = self.root / "block_9001" / "votes_25"
        self.source.mkdir(parents=True)
        groups = []
        for number in (1, 2, 3):
            token = {
                "index": number,
                "pool_address": f"0x{number:040x}",
                "gauge_address": f"0x{number + 100:040x}",
                "gauge_active": True,
                "weight_raw": str(1000000000000000000 * number),
            }
            self.write(self.source / f"batch_{number:03d}.json", {
                "chain_id": 8453, "batch_number": number, "batch_count": 3,
                "inventory_sha256": HASH, "pools": [token],
            })
            groups.append({
                "number": number, "pool_count": 1, "pool_indexes": [number],
                "file": f"data/pool_collection_batches_base/block_9001/votes_25/batch_{number:03d}.json",
            })
        self.write(self.source / "manifest.json", {
            "chain_id": 8453, "snapshot_block_number": 9001,
            "inventory_sha256": HASH, "batch_order": "votes",
            "active_pool_count": 3, "all_batches_pool_count": 3,
            "batch_count": 3, "batch_size_limit": 25, "batches": groups,
        })
        for number in (1, 2):
            self.write(self.source / f"fee_histories_batch_{number:03d}.json", {
                "current_epoch_start_utc": OLD_EPOCH,
            })
            self.write(self.source / f"incentives_batch_{number:03d}.json", {
                "current_epoch_utc": OLD_EPOCH,
            })
            self.write(self.source / f"audit_batch_{number:03d}.json", {
                "source_epoch_utc": OLD_EPOCH,
                "pool_count": 1,
                "audited_complete_usd_count": number - 1,
                "four_week_usd_totals_by_pool": [{
                    "index": number,
                    "usd_coverage_complete_at_audit": number == 2,
                    "truncated_registry": number == 1,
                    "missing_or_stale_components": [],
                }],
            })
            if number > 1:
                self.write(self.source / f"batch_{number:03d}_status.json", {
                    "state": "complete", "epoch_utc": OLD_EPOCH,
                    "expected_pools": 1, "audited_active_pools": 1,
                    "fully_priced_pools": 1,
                })

    @staticmethod
    def write(path, value):
        path.write_text(json.dumps(value), encoding="utf-8")

    def test_epoch_start_is_utc_thursday(self):
        self.assertEqual(p.epoch_start(NEW_TIME).isoformat(), "2026-10-15T00:00:00+00:00")
        weds = datetime(2026, 10, 14, 23, tzinfo=timezone.utc)
        self.assertEqual(p.epoch_start(weds).isoformat(), OLD_EPOCH)

    def test_dry_run_does_not_create_folder(self):
        with patch.object(p, "BATCH_ROOT", self.root):
            report = p.prepare(self.source, completed_through=2, now=NEW_TIME, dry_run=True)
        self.assertEqual(report["action"], "DRY RUN")
        self.assertFalse((self.source / "epoch_2026-10-15").exists())
        self.assertEqual(report["remaining_pools"], 1)
        self.assertEqual(report["original_usd_complete"], 1)
        self.assertEqual(len(report["original_incomplete"]), 1)

    def test_publishes_separate_plan_and_keeps_old_bytes(self):
        before = (self.source / "batch_003.json").read_bytes()
        with patch.object(p, "BATCH_ROOT", self.root):
            with patch.object(p, "DEFAULT_SOURCE", self.source):
                report = p.prepare(self.source, completed_through=2, now=NEW_TIME)
                self.assertEqual(report["action"], "SAVED")
                target = self.source / "epoch_2026-10-15"
                manifest = p.validate_manifest(target)
                self.assertEqual(manifest["collection_epoch_utc"], "2026-10-15T00:00:00+00:00")
                self.assertEqual(manifest["active_pool_count"], 1)
                self.assertEqual(manifest["batches"][0]["original_batch_number"], 3)
                self.assertEqual(p.reference_epoch(target, manifest), "2026-10-15T00:00:00+00:00")
                self.assertEqual(self.source.joinpath("batch_003.json").read_bytes(), before)
                again = p.prepare(self.source, completed_through=2, now=NEW_TIME)
                self.assertEqual(again["action"], "EXISTING VERIFIED")

    def test_refuses_partial_old_status(self):
        (self.source / "batch_002_status.json").unlink()
        with patch.object(p, "BATCH_ROOT", self.root):
            with self.assertRaisesRegex(RuntimeError, "missing completed status"):
                p.prepare(self.source, completed_through=2, now=NEW_TIME)

    def test_rejects_mixed_epoch_and_no_new_epoch(self):
        with patch.object(p, "BATCH_ROOT", self.root):
            old_date = datetime(2026, 10, 14, 23, tzinfo=timezone.utc)
            with self.assertRaisesRegex(ValueError, "No new Aerodrome"):
                p.prepare(self.source, completed_through=2, now=old_date)
            self.write(self.source / "fee_histories_batch_002.json", {
                "current_epoch_start_utc": "2026-10-15T00:00:00+00:00",
            })
            with self.assertRaisesRegex(RuntimeError, "original epoch"):
                p.prepare(self.source, completed_through=2, now=NEW_TIME)


if __name__ == "__main__":
    unittest.main()
