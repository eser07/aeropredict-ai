"""GLSim integration test for independent Base JSON-RPC chain ID consensus.

Run ONLY against local GLSim, with network access enabled:
    gltest tests/test_base_rpc_studio.py -v -s --network localnet

This test deliberately uses the REAL public Base RPC, not a web mock.
A pass checks only chain ID access and GenLayer strict equivalence.
"""
import importlib
import inspect

from gltest import get_contract_factory
from gltest.assertions import tx_execution_succeeded


def _adapt_local_sdk(monkeypatch):
    """Adapt genlayer-test 0.29.2 calls to installed genlayer-py 0.18.0."""
    def sdk_fee_kwargs(method, fees, fee_value):
        params = inspect.signature(method).parameters
        if "fees" not in params:
            if fees is not None or fee_value is not None:
                raise ValueError("Explicit fees are unsupported by this SDK")
            return {}
        if "fee_value" in params:
            return {"fees": fees, "fee_value": fee_value}
        return {
            "fees": {**(fees or {}), "feeValue": fee_value}
            if fee_value is not None else fees
        }

    factory_module = importlib.import_module("gltest.contracts.contract_factory")
    contract_module = importlib.import_module("gltest.contracts.contract")
    monkeypatch.setattr(factory_module, "_fee_kwargs", sdk_fee_kwargs)
    monkeypatch.setattr(contract_module, "_fee_kwargs", sdk_fee_kwargs)

    from genlayer_py.client.genlayer_client import GenLayerClient
    from genlayer_py.types import TransactionStatus

    original_wait = GenLayerClient.wait_for_transaction_receipt
    if "wait_until" not in inspect.signature(original_wait).parameters:
        def compatible_wait(self, *args, wait_until=None, **kwargs):
            if wait_until not in (None, "decided", "finalized"):
                raise ValueError(f"Unsupported wait_until: {wait_until}")
            if wait_until is not None and "status" in kwargs:
                raise ValueError("Cannot supply status and wait_until together")
            if wait_until == "decided":
                kwargs["status"] = TransactionStatus.ACCEPTED
            elif wait_until == "finalized":
                kwargs["status"] = TransactionStatus.FINALIZED
            return original_wait(self, *args, **kwargs)

        monkeypatch.setattr(
            GenLayerClient, "wait_for_transaction_receipt", compatible_wait
        )


def test_glsim_validators_reach_base_rpc(monkeypatch):
    _adapt_local_sdk(monkeypatch)
    factory = get_contract_factory("BaseRpcProbe")

    print("Deploying standalone BaseRpcProbe to GLSim...", flush=True)
    contract = factory.deploy()
    print(f"Contract deployed: {contract.address}", flush=True)

    assert int(contract.get_chain_id().call()) == 0

    print("Checking real Base RPC through GenLayer strict_eq...", flush=True)
    receipt = contract.check_base_rpc().transact(
        consensus_max_rotations=3, wait_interval=2000, wait_retries=80
    )
    assert tx_execution_succeeded(receipt), f"Probe transaction failed: {receipt}"
    assert int(contract.get_chain_id().call()) == 8453
    print("GLSim confirmed Base chain ID 8453.", flush=True)
