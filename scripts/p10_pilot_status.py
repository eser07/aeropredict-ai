"""Read-only P10 registration/status loader, no settlement or network calls."""
import hashlib
import json
from datetime import datetime,timezone
from pathlib import Path
from p10_forecast_v2 import ROOT,FOLDER,validate_commitment,canonical_hash,evaluate_v2
from p10_evidence import load_observations, OBSERVATIONS, local_bytes
REGISTRY=ROOT/"research/p10_pilot/registrations/pilot_v2_20261018_r2.json"
REPORT=ROOT/"research/p10_pilot/direct_test_report.json"

def load_pilot_status(now=None,registry=REGISTRY,report=REPORT,observations=OBSERVATIONS):
    now=now or datetime.now(timezone.utc)
    doc=json.loads(local_bytes(registry))
    records=doc.get("forecasts")
    if doc.get("schema_version")!=2 or not isinstance(records,list) or len(records)!=5 or {r["commitment"]["pool_index"] for r in records}!={64,35,0,1,4}:
        raise ValueError("Invalid five-pool pilot registry")
    result=[]
    for record in records:
        c=validate_commitment(record["commitment"])
        if record["commitment_sha256"]!=canonical_hash(c):raise ValueError("Registration digest mismatch")
        for file_key,hash_key in (("source_file","source_sha256"),("fees_source_file","fees_source_sha256")):
            path=(ROOT/c[file_key]).resolve()
            if not path.is_relative_to(FOLDER.resolve()) or hashlib.sha256(local_bytes(path)).hexdigest()!=c[hash_key]:
                raise ValueError("Registration source changed")
        if hashlib.sha256(local_bytes(ROOT/"contracts/P10ForecastVerifier.py")).hexdigest()!=c["verifier_sha256"]:
            raise ValueError("Registered verifier version changed")
        status=evaluate_v2(record,None,now)
        result.append({**record,**status,"actual_raw":None})
    archive=load_observations(records,now,observations)
    for row in result:
        key=row["commitment_sha256"]
        row["collection_attempt"]=archive["latest"].get(key)
        saved=archive["valid"].get(key)
        if saved:
            row.update(status="locally_evaluated",actual_raw=saved["actual_raw"],forecast_matched=saved["forecast_matched"],
                       evidence_block_number=saved["evidence"]["block_number"],evidence_block_hash=saved["evidence"]["block_hash"],
                       observation_utc=saved["collected_at_utc"],evidence_scope="single_provider_local_read; not GenLayer consensus")
    test={"available":False,"network_consensus":False}
    try:
        saved=json.loads(local_bytes(report))
        current=all(hashlib.sha256(local_bytes(ROOT/path)).hexdigest()==digest for path,digest in saved["source_sha256"].items())
        if current:test={"available":True,"passed":saved["passed"],"tests":saved["tests"],"ran_at_utc":saved["ran_at_utc"],"network_consensus":False,"scope":"Direct Mode; Base RPC responses mocked"}
    except (OSError,ValueError,KeyError,TypeError):pass
    return {"schema_version":2,"forecasts":result,"test_validation":test,"independent_timestamp":False,"network_consensus":False,"paid_transactions":0,"generated_at_utc":now.isoformat(),"collection_summary":{"scanned_snapshots":archive["scanned_snapshots"],"invalid_snapshots":archive["invalid_snapshots"]}}
