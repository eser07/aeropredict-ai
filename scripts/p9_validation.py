"""Strict saved P9 snapshot validation. No RPC and no writes to data/."""
import hashlib
import json
import re
from decimal import Decimal
from pathlib import Path
from serve_pool_research import saved_decimal

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "data/pool_collection_batches_base/p9_unified_research/block_52731839/registration_25"
INVENTORY = ROOT / "data/pool_collection_batches_base/p9_unified_inventory/active_pools.json"
EPOCH = "2026-10-15T00:00:00+00:00"


def address(value):
    return isinstance(value, str) and re.fullmatch(r"0x[0-9a-fA-F]{40}", value) is not None and int(value[2:], 16) > 0


def validate_snapshot(research, pairs, inventory, manifest):
    documents = (research, pairs, inventory, manifest)
    if not all(isinstance(d, dict) and d.get("chain_id") == 8453 for d in documents):
        raise ValueError("Expected Base Mainnet in all saved sources")
    for d in (research, inventory, manifest):
        if d.get("snapshot_block_number") != 52731839:
            raise ValueError("P9 inventory block mismatch")
    if research.get("collection_epoch_utc") != EPOCH:
        raise ValueError("P9 reward collection epoch mismatch")
    if inventory.get("complete") is not True or inventory.get("total_registered") != 2013 or inventory.get("active_pool_count") != 950:
        raise ValueError("Incomplete P9 active inventory")
    digest = hashlib.sha256(json.dumps(inventory, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
    if research.get("inventory_sha256") != digest or manifest.get("inventory_sha256") != digest:
        raise ValueError("Canonical inventory fingerprint mismatch")
    maps = []
    for d in (research, pairs, inventory):
        rows = d.get("pools")
        if not isinstance(rows, list) or len(rows) != 950 or any(not isinstance(r, dict) or type(r.get("index")) is not int or not 0 <= r["index"] < 2013 for r in rows):
            raise ValueError("Expected 950 valid pool records")
        indexed = {r["index"]: r for r in rows}
        if len(indexed) != 950:
            raise ValueError("Duplicate P9 pool index")
        maps.append(indexed)
    pools, pair_map, inventory_map = maps
    if set(pools) != set(pair_map) or set(pools) != set(inventory_map):
        raise ValueError("Pool sets differ between saved sources")
    batches = manifest.get("batches")
    if not isinstance(batches, list) or len(batches) != 38 or manifest.get("batch_count") != 38:
        raise ValueError("P9 technical collection coverage mismatch")
    assignments = {}
    for batch in batches:
        number = batch.get("number")
        if type(number) is not int or not 1 <= number <= 38 or batch.get("pool_count") != len(batch.get("pool_indexes", [])):
            raise ValueError("Invalid batch manifest identity")
        for index in batch["pool_indexes"]:
            if index in assignments:
                raise ValueError("Duplicate pool in collection manifest")
            assignments[index] = number
    if set(assignments) != set(pools):
        raise ValueError("Collection manifest does not cover the active pool set")
    complete = zero = 0
    unresolved = []
    for index, pool in pools.items():
        pair = pair_map[index]
        inv = inventory_map[index]
        if not address(pool.get("address")) or not address(pool.get("gauge_address")):
            raise ValueError("Invalid pool or gauge address")
        if any(value.lower() != pool["address"].lower() for value in (pair.get("pool_address", ""), inv.get("pool_address", ""))):
            raise ValueError("Pool address differs between sources")
        if pool["gauge_address"].lower() != inv.get("gauge_address", "").lower() or inv.get("gauge_active") is not True:
            raise ValueError("Gauge identity or active status mismatch")
        if pool.get("inventory_snapshot_block") != 52731839 or pool.get("collection_epoch_utc") != EPOCH or pool.get("batch_number") != assignments[index]:
            raise ValueError("Pool provenance mismatch")
        if type(pool.get("usd_coverage_complete")) is not bool or type(pool.get("no_observed_rewards")) is not bool:
            raise ValueError("Invalid USD coverage or reward flag")
        counts = [pool.get(k) for k in ("observed_any_reward_positive_weeks", "observed_fees_positive_weeks", "observed_bribes_positive_weeks")]
        if any(type(n) is not int or not 0 <= n <= 4 for n in counts) or max(counts[1:]) > counts[0] or counts[0] > sum(counts[1:]):
            raise ValueError("Invalid reward-positive week counts")
        if pool["no_observed_rewards"] != (counts[0] == 0):
            raise ValueError("Zero reward and missing-price distinction is inconsistent")
        if not isinstance(pool.get("token_rewards"), list):
            raise ValueError("Missing token reward records")
        complete += pool["usd_coverage_complete"]
        zero += pool["no_observed_rewards"]
        if pool["usd_coverage_complete"]:
            weeks = pool.get("weekly_pool_usd_at_collection_quote")
            if not isinstance(weeks, list) or len(weeks) != 4:
                raise ValueError("Expected four audited USD totals")
            total = sum((saved_decimal(v) for v in weeks), Decimal(0))
            average = saved_decimal(pool.get("avg_pool_usd_per_week_at_collection_quote"))
            if abs(total / 4 - average) > max(total, Decimal(1)) * Decimal("1e-20"):
                raise ValueError("Audited average does not reconcile")
        elif pool.get("avg_pool_usd_per_week_at_collection_quote") is not None:
            raise ValueError("Incomplete USD pool has a misleading full average")
        if not pair.get("token0_symbol") or not pair.get("token1_symbol"):
            unresolved.append(index)
    expected = {"inventory_pool_count": 950, "audited_pool_count": 950,
                "audited_usd_complete_pool_count": complete, "audited_usd_incomplete_pool_count": 950 - complete,
                "no_observed_rewards_pool_count": zero}
    if any(research.get(key) != value for key, value in expected.items()) or (complete, zero, sorted(unresolved)) != (904, 249, [1130]):
        raise ValueError("P9 summary counters do not match saved rows")
    return {"chain_id": 8453, "snapshot_block_number": 52731839, "collection_epoch_utc": EPOCH,
            "active_pools": 950, "registered_pools": 2013, "technical_batches": 38,
            "usd_complete": complete, "usd_incomplete": 950 - complete, "zero_observed_rewards": zero,
            "resolved_pairs": 950 - len(unresolved), "unresolved_pairs": unresolved,
            "canonical_inventory_sha256": digest}


def load_snapshot():
    paths = (FOLDER / "research_all_950_one_epoch.json", FOLDER / "pool_pairs_950_base.json", INVENTORY, FOLDER / "manifest.json")
    docs = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    return docs, validate_snapshot(*docs)
