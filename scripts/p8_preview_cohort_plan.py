#!/usr/bin/env python3
"""P8.2: PREVIEW a new isolated research cohort, without writing or collecting.

This previews repeated observations of the FROZEN historical 928-pool cohort,
NOT a freshly validated list of currently alive gauges. New live collection
and cross-period research publication are intentionally NOT implemented.
No RPC, token-price calls, file mutations, wallets or schedulers.
"""
import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from p8_collection_preflight import (
    EXPECTED_BATCH_COUNT, EXPECTED_BLOCK, EXPECTED_POOL_COUNT,
    NEXT_FOLDER, OLD_FOLDER, validate_archive, next_thursday_utc,
)
from run_pool_batch_pipeline import (
    BATCH_ROOT, read_json, validate_manifest,
)
from serve_pool_research import DATA, EPOCHS, validate_research

ISOLATED_ROOT = BATCH_ROOT / "p8_research_cohorts"
MAX_BATCH_SIZE = 25


def choose_epoch(text, now):
    """Choose only a future Thursday 00:00 UTC period for a dry-run preview."""
    now = now.astimezone(timezone.utc)
    if text is None:
        chosen = next_thursday_utc(now)
    else:
        try:
            chosen = datetime.fromisoformat(date.fromisoformat(text).isoformat()).replace(
                tzinfo=timezone.utc
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("Epoch must be a YYYY-MM-DD UTC calendar date") from exc
        if chosen.weekday() != 3:
            raise ValueError("The new research collection epoch must begin Thursday UTC")
    if chosen <= now:
        raise ValueError("Expired or started epochs cannot be previewed as a future plan")
    if chosen.isoformat() <= max(EPOCHS):
        raise ValueError("New research epoch must be later than both archived epochs")
    return chosen


def plan_frozen_subset(manifest, epoch, now):
    """Validate identity and preview a historical sample; no live-active claims."""
    if epoch <= now.astimezone(timezone.utc):
        raise ValueError("Planning target must be in the future")
    if epoch.weekday() != 3 or (epoch.hour, epoch.minute, epoch.second,
                                epoch.microsecond) != (0, 0, 0, 0):
        raise ValueError("Epoch must start Thursday 00:00 UTC")
    if manifest.get("chain_id") != 8453 or (
        manifest.get("snapshot_block_number") != EXPECTED_BLOCK
    ):
        raise ValueError("Historical Base inventory provenance mismatched")
    if manifest.get("batch_count") != EXPECTED_BATCH_COUNT or (
        manifest.get("all_batches_pool_count") != EXPECTED_POOL_COUNT
    ):
        raise ValueError("Frozen sample does not have 928 pools in 38 batches")
    groups = manifest.get("batches")
    if not isinstance(groups, list) or len(groups) != EXPECTED_BATCH_COUNT:
        raise ValueError("Frozen cohort manifest lacks the 38 original groups")
    indexes = []
    for i, row in enumerate(groups, 1):
        ids = row.get("pool_indexes")
        if (row.get("number") != i or not isinstance(ids, list) or
            row.get("pool_count") != len(ids) or
            not 1 <= len(ids) <= MAX_BATCH_SIZE or
            any(type(idx) is not int or idx < 0 for idx in ids)):
            raise ValueError(f"Historical group {i} has invalid identities")
        indexes.extend(ids)
    if len(indexes) != EXPECTED_POOL_COUNT or len(set(indexes)) != EXPECTED_POOL_COUNT:
        raise ValueError("Frozen subset identities are incomplete or duplicated")
    token = epoch.date().isoformat()
    target = ISOLATED_ROOT / f"epoch_{token}" / f"frozen_block_{EXPECTED_BLOCK}"
    return {
        "epoch_utc": epoch.isoformat(),
        "target_preview_only": str(target),
        "source_inventory_block": EXPECTED_BLOCK,
        "source_inventory_sha256": manifest.get("inventory_sha256"),
        "scope": "frozen historical cohort; NOT verified currently active pools",
        "total_pools": len(indexes),
        "total_batches": len(groups),
        "max_pools_per_batch": MAX_BATCH_SIZE,
        "input_identity_count": len(set(indexes)),
        "existing_target": target.exists(),
        "new_live_collection_enabled": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--epoch", default=None, metavar="YYYY-MM-DD",
                        help="Future Thursday UTC week; default next Thursday")
    args = parser.parse_args(argv)
    now = datetime.now(timezone.utc)
    future = choose_epoch(args.epoch, now)
    old = validate_manifest(OLD_FOLDER)
    next_manifest = validate_manifest(NEXT_FOLDER)
    archived = validate_research(json.loads(DATA.read_text(encoding="utf-8")))
    validate_archive(archived, old, next_manifest, OLD_FOLDER, NEXT_FOLDER)
    plan = plan_frozen_subset(old, future, now)
    print("P8.2 READ-ONLY PLAN PREVIEW | No RPC, no writes, no scheduler")
    print("Archived 928 pool identities verified across 38 separate historical groups.")
    print("FROZEN INVENTORY: pinned Base block 52,595,092; current active status UNKNOWN.")
    print("Target epoch UTC:", plan["epoch_utc"])
    print("Separate proposed path:", plan["target_preview_only"])
    print("Frozen cohort:", plan["total_pools"], "pool identities in",
          plan["total_batches"], "groups; up to", plan["max_pools_per_batch"], "per group")
    print("Target path already exists:", plan["existing_target"])
    print("NO collection plan files were created. This preview is NOT live-capable.")
    print("REQUIRED BEFORE LIVE: recheck current Voter registry/gauge activity;")
    print("publish new period inputs in a separate versioned path with explicit user opt-in;")
    print("validate fresh epoch guards, RPC budgets, quote timestamps and saved prices;")
    print("build isolated multi-cohort API/UI before any 8766 data promotion.")
    print("8765 hourly task, existing 8766 research data and old P2 batches unchanged.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print("P8.2 PREVIEW BLOCKED:", exc, file=sys.stderr)
        sys.exit(1)
