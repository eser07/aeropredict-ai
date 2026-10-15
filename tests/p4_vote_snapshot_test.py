"""Offline regression tests for the isolated P4 same-block vote collector."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import collect_p4_votes_base as p4


def inventory():
    return {
        "snapshot_block_number": 52595092,
        "pools": [
            {"index": i + 10, "pool_address": "0x" + f"{i + 1:040x}"}
            for i in range(3)
        ],
    }


def sample_progress():
    source = inventory()
    return {
        "schema_version": 1,
        "chain_id": 8453,
        "voter": p4.VOTER,
        "snapshot_block_number": 52630000,
        "snapshot_block_hash": "0x" + "a" * 64,
        "snapshot_block_timestamp_utc": "2026-10-15T10:00:00+00:00",
        "source_inventory_sha256": "source_sha",
        "source_inventory_block_number": source["snapshot_block_number"],
        "total_voting_weight_raw": "1000",
        "expected_pools": 3,
        "next_offset": 0,
        "pools": [],
        "complete": False,
    }


class P4VoteSnapshotTests(unittest.TestCase):
    def test_empty_checkpoint_is_valid(self):
        self.assertEqual(p4.validate(sample_progress(), inventory(), "source_sha")["next_offset"], 0)

    def test_rejects_wrong_source_or_cohort(self):
        with self.assertRaisesRegex(ValueError, "does not match"):
            p4.validate(sample_progress(), inventory(), "other_sha")

    def test_rejects_gaps_and_mislabeled_rows(self):
        checkpoint = sample_progress()
        checkpoint["next_offset"] = 1
        checkpoint["pools"] = []
        with self.assertRaisesRegex(ValueError, "gap"):
            p4.validate(checkpoint, inventory(), "source_sha")
        checkpoint["pools"] = [{"index": 999, "pool_address": inventory()["pools"][0]["pool_address"],
                                "weight_raw": "1"}]
        with self.assertRaisesRegex(ValueError, "identity"):
            p4.validate(checkpoint, inventory(), "source_sha")

    def test_collect_page_uses_exact_same_block_for_all_pools(self):
        tags = []
        def fake_read(signature, address, block):
            tags.append((signature, address, block))
            return 5
        with patch.object(p4, "read_uint", side_effect=fake_read):
            result = p4.collect_page(sample_progress(), inventory(), 3, 0)
        self.assertEqual(result["next_offset"], 3)
        self.assertTrue(result["complete"])
        self.assertEqual(len(result["pools"]), 3)
        self.assertEqual(set(tag for _, _, tag in tags), {hex(52630000)})
        self.assertEqual([r["vote_share_percent"] for r in result["pools"]], ["0.50000000"] * 3)
        p4.validate(result, inventory(), "source_sha")

    def test_interrupted_page_does_not_mutate_prior_progress(self):
        source = sample_progress()
        original = copy.deepcopy(source)
        with patch.object(p4, "read_uint", side_effect=[5, RuntimeError("RPC failed")]):
            with self.assertRaises(RuntimeError):
                p4.collect_page(source, inventory(), 3, 0)
        self.assertEqual(source, original)

    def test_refuse_reorged_pinned_block(self):
        checkpoint = sample_progress()
        with patch.object(p4, "verify_chain"), patch.object(p4, "block_info",
            return_value=("0x" + "b" * 64, checkpoint["snapshot_block_timestamp_utc"])):
            with self.assertRaisesRegex(RuntimeError, "hash changed"):
                p4.verify_pinned(checkpoint)

    def test_page_resume_and_final_immutable_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with patch.object(p4, "DESTINATION", root), \
                 patch.object(p4, "start", return_value=sample_progress()), \
                 patch.object(p4, "verify_pinned"), \
                 patch.object(p4, "read_uint", return_value=8):
                first = p4._run(inventory(), "source_sha", 2, 1, 0, False, False)
                self.assertEqual(first["next_offset"], 2)
                checkpoint = root / "block_52630000" / "checkpoint.json"
                self.assertTrue(checkpoint.exists())
                self.assertFalse((checkpoint.parent / "snapshot.json").exists())
                second = p4._run(inventory(), "source_sha", 2, 1, 0, False, False)
                self.assertTrue(second["complete"])
                final = checkpoint.parent / "snapshot.json"
                self.assertTrue(final.exists())
                published = json.loads(final.read_text())
                self.assertEqual(published["snapshot_block_number"], 52630000)
                self.assertEqual(len(published["pools"]), 3)
                before = final.read_bytes()
                p4._run(inventory(), "source_sha", 2, 1, 0, False, False)
                self.assertEqual(final.read_bytes(), before)

    def test_new_refused_while_snapshot_incomplete(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint = root / "block_52630000" / "checkpoint.json"
            p4.save_atomic(checkpoint, sample_progress())
            with patch.object(p4, "DESTINATION", root):
                with self.assertRaisesRegex(RuntimeError, "incomplete snapshot"):
                    p4._run(inventory(), "source_sha", 1, 1, 0, False, True)

    def test_recover_publication_after_completed_checkpoint(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            done = sample_progress()
            done["pools"] = [
                {"index": item["index"], "pool_address": item["pool_address"],
                 "weight_raw": "5"}
                for item in inventory()["pools"]
            ]
            done["next_offset"] = 3
            done["complete"] = True
            checkpoint = root / "block_52630000" / "checkpoint.json"
            p4.save_atomic(checkpoint, done)
            with patch.object(p4, "DESTINATION", root), patch.object(p4, "verify_pinned"):
                result = p4._run(inventory(), "source_sha", 2, 1, 0, False, False)
                self.assertTrue(result["complete"])
                self.assertTrue(checkpoint.with_name("snapshot.json").exists())

    def test_invalid_collection_options(self):
        with self.assertRaisesRegex(ValueError, "Invalid page"):
            p4.run(page_size=0)


if __name__ == "__main__":
    unittest.main()
