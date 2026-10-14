#!/usr/bin/env python3
"""Run a few opt-in P2 FEES/BRIBES/USD audit batches without touching the dashboard.

This is not a continuous/hidden scheduler. It runs at most 5 sequential
25-pool batches per invocation, with per-batch staging, validation and
a resume marker. It refuses to combine reward data from different epochs.
"""
import argparse
import fcntl
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from audit_pool_rewards_base import audit, read_time
from plan_pool_collection_base import save_atomic

ROOT = Path(__file__).resolve().parents[1]
BATCH_ROOT = ROOT / "data" / "pool_collection_batches_base"
PREFIX = "block_52595092/votes_25"
MAX_BATCHES_PER_CALL = 5


def read_json(path):
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def paths_for(folder, number):
    suffix = f"{number:03d}"
    return {
        "input": folder / f"batch_{suffix}.json",
        "fees": folder / f"fee_histories_batch_{suffix}.json",
        "incentives": folder / f"incentives_batch_{suffix}.json",
        "audit": folder / f"audit_batch_{suffix}.json",
        "status": folder / f"batch_{suffix}_status.json",
        "staging": folder / ".pipeline_staging" / f"batch_{suffix}",
    }


def validate_manifest(folder):
    manifest = read_json(folder / "manifest.json")
    batches = manifest.get("batches")
    if (manifest.get("chain_id") != 8453 or
            not isinstance(batches, list) or not batches or
            manifest.get("batch_count") != len(batches) or
            manifest.get("all_batches_pool_count") !=
            manifest.get("active_pool_count")):
        raise ValueError("Invalid or inconsistent P2 collection manifest")
    indexes = []
    for i, row in enumerate(batches, 1):
        if row.get("number") != i or not 1 <= row.get("pool_count", 0) <= 50:
            raise ValueError(f"Manifest batch #{i} metadata mismatch")
        expected = paths_for(folder, i)["input"]
        source = read_json(expected)
        ids = [pool.get("index") for pool in source.get("pools", [])]
        if (source.get("chain_id") != 8453 or
                source.get("inventory_sha256") != manifest.get("inventory_sha256") or
                len(ids) != row.get("pool_count") or
                ids != row.get("pool_indexes") or
                len(ids) != len(set(ids))):
            raise ValueError(f"Manifest batch #{i} input/identities mismatch")
        indexes.extend(ids)
    if len(indexes) != len(set(indexes)):
        raise ValueError("Duplicate pool index across separate batch inputs")
    return manifest


def reference_epoch(folder):
    """Anchor new batches to the already completed first P2 batch."""
    prior = paths_for(folder, 1)
    if not all(prior[key].is_file() for key in ("fees", "incentives", "audit")):
        raise RuntimeError("First batch FEES, BRIBES and audit must be present before continuation")
    f = read_json(prior["fees"])
    inc = read_json(prior["incentives"])
    report = read_json(prior["audit"])
    epoch = f.get("current_epoch_start_utc")
    if (not isinstance(epoch, str) or epoch != inc.get("current_epoch_utc") or
            epoch != report.get("source_epoch_utc") or report.get("pool_count", 0) < 1):
        raise ValueError("First batch epoch or audit data mismatch")
    read_time(epoch, "anchor epoch")
    return epoch


def publish_batch(files, folder, expected_count, anchor_epoch):
    staged = files["staging"]
    fees, incentives = read_json(staged / "fees.json"), read_json(staged / "incentives.json")
    if fees.get("current_epoch_start_utc") != anchor_epoch:
        raise RuntimeError("Base voting epoch rolled over during collection; refusing mixed-epoch publish")
    if incentives.get("current_epoch_utc") != anchor_epoch:
        raise RuntimeError("BRIBES epoch does not match the first batch")
    all_items = fees.get("pools")
    if not isinstance(all_items, list) or len(all_items) != expected_count:
        raise ValueError("Collected FEES pool count does not match planned batch")
    original = read_json(files["input"])
    for received, planned in zip(all_items, original["pools"]):
        if (received.get("index") != planned["index"] or
                received.get("pool_address", "").lower() != planned["pool_address"].lower()):
            raise ValueError("FEES collection pool order/identity does not match batch manifest")
    report = audit(fees, incentives)
    if report["pool_count"] < 1 or report["pool_count"] > expected_count:
        raise ValueError("Unexpected active pool count in offline audit")
    # Verify output from standalone audit CLI matches independent in-process check.
    generated = read_json(staged / files["audit"].name)
    if (generated.get("pool_count") != report["pool_count"] or
            generated.get("audited_complete_usd_count") !=
            report["audited_complete_usd_count"]):
        raise RuntimeError("Staged audit and verified audit disagree")
    # Published per-component files are separate; the status marker is LAST.
    for name, target in (
        ("fees.json", files["fees"]),
        ("incentives.json", files["incentives"]),
        (files["audit"].name, files["audit"]),
    ):
        save_atomic(target, read_json(staged / name))
    status = {
        "state": "complete",
        "batch_number": int(files["input"].stem.split("_")[-1]),
        "epoch_utc": anchor_epoch,
        "expected_pools": expected_count,
        "audited_active_pools": report["pool_count"],
        "fully_priced_pools": report["audited_complete_usd_count"],
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "note": "Independent P2 batch; no dashboard or hourly-task promotion.",
    }
    save_atomic(files["status"], status)
    return status


def already_done(files, expected_count, anchor_epoch):
    if not files["status"].is_file():
        return False
    status = read_json(files["status"])
    if (status.get("state") != "complete" or
            status.get("epoch_utc") != anchor_epoch or
            status.get("expected_pools") != expected_count):
        raise RuntimeError("Existing batch status conflicts with pinned epoch or pool count")
    if not all(files[k].is_file() for k in ("fees", "incentives", "audit")):
        raise RuntimeError("Marked-complete batch has missing component files")
    if (read_json(files["fees"]).get("current_epoch_start_utc") != anchor_epoch or
            read_json(files["incentives"]).get("current_epoch_utc") != anchor_epoch or
            read_json(files["audit"]).get("pool_count") !=
            status.get("audited_active_pools")):
        raise RuntimeError("Completed batch component mismatch; refusing to skip")
    return True


def cli_call(label, argv, attempts=2, backoff=10):
    for attempt in range(1, attempts + 1):
        print(f"{label} | attempt {attempt}/{attempts}", flush=True)
        result = subprocess.run([sys.executable, *argv], cwd=ROOT, check=False)
        if result.returncode == 0:
            return
        if attempt == attempts:
            raise RuntimeError(
                f"{label} failed after {attempts} attempts (exit {result.returncode}); "
                "prior completed batches retained."
            )
        print(f"Transient failure possible; waiting {backoff}s before retry", flush=True)
        time.sleep(backoff)


def process_one(folder, number, anchor_epoch, weeks=4):
    files = paths_for(folder, number)
    source = read_json(files["input"])
    count = len(source["pools"])
    if already_done(files, count, anchor_epoch):
        print(f"Batch {number:03d}: already complete; skipping", flush=True)
        return
    staged = files["staging"]
    staged.mkdir(parents=True, exist_ok=True)
    fee_tmp = staged / "fees.json"
    incentive_tmp = staged / "incentives.json"
    # Audit CLI requires output basename beginning with audit_.
    audit_tmp = staged / files["audit"].name
    staged_complete = fee_tmp.is_file() and incentive_tmp.is_file()
    if staged_complete:
        fees, incentives = read_json(fee_tmp), read_json(incentive_tmp)
        if (fees.get("current_epoch_start_utc") != anchor_epoch or
                incentives.get("current_epoch_utc") != anchor_epoch):
            raise RuntimeError(
                f"Batch {number:03d}: saved staging epoch differs from first batch; "
                "refusing to discard or mix existing data."
            )
        collected = fees.get("pools")
        if not isinstance(collected, list) or len(collected) != count:
            raise RuntimeError("Saved staged FEES pool count differs from batch input")
        for got, planned in zip(collected, source["pools"]):
            if (got.get("index") != planned.get("index") or
                    got.get("pool_address", "").lower() !=
                    planned.get("pool_address", "").lower()):
                raise RuntimeError("Saved staged FEES identities differ from batch input")
        # Re-validate saved quotes at current time rather than silently trust
        # a previous CLI success; never fall back to zero for expired quotes.
        audit(fees, incentives)
        print(
            f"Batch {number:03d}: reusing validated saved FEES + BRIBES data; "
            "no new RPC or price download for this batch", flush=True,
        )
    else:
        print(f"Batch {number:03d}: collecting FEES for {count} planned pools", flush=True)
        cli_call(
            f"Batch {number:03d} FEES",
            ["scripts/pool_fee_histories_base.py", "--scan-file", str(files["input"]),
             "--output-file", str(fee_tmp), "--weeks", str(weeks),
             "--max-pools", str(count), "--max-tokens", "4"],
        )
        # Stop BEFORE querying BRIBES if a new Thursday epoch has started.
        if read_json(fee_tmp).get("current_epoch_start_utc") != anchor_epoch:
            raise RuntimeError(
                "Epoch has changed since first batch; stop to avoid mixing snapshots. "
                "Completed prior batches are kept unchanged."
            )
        print(f"Batch {number:03d}: collecting BRIBES and saved-current-price USD", flush=True)
        cli_call(
            f"Batch {number:03d} BRIBES",
            ["scripts/collect_pool_incentives_base.py", "--input-file", str(fee_tmp),
             "--output-file", str(incentive_tmp), "--max-bribe-tokens", "40"],
        )
    cli_call(
        f"Batch {number:03d} AUDIT",
        ["scripts/audit_pool_rewards_base.py", "--fees", str(fee_tmp),
         "--incentives", str(incentive_tmp), "--output", str(audit_tmp)],
        attempts=1,
    )
    status = publish_batch(files, folder, count, anchor_epoch)
    print(
        f"COMPLETED batch {number:03d}: {status['audited_active_pools']}/{count} "
        f"active; USD complete {status['fully_priced_pools']}/"
        f"{status['audited_active_pools']}", flush=True,
    )


def run(folder, start=2, max_batches=1, cooldown=10, dry_run=False):
    folder = folder.resolve()
    if not folder.is_relative_to(BATCH_ROOT.resolve()):
        raise ValueError("Batch folder must be under data/pool_collection_batches_base")
    manifest = validate_manifest(folder)
    anchor = reference_epoch(folder)
    last = min(start + max_batches - 1, manifest["batch_count"])
    if start < 2 or start > manifest["batch_count"]:
        raise ValueError("Start batch must be 2 through the last batch")
    if not 1 <= max_batches <= MAX_BATCHES_PER_CALL:
        raise ValueError("Run 1-5 batches per call (explicitly bounded)")
    if not 0 <= cooldown <= 120:
        raise ValueError("Cooldown must be 0-120 seconds")
    print(
        f"P2 isolated batch pipeline | Base block {manifest['snapshot_block_number']} | "
        f"epoch {anchor} | batches {start}-{last} of {manifest['batch_count']}",
        flush=True,
    )
    if dry_run:
        print("DRY RUN only: no RPC or file mutations", flush=True)
        return
    with (folder / ".batch_pipeline.lock").open("a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Another P2 batch pipeline is running") from None
        for number in range(start, last + 1):
            process_one(folder, number, anchor)
            if number < last and cooldown:
                print(f"Waiting {cooldown}s before next batch", flush=True)
                time.sleep(cooldown)
    print("Selected batch range finished. Existing dashboard was not modified.", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", type=Path, default=BATCH_ROOT / PREFIX)
    parser.add_argument("--start-batch", type=int, default=2)
    parser.add_argument("--max-batches", type=int, default=1)
    parser.add_argument("--cooldown", type=float, default=10)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(args.folder, args.start_batch, args.max_batches, args.cooldown, args.dry_run)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"PIPELINE PAUSED: {exc}", file=sys.stderr, flush=True)
        sys.exit(1)
    except KeyboardInterrupt:
        print(
            "\nPIPELINE PAUSED BY USER. Completed batches are preserved. "
            "Rerun the same command to resume.",
            file=sys.stderr, flush=True,
        )
        sys.exit(130)
