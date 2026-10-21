# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
"""AeroPredict AI: isolated GenLayer-to-Base RPC connectivity probe.

This separate contract is intentionally small. A successful write proves
that GLSim can fetch Base's chain ID via GenLayer web access and apply
strict equivalence. It does NOT validate reward values or forecasts.
"""
import json

import genlayer as gl
from genlayer import *

BASE_RPC = "https://base-rpc.publicnode.com"
BASE_CHAIN_ID = 8453


class BaseRpcProbe(gl.Contract):
    checked_chain_id: u256

    def __init__(self):
        self.checked_chain_id = 0

    @gl.public.write
    def check_base_rpc(self) -> None:
        def fetch_chain_id() -> int:
            response = gl.nondet.web.request(
                BASE_RPC,
                method="POST",
                headers={"Content-Type": "application/json"},
                body=json.dumps({
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "eth_chainId",
                    "params": [],
                }),
            )
            if response.status != 200 or response.body is None:
                raise gl.vm.UserError("Base RPC HTTP request failed")
            payload = json.loads(response.body.decode("utf-8"))
            if "error" in payload or "result" not in payload:
                raise gl.vm.UserError("Invalid Base RPC response")
            chain_id = int(payload["result"], 16)
            if chain_id != BASE_CHAIN_ID:
                raise gl.vm.UserError("Unexpected chain ID")
            return chain_id

        self.checked_chain_id = u256(gl.eq_principle.strict_eq(fetch_chain_id))

    @gl.public.view
    def get_chain_id(self) -> u256:
        return self.checked_chain_id
