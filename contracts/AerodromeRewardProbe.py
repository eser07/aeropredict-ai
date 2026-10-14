"""AeroPredict AI: read a historical Aerodrome FEES allocation from Base.

A fixed (caller-supplied) Base block and epoch make the result reproducible.
For this first integration probe, both the voting-reward contract and
token are fixed to verified Pool #0 FEES and USDbC.

A per-epoch allocation is NOT a user's claimable reward or voting APR.
"""
import json

import genlayer as gl
from genlayer import *

RPC = "https://base-rpc.publicnode.com"
CHAIN_ID = 8453
WEEK_SECONDS = 604800
FEES_CONTRACT = "0x958a5612390bb4134e1e7505c7cb6b0652941174"
TOKEN = "0xd9aaec86b65d86f6a7b5b1b0c42ffa531710b6ca"  # USDbC, 6 decimals
SELECTOR = "0x92777b29"  # tokenRewardsPerEpoch(address,uint256)


class AerodromeRewardProbe(gl.contract.Contract):
    last_reward_raw: u256
    last_base_block: u256
    last_epoch_start: u256

    def __init__(self):
        self.last_reward_raw = 0
        self.last_base_block = 0
        self.last_epoch_start = 0

    @gl.public.write
    def snapshot_reward(self, base_block: u256, epoch_start: u256) -> None:
        block = int(base_block)
        epoch = int(epoch_start)
        if block < 1 or epoch <= 0 or epoch % WEEK_SECONDS != 0:
            raise gl.vm.UserError("Invalid Base block or epoch start")
        block_tag = hex(block)

        def get_reward() -> int:
            def rpc(method, params):
                response = gl.nondet.web.request(
                    RPC,
                    method="POST",
                    headers={"Content-Type": "application/json"},
                    body=json.dumps({
                        "jsonrpc": "2.0", "id": 1,
                        "method": method, "params": params,
                    }),
                )
                if response.status != 200 or response.body is None:
                    # Diagnostics for local RPC connectivity; never include keys.
                    detail = (response.body or b"")[:240].decode(
                        "utf-8", errors="replace"
                    ).replace("\\n", " ")
                    raise gl.vm.UserError(
                        f"Base RPC {method} HTTP {response.status}: {detail}"
                    )
                answer = json.loads(response.body.decode("utf-8"))
                if "error" in answer:
                    raise gl.vm.UserError(
                        f"Base RPC {method} JSON-RPC error: {answer['error']}"
                    )
                if "result" not in answer:
                    raise gl.vm.UserError(
                        f"Base RPC {method} response missing result"
                    )
                return answer["result"]

            if int(rpc("eth_chainId", []), 16) != CHAIN_ID:
                raise gl.vm.UserError("RPC is not Base mainnet")
            block_info = rpc("eth_getBlockByNumber", [block_tag, False])
            if not isinstance(block_info, dict):
                raise gl.vm.UserError("Base block not found")
            if int(block_info["timestamp"], 16) < epoch:
                raise gl.vm.UserError("Base block predates requested epoch")
            calldata = SELECTOR + TOKEN[2:].lower().zfill(64) + f"{epoch:064x}"
            encoded = rpc(
                "eth_call",
                [{"to": FEES_CONTRACT, "data": calldata}, block_tag],
            )
            if not isinstance(encoded, str) or not encoded.startswith("0x"):
                raise gl.vm.UserError("Invalid reward response")
            return int(encoded, 16)

        value = gl.eq_principle.strict_eq(get_reward)
        self.last_reward_raw = u256(value)
        self.last_base_block = base_block
        self.last_epoch_start = epoch_start

    @gl.public.view
    def get_reward_raw(self) -> u256:
        return self.last_reward_raw

    @gl.public.view
    def get_snapshot(self) -> str:
        return json.dumps({
            "chain_id": CHAIN_ID,
            "reward_contract": FEES_CONTRACT,
            "token": TOKEN,
            "decimals": 6,
            "base_block": int(self.last_base_block),
            "epoch_start": int(self.last_epoch_start),
            "reward_raw": str(self.last_reward_raw),
            "note": "Pool allocation, not claimable earnings or APR",
        }, sort_keys=True)
