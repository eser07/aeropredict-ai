"""P10 read-only evidence collection. No wallets, signing, or write RPC methods.

Saved observations are local provider claims, not GenLayer attestations.
Historical datasets and immutable forecast registrations are never overwritten.
"""
import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from p10_forecast_v2 import ROOT, canonical_hash, evaluate_v2, validate_commitment

VOTER = "0x16613524e02ad97edfef371bc883f2f5d6c480a5"
READ_METHODS = frozenset({"eth_chainId", "eth_getBlockByNumber", "eth_call"})
OBSERVATIONS = ROOT / "research/p10_pilot/observations"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class EvidenceError(ValueError):
    """Safe fixed error code, never a provider response or credential-bearing URL."""


class ReadOnlyRPC:
    def __init__(self, endpoint=None, timeout=8, max_calls=96, max_seconds=45):
        self._endpoint = endpoint or os.getenv("BASE_RPC_URL", "https://mainnet.base.org")
        parsed = urlsplit(self._endpoint)
        if not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise EvidenceError("invalid_rpc_configuration")
        if parsed.scheme != "https" and not (
            parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
        ):
            raise EvidenceError("invalid_rpc_configuration")
        self.timeout = timeout
        self.max_calls = max_calls
        self.calls = 0
        self.deadline = time.monotonic() + max_seconds

    def call(self, method, params):
        if method not in READ_METHODS:
            raise EvidenceError("write_rpc_forbidden")
        remaining = self.deadline - time.monotonic()
        if self.calls >= self.max_calls or remaining <= 0:
            raise EvidenceError("rpc_budget_exhausted")
        self.calls += 1
        payload = {"jsonrpc": "2.0", "id": self.calls, "method": method, "params": params}
        request = Request(self._endpoint, data=json.dumps(payload).encode("utf-8"),
                          headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urlopen(request, timeout=min(self.timeout, remaining)) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise EvidenceError("rpc_response_too_large")
            message = json.loads(raw)
        except EvidenceError:
            raise
        except HTTPError:
            raise EvidenceError("rpc_http_error") from None
        except (URLError, OSError, TimeoutError):
            raise EvidenceError("rpc_transport_unavailable") from None
        except (ValueError, UnicodeError):
            raise EvidenceError("rpc_invalid_json") from None
        if (not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or
                type(message.get("id")) is not int or message["id"] != self.calls or
                "error" in message or "result" not in message):
            raise EvidenceError("rpc_invalid_response")
        return message["result"]


def quantity(value):
    if not isinstance(value, str) or not re.fullmatch(r"0x(?:0|[1-9a-fA-F][0-9a-fA-F]*)", value):
        raise EvidenceError("malformed_hex_quantity")
    number = int(value, 16)
    if number >= 2**64:
        raise EvidenceError("quantity_out_of_bounds")
    return number


def header(block, expected_number=None):
    if not isinstance(block, dict):
        raise EvidenceError("missing_block")
    number = quantity(block.get("number"))
    timestamp = quantity(block.get("timestamp"))
    if expected_number is not None and number != expected_number:
        raise EvidenceError("block_number_mismatch")
    for key in ("hash", "parentHash"):
        if not isinstance(block.get(key), str) or not re.fullmatch(r"0x[0-9a-fA-F]{64}", block[key]):
            raise EvidenceError("malformed_block_hash")
    return {"number": number, "timestamp": timestamp, "hash": block["hash"].lower(),
            "parent_hash": block["parentHash"].lower()}


def boundary_blocks(rpc, boundary):
    """Binary search bounded by the provider's finalized head, then verify adjacency."""
    if quantity(rpc.call("eth_chainId", [])) != 8453:
        raise EvidenceError("wrong_chain")
    finalized = header(rpc.call("eth_getBlockByNumber", ["finalized", False]))
    if finalized["timestamp"] < boundary:
        raise EvidenceError("boundary_not_finalized")
    low = header(rpc.call("eth_getBlockByNumber", ["0x0", False]), 0)
    if low["timestamp"] >= boundary:
        raise EvidenceError("boundary_before_genesis")
    high = finalized
    while high["number"] - low["number"] > 1:
        number = (low["number"] + high["number"]) // 2
        candidate = header(rpc.call("eth_getBlockByNumber", [hex(number), False]), number)
        if not low["timestamp"] <= candidate["timestamp"] <= high["timestamp"]:
            raise EvidenceError("nonmonotonic_block_timestamps")
        if candidate["timestamp"] < boundary:
            low = candidate
        else:
            high = candidate
    if high["parent_hash"] != low["hash"] or not low["timestamp"] < boundary <= high["timestamp"]:
        raise EvidenceError("boundary_parent_mismatch")
    return high, low, finalized


def abi_word(rpc, target, data, pinned):
    result = rpc.call("eth_call", [{"to": target, "data": data}, pinned])
    if not isinstance(result, str) or not re.fullmatch(r"0x[0-9a-fA-F]{64}", result):
        raise EvidenceError("malformed_abi_word")
    return result.lower()


def mapped_address(rpc, selector, argument, pinned):
    word = abi_word(rpc, VOTER, selector + argument[2:].zfill(64), pinned)
    if int(word[2:26], 16) != 0:
        raise EvidenceError("malformed_abi_address")
    return "0x" + word[-40:]


def collect_one(record, rpc, now, context):
    c = record["commitment"]
    current, parent, finalized = context
    pinned = {"blockHash": current["hash"], "requireCanonical": True}
    if mapped_address(rpc, "0xb9a09fd5", c["pool_address"], pinned) != c["gauge_address"]:
        raise EvidenceError("pool_gauge_mismatch")
    if mapped_address(rpc, "0xc4f08165", c["gauge_address"], pinned) != c["fees_contract"]:
        raise EvidenceError("gauge_fees_mismatch")
    if int(abi_word(rpc, c["fees_contract"], "0x1be05289", pinned), 16) != 604800:
        raise EvidenceError("unsupported_reward_duration")
    start = int(datetime.fromisoformat(c["target_start_utc"]).timestamp())
    data = "0x92777b29" + c["token_address"][2:].zfill(64) + f"{start:064x}"
    actual = str(int(abi_word(rpc, c["fees_contract"], data, pinned), 16))
    recheck = header(rpc.call("eth_getBlockByNumber", [hex(current["number"]), False]), current["number"])
    if recheck != current:
        raise EvidenceError("canonical_block_changed")
    evidence = {key: c[key] for key in ("chain_id", "pool_address", "gauge_address",
                                       "fees_contract", "token_address", "target_start_utc")}
    evidence.update(block_number=current["number"], parent_number=parent["number"],
                    finalized_number=finalized["number"], block_hash=current["hash"],
                    parent_hash=parent["hash"], block_parent_hash=current["parent_hash"],
                    parent_timestamp=parent["timestamp"], block_timestamp=current["timestamp"],
                    actual_raw=actual)
    assessment = evaluate_v2(record, evidence, now)
    if assessment.get("status") != "locally_evaluated":
        raise EvidenceError("local_evidence_validation_failed")
    return {"pool_index": c["pool_index"], "commitment_sha256": record["commitment_sha256"],
            "status": "collected_local", "evidence": evidence, "assessment": assessment}


def collect_pilot(records, now=None, rpc_factory=ReadOnlyRPC):
    """Validate all registrations before network work; do not call RPC before target end."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise EvidenceError("naive_collection_clock")
    if not isinstance(records, list) or len(records) != 5:
        raise EvidenceError("expected_five_pilot_records")
    if {r.get("commitment", {}).get("pool_index") for r in records} != {64, 35, 0, 1, 4}:
        raise EvidenceError("pilot_pool_identity_mismatch")
    for record in records:
        validate_commitment(record["commitment"])
        if record["commitment_sha256"] != canonical_hash(record["commitment"]):
            raise EvidenceError("commitment_digest_mismatch")
    results = []
    rpc = None
    contexts = {}
    for record in records:
        c = record["commitment"]
        base = {"pool_index": c["pool_index"], "commitment_sha256": record["commitment_sha256"]}
        end = datetime.fromisoformat(c["target_end_utc"])
        if now < end:
            results.append({**base, "status": "pending", "reason": "epoch_not_completed"})
            continue
        try:
            if rpc is None:
                rpc = rpc_factory()
            boundary = int(end.timestamp())
            if boundary not in contexts:
                try:
                    contexts[boundary] = boundary_blocks(rpc, boundary)
                except EvidenceError as error:
                    contexts[boundary] = error
            if isinstance(contexts[boundary], EvidenceError):
                raise contexts[boundary]
            results.append(collect_one(record, rpc, now, contexts[boundary]))
        except EvidenceError as error:
            results.append({**base, "status": "insufficient_data", "reason": str(error)})
    return {"schema_version": 1, "mode": "read_only_local_collection", "collected_at_utc": now.isoformat(),
            "results": results, "rpc_calls": getattr(rpc, "calls", 0), "network_consensus": False,
            "independent_timestamp": False, "paid_transactions": 0}


def save_observation(payload, folder=OBSERVATIONS):
    """Content-addressed exclusive creation; an identical snapshot is safely reused."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    digest = canonical_hash(payload)
    packet = {"payload": payload, "sha256": digest}
    target = folder / (digest + ".json")
    text = json.dumps(packet, indent=2, ensure_ascii=False)
    try:
        with target.open("x", encoding="utf-8") as stream:
            stream.write(text)
    except FileExistsError:
        if target.read_text(encoding="utf-8") != text:
            raise EvidenceError("observation_collision_or_tampering") from None
    return target


def local_bytes(path):
    """Retry only transient Windows/WSL sharing denials, then preserve the failure."""
    for attempt in range(3):
        try:
            return Path(path).read_bytes()
        except PermissionError:
            if attempt == 2:
                raise
            time.sleep(0.03 * (attempt + 1))


def load_observations(records, now=None, folder=OBSERVATIONS):
    """Re-evaluate saved local evidence; ignore corrupt snapshots and future clocks."""
    now = now or datetime.now(timezone.utc)
    known = {r["commitment_sha256"]: r for r in records}
    latest = {}
    valid = {}
    invalid = 0
    paths = list(Path(folder).glob("*.json"))
    # Keep reads bounded. A larger archive can be reviewed separately.
    paths = sorted(paths, key=lambda path: path.stat().st_mtime, reverse=True)[:256]
    for path in paths:
        try:
            if path.stat().st_size > MAX_RESPONSE_BYTES:
                raise ValueError("oversized_snapshot")
            packet = json.loads(local_bytes(path))
            payload = packet["payload"]
            digest = canonical_hash(payload)
            if packet["sha256"] != digest or path.stem != digest:
                raise ValueError("snapshot_hash_mismatch")
            timestamp = datetime.fromisoformat(payload["collected_at_utc"])
            if timestamp.tzinfo is None or timestamp > now:
                raise ValueError("future_snapshot")
            rows = payload["results"]
            if (payload.get("schema_version") != 1 or
                    payload.get("mode") != "read_only_local_collection" or
                    payload.get("network_consensus") is not False or
                    not isinstance(rows, list) or len(rows) != 5 or
                    {r["commitment_sha256"] for r in rows} != set(known)):
                raise ValueError("snapshot_identity_mismatch")
            staged = []
            for row in rows:
                record = known[row["commitment_sha256"]]
                if row["pool_index"] != record["commitment"]["pool_index"]:
                    raise ValueError("snapshot_pool_mismatch")
                evaluation = None
                if row["status"] == "collected_local":
                    evaluation = evaluate_v2(record, row["evidence"], timestamp)
                    if evaluation["status"] != "locally_evaluated":
                        raise ValueError("invalid_local_evidence")
                elif row["status"] not in {"pending", "insufficient_data"}:
                    raise ValueError("invalid_collection_status")
                staged.append((row, evaluation))
            # Do not accept part of an invalid packet.
            for row, evaluation in staged:
                key = row["commitment_sha256"]
                info = {"collected_at_utc": timestamp.isoformat(), "snapshot_sha256": digest,
                        "collection_status": row["status"], "reason": row.get("reason")}
                if key not in latest or timestamp > latest[key][0]:
                    latest[key] = (timestamp, info)
                if evaluation and (key not in valid or timestamp > valid[key][0]):
                    valid[key] = (timestamp, {**info, **evaluation, "evidence": row["evidence"]})
        except (OSError, ValueError, KeyError, TypeError, OverflowError):
            invalid += 1
    return {"latest": {key: item[1] for key, item in latest.items()},
            "valid": {key: item[1] for key, item in valid.items()},
            "invalid_snapshots": invalid, "scanned_snapshots": len(paths)}


def main():
    from p10_pilot_status import load_pilot_status
    doc = load_pilot_status()
    # Use the checked registrations; the status fields never serve as chain evidence.
    payload = collect_pilot(doc["forecasts"])
    target = save_observation(payload)
    print(json.dumps({"saved_file": target.name, "rpc_calls": payload["rpc_calls"],
                      "statuses": {str(r["pool_index"]): r["status"] for r in payload["results"]}}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (EvidenceError, OSError, ValueError, KeyError, TypeError):
        raise SystemExit("Evidence collection unavailable; no historical data was modified") from None
