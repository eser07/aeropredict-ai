#!/usr/bin/env python3
"""Read Base Aerodrome voting reward token registrations (read-only RPC).

Registration does not prove that a token currently pays rewards.
Requires only Python 3.10+ and an installed curl executable.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

RPC = os.getenv("BASE_RPC_URL", "https://base-rpc.publicnode.com")
CHAIN_ID = 8453
CONTRACTS = {
    "FEES": "0x958a5612390bb4134e1e7505c7cb6b0652941174",
    "BRIBES": "0xb0b88ca338f183d2fbabab0f75ba3c90424131d9",
}
SELECTOR_LENGTH = "0xe6886396"  # rewardsListLength()
SELECTOR_REWARD = "0xf301af42"  # rewards(uint256)
SELECTOR_SYMBOL = "0x95d89b41"  # symbol()


def rpc(method, params):
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    process = subprocess.run(
        ["curl", "-fsS", "--retry", "2", "--connect-timeout", "10",
         "--max-time", "25", "-H", "Content-Type: application/json",
         "--data", payload, RPC],
        capture_output=True, text=True, check=True, timeout=85,
    )
    reply = json.loads(process.stdout)
    if "error" in reply:
        raise RuntimeError(f"RPC {method}: {reply['error']}")
    value = reply.get("result")
    if not isinstance(value, str) or not value.startswith("0x"):
        raise RuntimeError(f"Unexpected RPC result for {method}: {reply}")
    return value


def read_call(address, call_data, block_tag):
    return rpc("eth_call", [{"to": address, "data": call_data}, block_tag])


def symbol_from_hex(value):
    """Decode ERC-20 symbol() returning a string or legacy bytes32."""
    raw = bytes.fromhex(value[2:])
    if len(raw) == 32:
        return raw.rstrip(b"\0").decode("utf-8", errors="replace") or None
    if len(raw) >= 64:
        offset = int.from_bytes(raw[:32], "big")
        if offset + 32 <= len(raw):
            length = int.from_bytes(raw[offset:offset + 32], "big")
            if length <= 256 and offset + 32 + length <= len(raw):
                return raw[offset + 32:offset + 32 + length].decode(
                    "utf-8", errors="replace"
                ) or None
    return None


def main():
    chain = int(rpc("eth_chainId", []), 16)
    if chain != CHAIN_ID:
        raise RuntimeError(f"Wrong chain: expected {CHAIN_ID}, got {chain}")
    block_number = int(rpc("eth_blockNumber", []), 16)
    tag = hex(block_number)
    snapshot = {
        "chain_id": chain,
        "block_number": block_number,
        "rpc": RPC,
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
        "note": "Token registrations only; no current rewards or voting APR verified.",
        "contracts": {},
    }
    unique = set()
    print(f"Base block: {block_number}", flush=True)
    for group, contract in CONTRACTS.items():
        count = int(read_call(contract, SELECTOR_LENGTH, tag), 16)
        if count > 100:
            raise RuntimeError(f"Unexpected {group} token count: {count}")
        print(f"{group}: {count} registered reward tokens", flush=True)
        records = []
        for index in range(count):
            data = SELECTOR_REWARD + f"{index:064x}"
            result = read_call(contract, data, tag)
            address = "0x" + result[-40:].lower()
            if len(result) < 66 or int(address, 16) == 0:
                raise RuntimeError(f"Invalid {group} token address at index {index}")
            try:
                symbol = symbol_from_hex(read_call(address, SELECTOR_SYMBOL, tag))
            except (ValueError, RuntimeError, subprocess.SubprocessError, json.JSONDecodeError):
                symbol = None
            records.append({"index": index, "address": address, "symbol": symbol})
            unique.add(address)
            print(f"  [{index}] {symbol or 'UNKNOWN'}  {address}", flush=True)
        snapshot["contracts"][group] = {"address": contract, "tokens": records}
    snapshot["unique_token_count"] = len(unique)
    path = Path("data/reward_tokens_base.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Unique token addresses: {len(unique)}", flush=True)
    print(f"Saved: {path}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
