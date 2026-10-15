"""P8.1 offline regression tests: planning checks must never enable live collection."""
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from p8_collection_preflight import next_thursday_utc, require, validate_archive  # noqa: E402


class TestP8Preflight(unittest.TestCase):
    def test_next_utc_thursday_boundary_is_in_the_future(self):
        cases = (
            ("2026-10-14T23:59:00+00:00", "2026-10-15T00:00:00+00:00"),
            ("2026-10-15T00:00:00+00:00", "2026-10-22T00:00:00+00:00"),
            ("2026-10-15T20:33:00+00:00", "2026-10-22T00:00:00+00:00"),
            ("2026-10-18T10:00:00+00:00", "2026-10-22T00:00:00+00:00"),
        )
        for source, expected in cases:
            with self.subTest(source=source):
                now = datetime.fromisoformat(source)
                self.assertEqual(next_thursday_utc(now).isoformat(), expected)
                self.assertGreater(next_thursday_utc(now), now)

    def test_explicit_guard_rejects_invalid_archive(self):
        with self.assertRaisesRegex(ValueError, "readiness"):
            require(False, "Unsafe readiness state")
        require(True, "No error")

    def test_archive_incomplete_inventory_refused_without_reading_files(self):
        doc = {"chain_id": 8453, "audited_pool_count": 927,
               "inventory_pool_count": 928, "not_audited_at_collection": []}
        with self.assertRaisesRegex(ValueError, "928-pool"):
            validate_archive(doc, {}, {}, Path("/unused/old"), Path("/unused/new"))

    def test_archive_wrong_base_chain_refused_without_reading_files(self):
        doc = {"chain_id": 1, "audited_pool_count": 928,
               "inventory_pool_count": 928, "not_audited_at_collection": []}
        with self.assertRaisesRegex(ValueError, "Base Mainnet"):
            validate_archive(doc, {}, {}, Path("/unused/old"), Path("/unused/new"))

    def test_preflight_uses_existing_read_only_sources(self):
        source = (ROOT / "scripts" / "p8_collection_preflight.py").read_text(
            encoding="utf-8"
        )
        for snippet in (
            "validate_manifest(OLD_FOLDER)",
            "validate_manifest(NEXT_FOLDER)",
            "validate_research(",
            "No blockchain/RPC/price requests or file writes",
            "NEW 928-pool live collection NOT enabled",
        ):
            self.assertIn(snippet, source)
        for forbidden in (
            "save_atomic(", ".write_text(", ".write_bytes(", ".mkdir(",
            "subprocess.run(", "requests.get(", "rpc_checked(",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
