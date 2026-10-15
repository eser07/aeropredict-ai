"""Offline tests: preserve old P4 votes, safely resume across separately labeled blocks."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import collect_p4_rolling_votes_base as rolling


def source_inventory():
    return {
        "snapshot_block_number": 52595092,
        "pools": [
            {"index": i + 100, "pool_address": "0x" + f"{i+1:040x}"}
            for i in range(4)
        ],
    }


def pinned_rows(count=2):
    source = source_inventory()
    return {
        "chain_id": 8453,
        "voter": rolling.VOTER,
        "source_inventory_sha256": "inventory_hash",
        "expected_pools": 4,
        "next_offset": count,
        "snapshot_block_number": 52646576,
        "snapshot_block_hash": "0x" + "a" * 64,
        "snapshot_block_timestamp_utc": "2026-10-15T07:00:00+00:00",
        "total_voting_weight_raw": "5000",
        "last_page_completed_at_utc": "2026-10-15T07:05:00+00:00",
        "pools": [
            {"index": item["index"], "pool_address": item["pool_address"],
             "weight_raw": str(n + 1)}
            for n, item in enumerate(source["pools"][:count])
        ],
    }


def make_checkpoint(tmp):
    path = Path(tmp) / "pinned.json"
    path.write_text(json.dumps(pinned_rows()))
    return rolling.import_pinned(source_inventory(), "inventory_hash", path)


class RollingP4Tests(unittest.TestCase):
    def test_import_preserves_prior_observations_and_block(self):
        with tempfile.TemporaryDirectory() as td:
            data = make_checkpoint(td)
        self.assertEqual(data["next_offset"], 2)
        self.assertEqual(data["pages"][0]["block_number"], 52646576)
        self.assertEqual(data["pages"][0]["source"], "preserved_pinned_checkpoint")
        self.assertEqual(len(data["pages"][0]["pools"]), 2)
        self.assertEqual(data["pages"][0]["total_voting_weight_raw"], "5000")

    def test_import_rejects_different_cohort(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "pinned.json"
            path.write_text(json.dumps(pinned_rows()))
            with self.assertRaisesRegex(ValueError, "mismatch"):
                rolling.import_pinned(source_inventory(), "changed", path)

    def test_page_uses_new_block_and_keeps_existing_pinned_rows(self):
        with tempfile.TemporaryDirectory() as td:
            previous = make_checkpoint(td)
        original = copy.deepcopy(previous)
        seen = []
        def get_weight(signature, address, tag):
            seen.append(tag)
            return 100
        with patch.object(rolling, "new_block", return_value=(
            52648000, "0x" + "b" * 64, "2026-10-15T08:00:00+00:00", 10000
        )), patch.object(rolling, "read_uint", side_effect=get_weight):
            updated, page = rolling.collect_page(previous, source_inventory(), 2, 0)
        self.assertEqual(seen, [hex(52648000)] * 2)
        self.assertEqual(page["start_offset"], 2)
        self.assertEqual(page["end_offset"], 4)
        self.assertEqual(updated["next_offset"], 4)
        self.assertTrue(updated["complete"])
        self.assertEqual(updated["pages"][0], previous["pages"][0])
        self.assertEqual(previous, original)
        rolling.validate_checkpoint(updated, source_inventory(), "inventory_hash")

    def test_partial_failed_page_is_discarded_and_re_pinned(self):
        with tempfile.TemporaryDirectory() as td:
            old = make_checkpoint(td)
        blocks = iter([
            (52648000, "0x" + "b" * 64, "2026-10-15T08:00:00+00:00", 10000),
            (52648500, "0x" + "c" * 64, "2026-10-15T08:15:00+00:00", 11000),
        ])
        calls = []
        def read_weight(signature, address, block):
            calls.append(block)
            if block == hex(52648000) and len(calls) == 2:
                raise RuntimeError("HTTP 403: historical block unavailable")
            return 200
        with patch.object(rolling, "new_block", side_effect=lambda: next(blocks)), \
             patch.object(rolling, "read_uint", side_effect=read_weight), \
             patch.object(rolling.time, "sleep"):
            updated, page = rolling.collect_with_repin(
                old, source_inventory(), 2, 0, 2
            )
        self.assertEqual(page["block_number"], 52648500)
        self.assertEqual(updated["pages"][0]["block_number"], 52646576)
        self.assertEqual(updated["next_offset"], 4)
        self.assertEqual(len(updated["pages"]), 2)

    def test_429_stops_without_repinning_or_data_loss(self):
        with tempfile.TemporaryDirectory() as td:
            old = make_checkpoint(td)
        snapshot = copy.deepcopy(old)
        with patch.object(rolling, "collect_page", side_effect=RuntimeError("HTTP 429")), \
             patch.object(rolling.time, "sleep") as sleeper:
            with self.assertRaisesRegex(RuntimeError, "rate-limited"):
                rolling.collect_with_repin(old, source_inventory(), 2, 0, 3)
            sleeper.assert_not_called()
        self.assertEqual(old, snapshot)

    def test_rejects_corrupted_page_boundaries(self):
        with tempfile.TemporaryDirectory() as td:
            progress = make_checkpoint(td)
        progress["pages"][0]["end_offset"] = 3
        with self.assertRaisesRegex(ValueError, "provenance"):
            rolling.validate_checkpoint(progress, source_inventory(), "inventory_hash")

    def test_save_and_resume_no_duplicate_pages(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "rolling"
            pinned = Path(td) / "pinned.json"
            pinned.write_text(json.dumps(pinned_rows()))
            saved = pinned.read_bytes()
            with patch.object(rolling, "ROOT", root), \
                 patch.object(rolling, "PINNED_CHECKPOINT", pinned), \
                 patch.object(rolling, "load_inventory",
                              return_value=(source_inventory(), "inventory_hash")), \
                 patch.object(rolling, "rpc_checked", return_value=hex(8453)), \
                 patch.object(rolling, "collect_with_repin") as collect:
                def new_page(progress, inventory, page_size, delay, max_repins):
                    rows = [
                        {"index": item["index"], "pool_address": item["pool_address"],
                         "weight_raw": "200"}
                        for item in inventory["pools"][2:4]
                    ]
                    page = {
                        "start_offset": 2, "end_offset": 4, "block_number": 52649000,
                        "block_hash": "0x" + "f" * 64,
                        "block_timestamp_utc": "2026-10-15T09:00:00+00:00",
                        "total_voting_weight_raw": "6000",
                        "source": "public_or_configured_base_rpc",
                        "collected_at_utc": "2026-10-15T09:05:00+00:00",
                        "pools": rows,
                    }
                    final = dict(progress)
                    final["pages"] = progress["pages"] + [page]
                    final["next_offset"] = 4
                    final["complete"] = True
                    return final, page
                collect.side_effect = new_page
                result = rolling.run(page_size=2, max_pages=1, delay=0)
                self.assertTrue(result["complete"])
                final = root / "snapshot.json"
                self.assertTrue(final.exists())
                original_final = final.read_bytes()
                rolling.run(page_size=2, max_pages=1, delay=0)
                self.assertEqual(final.read_bytes(), original_final)
                self.assertEqual(collect.call_count, 1)
            self.assertEqual(pinned.read_bytes(), saved)

    def test_rejects_wrong_network(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "rolling"
            pinned = Path(td) / "pinned.json"
            pinned.write_text(json.dumps(pinned_rows()))
            with patch.object(rolling, "ROOT", root), \
                 patch.object(rolling, "PINNED_CHECKPOINT", pinned), \
                 patch.object(rolling, "load_inventory",
                              return_value=(source_inventory(), "inventory_hash")), \
                 patch.object(rolling, "rpc_checked", return_value=hex(1)):
                with self.assertRaisesRegex(RuntimeError, "Wrong network"):
                    rolling.run(page_size=2)
            self.assertEqual(json.loads((root / "checkpoint.json").read_text())["next_offset"], 2)


if __name__ == "__main__":
    unittest.main()
