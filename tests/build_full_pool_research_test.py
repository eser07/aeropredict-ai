"""Offline end-to-end tests of the 928-pool, two-epoch research merger."""
import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location(
    "build_full_pool_research_base", SCRIPTS / "build_full_pool_research_base.py",
)
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)

EPOCHS = ("2026-10-08T00:00:00+00:00", "2026-10-15T00:00:00+00:00")
TOKEN = "0x" + "f" * 40


def save(path, doc):
    path.parent.mkdir(exist_ok=True, parents=True)
    path.write_text(json.dumps(doc), encoding="utf-8")


def mock_files(root, inactive_index=None):
    original = root / "block_52595092" / "votes_25"
    next_week = original / "epochs" / "2026-10-15"
    rows = []
    indexes = 1
    for number in range(1, 39):
        count = 25 if number < 38 else 3
        ids = list(range(indexes, indexes + count))
        indexes += count
        rows.append({
            "number": number, "pool_count": count,
            "pool_indexes": ids,
        })
    assert indexes == 929
    base_manifest = {
        "chain_id": 8453,
        "snapshot_block_number": 52595092,
        "active_pool_count": 928, "all_batches_pool_count": 928,
        "inventory_sha256": "snapshot_same_in_both",
        "batch_count": 38, "batches": rows,
    }
    save(original / "manifest.json", base_manifest)
    next_manifest = dict(base_manifest, **{
        "collection_epoch_utc": EPOCHS[1],
        "prior_collection_epoch_utc": EPOCHS[0],
        "carry_forward_completed_through": 15,
        "new_epoch_collection_start_batch": 16,
    })
    save(next_week / "manifest.json", next_manifest)
    for number, planned in enumerate(rows, 1):
        epoch = EPOCHS[0] if number <= 15 else EPOCHS[1]
        folder = original if number <= 15 else next_week
        selected = []
        fee_pools = []
        inc_pools = []
        reports = []
        for idx in planned["pool_indexes"]:
            address = f"0x{idx:040x}"
            gauge = f"0x{idx + 1000:040x}"
            pair = {"index": idx, "pool_address": address, "gauge_address": gauge}
            selected.append(pair)
            act = idx != inactive_index
            raw = "1000000" if idx in (1, 26, 376) else "0"
            weeks = [
                {"epoch_start_utc": epoch, "raw": raw} for _ in range(4)
            ]
            reward = {
                "token_address": TOKEN, "symbol": "TEST", "decimals": 6,
                "last_four_weeks": weeks,
                "four_week_mean_amount": "1" if raw != "0" else "0",
                "usd_at_current_price": "4" if raw != "0" else "0",
            }
            fee_pools.append({
                **pair,
                "active_at_collection": act,
                "pool_vote_weight_raw": "1000000000000000000",
            })
            if act:
                inc_pools.append({
                    **pair,
                    "pool_vote_weight_raw": "1000000000000000000",
                    "fees": [reward], "bribes": [],
                })
                complete = idx != 26
                mean = "4" if raw != "0" and complete else (
                    "0" if complete else None
                )
                reports.append({
                    "index": idx, "pool_address": address,
                    "usd_coverage_complete_at_audit": complete,
                    "avg_weekly_usd_at_saved_current_prices": mean,
                    "weekly_usd_at_saved_current_prices":
                        [mean] * 4 if complete else None,
                    "combined_positive_weeks": 4 if raw != "0" else 0,
                    "fees_positive_weeks": 4 if raw != "0" else 0,
                    "bribes_positive_weeks": 0,
                    "snapshot_votes": "1",
                    "usd_per_million_snapshot_votes": None if not complete else mean,
                    "highest_week_share_of_four_week_total": (
                        "0.25" if raw != "0" and complete else None
                    ),
                    "missing_or_stale_components":
                        [TOKEN + ":missing_or_stale_quote"] if not complete else [],
                    "truncated_registry": False,
                })
        batch_doc = {"chain_id": 8453,
                     "inventory_sha256": "snapshot_same_in_both",
                     "pools": selected}
        save(original / f"batch_{number:03d}.json", batch_doc)
        save(next_week / f"batch_{number:03d}.json", batch_doc)
        save(folder / f"fee_histories_batch_{number:03d}.json", {
            "chain_id": 8453,
            "current_epoch_start_utc": epoch,
            "completed_weeks_requested": 4,
            "pools": fee_pools,
        })
        save(folder / f"incentives_batch_{number:03d}.json", {
            "chain_id": 8453, "current_epoch_utc": epoch, "week_count": 4,
            "pools": inc_pools,
            "prices": {
                TOKEN: {
                    "price_usd": "4",
                    "price_timestamp_utc": epoch,
                    "reason": None,
                },
            },
        })
        usd_count = sum(p["usd_coverage_complete_at_audit"] for p in reports)
        save(folder / f"audit_batch_{number:03d}.json", {
            "chain_id": 8453, "source_epoch_utc": epoch,
            "pool_count": len(reports),
            "audited_complete_usd_count": usd_count,
            "incomplete_usd_count": len(reports) - usd_count,
            "four_week_usd_totals_by_pool": reports,
        })
        if number > 1:
            save(folder / f"batch_{number:03d}_status.json", {
                "state": "complete", "epoch_utc": epoch,
                "batch_number": number, "expected_pools": len(selected),
                "audited_active_pools": len(reports),
                "fully_priced_pools": usd_count,
            })
    return original, next_week


class TestFullResearchBuild(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.old, self.new = mock_files(self.root)

    def test_exhaustive_928_and_two_epochs_without_global_rank(self):
        result = m.consolidate(self.old, self.new)
        self.assertEqual(result["audited_pool_count"], 928)
        self.assertEqual(result["audited_usd_complete_pool_count"], 927)
        self.assertEqual(result["audited_usd_incomplete_pool_count"], 1)
        self.assertEqual(set(result["by_collection_epoch"]), set(EPOCHS))
        self.assertEqual(result["by_collection_epoch"][EPOCHS[0]]["audited_pools"], 375)
        self.assertEqual(result["by_collection_epoch"][EPOCHS[1]]["audited_pools"], 553)
        self.assertEqual(result["by_collection_epoch"][EPOCHS[0]]["complete_usd_pools"], 374)
        self.assertEqual(result["by_collection_epoch"][EPOCHS[1]]["complete_usd_pools"], 553)
        self.assertEqual(result["by_collection_epoch"][EPOCHS[0]]["no_observed_rewards_pools"], 373)
        self.assertEqual(result["by_collection_epoch"][EPOCHS[1]]["no_observed_rewards_pools"], 552)
        self.assertEqual(len(result["pools"]), 928)
        self.assertEqual(len(result["not_audited_at_collection"]), 0)
        inc = next(p for p in result["pools"] if p["index"] == 26)
        self.assertFalse(inc["usd_coverage_complete"])
        self.assertIsNone(inc["avg_pool_usd_per_week_at_collection_quote"])
        self.assertEqual(inc["observed_any_reward_positive_weeks"], 4)
        self.assertNotIn("top_global", result)
        self.assertEqual(result["pools"][0]["collection_epoch_utc"], EPOCHS[0])
        self.assertEqual(result["pools"][-1]["collection_epoch_utc"], EPOCHS[1])

    def test_rejects_broken_epoch(self):
        path = self.new / "audit_batch_038.json"
        doc = json.loads(path.read_text())
        doc["source_epoch_utc"] = EPOCHS[0]
        save(path, doc)
        with self.assertRaisesRegex(ValueError, "epochs do not align"):
            m.consolidate(self.old, self.new)

    def test_rejects_missing_complete_marker(self):
        (self.new / "batch_038_status.json").unlink()
        with self.assertRaisesRegex(ValueError, "has no complete marker"):
            m.consolidate(self.old, self.new)

    def test_rejects_duplicated_pool_record(self):
        path = self.new / "audit_batch_038.json"
        doc = json.loads(path.read_text())
        doc["four_week_usd_totals_by_pool"][1]["index"] = 926
        save(path, doc)
        with self.assertRaisesRegex(ValueError, "audit indices mismatch"):
            m.consolidate(self.old, self.new)

    def test_inactive_pool_never_counts_as_zero_reward(self):
        other = self.root / "fresh"
        old, new = mock_files(other, inactive_index=928)
        result = m.consolidate(old, new)
        self.assertEqual(result["audited_pool_count"], 927)
        self.assertEqual(len(result["not_audited_at_collection"]), 1)
        self.assertEqual(result["not_audited_at_collection"][0]["index"], 928)
        self.assertNotIn(928, [r["index"] for r in result["pools"]])

    def test_missing_usd_stays_unknown(self):
        result = m.consolidate(self.old, self.new)
        inc = next(p for p in result["pools"] if p["index"] == 26)
        self.assertEqual(inc["missing_or_stale_components"], [
            TOKEN + ":missing_or_stale_quote"
        ])
        self.assertIsNone(inc["weekly_pool_usd_at_collection_quote"])


if __name__ == "__main__":
    unittest.main()
