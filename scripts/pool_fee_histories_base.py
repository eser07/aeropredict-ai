#!/usr/bin/env python3
"""Gather multi-pool Aerodrome Base FEES histories from current chain state.

All per-epoch allocations are fetched using eth_call at "latest" because the
public RPC requires archive credentials for old block state. An older *epoch
key* is not a historical block snapshot. Values can be revised, and this is
not a point-in-time training dataset without independent archived snapshots.

Pools come from the registration-order sample in data/pool_scan_base.json.
Only currently alive gauges are sampled. Different reward token units must
NEVER be summed or compared as if they were USD. No wallet needed.
"""
import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from reward_tokens import CHAIN_ID, RPC, read_call, rpc, symbol_from_hex
from reward_epochs import (
    SELECTOR_DECIMALS, SELECTOR_DURATION, SELECTOR_EPOCH_START,
    SELECTOR_TOKEN_REWARDS, rpc_object,
)
from scan_pools_base import VOTER, read_address, read_uint, selector

INPUT = Path("data/pool_scan_base.json")
OUTPUT = Path("data/pool_fee_histories_base.json")
EPOCH_SECONDS = 604800
ZERO = "0x" + "0" * 40


def human_amount(raw, decimals):
    if decimals is None:
        return None
    return format(Decimal(raw) / (Decimal(10) ** decimals), "f")


def utc(timestamp):
    return datetime.fromtimestamp(timestamp, timezone.utc).strftime("%Y-%m-%d")


def metadata(token, cache):
    if token in cache:
        return cache[token]
    try:
        symbol = symbol_from_hex(read_call(token, selector("symbol()"), "latest"))
    except (ValueError, RuntimeError, subprocess.SubprocessError, UnicodeError):
        symbol = None
    try:
        decimals = int(read_call(token, SELECTOR_DECIMALS, "latest"), 16)
        if not 0 <= decimals <= 36:
            decimals = None
    except (ValueError, RuntimeError, subprocess.SubprocessError):
        decimals = None
    cache[token] = {"symbol": symbol or "UNKNOWN", "decimals": decimals}
    return cache[token]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--weeks", type=int, default=12, help="Completed weeks, 4-16")
    parser.add_argument(
        "--max-pools", type=int, default=5,
        help="How many scan-listed pools to inspect, 1-50",
    )
    parser.add_argument(
        "--max-tokens", type=int, default=4,
        help="First N registered FEES tokens per active pool, 1-20",
    )
    parser.add_argument(
        "--scan-file", type=Path, default=INPUT,
        help="Read saved pool scan; default keeps original demo sample",
    )
    parser.add_argument(
        "--output-file", type=Path, default=OUTPUT,
        help="Write fee history to specified JSON in data/",
    )
    args = parser.parse_args()
    data_dir = Path("data").resolve()
    scan_file = args.scan_file.resolve()
    output_file = args.output_file.resolve()
    if any(
        not p.is_relative_to(data_dir) or p.suffix.lower() != ".json"
        for p in (scan_file, output_file)
    ):
        parser.error("Scan and output files must be .json paths under data/")
    if output_file == scan_file:
        parser.error("Output must not overwrite its scan input")
    if not 4 <= args.weeks <= 16:
        parser.error("--weeks must be 4-16")
    if not 1 <= args.max_pools <= 50:
        parser.error("--max-pools must be 1-50")
    if not 1 <= args.max_tokens <= 20:
        parser.error("--max-tokens must be 1-20")

    if not scan_file.is_file():
        raise RuntimeError(
            f"Missing scan: {args.scan_file}. Run a pool scan first."
        )
    scan = json.loads(scan_file.read_text(encoding="utf-8"))
    if int(scan.get("chain_id", 0)) != CHAIN_ID:
        raise RuntimeError("Saved scan was not made on Base Mainnet")
    if int(rpc("eth_chainId", []), 16) != CHAIN_ID:
        raise RuntimeError("RPC is not Base Mainnet")

    tip = rpc_object("eth_getBlockByNumber", ["latest", False])
    if not isinstance(tip, dict):
        raise RuntimeError("Could not retrieve latest Base block")
    block_time = int(tip["timestamp"], 16)
    tip_number = int(tip["number"], 16)
    epoch = int(
        read_call(
            VOTER, SELECTOR_EPOCH_START + f"{block_time:064x}", "latest"
        ), 16
    )
    if not epoch <= block_time < epoch + EPOCH_SECONDS:
        raise RuntimeError("Unexpected Voter epoch boundary")
    print(
        f"Base tip {tip_number} | current epoch {utc(epoch)} UTC | "
        f"{args.weeks} completed epochs",
        flush=True,
    )
    print(
        "Using historical epoch keys at 'latest' state, not archive snapshots.",
        flush=True,
    )
    pools = scan.get("pools", [])[:args.max_pools]
    if not pools:
        raise RuntimeError("The saved pool scan is empty")

    out = {
        "chain_id": CHAIN_ID,
        "rpc": RPC,
        "base_tip_block_approx": tip_number,
        "sample_source": str(args.scan_file),
        "current_epoch_start_utc": datetime.fromtimestamp(
            epoch, timezone.utc
        ).isoformat(),
        "collected_at_utc": datetime.now(timezone.utc).isoformat(),
        "completed_weeks_requested": args.weeks,
        "scope": "Pools listed in selected scan input; currently active FEES only",
        "block_tag": "latest",
        "caveat": (
            "Historical epoch keys are read at current state; they are not "
            "historical block snapshots. No voter APY, future guarantee, "
            "claimable veAERO income or USD conversion is established."
        ),
        "pools": [],
    }
    meta_cache = {}
    series_count = 0

    for entry in pools:
        pool = entry["pool_address"]
        idx = entry["index"]
        gauge = read_address("gauges(address)", pool, "latest")
        active = gauge != ZERO and bool(read_uint("isAlive(address)", gauge, "latest"))
        record = {
            "index": idx,
            "pool_address": pool,
            "gauge_address": gauge,
            "active_at_collection": active,
            "pool_vote_weight_raw": None,
            "pool_vote_weight_snapshot_block_approx": tip_number,
            "fees_contract": None,
            "registered_fee_tokens": 0,
            "tokens_truncated": False,
            "reward_series": [],
        }
        out["pools"].append(record)
        print(f"Pool #{idx} | currently active: {active}", flush=True)
        if not active:
            continue

        # Current Voter weight is measured in 18-decimal voting-power units.
        # It is not a historical snapshot synchronized with prior fee epochs.
        current_votes_raw = read_uint("weights(address)", pool, "latest")
        record["pool_vote_weight_raw"] = str(current_votes_raw)
        print(
            f"  Snapshot vote weight: {human_amount(current_votes_raw, 18)} veAERO",
            flush=True,
        )

        fees = read_address("gaugeToFees(address)", gauge, "latest")
        if fees == ZERO:
            print("  No FEES contract", flush=True)
            continue
        record["fees_contract"] = fees
        duration = int(read_call(fees, SELECTOR_DURATION, "latest"), 16)
        if duration != EPOCH_SECONDS:
            print(
                f"  Unexpected FEES epoch duration {duration}, "
                "skipping to avoid wrong weekly alignment",
                flush=True,
            )
            record["skip_reason"] = f"Unexpected duration {duration}"
            continue

        count = int(
            read_call(fees, selector("rewardsListLength()"), "latest"), 16
        )
        if not 0 <= count <= 100:
            raise RuntimeError(f"Unexpected reward token count {count} for pool {idx}")
        record["registered_fee_tokens"] = count
        record["tokens_truncated"] = count > args.max_tokens
        limit = min(count, args.max_tokens)
        print(
            f"  FEES {fees}, inspecting {limit}/{count} reward tokens",
            flush=True,
        )

        for j in range(limit):
            word = read_call(
                fees, selector("rewards(uint256)") + f"{j:064x}", "latest"
            )
            if len(word) != 66:
                raise RuntimeError(f"Invalid token address at pool #{idx}, index {j}")
            token = "0x" + word[-40:].lower()
            if token == ZERO:
                raise RuntimeError(f"Zero reward token at pool #{idx}, index {j}")
            info = metadata(token, meta_cache)
            amounts = []
            for n in range(args.weeks, 0, -1):
                week = epoch - n * EPOCH_SECONDS
                data = (
                    SELECTOR_TOKEN_REWARDS
                    + token[2:].lower().zfill(64)
                    + f"{week:064x}"
                )
                raw = int(read_call(fees, data, "latest"), 16)
                amounts.append({
                    "epoch_start_utc": datetime.fromtimestamp(
                        week, timezone.utc
                    ).isoformat(),
                    "raw": str(raw),
                    "token_amount": human_amount(raw, info["decimals"]),
                })
            positive = sum(int(row["raw"]) > 0 for row in amounts)
            record["reward_series"].append({
                "token_address": token,
                "symbol": info["symbol"],
                "decimals": info["decimals"],
                "positive_weeks": positive,
                "zero_weeks": args.weeks - positive,
                "completed_weeks": amounts,
            })
            series_count += 1
            last = amounts[-1]
            print(
                f"    {info['symbol']} ({token}): {positive}/{args.weeks} "
                f"nonzero weeks | last {last['token_amount'] or last['raw']}",
                flush=True,
            )

    out["series_count"] = series_count
    output_file.parent.mkdir(exist_ok=True, parents=True)
    output_file.write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Saved: {args.output_file} | {series_count} token/pool reward series")
    print(
        "NOTE: Token amounts across different assets must not be added "
        "or compared as common currency."
    )


if __name__ == "__main__":
    try:
        main()
    except (
        OSError, ValueError, RuntimeError, KeyError, TypeError,
        subprocess.SubprocessError, json.JSONDecodeError,
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
