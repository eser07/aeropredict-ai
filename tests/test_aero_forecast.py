"""Local direct-VM tests for AeroForecastVerifier's deterministic storage path.

These do not exercise external Base RPC access or network consensus.
"""
import json

TOKEN = "0xd9aaec86b65d86f6a7b5b1b0c42ffa531710b6ca"
FUTURE_EPOCH = 604800 * 5000  # Valid Thursday UTC boundary, decades in future.


def test_initial_state(direct_vm, direct_deploy):
    contract = direct_deploy("contracts/AeroForecastVerifier.py")
    assert contract.get_status() == "EMPTY"
    assert int(contract.get_prediction_raw()) == 0
    assert int(contract.get_actual_raw()) == 0


def test_submit_forecast_storage(direct_vm, direct_deploy):
    contract = direct_deploy("contracts/AeroForecastVerifier.py")
    contract.submit_forecast(TOKEN, FUTURE_EPOCH, 1_500_000)
    assert contract.get_status() == "PENDING"
    assert int(contract.get_prediction_raw()) == 1_500_000
    assert int(contract.get_actual_raw()) == 0
    details = json.loads(contract.get_details())
    assert details["token"] == TOKEN
    assert details["epoch_start"] == FUTURE_EPOCH
    assert details["status"] == "PENDING"
    assert details["predicted_raw"] == "1500000"
    assert int(details["forecast_created_at"]) > 0
