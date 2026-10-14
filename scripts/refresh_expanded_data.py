#!/usr/bin/env python3
"""Safely refresh the opt-in expanded Aerodrome research dataset.

Run from the project root with the project's Python venv active:
    python scripts/refresh_expanded_data.py

Each collector writes to a temporary location under data/. No production/demo
snapshot is overwritten. Four expanded preview files are replaced only after
the complete run passes basic chain, epoch and pool-identity checks.
The four-file replacement is NOT one atomic transaction; stop the local
dashboard while refreshing. Backups are restored on ordinary publish errors.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SCAN = DATA / "pool_scan_active_expanded.json"
DESTINATIONS = {
    "history": DATA / "pool_fee_histories_expanded_base.json",
    "backtest": DATA / "pool_fee_backtest_expanded_base.json",
    "incentives": DATA / "pool_incentives_expanded_base.json",
    "pairs": DATA / "pool_pairs_expanded_base.json",
}
CHAIN_ID = 8453
MAX_POOLS = 50


def read_json(path):
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict) or obj.get("chain_id") != CHAIN_ID:
        raise ValueError(f"{path.name}: invalid JSON or not Base Mainnet")
    return obj


def run(*args):
    command = [sys.executable, *map(str, args)]
    print("\nRUN: " + " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def pool_ids(items, index_key):
    identities = set()
    for item in items:
        index = item.get(index_key)
        address = item.get("pool_address")
        if not isinstance(index, int) or isinstance(index, bool):
            raise ValueError("Invalid pool registration index")
        if not isinstance(address, str) or not address.startswith("0x") or len(address) != 42:
            raise ValueError("Invalid pool contract address")
        identity = (index, address.lower())
        if identity in identities:
            raise ValueError(f"Duplicate pool identity: {identity}")
        identities.add(identity)
    return identities


def validate(staged, pool_count):
    history = read_json(staged["history"])
    backtest = read_json(staged["backtest"])
    incentives = read_json(staged["incentives"])
    pairs = read_json(staged["pairs"])

    if history.get("block_tag") != "latest":
        raise ValueError("Unexpected historical-state query method")
    pools = history.get("pools")
    if not isinstance(pools, list) or len(pools) != pool_count:
        raise ValueError("FEES history has missing scan entries")
    active_ids = pool_ids(
        [p for p in pools if p.get("active_at_collection")], "index"
    )
    if len(active_ids) < 4:
        raise ValueError("Fewer than four active pools; optimizer would be unusable")

    incentive_pools = incentives.get("pools")
    pair_pools = pairs.get("pools")
    rows = backtest.get("results")
    if not all(isinstance(v, list) for v in (incentive_pools, pair_pools, rows)):
        raise ValueError("An expanded output is missing its pools/results list")
    if pool_ids(incentive_pools, "index") != active_ids:
        raise ValueError("Incentive pools do not match the fresh FEES history")
    if pool_ids(pair_pools, "index") != active_ids:
        raise ValueError("Trading pairs do not match the incentive pools")
    if len(rows) != history.get("series_count") or len(rows) != backtest.get("series_count"):
        raise ValueError("Backtest series count does not match FEES history")
    if not all(
        (r.get("pool_index"), str(r.get("pool_address", "")).lower()) in active_ids
        for r in rows
    ):
        raise ValueError("Backtest contains a pool outside the active sample")

    epoch_str = history.get("current_epoch_start_utc")
    if epoch_str != incentives.get("current_epoch_utc"):
        raise ValueError("FEES and BRIBES data were collected in different epochs")
    epoch = datetime.fromisoformat(epoch_str)
    now = datetime.now(timezone.utc)
    if not epoch.tzinfo or not epoch <= now < epoch + timedelta(days=7):
        raise ValueError("Weekly epoch changed during refresh; please rerun")
    collected = datetime.fromisoformat(incentives["collected_at_utc"])
    if not collected.tzinfo or abs((now - collected).total_seconds()) > 2 * 3600:
        raise ValueError("Incentives output is stale or has an invalid timestamp")

    for series in rows:
        if not isinstance(series.get("analysis"), dict):
            raise ValueError("Incomplete backtest result")
    for p in incentive_pools:
        if p.get("pool_vote_weight_raw") is None:
            raise ValueError(f"Missing current vote weight for pool #{p.get('index')}")

    # Temporary file paths should not remain in the published provenance fields.
    backtest["input"] = str(DESTINATIONS["history"].relative_to(ROOT))
    incentives["source_file"] = str(DESTINATIONS["history"].relative_to(ROOT))
    pairs["source_incentive_file"] = str(DESTINATIONS["incentives"].relative_to(ROOT))
    for kind, data in (("backtest", backtest), ("incentives", incentives), ("pairs", pairs)):
        staged[kind].write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    priced = sum(bool(p.get("fully_priced")) for p in incentive_pools)
    found = sum(bool(p.get("pair_label")) for p in pair_pools)
    print(
        f"\nVALIDATED: {len(active_ids)} currently active pools, "
        f"{len(rows)} FEES series, {priced}/{len(active_ids)} fully priced pools, "
        f"{found}/{len(active_ids)} pairs, epoch {epoch.date()} UTC.",
        flush=True,
    )


def publish(staged, temp):
    backup_dir = temp / "backups"
    backup_dir.mkdir()
    existed = {}
    for kind, target in DESTINATIONS.items():
        existed[kind] = target.exists()
        if target.exists():
            shutil.copy2(target, backup_dir / target.name)

    moved = []
    try:
        for kind, target in DESTINATIONS.items():
            os.replace(staged[kind], target)
            moved.append(kind)
    except BaseException:
        print("Publish failed; restoring previously saved expanded data.", flush=True)
        for kind in reversed(moved):
            target = DESTINATIONS[kind]
            old = backup_dir / target.name
            if existed[kind]:
                os.replace(old, target)
            elif target.exists():
                target.unlink()
        raise


def main():
    if not SCAN.is_file():
        raise ValueError("Missing data/pool_scan_active_expanded.json")
    scan = read_json(SCAN)
    candidates = scan.get("pools")
    if not isinstance(candidates, list) or not 4 <= len(candidates) <= MAX_POOLS:
        raise ValueError("Expanded scan must contain 4-50 active candidates")
    pool_ids(candidates, "index")
    DATA.mkdir(exist_ok=True)
    print(
        f"AeroPredict AI | safe refresh | {len(candidates)} registered-pool candidates",
        flush=True,
    )
    print(
        "Stops without replacing existing expanded files if any stage fails.",
        flush=True,
    )
    print("Do not leave the dashboard server running during this refresh.", flush=True)

    with tempfile.TemporaryDirectory(
        prefix=".aeropredict_refresh_", dir=DATA
    ) as temp_dir:
        temp = Path(temp_dir)
        staged = {k: temp / v.name for k, v in DESTINATIONS.items()}

        run(
            "scripts/pool_fee_histories_base.py",
            "--scan-file", SCAN,
            "--output-file", staged["history"],
            "--weeks", "12",
            "--max-pools", str(len(candidates)),
            "--max-tokens", "4",
        )
        run(
            "scripts/backtest_pool_fees.py",
            "--input-file", staged["history"],
            "--output-file", staged["backtest"],
        )
        run(
            "scripts/collect_pool_incentives_base.py",
            "--input-file", staged["history"],
            "--output-file", staged["incentives"],
            "--max-bribe-tokens", "20",
        )
        run(
            "scripts/collect_pool_pairs_base.py",
            "--input-file", staged["incentives"],
            "--output-file", staged["pairs"],
        )
        validate(staged, len(candidates))
        publish(staged, temp)

    print("\nSUCCESS: Expanded dashboard data refreshed.", flush=True)
    print("Start: python scripts/serve_dashboard.py --dataset expanded", flush=True)
    print(
        "Reminder: FEES/BRIBES and voting-weight snapshots remain unsynchronized; "
        "the optimizer is only a historical-data what-if scenario.",
        flush=True,
    )


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as exc:
        print(f"\nREFRESH STOPPED: {exc}", file=sys.stderr, flush=True)
        print(
            "Existing expanded dataset was preserved if failure occurred before "
            "the publish phase.",
            file=sys.stderr, flush=True,
        )
        sys.exit(1)
