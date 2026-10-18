"""Offline P10 collection regressions. No public RPC, no historical file writes."""
import copy
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from p10_evidence import (EvidenceError, ReadOnlyRPC, boundary_blocks, collect_pilot,
                         load_observations, save_observation)
from p10_forecast_v2 import build_pilot_v2, canonical_hash

NOW = datetime(2026, 10, 18, tzinfo=timezone.utc)


@pytest.fixture
def records():
    return build_pilot_v2(NOW)["forecasts"]


class FakeRPC:
    def __init__(self, records, mode="ok"):
        self.records = records
        self.mode = mode
        self.calls = 0
        self.history = []
        self.boundary = int(datetime.fromisoformat(records[0]["commitment"]["target_end_utc"]).timestamp())
        self.block_reads = {}

    def block(self, n):
        # First block on/after target end is 50; finalized head is 100.
        return {"number": hex(n), "timestamp": hex(self.boundary + (n - 50) * 2),
                "hash": "0x" + f"{n + 1:064x}", "parentHash": "0x" + f"{n:064x}"}

    def call(self, method, params):
        self.calls += 1
        self.history.append((method, params))
        if self.mode == "unavailable":
            raise EvidenceError("rpc_transport_unavailable")
        if self.mode == "budget" and self.calls > 4:
            raise EvidenceError("rpc_budget_exhausted")
        if method == "eth_chainId":
            return "0x1" if self.mode == "wrong_chain" else "0x2105"
        if method == "eth_getBlockByNumber":
            n = 100 if params[0] == "finalized" else int(params[0], 16)
            if params[0] == "finalized" and self.mode == "unfinalized":
                n = 40
            block = self.block(n)
            if self.mode == "wrong_number" and n not in {0, 100}:
                block["number"] = hex(n + 1)
            if self.mode == "bad_parent" and n == 50:
                block["parentHash"] = "0x" + "f" * 64
            self.block_reads[n] = self.block_reads.get(n, 0) + 1
            if self.mode == "reorg" and n == 50 and self.block_reads[n] > 1:
                block["hash"] = "0x" + "e" * 64
            return block
        assert method == "eth_call"
        assert params[1] == {"blockHash": self.block(50)["hash"], "requireCanonical": True}
        data = params[0]["data"]
        if data.startswith("0xb9a09fd5"):
            c = next(r["commitment"] for r in self.records if r["commitment"]["pool_address"][2:].zfill(64) == data[10:])
            raw = int(c["gauge_address"], 16)
            if self.mode == "wrong_gauge": raw = 1
        elif data.startswith("0xc4f08165"):
            c = next(r["commitment"] for r in self.records if r["commitment"]["gauge_address"][2:].zfill(64) == data[10:])
            raw = int(c["fees_contract"], 16)
            if self.mode == "wrong_fees": raw = 1
        elif data == "0x1be05289":
            raw = 1 if self.mode == "wrong_duration" else 604800
        else:
            c = next(r["commitment"] for r in self.records if r["commitment"]["fees_contract"] == params[0]["to"])
            start = int(datetime.fromisoformat(c["target_start_utc"]).timestamp())
            assert data == "0x92777b29" + c["token_address"][2:].zfill(64) + f"{start:064x}"
            raw = int(c["predicted_raw"]) * (2 if self.mode == "forecast_miss" else 1)
        return "0x12" if self.mode == "bad_abi" else "0x" + f"{raw:064x}"


def test_pre_epoch_collection_makes_no_network_calls(records):
    def forbidden(): raise AssertionError("RPC was constructed before target end")
    payload = collect_pilot(records, NOW, forbidden)
    assert payload["rpc_calls"] == 0
    assert {r["status"] for r in payload["results"]} == {"pending"}


def test_successful_five_pool_collection_and_archive(records, tmp_path):
    rpc = FakeRPC(records)
    end = datetime.fromisoformat(records[0]["commitment"]["target_end_utc"])
    payload = collect_pilot(records, end, lambda: rpc)
    assert all(r["status"] == "collected_local" for r in payload["results"])
    assert all(r["assessment"]["forecast_matched"] for r in payload["results"])
    assert rpc.calls < 40  # One shared boundary search for the five pools.
    target = save_observation(payload, tmp_path)
    before = target.read_bytes()
    assert save_observation(payload, tmp_path) == target
    assert target.read_bytes() == before
    loaded = load_observations(records, end, tmp_path)
    assert len(loaded["valid"]) == 5 and loaded["invalid_snapshots"] == 0
    assert all(not r["genlayer_consensus"] for r in loaded["valid"].values())


@pytest.mark.parametrize("mode", ["wrong_chain", "unfinalized", "bad_parent", "wrong_number", "wrong_gauge", "wrong_fees", "wrong_duration", "bad_abi", "unavailable", "budget", "reorg"])
def test_invalid_provider_data_is_not_published(records, mode):
    rpc = FakeRPC(records, mode)
    end = datetime.fromisoformat(records[0]["commitment"]["target_end_utc"])
    payload = collect_pilot(records, end, lambda: rpc)
    assert all(r["status"] == "insufficient_data" for r in payload["results"])
    assert all("evidence" not in r for r in payload["results"])
    assert payload["network_consensus"] is False


def test_miss_is_distinct_from_missing_data(records):
    end = datetime.fromisoformat(records[0]["commitment"]["target_end_utc"])
    payload = collect_pilot(records, end, lambda: FakeRPC(records, "forecast_miss"))
    assert all(r["status"] == "collected_local" and not r["assessment"]["forecast_matched"] for r in payload["results"])


def test_corrupt_and_future_observations_are_rejected(records, tmp_path):
    end = datetime.fromisoformat(records[0]["commitment"]["target_end_utc"])
    payload = collect_pilot(records, end, lambda: FakeRPC(records))
    target = save_observation(payload, tmp_path)
    assert not load_observations(records, NOW, tmp_path)["valid"]
    packet = json.loads(target.read_text())
    packet["payload"]["results"][0]["evidence"]["actual_raw"] = "999"
    target.write_text(json.dumps(packet))
    loaded = load_observations(records, end, tmp_path)
    assert loaded["invalid_snapshots"] == 1 and not loaded["valid"]


def test_forged_evidence_is_rechecked_even_with_recomputed_digest(records, tmp_path):
    end = datetime.fromisoformat(records[0]["commitment"]["target_end_utc"])
    payload = collect_pilot(records, end, lambda: FakeRPC(records))
    payload["results"][0]["evidence"]["chain_id"] = 1
    save_observation(payload, tmp_path)
    loaded = load_observations(records, end, tmp_path)
    assert loaded["invalid_snapshots"] == 1 and not loaded["valid"]


def test_later_failed_attempt_does_not_erase_prior_observation(records, tmp_path):
    end = datetime.fromisoformat(records[0]["commitment"]["target_end_utc"])
    save_observation(collect_pilot(records, end, lambda: FakeRPC(records)), tmp_path)
    save_observation(collect_pilot(records, end + timedelta(hours=1), lambda: FakeRPC(records, "unavailable")), tmp_path)
    loaded = load_observations(records, end + timedelta(hours=2), tmp_path)
    assert len(loaded["valid"]) == 5
    assert all(r["collection_status"] == "insufficient_data" for r in loaded["latest"].values())


def test_digest_mismatch_stops_before_network(records):
    records[0]["commitment"]["predicted_raw"] = "1"
    with pytest.raises(EvidenceError, match="commitment_digest_mismatch"):
        collect_pilot(records, NOW, lambda: None)


def test_read_only_rpc_blocks_transactions():
    rpc = ReadOnlyRPC("https://example.invalid/private-key-in-query")
    with patch("p10_evidence.urlopen") as transport:
        for method in ("eth_sendRawTransaction", "eth_sendTransaction", "personal_sign", "debug_traceCall"):
            with pytest.raises(EvidenceError, match="write_rpc_forbidden"):
                rpc.call(method, [])
        transport.assert_not_called()
    assert rpc.calls == 0


def test_rpc_errors_do_not_expose_credentials():
    from urllib.error import URLError
    rpc = ReadOnlyRPC("https://example.invalid/?secret=NEVER_LOG_THIS")
    with patch("p10_evidence.urlopen", side_effect=URLError("https://secret-provider/NEVER_LOG_THIS")):
        with pytest.raises(EvidenceError) as caught: rpc.call("eth_chainId", [])
    assert str(caught.value) == "rpc_transport_unavailable"


def test_observation_existing_content_is_never_overwritten(records, tmp_path):
    payload = collect_pilot(records, NOW, lambda: None)
    target = save_observation(payload, tmp_path)
    target.write_text("tampered")
    with pytest.raises(EvidenceError, match="observation_collision_or_tampering"):
        save_observation(payload, tmp_path)
    assert target.read_text() == "tampered"


def test_status_api_accepts_only_matching_completed_local_observations(tmp_path):
    from p10_pilot_status import load_pilot_status
    real = load_pilot_status(NOW, observations=tmp_path)["forecasts"]
    end = datetime.fromisoformat(real[0]["commitment"]["target_end_utc"])
    save_observation(collect_pilot(real, end, lambda: FakeRPC(real)), tmp_path)
    before = load_pilot_status(NOW, observations=tmp_path)
    assert all(r["actual_raw"] is None for r in before["forecasts"])
    after = load_pilot_status(end, observations=tmp_path)
    assert all(r["status"] == "locally_evaluated" and r["actual_raw"] == r["commitment"]["predicted_raw"] for r in after["forecasts"])
    assert not after["network_consensus"]


@pytest.mark.parametrize("message", [[], {"jsonrpc":"1.0","id":1,"result":"0x2105"}, {"jsonrpc":"2.0","id":True,"result":"0x2105"}, {"jsonrpc":"2.0","id":2,"result":"0x2105"}, {"jsonrpc":"2.0","id":1,"error":{"code":-32000}}, {"jsonrpc":"2.0","id":1}])
def test_json_rpc_identity_is_checked(message):
    class Response:
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def read(self,n): return json.dumps(message).encode()
    with patch("p10_evidence.urlopen",return_value=Response()):
        with pytest.raises(EvidenceError,match="rpc_invalid_response"):
            ReadOnlyRPC("https://example.invalid").call("eth_chainId",[])


def test_oversized_response_is_rejected():
    from p10_evidence import MAX_RESPONSE_BYTES
    class Response:
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def read(self,n): return b"x"*n
    with patch("p10_evidence.urlopen",return_value=Response()):
        with pytest.raises(EvidenceError,match="rpc_response_too_large"):
            ReadOnlyRPC("https://example.invalid").call("eth_chainId",[])


def test_transport_budget_and_credentials_configuration():
    with pytest.raises(EvidenceError,match="invalid_rpc_configuration"):
        ReadOnlyRPC("https://username:password@example.invalid")
    rpc=ReadOnlyRPC("https://example.invalid",max_calls=0)
    with patch("p10_evidence.urlopen") as transport:
        with pytest.raises(EvidenceError,match="rpc_budget_exhausted"):rpc.call("eth_chainId",[])
        transport.assert_not_called()


def test_transient_wsl_sharing_denial_retries_without_hiding_persistent_errors():
    from p10_evidence import local_bytes
    with patch("pathlib.Path.read_bytes",side_effect=[PermissionError(),PermissionError(),b"saved"]):
        with patch("p10_evidence.time.sleep"):assert local_bytes("unused")==b"saved"
    with patch("pathlib.Path.read_bytes",side_effect=PermissionError()):
        with patch("p10_evidence.time.sleep"):
            with pytest.raises(PermissionError):local_bytes("unused")
