#!/usr/bin/env python3
"""Discover all registered, currently alive Aerodrome Base pools, page by page.

Discovery is opt-in and DOES NOT replace the existing 16-pool dashboard,
the hourly refresh candidate file, or either of their datasets.

All pages use one pinned Base block to avoid treating different chain states
as one complete registry. Public RPC providers may stop serving that old block:
if so, keep the checkpoint, use an archive-capable RPC, or explicitly --restart.
"""
import argparse
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from reward_tokens import CHAIN_ID, rpc
from scan_pools_base import VOTER, read_address, read_uint

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CHECKPOINT = DATA / "pool_discovery_checkpoint_base.json"
RESULT = DATA / "pool_discovery_active_base.json"
ZERO = "0x" + "0" * 40
SCHEMA_VERSION = 1


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def save_atomic(path, obj):
    """Never expose a partially written registry or progress document."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".json",
            prefix=".pool_discovery_", dir=path.parent, delete=False,
        ) as handle:
            tmp = Path(handle.name)
            json.dump(obj, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if tmp is not None and tmp.exists():
            tmp.unlink()


def address_ok(value):
    return (
        isinstance(value, str) and len(value) == 42 and
        value.startswith("0x") and
        all(char in "0123456789abcdefABCDEF" for char in value[2:])
    )


def validate_progress(progress):
    if progress.get("schema_version") != SCHEMA_VERSION or progress.get("chain_id") != CHAIN_ID:
        raise ValueError("Checkpoint schema or Base chain ID mismatch; not resuming")
    if str(progress.get("voter", "")).lower() != VOTER.lower():
        raise ValueError("Checkpoint Voter contract mismatch")
    block = progress.get("snapshot_block_number")
    length = progress.get("total_registered")
    next_index = progress.get("next_index")
    if not all(type(v) is int for v in (block, length, next_index)):
        raise ValueError("Malformed checkpoint block, registry length or index")
    if block < 1 or length < 1 or not 0 <= next_index <= length:
        raise ValueError("Checkpoint contains invalid scan boundaries")
    pools = progress.get("pools")
    if not isinstance(pools, list) or len(pools) > next_index:
        raise ValueError("Malformed discovered active pools")
    indexes = set()
    addresses = set()
    for entry in pools:
        idx = entry.get("index")
        addr = entry.get("pool_address")
        gauge = entry.get("gauge_address")
        if (type(idx) is not int or not 0 <= idx < next_index or idx in indexes or
                not address_ok(addr) or not address_ok(gauge) or
                not entry.get("gauge_active") or int(gauge, 16) == 0):
            raise ValueError("Malformed or duplicate active pool in checkpoint")
        if addr.lower() in addresses:
            raise ValueError("Duplicate active pool address in checkpoint")
        weight = entry.get("weight_raw")
        if not isinstance(weight, str) or not weight.isdigit():
            raise ValueError("Malformed voting weight in checkpoint")
        indexes.add(idx)
        addresses.add(addr.lower())
    if progress.get("active_pool_count") != len(pools):
        raise ValueError("Active pool count mismatch in checkpoint")
    return True


def begin_scan():
    if int(rpc("eth_chainId", []), 16) != CHAIN_ID:
        raise RuntimeError("Wrong chain ID; expected Base Mainnet (8453)")
    block = int(rpc("eth_blockNumber", []), 16)
    tag = hex(block)
    count = read_uint("length()", None, tag)
    weight = read_uint("totalWeight()", None, tag)
    if not 0 < count < 1000000:
        raise RuntimeError(f"Unexpected Aerodrome registration count: {count}")
    if weight < 0:
        raise RuntimeError("Unexpected negative voting weight")
    return {
        "schema_version": SCHEMA_VERSION,
        "source": "Aerodrome Voter Base RPC pinned-block registry inventory",
        "chain_id": CHAIN_ID,
        "voter": VOTER,
        "snapshot_block_number": block,
        "total_registered": count,
        "total_voting_weight_raw": str(weight),
        "scan_start": 0,
        "next_index": 0,
        "scan_end_exclusive": 0,
        "active_pool_count": 0,
        "pools": [],
        "started_at_utc": utc_now(),
        "last_page_completed_at_utc": None,
        "complete": False,
        "notice": (
            "This is a pinned-block inventory, not a live yield ranking. "
            "Completeness is asserted only after every registration index is inspected. "
            "Historical pinned blocks may require an archive-enabled RPC."
        ),
    }


def inspect_page(progress, page_size, delay):
    """Stage one page in memory, committing the checkpoint only if it finishes."""
    tag = hex(progress["snapshot_block_number"])
    start = progress["next_index"]
    end = min(start + page_size, progress["total_registered"])
    active = []
    total_weight = int(progress["total_voting_weight_raw"])
    for index in range(start, end):
        address = read_address("pools(uint256)", index, tag)
        if not address_ok(address) or int(address, 16) == 0:
            raise RuntimeError(f"Invalid pool address for index {index}")
        gauge = read_address("gauges(address)", address, tag)
        if not address_ok(gauge):
            raise RuntimeError(f"Invalid gauge address for index {index}")
        alive = (
            int(gauge, 16) != 0 and
            bool(read_uint("isAlive(address)", gauge, tag))
        )
        if alive:
            raw_weight = read_uint("weights(address)", address, tag)
            if raw_weight < 0:
                raise RuntimeError(f"Negative weight for pool index {index}")
            share = (
                format(Decimal(raw_weight) * 100 / Decimal(total_weight), ".8f")
                if total_weight > 0 else None
            )
            active.append({
                "index": index,
                "pool_address": address,
                "gauge_address": gauge,
                "gauge_active": True,
                "weight_raw": str(raw_weight),
                "vote_share_percent": share,
            })
        if delay > 0 and index + 1 < end:
            time.sleep(delay)
    # Construct a new checkpoint; no valid completed page is lost on RPC errors.
    next_progress = dict(progress)
    next_progress["pools"] = progress["pools"] + active
    next_progress["next_index"] = end
    next_progress["scan_end_exclusive"] = end
    next_progress["active_pool_count"] = len(next_progress["pools"])
    next_progress["last_page_completed_at_utc"] = utc_now()
    next_progress["complete"] = end == progress["total_registered"]
    validate_progress(next_progress)
    return next_progress, len(active)


def run_scan(page_size=25, max_pages=1, delay=0.1, restart=False):
    DATA.mkdir(parents=True, exist_ok=True)
    if restart or not CHECKPOINT.is_file():
        if restart:
            print("Explicit restart: starting a new pinned-block inventory.", flush=True)
        progress = begin_scan()
        save_atomic(CHECKPOINT, progress)
    else:
        progress = json.loads(CHECKPOINT.read_text(encoding="utf-8"))
        validate_progress(progress)
        if int(rpc("eth_chainId", []), 16) != CHAIN_ID:
            raise RuntimeError("Wrong chain ID while resuming saved inventory")
        tag = hex(progress["snapshot_block_number"])
        # If the RPC can no longer read the pinned block, stop rather than
        # silently combine registry states from different moments.
        if read_uint("length()", None, tag) != progress["total_registered"]:
            raise RuntimeError("Pinned-block registry length mismatch; checkpoint retained")
        if str(read_uint("totalWeight()", None, tag)) != progress["total_voting_weight_raw"]:
            raise RuntimeError("Pinned-block total voting weight mismatch; checkpoint retained")

    if progress["complete"]:
        print("Inventory already complete. Use --restart for a new pinned block.", flush=True)
        return progress

    print(
        f"Base block {progress['snapshot_block_number']} | "
        f"registered {progress['total_registered']} | "
        f"resuming at index {progress['next_index']}",
        flush=True,
    )
    for page in range(max_pages):
        if progress["complete"]:
            break
        start = progress["next_index"]
        progress, found = inspect_page(progress, page_size, delay)
        save_atomic(CHECKPOINT, progress)
        print(
            f"Page {page + 1}/{max_pages}: scanned [{start}, {progress['next_index']}) "
            f"| active on page: {found} | total active found: {progress['active_pool_count']}",
            flush=True,
        )

    if progress["complete"]:
        # Publish a discoverable, explicitly COMPLETE inventory only when
        # the entire registry was traversed at the same pinned block.
        result = {
            **progress,
            "scan_end_exclusive": progress["total_registered"],
            "fetched_at_utc": utc_now(),
            "coverage_percent": 100,
            "selection_policy": "all gauges alive at pinned Base block",
            "publish_warning": (
                "Independent discovery output. NOT used as dashboard or hourly "
                "refresh input until a separate capacity-aware migration passes."
            ),
        }
        save_atomic(RESULT, result)
        print(
            f"COMPLETE: {result['active_pool_count']} active pools of "
            f"{result['total_registered']} registered. Saved: {RESULT}",
            flush=True,
        )
    else:
        remaining = progress["total_registered"] - progress["next_index"]
        percent = progress["next_index"] / progress["total_registered"] * 100
        print(
            f"PARTIAL: {percent:.2f}% inspected; {remaining} indices left. "
            f"Rerun the same command to resume from checkpoint. "
            f"Do NOT treat partial results as all active pools.",
            flush=True,
        )
    return progress


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--page-size", type=int, default=25, help="Indexes per page (1-100)")
    parser.add_argument("--max-pages", type=int, default=1, help="Pages in this run (1-20)")
    parser.add_argument("--delay-seconds", type=float, default=0.1,
                        help="Pause between inspected indices (0-5 seconds)")
    parser.add_argument("--restart", action="store_true",
                        help="Discard incomplete checkpoint and begin at a fresh pinned block")
    args = parser.parse_args()
    if not 1 <= args.page_size <= 100:
        parser.error("--page-size must be 1-100")
    if not 1 <= args.max_pages <= 20:
        parser.error("--max-pages must be 1-20")
    if not 0 <= args.delay_seconds <= 5:
        parser.error("--delay-seconds must be 0-5")
    run_scan(args.page_size, args.max_pages, args.delay_seconds, args.restart)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, TypeError, KeyError, json.JSONDecodeError) as exc:
        print(
            f"DISCOVERY PAUSED: {exc}. Last completed page is retained; "
            "hourly dashboard data were not changed.",
            file=sys.stderr, flush=True,
        )
        sys.exit(1)
