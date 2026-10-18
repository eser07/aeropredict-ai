"""P10 v2: source-bound five-pool baseline, no wallets or paid transactions."""
import hashlib
import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from p10_local_pilot import build_pilot, FOLDER, ROOT, canonical_hash
WEEK=604800

def validate_commitment(c):
    if not isinstance(c,dict) or c.get("schema_version") != 2 or c.get("chain_id") != 8453:
        raise ValueError("Invalid forecast chain or schema")
    if c.get("reward_category")!="FEES":raise ValueError("Unsupported reward category")
    for key in ("pool_address","gauge_address","fees_contract","token_address"):
        if not re.fullmatch(r"0x[0-9a-f]{40}",c.get(key,"")) or int(c[key][2:],16)==0:
            raise ValueError("Invalid forecast address")
    for key in ("predicted_raw",):
        if not re.fullmatch(r"0|[1-9][0-9]{0,77}",c.get(key,"")) or int(c[key]) >= 2**256:
            raise ValueError("Invalid uint256")
    if type(c.get("tolerance_percent")) is not int or not 0 <= c["tolerance_percent"] <= 100:
        raise ValueError("Invalid tolerance")
    for key in ("source_sha256","fees_source_sha256","verifier_sha256"):
        if not re.fullmatch(r"[0-9a-f]{64}",c.get(key,"")):raise ValueError("Invalid source hash")
    start=datetime.fromisoformat(c["target_start_utc"]);end=datetime.fromisoformat(c["target_end_utc"])
    created=datetime.fromisoformat(c["created_at_utc"])
    if any(t.tzinfo is None for t in (start,end,created)) or start.timestamp()!=int(start.timestamp()) or int(start.timestamp())%WEEK or (end-start).total_seconds()!=WEEK or created>=start:
        raise ValueError("Invalid forecast time window")
    return c

def build_pilot_v2(now=None):
    old=build_pilot(now)
    verifier=ROOT/"contracts/P10ForecastVerifier.py"
    records=[]
    for forecast in old["forecasts"]:
        c=dict(forecast["commitment"])
        source=ROOT/c["source_file"]
        batch=int(source.stem.rsplit("_",1)[1])
        fees_path=FOLDER/f"fee_histories_batch_{batch:03d}.json"
        fees_doc=json.loads(fees_path.read_text(encoding="utf-8"))
        rows=[r for r in fees_doc["pools"] if r["index"]==c["pool_index"]]
        if len(rows)!=1 or rows[0]["pool_address"].lower()!=c["pool_address"].lower() or fees_doc["chain_id"]!=8453:
            raise ValueError("Saved FEES source identity mismatch")
        row=rows[0]
        epoch="2026-10-15T00:00:00+00:00"
        if fees_doc.get("current_epoch_start_utc")!=epoch or fees_doc.get("completed_weeks_requested")!=4:
            raise ValueError("Saved training epoch mismatch")
        incentives=json.loads(source.read_text(encoding="utf-8"))
        if incentives.get("chain_id")!=8453 or incentives.get("current_epoch_utc")!=epoch:
            raise ValueError("Saved incentive epoch mismatch")
        incentive_rows=[r for r in incentives["pools"] if r["index"]==c["pool_index"]]
        if len(incentive_rows)!=1 or incentive_rows[0]["pool_address"].lower()!=c["pool_address"] or incentive_rows[0]["gauge_address"].lower()!=row["gauge_address"].lower():
            raise ValueError("Saved incentive identity mismatch")
        histories=[t for t in row["reward_series"] if t["token_address"].lower()==c["token_address"].lower()]
        if len(histories)!=1 or len(histories[0]["completed_weeks"])!=4:
            raise ValueError("Saved token history missing")
        series=histories[0]["completed_weeks"]
        expected=[(datetime.fromisoformat(epoch)-timedelta(days=7*(4-i))).isoformat() for i in range(4)]
        if [w["epoch_start_utc"] for w in series]!=expected or any(not re.fullmatch(r"[0-9]{1,78}",w["raw"]) or int(w["raw"])>=2**256 for w in series):
            raise ValueError("Saved training week or raw amount mismatch")
        incentive_tokens=[t for t in incentive_rows[0]["fees"] if t["token_address"].lower()==c["token_address"]]
        if len(incentive_tokens)!=1 or incentive_tokens[0]["last_four_weeks"]!=series:
            # FEES histories contain extra human-readable fields; compare identity/raw only.
            if len(incentive_tokens)!=1 or [(w["epoch_start_utc"],w["raw"]) for w in incentive_tokens[0]["last_four_weeks"]]!=[(w["epoch_start_utc"],w["raw"]) for w in series]:
                raise ValueError("Saved raw FEES sources disagree")
        if str(sum(int(w["raw"]) for w in series)//4)!=c["predicted_raw"]:
            raise ValueError("Pilot baseline does not reconcile")
        c.update(schema_version=2,gauge_address=row["gauge_address"].lower(),fees_contract=row["fees_contract"].lower(),
            source_file=source.relative_to(ROOT).as_posix(),fees_source_file=fees_path.relative_to(ROOT).as_posix(),
            fees_source_sha256=hashlib.sha256(fees_path.read_bytes()).hexdigest(),verifier_sha256=hashlib.sha256(verifier.read_bytes()).hexdigest(),
            token_symbol=histories[0].get("symbol"),token_decimals=histories[0].get("decimals"),
            evidence_policy="Base finalized block, first block crossing target end, parent hash continuity, voter pool/gauge/FEES mapping, block-hash-pinned eth_call")
        validate_commitment(c)
        records.append({"commitment":c,"commitment_sha256":canonical_hash(c),"status":"pending", "registration":"local_file_only", "genlayer_consensus":False})
    return {"schema_version":2,"mode":"direct_mode_ready","forecasts":records,"paid_transactions":0,"independent_timestamp":False}

def evaluate_v2(record,evidence,now):
    try:
        c=validate_commitment(record["commitment"])
        if record["commitment_sha256"]!=canonical_hash(c):return {"status":"unverifiable","reason":"commitment_mismatch"}
        if now.tzinfo is None:raise ValueError("Naive clock")
        if now<datetime.fromisoformat(c["target_end_utc"]):return {"status":"pending","reason":"epoch_not_completed"}
        if evidence is None:return {"status":"insufficient_data","reason":"no_evidence"}
        for key in ("chain_id","pool_address","gauge_address","fees_contract","token_address","target_start_utc"):
            if evidence.get(key)!=c[key]:return {"status":"unverifiable","reason":"identity_mismatch"}
        n=evidence.get("block_number"); parent=evidence.get("parent_number"); finalized=evidence.get("finalized_number")
        if any(type(x)is not int for x in (n,parent,finalized)) or n<=0 or parent!=n-1 or finalized<n:
            return {"status":"unverifiable","reason":"block_not_finalized_or_linked"}
        for key in ("block_hash","parent_hash","block_parent_hash"):
            if not re.fullmatch(r"0x[0-9a-f]{64}",evidence.get(key,"")):raise ValueError("Malformed block hash")
        if evidence["parent_hash"]!=evidence["block_parent_hash"]:return {"status":"unverifiable","reason":"parent_hash_mismatch"}
        boundary=int(datetime.fromisoformat(c["target_end_utc"]).timestamp())
        if not (type(evidence.get("parent_timestamp"))is int and type(evidence.get("block_timestamp"))is int and evidence["parent_timestamp"]<boundary<=evidence["block_timestamp"]):
            return {"status":"unverifiable","reason":"wrong_epoch_boundary"}
        raw=evidence.get("actual_raw")
        if not isinstance(raw,str) or not re.fullmatch(r"0|[1-9][0-9]{0,77}",raw) or int(raw)>=2**256:
            return {"status":"insufficient_data","reason":"invalid_raw_amount"}
        predicted=int(c["predicted_raw"]);actual=int(raw)
        matched=abs(actual-predicted)*100<=predicted*c["tolerance_percent"]
        return {"status":"locally_evaluated","forecast_matched":matched,"actual_raw":raw,"genlayer_consensus":False}
    except (KeyError,TypeError,ValueError,OverflowError):return {"status":"unverifiable","reason":"malformed_record_or_evidence"}

if __name__=="__main__":
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument("--output",required=True);args=parser.parse_args()
    doc=build_pilot_v2()
    with open(args.output,"x",encoding="utf-8") as stream:json.dump(doc,stream,indent=2,ensure_ascii=False)
