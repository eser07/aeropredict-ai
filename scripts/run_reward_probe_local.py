#!/usr/bin/env python3
"""One-command read-only Base-to-GLSim Aerodrome reward integration check.

Requires GLSim running locally on 127.0.0.1:4000.
Deploys a fresh contract to GLSim via sim_deploy, performs sim_call and
sim_read, and independently checks the SAME historical Base block through
the existing curl-based on-chain reader. This bypasses full GLSim consensus.
No wallet or private key is used.
"""
import json
import subprocess
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from reward_tokens import read_call  # noqa: E402
from reward_epochs import SELECTOR_TOKEN_REWARDS  # noqa: E402

GLSIM_RPC = "http://127.0.0.1:4000/api"
BASE_BLOCK = 52571849
EPOCH_START = 1791417600  # 2026-10-08 00:00:00 UTC
FEES_CONTRACT = "0x958a5612390bb4134e1e7505c7cb6b0652941174"
USDBC = "0xd9aaec86b65d86f6a7b5b1b0c42ffa531710b6ca"
SELECTOR = "0x92777b29"


def sim_call(method, params, timeout=75):
    payload = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": method, "params": params,
    }).encode()
    request = Request(
        GLSIM_RPC, data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:
        answer = json.loads(response.read().decode())
    if "error" in answer:
        raise RuntimeError(f"GLSim {method}: {answer['error']}")
    if "result" not in answer:
        raise RuntimeError(f"GLSim {method} gave no result")
    return answer["result"]


def main():
    if SELECTOR_TOKEN_REWARDS != SELECTOR:
        raise RuntimeError(
            f"Selector mismatch: computed {SELECTOR_TOKEN_REWARDS}, "
            f"contract expects {SELECTOR}"
        )
    contract_path = ROOT / "contracts" / "AerodromeRewardProbe.py"
    if not contract_path.is_file():
        raise RuntimeError("Missing AerodromeRewardProbe.py; git pull first")

    print("1/4 Deploying AerodromeRewardProbe to local GLSim...", flush=True)
    deployed = sim_call("sim_deploy", {"code_path": str(contract_path)})
    addr = deployed["contract_address"]
    print(f"     GLSim address: {addr}", flush=True)

    print(
        f"2/4 Fetching USDbC FEES allocation at Base block {BASE_BLOCK} "
        "through the GenLayer contract...",
        flush=True,
    )
    sim_call("sim_call", {
        "to": addr, "method": "snapshot_reward",
        "args": [BASE_BLOCK, EPOCH_START],
    })
    stored = sim_call("sim_read", {"to": addr, "method": "get_snapshot"})
    snapshot = json.loads(stored["result"])
    from_glsim = int(snapshot["reward_raw"])
    if snapshot["base_block"] != BASE_BLOCK or snapshot["epoch_start"] != EPOCH_START:
        raise RuntimeError(f"Wrong saved epoch/block in GLSim: {snapshot}")
    print(
        f"3/4 GenLayer recorded: {from_glsim} raw USDbC "
        f"({from_glsim / 1_000_000:.6f} USDbC)",
        flush=True,
    )

    print("4/4 Independently reading the same Base block...", flush=True)
    data = SELECTOR + USDBC[2:].zfill(64) + f"{EPOCH_START:064x}"
    direct_raw = int(read_call(FEES_CONTRACT, data, hex(BASE_BLOCK)), 16)
    print(f"     Direct Base: {direct_raw} raw USDbC", flush=True)
    if from_glsim != direct_raw:
        raise RuntimeError(
            f"Mismatch! GLSim: {from_glsim}; direct Base: {direct_raw}"
        )
    print("PASS: GLSim GenLayer reward snapshot matches Base at pinned block.")
    print("NOTE: This is NOT proof of multi-validator consensus or voting APR.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, RuntimeError,
            subprocess.SubprocessError, HTTPError, URLError,
            json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
