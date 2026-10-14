"""AeroPredict AI: prove GenLayer can read Aerodrome reward allocations from
Base's CURRENT state (eth_call(..., "latest")), without an archive RPC.

This is an unpinned CURRENT-STATE integration probe, not a historical proof,
voting APR or proof of independent multi-validator consensus.
"""
import json

import genlayer as gl
from genlayer import *

BASE_RPC = "https://base-rpc.publicnode.com"
BASE_CHAIN_ID = 8453
EPOCH_SECONDS = 604800
FEES_CONTRACT = "0x958a5612390bb4134e1e7505c7cb6b0652941174"
USDBC = "0xd9aaec86b65d86f6a7b5b1b0c42ffa531710b6ca"
SELECTOR_REWARD = "0x92777b29"  # tokenRewardsPerEpoch(address,uint256)


class AerodromeLatestRewardProbe(gl.contract.Contract):
    last_epoch: u256
    last_raw: u256
    completed: bool

    def __init__(self):
        self.last_epoch = 0
        self.last_raw = 0
        self.completed = False

    @gl.public.write
    def read_reward_latest(self, epoch_start: u256) -> None:
        epoch = int(epoch_start)
        if epoch <= 0 or epoch % EPOCH_SECONDS != 0:
            raise gl.vm.UserError("Epoch start must be a weekly UTC boundary")

        def fetch() -> int:
            def rpc(method, params):
                response = gl.nondet.web.request(
                    BASE_RPC,
                    method="POST",
                    headers={"Content-Type": "application/json"},
                    body=json.dumps({
                        "jsonrpc": "2.0", "id": 1,
                        "method": method, "params": params,
                    }),
                )
                if response.status != 200 or response.body is None:
                    detail = (response.body or b"")[:240].decode(
                        "utf-8", errors="replace"
                    )
                    raise gl.vm.UserError(
                        f"Base RPC {method} HTTP {response.status}: {detail}"
                    )
                response_json = json.loads(response.body.decode("utf-8"))
                if "error" in response_json:
                    raise gl.vm.UserError(
                        f"Base RPC {method} error: {response_json['error']}"
                    )
                if "result" not in response_json:
                    raise gl.vm.UserError(f"Base RPC {method} missing result")
                return response_json["result"]

            chain_id = int(rpc("eth_chainId", []), 16)
            if chain_id != BASE_CHAIN_ID:
                raise gl.vm.UserError("Expected Base Mainnet chain 8453")

            calldata = (
                SELECTOR_REWARD
                + USDBC[2:].lower().zfill(64)
                + f"{epoch:064x}"
            )
            value_hex = rpc("eth_call", [{
                "to": FEES_CONTRACT, "data": calldata,
            }, "latest"])
            if not isinstance(value_hex, str) or not value_hex.startswith("0x"):
                raise gl.vm.UserError("Invalid eth_call reward value")
            return int(value_hex, 16)

        amount = gl.eq_principle.strict_eq(fetch)
        self.last_epoch = epoch_start
        self.last_raw = u256(amount)
        self.completed = True

    @gl.public.view
    def get_reading(self) -> str:
        return json.dumps({
            "completed": self.completed,
            "base_chain_id": BASE_CHAIN_ID,
            "reward_contract": FEES_CONTRACT,
            "token": USDBC,
            "decimals": 6,
            "epoch_start": int(self.last_epoch),
            "raw": str(self.last_raw),
            "block_tag": "latest",
            "caveat": "Not pinned: value may change between independent reads",
        }, sort_keys=True)
