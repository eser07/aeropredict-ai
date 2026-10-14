#!/usr/bin/env python3
"""Collect Base Aerodrome BRIBES and current USD token quote coverage.

Experimental analysis only. FEES history from latest-state epoch keys,
BRIBES data, vote weights and current prices are not synchronized to
one historical block. This does NOT establish claimable veAERO income.
Missing/stale quotes or truncated token lists invalidate full USD totals.
"""
import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from reward_tokens import CHAIN_ID, read_call, rpc
from reward_epochs import SELECTOR_DURATION, SELECTOR_EPOCH_START, SELECTOR_TOKEN_REWARDS, rpc_object
from scan_pools_base import VOTER, read_address, selector
from pool_fee_histories_base import metadata

SOURCE = Path("data/pool_fee_histories_base.json")
OUTPUT = Path("data/pool_incentives_base.json")
WEEK = 604800
ZERO = "0x" + "0" * 40
MAX_PRICE_AGE = 36 * 3600


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


def quotes_for(tokens):
    """Query by Base contract address, not ambiguous token symbol."""
    results = {}
    ordered = sorted(set(tokens))
    for i in range(0, len(ordered), 15):
        batch = ordered[i:i + 15]
        path = ",".join("base:" + t for t in batch)
        url = "https://coins.llama.fi/prices/current/" + path
        try:
            proc = subprocess.run(
                ["curl", "-fsS", "--retry", "2", "--connect-timeout", "10",
                 "--max-time", "30", url],
                capture_output=True, text=True, check=True, timeout=100,
            )
            result = json.loads(proc.stdout)
            response = result.get("coins", {})
            if not isinstance(response, dict):
                raise ValueError("Invalid price response")
        except (OSError, ValueError, subprocess.SubprocessError) as e:
            print(f"  Price request error: {e}", flush=True)
            response = {}
        for addr in batch:
            item = response.get("base:" + addr)
            reason = "quote_missing"
            price = None
            timestamp = None
            if isinstance(item, dict):
                try:
                    p = Decimal(str(item["price"]))
                    timestamp = int(item["timestamp"])
                    age = int(time.time()) - timestamp
                    if p.is_finite() and p > 0 and -300 <= age <= MAX_PRICE_AGE:
                        price, reason = str(p), None
                    else:
                        reason = "nonpositive_or_stale_quote"
                except (KeyError, ValueError, TypeError, InvalidOperation):
                    reason = "malformed_quote"
            results[addr] = {
                "price_usd": price, "reason": reason,
                "price_timestamp_utc": iso(timestamp) if timestamp else None,
            }
    return results


def record_reward(token, symbol, decimals, periods):
    amounts = [int(row["raw"]) for row in periods]
    if len(amounts) != 4 or min(amounts) < 0:
        raise RuntimeError("Expected four nonnegative completed weekly allocations")
    average = (
        Decimal(sum(amounts)) / Decimal(4) / Decimal(10) ** decimals
        if decimals is not None else None
    )
    return {
        "token_address": token.lower(), "symbol": symbol, "decimals": decimals,
        "last_four_weeks": periods,
        "four_week_mean_amount": str(average) if average is not None else None,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-bribe-tokens", type=int, default=8)
    parser.add_argument(
        "--input-file", type=Path, default=SOURCE,
        help="FEES history file (default original dashboard sample)",
    )
    parser.add_argument(
        "--output-file", type=Path, default=OUTPUT,
        help="BRIBES + USD quote file (default original dashboard sample)",
    )
    args = parser.parse_args()
    data_dir = Path("data").resolve()
    input_file = args.input_file.resolve()
    output_file = args.output_file.resolve()
    if any(
        not p.is_relative_to(data_dir) or p.suffix.lower() != ".json"
        for p in (input_file, output_file)
    ):
        parser.error("Both JSON paths must be inside data/")
    if input_file == output_file:
        parser.error("Input and output must be different files")
    if input_file != SOURCE.resolve() and output_file == OUTPUT.resolve():
        parser.error(
            "Custom FEES input requires a custom --output-file to protect the demo"
        )
    if not 1 <= args.max_bribe_tokens <= 40:
        parser.error("--max-bribe-tokens must be between 1 and 40")
    if not input_file.is_file():
        raise RuntimeError(f"Missing saved fees history: {args.input_file}")
    source = json.loads(input_file.read_text(encoding="utf-8"))
    if source.get("chain_id") != CHAIN_ID:
        raise RuntimeError("Input is not Base Mainnet")
    if int(rpc("eth_chainId", []), 16) != CHAIN_ID:
        raise RuntimeError("Wrong RPC chain")

    block = rpc_object("eth_getBlockByNumber", ["latest", False])
    timestamp = int(block["timestamp"], 16)
    epoch = int(read_call(
        VOTER, SELECTOR_EPOCH_START + f"{timestamp:064x}", "latest"
    ), 16)
    if source.get("current_epoch_start_utc") != iso(epoch):
        raise RuntimeError(
            "Current epoch changed since FEES history collection; "
            "refresh FEES data first"
        )
    weeks = [epoch - i * WEEK for i in range(4, 0, -1)]
    print("AeroPredict AI | FEES + BRIBES USD quote diagnostics", flush=True)
    print("Past four completed weeks using latest-state epoch queries.", flush=True)
    print(f"Base current epoch: {iso(epoch)}", flush=True)
    pools = []
    tokens = set()
    cache = {}

    for old in source.get("pools", []):
        if not old.get("active_at_collection"):
            continue
        idx = old["index"]
        fees = []
        for series in old.get("reward_series", []):
            records = series["completed_weeks"][-4:]
            if [r["epoch_start_utc"] for r in records] != [iso(w) for w in weeks]:
                raise RuntimeError(f"FEES data weeks do not match for pool #{idx}")
            fee = record_reward(
                series["token_address"], series["symbol"], series["decimals"], records
            )
            fees.append(fee)
            tokens.add(fee["token_address"])
        bribe_contract = read_address(
            "gaugeToBribe(address)", old["gauge_address"], "latest"
        )
        pool = {
            "index": idx, "pool_address": old["pool_address"],
            "gauge_address": old["gauge_address"],
            "pool_vote_weight_raw": old.get("pool_vote_weight_raw"),
            "bribe_contract": bribe_contract,
            "fees_registry_truncated": bool(old.get("tokens_truncated")),
            "bribes_registry_truncated": False,
            "fees": fees, "bribes": [],
        }
        pools.append(pool)
        print(f"Pool #{idx}: {len(fees)} FEES tokens", flush=True)
        if bribe_contract == ZERO:
            continue
        duration = int(read_call(bribe_contract, SELECTOR_DURATION, "latest"), 16)
        if duration != WEEK:
            pool["bribes_error"] = f"reward duration {duration} != {WEEK}"
            print("  BRIBES unsupported reward duration", flush=True)
            continue
        count = int(read_call(
            bribe_contract, selector("rewardsListLength()"), "latest"
        ), 16)
        if count > 500:
            raise RuntimeError(f"Too many BRIBES tokens for pool #{idx}: {count}")
        pool["bribes_registry_truncated"] = count > args.max_bribe_tokens
        print(
            f"  BRIBES: reading {min(count, args.max_bribe_tokens)}/{count} tokens",
            flush=True,
        )
        for i in range(min(count, args.max_bribe_tokens)):
            encoded = read_call(
                bribe_contract, selector("rewards(uint256)") + f"{i:064x}",
                "latest",
            )
            if len(encoded) != 66:
                raise RuntimeError("Invalid registered reward token address")
            token = "0x" + encoded[-40:].lower()
            if token == ZERO:
                raise RuntimeError("Invalid zero reward token address")
            info = metadata(token, cache)
            records = []
            for w in weeks:
                calldata = SELECTOR_TOKEN_REWARDS + token[2:].zfill(64) + f"{w:064x}"
                raw = int(read_call(bribe_contract, calldata, "latest"), 16)
                records.append({"epoch_start_utc": iso(w), "raw": str(raw)})
            bribe = record_reward(
                token, info["symbol"], info["decimals"], records
            )
            pool["bribes"].append(bribe)
            tokens.add(token)
            print(
                f"    {info['symbol']}: 4-week mean {bribe['four_week_mean_amount']}",
                flush=True,
            )

    print(f"Fetching current USD quotes for {len(tokens)} Base tokens...", flush=True)
    prices = quotes_for(tokens)
    good = 0
    for pool in pools:
        missing = []
        total = Decimal(0)
        for kind in ("fees", "bribes"):
            for series in pool[kind]:
                amount = series["four_week_mean_amount"]
                quote = prices.get(series["token_address"], {})
                price = quote.get("price_usd")
                if amount is None:
                    missing.append(series["symbol"] + ":unknown_decimals")
                    series["usd_at_current_price"] = None
                elif Decimal(amount) == 0:
                    series["usd_at_current_price"] = "0"
                elif price is None:
                    missing.append(series["symbol"] + ":no_fresh_price")
                    series["usd_at_current_price"] = None
                else:
                    usd = Decimal(amount) * Decimal(price)
                    series["usd_at_current_price"] = str(usd)
                    total += usd
        complete = (
            not pool["fees_registry_truncated"]
            and not pool["bribes_registry_truncated"]
            and not pool.get("bribes_error")
            and len(missing) == 0
        )
        pool["fully_priced"] = complete
        pool["missing_components"] = missing
        pool["four_week_avg_total_usd_at_current_prices"] = (
            str(total) if complete else None
        )
        print(
            f"Pool #{pool['index']}: " +
            (f"complete / approx USD {total:.2f} per week"
             if complete else "INCOMPLETE: " + ", ".join(missing)),
            flush=True,
        )
        good += int(complete)

    report = {
        "chain_id": CHAIN_ID, "current_epoch_utc": iso(epoch),
        "source_file": str(args.input_file), "collected_at_utc": iso(int(time.time())),
        "quote_provider": "DefiLlama current token address prices",
        "week_count": 4, "quote_max_age_hours": 36,
        "fully_priced_pools": good,
        "prices": prices, "pools": pools,
        "warnings": [
            "Current prices applied to past allocations, not historical prices",
            "Historical epoch keys queried against latest state, not archived snapshots",
            "Current voting weight and past reward allocations are not aligned",
            "Missing quote does not mean a token reward has zero USD value",
            "Amounts are pool-level allocations, not individual veAERO payouts",
            "BRIBES and FEES distribution timing and voting eligibility require checking",
        ],
    }
    output_file.parent.mkdir(exist_ok=True, parents=True)
    output_file.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Saved: {args.output_file} | fully priced: {good}/{len(pools)} active pools")
    print("Not yet an optimizer or a guaranteed veAERO income forecast.")


if __name__ == "__main__":
    try:
        main()
    except (
        OSError, ValueError, RuntimeError, KeyError, TypeError,
        InvalidOperation, subprocess.SubprocessError,
    ) as err:
        print(f"ERROR: {err}", file=sys.stderr)
        sys.exit(1)
