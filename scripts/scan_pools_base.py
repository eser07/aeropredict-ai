#!/usr/bin/env python3
"""Scan Aerodrome Base Voter pools with pinned block state (read-only).

Outputs actual Voter pool addresses, gauge addresses, active flags, and
voting weights. Index order is contract registration order, NOT profitability.
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from decimal import Decimal, getcontext
from pathlib import Path

from eth_utils import keccak
from reward_tokens import CHAIN_ID, RPC, read_call, rpc

getcontext().prec = 70
VOTER = "0x16613524e02ad97eDfeF371bC883F2F5d6C480A5"


def selector(signature):
    return "0x" + keccak(text=signature)[:4].hex()


def read_uint(signature, argument, block):
    data = selector(signature)
    if argument is not None:
        encoded = (
            f"{argument:064x}" if isinstance(argument, int)
            else argument[2:].lower().zfill(64)
        )
        data += encoded
    return int(read_call(VOTER, data, block), 16)


def read_address(signature, argument, block):
    value = read_uint(signature, argument, block)
    if value >> 160:
        raise RuntimeError(f"Unexpected address result for {signature}")
    return "0x" + f"{value:040x}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=0, help="First registration index")
    parser.add_argument("--count", type=int, default=5, help="Number of pools (1-100)")
    parser.add_argument(
        "--output", type=Path, default=Path("data/pool_scan_base.json"),
        help="Save scan to a separate JSON file under data/ (default: current sample)",
    )
    args = parser.parse_args()
    if args.start < 0 or not (1 <= args.count <= 100):
        parser.error("--start must be >= 0 and --count must be between 1 and 100")
    data_folder = Path("data").resolve()
    output_path = args.output.resolve()
    if not output_path.is_relative_to(data_folder) or output_path.suffix != ".json":
        parser.error("--output must be a .json file inside the data/ directory")

    if int(rpc("eth_chainId", []), 16) != CHAIN_ID:
        raise RuntimeError("Unexpected chain ID")
    block = int(rpc("eth_blockNumber", []), 16)
    tag = hex(block)
    length = read_uint("length()", None, tag)
    total_weight = read_uint("totalWeight()", None, tag)
    if args.start >= length:
        raise RuntimeError(f"Start index must be below {length}")
    end = min(args.start + args.count, length)
    report = {
        "source": "Aerodrome Voter contract via Base JSON-RPC",
        "rpc": RPC,
        "voter": VOTER,
        "chain_id": CHAIN_ID,
        "block_number": block,
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
        "total_registered": length,
        "scan_start": args.start,
        "scan_end_exclusive": end,
        "total_voting_weight_raw": str(total_weight),
        "notice": "Registration-order sample. Active gauges or vote weights are not yield estimates.",
        "pools": [],
    }
    print(f"Base block {block}; registered pools {length}; scanning [{args.start}, {end})", flush=True)
    for i in range(args.start, end):
        pool = read_address("pools(uint256)", i, tag)
        gauge = read_address("gauges(address)", pool, tag)
        active = (
            bool(read_uint("isAlive(address)", gauge, tag))
            if int(gauge, 16) != 0 else False
        )
        weight = read_uint("weights(address)", pool, tag)
        share = (
            format(Decimal(weight) * 100 / Decimal(total_weight), ".8f")
            if total_weight else None
        )
        item = {
            "index": i, "pool_address": pool, "gauge_address": gauge,
            "gauge_active": active, "weight_raw": str(weight),
            "vote_share_percent": share,
        }
        report["pools"].append(item)
        print(f"[{i}] active={active} vote_share={share or 'N/A'}% "
              f"pool={pool} gauge={gauge}", flush=True)

    active_pools = [p for p in report["pools"] if p["gauge_active"]]
    report["active_pool_count"] = len(active_pools)
    print(
        f"Scanned {len(report['pools'])} pools | currently active {len(active_pools)}",
        flush=True,
    )
    if active_pools:
        print("Largest CURRENT vote weights IN THIS SCANNED BATCH (not yield rankings):")
        for row in sorted(
            active_pools, key=lambda p: int(p["weight_raw"]), reverse=True
        )[:8]:
            print(
                f"  Pool #{row['index']} | vote share {row['vote_share_percent']}%",
                flush=True,
            )
    file = args.output
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Saved: {file}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError, json.JSONDecodeError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
