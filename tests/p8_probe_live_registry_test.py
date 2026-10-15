"""P8.3 offline-only regression tests for bounded, pinned Voter pilot."""
import contextlib
import io
import json
import sys
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import p8_probe_live_registry as probe  # noqa: E402


def old(i, pool, gauge):
    return {"index": i, "address": pool, "gauge_address": gauge}


A = "0x" + "1" * 40
B = "0x" + "2" * 40
C = "0x" + "3" * 40
D = "0x" + "4" * 40
E = "0x" + "5" * 40
F = "0x" + "6" * 40
G = "0x" + "7" * 40
H = "0x" + "8" * 40


class P8ProbeTests(unittest.TestCase):
    def test_sample_bounds_and_duplicate_guards(self):
        self.assertEqual(probe.parse_indexes("1930,1774,1414"), [1930, 1774, 1414])
        for value in ("", "01", "-1", "1,1", "x", "1,2,3,4,5,6"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    probe.parse_indexes(value)

    def test_must_match_archived_addresses(self):
        self.assertEqual(probe.old_sample([old(1930, A, B)], [1930])[0]["old_pool"], A)
        with self.assertRaisesRegex(ValueError, "not found"):
            probe.old_sample([old(1930, A, B)], [1774])
        with self.assertRaisesRegex(ValueError, "malformed"):
            probe.old_sample([old(1930, A, "bad")], [1930])

    def test_same_pinned_block_active_inactive_and_address_mismatch(self):
        samples = probe.old_sample([old(1930, A, B), old(1774, C, D),
                                    old(1414, E, F)], [1930, 1774, 1414])
        tags = []
        def address_read(signature, argument, tag):
            tags.append(tag)
            if signature == "pools(uint256)":
                return {1930: A, 1774: C, 1414: G}[argument]
            if signature == "gauges(address)":
                return {A: B, C: D}[argument]
            raise AssertionError(signature)

        def uint_read(signature, argument, tag):
            tags.append(tag)
            if signature == "length()":
                return 2200
            if signature == "isAlive(address)":
                return {B: 1, D: 0}[argument]
            if signature == "weights(address)":
                return {A: 123}[argument]
            raise AssertionError(signature)

        def rpc(method, _params):
            return {"eth_chainId": hex(8453), "eth_blockNumber": hex(52650000)}[method]

        with patch.object(probe, "rpc", side_effect=rpc):
            result = probe.observe_at_one_block(
                samples, lambda fn, _label: fn(), address_read, uint_read
            )
        self.assertEqual(result["pinned_block"], 52650000)
        self.assertTrue(all(tag == hex(52650000) for tag in tags))
        self.assertEqual(
            [x["status"] for x in result["sample"]],
            ["ACTIVE_SAME_GAUGE", "CURRENT_GAUGE_INACTIVE",
             "POOL_ADDRESS_CHANGED"],
        )
        self.assertEqual(result["sample"][0]["current_weight_raw"], "123")
        self.assertFalse(result["sample"][1]["is_alive"])
        self.assertIsNone(result["sample"][2]["is_alive"])

    def test_rejects_wrong_chain_and_stale_block(self):
        sample = probe.old_sample([old(1930, A, B)], [1930])
        def blocked(_signature, _argument, _tag):
            raise AssertionError("No calls should reach registry after wrong chain/block")
        for chain, block in ((1, 53000000), (8453, 52595092)):
            with self.subTest(chain=chain, block=block):
                def rpc(method, _params):
                    return {"eth_chainId": hex(chain),
                            "eth_blockNumber": hex(block)}[method]
                with patch.object(probe, "rpc", side_effect=rpc):
                    with self.assertRaises(RuntimeError):
                        probe.observe_at_one_block(
                            sample, lambda fn, _label: fn(), blocked, blocked
                        )

    def test_preview_requires_no_rpc_and_no_saved_writes(self):
        sample = [old(1930, A, B), old(1774, C, D), old(1414, E, F)]
        dataset = {"chain_id": 8453, "pools": sample}
        buf = io.StringIO()
        with (patch.object(probe, "DATA", SimpleNamespace(
                    read_text=lambda **_kwargs: json.dumps(dataset))),
              patch.object(probe, "validate_research", side_effect=lambda d: d),
              patch.object(probe, "rpc", side_effect=AssertionError("RPC forbidden")),
              contextlib.redirect_stdout(buf)):
            probe.main([])
        text = buf.getvalue()
        self.assertIn("OFFLINE PREVIEW: NO RPC calls", text)
        self.assertIn("NO writes", text)
        self.assertNotIn("ACTIVE_SAME_GAUGE", text)

    def test_source_does_not_modify_data_or_schedule_jobs(self):
        source = (ROOT / "scripts" / "p8_probe_live_registry.py").read_text(
            encoding="utf-8"
        )
        for disallowed in ("save_atomic(", ".write_text(", ".write_bytes(",
                           ".mkdir(", "subprocess.run(", "requests.get(",
                           "localStorage"):
            self.assertNotIn(disallowed, source)
        for required in ("--live", "MAX_SAMPLE = 5", "newer than the historical",
                         "ONLY", "928-pool active count UNKNOWN"):
            self.assertIn(required, source)


if __name__ == "__main__":
    unittest.main()
