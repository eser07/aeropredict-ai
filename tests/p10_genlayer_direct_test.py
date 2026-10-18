"""GenLayer Direct Mode only; all Base responses are mocked, no network consensus."""
import copy
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from p10_forecast_v2 import build_pilot_v2,canonical_hash,evaluate_v2
NOW=datetime(2026,10,18,tzinfo=timezone.utc)
BLOCK=60000000
HASH="0x"+"a"*64
PARENT="0x"+"b"*64

@pytest.fixture
def setup_case(direct_vm,direct_deploy):
    def setup(index=64):
        direct_vm.warp(NOW.isoformat())
        record=next(r for r in build_pilot_v2(NOW)["forecasts"] if r["commitment"]["pool_index"]==index)
        contract=direct_deploy("contracts/P10ForecastVerifier.py",json.dumps(record["commitment"]),record["commitment_sha256"])
        module=sys.modules["_contract_P10ForecastVerifier"]
        return record,contract,module
    return setup

def rpc_mock(c,mode="match"):
    boundary=int(datetime.fromisoformat(c["target_end_utc"]).timestamp())
    calls=[]
    def reply(url,*,method,headers,body):
        assert url=="https://base-rpc.publicnode.com" and method=="POST"
        request=json.loads(body);name=request["method"];params=request["params"]
        calls.append((name,params))
        if mode=="http_error":return SimpleNamespace(status=503,body=b"")
        if name=="eth_chainId":value="0x1" if mode=="wrong_chain" else "0x2105"
        elif name=="eth_getBlockByNumber":
            tag=params[0]
            if tag=="finalized":value={"number":hex(BLOCK-1 if mode=="unfinalized" else BLOCK+10)}
            elif tag==hex(BLOCK-1):value={"number":tag,"hash":PARENT,"timestamp":hex(boundary if mode=="wrong_boundary" else boundary-2)}
            else:
                value={"number":tag,"hash":HASH,"parentHash":("0x"+"c"*64) if mode=="bad_parent" else PARENT,"timestamp":hex(boundary)}
                if mode=="reorg" and sum(x[0]==name and x[1][0]==hex(BLOCK) for x in calls)>1:value["hash"]="0x"+"d"*64
        elif name=="eth_call":
            assert params[1]=={"blockHash":HASH,"requireCanonical":True}
            to=params[0]["to"];data=params[0]["data"]
            if data.startswith("0xb9a09fd5"):
                assert data[10:]==c["pool_address"][2:].zfill(64)
                value="0x"+c["gauge_address"][2:].zfill(64)
            elif data.startswith("0xc4f08165"):
                value="0x"+("e"*40 if mode=="wrong_fees" else c["fees_contract"][2:]).zfill(64)
            elif data=="0x1be05289":value="0x"+f"{604800:064x}"
            else:
                assert to==c["fees_contract"]
                start=int(datetime.fromisoformat(c["target_start_utc"]).timestamp())
                assert data=="0x92777b29"+c["token_address"][2:].zfill(64)+f"{start:064x}"
                raw=int(c["predicted_raw"])*(2 if mode=="miss" else 1)
                value="0x123" if mode=="bad_abi" else "0x"+f"{raw:064x}"
        else:raise AssertionError(name)
        return SimpleNamespace(status=200,body=json.dumps({"jsonrpc":"2.0","id":request["id"],"result":value}).encode())
    return reply,calls

@pytest.mark.parametrize("index",[64,35,0,1,4])
def test_five_pool_settlement(setup_case,direct_vm,index):
    record,contract,module=setup_case(index);c=record["commitment"]
    assert json.loads(contract.get_details())["status"]=="PENDING"
    direct_vm.warp(c["target_end_utc"])
    response,calls=rpc_mock(c)
    with patch.object(module.gl.nondet.web,"request",side_effect=response):
        contract.settle(BLOCK)
        details=json.loads(contract.get_details())
        assert details["status"]=="FORECAST_MATCH"
        assert details["result"]["actual_raw"]==c["predicted_raw"]
        assert details["result"]["block_hash"]==HASH
        # SDK sandbox compatibility only; validator replay remains a local unit test.
        with patch.object(module.gl.vm,"spawn_sandbox",side_effect=lambda fn,**kwargs:module.gl.vm.Return(calldata=fn())):
            assert direct_vm.run_validator() is True
            changed,_=rpc_mock(c,"miss")
            with patch.object(module.gl.nondet.web,"request",side_effect=changed):
                assert direct_vm.run_validator() is False
    assert len(calls)==18
    with pytest.raises(Exception,match="already settled"):contract.settle(BLOCK)

@pytest.mark.parametrize("mode",["wrong_chain","unfinalized","wrong_boundary","bad_parent","wrong_fees","reorg","bad_abi","http_error"])
def test_rejected_evidence_can_retry(setup_case,direct_vm,mode):
    record,contract,module=setup_case();c=record["commitment"];direct_vm.warp(c["target_end_utc"])
    bad,_=rpc_mock(c,mode)
    with patch.object(module.gl.nondet.web,"request",side_effect=bad):contract.settle(BLOCK)
    assert json.loads(contract.get_details())["status"]=="INSUFFICIENT_DATA"
    good,_=rpc_mock(c)
    with patch.object(module.gl.nondet.web,"request",side_effect=good):contract.settle(BLOCK)
    assert json.loads(contract.get_details())["status"]=="FORECAST_MATCH"

def test_missed_prediction_is_distinct_from_missing_evidence(setup_case,direct_vm):
    record,contract,module=setup_case();c=record["commitment"];direct_vm.warp(c["target_end_utc"])
    response,_=rpc_mock(c,"miss")
    with patch.object(module.gl.nondet.web,"request",side_effect=response):contract.settle(BLOCK)
    assert json.loads(contract.get_details())["status"]=="FORECAST_MISS"

def test_early_settlement_rejected(setup_case):
    _,contract,_=setup_case()
    with pytest.raises(Exception,match="not ended"):contract.settle(BLOCK)

@pytest.mark.parametrize("kind",["hash","late","address","zero_address","chain","negative","overflow"])
def test_bad_registration(direct_vm,direct_deploy,kind):
    direct_vm.warp(NOW.isoformat());record=build_pilot_v2(NOW)["forecasts"][0];c=record["commitment"]
    if kind=="late":direct_vm.warp(c["target_start_utc"])
    if kind=="address":c["fees_contract"]="0xBAD"
    if kind=="zero_address":c["fees_contract"]="0x"+"0"*40
    if kind=="chain":c["chain_id"]=1
    if kind=="negative":c["predicted_raw"]="-1"
    if kind=="overflow":c["predicted_raw"]=str(2**256)
    digest="f"*64 if kind=="hash" else canonical_hash(c)
    with pytest.raises(Exception,match="Invalid forecast commitment"):
        direct_deploy("contracts/P10ForecastVerifier.py",json.dumps(c),digest)

def test_local_evidence_validation():
    record=build_pilot_v2(NOW)["forecasts"][0];c=record["commitment"];end=datetime.fromisoformat(c["target_end_utc"])
    assert evaluate_v2(record,None,NOW)["status"]=="pending"
    assert evaluate_v2(record,None,end)["status"]=="insufficient_data"
    assert evaluate_v2({},None,end)["status"]=="unverifiable"
    evidence={key:c[key] for key in ("chain_id","pool_address","gauge_address","fees_contract","token_address","target_start_utc")}
    evidence.update(block_number=BLOCK,parent_number=BLOCK-1,finalized_number=BLOCK,block_hash=HASH,parent_hash=PARENT,block_parent_hash=PARENT,parent_timestamp=int(end.timestamp())-2,block_timestamp=int(end.timestamp()),actual_raw=c["predicted_raw"])
    assert evaluate_v2(record,evidence,end)["forecast_matched"] is True
    evidence["parent_hash"]="0x"+"f"*64
    assert evaluate_v2(record,evidence,end)["reason"]=="parent_hash_mismatch"

@pytest.mark.parametrize("bad",["category","fractional_epoch","naive_epoch","bad_token"])
def test_malformed_commitment_status(bad):
    record=build_pilot_v2(NOW)["forecasts"][0];c=record["commitment"]
    if bad=="category":c["reward_category"]="BRIBES"
    elif bad=="fractional_epoch":
        c["target_start_utc"]=c["target_start_utc"].replace("00:00:00+","00:00:00.5+")
        c["target_end_utc"]=c["target_end_utc"].replace("00:00:00+","00:00:00.5+")
    elif bad=="naive_epoch":c["target_start_utc"]=c["target_start_utc"].replace("+00:00","")
    else:c["token_address"]="0x"+"0"*40
    record["commitment_sha256"]=canonical_hash(c)
    assert evaluate_v2(record,None,NOW)["status"]=="unverifiable"

def test_zero_prediction_requires_exact_zero():
    record=build_pilot_v2(NOW)["forecasts"][0];c=record["commitment"];c["predicted_raw"]="0";record["commitment_sha256"]=canonical_hash(c)
    end=datetime.fromisoformat(c["target_end_utc"])
    evidence={key:c[key] for key in ("chain_id","pool_address","gauge_address","fees_contract","token_address","target_start_utc")}
    evidence.update(block_number=BLOCK,parent_number=BLOCK-1,finalized_number=BLOCK,block_hash=HASH,parent_hash=PARENT,block_parent_hash=PARENT,parent_timestamp=int(end.timestamp())-2,block_timestamp=int(end.timestamp()),actual_raw="0")
    assert evaluate_v2(record,evidence,end)["forecast_matched"] is True
    evidence["actual_raw"]="1"
    assert evaluate_v2(record,evidence,end)["forecast_matched"] is False

def test_panel_status_keeps_realized_values_unknown():
    from p10_pilot_status import load_pilot_status
    status=load_pilot_status(NOW)
    assert len(status["forecasts"])==5
    assert not status["network_consensus"]
    assert all(r["status"]=="pending" and r["actual_raw"] is None for r in status["forecasts"])
    later=datetime(2026,11,1,tzinfo=timezone.utc)
    assert all(r["status"]=="insufficient_data" and r["actual_raw"] is None for r in load_pilot_status(later)["forecasts"])
