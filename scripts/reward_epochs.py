#!/usr/bin/env python3
"""Read two epochs of on-chain Aerodrome FEES/BRIBES allocations on Base.

Uses the reward token registrations saved by scripts/reward_tokens.py.
No wallet, private key or gas required. This is NOT a voting APR estimate.
"""
import json
import subprocess
import sys
from datetime import datetime, timezone
from decimal import Decimal, getcontext
from pathlib import Path

from eth_utils import keccak

from reward_tokens import CHAIN_ID, RPC, read_call, rpc

getcontext().prec = 80
INPUT = Path("data/reward_tokens_base.json")
OUTPUT = Path("data/reward_epochs_base.json")
VOTER = "0x16613524e02ad97eDfeF371bC883F2F5d6C480A5"
SELECTOR_DURATION = "0x" + keccak(text="DURATION()")[:4].hex()
SELECTOR_EPOCH_START = "0x" + keccak(text="epochStart(uint256)")[:4].hex()
SELECTOR_TOKEN_REWARDS = "0x" + keccak(text="tokenRewardsPerEpoch(address,uint256)")[:4].hex()
SELECTOR_DECIMALS = "0x313ce567"


def rpc_object(method, params):
    """Unlike rpc(), returns arbitrary JSON RPC values (e.g. a block object)."""
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    result = subprocess.run(
        ["curl", "-fsS", "--retry", "2", "--connect-timeout", "10",
         "--max-time", "25", "-H", "Content-Type: application/json",
         "--data", body, RPC],
        capture_output=True, text=True, check=True, timeout=85,
    )
    reply = json.loads(result.stdout)
    if "error" in reply:
        raise RuntimeError(f"RPC {method}: {reply['error']}")
    if "result" not in reply:
        raise RuntimeError(f"Unexpected RPC response: {reply}")
    return reply["result"]


def iso(timestamp):
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def token_amount(raw, decimals):
    if decimals is None:
        return None
    return format((Decimal(raw) / (Decimal(10) ** decimals)).normalize(), "f")


def main():
    if not INPUT.exists():
        raise RuntimeError("Missing data/reward_tokens_base.json; run python scripts/reward_tokens.py")
    source = json.loads(INPUT.read_text(encoding="utf-8"))
    if int(source["chain_id"]) != CHAIN_ID or int(rpc("eth_chainId", []), 16) != CHAIN_ID:
        raise RuntimeError("Incorrect chain ID")
    block = int(rpc("eth_blockNumber", []), 16)
    tag = hex(block)
    block_data = rpc_object("eth_getBlockByNumber", [tag, False])
    if not isinstance(block_data, dict):
        raise RuntimeError("RPC returned no block details")
    timestamp = int(block_data["timestamp"], 16)
    epoch = int(read_call(VOTER, SELECTOR_EPOCH_START + f"{timestamp:064x}", tag), 16)
    now = iso(epoch)
    print(f"Base block: {block} | chain timestamp: {iso(timestamp)}", flush=True)
    print(f"Current epoch starts: {now}", flush=True)

    cache = {}
    result = {
        "chain_id": CHAIN_ID,
        "rpc": RPC,
        "block_number": block,
        "block_timestamp_utc": iso(timestamp),
        "epoch_start_utc": now,
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_file": str(INPUT),
        "warning": (
            "tokenRewardsPerEpoch is a contract allocation per epoch, not "
            "proof of current claimability, realized earnings or voting APR. "
            "Current epoch values can change until the epoch ends."
        ),
        "contracts": {},
    }
    for label, info in source["contracts"].items():
        contract = info["address"]
        duration = int(read_call(contract, SELECTOR_DURATION, tag), 16)
        if not 0 < duration <= 60 * 60 * 24 * 30:
            raise RuntimeError(f"Unexpected {label} duration: {duration}")
        prev = epoch - duration
        print(f"{label} | epoch length: {duration} s | prev start: {iso(prev)}", flush=True)
        entries = []
        for token in info["tokens"]:
            addr = token["address"]
            symbol = token.get("symbol") or "UNKNOWN"
            if addr not in cache:
                try:
                    decimals = int(read_call(addr, SELECTOR_DECIMALS, tag), 16)
                    cache[addr] = decimals if 0 <= decimals <= 36 else None
                except (RuntimeError, subprocess.SubprocessError, ValueError):
                    cache[addr] = None
            decimals = cache[addr]
            amounts = {}
            for period, start in (("current", epoch), ("previous", prev)):
                calldata = (
                    SELECTOR_TOKEN_REWARDS
                    + addr[2:].lower().zfill(64)
                    + f"{start:064x}"
                )
                amount = int(read_call(contract, calldata, tag), 16)
                amounts[period] = {"epoch_start_utc": iso(start),
                                   "raw": str(amount),
                                   "token_amount": token_amount(amount, decimals)}
            print(f"  {symbol}: current={amounts['current']['token_amount']} | "
                  f"previous={amounts['previous']['token_amount']}", flush=True)
            entries.append({"symbol": symbol, "address": addr,
                            "decimals": decimals, "amounts": amounts})
        result["contracts"][label] = {"address": contract, "duration_seconds": duration,
                                       "tokens": entries}
    OUTPUT.parent.mkdir(exist_ok=True, parents=True)
    OUTPUT.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n",
                      encoding="utf-8")
    print(f"Saved: {OUTPUT}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError,
            subprocess.SubprocessError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
