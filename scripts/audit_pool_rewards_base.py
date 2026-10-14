#!/usr/bin/env python3
"""Audit saved FEES+BRIBES quotes and vote-efficiency for a single P2 pool batch.

Offline/read-only analysis: no Base RPC, no API, no wallet and no changes to
the expanded dashboard or hourly refresh. Four-week historical allocations
are valued at SAVED current quotes, not period-specific historical prices.
"""
import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path

from plan_pool_collection_base import save_atomic

ROOT = Path(__file__).resolve().parents[1]
BATCHES = ROOT / "data" / "pool_collection_batches_base"
WEEK = timedelta(days=7)
MAX_QUOTE_AGE = timedelta(hours=36)
FUTURE_TOLERANCE = timedelta(minutes=5)
UNITS_PER_VOTE = Decimal(10) ** 18


def read_time(value, label):
    try:
        result = datetime.fromisoformat(value)
        if result.tzinfo is None:
            raise ValueError("timezone missing")
        return result.astimezone(timezone.utc)
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError(f"Invalid UTC timestamp in {label}") from exc


def nonnegative_raw(value, label):
    if not isinstance(value, str) or not value.isdigit():
        raise ValueError(f"Invalid nonnegative raw amount in {label}")
    return int(value)


def snapshot_weeks(epoch):
    t = read_time(epoch, "reward epoch")
    return [(t - WEEK * distance).isoformat() for distance in (4, 3, 2, 1)]


def rows_for_series(series, expected_weeks, label):
    weeks = series.get("last_four_weeks")
    if not isinstance(weeks, list) or len(weeks) != 4:
        raise ValueError(f"{label}: expected exactly four weekly records")
    if [r.get("epoch_start_utc") for r in weeks] != expected_weeks:
        raise ValueError(f"{label}: reward weeks do not align with source epoch")
    return [nonnegative_raw(row.get("raw"), label) for row in weeks]


def price_for_token(quotes, address, now):
    quote = quotes.get(address.lower())
    if not isinstance(quote, dict) or quote.get("price_usd") is None:
        return None
    try:
        p = Decimal(str(quote["price_usd"]))
    except (InvalidOperation, ValueError):
        return None
    if not p.is_finite() or p <= 0:
        return None
    try:
        t = read_time(quote.get("price_timestamp_utc"), f"quote for {address}")
    except ValueError:
        return None
    age = now - t
    if age < -FUTURE_TOLERANCE or age > MAX_QUOTE_AGE:
        return None
    return p


def value_entries(entries, expected_weeks, quotes, now, label):
    if not isinstance(entries, list):
        raise ValueError(f"{label}: missing token series")
    totals = [Decimal(0) for _ in range(4)]
    positive = [False] * 4
    missing = []
    addresses = set()
    for series in entries:
        token = series.get("token_address")
        if not isinstance(token, str) or len(token) != 42 or not token.startswith("0x"):
            raise ValueError(f"{label}: invalid reward token address")
        token = token.lower()
        if token in addresses:
            raise ValueError(f"{label}: duplicate reward token address")
        addresses.add(token)
        amounts = rows_for_series(series, expected_weeks, f"{label}/{token}")
        decimals = series.get("decimals")
        if type(decimals) is not int or not 0 <= decimals <= 36:
            if any(amounts):
                missing.append(f"{token}:unknown_decimals")
            continue
        price = price_for_token(quotes, token, now)
        if any(amounts) and price is None:
            missing.append(f"{token}:missing_or_stale_quote")
        for i, raw in enumerate(amounts):
            positive[i] |= raw > 0
            if price is not None:
                totals[i] += (Decimal(raw) / (Decimal(10) ** decimals)) * price
    return totals, positive, missing


def audit(fees, incentives, now=None):
    if now is None:
        now = datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Audit time must include timezone")
    now = now.astimezone(timezone.utc)
    if fees.get("chain_id") != 8453 or incentives.get("chain_id") != 8453:
        raise ValueError("Both datasets must be from Base Mainnet")
    epoch = fees.get("current_epoch_start_utc")
    if epoch != incentives.get("current_epoch_utc"):
        raise ValueError("FEES and BRIBES datasets were collected for different epochs")
    if incentives.get("week_count") != 4 or fees.get("completed_weeks_requested", 0) < 4:
        raise ValueError("Expected at least four FEES weeks and four BRIBES weeks")
    expected_weeks = snapshot_weeks(epoch)
    quotes = incentives.get("prices")
    if not isinstance(quotes, dict):
        raise ValueError("Incentive price map is missing")
    source_pools = fees.get("pools")
    incentive_pools = incentives.get("pools")
    if not isinstance(source_pools, list) or not isinstance(incentive_pools, list):
        raise ValueError("Pool arrays are missing")
    active = {}
    for p in source_pools:
        idx = p.get("index")
        if type(idx) is not int:
            raise ValueError("Invalid source pool index")
        if p.get("active_at_collection"):
            if idx in active:
                raise ValueError("Duplicate active source pool index")
            active[idx] = p
    target = {}
    for p in incentive_pools:
        idx = p.get("index")
        if type(idx) is not int or idx in target:
            raise ValueError("Duplicate or malformed incentive pool index")
        target[idx] = p
    if not active or active.keys() != target.keys():
        raise ValueError("FEES active pool identities do not match incentive pools")
    report_pools = []
    for index in sorted(active):
        src, dst = active[index], target[index]
        if any(src.get(k) != dst.get(k) for k in (
            "pool_address", "gauge_address", "pool_vote_weight_raw",
        )):
            raise ValueError(f"Pool #{index}: FEES and incentives identity/weight mismatch")
        expected_fee = {
            s.get("token_address", "").lower(): s
            for s in src.get("reward_series", [])
        }
        actual_fee = {
            s.get("token_address", "").lower(): s
            for s in dst.get("fees", [])
        }
        if (len(expected_fee) != len(src.get("reward_series", [])) or
                len(actual_fee) != len(dst.get("fees", [])) or
                expected_fee.keys() != actual_fee.keys()):
            raise ValueError(f"Pool #{index}: FEES token registrations mismatch")
        for token, from_fees in expected_fee.items():
            values = from_fees.get("completed_weeks", [])[-4:]
            audited = actual_fee[token].get("last_four_weeks", [])
            if (len(values) != 4 or len(audited) != 4 or
                    [(v.get("epoch_start_utc"), v.get("raw")) for v in values] !=
                    [(v.get("epoch_start_utc"), v.get("raw")) for v in audited]):
                raise ValueError(f"Pool #{index}: FEES reward records mismatch")
        fee_total, fee_positive, fee_missing = value_entries(
            dst.get("fees"), expected_weeks, quotes, now, f"Pool #{index} FEES",
        )
        bribe_total, bribe_positive, bribe_missing = value_entries(
            dst.get("bribes"), expected_weeks, quotes, now, f"Pool #{index} BRIBES",
        )
        try:
            vote_raw = nonnegative_raw(dst.get("pool_vote_weight_raw"), f"Pool #{index} votes")
        except ValueError:
            vote_raw = 0
            vote_missing = True
        else:
            vote_missing = False
        votes = Decimal(vote_raw) / UNITS_PER_VOTE
        truncated = (
            bool(src.get("tokens_truncated")) or
            bool(dst.get("fees_registry_truncated")) or
            bool(dst.get("bribes_registry_truncated")) or
            bool(dst.get("bribes_error"))
        )
        missing = fee_missing + bribe_missing
        valid = not truncated and not missing
        week_usd = [f + b for f, b in zip(fee_total, bribe_total)]
        avg = sum(week_usd) / Decimal(4) if valid else None
        efficiency = avg / votes * Decimal(1000000) if avg is not None and votes > 0 else None
        nonzero_week_count = sum(f or b for f, b in zip(fee_positive, bribe_positive))
        peak_share = max(week_usd) / sum(week_usd) if valid and sum(week_usd) > 0 else None
        report_pools.append({
            "index": index,
            "pool_address": src["pool_address"],
            "snapshot_votes": str(votes) if not vote_missing else None,
            "weekly_usd_at_saved_current_prices": [str(x) for x in week_usd] if valid else None,
            "avg_weekly_usd_at_saved_current_prices": str(avg) if avg is not None else None,
            "usd_per_million_snapshot_votes": str(efficiency) if efficiency is not None else None,
            "fees_positive_weeks": sum(fee_positive),
            "bribes_positive_weeks": sum(bribe_positive),
            "combined_positive_weeks": nonzero_week_count,
            "highest_week_share_of_four_week_total": str(peak_share) if peak_share is not None else None,
            "truncated_registry": truncated,
            "missing_or_stale_components": missing,
            "usd_coverage_complete_at_audit": valid,
            "caveat": "Vote weight and reward series are from different collection moments",
        })
    complete = [p for p in report_pools if p["usd_coverage_complete_at_audit"]]
    by_usd = sorted(
        [p for p in complete if p["avg_weekly_usd_at_saved_current_prices"] is not None],
        key=lambda p: (-Decimal(p["avg_weekly_usd_at_saved_current_prices"]), p["index"]),
    )
    by_votes = sorted(
        [p for p in complete if p["usd_per_million_snapshot_votes"] is not None],
        key=lambda p: (-Decimal(p["usd_per_million_snapshot_votes"]), p["index"]),
    )
    return {
        "schema_version": 1,
        "type": "P2 offline coverage/efficiency audit, not an optimizer",
        "chain_id": 8453,
        "audit_at_utc": now.isoformat(),
        "source_epoch_utc": epoch,
        "source_fees_collected_at_utc": fees.get("collected_at_utc"),
        "source_incentives_collected_at_utc": incentives.get("collected_at_utc"),
        "pool_count": len(report_pools),
        "audited_complete_usd_count": len(complete),
        "incomplete_usd_count": len(report_pools) - len(complete),
        "four_week_usd_totals_by_pool": report_pools,
        "top_five_by_total_usd_indexes": [p["index"] for p in by_usd[:5]],
        "top_five_by_usd_per_million_votes_indexes": [p["index"] for p in by_votes[:5]],
        "warnings": [
            "These are pool-level rewards, not veNFT payouts, claimable fees or a yield forecast.",
            "The same saved current token quote is applied to all four past epochs; "
            "not historical USD prices.",
            "Past epoch keys are fetched from current contract state, not historic chain snapshots.",
            "Current vote weights are not synchronized with the four past reward epochs.",
            "A small vote denominator can produce misleadingly large vote-efficiency ratios.",
            "Reward frequency is observed over just four weeks and is not a future prediction.",
            "Quoted token prices alone do not verify token legitimacy, depth or liquidity.",
            "Missing/stale quotes and truncated registries suppress pool total USD estimates.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fees", type=Path, required=True)
    parser.add_argument("--incentives", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = BATCHES.resolve()
    paths = [args.fees.resolve(), args.incentives.resolve(), args.output.resolve()]
    if any(not p.is_relative_to(root) or p.suffix != ".json" for p in paths):
        parser.error("All JSON inputs and output must be under data/pool_collection_batches_base/")
    if (len(set(paths)) != 3 or paths[0].parent != paths[1].parent or
            paths[0].parent != paths[2].parent or not paths[2].name.startswith("audit_")):
        parser.error("Use distinct files in one batch folder and name output audit_*.json")
    if not paths[0].is_file() or not paths[1].is_file():
        parser.error("Saved batch FEES and BRIBES files are required")
    report = audit(
        json.loads(paths[0].read_text(encoding="utf-8")),
        json.loads(paths[1].read_text(encoding="utf-8")),
    )
    save_atomic(paths[2], report)
    print(
        f"VERIFIED: {report['pool_count']} pools | "
        f"USD coverage {report['audited_complete_usd_count']}/{report['pool_count']}",
        flush=True,
    )
    for label, ids in (
        ("Largest historic mean rewards (NOT best yield)", report["top_five_by_total_usd_indexes"]),
        ("Highest USD per million snapshot votes (NOT a return promise)",
         report["top_five_by_usd_per_million_votes_indexes"]),
    ):
        print(label + ":", flush=True)
        lookup = {p["index"]: p for p in report["four_week_usd_totals_by_pool"]}
        for idx in ids:
            p = lookup[idx]
            field = ("avg_weekly_usd_at_saved_current_prices" if label.startswith("Largest")
                     else "usd_per_million_snapshot_votes")
            print(
                f"  #{idx}: ${Decimal(p[field]):,.2f} | "
                f"FEES weeks {p['fees_positive_weeks']}/4 | "
                f"all rewards weeks {p['combined_positive_weeks']}/4",
                flush=True,
            )
    print(f"Saved isolated audit: {paths[2]}", flush=True)
    print("Offline: no new RPC/price queries, no changes to dashboard or hourly refresh.", flush=True)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, InvalidOperation) as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        sys.exit(1)
