#!/usr/bin/env python3
"""Merge separately saved Aerodrome scan batches into a NEW active-pool input.

No onchain queries or transactions. Scans may come from different Base block
numbers: these are discovery candidates only, NOT a single-block snapshot.
The FEES collector must recheck each gauge against current Base state.
Never overwrite the existing production/demo scan with this tool.
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

EXPECTED_CHAIN = 8453
DATA = Path("data").resolve()
ORIGINAL = DATA / "pool_scan_base.json"


def within_data(path):
    resolved = path.resolve()
    if not resolved.is_relative_to(DATA) or resolved.suffix.lower() != ".json":
        raise ValueError("Use .json paths inside data/ only")
    return resolved


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "inputs", nargs="+", type=Path,
        help="Existing scan JSONs, e.g. data/pool_scan_base.json data/pool_scan_20_44.json",
    )
    parser.add_argument(
        "--output", type=Path,
        default=Path("data/pool_scan_active_expanded.json"),
        help="NEW output under data/; never overwrite an input",
    )
    args = parser.parse_args()
    if len(args.inputs) < 2:
        parser.error("Provide at least two saved scan files")
    paths = [within_data(p) for p in args.inputs]
    output = within_data(args.output)
    if len(set(paths)) != len(paths):
        parser.error("Input files must be distinct")
    if output in paths or output == ORIGINAL:
        parser.error("Do not overwrite an input or the original demo scan")
    by_index = {}
    by_address = {}
    scans = []
    voter = None
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        if int(data.get("chain_id", -1)) != EXPECTED_CHAIN:
            raise ValueError(f"{path}: not Base Mainnet")
        if not isinstance(data.get("pools"), list):
            raise ValueError(f"{path}: no pools list")
        current_voter = str(data.get("voter", "")).lower()
        if not current_voter.startswith("0x") or len(current_voter) != 42:
            raise ValueError(f"{path}: invalid Voter contract address")
        if voter is None:
            voter = current_voter
        elif voter != current_voter:
            raise ValueError("Scan batches reference different Voter contracts")
        scans.append({
            "file": str(path.relative_to(DATA.parent)),
            "base_block": data.get("block_number"),
            "pool_count": len(data["pools"]),
        })
        for pool in data["pools"]:
            index = pool["index"]
            addr = str(pool["pool_address"]).lower()
            if not isinstance(index, int) or index < 0 or not addr.startswith("0x") or len(addr) != 42:
                raise ValueError(f"{path}: invalid pool entry")
            if index in by_index:
                if by_index[index]["pool_address"].lower() != addr:
                    raise ValueError(f"Conflicting pool address at index {index}")
                raise ValueError(f"Duplicate registration index {index}; use non-overlapping scans")
            if addr in by_address and by_address[addr] != index:
                raise ValueError(f"Pool address appears under different indexes: {addr}")
            by_address[addr] = index
            by_index[index] = pool
    if not by_index:
        raise ValueError("Empty combined scan")
    active = [pool for _, pool in sorted(by_index.items()) if pool.get("gauge_active")]
    result = {
        "source": "Merged active Aerodrome Voter scan candidates from separate saved Base blocks",
        "chain_id": EXPECTED_CHAIN,
        "voter": voter,
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
        "sample_scope": "Active-at-scan candidates only; registration-order batch discovery",
        "notice": (
            "Source scans were taken at different Base blocks. This is NOT a "
            "synchronized snapshot, profitability ranking or confirmed current "
            "active state. Recheck gauge status and voting weights before analysis."
        ),
        "inputs": scans,
        "scanned_unique_pools": len(by_index),
        "active_pool_count_at_scan": len(active),
        "pools": active,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"Scan candidates: {len(by_index)} unique registered pools | "
        f"{len(active)} active at their respective scan blocks"
    )
    print("Active registration IDs: " + ", ".join("#" + str(row["index"]) for row in active))
    print("WARNING: original scans use separate Base block snapshots.")
    print(f"Saved: {args.output} | original dashboard data unchanged")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
