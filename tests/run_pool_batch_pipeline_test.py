"""Offline tests for bounded P2 collection pipeline orchestration."""
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
    "run_pool_batch_pipeline", SCRIPTS / "run_pool_batch_pipeline.py",
)
p = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(p)
EPOCH = "2026-10-08T00:00:00+00:00"
HASH = "abc123"


class FakeResult:
    def __init__(self, returncode):
        self.returncode = returncode


class TestBatchPipeline(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.folder = self.root / "block_9001" / "votes_25"
        self.folder.mkdir(parents=True)
        self.reference = self.folder / "manifest.json"
        self.set_manifest()

    def put(self, name, obj):
        (self.folder / name).write_text(json.dumps(obj), encoding="utf-8")

    def set_manifest(self):
        batches = []
        for number in (1, 2):
            addr = f"0x{number:040x}"
            entry = {
                "index": number, "pool_address": addr,
                "gauge_address": f"0x{number + 100:040x}",
                "weight_raw": "1000000000000000000", "gauge_active": True,
            }
            self.put(f"batch_{number:03d}.json", {
                "chain_id": 8453, "inventory_sha256": HASH, "pools": [entry],
            })
            batches.append({
                "number": number, "pool_count": 1, "pool_indexes": [number],
            })
        self.put("manifest.json", {
            "chain_id": 8453, "inventory_sha256": HASH,
            "batch_count": 2, "active_pool_count": 2,
            "all_batches_pool_count": 2, "snapshot_block_number": 9001,
            "batches": batches,
        })
        self.put("fee_histories_batch_001.json", {
            "current_epoch_start_utc": EPOCH,
        })
        self.put("incentives_batch_001.json", {
            "current_epoch_utc": EPOCH,
        })
        self.put("audit_batch_001.json", {
            "source_epoch_utc": EPOCH, "pool_count": 1,
        })

    def test_manifest_and_epoch_anchor(self):
        plan = p.validate_manifest(self.folder)
        self.assertEqual(plan["active_pool_count"], 2)
        self.assertEqual(p.reference_epoch(self.folder), EPOCH)

    def test_inconsistent_manifest_is_rejected(self):
        bad = json.loads(self.reference.read_text())
        bad["batches"][1]["pool_indexes"] = [999]
        self.put("manifest.json", bad)
        with self.assertRaisesRegex(ValueError, "identities mismatch"):
            p.validate_manifest(self.folder)

    def test_dry_run_cannot_invoke_live_collection(self):
        with patch.object(p, "BATCH_ROOT", self.root):
            with patch.object(p, "process_one") as process:
                p.run(self.folder, start=2, max_batches=1, dry_run=True)
                process.assert_not_called()
        self.assertFalse((self.folder / ".batch_pipeline.lock").exists())

    def test_batch_success_is_skipped_without_rpcs(self):
        files = p.paths_for(self.folder, 2)
        self.put("fee_histories_batch_002.json", {
            "current_epoch_start_utc": EPOCH,
        })
        self.put("incentives_batch_002.json", {
            "current_epoch_utc": EPOCH,
        })
        self.put("audit_batch_002.json", {
            "pool_count": 1,
        })
        self.put("batch_002_status.json", {
            "state": "complete", "expected_pools": 1,
            "epoch_utc": EPOCH, "audited_active_pools": 1,
        })
        self.assertTrue(p.already_done(files, 1, EPOCH))
        with patch.object(p, "cli_call") as cli:
            p.process_one(self.folder, 2, EPOCH)
            cli.assert_not_called()

    def test_bounded_retry_succeeds_on_second_attempt(self):
        with patch.object(p.subprocess, "run", side_effect=[FakeResult(1), FakeResult(0)]) as cmd:
            with patch.object(p.time, "sleep") as sleep:
                p.cli_call("mock task", ["script.py"], attempts=2, backoff=7)
        self.assertEqual(cmd.call_count, 2)
        sleep.assert_called_once_with(7)

    def test_retry_exhaustion_preserves_prior_status(self):
        files = p.paths_for(self.folder, 2)
        with patch.object(p.subprocess, "run", side_effect=[FakeResult(22), FakeResult(22)]):
            with patch.object(p.time, "sleep"):
                with self.assertRaisesRegex(RuntimeError, "failed after 2 attempts"):
                    p.cli_call("mock failure", ["script.py"])
        self.assertFalse(files["status"].exists())

    def test_epoch_mismatch_prevents_skipping(self):
        files = p.paths_for(self.folder, 2)
        self.put("batch_002_status.json", {
            "state": "complete", "epoch_utc": "2026-10-15T00:00:00+00:00",
            "expected_pools": 1,
        })
        with self.assertRaisesRegex(RuntimeError, "conflicts"):
            p.already_done(files, 1, EPOCH)


if __name__ == "__main__":
    unittest.main()
