"""Audit all saved P9 pools and optionally save a report outside data/."""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from p9_validation import FOLDER, ROOT, load_snapshot
from p9_weekly_950 import weekly_breakdown_950


def audit():
    docs, summary = load_snapshot()
    cache = {}
    def read(path):
        if path not in cache:
            cache[path] = json.loads(path.read_text(encoding="utf-8"))
        return cache[path]
    examples = {}
    unavailable = 0
    for pool in docs[0]["pools"]:
        weekly = weekly_breakdown_950(pool, FOLDER, read)
        unavailable += weekly["trend"]["status"] != "available"
        if pool["index"] in (64, 35):
            examples[str(pool["index"])] = {k: weekly["trend"][k] for k in (
                "fees_four_week_usd", "bribes_four_week_usd", "total_four_week_usd", "fees_share_percent", "bribes_share_percent")}
    if unavailable != 46:
        raise ValueError("Weekly USD availability differs from audited coverage")
    return {**summary, "audited_weekly_pools": 950, "weekly_usd_unavailable": unavailable,
            "examples": examples, "source_files_read": len(cache),
            "source_sha256": {str(path.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(path.read_bytes()).hexdigest() for path in cache},
            "checked_at_utc": datetime.now(timezone.utc).isoformat(), "network_calls": 0}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    result = audit()
    if args.report:
        target = args.report.resolve()
        if target.is_relative_to((ROOT / "data").resolve()):
            parser.error("Audit report must not be written into historical data/")
        target.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k not in ("source_sha256", "examples")}, ensure_ascii=False))
