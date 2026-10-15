#!/usr/bin/env python3
"""P8.3 opt-in, read-only current Base Voter sample vs frozen P2 pool IDs.

Default is OFFLINE PREVIEW. --live queries at most five archived pool IDs
at ONE newly pinned Base block, and writes no files. This is not a full
registry scan or an assertion that all 928 historical pools remain active.
Existing discovery checkpoints, dashboards and hourly refresh are untouched.
"""
import argparse
import json
import sys
from datetime import datetime, timezone

from discover_active_pools_base import address_ok, rpc_checked
from p8_collection_preflight import EXPECTED_BLOCK
from reward_tokens import CHAIN_ID, rpc
from scan_pools_base import VOTER, read_address, read_uint
from serve_pool_research import DATA, validate_research

DEFAULT_INDEXES = "1930,1774,1414"
MAX_SAMPLE = 5


def parse_indexes(value):
    if not isinstance(value, str) or not value:
        raise ValueError("Pool indexes must be a comma-separated list")
    parts = value.split(",")
    if not 1 <= len(parts) <= MAX_SAMPLE:
        raise ValueError("Choose 1–5 archived indexes per sample")
    ids = []
    for text in parts:
        text = text.strip()
        if not text.isdecimal() or text != str(int(text)):
            raise ValueError("Pool index must be a canonical nonnegative integer")
        ids.append(int(text))
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate registry index in sample")
    return ids


def old_sample(pools, indexes):
    archive = {p["index"]: p for p in pools if type(p.get("index")) is int}
    if len(archive) != len(pools):
        raise ValueError("Archive pool indexes are duplicated or malformed")
    result = []
    for idx in indexes:
        pool = archive.get(idx)
        if pool is None:
            raise ValueError(f"Pool #{idx} not found in historical 928-pool archive")
        old_addr = pool.get("address")
        gauge = pool.get("gauge_address")
        if not address_ok(old_addr) or not address_ok(gauge):
            raise ValueError(f"Pool #{idx} has malformed saved addresses")
        result.append({
            "index": idx,
            "old_pool": old_addr.lower(),
            "old_gauge": gauge.lower(),
        })
    return result


def observe_at_one_block(sample, query, address_reader, uint_reader):
    """Return a small pinned-block comparison; never create an output file."""
    chain = int(query(lambda: rpc("eth_chainId", []), "Base chain ID"), 16)
    if chain != CHAIN_ID:
        raise RuntimeError("Wrong RPC chain ID; expected Base Mainnet 8453")
    block = int(query(lambda: rpc("eth_blockNumber", []), "New Base snapshot block"), 16)
    if block <= EXPECTED_BLOCK:
        raise RuntimeError("RPC block must be newer than the historical inventory")
    tag = hex(block)
    total_registered = query(
        lambda: uint_reader("length()", None, tag), "Pinned Voter registry length"
    )
    if type(total_registered) is not int or not 1 <= total_registered <= 1000000:
        raise RuntimeError("Invalid pinned Voter registry length")
    rows = []
    for source in sample:
        idx = source["index"]
        result = {**source, "new_block": block, "status": None,
                  "current_pool": None, "current_gauge": None,
                  "is_alive": None, "current_weight_raw": None}
        if idx >= total_registered:
            result["status"] = "INDEX_OUT_OF_RANGE"
            rows.append(result)
            continue
        current_pool = query(
            lambda: address_reader("pools(uint256)", idx, tag),
            f"P8.3 pool #{idx} registration",
        )
        if not address_ok(current_pool) or int(current_pool, 16) == 0:
            raise RuntimeError(f"Pool #{idx}: invalid pinned registry address")
        result["current_pool"] = current_pool.lower()
        if result["current_pool"] != source["old_pool"]:
            result["status"] = "POOL_ADDRESS_CHANGED"
            rows.append(result)
            continue
        gauge = query(
            lambda: address_reader("gauges(address)", current_pool, tag),
            f"P8.3 pool #{idx} gauge",
        )
        if not address_ok(gauge):
            raise RuntimeError(f"Pool #{idx}: invalid pinned gauge address")
        result["current_gauge"] = gauge.lower()
        if int(gauge, 16) == 0:
            result["is_alive"] = False
            result["status"] = "NO_CURRENT_GAUGE"
        else:
            alive = query(
                lambda: uint_reader("isAlive(address)", gauge, tag),
                f"P8.3 pool #{idx} isAlive",
            )
            if alive not in (0, 1):
                raise RuntimeError(f"Pool #{idx}: invalid pinned isAlive result")
            result["is_alive"] = bool(alive)
            if not alive:
                result["status"] = "CURRENT_GAUGE_INACTIVE"
            else:
                weight = query(
                    lambda: uint_reader("weights(address)", current_pool, tag),
                    f"P8.3 pool #{idx} weight",
                )
                if type(weight) is not int or weight < 0:
                    raise RuntimeError(f"Pool #{idx}: invalid current voting weight")
                result["current_weight_raw"] = str(weight)
                result["status"] = ("ACTIVE_SAME_GAUGE"
                                    if result["current_gauge"] == source["old_gauge"]
                                    else "ACTIVE_GAUGE_CHANGED")
        rows.append(result)
    return {"chain_id": chain, "voter": VOTER, "pinned_block": block,
            "total_registered": total_registered, "sample": rows}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--indexes", default=DEFAULT_INDEXES,
                        help="1–5 registry indexes saved in the old archive")
    parser.add_argument("--live", action="store_true",
                        help="Explicitly make bounded pinned-block Base RPC reads")
    args = parser.parse_args(argv)
    indexed = parse_indexes(args.indexes)
    data = validate_research(json.loads(DATA.read_text(encoding="utf-8")))
    archive = old_sample(data["pools"], indexed)
    print("P8.3 | Base Voter historical-vs-current SAME-INDEX identity pilot")
    print("Historical source: pinned block", EXPECTED_BLOCK,
          "|", len(data["pools"]), "archived pools | not verified active today")
    for row in archive:
        print(f"  Pool #{row['index']} | old pool {row['old_pool']} | "
              f"old gauge {row['old_gauge']}")
    if not args.live:
        print("OFFLINE PREVIEW: NO RPC calls, NO writes, NO current status claims.")
        print("To check the listed indexes ONLY, run again with --live (opt-in).")
        return
    result = observe_at_one_block(
        archive, lambda op, label: rpc_checked(op, label, retries=1, retry_delay=1),
        read_address, read_uint,
    )
    print("LIVE PINNED READ-ONLY SAMPLE | Base block", result["pinned_block"],
          "| registered pool indexes", result["total_registered"])
    for row in result["sample"]:
        msg = f"  Pool #{row['index']}: {row['status']}"
        if row["is_alive"] is not None:
            msg += f" | gauge alive={row['is_alive']}"
        if row["current_weight_raw"] is not None:
            msg += f" | raw current vote weight={row['current_weight_raw']}"
        print(msg)
    print("Fetched at (UTC, approx):", datetime.now(timezone.utc).isoformat())
    print("ONLY", len(result["sample"]), "indexes checked; 928-pool active count UNKNOWN.")
    print("No yield, voting APR, personal payout, token liquidity or current reward claim.")
    print("No files written; old P2 research and 8765/8766 unchanged.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError, TypeError,
            json.JSONDecodeError) as exc:
        print("P8.3 PROBE PAUSED:", exc, file=sys.stderr)
        sys.exit(1)
