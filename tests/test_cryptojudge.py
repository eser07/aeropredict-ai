def test_initial_state(direct_vm, direct_deploy):
    contract = direct_deploy("contracts/CryptoJudge.py")

    assert contract.get_verdict() == "BEKLIYOR"
    assert int(contract.get_weekly_fee()) == 0

def test_refresh_above_threshold(direct_vm, direct_deploy):
    import json

    direct_vm.mock_web(
        r"api\.llama\.fi/summary/fees/aerodrome",
        {
            "status": 200,
            "body": json.dumps({"total7d": 6200000})
        }
    )

    contract = direct_deploy("contracts/CryptoJudge.py")
    contract.refresh()

    assert contract.get_verdict() == "EVET"
    assert int(contract.get_weekly_fee()) == 6200000

import pytest

@pytest.mark.parametrize(
    "fee,expected",
    [
        (2717962, "HAYIR"),
        (5000000, "HAYIR"),
        (5000001, "EVET"),
    ]
)
def test_fee_scenarios(direct_vm, direct_deploy, fee, expected):
    import json

    direct_vm.mock_web(
        r"api\.llama\.fi/summary/fees/aerodrome",
        {
            "status": 200,
            "body": json.dumps({"total7d": fee})
        }
    )

    contract = direct_deploy("contracts/CryptoJudge.py")
    contract.refresh()

    assert contract.get_verdict() == expected
    assert int(contract.get_weekly_fee()) == fee
