#!/usr/bin/env python3
"""P8.1: read-only readiness check for a future isolated 928-pool cohort.

NO RPC, token-price requests, wallet access, scheduling or output files.
Existing 2026-10-08/2026-10-15 cohorts remain historical.
This script does not enable collection or an update to the 8766 browser.
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from run_pool_batch_pipeline import (
    BATCH_ROOT, PREFIX, paths_for, read_json, reference_epoch, validate_manifest,
)
from serve_pool_research import DATA, EPOCHS, validate_research

OLD_THROUGH = 15
EXPECTED_POOL_COUNT = 928
EXPECTED_BATCH_COUNT = 38
EXPECTED_BLOCK = 52595092
OLD_FOLDER = BATCH_ROOT / PREFIX
NEXT_FOLDER = OLD_FOLDER / "epochs" / "2026-10-15"


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def next_thursday_utc(now):
    """A planning reference only. Does not imply safe collection next week."""
    now = now.astimezone(timezone.utc)
    days = (3 - now.weekday()) % 7
    target = (now + timedelta(days=days)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    if target <= now:
        target += timedelta(days=7)
    return target


def validate_archive(data, old_manifest, new_manifest, old, newer):
    """Verify cohort identity and local-file completeness without modifying files."""
    require(data.get("chain_id") == 8453, "Research dataset is not Base Mainnet")
    require(data.get("audited_pool_count") == EXPECTED_POOL_COUNT and
            data.get("inventory_pool_count") == EXPECTED_POOL_COUNT and
            not data.get("not_audited_at_collection"),
            "Research dataset is not an entirely audited 928-pool inventory")
    require(old_manifest.get("snapshot_block_number") == EXPECTED_BLOCK and
            new_manifest.get("snapshot_block_number") == EXPECTED_BLOCK,
            "Source batch plans do not use the historical inventory block")
    require(old_manifest.get("inventory_sha256") ==
            new_manifest.get("inventory_sha256"),
            "Historical cohort batch plans use different inventory identities")
    require(old_manifest.get("batch_count") == EXPECTED_BATCH_COUNT and
            new_manifest.get("batch_count") == EXPECTED_BATCH_COUNT,
            "Historical 38-batch plans are incomplete")
    require(reference_epoch(old, old_manifest) == EPOCHS[0] and
            reference_epoch(newer, new_manifest) == EPOCHS[1],
            "Historical cohort files do not match their pinned reward epochs")
    require(data.get("snapshot_block_number") == EXPECTED_BLOCK,
            "Research JSON has a different inventory snapshot block")

    indexed = {}
    for p in data["pools"]:
        require(type(p.get("index")) is int and
                type(p.get("batch_number")) is int,
                "Pool identity or source batch is malformed")
        key = (p["collection_epoch_utc"], p["batch_number"])
        indexed.setdefault(key, set()).add(p["index"])
    require(sum(map(len, indexed.values())) == EXPECTED_POOL_COUNT,
            "Duplicated or unclassified research pool index")

    counts = []
    for epoch, folder, first, last, manifest in (
        (EPOCHS[0], old, 1, OLD_THROUGH, old_manifest),
        (EPOCHS[1], newer, OLD_THROUGH + 1, EXPECTED_BATCH_COUNT, new_manifest),
    ):
        cohort_pools, status_markers = 0, 0
        for n in range(first, last + 1):
            row = manifest["batches"][n - 1]
            identities = set(row["pool_indexes"])
            require(indexed.get((epoch, n)) == identities,
                    f"Pool identities in saved epoch/batch {epoch} #{n:03d} differ")
            cohort_pools += len(identities)
            paths = paths_for(folder, n)
            for name in ("input", "fees", "incentives", "audit"):
                require(paths[name].is_file(),
                        f"Archived {epoch} batch {n:03d} lacks {name}")
            fees = read_json(paths["fees"])
            incentives = read_json(paths["incentives"])
            audit = read_json(paths["audit"])
            require(fees.get("current_epoch_start_utc") == epoch and
                    incentives.get("current_epoch_utc") == epoch and
                    audit.get("source_epoch_utc") == epoch,
                    f"Archived batch {n:03d} has inconsistent source epochs")
            status_path = paths["status"]
            if status_path.is_file():
                status_markers += 1
                status = read_json(status_path)
                require(status.get("state") == "complete" and
                        status.get("epoch_utc") == epoch and
                        status.get("expected_pools") == len(identities),
                        f"Archived batch {n:03d} has a conflicting status marker")
            else:
                # Historical batch 001 was originally collected separately.
                require(epoch == EPOCHS[0] and n == 1,
                        f"Archived batch {n:03d} has no completion marker")
        require(cohort_pools == data["by_collection_epoch"][epoch]["audited_pools"],
                f"Archived {epoch} totals do not match the research dataset")
        counts.append((epoch, cohort_pools, last - first + 1, status_markers))
    return counts


def inspect():
    print("P8.1 READ-ONLY PREFLIGHT | No blockchain/RPC/price requests or file writes")
    print("Checking existing historical batches; NOT preparing live collection.")
    old_manifest = validate_manifest(OLD_FOLDER)
    new_manifest = validate_manifest(NEXT_FOLDER)
    data = validate_research(json.loads(DATA.read_text(encoding="utf-8")))
    counts = validate_archive(data, old_manifest, new_manifest, OLD_FOLDER, NEXT_FOLDER)
    for epoch, pools, batches, markers in counts:
        print(f"ARCHIVE OK {epoch}: {pools} pools | {batches} batches | "
              f"{markers} completion markers")
    print(f"RESEARCH OK {data['audited_pool_count']}/928 | "
          f"complete saved USD: {data['audited_usd_complete_pool_count']} | "
          f"incomplete saved USD: {data['audited_usd_incomplete_pool_count']}")
    print(f"Research generated UTC: {data.get('generated_at_utc', 'Unknown')}")
    print(f"Next potential new UTC cohort boundary: "
          f"{next_thursday_utc(datetime.now(timezone.utc)).isoformat()}")
    print("P8 DESIGN GATES:")
    print("  1. Create a NEW isolated period plan; never reuse expired cohort folders.")
    print("  2. Recheck current Voter registry and pool/gauge status before claiming 928 live.")
    print("  3. Bound collection with retries, epoch guards and separate locks/resources.")
    print("  4. Preserve original research and both epoch labels; do not overwrite 8766 data.")
    print("  5. Validate each quote timestamp and separate old P4 votes from reward weeks.")
    print("  6. Add versioned multi-cohort APIs/UI and offline tests BEFORE promotion.")
    print("  7. Leave the 8765 hourly task and original 16-pool bundle untouched.")
    print("READINESS: historical data verified; NEW 928-pool live collection NOT enabled.")


if __name__ == "__main__":
    try:
        inspect()
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"P8.1 PREFLIGHT BLOCKED: {exc}", file=sys.stderr)
        sys.exit(1)
