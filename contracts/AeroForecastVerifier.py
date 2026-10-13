# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
"""AeroPredict AI - single-forecast GenLayer verification prototype.

A forecast is submitted before its Aerodrome epoch starts.
After the epoch, a caller supplies the first Base block at/after the
epoch boundary. GenLayer validators independently fetch that immutable
block and its parent, check the boundary, and compare the reward value
at the supplied block via strict equality.

Prototype scope: one prediction per deployed contract, one fixed Base
Aerodrome FEES contract. No APR or USD conversion.
"""
import json
from datetime import datetime, timezone

import genlayer as gl
from genlayer import *

BASE_RPC = "https://base-rpc.publicnode.com"
BASE_CHAIN_ID = 8453
EPOCH_SECONDS = 604800
FEES_REWARD_CONTRACT = "0x958a5612390bb4134e1e7505c7cb6b0652941174"
REWARD_EPOCH_SELECTOR = "0x92777b29"  # tokenRewardsPerEpoch(address,uint256)


class AeroForecastVerifier(gl.contract.Contract):
    token_address: str
    epoch_start: u256
    predicted_raw: u256
    actual_raw: u256
    settlement_block: u256
    forecast_created_at: u256
    status: str
    error_raw: u256

    def __init__(self):
        self.token_address = ""
        self.epoch_start = 0
        self.predicted_raw = 0
        self.actual_raw = 0
        self.settlement_block = 0
        self.forecast_created_at = 0
        self.error_raw = 0
        self.status = "EMPTY"

    @gl.public.write
    def submit_forecast(self, token_address: str, epoch_start: u256, predicted_raw: u256) -> None:
        if self.status != "EMPTY":
            raise gl.UserError("Forecast already submitted")
        if len(token_address) != 42 or not token_address.startswith("0x"):
            raise gl.UserError("Invalid token address")
        try:
            int(token_address[2:], 16)
        except ValueError:
            raise gl.UserError("Invalid hexadecimal token address")
        start = int(epoch_start)
        if start <= int(datetime.now(timezone.utc).timestamp()):
            raise gl.UserError("Forecast must be submitted before its epoch starts")
        if start % EPOCH_SECONDS != 0:
            raise gl.UserError("Epoch must start at Thursday 00:00 UTC")
        self.token_address = token_address.lower()
        self.epoch_start = epoch_start
        self.predicted_raw = predicted_raw
        self.forecast_created_at = int(datetime.now(timezone.utc).timestamp())
        self.status = "PENDING"

    @gl.public.write
    def settle(self, first_next_epoch_block: u256) -> None:
        if self.status != "PENDING":
            raise gl.UserError("No pending forecast")
        boundary = int(self.epoch_start) + EPOCH_SECONDS
        if int(datetime.now(timezone.utc).timestamp()) < boundary:
            raise gl.UserError("Epoch has not ended")
        block_num = int(first_next_epoch_block)
        if block_num < 1:
            raise gl.UserError("Invalid Base block")
        token = self.token_address
        start = int(self.epoch_start)
        block_tag = hex(block_num)

        # All external RPC operations are inside the nondeterministic block.
        # The returned raw uint256 is compared exactly across GenLayer validators.
        def verify_external_reward() -> int:
            def rpc(method, params):
                response = gl.nondet.web.request(
                    BASE_RPC,
                    method="POST",
                    headers={"Content-Type": "application/json"},
                    body={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                )
                if response.status_code != 200:
                    raise gl.UserError("Base RPC returned an HTTP error")
                message = json.loads(response.body.decode("utf-8"))
                if "error" in message or "result" not in message:
                    raise gl.UserError("Base RPC returned an invalid result")
                return message["result"]

            if int(rpc("eth_chainId", []), 16) != BASE_CHAIN_ID:
                raise gl.UserError("Wrong RPC chain")
            current = rpc("eth_getBlockByNumber", [block_tag, False])
            parent = rpc("eth_getBlockByNumber", [hex(block_num - 1), False])
            if not isinstance(current, dict) or not isinstance(parent, dict):
                raise gl.UserError("Block not found")
            # Requires the FIRST block at/after the new epoch boundary.
            if not (
                int(parent["timestamp"], 16) < start + EPOCH_SECONDS
                <= int(current["timestamp"], 16)
            ):
                raise gl.UserError("Block does not cross the epoch boundary")
            calldata = (
                REWARD_EPOCH_SELECTOR
                + token[2:].lower().zfill(64)
                + f"{start:064x}"
            )
            observed_hex = rpc(
                "eth_call",
                [{"to": FEES_REWARD_CONTRACT, "data": calldata}, block_tag],
            )
            return int(observed_hex, 16)

        observed = gl.eq_principle.strict_eq(verify_external_reward)
        self.actual_raw = u256(observed)
        self.settlement_block = first_next_epoch_block
        predicted = int(self.predicted_raw)
        self.error_raw = u256(abs(observed - predicted))
        self.status = "VERIFIED_AT_BLOCK"

    @gl.public.view
    def get_status(self) -> str:
        return self.status

    @gl.public.view
    def get_prediction_raw(self) -> u256:
        return self.predicted_raw

    @gl.public.view
    def get_actual_raw(self) -> u256:
        return self.actual_raw

    @gl.public.view
    def get_details(self) -> str:
        return json.dumps({
            "chain_id": BASE_CHAIN_ID,
            "reward_contract": FEES_REWARD_CONTRACT,
            "token": self.token_address,
            "epoch_start": int(self.epoch_start),
            "predicted_raw": str(self.predicted_raw),
            "actual_raw": str(self.actual_raw),
            "error_raw": str(self.error_raw),
            "settlement_block": int(self.settlement_block),
            "forecast_created_at": int(self.forecast_created_at),
            "status": self.status,
        }, sort_keys=True)
