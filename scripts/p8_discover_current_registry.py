#!/usr/bin/env python3
"""P8.4: isolated, bounded, resumable Base Voter registry discovery.

Default is offline preview. --live explicitly scans 1-25 registration
indexes per page and 1-3 pages per invocation, at ONE pinned Base block
for the whole scan. Only a COMPLETE scan establishes an active-gauge count.
Do not touch the old P2 inventory, old discovery checkpoint or dashboards.
"""
import argparse
import json
import sys
from pathlib import Path
from unittest.mock import patch

import discover_active_pools_base as discovery
from run_pool_batch_pipeline import BATCH_ROOT
from p8_collection_preflight import EXPECTED_BLOCK

FOLDER = BATCH_ROOT / "p8_registry_discovery"
CHECKPOINT = FOLDER / "checkpoint.json"
RESULT = FOLDER / "active_pools.json"
DEFAULT_PAGE_SIZE = 10
MAX_PAGE_SIZE = 25
MAX_PAGES_PER_CALL = 3


def bounds(page_size, max_pages):
    if type(page_size) is not int or not 1 <= page_size <= MAX_PAGE_SIZE:
        raise ValueError("Page size must be 1–25 registration indexes")
    if type(max_pages) is not int or not 1 <= max_pages <= MAX_PAGES_PER_CALL:
        raise ValueError("Maximum pages per invocation must be 1–3")
    return page_size * max_pages


def local_progress():
    """Read P8.4 state only; never use legacy discovery checkpoint files."""
    if not CHECKPOINT.is_file():
        if RESULT.exists():
            raise RuntimeError("Isolated result exists without checkpoint; manual inspection needed")
        return None
    data = json.loads(CHECKPOINT.read_text(encoding="utf-8"))
    discovery.validate_progress(data)
    if data["snapshot_block_number"] <= EXPECTED_BLOCK:
        raise ValueError("New P8.4 scan block is not newer than the old inventory")
    if RESULT.is_file():
        done = json.loads(RESULT.read_text(encoding="utf-8"))
        discovery.validate_progress(done)
        if (not done.get("complete") or
                done.get("snapshot_block_number") != data["snapshot_block_number"] or
                done.get("next_index") != data["next_index"] or
                done.get("active_pool_count") != data["active_pool_count"] or
                done.get("coverage_percent") != 100):
            raise RuntimeError("Isolated published result conflicts with its checkpoint")
    return data


def preview(page_size, max_pages):
    upper = bounds(page_size, max_pages)
    state = local_progress()
    print("P8.4 ISOLATED DISCOVERY PREVIEW | OFFLINE ONLY; no RPC and no writes")
    print("Proposed P8-only folder:", FOLDER)
    print("Bounded per invocation:", max_pages, "page(s) ×",
          page_size, "indexes =", upper, "maximum index reads")
    if state is None:
        print("State: NOT STARTED. First --live call pins a NEW Base block.")
    else:
        print("State:", "COMPLETE" if state["complete"] else "PARTIAL",
              "| pinned Base block:", state["snapshot_block_number"],
              "| inspected:", state["next_index"], "of", state["total_registered"],
              "| active gauges found:", state["active_pool_count"])
        if not state["complete"]:
            print("Remaining pages MUST use that same block; archive RPC may be required.")
    print("Only a fully scanned snapshot can provide the total active-gauge count.")
    print("An isolated scan will not replace the 928 historical research inventory.")
    print("8765/8766, Windows hourly task and old discovery files are unchanged.")


def run_live(page_size, max_pages):
    bounds(page_size, max_pages)
    local_progress()
    # Reuse the existing tested pinned-block, per-page atomic collector while
    # swapping ONLY its output paths. This is not an edit to its legacy files.
    with patch.multiple(
        discovery, DATA=FOLDER, CHECKPOINT=CHECKPOINT, RESULT=RESULT,
    ):
        state = discovery.run_scan(
            page_size=page_size, max_pages=max_pages, delay=0.1,
            restart=False, until_complete=False,
            retry_attempts=2, retry_delay=2.0,
        )
    if state["snapshot_block_number"] <= EXPECTED_BLOCK:
        raise RuntimeError("P8.4 snapshot block is not newer than old inventory")
    print("P8.4 snapshot block:", state["snapshot_block_number"])
    print("Inspected:", state["next_index"], "/", state["total_registered"],
          "| gauges alive at pinned block:", state["active_pool_count"])
    if state["complete"]:
        print("COMPLETE active-gauge count:", state["active_pool_count"],
              "| archived result:", RESULT)
    else:
        print("PARTIAL: active count is incomplete, NOT a claim about all registered pools.")
    print("Saved ONLY in P8.4 isolated folder. No 8765/8766 promotion or live APR.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true",
                        help="Opt in to a bounded read-only RPC scan with isolated checkpoints")
    parser.add_argument("--page-size", type=int, default=DEFAULT_PAGE_SIZE,
                        help="Registry indexes per page, from 1 to 25 (default 10)")
    parser.add_argument("--max-pages", type=int, default=1,
                        help="Pages per invocation, from 1 to 3 (default 1)")
    args = parser.parse_args(argv)
    bounds(args.page_size, args.max_pages)
    if args.live:
        run_live(args.page_size, args.max_pages)
    else:
        preview(args.page_size, args.max_pages)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError, TypeError,
            json.JSONDecodeError) as exc:
        print("P8.4 DISCOVERY PAUSED:", exc, file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("P8.4 PAUSED: completed pages remain in the isolated checkpoint.",
              file=sys.stderr)
        sys.exit(130)
