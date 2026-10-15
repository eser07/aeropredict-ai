#!/usr/bin/env python3
"""Collect one-block veAERO Voter weights for the historical 928-pool cohort.

Independent read-only P4 research. All weights and totalWeight use one pinned
Base Mainnet block, even across resumptions. This is NOT a live complete pool
inventory, synchronized reward snapshot, APR, or wallet payout estimate.
"""
import argparse
import fcntl
import json
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from discover_active_pools_base import rpc_checked, save_atomic
from plan_pool_collection_base import fingerprint, validate_complete_inventory
from reward_epochs import rpc_object
from reward_tokens import CHAIN_ID, rpc
from scan_pools_base import VOTER, read_uint

INVENTORY = Path("data/pool_discovery_active_base.json")
DESTINATION = Path("data/p4_vote_snapshots_base")
SCHEMA = 1


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def load_inventory():
    source = validate_complete_inventory(
        json.loads(INVENTORY.read_text(encoding="utf-8"))
    )
    return source, fingerprint(source)


def block_info(block):
    tag = hex(block)
    item = rpc_checked(
        lambda: rpc_object("eth_getBlockByNumber", [tag, False]),
        "Read pinned Base block",
    )
    if not isinstance(item, dict) or int(item["number"], 16) != block:
        raise RuntimeError("RPC returned a different pinned block")
    value = item.get("hash")
    if not isinstance(value, str) or len(value) != 66 or not value.startswith("0x"):
        raise RuntimeError("Pinned Base block has no valid hash")
    return value.lower(), datetime.fromtimestamp(
        int(item["timestamp"], 16), timezone.utc
    ).isoformat()


def verify_chain():
    chain = int(rpc_checked(lambda: rpc("eth_chainId", []), "Check Base chain"), 16)
    if chain != CHAIN_ID:
        raise RuntimeError("Wrong network: Base Mainnet (8453) required")


def start(inventory, source_sha):
    verify_chain()
    block = int(rpc_checked(
        lambda: rpc("eth_blockNumber", []), "Read latest Base block"
    ), 16)
    block_hash, block_time = block_info(block)
    total = rpc_checked(
        lambda: read_uint("totalWeight()", None, hex(block)),
        "Read pinned Voter totalWeight",
    )
    if total < 0:
        raise RuntimeError("Negative total voting weight")
    return {
        "schema_version": SCHEMA,
        "chain_id": CHAIN_ID,
        "voter": VOTER,
        "snapshot_block_number": block,
        "snapshot_block_hash": block_hash,
        "snapshot_block_timestamp_utc": block_time,
        "source_inventory_sha256": source_sha,
        "source_inventory_block_number": inventory["snapshot_block_number"],
        "selection_policy": "pools alive in older pinned inventory, NOT all pools alive now",
        "total_voting_weight_raw": str(total),
        "expected_pools": len(inventory["pools"]),
        "next_offset": 0,
        "pools": [],
        "started_at_utc": utc_now(),
        "last_page_completed_at_utc": None,
        "complete": False,
    }


def validate(progress, inventory, source_sha):
    expected = inventory["pools"]
    if (progress.get("schema_version") != SCHEMA
            or progress.get("chain_id") != CHAIN_ID
            or str(progress.get("voter", "")).lower() != VOTER.lower()
            or progress.get("source_inventory_sha256") != source_sha
            or progress.get("source_inventory_block_number") != inventory["snapshot_block_number"]
            or progress.get("expected_pools") != len(expected)):
        raise ValueError("P4 checkpoint does not match original 928-pool cohort")
    block = progress.get("snapshot_block_number")
    offset = progress.get("next_offset")
    if type(block) is not int or block <= 0 or type(offset) is not int:
        raise ValueError("Invalid pinned block or progress offset")
    if not 0 <= offset <= len(expected) or progress.get("complete") != (offset == len(expected)):
        raise ValueError("Invalid checkpoint completion state")
    value = progress.get("snapshot_block_hash")
    total = progress.get("total_voting_weight_raw")
    if (not isinstance(value, str) or len(value) != 66
            or not isinstance(total, str) or not total.isdigit()):
        raise ValueError("Missing pinned block identity or totalWeight")
    rows = progress.get("pools")
    if not isinstance(rows, list) or len(rows) != offset:
        raise ValueError("Checkpoint has a gap or duplicate rows")
    for row, original in zip(rows, expected):
        if (row.get("index") != original["index"]
                or str(row.get("pool_address", "")).lower() != original["pool_address"].lower()
                or not isinstance(row.get("weight_raw"), str)
                or not row["weight_raw"].isdigit()):
            raise ValueError("Checkpoint pool identity or voting weight mismatch")
    return progress


def verify_pinned(progress):
    verify_chain()
    block = progress["snapshot_block_number"]
    block_hash, _ = block_info(block)
    if block_hash != progress["snapshot_block_hash"]:
        raise RuntimeError("Pinned block hash changed; refusing mixed/reorged data")
    total = rpc_checked(
        lambda: read_uint("totalWeight()", None, hex(block)),
        "Recheck pinned Voter totalWeight",
    )
    if str(total) != progress["total_voting_weight_raw"]:
        raise RuntimeError("Pinned totalWeight changed; refusing mixed snapshot")


def collect_page(progress, inventory, page_size, delay):
    """Read one full page before checkpointing it atomically."""
    block_tag = hex(progress["snapshot_block_number"])
    total = int(progress["total_voting_weight_raw"])
    first = progress["next_offset"]
    end = min(first + page_size, progress["expected_pools"])
    additions = []
    for offset in range(first, end):
        item = inventory["pools"][offset]
        value = rpc_checked(
            lambda pool=item["pool_address"]: read_uint(
                "weights(address)", pool, block_tag
            ),
            f"Pool #{item['index']} pinned voting weight",
        )
        if value < 0:
            raise RuntimeError("Negative pool voting weight")
        share = (format(Decimal(value) * 100 / Decimal(total), ".8f")
                 if total else None)
        additions.append({
            "index": item["index"],
            "pool_address": item["pool_address"].lower(),
            "weight_raw": str(value),
            "vote_share_percent": share,
        })
        if delay and offset + 1 < end:
            time.sleep(delay)
    result = dict(progress)
    result["pools"] = progress["pools"] + additions
    result["next_offset"] = end
    result["last_page_completed_at_utc"] = utc_now()
    result["complete"] = end == progress["expected_pools"]
    return result


def run(page_size=25, max_pages=1, delay=0.1, until_complete=False, new=False):
    if not 1 <= page_size <= 100 or not 1 <= max_pages <= 1000 or not 0 <= delay <= 5:
        raise ValueError("Invalid page size, page limit, or delay")
    inventory, source_sha = load_inventory()
    DESTINATION.mkdir(parents=True, exist_ok=True)
    with (DESTINATION / ".p4_votes.lock").open("a+") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Another P4 vote collection is running") from None
        return _run(inventory, source_sha, page_size, max_pages, delay, until_complete, new)


def _run(inventory, source_sha, page_size, max_pages, delay, until_complete, new):
    pending = []
    completed = []
    for filename in sorted(DESTINATION.glob("block_*/checkpoint.json")):
        doc = validate(
            json.loads(filename.read_text(encoding="utf-8")), inventory, source_sha
        )
        (completed if doc["complete"] else pending).append((filename, doc))
    if len(pending) > 1:
        raise RuntimeError("Multiple incomplete P4 snapshots; choose manually")
    if pending:
        if new:
            raise RuntimeError("An incomplete snapshot exists; finish it before --new")
        checkpoint, progress = pending[0]
        verify_pinned(progress)
    else:
        if completed and not new:
            newest = completed[-1][1]
            print(f"Existing P4 snapshot complete at block {newest['snapshot_block_number']}. "
                  "Use --new only when intentionally starting a NEW snapshot.")
            return newest
        progress = start(inventory, source_sha)
        folder = DESTINATION / f"block_{progress['snapshot_block_number']}"
        checkpoint = folder / "checkpoint.json"
        if folder.exists():
            raise RuntimeError("Pinned block output already exists; refusing overwrite")
        save_atomic(checkpoint, progress)
    print(
        f"P4 Base pinned block {progress['snapshot_block_number']} | "
        f"cohort {progress['expected_pools']} | resume {progress['next_offset']}",
        flush=True,
    )
    remaining = progress["expected_pools"] - progress["next_offset"]
    pages = (remaining + page_size - 1) // page_size
    count = pages if until_complete else min(pages, max_pages)
    for _ in range(count):
        start_offset = progress["next_offset"]
        progress = collect_page(progress, inventory, page_size, delay)
        validate(progress, inventory, source_sha)
        save_atomic(checkpoint, progress)
        print(
            f"Saved page {start_offset}-{progress['next_offset']} / "
            f"{progress['expected_pools']} at SAME pinned block", flush=True
        )
    if progress["complete"]:
        verify_pinned(progress)
        filename = checkpoint.with_name("snapshot.json")
        if filename.exists():
            raise RuntimeError("P4 complete snapshot already exists; refusing overwrite")
        published = {
            **progress,
            "published_at_utc": utc_now(),
            "warning": (
                "One-block Voter weights for an older 928-pool selection only. "
                "Not synchronized with stored FEES/BRIBES, not all currently "
                "active pools, not veAERO APR or wallet earnings."
            ),
        }
        save_atomic(filename, published)
        print(f"COMPLETE single-block P4 vote snapshot: {filename}", flush=True)
    else:
        print(
            f"PARTIAL: {progress['next_offset']}/{progress['expected_pools']}. "
            "Rerun the SAME command to resume pinned block; no APR implied.",
            flush=True,
        )
    return progress


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--page-size", type=int, default=25)
    parser.add_argument("--max-pages", type=int, default=1)
    parser.add_argument("--delay-seconds", type=float, default=0.1)
    parser.add_argument("--until-complete", action="store_true")
    parser.add_argument("--new", action="store_true",
                        help="Start a separate new block after prior snapshot is complete")
    args = parser.parse_args()
    run(args.page_size, args.max_pages, args.delay_seconds,
        args.until_complete, args.new)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"P4 VOTE COLLECTION STOPPED: {exc}", file=sys.stderr, flush=True)
        sys.exit(1)
