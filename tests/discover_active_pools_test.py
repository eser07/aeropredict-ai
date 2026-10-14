"""Offline regression tests for resumable Aerodrome pool discovery.

No real RPC calls, wallet, external network or production data files.
Run: python -m unittest discover_active_pools_test
"""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "discover_active_pools_base.py"
SPEC = importlib.util.spec_from_file_location("discover_active_pools_base", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)

POOL = [f"0x{x:040x}" for x in range(101, 106)]
GAUGE = [f"0x{x:040x}" for x in range(201, 206)]
ACTIVE_INDEXES = {0, 2, 4}


class TestDiscovery(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        data = Path(self.tmp.name)
        p = patch.multiple(
            module,
            DATA=data,
            CHECKPOINT=data / "checkpoint.json",
            RESULT=data / "discovered.json",
        )
        p.start()
        self.addCleanup(p.stop)
        r = patch.object(module, "rpc", side_effect=self.fake_rpc)
        u = patch.object(module, "read_uint", side_effect=self.fake_uint)
        a = patch.object(module, "read_address", side_effect=self.fake_address)
        r.start()
        u.start()
        a.start()
        self.addCleanup(r.stop)
        self.addCleanup(u.stop)
        self.addCleanup(a.stop)

    @staticmethod
    def fake_rpc(method, _params):
        return hex(8453) if method == "eth_chainId" else hex(9001)

    @staticmethod
    def fake_uint(signature, argument, tag):
        if tag != hex(9001):
            raise RuntimeError("Wrong pinned block")
        if signature == "length()":
            return 5
        if signature == "totalWeight()":
            return 500
        if signature == "isAlive(address)":
            return 1 if argument in (GAUGE[i] for i in ACTIVE_INDEXES) else 0
        if signature == "weights(address)":
            return (POOL.index(argument) + 1) * 20
        raise RuntimeError("Unexpected call: " + signature)

    @staticmethod
    def fake_address(signature, argument, tag):
        if tag != hex(9001):
            raise RuntimeError("Wrong pinned block")
        if signature == "pools(uint256)":
            return POOL[argument]
        if signature == "gauges(address)":
            return GAUGE[POOL.index(argument)]
        raise RuntimeError("Unexpected call: " + signature)

    def test_resume_and_complete_then_idempotent(self):
        first = module.run_scan(page_size=2, max_pages=1, delay=0)
        self.assertEqual(first["next_index"], 2)
        self.assertFalse(first["complete"])
        self.assertEqual(first["active_pool_count"], 1)
        self.assertFalse(module.RESULT.exists())
        second = module.run_scan(page_size=2, max_pages=2, delay=0)
        self.assertEqual(second["next_index"], 5)
        self.assertTrue(second["complete"])
        self.assertEqual(second["active_pool_count"], 3)
        saved = json.loads(module.RESULT.read_text())
        self.assertEqual([p["index"] for p in saved["pools"]], [0, 2, 4])
        self.assertEqual(saved["snapshot_block_number"], 9001)
        self.assertEqual(saved["coverage_percent"], 100)
        again = module.run_scan(page_size=2, max_pages=1, delay=0)
        self.assertTrue(again["complete"])

    def test_rpc_error_does_not_advance_partially_completed_page(self):
        original = module.read_uint
        module.run_scan(page_size=2, max_pages=1, delay=0)

        def fail_on_third_pool(signature, argument, tag):
            if signature == "weights(address)" and argument == POOL[2]:
                raise RuntimeError("Simulated rate limit")
            return original(signature, argument, tag)

        with patch.object(module, "read_uint", side_effect=fail_on_third_pool):
            with self.assertRaisesRegex(RuntimeError, "Simulated rate limit"):
                module.run_scan(page_size=2, max_pages=1, delay=0)
        checkpoint = json.loads(module.CHECKPOINT.read_text())
        self.assertEqual(checkpoint["next_index"], 2)
        self.assertEqual(checkpoint["active_pool_count"], 1)
        self.assertFalse(module.RESULT.exists())
        resumed = module.run_scan(page_size=2, max_pages=2, delay=0)
        self.assertTrue(resumed["complete"])

    def test_rejects_tampered_checkpoint(self):
        module.run_scan(page_size=2, max_pages=1, delay=0)
        progress = json.loads(module.CHECKPOINT.read_text())
        progress["active_pool_count"] = 999
        module.CHECKPOINT.write_text(json.dumps(progress))
        with self.assertRaisesRegex(ValueError, "Active pool count mismatch"):
            module.run_scan(page_size=2, max_pages=1, delay=0)


if __name__ == "__main__":
    unittest.main()
