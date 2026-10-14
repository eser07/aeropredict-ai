#!/usr/bin/env python3
"""Read 8 finalized weekly Aerodrome USDbC FEES allocations from Base 'latest'.

Historical *epoch keys* are queried against current contract state; this
does NOT require an archive node. It is not an immutable historic block proof.

Scope: one verified Base FEES contract, one reward token (USDbC).
Amounts are pool-level token allocations, NOT veAERO income or voting APR.
"""
import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from statistics import median

from reward_tokens import CHAIN_ID, RPC, read_call, rpc
from reward_epochs import SELECTOR_DURATION, SELECTOR_EPOCH_START, SELECTOR_TOKEN_REWARDS
from scan_pools_base import VOTER

FEES = "0x958a5612390bb4134e1e7505c7cb6b0652941174"
USDBC = "0xd9aaec86b65d86f6a7b5b1b0c42ffa531710b6ca"
DECIMALS = 6
OUTPUT = Path("data/usdbc_fee_history_base.json")


def utc_date(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")


def read_reward(epoch):
    data = (
        SELECTOR_TOKEN_REWARDS
        + USDBC[2:].lower().zfill(64)
        + f"{epoch:064x}"
    )
    return int(read_call(FEES, data, "latest"), 16)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--weeks", type=int, default=8,
                        help="Number of completed epochs to examine (4-12)")
    opts = parser.parse_args()
    if not 4 <= opts.weeks <= 12:
        parser.error("--weeks must be between 4 and 12")

    if int(rpc("eth_chainId", []), 16) != CHAIN_ID:
        raise RuntimeError("RPC not connected to Base Mainnet")

    # Resolve chain time, not PC time, and use latest state for all calls:
    # PublicNode rejects historical state access without an archive token.
    tip = int(rpc("eth_blockNumber", []), 16)
    block = _rpc_block_latest()
    block_timestamp = int(block["timestamp"], 16)
    epoch_selector = SELECTOR_EPOCH_START + f"{block_timestamp:064x}"
    current_epoch = int(read_call(VOTER, epoch_selector, "latest"), 16)
    duration = int(read_call(FEES, SELECTOR_DURATION, "latest"), 16)
    if not 60 * 60 * 24 <= duration <= 30 * 60 * 60 * 24:
        raise RuntimeError(f"Unexpected reward epoch duration: {duration}")
    if not current_epoch <= block_timestamp < current_epoch + duration:
        raise RuntimeError("Voter epochStart disagrees with chain timestamp")

    print(f"Base tip ~{tip} | ongoing epoch starts: {utc_date(current_epoch)} UTC")
    print(f"Pool #0 FEES / USDbC ({DECIMALS} decimals) | {opts.weeks} completed weeks")
    print("This uses historical epoch mapping read at 'latest', not an archive block.")

    observations = []
    for i in range(1, opts.weeks + 1):
        start = current_epoch - i * duration
        raw = read_reward(start)
        amount = Decimal(raw) / (Decimal(10) ** DECIMALS)
        observations.append({
            "epoch_start_utc": datetime.fromtimestamp(start, timezone.utc).isoformat(),
            "raw": str(raw),
            "usdbc": str(amount),
        })
        print(f"  {utc_date(start)}: {amount:,.6f} USDbC")

    # Plain statistical reference only: median of most recent 4 completed
    # epochs. It is not an AI model or a validated investment forecast.
    recent = [Decimal(x["usdbc"]) for x in observations[:4]]
    baseline = median(recent)
    print(f"4-week historical median baseline: {baseline:,.6f} USDbC")
    print("Not a guaranteed next-week reward, realized voter income, or APR.")

    result = {
        "source": "Aerodrome Base FEES tokenRewardsPerEpoch via eth_call latest",
        "chain_id": CHAIN_ID,
        "rpc": RPC,
        "observed_tip_block_approx": tip,
        "current_epoch_start": datetime.fromtimestamp(
            current_epoch, timezone.utc
        ).isoformat(),
        "reward_contract": FEES,
        "token": USDBC,
        "token_symbol": "USDbC",
        "token_decimals": DECIMALS,
        "completed_weeks": observations,
        "four_week_median_baseline_usdbc": str(baseline),
        "caveats": [
            "Historical epoch allocations read from latest state are not an "
            "immutable block-by-block record",
            "Current incomplete epoch is intentionally excluded",
            "Per-pool token allocations are not veAERO earnings, USD APR, "
            "or an individually claimable amount",
            "Four-week median is a descriptive baseline, not a trained AI model",
        ],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Saved: {OUTPUT}")


def _rpc_block_latest():
    payload = json.dumps({
        "jsonrpc": "2.0", "id": 1,
        "method": "eth_getBlockByNumber",
        "params": ["latest", False],
    })
    proc = subprocess.run(
        ["curl", "-fsS", "--retry", "2",
         "--connect-timeout", "10", "--max-time", "25",
         "-H", "Content-Type: application/json",
         "--data", payload, RPC],
        text=True, capture_output=True, check=True, timeout=85,
    )
    answer = json.loads(proc.stdout)
    if "error" in answer or not isinstance(answer.get("result"), dict):
        raise RuntimeError(f"Invalid latest Base block: {answer}")
    return answer["result"]


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError,
            subprocess.SubprocessError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
