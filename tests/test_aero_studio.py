"""GLSim integration smoke test: real local deployment and transaction.

Run ONLY against the running local GLSim, not public testnets:
    gltest tests/test_aero_studio.py -v --network localnet

This exercises GenLayer deployment, state read, and submit_forecast
through the actual local RPC/transaction flow. It deliberately does
not call settle() or claim to prove the external Base data path.
"""

from datetime import datetime, timezone

from gltest import get_contract_factory
from gltest.assertions import tx_execution_succeeded

TOKEN_USDBC = "0xd9aaec86b65d86f6a7b5b1b0c42ffa531710b6ca"
EPOCH_SECONDS = 604800


def test_aero_deploy_and_forecast_on_glsim():
    factory = get_contract_factory("AeroForecastVerifier")

    print("GLSim: Deploying AeroForecastVerifier...")
    contract = factory.deploy()
    assert contract.address is not None
    print(f"GLSim contract address: {contract.address}")

    assert contract.get_status().call() == "EMPTY"

    # A boundary safely in the future to avoid expiry during the test.
    now = int(datetime.now(timezone.utc).timestamp())
    next_epoch = ((now // EPOCH_SECONDS) + 4) * EPOCH_SECONDS
    predicted_raw = 1_500_000

    print(f"GLSim: Submitting forecast for epoch {next_epoch}...")
    receipt = contract.submit_forecast(
        args=[TOKEN_USDBC, next_epoch, predicted_raw]
    ).transact(consensus_max_rotations=3, wait_interval=2000, wait_retries=80)

    assert tx_execution_succeeded(receipt), f"GLSim transaction failed: {receipt}"
    assert contract.get_status().call() == "PENDING"
    assert int(contract.get_prediction_raw().call()) == predicted_raw

    print("GLSim: Deployment, forecast transaction, and state reads passed.")
