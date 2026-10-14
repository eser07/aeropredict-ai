#!/usr/bin/env python3
"""Read REAL token0/token1 symbols for sampled Aerodrome pools on Base.

Pool trading tokens are NOT inferred from FEES / BRIBES reward tokens.
This lightweight metadata step does not refresh or modify reward estimates.
Stores a separate local JSON artifact for the read-only dashboard.
"""
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from reward_tokens import CHAIN_ID, RPC, read_call, rpc, symbol_from_hex
from scan_pools_base import selector

SOURCE = Path("data/pool_incentives_base.json")
OUTPUT = Path("data/pool_pairs_base.json")
ZERO = "0x" + "0" * 40
SYMBOL_SELECTOR = selector("symbol()")
TOKEN0_SELECTOR = selector("token0()")
TOKEN1_SELECTOR = selector("token1()")


def read_pool_token(pool_address, signature):
    word = read_call(pool_address, signature, "latest")
    if len(word) != 66:
        raise RuntimeError(f"Unexpected response length for pool {pool_address}")
    result = int(word, 16)
    if result >= 2 ** 160 or result == 0:
        raise RuntimeError(f"Invalid token address for pool {pool_address}")
    return "0x" + format(result, "040x")


def symbol_or_address(token_address, cache):
    if token_address in cache:
        return cache[token_address]
    try:
        raw = read_call(token_address, SYMBOL_SELECTOR, "latest")
        symbol = symbol_from_hex(raw)
    except (ValueError, RuntimeError, subprocess.SubprocessError, UnicodeError):
        symbol = None

    if symbol is not None:
        # Avoid control chars / arbitrarily long strings from untrusted tokens.
        symbol = "".join(c for c in symbol.strip() if c.isprintable())
        if len(symbol) > 32 or not symbol:
            symbol = None
    if not symbol:
        symbol = token_address[:6] + "…" + token_address[-4:]
    cache[token_address] = symbol
    return symbol


def main():
    if not SOURCE.is_file():
        raise RuntimeError(
            "Missing saved incentive data. Run collect_pool_incentives_base.py first."
        )
    incentives = json.loads(SOURCE.read_text(encoding="utf-8"))
    if incentives.get("chain_id") != CHAIN_ID:
        raise RuntimeError("Saved incentives are not from Base Mainnet")
    if not isinstance(incentives.get("pools"), list):
        raise RuntimeError("Saved incentives have no pool list")
    if int(rpc("eth_chainId", []), 16) != CHAIN_ID:
        raise RuntimeError("RPC is not Base Mainnet")
    block = int(rpc("eth_blockNumber", []), 16)
    print(
        f"AeroPredict AI | actual pool trading pairs from Base block ~{block}",
        flush=True,
    )
    cache = {}
    results = []
    seen = set()
    for entry in incentives["pools"]:
        index = entry["index"]
        pool = entry["pool_address"].lower()
        if not isinstance(index, int) or not isinstance(pool, str):
            raise RuntimeError("Invalid pool entry")
        if len(pool) != 42 or not pool.startswith("0x"):
            raise RuntimeError(f"Invalid pool address for #{index}")
        try:
            int(pool[2:], 16)
        except ValueError as exc:
            raise RuntimeError(f"Invalid hex pool address for #{index}") from exc
        if pool in seen:
            raise RuntimeError(f"Duplicate pool address for #{index}")
        seen.add(pool)

        record = {
            "index": index,
            "pool_address": pool,
            "token0_address": None,
            "token1_address": None,
            "token0_symbol": None,
            "token1_symbol": None,
            "pair_label": None,
        }
        try:
            token0 = read_pool_token(pool, TOKEN0_SELECTOR)
            token1 = read_pool_token(pool, TOKEN1_SELECTOR)
            if token0 == token1 or token0 == ZERO or token1 == ZERO:
                raise RuntimeError("Pool returned identical or zero token addresses")
            s0 = symbol_or_address(token0, cache)
            s1 = symbol_or_address(token1, cache)
            record.update({
                "token0_address": token0,
                "token1_address": token1,
                "token0_symbol": s0,
                "token1_symbol": s1,
                "pair_label": s0 + " / " + s1,
            })
            print(f"Pool #{index} · {record['pair_label']}", flush=True)
        except (ValueError, RuntimeError, subprocess.SubprocessError) as exc:
            record["error"] = str(exc)[:240]
            print(
                f"Pool #{index} · pair unavailable (not guessed from reward tokens)",
                flush=True,
            )
        results.append(record)

    output = {
        "chain_id": CHAIN_ID,
        "source": "token0() and token1() read directly from pool contracts on Base",
        "source_incentive_file": str(SOURCE),
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
        "approx_block_number": block,
        "rpc": RPC,
        "pools": results,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    good = sum(bool(p["pair_label"]) for p in results)
    print(f"Saved: {OUTPUT} | identified {good}/{len(results)} pool pairs")


if __name__ == "__main__":
    try:
        main()
    except (
        OSError, ValueError, RuntimeError, KeyError, TypeError,
        subprocess.SubprocessError, json.JSONDecodeError,
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
