#!/usr/bin/env python3
"""Create a NEW, isolated next-week Aerodrome collection plan for pending batches.

Offline only. Does not overwrite already published FEES, BRIBES, audits, or
the 16-pool dashboard. The older pinned-block pool *selection* is reused,
but historical voting weights are never represented as new snapshots.
"""
import argparse
import fcntl
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from audit_pool_rewards_base import read_time
from plan_pool_collection_base import save_atomic
from run_pool_batch_pipeline import (
    BATCH_ROOT, PREFIX, paths_for, read_json, reference_epoch, validate_manifest,
)

WEEK = timedelta(days=7)


def utc_week(date_text):
    try:
        day = datetime.strptime(date_text, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError) as exc:
        raise ValueError("--next-epoch must be YYYY-MM-DD (Thursday UTC)") from exc
    if day.weekday() != 3:
        raise ValueError("--next-epoch must be a Thursday UTC")
    return day


def verify_published_prior(folder, manifest, through):
    if type(through) is not int or through < 1 or through >= manifest["batch_count"]:
        raise ValueError("--through-batch must be between 1 and batch_count - 1")
    epoch = reference_epoch(folder, manifest)
    first = paths_for(folder, 1)
    report = read_json(first["audit"])
    first_fees = read_json(first["fees"])
    if (report.get("pool_count") != manifest["batches"][0]["pool_count"] or
            len(first_fees.get("pools", [])) != manifest["batches"][0]["pool_count"]):
        raise ValueError("Batch 001 source collection does not match planned pool count")
    usd_total = report.get("audited_complete_usd_count")
    if type(usd_total) is not int or not 0 <= usd_total <= report["pool_count"]:
        raise ValueError("Invalid batch 001 complete-USD count")
    active_total = report["pool_count"]
    for number in range(2, through + 1):
        files = paths_for(folder, number)
        if not all(files[key].is_file() for key in ("status", "fees", "incentives", "audit")):
            raise RuntimeError(f"Prior batch {number:03d} is not fully published; stop")
        status = read_json(files["status"])
        audit = read_json(files["audit"])
        fees = read_json(files["fees"])
        incentives = read_json(files["incentives"])
        planned_count = manifest["batches"][number - 1]["pool_count"]
        if (status.get("state") != "complete" or
                status.get("batch_number") != number or
                status.get("expected_pools") != planned_count or
                status.get("epoch_utc") != epoch or
                fees.get("current_epoch_start_utc") != epoch or
                incentives.get("current_epoch_utc") != epoch or
                audit.get("source_epoch_utc") != epoch or
                audit.get("pool_count") != status.get("audited_active_pools") or
                audit.get("audited_complete_usd_count") != status.get("fully_priced_pools") or
                len(fees.get("pools", [])) != planned_count):
            raise ValueError(f"Published prior batch {number:03d} does not match epoch/count")
        active_total += status["audited_active_pools"]
        usd_total += status["fully_priced_pools"]
    return {
        "previous_epoch_utc": epoch,
        "prior_completed_batches": through,
        "prior_audited_pools": active_total,
        "prior_fully_priced_pools": usd_total,
    }


def prepare(source_folder, through, next_epoch):
    source_folder = Path(source_folder).resolve()
    base = BATCH_ROOT.resolve()
    if not source_folder.is_relative_to(base):
        raise ValueError("Source must be inside the P2 batch data folder")
    manifest = validate_manifest(source_folder)
    previous = verify_published_prior(source_folder, manifest, through)
    requested = utc_week(next_epoch)
    original = read_time(previous["previous_epoch_utc"], "prior collection epoch")
    if requested != original + WEEK:
        raise ValueError(
            "New collection epoch must be exactly one Thursday after the prior epoch"
        )
    # A pinned target epoch prevents the new runner from mixing newer chain data.
    epoch_text = requested.isoformat()
    parent = source_folder / "epochs"
    destination = parent / next_epoch
    parent.mkdir(parents=True, exist_ok=True)
    with (parent / ".prepare_next_epoch.lock").open("a+") as guard:
        try:
            fcntl.flock(guard.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Another next-epoch preparation is running") from None
        if destination.exists():
            old_plan = validate_manifest(destination)
            if (old_plan.get("collection_epoch_utc") != epoch_text or
                    old_plan.get("inventory_sha256") != manifest["inventory_sha256"] or
                    old_plan.get("carry_forward_completed_through") != through or
                    old_plan.get("prior_collection_epoch_utc") !=
                    previous["previous_epoch_utc"]):
                raise RuntimeError("Existing next-epoch plan differs; refusing overwrite")
            print(f"Already prepared, untouched: {destination}", flush=True)
            return destination, old_plan, previous
        with tempfile.TemporaryDirectory(prefix=".pending_", dir=parent) as temp:
            stage = Path(temp)
            new_manifest = dict(manifest)
            new_manifest["type"] = "P2 separate next-epoch collection for remaining batch numbers"
            new_manifest["collection_epoch_utc"] = epoch_text
            new_manifest["prior_collection_epoch_utc"] = previous["previous_epoch_utc"]
            new_manifest["carry_forward_completed_through"] = through
            new_manifest["new_epoch_collection_start_batch"] = through + 1
            new_manifest["prior_collection_summary"] = previous
            new_manifest["selection_warning"] = (
                "Existing pinned-block pool order and vote weights reused as identifiers/"
                "coverage heuristic, NOT a fresh current-week vote snapshot or APR."
            )
            new_manifest["batches"] = []
            for number in range(1, manifest["batch_count"] + 1):
                input_name = f"batch_{number:03d}.json"
                original_file = read_json(source_folder / input_name)
                if (original_file.get("inventory_sha256") != manifest["inventory_sha256"] or
                        original_file.get("batch_number") != number or
                        original_file.get("chain_id") != 8453):
                    raise ValueError(f"Input batch {number:03d} failed integrity check")
                save_atomic(stage / input_name, original_file)
                old_row = manifest["batches"][number - 1]
                new_row = dict(old_row)
                new_row["file"] = str(destination / input_name)
                new_manifest["batches"].append(new_row)
            save_atomic(stage / "manifest.json", new_manifest)
            if validate_manifest(stage).get("collection_epoch_utc") != epoch_text:
                raise RuntimeError("Staged plan validation failed")
            if destination.exists():
                raise RuntimeError("Next-epoch destination appeared during preparation")
            os.rename(stage, destination)
    print(
        f"PREPARED next epoch: {epoch_text} | "
        f"previous {previous['prior_completed_batches']} batches "
        f"({previous['prior_audited_pools']} audited, "
        f"{previous['prior_fully_priced_pools']} USD complete) protected",
        flush=True,
    )
    print(
        f"Remaining: batches {through + 1}-{manifest['batch_count']} "
        f"({sum(x['pool_count'] for x in manifest['batches'][through:])} "
        "pinned-inventory entries); new outputs will stay in a separate folder",
        flush=True,
    )
    print(f"New collection folder: {destination}", flush=True)
    print("No RPC, prices, wallet, dashboard, or hourly jobs were touched.", flush=True)
    return destination, new_manifest, previous


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-folder", type=Path, default=BATCH_ROOT / PREFIX,
    )
    parser.add_argument("--through-batch", type=int, default=15)
    parser.add_argument("--next-epoch", default="2026-10-15")
    args = parser.parse_args()
    prepare(args.source_folder, args.through_batch, args.next_epoch)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"PREPARATION STOPPED: {exc}", file=sys.stderr, flush=True)
        sys.exit(1)
