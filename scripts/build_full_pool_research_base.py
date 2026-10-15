#!/usr/bin/env python3
"""Build a read-only, two-epoch research dataset from all 38 P2 pool batches.

This does NOT combine two collection epochs into a synchronized market/yield
snapshot, and does NOT modify the existing 16-pool dashboard or hourly jobs.
It uses SAVED per-batch audits/quotes, never re-prices with today's market.
"""
import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from plan_pool_collection_base import save_atomic
from run_pool_batch_pipeline import BATCH_ROOT, PREFIX, paths_for, read_json, validate_manifest

OLD_THROUGH = 15
EXPECTED_EPOCHS = ("2026-10-08T00:00:00+00:00", "2026-10-15T00:00:00+00:00")
OUTPUT_NAME = "research_all_928_two_epochs.json"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def amount(value, label):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"Malformed decimal: {label}") from exc
    require(result.is_finite() and result >= 0, f"Invalid or negative decimal: {label}")
    return result


def token_summary(item, category, prices):
    require(isinstance(item, dict), "Reward token record must be an object")
    token = item.get("token_address")
    require(isinstance(token, str) and len(token) == 42 and
            token.startswith("0x"), "Invalid reward token address")
    records = item.get("last_four_weeks")
    require(isinstance(records, list) and len(records) == 4,
            f"Missing reward weekly history for {token}")
    raw = [amount(r.get("raw"), f"raw reward {token}") for r in records]
    quote = prices.get(token.lower(), {})
    if not isinstance(quote, dict):
        quote = {}
    decimals = item.get("decimals")
    if decimals is not None:
        require(type(decimals) is int and 0 <= decimals <= 36,
                f"Invalid reward decimals {token}")
    average = item.get("four_week_mean_amount")
    if average is not None:
        require(decimals is not None, f"Mean amount without decimals: {token}")
        require(
            abs(amount(average, f"mean amount {token}") -
                sum(raw) / Decimal(4) / (Decimal(10) ** decimals))
            <= Decimal("1e-18"),
            f"Reward average mismatch: {token}",
        )
    usd = item.get("usd_at_current_price")
    if usd is not None:
        amount(usd, f"USD {token}")
    return {
        "type": category,
        "address": token.lower(),
        "symbol": item.get("symbol"),
        "decimals": decimals,
        "mean_amount_per_week": average,
        "mean_usd_at_collection_quote": usd,
        "observed_positive_weeks": sum(x > 0 for x in raw),
        "quote_usd_per_token_at_collection": quote.get("price_usd"),
        "quote_timestamp_utc": quote.get("price_timestamp_utc"),
        "quote_missing_reason": quote.get("reason"),
    }


def verify_one_batch(folder, manifest, number, epoch, expected_ids, require_status):
    files = paths_for(folder, number)
    names = ("fees", "incentives", "audit")
    require(all(files[k].is_file() for k in names),
            f"Batch {number:03d} missing published FEES, BRIBES or audit")
    if require_status:
        require(files["status"].is_file(), f"Batch {number:03d} has no complete marker")
    fees, incentives, audit = (read_json(files[k]) for k in names)
    where = f"Batch {number:03d}"
    for name, doc in (("FEES", fees), ("BRIBES", incentives), ("AUDIT", audit)):
        require(doc.get("chain_id") == 8453, f"{where} {name} wrong chain")
    require(
        fees.get("current_epoch_start_utc") == epoch and
        incentives.get("current_epoch_utc") == epoch and
        audit.get("source_epoch_utc") == epoch,
        f"{where} epochs do not align",
    )
    require(incentives.get("week_count") == 4 and
            fees.get("completed_weeks_requested") == 4,
            f"{where} expected four completed weeks")
    planned = read_json(files["input"]).get("pools")
    fee_rows, price_rows, audit_rows = (
        fees.get("pools"), incentives.get("pools"),
        audit.get("four_week_usd_totals_by_pool"),
    )
    require(all(isinstance(v, list) for v in (planned, fee_rows, price_rows, audit_rows)),
            f"{where} malformed pool records")
    expected_size = len(expected_ids)
    require(len(planned) == expected_size and
            [p.get("index") for p in planned] == expected_ids,
            f"{where} planned input differs from manifest")
    # A source inventory pool can become inactive later, so a missing audited
    # pool is handled as an explicit coverage gap, NEVER a zero-USD pool.
    require(len(fee_rows) == expected_size, f"{where} FEES count mismatch")
    require([p.get("index") for p in fee_rows] == expected_ids,
            f"{where} FEES ordering does not match plan")
    fee_map = {p["index"]: p for p in fee_rows}
    actual_ids = [p.get("index") for p in audit_rows]
    require(len(set(actual_ids)) == len(actual_ids) and
            set(actual_ids).issubset(set(expected_ids)),
            f"{where} audit indices mismatch")
    bribe_ids = [p.get("index") for p in price_rows]
    require(len(set(bribe_ids)) == len(bribe_ids) and
            set(bribe_ids) == set(actual_ids),
            f"{where} BRIBES and AUDIT indices differ")
    require(audit.get("pool_count") == len(audit_rows),
            f"{where} audit pool count mismatch")
    usd_complete = sum(p.get("usd_coverage_complete_at_audit") is True for p in audit_rows)
    require(usd_complete == audit.get("audited_complete_usd_count"),
            f"{where} audited USD count mismatch")
    require(len(audit_rows) - usd_complete == audit.get("incomplete_usd_count"),
            f"{where} incomplete USD count mismatch")
    if require_status:
        status = read_json(files["status"])
        require(
            status.get("state") == "complete" and
            status.get("batch_number") == number and
            status.get("expected_pools") == expected_size and
            status.get("epoch_utc") == epoch and
            status.get("audited_active_pools") == len(audit_rows) and
            status.get("fully_priced_pools") == usd_complete,
            f"{where} status marker mismatch",
        )
    planned_map = {p["index"]: p for p in planned}
    price_map = {p["index"]: p for p in price_rows}
    quote_map = incentives.get("prices")
    require(isinstance(quote_map, dict), f"{where} missing saved quote map")
    output = []
    for item in audit_rows:
        idx = item["index"]
        planned_pool, src, inc = planned_map[idx], fee_map[idx], price_map[idx]
        addresses = (
            item.get("pool_address"), planned_pool.get("pool_address"),
            src.get("pool_address"), inc.get("pool_address"),
        )
        require(all(isinstance(a, str) for a in addresses) and
                len({a.lower() for a in addresses}) == 1,
                f"{where} pool #{idx}: incompatible addresses")
        require(src.get("active_at_collection") is True,
                f"{where} pool #{idx}: audit references inactive FEES")
        require(src.get("gauge_address", "").lower() ==
                inc.get("gauge_address", "").lower(),
                f"{where} pool #{idx}: gauge mismatch")
        require(src.get("pool_vote_weight_raw") ==
                inc.get("pool_vote_weight_raw"),
                f"{where} pool #{idx}: vote weight mismatch")
        complete = item.get("usd_coverage_complete_at_audit")
        require(type(complete) is bool,
                f"{where} pool #{idx}: invalid coverage flag")
        mean_usd = item.get("avg_weekly_usd_at_saved_current_prices")
        if complete:
            require(mean_usd is not None and
                    isinstance(item.get("weekly_usd_at_saved_current_prices"), list) and
                    len(item["weekly_usd_at_saved_current_prices"]) == 4,
                    f"{where} pool #{idx}: missing complete USD history")
            weekly = [amount(v, f"{where} #{idx} weekly USD")
                      for v in item["weekly_usd_at_saved_current_prices"]]
            require(abs(sum(weekly) / Decimal(4) -
                        amount(mean_usd, f"{where} #{idx} mean USD")) <= Decimal("1e-12"),
                    f"{where} pool #{idx}: USD weekly mean mismatch")
        else:
            require(mean_usd is None,
                    f"{where} pool #{idx}: partial USD misrepresented as complete")
        active_weeks = item.get("combined_positive_weeks")
        require(type(active_weeks) is int and 0 <= active_weeks <= 4,
                f"{where} pool #{idx}: invalid positive-week count")
        for field in ("fees_positive_weeks", "bribes_positive_weeks"):
            n = item.get(field)
            require(type(n) is int and 0 <= n <= active_weeks,
                    f"{where} pool #{idx}: invalid {field}")
        records = []
        for kind in ("fees", "bribes"):
            parts = inc.get(kind)
            require(isinstance(parts, list),
                    f"{where} pool #{idx}: {kind} token records missing")
            records.extend(token_summary(t, kind.upper(), quote_map) for t in parts)
        token_positive = [False] * 4
        # Explicitly recompute nonzero weeks from token reward raw values,
        # regardless of price coverage.
        for kind in ("fees", "bribes"):
            for token in inc[kind]:
                for i, row in enumerate(token["last_four_weeks"]):
                    token_positive[i] |= amount(row["raw"], f"{where} #{idx} token raw") > 0
        require(sum(token_positive) == active_weeks,
                f"{where} pool #{idx}: reward frequency mismatch")
        output.append({
            "index": idx,
            "address": addresses[0].lower(),
            "gauge_address": inc.get("gauge_address"),
            "inventory_snapshot_block": manifest["snapshot_block_number"],
            "inventory_snapshot_votes": item.get("snapshot_votes"),
            "collection_epoch_utc": epoch,
            "batch_number": number,
            "usd_coverage_complete": complete,
            "avg_pool_usd_per_week_at_collection_quote": mean_usd,
            "weekly_pool_usd_at_collection_quote":
                item.get("weekly_usd_at_saved_current_prices"),
            "illustrative_usd_per_million_inventory_votes":
                item.get("usd_per_million_snapshot_votes"),
            "observed_fees_positive_weeks": item["fees_positive_weeks"],
            "observed_bribes_positive_weeks": item["bribes_positive_weeks"],
            "observed_any_reward_positive_weeks": active_weeks,
            "max_week_share_of_four_week_usd":
                item.get("highest_week_share_of_four_week_total"),
            "no_observed_rewards": active_weeks == 0,
            "missing_or_stale_components": item.get("missing_or_stale_components", []),
            "truncated_reward_registry": bool(item.get("truncated_registry")),
            "token_rewards": records,
        })
    return output, usd_complete, sorted(set(expected_ids) - set(actual_ids))


def consolidate(original_folder, new_folder, completed_through=OLD_THROUGH):
    original_folder = original_folder.resolve()
    new_folder = new_folder.resolve()
    root = BATCH_ROOT.resolve()
    require(original_folder.is_relative_to(root) and new_folder.is_relative_to(root),
            "Both P2 batch folders must be inside isolated collection data root")
    original = validate_manifest(original_folder)
    newer = validate_manifest(new_folder)
    require(new_folder.parent == original_folder / "epochs",
            "New epoch folder must be beneath original folder/epochs")
    require(type(completed_through) is int and
            completed_through == newer.get("carry_forward_completed_through"),
            "Previously completed batch boundary mismatch")
    require(original.get("inventory_sha256") == newer.get("inventory_sha256") and
            original.get("snapshot_block_number") == newer.get("snapshot_block_number") and
            original.get("batch_count") == newer.get("batch_count") and
            original.get("batch_count") == 38 and
            original.get("active_pool_count") == newer.get("active_pool_count") == 928,
            "Collection plans do not refer to same 928-pool snapshot")
    require(newer.get("new_epoch_collection_start_batch") == completed_through + 1,
            "New plan does not begin after completed old batches")
    epoch_old = "2026-10-08T00:00:00+00:00"
    epoch_new = newer.get("collection_epoch_utc")
    require((epoch_old, epoch_new) == EXPECTED_EPOCHS and
            newer.get("prior_collection_epoch_utc") == epoch_old,
            "Unexpected Aerodrome collection epochs")
    require(new_folder.name == epoch_new[:10], "New-epoch folder naming mismatch")
    rows = []
    missing_from_audit = []
    per_epoch = {}
    seen = set()
    for epoch, start, finish, folder in (
        (epoch_old, 1, completed_through, original_folder),
        (epoch_new, completed_through + 1, original["batch_count"], new_folder),
    ):
        group = {
            "epoch_utc": epoch,
            "batch_start": start,
            "batch_end": finish,
            "planned_inventory_pools": 0,
            "audited_pools": 0,
            "complete_usd_pools": 0,
            "incomplete_usd_pools": 0,
            "no_observed_rewards_pools": 0,
            "positive_reward_pools": 0,
            "incomplete_pools": [],
        }
        for batch in range(start, finish + 1):
            planned_ids = original["batches"][batch - 1]["pool_indexes"]
            newer_ids = newer["batches"][batch - 1]["pool_indexes"]
            require(planned_ids == newer_ids,
                    f"Batch {batch:03d} differs between plans")
            expected_count = original["batches"][batch - 1]["pool_count"]
            require(len(planned_ids) == expected_count,
                    f"Batch {batch:03d} bad planned count")
            records, n_priced, absent = verify_one_batch(
                folder, original, batch, epoch, planned_ids, batch > 1,
            )
            for record in records:
                require(record["index"] not in seen,
                        f"Pool index {record['index']} is duplicated between epochs")
                seen.add(record["index"])
                rows.append(record)
                if not record["usd_coverage_complete"]:
                    group["incomplete_pools"].append({
                        "index": record["index"],
                        "batch_number": batch,
                        "missing_or_stale_components":
                            record["missing_or_stale_components"],
                        "truncated_reward_registry":
                            record["truncated_reward_registry"],
                    })
            for idx in absent:
                missing_from_audit.append({
                    "index": idx, "batch_number": batch,
                    "epoch_utc": epoch, "reason": "Not active/audited at collection",
                })
            group["planned_inventory_pools"] += expected_count
            group["audited_pools"] += len(records)
            group["complete_usd_pools"] += n_priced
        group["incomplete_usd_pools"] = (
            group["audited_pools"] - group["complete_usd_pools"]
        )
        group["no_observed_rewards_pools"] = sum(
            p["no_observed_rewards"] for p in rows
            if p["collection_epoch_utc"] == epoch
        )
        group["positive_reward_pools"] = (
            group["audited_pools"] - group["no_observed_rewards_pools"]
        )
        per_epoch[epoch] = group
    expected_all = [
        pool_id for entry in original["batches"]
        for pool_id in entry["pool_indexes"]
    ]
    require(len(set(expected_all)) == len(expected_all) == 928,
            "Original 928-pool inventory is incomplete or duplicated")
    require(seen.union({m["index"] for m in missing_from_audit}) == set(expected_all),
            "Some original inventory pools lack any collection classification")
    require(len(seen) + len(missing_from_audit) == 928,
            "Combined count differs from 928 planned inventory entries")
    rows.sort(key=lambda p: p["index"])
    result = {
        "schema_version": 1,
        "type": "Research inventory combining separately observed epochs (NOT a single synced snapshot)",
        "chain_id": 8453,
        "snapshot_block_number": original["snapshot_block_number"],
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "inventory_pool_count": 928,
        "audited_pool_count": len(rows),
        "audited_usd_complete_pool_count": sum(p["usd_coverage_complete"] for p in rows),
        "audited_usd_incomplete_pool_count": sum(not p["usd_coverage_complete"] for p in rows),
        "not_audited_at_collection": missing_from_audit,
        "by_collection_epoch": per_epoch,
        "pools": rows,
        "warnings": [
            "Epochs 2026-10-08 and 2026-10-15 are separate, never one synced market snapshot.",
            "All vote weights come from a pinned older block and are not epoch voting power.",
            "FEES/BRIBES epoch keys were queried at latest state, not archive-block snapshots.",
            "Past 4-week allocations are converted with each batch's saved CURRENT USD token quotes, "
            "not each historical week's token prices.",
            "Do not sum USD mean revenues or rank yields across different epochs.",
            "An active gauge can have no observed rewards; USD price coverage can still be complete.",
            "An incomplete quote is UNKNOWN, not zero; zero historical rewards do not predict zero future rewards.",
            "Do not treat USD-per-million-votes as an expected user return, yield or APR.",
            "Quoted token value does not guarantee on-chain liquidity or ability to exit.",
            "This file does not change any current dashboard, scheduled job, wallet or on-chain state.",
        ],
    }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original-folder", type=Path, default=BATCH_ROOT / PREFIX)
    parser.add_argument(
        "--new-folder", type=Path,
        default=BATCH_ROOT / PREFIX / "epochs" / "2026-10-15",
    )
    parser.add_argument(
        "--output-file", type=Path,
        default=BATCH_ROOT / PREFIX / OUTPUT_NAME,
    )
    args = parser.parse_args()
    output = args.output_file.resolve()
    root = BATCH_ROOT.resolve()
    if (not output.is_relative_to(root) or
            output.name != OUTPUT_NAME or
            output.parent != args.original_folder.resolve()):
        parser.error("Output must be the isolated original batch folder / " + OUTPUT_NAME)
    result = consolidate(args.original_folder, args.new_folder)
    save_atomic(output, result)
    print(
        f"VERIFIED: {result['audited_pool_count']}/{result['inventory_pool_count']} "
        f"audited | complete USD {result['audited_usd_complete_pool_count']}/"
        f"{result['audited_pool_count']}", flush=True,
    )
    for epoch, info in result["by_collection_epoch"].items():
        print(
            f"  {epoch}: {info['audited_pools']}/"
            f"{info['planned_inventory_pools']} audited, "
            f"USD complete {info['complete_usd_pools']}, "
            f"USD incomplete {info['incomplete_usd_pools']}, "
            f"no observed rewards {info['no_observed_rewards_pools']}",
            flush=True,
        )
    print(
        f"Missing from audit at collection: {len(result['not_audited_at_collection'])}",
        flush=True,
    )
    print(f"Saved separate research dataset: {output}", flush=True)
    print(
        "No new blockchain/price queries; old reports, dashboard and hourly tasks unchanged.",
        flush=True,
    )


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"RESEARCH DATASET NOT BUILT: {exc}", file=sys.stderr, flush=True)
        sys.exit(1)
