"""P8.4 offline tests: preserve legacy inventory and bound all new RPC scans."""
import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import p8_discover_current_registry as p8  # noqa: E402


class P8DiscoveryTests(unittest.TestCase):
    def test_bounds_never_allow_unattended_all_registered_scan(self):
        self.assertEqual(p8.bounds(10, 1), 10)
        self.assertEqual(p8.bounds(25, 3), 75)
        for page_size, max_pages in ((0, 1), (26, 1), (10, 0),
                                     (10, 4), (True, 1), (25, True)):
            with self.subTest(page_size=page_size, max_pages=max_pages):
                with self.assertRaises(ValueError):
                    p8.bounds(page_size, max_pages)

    def test_offline_preview_uses_no_rpc_and_creates_nothing(self):
        with tempfile.TemporaryDirectory() as path:
            folder = Path(path) / "p8"
            output = io.StringIO()
            with (patch.object(p8, "FOLDER", folder),
                  patch.object(p8, "CHECKPOINT", folder / "checkpoint.json"),
                  patch.object(p8, "RESULT", folder / "active_pools.json"),
                  patch.object(p8.discovery, "rpc",
                               side_effect=AssertionError("Preview must never access RPC")),
                  contextlib.redirect_stdout(output)):
                p8.main([])
            self.assertFalse(folder.exists())
            self.assertIn("OFFLINE ONLY", output.getvalue())
            self.assertIn("NOT STARTED", output.getvalue())
            self.assertIn("historical research inventory", output.getvalue())

    def test_live_only_patches_discovery_output_paths_and_never_restarts(self):
        with tempfile.TemporaryDirectory() as path:
            folder = Path(path) / "new-scan"
            original_data = p8.discovery.DATA
            original_checkpoint = p8.discovery.CHECKPOINT
            original_result = p8.discovery.RESULT
            calls = []
            def fake_scan(**kwargs):
                self.assertEqual(p8.discovery.DATA, folder)
                self.assertEqual(p8.discovery.CHECKPOINT, folder / "checkpoint.json")
                self.assertEqual(p8.discovery.RESULT, folder / "active_pools.json")
                calls.append(kwargs)
                return {
                    "snapshot_block_number": 52660000, "total_registered": 2011,
                    "next_index": 10, "active_pool_count": 4, "complete": False,
                }
            with (patch.object(p8, "FOLDER", folder),
                  patch.object(p8, "CHECKPOINT", folder / "checkpoint.json"),
                  patch.object(p8, "RESULT", folder / "active_pools.json"),
                  patch.object(p8.discovery, "run_scan", side_effect=fake_scan),
                  contextlib.redirect_stdout(io.StringIO())):
                p8.run_live(10, 1)
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0]["page_size"], 10)
            self.assertEqual(calls[0]["max_pages"], 1)
            self.assertFalse(calls[0]["restart"])
            self.assertFalse(calls[0]["until_complete"])
            self.assertEqual(p8.discovery.DATA, original_data)
            self.assertEqual(p8.discovery.CHECKPOINT, original_checkpoint)
            self.assertEqual(p8.discovery.RESULT, original_result)
            self.assertFalse(folder.exists())

    def test_rejects_p8_only_orphaned_published_result(self):
        with tempfile.TemporaryDirectory() as path:
            folder = Path(path)
            (folder / "active_pools.json").write_text("{}", encoding="utf-8")
            with (patch.object(p8, "CHECKPOINT", folder / "checkpoint.json"),
                  patch.object(p8, "RESULT", folder / "active_pools.json")):
                with self.assertRaisesRegex(RuntimeError, "without checkpoint"):
                    p8.local_progress()

    def test_code_has_no_user_path_override_or_mass_scan(self):
        source = (ROOT / "scripts" / "p8_discover_current_registry.py").read_text(
            encoding="utf-8"
        )
        for text in ("--live", "MAX_PAGE_SIZE = 25",
                     "MAX_PAGES_PER_CALL = 3", "restart=False",
                     "until_complete=False", "patch.multiple(",
                     "data", "PARTIAL:"):
            self.assertIn(text, source)
        self.assertNotIn("add_argument(\"--restart\"", source)
        self.assertNotIn("add_argument(\"--until-complete\"", source)
        self.assertNotIn("save_atomic(", source)
        self.assertNotIn("subprocess.run(", source)
        self.assertNotIn("requests.get(", source)


if __name__ == "__main__":
    unittest.main()
