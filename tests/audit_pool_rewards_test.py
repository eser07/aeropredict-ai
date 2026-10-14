"""Offline tests for P2 pool-level USD and vote-efficiency diagnostics."""
import copy
import importlib.util
import sys
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location(
    "audit_pool_rewards_base", SCRIPTS / "audit_pool_rewards_base.py",
)
audit_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit_module)

EPOCH = "2026-10-08T00:00:00+00:00"
NOW = datetime(2026, 10, 14, 15, 10, tzinfo=timezone.utc)
QUOTE_AT = datetime(2026, 10, 14, 15, 0, tzinfo=timezone.utc).isoformat()
WEEKS = [
    (datetime.fromisoformat(EPOCH) - timedelta(weeks=n)).isoformat()
    for n in (4, 3, 2, 1)
]
TOKEN = "0x" + "1" * 40
ZERO_BRIBE = "0x" + "2" * 40


def fixture():
    fee_pools, incentive_pools = [], []
    for idx, amounts, votes in (
        (11, [0, 0, 0, 4000000], "1000000000000000000"),
        (12, [1000000] * 4, "0"),
    ):
        pair = {
            "index": idx,
            "pool_address": f"0x{idx:040x}",
            "gauge_address": f"0x{idx + 100:040x}",
            "pool_vote_weight_raw": votes,
        }
        rows = [{"epoch_start_utc": w, "raw": str(a)}
                for w, a in zip(WEEKS, amounts)]
        old = {**pair, "active_at_collection": True,
               "tokens_truncated": False,
               "reward_series": [{
                   "token_address": TOKEN,
                   "decimals": 6,
                   "completed_weeks": copy.deepcopy(rows),
               }]}
        new = {**pair, "fees_registry_truncated": False,
               "bribes_registry_truncated": False,
               "fees": [{"token_address": TOKEN, "decimals": 6,
                         "last_four_weeks": copy.deepcopy(rows)}],
               "bribes": [{
                   "token_address": ZERO_BRIBE,
                   "decimals": 18,
                   "last_four_weeks": [
                       {"epoch_start_utc": w, "raw": "0"} for w in WEEKS
                   ],
               }]}
        fee_pools.append(old)
        incentive_pools.append(new)
    fees = {
        "chain_id": 8453,
        "current_epoch_start_utc": EPOCH,
        "completed_weeks_requested": 4,
        "collected_at_utc": "2026-10-14T14:00:00+00:00",
        "pools": fee_pools,
    }
    incentives = {
        "chain_id": 8453,
        "current_epoch_utc": EPOCH,
        "week_count": 4,
        "collected_at_utc": "2026-10-14T15:00:00+00:00",
        "prices": {
            TOKEN: {"price_usd": "2", "price_timestamp_utc": QUOTE_AT},
        },
        "pools": incentive_pools,
    }
    return fees, incentives


class TestAuditPoolRewards(unittest.TestCase):
    def test_weekly_totals_and_vote_efficiency(self):
        fees, incentives = fixture()
        result = audit_module.audit(fees, incentives, NOW)
        self.assertEqual(result["pool_count"], 2)
        self.assertEqual(result["audited_complete_usd_count"], 2)
        first, second = result["four_week_usd_totals_by_pool"]
        self.assertEqual(
            [Decimal(x) for x in first["weekly_usd_at_saved_current_prices"]],
            [Decimal(0), Decimal(0), Decimal(0), Decimal(8)],
        )
        self.assertEqual(Decimal(first["avg_weekly_usd_at_saved_current_prices"]), 2)
        self.assertEqual(Decimal(first["usd_per_million_snapshot_votes"]), 2000000)
        self.assertEqual(first["fees_positive_weeks"], 1)
        self.assertEqual(first["combined_positive_weeks"], 1)
        self.assertEqual(Decimal(first["highest_week_share_of_four_week_total"]), 1)
        self.assertIsNone(second["usd_per_million_snapshot_votes"])
        self.assertEqual(second["fees_positive_weeks"], 4)
        self.assertEqual(result["top_five_by_total_usd_indexes"], [11, 12])

    def test_rejects_mismatched_epochs(self):
        fees, incentives = fixture()
        incentives["current_epoch_utc"] = "2026-10-01T00:00:00+00:00"
        with self.assertRaisesRegex(ValueError, "different epochs"):
            audit_module.audit(fees, incentives, NOW)

    def test_rejects_source_fee_reward_mismatch(self):
        fees, incentives = fixture()
        incentives["pools"][0]["fees"][0]["last_four_weeks"][3]["raw"] = "9000000"
        with self.assertRaisesRegex(ValueError, "FEES reward records mismatch"):
            audit_module.audit(fees, incentives, NOW)

    def test_rejects_active_pool_identity_mismatch(self):
        fees, incentives = fixture()
        incentives["pools"][0]["gauge_address"] = "0x" + "f" * 40
        with self.assertRaisesRegex(ValueError, "identity/weight mismatch"):
            audit_module.audit(fees, incentives, NOW)

    def test_missing_or_stale_quote_is_not_zero(self):
        fees, incentives = fixture()
        missing = audit_module.audit(
            fees, {**incentives, "prices": {}}, NOW,
        )
        self.assertEqual(missing["audited_complete_usd_count"], 0)
        self.assertIsNone(
            missing["four_week_usd_totals_by_pool"][0]["avg_weekly_usd_at_saved_current_prices"]
        )
        stale = audit_module.audit(
            fees, incentives, NOW + timedelta(hours=37),
        )
        self.assertEqual(stale["audited_complete_usd_count"], 0)

    def test_truncated_registry_is_never_reported_complete(self):
        fees, incentives = fixture()
        incentives["pools"][0]["bribes_registry_truncated"] = True
        report = audit_module.audit(fees, incentives, NOW)
        self.assertEqual(report["audited_complete_usd_count"], 1)
        self.assertIsNone(
            report["four_week_usd_totals_by_pool"][0]["avg_weekly_usd_at_saved_current_prices"]
        )


if __name__ == "__main__":
    unittest.main()
