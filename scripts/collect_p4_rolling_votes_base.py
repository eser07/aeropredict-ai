#!/usr/bin/env python3
"""P4 rolling Base vote observations: resume across blocks, never claim one snapshot.

Keeps the existing pinned P4 checkpoint untouched. Each NEW page reads its
weights and totalWeight at ONE pinned block. Different pages may use different
blocks, with explicit provenance; these rows must NEVER be totaled into a
single-time vote distribution or treated as synchronized veAERO APR.
"""
import argparse
import fcntl
import json
import re
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
PINNED_CHECKPOINT = Path("data/p4_vote_snapshots_base/block_52646576/checkpoint.json")
ROOT = Path("data/p4_rolling_votes_base")
SCHEMA = 1


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def load_inventory():
    data = validate_complete_inventory(json.loads(INVENTORY.read_text(encoding="utf-8")))
    return data, fingerprint(data)


def valid_address(text):
    return (isinstance(text, str) and re.fullmatch(r"0x[0-9a-fA-F]{40}", text)
            is not None)


def validate_checkpoint(doc, inventory, source_sha):
    expected = inventory["pools"]
    if (doc.get("schema_version") != SCHEMA or doc.get("chain_id") != CHAIN_ID
            or str(doc.get("voter", "")).lower() != VOTER.lower()
            or doc.get("source_inventory_sha256") != source_sha
            or doc.get("expected_pools") != len(expected)
            or doc.get("source_inventory_block_number") != inventory["snapshot_block_number"]):
        raise ValueError("Rolling checkpoint belongs to a different inventory")
    offset = doc.get("next_offset")
    pages = doc.get("pages")
    if (type(offset) is not int or not 0 <= offset <= len(expected)
            or not isinstance(pages, list)
            or doc.get("complete") is not (offset == len(expected))):
        raise ValueError("Rolling checkpoint has invalid progress")
    cursor = 0
    for page in pages:
        n = page.get("block_number")
        h = page.get("block_hash")
        total = page.get("total_voting_weight_raw")
        end = page.get("end_offset")
        rows = page.get("pools")
        if (page.get("start_offset") != cursor or type(end) is not int
                or not cursor < end <= offset
                or type(n) is not int or n <= 0
                or not isinstance(h, str) or re.fullmatch(r"0x[0-9a-fA-F]{64}", h) is None
                or not isinstance(total, str) or not total.isdigit()
                or not isinstance(rows, list) or len(rows) != end - cursor):
            raise ValueError("Rolling page provenance, boundaries or counts invalid")
        for row, source in zip(rows, expected[cursor:end]):
            if (row.get("index") != source["index"]
                    or str(row.get("pool_address", "")).lower() != source["pool_address"].lower()
                    or not isinstance(row.get("weight_raw"), str)
                    or not row["weight_raw"].isdigit()):
                raise ValueError("Rolling page contains wrong pool identity or weight")
        cursor = end
    if cursor != offset:
        raise ValueError("Rolling checkpoint has missing or duplicate ranges")
    return doc


def import_pinned(inventory, source_sha, source=PINNED_CHECKPOINT):
    original = json.loads(Path(source).read_text(encoding="utf-8"))
    count = original.get("next_offset")
    old_rows = original.get("pools")
    if (original.get("chain_id") != CHAIN_ID
            or str(original.get("voter", "")).lower() != VOTER.lower()
            or original.get("source_inventory_sha256") != source_sha
            or original.get("expected_pools") != len(inventory["pools"])
            or type(count) is not int or not 1 <= count <= len(inventory["pools"])
            or not isinstance(old_rows, list) or len(old_rows) != count):
        raise ValueError("Pinned P4 source identity/coverage mismatch; nothing imported")
    page = {
        "start_offset": 0, "end_offset": count,
        "block_number": original["snapshot_block_number"],
        "block_hash": original["snapshot_block_hash"],
        "block_timestamp_utc": original["snapshot_block_timestamp_utc"],
        "total_voting_weight_raw": original["total_voting_weight_raw"],
        "source": "preserved_pinned_checkpoint",
        "collected_at_utc": original.get("last_page_completed_at_utc"),
        "pools": [
            {"index": item["index"], "pool_address": item["pool_address"].lower(),
             "weight_raw": item["weight_raw"]}
            for item in old_rows
        ],
    }
    result = {
        "schema_version": SCHEMA, "chain_id": CHAIN_ID, "voter": VOTER,
        "source_inventory_sha256": source_sha,
        "source_inventory_block_number": inventory["snapshot_block_number"],
        "expected_pools": len(inventory["pools"]),
        "next_offset": count,
        "pages": [page], "complete": count == len(inventory["pools"]),
        "started_at_utc": utc_now(),
        "last_page_completed_at_utc": original.get("last_page_completed_at_utc"),
        "notice": (
            "ROLLING, NOT SYNCHRONIZED: each page is pinned internally but "
            "different pages can be different blocks, including prior imported 180. "
            "Do not sum vote shares across pages or estimate individual veAERO payouts."
        ),
    }
    return validate_checkpoint(result, inventory, source_sha)


def new_block():
    block = int(rpc_checked(lambda: rpc("eth_blockNumber", []),
                            "Get current Base block", retries=1), 16)
    tag = hex(block)
    response = rpc_checked(
        lambda: rpc_object("eth_getBlockByNumber", [tag, False]),
        "Read page block details", retries=1,
    )
    if not isinstance(response, dict) or int(response["number"], 16) != block:
        raise RuntimeError("Block header does not match pinned page block")
    block_hash = response.get("hash")
    if not isinstance(block_hash, str) or re.fullmatch(r"0x[0-9a-fA-F]{64}", block_hash) is None:
        raise RuntimeError("Invalid page block hash")
    total = rpc_checked(
        lambda: read_uint("totalWeight()", None, tag),
        "Read page total voting weight", retries=1,
    )
    if total < 0:
        raise RuntimeError("Negative total voting weight")
    return block, block_hash.lower(), datetime.fromtimestamp(
        int(response["timestamp"], 16), timezone.utc
    ).isoformat(), total


def collect_page(checkpoint, inventory, page_size, delay):
    start = checkpoint["next_offset"]
    end = min(start + page_size, checkpoint["expected_pools"])
    block, block_hash, block_time, total = new_block()
    tag = hex(block)
    rows = []
    for offset in range(start, end):
        pool = inventory["pools"][offset]
        weight = rpc_checked(
            lambda addr=pool["pool_address"]: read_uint(
                "weights(address)", addr, tag
            ),
            f"Pool #{pool['index']} at page block {block}",
            retries=1,
        )
        if weight < 0:
            raise RuntimeError("Negative vote weight")
        rows.append({
            "index": pool["index"], "pool_address": pool["pool_address"].lower(),
            "weight_raw": str(weight),
        })
        if delay and offset + 1 < end:
            time.sleep(delay)
    page = {
        "start_offset": start, "end_offset": end, "block_number": block,
        "block_hash": block_hash, "block_timestamp_utc": block_time,
        "total_voting_weight_raw": str(total),
        "source": "public_or_configured_base_rpc", "collected_at_utc": utc_now(),
        "pools": rows,
    }
    result = dict(checkpoint)
    result["pages"] = checkpoint["pages"] + [page]
    result["next_offset"] = end
    result["last_page_completed_at_utc"] = utc_now()
    result["complete"] = end == checkpoint["expected_pools"]
    return result, page


def collect_with_repin(checkpoint, inventory, page_size, delay, max_repins):
    for attempt in range(max_repins + 1):
        try:
            return collect_page(checkpoint, inventory, page_size, delay)
        except (RuntimeError, OSError) as exc:
            message = str(exc)
            if ("HTTP 429" in message or "rate limit" in message.lower()
                    or "too many requests" in message.lower()):
                raise RuntimeError(
                    "RPC rate-limited (429); checkpoint protected. "
                    "Wait or configure a functioning RPC, then resume."
                ) from None
            if not ("HTTP 403" in message or "historic" in message.lower()
                    or "archive" in message.lower()):
                raise
            if attempt == max_repins:
                raise RuntimeError(
                    "RPC denied historical block too many times (403); "
                    "completed pages saved. Try a different provider."
                ) from None
            print(
                f"Page {checkpoint['next_offset']}: old pinned block denied (403); "
                f"discarded partial page, re-pinning latest block "
                f"({attempt+1}/{max_repins})", flush=True,
            )
            time.sleep(2)
    raise AssertionError("Unreachable")


def publish(checkpoint, path):
    if not checkpoint["complete"]:
        raise ValueError("Cannot publish partial rolling cohort")
    target = path.with_name("snapshot.json")
    if target.exists():
        return target
    completed = {**checkpoint, "published_at_utc": utc_now()}
    save_atomic(target, completed)
    print(f"COMPLETE ROLLING (not synchronized) vote observations: {target}", flush=True)
    return target


def run(page_size=25, max_pages=1, delay=0.1, until_complete=False, max_repins=3):
    if (type(page_size) is not int or not 1 <= page_size <= 100
            or type(max_pages) is not int or not 1 <= max_pages <= 1000
            or not 0 <= delay <= 5 or not 0 <= max_repins <= 10):
        raise ValueError("Invalid command options")
    inventory, source_sha = load_inventory()
    ROOT.mkdir(parents=True, exist_ok=True)
    with (ROOT / ".rolling_votes.lock").open("a+") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Another P4 rolling collection is running") from None
        path = ROOT / "checkpoint.json"
        if path.exists():
            progress = validate_checkpoint(
                json.loads(path.read_text(encoding="utf-8")), inventory, source_sha
            )
        else:
            progress = import_pinned(inventory, source_sha)
            save_atomic(path, progress)
            print(
                f"IMPORTED {progress['next_offset']} prior pinned rows intact; "
                "original P4 checkpoint unchanged", flush=True,
            )
        if progress["complete"]:
            publish(progress, path)
            print("Already complete; no new RPC queries")
            return progress
        chain = int(rpc_checked(lambda: rpc("eth_chainId", []),
                                "Check Base Mainnet", retries=1), 16)
        if chain != CHAIN_ID:
            raise RuntimeError("Wrong network: Base Mainnet required")
        remaining = progress["expected_pools"] - progress["next_offset"]
        count = ((remaining + page_size - 1) // page_size if until_complete else max_pages)
        print(
            f"P4 ROLLING | {progress['next_offset']}/{progress['expected_pools']} "
            f"saved | up to {count} more pages | blocks are NOT synchronized",
            flush=True,
        )
        for _ in range(count):
            if progress["complete"]:
                break
            updated, page = collect_with_repin(
                progress, inventory, page_size, delay, max_repins
            )
            validate_checkpoint(updated, inventory, source_sha)
            save_atomic(path, updated)
            progress = updated
            print(
                f"SAVED {page['start_offset']}-{page['end_offset']} "
                f"/ {progress['expected_pools']} | block {page['block_number']} "
                f"| rolling, NOT single-block", flush=True,
            )
        if progress["complete"]:
            publish(progress, path)
        else:
            print(
                f"PARTIAL ROLLING: {progress['next_offset']}/"
                f"{progress['expected_pools']} | resume the same command",
                flush=True,
            )
        return progress


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--page-size", type=int, default=25)
    parser.add_argument("--max-pages", type=int, default=1)
    parser.add_argument("--delay-seconds", type=float, default=0.1)
    parser.add_argument("--until-complete", action="store_true")
    parser.add_argument("--max-repins", type=int, default=3)
    args = parser.parse_args()
    run(args.page_size, args.max_pages, args.delay_seconds,
        args.until_complete, args.max_repins)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, OSError, KeyError, TypeError,
            json.JSONDecodeError) as exc:
        print(f"P4 ROLLING STOPPED: {exc}", file=sys.stderr, flush=True)
        sys.exit(1)
