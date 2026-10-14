#!/usr/bin/env python3
"""Validate a COMPLETE pinned-block Aerodrome inventory and plan safe collection batches.

No RPC, wallet, or price requests. This intentionally never changes the
existing expanded 16-pool input, dashboard bundle, or hourly refresh task.
Voting-weight order is a coverage heuristic, NOT a fee or yield ranking.
"""
import argparse
import hashlib
import json
import sys
import tempfile
import os
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from discover_active_pools_base import validate_progress

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SOURCE = DATA / "pool_discovery_active_base.json"
OUTPUT_ROOT = DATA / "pool_collection_batches_base"
MAX_BATCH_SIZE = 50


def fingerprint(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def validate_complete_inventory(document):
    if not isinstance(document, dict):
        raise ValueError("Inventory must be a JSON object")
    # Give a clear error for explicitly inactive gauges before the shared
    # checkpoint validator's more general malformed-record rejection.
    pools = document.get("pools")
    if isinstance(pools, list):
        for pool in pools:
            if isinstance(pool, dict) and pool.get("gauge_active") is False:
                raise ValueError("Inventory includes a gauge not marked alive")
    validate_progress(document)
    if document.get("complete") is not True:
        raise ValueError("Inventory is partial; wait for discovery COMPLETE")
    if document["next_index"] != document["total_registered"]:
        raise ValueError("Inventory did not inspect all registration indexes")
    if document.get("scan_end_exclusive") != document["total_registered"]:
        raise ValueError("Inventory has an unexpected scan end")
    if document.get("coverage_percent") != 100:
        raise ValueError("Inventory coverage must be exactly 100%")
    if not isinstance(document.get("total_voting_weight_raw"), str) or not (
        document["total_voting_weight_raw"].isdigit()
    ):
        raise ValueError("Inventory total voting weight is malformed")
    if not document["pools"]:
        raise ValueError("Inventory has no active pools")
    # Recheck deterministic ordering in the original registry. All entries
    # are active gauges at the pinned block, not guaranteed reward earners.
    for pool in document["pools"]:
        if pool["gauge_active"] is not True:
            raise ValueError("Inventory includes a gauge not marked alive")
    return document


def make_batches(document, batch_size=25, order="votes"):
    validate_complete_inventory(document)
    if type(batch_size) is not int or not 1 <= batch_size <= MAX_BATCH_SIZE:
        raise ValueError("Batch size must be between 1 and 50")
    if order not in ("votes", "registration"):
        raise ValueError("Order must be votes or registration")
    entries = list(document["pools"])
    if order == "votes":
        entries.sort(key=lambda p: (-int(p["weight_raw"]), p["index"]))
    else:
        entries.sort(key=lambda p: p["index"])
    return [entries[i:i + batch_size] for i in range(0, len(entries), batch_size)]


def save_atomic(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", prefix=".batch_",
            suffix=".json", dir=path.parent, delete=False,
        ) as handle:
            temp = Path(handle.name)
            json.dump(obj, handle, indent=2, ensure_ascii=False, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if temp is not None and temp.exists():
            temp.unlink()


def prepare_batches(document, batch_size=25, order="votes", output_root=OUTPUT_ROOT):
    chunks = make_batches(document, batch_size, order)
    block = document["snapshot_block_number"]
    destination = Path(output_root) / f"block_{block}" / f"{order}_{batch_size}"
    manifest_file = destination / "manifest.json"
    source_hash = fingerprint(document)
    if manifest_file.is_file():
        previous = json.loads(manifest_file.read_text(encoding="utf-8"))
        if previous.get("inventory_sha256") != source_hash:
            raise RuntimeError(
                "Existing batch plan belongs to different inventory content. "
                "Original files were not changed."
            )
    count_zero = sum(int(p["weight_raw"]) == 0 for p in document["pools"])
    manifest = {
        "schema_version": 1,
        "type": "Aerodrome independent collection plan (NOT collected rewards)",
        "chain_id": document["chain_id"],
        "snapshot_block_number": block,
        "total_registered": document["total_registered"],
        "active_pool_count": document["active_pool_count"],
        "inactive_registered_count": document["total_registered"] - document["active_pool_count"],
        "zero_weight_active_count": count_zero,
        "inventory_sha256": source_hash,
        "batch_size_limit": batch_size,
        "batch_order": order,
        "batch_count": len(chunks),
        "all_batches_pool_count": sum(len(chunk) for chunk in chunks),
        "notices": [
            "All active gauges are evaluated at one past Base block, not live.",
            "Voting-weight order is NOT fee revenue, opportunity or expected payout rank.",
            "Rewards, token prices and claimable income have NOT been collected.",
            "Each batch is an optional input for separate collection; never feed these "
            "files directly into the current hourly refresh.",
            "Later FEES/BRIBES reads use newer chain state; gauge status can change.",
        ],
        "batches": [],
    }
    for number, entries in enumerate(chunks, 1):
        filename = f"batch_{number:03d}.json"
        share = sum(int(p["weight_raw"]) for p in entries)
        total_weight = int(document["total_voting_weight_raw"])
        pct = (
            format(Decimal(share) * 100 / Decimal(total_weight), ".6f")
            if total_weight else None
        )
        batch = {
            "schema_version": 1,
            "source": "P2 independent subset of complete Aerodrome pool registry",
            "chain_id": document["chain_id"],
            "voter": document["voter"],
            "block_number": block,
            "snapshot_block_number": block,
            "total_registered": document["total_registered"],
            "total_voting_weight_raw": document["total_voting_weight_raw"],
            "fetched_at_utc": document.get("fetched_at_utc"),
            "batch_number": number,
            "batch_count": len(chunks),
            "selection_policy": f"all active gauges at pinned Base block, ordered by {order}",
            "inventory_sha256": source_hash,
            "active_pool_count": len(entries),
            "pools": entries,
            "notice": "Voting weights are NOT FEES, BRIBES, USD returns or yield rankings.",
        }
        save_atomic(destination / filename, batch)
        manifest["batches"].append({
            "number": number,
            "file": str((destination / filename).relative_to(ROOT))
                if (destination / filename).is_relative_to(ROOT) else str(destination / filename),
            "pool_count": len(entries),
            "first_pool_index": entries[0]["index"],
            "last_pool_index": entries[-1]["index"],
            "summed_snapshot_vote_share_percent": pct,
            "pool_indexes": [entry["index"] for entry in entries],
        })
    # Publish manifest last: all referenced batch files have been written.
    save_atomic(manifest_file, manifest)
    return manifest, manifest_file


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=25, help="Pools per batch (1-50)")
    parser.add_argument("--order", choices=("votes", "registration"), default="votes",
                        help="Prioritize by snapshot vote weight or registry position")
    args = parser.parse_args()
    if not 1 <= args.batch_size <= MAX_BATCH_SIZE:
        parser.error("--batch-size must be between 1 and 50")
    if not SOURCE.is_file():
        raise RuntimeError("Complete discovery file missing: data/pool_discovery_active_base.json")
    document = json.loads(SOURCE.read_text(encoding="utf-8"))
    manifest, filename = prepare_batches(document, args.batch_size, args.order)
    print(
        f"VERIFIED: Base block {manifest['snapshot_block_number']} | "
        f"registered {manifest['total_registered']} | active {manifest['active_pool_count']} | "
        f"inactive {manifest['inactive_registered_count']} | "
        f"active with zero snapshot vote weight {manifest['zero_weight_active_count']}",
        flush=True,
    )
    print(
        f"PLANNED: {manifest['batch_count']} offline batches of at most "
        f"{args.batch_size} pools | ordering: {args.order}", flush=True,
    )
    print(f"Saved manifest: {filename}", flush=True)
    print("No RPC requests; no FEES/BRIBES/USD collected; existing dashboard unchanged.", flush=True)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
