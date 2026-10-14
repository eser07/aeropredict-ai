#!/usr/bin/env python3
"""Compare a live Base Aerodrome FEES allocation read through GenLayer/GLSim
with an independent, near-contemporaneous Base eth_call at 'latest'.

No archive access, wallet, private key or actual chain transaction needed.
These reads are NOT pinned to one block: changing rewards can cause mismatch.
The GLSim sim_call route bypasses simulated multi-validator consensus.
"""
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from reward_tokens import read_call  # noqa: E402
from reward_epochs import SELECTOR_TOKEN_REWARDS  # noqa: E402

GLSIM = "http://127.0.0.1:4000/api"
FEES = "0x958a5612390bb4134e1e7505c7cb6b0652941174"
USDBC = "0xd9aaec86b65d86f6a7b5b1b0c42ffa531710b6ca"
EXPECTED_SELECTOR = "0x92777b29"
EPOCH_SECONDS = 604800


def local_rpc(method, params):
    body = json.dumps({
        "jsonrpc": "2.0", "id": 1,
        "method": method, "params": params,
    }).encode()
    req = Request(GLSIM, data=body, headers={
        "Content-Type": "application/json",
    }, method="POST")
    with urlopen(req, timeout=90) as reply:
        response = json.loads(reply.read())
    if "error" in response:
        raise RuntimeError(f"GLSim {method}: {response['error']}")
    if "result" not in response:
        raise RuntimeError(f"GLSim {method} returned no result")
    return response["result"]


def main():
    if SELECTOR_TOKEN_REWARDS != EXPECTED_SELECTOR:
        raise RuntimeError(
            f"Incorrect function selector: {SELECTOR_TOKEN_REWARDS}"
        )
    epoch = (int(time.time()) // EPOCH_SECONDS) * EPOCH_SECONDS
    epoch_date = datetime.fromtimestamp(epoch, timezone.utc).isoformat()
    print(f"Target Aerodrome epoch: {epoch_date} (UTC)", flush=True)
    contract = ROOT / "contracts" / "AerodromeLatestRewardProbe.py"
    print("1/4 Deploying latest-state probe to local GLSim...", flush=True)
    addr = local_rpc("sim_deploy", {
        "code_path": str(contract),
    })["contract_address"]
    print(f"     GLSim contract: {addr}", flush=True)

    print("2/4 Reading Base 'latest' through GenLayer code...", flush=True)
    local_rpc("sim_call", {
        "to": addr,
        "method": "read_reward_latest",
        "args": [epoch],
    })
    stored = local_rpc("sim_read", {
        "to": addr, "method": "get_reading",
    })
    reading = json.loads(stored["result"])
    if not reading.get("completed") or int(reading["epoch_start"]) != epoch:
        raise RuntimeError(f"Invalid GenLayer reading: {reading}")
    result_gl = int(reading["raw"])
    print(
        f"3/4 GenLayer allocation: {result_gl} raw "
        f"({result_gl / 1_000_000:.6f} USDbC)",
        flush=True,
    )

    print("4/4 Comparing with direct Base RPC at 'latest'...", flush=True)
    calldata = EXPECTED_SELECTOR + USDBC[2:].lower().zfill(64) + f"{epoch:064x}"
    result_direct = int(read_call(FEES, calldata, "latest"), 16)
    print(
        f"     Direct allocation: {result_direct} raw "
        f"({result_direct / 1_000_000:.6f} USDbC)",
        flush=True,
    )

    if result_gl != result_direct:
        raise RuntimeError(
            "Latest-state values differ. This can happen if the Aerodrome "
            "allocation changed between unpinned reads. Re-test or use an "
            "archive RPC with the same fixed Base block; do NOT claim an "
            f"exact cross-block proof. GenLayer={result_gl}, Base={result_direct}"
        )
    print("PASS: GenLayer/GLSim and direct Base report the same latest-state allocation.")
    print(
        "LIMITATION: The calls are not block-pinned and GLSim sim_call "
        "does not prove independent validator consensus."
    )


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, RuntimeError,
            subprocess.SubprocessError, HTTPError, URLError,
            json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
