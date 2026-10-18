"""Read existing P4 block observations for P9. No RPC or source writes."""
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from serve_pool_research import rolling_vote_detail

ROOT = Path(__file__).resolve().parents[1]
VOTES = ROOT / "data/p4_rolling_votes_base/snapshot.json"
INVENTORY = ROOT / "data/pool_discovery_active_base.json"
VOTER = "0x16613524e02ad97edfef371bc883f2f5d6c480a5"

def uint256(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,78}", value) or int(value) >= 2**256:
        raise ValueError("Invalid vote uint256")
    return int(value)

def utc_stamp(value):
    if not isinstance(value, str):
        raise ValueError("Missing vote timestamp")
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None or stamp.utcoffset() != timezone.utc.utcoffset(stamp):
        raise ValueError("Vote timestamp must use UTC")
    return stamp

def validate_vote_sources(votes, inventory, research, source_sha256):
    if (inventory.get("chain_id") != 8453 or inventory.get("complete") is not True or
        inventory.get("active_pool_count") != 928 or inventory.get("snapshot_block_number") != 52595092 or
        str(inventory.get("voter", "")).lower() != VOTER or votes.get("schema_version") != 1):
        raise ValueError("Unexpected original P4 inventory")
    fingerprint = hashlib.sha256(json.dumps(inventory,sort_keys=True,separators=(",",":"),ensure_ascii=True).encode()).hexdigest()
    if votes.get("source_inventory_sha256") != fingerprint or votes.get("source_inventory_block_number") != 52595092:
        raise ValueError("P4 inventory fingerprint mismatch")
    rows = inventory.get("pools")
    if not isinstance(rows,list) or len(rows)!=928 or len({r.get("index") for r in rows})!=928:
        raise ValueError("Invalid original vote pool set")
    original = {"pools":[{"index":p["index"],"address":p["pool_address"]} for p in rows]}
    # Reuse the existing complete-cohort identity/range validation and Decimal math.
    rolling_vote_detail(votes, original, rows[0]["index"])
    current = {p["index"]:p for p in research["pools"]}
    if len(current)!=950 or research.get("chain_id")!=8453:
        raise ValueError("Expected validated P9 research")
    matched = set()
    pages_by_pool = {}
    utc_stamp(votes.get("published_at_utc"))
    for page in votes["pages"]:
        total = uint256(page["total_voting_weight_raw"])
        stamp = utc_stamp(page["block_timestamp_utc"])
        collected = utc_stamp(page["collected_at_utc"])
        if collected < stamp:
            raise ValueError("Vote collection predates its block")
        for row in page["pools"]:
            index = row["index"]
            pool = current.get(index)
            if (pool is None or row["pool_address"].lower()!=pool["address"].lower() or
                type(page["block_number"]) is not int or not 52595092 <= page["block_number"] < pool["inventory_snapshot_block"] or
                uint256(row["weight_raw"])>total):
                raise ValueError("P4 observation does not match P9 pool or chronology")
            matched.add(index)
            pages_by_pool[index]=page
    return {"votes":votes,"original":original,"covered":matched,"pages":pages_by_pool,"sha256":source_sha256}

def load_vote_sources(research):
    raw=VOTES.read_bytes()
    return validate_vote_sources(json.loads(raw),json.loads(INVENTORY.read_bytes()),research,hashlib.sha256(raw).hexdigest())

def vote_detail_950(pool,context):
    common={"index":pool["index"],"address":pool["address"],"covered_pools":len(context["covered"]),
            "missing_pools":950-len(context["covered"]),"source_snapshot_sha256":context["sha256"],
            "source_inventory_block_number":52595092,"synchronized_with_reward_epochs":False,
            "is_weekly_vote_history":False}
    if pool["index"] not in context["covered"]:
        return {**common,"available":False,"reason":"No saved P4 block observation for this pool","vote_weight_raw":None}
    result=rolling_vote_detail(context["votes"],context["original"],pool["index"])
    page=context["pages"][pool["index"]]
    return {**common,**result,"available":True,"block_hash":page["block_hash"],
            "collected_at_utc":page["collected_at_utc"],"published_at_utc":context["votes"]["published_at_utc"]}
