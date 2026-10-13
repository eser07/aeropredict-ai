#!/usr/bin/env python3
"""Compare current/prior epoch allocations for the pools in pool_scan_base.json.

Read-only, pinned to a single Base block. Rewards are amounts of different
tokens, NOT USD values, claimable balances, realized yield, or vAPR.
"""
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from reward_tokens import CHAIN_ID, RPC, read_call, rpc, symbol_from_hex
from reward_epochs import (
    SELECTOR_DECIMALS, SELECTOR_DURATION, SELECTOR_EPOCH_START,
    SELECTOR_TOKEN_REWARDS, iso, rpc_object, token_amount,
)
from scan_pools_base import VOTER, read_address, read_uint, selector

INPUT = Path("data/pool_scan_base.json")
OUTPUT = Path("data/pool_rewards_comparison_base.json")
MAX_REWARD_TOKENS = 40


def reward_records(contract, block_tag, epoch, metadata_cache):
    if int(contract, 16) == 0:
        return {"address": None, "tokens": [], "reason": "No reward contract"}
    length = int(read_call(contract, selector("rewardsListLength()"), block_tag), 16)
    if length > MAX_REWARD_TOKENS:
        raise RuntimeError(f"Unexpected reward count {length} at {contract}")
    duration = int(read_call(contract, SELECTOR_DURATION, block_tag), 16)
    if duration <= 0 or duration > 30 * 86400:
        raise RuntimeError(f"Invalid reward duration {duration} at {contract}")
    # Contract epoch lengths can differ; preserve the on-chain duration.
    previous = epoch - duration
    tokens = []
    for i in range(length):
        word = read_call(contract, selector("rewards(uint256)") + f"{i:064x}", block_tag)
        if len(word) != 66:
            raise RuntimeError(f"Unexpected rewards({i}) response at {contract}")
        address = "0x" + word[-40:].lower()
        if int(address, 16) == 0:
            raise RuntimeError(f"Zero token address at {contract}[{i}]")
        if address not in metadata_cache:
            try:
                sym = symbol_from_hex(read_call(address, selector("symbol()"), block_tag))
            except (ValueError, RuntimeError, subprocess.SubprocessError):
                sym = None
            try:
                dec = int(read_call(address, SELECTOR_DECIMALS, block_tag), 16)
                if dec < 0 or dec > 36:
                    dec = None
            except (ValueError, RuntimeError, subprocess.SubprocessError):
                dec = None
            metadata_cache[address] = {"symbol": sym or "UNKNOWN", "decimals": dec}
        info = metadata_cache[address]
        periods = {}
        for name, start in [("current", epoch), ("previous", previous)]:
            data = SELECTOR_TOKEN_REWARDS + address[2:].zfill(64) + f"{start:064x}"
            raw = int(read_call(contract, data, block_tag), 16)
            periods[name] = {
                "epoch_start_utc": iso(start),
                "raw": str(raw),
                "token_amount": token_amount(raw, info["decimals"]),
            }
        tokens.append({"address": address, **info, "periods": periods})
    return {"address": contract, "duration_seconds": duration, "tokens": tokens}


def main():
    if not INPUT.exists():
        raise RuntimeError("Missing scan file. Run python scripts/scan_pools_base.py --count 5")
    scan = json.loads(INPUT.read_text(encoding="utf-8"))
    if scan.get("chain_id") != CHAIN_ID:
        raise RuntimeError("Scan data is not from Base")
    if int(rpc("eth_chainId", []), 16) != CHAIN_ID:
        raise RuntimeError("RPC returned wrong chain ID")

    block = int(rpc("eth_blockNumber", []), 16)
    tag = hex(block)
    details = rpc_object("eth_getBlockByNumber", [tag, False])
    timestamp = int(details["timestamp"], 16)
    epoch = int(read_call(VOTER, SELECTOR_EPOCH_START + f"{timestamp:064x}", tag), 16)
    total_weight = read_uint("totalWeight()", None, tag)
    records = []
    meta_cache = {}
    print(f"Base block {block} | Current epoch {iso(epoch)}", flush=True)
    for entry in scan["pools"]:
        pool = entry["pool_address"]
        gauge = read_address("gauges(address)", pool, tag)
        active = (
            bool(read_uint("isAlive(address)", gauge, tag))
            if int(gauge, 16) else False
        )
        weight = read_uint("weights(address)", pool, tag)
        print(f"Pool #{entry['index']}: active={active}", flush=True)
        result = {
            "index": entry["index"], "pool_address": pool,
            "gauge_address": gauge, "gauge_active": active,
            "weight_raw": str(weight), "total_weight_raw": str(total_weight),
            "rewards": {},
        }
        if active:
            for label, signature in (
                ("FEES", "gaugeToFees(address)"),
                ("BRIBES", "gaugeToBribe(address)"),
            ):
                contract = read_address(signature, gauge, tag)
                print(f"  {label} contract: {contract}", flush=True)
                reward = reward_records(contract, tag, epoch, meta_cache)
                result["rewards"][label] = reward
                for token in reward["tokens"]:
                    cur = token["periods"]["current"]["token_amount"]
                    prev = token["periods"]["previous"]["token_amount"]
                    if int(token["periods"]["current"]["raw"]) or int(token["periods"]["previous"]["raw"]):
                        print(f"    {token['symbol']}: current={cur}, previous={prev}", flush=True)
        else:
            result["skip_reason"] = "Inactive gauge; excluded from reward comparisons"
        records.append(result)
    output = {
        "chain_id": CHAIN_ID, "rpc": RPC,
        "block_number": block, "block_timestamp_utc": iso(timestamp),
        "epoch_start_utc": iso(epoch),
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_scan": str(INPUT),
        "warning": (
            "On-chain epoch allocations are not guaranteed payments or yield. "
            "Current epoch can still change. Different reward tokens are not "
            "directly comparable without reliable token prices. "
            "This is a registration-order sample, not a pool ranking."
        ),
        "pools": records,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    print(f"Saved: {OUTPUT}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError,
            subprocess.SubprocessError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
