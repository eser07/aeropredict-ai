"""Offline regression tests for resumable Aerodrome pool discovery.

No real RPC calls, wallet, external network or production data files.
Run: python -m unittest discover -s tests -p "discover_active_pools_test.py"
"""
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
MODULE_PATH = SCRIPTS / "discover_active_pools_base.py"
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

    def test_automatic_scan_completes_all_pages_in_one_call(self):
        result = module.run_scan(page_size=2, max_pages=1, delay=0, until_complete=True)
        self.assertEqual(result["next_index"], 5)
        self.assertEqual(result["active_pool_count"], 3)
        self.assertTrue(result["complete"])
        self.assertTrue(module.RESULT.is_file())

    def test_temporary_http_429_retries_same_call(self):
        module.run_scan(page_size=2, max_pages=1, delay=0)
        original = module.read_uint
        hit_count = [0]

        def intermittent(signature, argument, tag):
            if signature == "weights(address)" and argument == POOL[2]:
                hit_count[0] += 1
                if hit_count[0] == 1:
                    raise subprocess.CalledProcessError(
                        22, ["curl"], stderr="curl: (22) The requested URL returned error: 429"
                    )
            return original(signature, argument, tag)

        with patch.object(module, "read_uint", side_effect=intermittent):
            with patch.object(module.time, "sleep") as sleep:
                result = module.run_scan(
                    page_size=2, max_pages=1, delay=0,
                    retry_attempts=2, retry_delay=1,
                )
        self.assertEqual(hit_count[0], 2)
        self.assertEqual(result["next_index"], 4)
        self.assertEqual(result["active_pool_count"], 2)
        sleep.assert_called_once_with(1)

    def test_http_403_archive_denial_stops_without_losing_page(self):
        module.run_scan(page_size=2, max_pages=1, delay=0)
        original = module.read_uint

        def archive_denial(signature, argument, tag):
            if signature == "length()":
                raise subprocess.CalledProcessError(
                    22, ["curl"], stderr="curl: (22) The requested URL returned error: 403"
                )
            return original(signature, argument, tag)

        with patch.object(module, "read_uint", side_effect=archive_denial):
            with patch.object(module.time, "sleep") as sleep:
                with self.assertRaisesRegex(RuntimeError, "HTTP 403"):
                    module.run_scan(page_size=2, max_pages=1, delay=0)
        sleep.assert_not_called()
        checkpoint = json.loads(module.CHECKPOINT.read_text())
        self.assertEqual(checkpoint["next_index"], 2)
        self.assertEqual(checkpoint["active_pool_count"], 1)
        self.assertFalse(module.RESULT.exists())

    def test_exclusive_lock_stops_second_scan(self):
        import fcntl
        module.DATA.mkdir(parents=True, exist_ok=True)
        with (module.DATA / ".pool_discovery.lock").open("a+") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                with self.assertRaisesRegex(RuntimeError, "already running"):
                    module.run_scan(page_size=2, max_pages=1, delay=0)
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def test_rejects_tampered_checkpoint(self):
        module.run_scan(page_size=2, max_pages=1, delay=0)
        progress = json.loads(module.CHECKPOINT.read_text())
        progress["active_pool_count"] = 999
        module.CHECKPOINT.write_text(json.dumps(progress))
        with self.assertRaisesRegex(ValueError, "Active pool count mismatch"):
            module.run_scan(page_size=2, max_pages=1, delay=0)


if __name__ == "__main__":
    unittest.main()
