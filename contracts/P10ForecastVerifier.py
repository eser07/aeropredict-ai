# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
"""P10 single-commitment verifier, instantiated for five source-bound pools.

Development prototype. Direct Mode runs are not network attestations.
The prediction is immutable after construction; settlement can be retried
when the RPC cannot supply finalized, canonical, block-pinned evidence.
"""
import hashlib
import json
import re
from datetime import datetime, timezone
from genlayer import *

RPC="https://base-rpc.publicnode.com"
VOTER="0x16613524e02ad97edfef371bc883f2f5d6c480a5"
WEEK=604800

def addr(value):
    return isinstance(value,str) and re.fullmatch(r"0x[0-9a-f]{40}",value) is not None and int(value[2:],16)>0

def block_hash(value):
    return isinstance(value,str) and re.fullmatch(r"0x[0-9a-f]{64}",value) is not None

class P10ForecastVerifier(gl.Contract):
    commitment_json: str
    commitment_sha256: str
    result_json: str
    status: str
    registered_at: u256

    def __init__(self, commitment_json: str, commitment_sha256: str):
        try:
            c=json.loads(commitment_json)
            normalized=json.dumps(c,sort_keys=True,separators=(",",":"))
            if hashlib.sha256(normalized.encode()).hexdigest()!=commitment_sha256:
                raise ValueError("commitment hash mismatch")
            if c.get("schema_version")!=2 or c.get("chain_id")!=8453 or c.get("reward_category")!="FEES":
                raise ValueError("unsupported schema or chain")
            for key in ("pool_address","gauge_address","fees_contract","token_address"):
                if not addr(c.get(key)):raise ValueError("invalid address")
            raw=c.get("predicted_raw")
            if not isinstance(raw,str) or not re.fullmatch(r"0|[1-9][0-9]{0,77}",raw) or int(raw)>=2**256:
                raise ValueError("invalid prediction")
            if type(c.get("tolerance_percent"))is not int or not 0<=c["tolerance_percent"]<=100:
                raise ValueError("invalid tolerance")
            for key in ("source_sha256","fees_source_sha256","verifier_sha256"):
                if not re.fullmatch(r"[0-9a-f]{64}",c.get(key,"")):raise ValueError("invalid source hash")
            start=datetime.fromisoformat(c["target_start_utc"]);end=datetime.fromisoformat(c["target_end_utc"])
            created=datetime.fromisoformat(c["created_at_utc"])
            now=datetime.now(timezone.utc)
            if any(t.tzinfo is None for t in (start,end,created)) or start.timestamp()!=int(start.timestamp()) or int(start.timestamp())%WEEK or (end-start).total_seconds()!=WEEK or not created<=now<start:
                raise ValueError("forecast must be registered before target epoch")
        except (ValueError,KeyError,TypeError,OverflowError) as error:
            raise gl.vm.UserError("Invalid forecast commitment") from error
        self.commitment_json=normalized
        self.commitment_sha256=commitment_sha256
        self.registered_at=u256(int(now.timestamp()))
        self.status="PENDING"
        self.result_json="{}"

    @gl.public.write
    def settle(self, first_next_epoch_block: u256) -> None:
        if self.status in ("FORECAST_MATCH","FORECAST_MISS"):
            raise gl.vm.UserError("Forecast already settled")
        c=json.loads(self.commitment_json)
        boundary=int(datetime.fromisoformat(c["target_end_utc"]).timestamp())
        if int(datetime.now(timezone.utc).timestamp())<boundary:
            raise gl.vm.UserError("Target epoch has not ended")
        number=int(first_next_epoch_block)
        if not 0<number<2**64:raise gl.vm.UserError("Invalid settlement block")
        tag=hex(number)
        def read_evidence():
            calls=0
            def rpc(method,params):
                nonlocal calls
                calls+=1
                response=gl.nondet.web.request(RPC,method="POST",headers={"Content-Type":"application/json"},body=json.dumps({"jsonrpc":"2.0","id":calls,"method":method,"params":params}))
                if response.status!=200 or response.body is None:raise ValueError("rpc_unavailable")
                message=json.loads(response.body.decode("utf-8"))
                if not isinstance(message,dict) or "error" in message or "result" not in message or message.get("id")!=calls:
                    raise ValueError("rpc_invalid_response")
                return message["result"]
            try:
                if int(rpc("eth_chainId",[]),16)!=8453:raise ValueError("wrong_chain")
                current=rpc("eth_getBlockByNumber",[tag,False])
                parent=rpc("eth_getBlockByNumber",[hex(number-1),False])
                finalized=rpc("eth_getBlockByNumber",["finalized",False])
                if not all(isinstance(b,dict) for b in (current,parent,finalized)):raise ValueError("missing_block")
                if int(current["number"],16)!=number or int(parent["number"],16)!=number-1 or int(finalized["number"],16)<number:
                    raise ValueError("block_not_finalized")
                if not block_hash(current.get("hash")) or not block_hash(parent.get("hash")) or current.get("parentHash")!=parent["hash"]:
                    raise ValueError("parent_hash_mismatch")
                if not int(parent["timestamp"],16)<boundary<=int(current["timestamp"],16):raise ValueError("wrong_epoch_boundary")
                pinned={"blockHash":current["hash"],"requireCanonical":True}
                def call(target,data):
                    raw=rpc("eth_call",[{"to":target,"data":data},pinned])
                    if not isinstance(raw,str) or not re.fullmatch(r"0x[0-9a-fA-F]{64}",raw):raise ValueError("malformed_abi_word")
                    return raw.lower()
                def address_word(target,selector,arg):
                    word=call(target,selector+arg[2:].zfill(64))
                    if int(word[2:26],16)!=0:raise ValueError("malformed_address_word")
                    return "0x"+word[-40:]
                if address_word(VOTER,"0xb9a09fd5",c["pool_address"])!=c["gauge_address"]:raise ValueError("pool_gauge_mismatch")
                if address_word(VOTER,"0xc4f08165",c["gauge_address"])!=c["fees_contract"]:raise ValueError("gauge_fees_mismatch")
                if int(call(c["fees_contract"],"0x1be05289"),16)!=WEEK:raise ValueError("unsupported_reward_duration")
                start=int(datetime.fromisoformat(c["target_start_utc"]).timestamp())
                data="0x92777b29"+c["token_address"][2:].zfill(64)+f"{start:064x}"
                actual=int(call(c["fees_contract"],data),16)
                # Compare the same block again; changing canonical headers invalidate evidence.
                recheck=rpc("eth_getBlockByNumber",[tag,False])
                if not isinstance(recheck,dict) or recheck.get("hash")!=current["hash"]:raise ValueError("block_hash_changed")
                result={"evidence_status":"available","actual_raw":str(actual),"block_number":number,"block_hash":current["hash"],"parent_hash":parent["hash"],"rpc_calls":calls}
            except (ValueError,KeyError,TypeError,OverflowError):
                result={"evidence_status":"insufficient_data","reason":"RPC evidence unavailable or rejected"}
            return json.dumps(result,sort_keys=True,separators=(",",":"))
        payload=gl.eq_principle.strict_eq(read_evidence)
        result=json.loads(payload)
        if result["evidence_status"]!="available":
            self.status="INSUFFICIENT_DATA"
            self.result_json=payload
            return
        predicted=int(c["predicted_raw"]);actual=int(result["actual_raw"])
        matched=abs(actual-predicted)*100<=predicted*c["tolerance_percent"]
        self.status="FORECAST_MATCH" if matched else "FORECAST_MISS"
        result.update(forecast_matched=matched,absolute_error_raw=str(abs(actual-predicted)),commitment_sha256=self.commitment_sha256)
        self.result_json=json.dumps(result,sort_keys=True,separators=(",",":"))

    @gl.public.view
    def get_details(self) -> str:
        return json.dumps({"status":self.status,"registered_at":int(self.registered_at),"commitment_sha256":self.commitment_sha256,"commitment":json.loads(self.commitment_json),"result":json.loads(self.result_json)},sort_keys=True)
