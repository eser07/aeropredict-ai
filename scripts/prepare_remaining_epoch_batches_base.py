#!/usr/bin/env python3
"""Offline prepare a NEW epoch-only plan for uncollected P2 pool batches.

Never mutate the already collected prior-epoch 15 batches. This reuses
the original pinned-block pool inventory only as a registration snapshot.
No Base RPC, token price fetch or dashboard/task change.
"""
import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from plan_pool_collection_base import save_atomic
from run_pool_batch_pipeline import (
    BATCH_ROOT, PREFIX, paths_for, read_json, validate_manifest, reference_epoch,
)

DEFAULT_SOURCE = BATCH_ROOT / PREFIX
WEEK = timedelta(days=7)


def epoch_start(now):
    if now.tzinfo is None:
        raise ValueError("Current time must include timezone")
    utc = now.astimezone(timezone.utc)
    anchor = utc - timedelta(
        days=(utc.weekday() - 3) % 7,
        hours=utc.hour,
        minutes=utc.minute,
        seconds=utc.second,
        microseconds=utc.microsecond,
    )
    return anchor


def check_previous(folder, manifest, completed_through):
    if not 1 <= completed_through < manifest["batch_count"]:
        raise ValueError("Completed-through must be 1 to one less than all batches")
    epoch = reference_epoch(folder, manifest)
    old_idxs = []
    audited = 0
    complete_usd = 0
    incomplete = []
    for number in range(1, completed_through + 1):
        files = paths_for(folder, number)
        expected_ids = manifest["batches"][number - 1]["pool_indexes"]
        old_idxs.extend(expected_ids)
        if not all(files[key].is_file() for key in ("fees", "incentives", "audit")):
            raise RuntimeError(f"Batch {number:03d} not fully saved; refusing to skip")
        fees = read_json(files["fees"])
        incentives = read_json(files["incentives"])
        report = read_json(files["audit"])
        if (fees.get("current_epoch_start_utc") != epoch or
                incentives.get("current_epoch_utc") != epoch or
                report.get("source_epoch_utc") != epoch):
            raise RuntimeError(f"Batch {number:03d} does not match original epoch")
        details = report.get("four_week_usd_totals_by_pool")
        if not isinstance(details, list) or report.get("pool_count") != len(details):
            raise RuntimeError(f"Batch {number:03d} audit details are incomplete")
        report_ids = [p.get("index") for p in details]
        if len(set(report_ids)) != len(report_ids) or not set(report_ids).issubset(expected_ids):
            raise RuntimeError(f"Batch {number:03d} audit pool IDs mismatch source manifest")
        if report.get("pool_count") != len(expected_ids):
            raise RuntimeError(
                f"Batch {number:03d} was not fully audited; need a separate "
                "recovery plan for skipped/inactive pools"
            )
        if number > 1:
            if not files["status"].is_file():
                raise RuntimeError(f"Batch {number:03d} missing completed status")
            status = read_json(files["status"])
            if (status.get("state") != "complete" or
                    status.get("epoch_utc") != epoch or
                    status.get("audited_active_pools") != report["pool_count"] or
                    status.get("fully_priced_pools") != report.get("audited_complete_usd_count") or
                    status.get("expected_pools") != len(expected_ids)):
                raise RuntimeError(f"Batch {number:03d} status/audit mismatch")
        audited += report["pool_count"]
        counted = sum(p.get("usd_coverage_complete_at_audit") is True for p in details)
        if counted != report.get("audited_complete_usd_count"):
            raise RuntimeError(f"Batch {number:03d} USD completeness totals mismatch")
        complete_usd += counted
        for pool in details:
            if not pool.get("usd_coverage_complete_at_audit"):
                incomplete.append({
                    "batch": number,
                    "pool_index": pool["index"],
                    "truncated_registry": bool(pool.get("truncated_registry")),
                    "missing_components": pool.get("missing_or_stale_components", []),
                })
    return {
        "source_epoch_utc": epoch,
        "previously_planned_pools": len(old_idxs),
        "previous_audited_pools": audited,
        "previous_complete_usd": complete_usd,
        "previous_incomplete_usd": incomplete,
        "previous_source_indices": old_idxs,
    }


def prepare(source, completed_through=15, now=None, dry_run=False):
    if now is None:
        now = datetime.now(timezone.utc)
    source = source.resolve()
    if not source.is_relative_to(BATCH_ROOT.resolve()):
        raise ValueError("Original source must be under isolated P2 batch root")
    if "/epoch_" in str(source):
        raise ValueError("Source must be original inventory, not a prior epoch copy")
    manifest = validate_manifest(source)
    if manifest.get("collection_epoch_utc") is not None:
        raise ValueError("Source is already pinned to another collection epoch")
    prior = check_previous(source, manifest, completed_through)
    target_epoch = epoch_start(now)
    old_epoch = datetime.fromisoformat(prior["source_epoch_utc"])
    if target_epoch <= old_epoch:
        raise ValueError(
            "No new Aerodrome collection epoch yet; do not clone the same epoch"
        )
    selected = manifest["batches"][completed_through:]
    if not selected:
        raise ValueError("No uncollected batches remain")
    for old in selected:
        files = paths_for(source, old["number"])
        if any(files[key].exists() for key in (
                "fees", "incentives", "audit", "status", "staging")):
            raise RuntimeError(
                f"Original batch {old['number']:03d} already has collected or "
                "staged data; refusing to treat it as uncollected"
            )
    target = source / f"epoch_{target_epoch.date().isoformat()}"
    target_manifest = target / "manifest.json"
    new_batches = []
    new_inputs = []
    remaining_indexes = []
    for serial, original in enumerate(selected, 1):
        orig_number = original["number"]
        original_input = read_json(paths_for(source, orig_number)["input"])
        if ([p.get("index") for p in original_input.get("pools", [])] !=
                original["pool_indexes"]):
            raise RuntimeError(f"Source batch {orig_number:03d} input changed")
        cloned = {
            **original_input,
            "batch_number": serial,
            "batch_count": len(selected),
            "original_batch_number": orig_number,
            "collection_epoch_utc": target_epoch.isoformat(),
            "notice": (
                "Previously uncollected registry pools; vote weights are from "
                "the original pinned block, NOT the current reward epoch."
            ),
        }
        filename = f"batch_{serial:03d}.json"
        new_inputs.append((target / filename, cloned))
        new_batches.append({
            **original,
            "number": serial,
            "original_batch_number": orig_number,
            "file": (str((target / filename).relative_to(Path(__file__).resolve().parents[1]))
                     if (target / filename).is_relative_to(Path(__file__).resolve().parents[1])
                     else str(target / filename)),
        })
        remaining_indexes.extend(original["pool_indexes"])
    if (set(remaining_indexes) & set(prior["previous_source_indices"]) or
            len(remaining_indexes) != len(set(remaining_indexes)) or
            len(remaining_indexes) + prior["previously_planned_pools"] !=
            manifest["active_pool_count"]):
        raise RuntimeError("New epoch plan does not partition original pool inventory")
    plan = {
        **manifest,
        "schema_version": 2,
        "type": "P2 remaining pool subset ONLY, collected in separate new epoch",
        "collection_epoch_utc": target_epoch.isoformat(),
        "previous_epoch_utc": prior["source_epoch_utc"],
        "parent_plan_folder": str(source),
        "parent_active_pool_count": manifest["active_pool_count"],
        "parent_completed_through_batch": completed_through,
        "parent_previously_audited_pools": prior["previous_audited_pools"],
        "parent_previously_usd_complete": prior["previous_complete_usd"],
        "active_pool_count": len(remaining_indexes),
        "zero_weight_active_count": sum(
            int(pool["weight_raw"]) == 0
            for _, item in new_inputs for pool in item["pools"]
        ),
        "all_batches_pool_count": len(remaining_indexes),
        "batch_count": len(selected),
        "batches": new_batches,
        "notices": [
            "This new collection uses a later reward epoch than the previous batches.",
            "Old and new four-week reward windows and current USD quotes differ; "
            "do not combine into one comparable profitability ranking.",
            "Voting power in these cloned batch inputs is from the original "
            "pinned Base block, not recomputed for the new epoch.",
            "This plan excludes already collected pools; it does not erase them.",
            "Never feed this plan directly into the existing 16-pool dashboard.",
        ],
    }
    if target_manifest.exists():
        existing = read_json(target_manifest)
        if existing != plan:
            raise RuntimeError("Existing epoch plan differs; refusing to overwrite")
        for output, obj in new_inputs:
            if not output.is_file() or read_json(output) != obj:
                raise RuntimeError("Existing epoch input differs; refusing to overwrite")
        action = "EXISTING VERIFIED"
    elif dry_run:
        action = "DRY RUN"
    else:
        for output, obj in new_inputs:
            if output.exists():
                if read_json(output) != obj:
                    raise RuntimeError("Partially prepared input differs; refusing overwrite")
            else:
                save_atomic(output, obj)
        save_atomic(target_manifest, plan)
        action = "SAVED"
    return {
        "action": action,
        "target_folder": str(target),
        "new_epoch": target_epoch.isoformat(),
        "remaining_groups": len(selected),
        "remaining_pools": len(remaining_indexes),
        "original_audited_pools": prior["previous_audited_pools"],
        "original_usd_complete": prior["previous_complete_usd"],
        "original_incomplete": prior["previous_incomplete_usd"],
        "source_snapshot_block": manifest["snapshot_block_number"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-folder", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--completed-through", type=int, default=15)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    result = prepare(args.source_folder, args.completed_through, dry_run=args.dry_run)
    print(
        f"{result['action']} separate epoch plan: {result['new_epoch']} | "
        f"{result['remaining_groups']} groups | "
        f"{result['remaining_pools']} previously uncollected pools", flush=True,
    )
    print(
        f"Prior epoch: audited {result['original_audited_pools']} | "
        f"USD complete {result['original_usd_complete']} | "
        f"incomplete {len(result['original_incomplete'])}", flush=True,
    )
    for item in result["original_incomplete"]:
        info = ",".join(item["missing_components"]) if item["missing_components"] else "none"
        print(
            f"  Old batch {item['batch']:03d} / pool #{item['pool_index']}: "
            f"truncated={item['truncated_registry']} | missing={info}", flush=True,
        )
    print(f"Target: {result['target_folder']}", flush=True)
    print(
        "Offline only. Original reports, 16-pool dashboard and hourly jobs unchanged. "
        "Do NOT merge old/new epoch revenue rankings.", flush=True,
    )


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        sys.exit(1)
