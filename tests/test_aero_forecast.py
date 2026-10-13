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


def test_settle_checks_base_rpc_and_records_difference(direct_vm, direct_deploy):
    """Exercise settlement with distinct, deterministic mocked JSON-RPC replies."""
    import sys
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from unittest.mock import patch

    contract = direct_deploy("contracts/AeroForecastVerifier.py")
    module = sys.modules["_contract_AeroForecastVerifier"]

    class Clock:
        current = FUTURE_EPOCH - 60

        @classmethod
        def now(cls, tz):
            return datetime.fromtimestamp(cls.current, tz=timezone.utc)

    next_epoch = FUTURE_EPOCH + 604800
    observed_raw = 1_700_000
    block_num = 12345
    rpc_methods = []

    def fake_request(url, *, method, headers, body):
        assert url == "https://base-rpc.publicnode.com"
        assert method == "POST"
        request = json.loads(body)
        name = request["method"]
        params = request["params"]
        rpc_methods.append(name)
        if name == "eth_chainId":
            value = "0x2105"
        elif name == "eth_getBlockByNumber":
            assert params[1] is False
            assert params[0] in (hex(block_num), hex(block_num - 1))
            t = next_epoch if params[0] == hex(block_num) else next_epoch - 2
            value = {"timestamp": hex(t)}
        elif name == "eth_call":
            assert params[1] == hex(block_num)
            assert params[0]["to"] == module.FEES_REWARD_CONTRACT
            expected_data = (
                module.REWARD_EPOCH_SELECTOR
                + TOKEN[2:].lower().zfill(64)
                + f"{FUTURE_EPOCH:064x}"
            )
            assert params[0]["data"] == expected_data
            value = hex(observed_raw)
        else:
            raise AssertionError(f"Unexpected JSON-RPC method: {name}")
        response = {"jsonrpc": "2.0", "id": 1, "result": value}
        return SimpleNamespace(status=200, body=json.dumps(response).encode())

    with patch.object(module, "datetime", Clock), patch.object(
        module.gl.nondet.web, "request", side_effect=fake_request
    ):
        contract.submit_forecast(TOKEN, FUTURE_EPOCH, 1_500_000)
        assert contract.get_status() == "PENDING"
        Clock.current = next_epoch + 1
        contract.settle(block_num)
        assert contract.get_status() == "VERIFIED_AT_BLOCK"
        assert int(contract.get_actual_raw()) == observed_raw
        details = json.loads(contract.get_details())
        assert details["error_raw"] == "200000"
        assert details["settlement_block"] == block_num
        # This checks the direct-mode validator reruns the same external reads.
        assert direct_vm.run_validator() is True

    assert "eth_chainId" in rpc_methods
    assert "eth_getBlockByNumber" in rpc_methods
    assert "eth_call" in rpc_methods
