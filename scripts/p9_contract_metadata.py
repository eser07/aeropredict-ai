"""Attach a saved, block-pinned special-contract observation to P9 pairs.

No RPC runs here. Hash checks bind the saved observation to reviewed source and
runtime bytes; they are not cryptographic chain proofs or GenLayer consensus.
"""
import copy
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

METADATA = Path(__file__).resolve().parents[1] / "research/p9_unified/special_contracts.json"
ADDRESS = "0x97cd4eb683e29695dc93eec95d47d4e7a35e2112"
BLOCK_HASH = "0x2ec194e84e38772dff217ab5139469b7f200d199e403162f378ed1105157fa9b"
SOURCE_SHA256 = "1abb9373367e32d88047f853946fc2a8a782c56c23ce4423f5e7a2e79003a352"
RUNTIME_SHA256 = "02ed94e494b4eb603354665d259df0726b16f115a361c2a3174a964a61e24514"
INVENTORY_SHA256 = "7db12533cca67e41ca488821c218607e76e534f4e023a3b07c29fbc185a429df"
SOURCE_URL = "https://basescan.org/address/" + ADDRESS + "#code"


def utc(value):
    if not isinstance(value, str):
        raise ValueError("Missing metadata timestamp")
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None or stamp.utcoffset() != timezone.utc.utcoffset(stamp):
        raise ValueError("Metadata timestamp must be UTC")
    return stamp


def annotate_special_contracts(pairs, research, metadata):
    if (metadata.get("schema_version") != 1 or metadata.get("chain_id") != 8453 or
        metadata.get("inventory_sha256") != INVENTORY_SHA256 or
        research.get("inventory_sha256") != INVENTORY_SHA256 or
        research.get("chain_id") != 8453 or pairs.get("chain_id") != 8453):
        raise ValueError("Special-contract inventory mismatch")
    entries = metadata.get("entries")
    if not isinstance(entries, list) or len(entries) != 1 or not isinstance(entries[0], dict):
        raise ValueError("Expected one reviewed special-contract observation")
    entry = entries[0]
    fixed = {"index": 1130, "address": ADDRESS, "kind": "emission_sink_placeholder",
             "contract_name": "SinkPool", "token_pair_applicable": False, "abi": [],
             "source_path": "contracts/sink/SinkPool.sol", "verified_source_url": SOURCE_URL,
             "source_sha256": SOURCE_SHA256, "runtime_sha256": RUNTIME_SHA256,
             "block_number": 52731839, "block_hash": BLOCK_HASH, "block_hash_pinned": True,
             "block_timestamp_utc": "2026-10-17T16:03:45+00:00",
             "evidence_kind": "public_explorer_and_single_rpc_observation", "independent_consensus": False}
    if any(type(entry.get(k)) is not type(v) or entry[k] != v for k, v in fixed.items()):
        raise ValueError("Unexpected special-contract evidence")
    source = entry.get("source_code")
    code = entry.get("runtime_bytecode")
    if (not isinstance(source, str) or hashlib.sha256(source.encode()).hexdigest() != SOURCE_SHA256 or
        not isinstance(code, str) or re.fullmatch(r"0x(?:[0-9a-f]{2})+", code) is None or
        hashlib.sha256(bytes.fromhex(code[2:])).hexdigest() != RUNTIME_SHA256):
        raise ValueError("Special-contract content hash mismatch")
    page_hash = entry.get("public_page_sha256")
    if not isinstance(page_hash, str) or re.fullmatch(r"[0-9a-f]{64}", page_hash) is None:
        raise ValueError("Missing public source fingerprint")
    observed = utc(entry.get("observed_at_utc"))
    if not utc(entry["block_timestamp_utc"]) <= observed <= datetime.now(timezone.utc):
        raise ValueError("Invalid observation time")
    research_rows = [p for p in research.get("pools", []) if p.get("index") == 1130]
    pair_rows = [p for p in pairs.get("pools", []) if p.get("index") == 1130]
    if (len(research_rows) != 1 or len(pair_rows) != 1 or
        research_rows[0].get("address", "").lower() != ADDRESS or
        research_rows[0].get("inventory_snapshot_block") != entry["block_number"] or
        pair_rows[0].get("pool_address", "").lower() != ADDRESS or
        any(pair_rows[0].get(k) is not None for k in
            ("token0_address", "token1_address", "token0_symbol", "token1_symbol", "pair_label"))):
        raise ValueError("Special-contract pool identity or token pair conflict")
    result = copy.deepcopy(pairs)
    row = next(p for p in result["pools"] if p["index"] == 1130)
    row["contract_name"] = entry["contract_name"]
    row["contract_classification"] = copy.deepcopy(entry)
    return result


def load_special_contracts(pairs, research):
    return annotate_special_contracts(pairs, research, json.loads(METADATA.read_bytes()))
