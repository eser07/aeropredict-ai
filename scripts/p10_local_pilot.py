"""Offline P10 pilot: deterministic baseline and local evidence checks, no network."""
import hashlib
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "data/pool_collection_batches_base/p9_unified_research/block_52731839/registration_25"

def canonical_hash(doc):
    return hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

def evaluate(forecast, evidence, now):
    """Local adapter simulation only; never claim GenLayer validator consensus."""
    if canonical_hash(forecast["commitment"]) != forecast["commitment_sha256"]:
        return {"status": "unverifiable", "reason": "commitment_mismatch"}
    c = forecast["commitment"]
    start = datetime.fromisoformat(c["target_start_utc"])
    end = datetime.fromisoformat(c["target_end_utc"])
    if datetime.fromisoformat(c["created_at_utc"]) >= start:
        return {"status": "unverifiable", "reason": "late_registration"}
    if now < end:
        return {"status": "pending", "reason": "epoch_not_completed"}
    if not evidence:
        return {"status": "insufficient_data", "reason": "no_completed_epoch_evidence"}
    for key in ("chain_id", "pool_address", "token_address", "target_start_utc"):
        if evidence.get(key) != c[key]:
            return {"status": "unverifiable", "reason": "identity_mismatch"}
    # The adapter accepts injected evidence. It is not an independent RPC attestation.
    raw = evidence.get("actual_raw")
    if not isinstance(raw, str) or not raw.isdecimal():
        return {"status": "insufficient_data", "reason": "missing_raw_amount"}
    predicted = int(c["predicted_raw"])
    actual = int(raw)
    matched = abs(actual-predicted)*100 <= max(predicted,1)*c["tolerance_percent"]
    return {"status": "locally_evaluated", "forecast_matched": matched,
            "actual_raw": raw, "genlayer_consensus": False}

def build_pilot(now=None):
    now = now or datetime.now(timezone.utc)
    doc=json.loads((FOLDER/"research_all_950_one_epoch.json").read_text())
    rows={r["index"]:r for r in doc["pools"]}
    # Next Thursday strictly after registration, with a full future epoch.
    epoch=datetime(1970,1,1,tzinfo=timezone.utc)
    target=epoch+timedelta(seconds=(int((now-epoch).total_seconds())//604800+1)*604800)
    forecasts=[]
    for index in (64,35,0,1,4):
        pool=rows[index]
        path=FOLDER/f"incentives_batch_{pool['batch_number']:03d}.json"
        batch=json.loads(path.read_text())
        row=next(r for r in batch["pools"] if r["index"]==index)
        candidates=[t for t in row["fees"] if any(int(w["raw"])>0 for w in t["last_four_weeks"])]
        token=(candidates or row["fees"])[0]
        c={"chain_id":8453,"pool_index":index,"pool_address":pool["address"],
           "token_address":token["token_address"],"reward_category":"FEES",
           "predicted_raw":str(sum(int(w["raw"]) for w in token["last_four_weeks"])//4),
           "created_at_utc":now.isoformat(),"target_start_utc":target.isoformat(),
           "target_end_utc":(target+timedelta(days=7)).isoformat(),"tolerance_percent":20,
           "model":"four_week_mean_raw_v1 (deterministic baseline, not an LLM)",
           "source_file":str(path.relative_to(ROOT)),"source_sha256":hashlib.sha256(path.read_bytes()).hexdigest(),
           "settlement_rule":"Compare same pool/token FEES raw amount at first Base block after target end; pin block hash and parent boundary; independent GenLayer adapter still required"}
        forecasts.append({"commitment":c,"commitment_sha256":canonical_hash(c),"status":"pending",
                          "registration":"local_file_only; not externally timestamped", "genlayer_consensus":False})
    return {"mode":"offline_prototype","forecasts":forecasts,"paid_transactions":0}

if __name__ == "__main__":
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument("--output",required=True);args=parser.parse_args()
    # Exclusive creation preserves earlier forecast registrations.
    with open(args.output,"x",encoding="utf-8") as stream:json.dump(build_pilot(),stream,indent=2)
