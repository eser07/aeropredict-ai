"""Offline special-contract provenance and HTTP integration checks."""
import copy
import hashlib
import json
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from p9_validation import load_snapshot
from p9_contract_metadata import METADATA, annotate_special_contracts, load_special_contracts
from serve_pool_research_950 import make_server


class ContractMetadataTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        docs, _ = load_snapshot()
        cls.research, cls.pairs = docs[:2]
        cls.metadata = json.loads(METADATA.read_bytes())

    def check(self, metadata):
        return annotate_special_contracts(self.pairs, self.research, metadata)

    def test_reviewed_record_and_same_inventory_block(self):
        result = load_special_contracts(self.pairs, self.research)
        entry = next(p for p in result['pools'] if p['index'] == 1130)['contract_classification']
        self.assertEqual(entry['contract_name'], 'SinkPool')
        self.assertEqual(entry['block_number'], 52731839)
        self.assertTrue(entry['block_hash_pinned'])
        self.assertFalse(entry['independent_consensus'])

    def test_one_special_record_and_949_original_pairs(self):
        result = self.check(self.metadata)
        self.assertEqual(sum('contract_classification' in p for p in result['pools']), 1)
        self.assertEqual(sum(bool(p['token0_symbol'] and p['token1_symbol']) for p in result['pools']), 949)
        row = next(p for p in result['pools'] if p['index'] == 1130)
        self.assertIsNone(row['token0_address'])
        self.assertIsNone(row['token1_address'])

    def test_input_documents_unchanged(self):
        before = copy.deepcopy((self.pairs, self.research, self.metadata))
        self.check(self.metadata)
        self.assertEqual((self.pairs, self.research, self.metadata), before)

    def test_identity_and_provenance_tampering_rejected(self):
        for key, value in [('index', 64), ('address', '0x' + 'f' * 40), ('block_number', 52731840),
                           ('block_hash', '0x' + 'f' * 64), ('block_hash_pinned', False),
                           ('independent_consensus', True), ('verified_source_url', 'javascript:alert(1)'),
                           ('token_pair_applicable', True)]:
            with self.subTest(key=key):
                doc = copy.deepcopy(self.metadata)
                doc['entries'][0][key] = value
                with self.assertRaises(ValueError):
                    self.check(doc)

    def test_wrong_chain_or_inventory_rejected(self):
        for key, value in [('chain_id', 1), ('inventory_sha256', '0' * 64)]:
            with self.subTest(key=key):
                doc = copy.deepcopy(self.metadata)
                doc[key] = value
                with self.assertRaises(ValueError):
                    self.check(doc)

    def test_runtime_and_digest_cannot_be_replaced_together(self):
        doc = copy.deepcopy(self.metadata)
        doc['entries'][0]['runtime_bytecode'] = '0x6000'
        doc['entries'][0]['runtime_sha256'] = hashlib.sha256(bytes.fromhex('6000')).hexdigest()
        with self.assertRaises(ValueError):
            self.check(doc)

    def test_source_and_digest_cannot_be_replaced_together(self):
        doc = copy.deepcopy(self.metadata)
        doc['entries'][0]['source_code'] += 'function token0() external {}'
        doc['entries'][0]['source_sha256'] = hashlib.sha256(doc['entries'][0]['source_code'].encode()).hexdigest()
        with self.assertRaises(ValueError):
            self.check(doc)

    def test_content_changed_without_new_digest_rejected(self):
        for key in ['source_code', 'runtime_bytecode']:
            with self.subTest(key=key):
                doc = copy.deepcopy(self.metadata)
                doc['entries'][0][key] += '00'
                with self.assertRaises(ValueError):
                    self.check(doc)

    def test_nonempty_abi_rejected(self):
        doc = copy.deepcopy(self.metadata)
        doc['entries'][0]['abi'] = [{'name': 'token0'}]
        with self.assertRaises(ValueError):
            self.check(doc)

    def test_invalid_observation_times_rejected(self):
        for stamp in ['2026-10-18T20:00:00', '2099-10-18T20:00:00+00:00', '2026-10-16T00:00:00+00:00']:
            with self.subTest(stamp=stamp):
                doc = copy.deepcopy(self.metadata)
                doc['entries'][0]['observed_at_utc'] = stamp
                with self.assertRaises(ValueError):
                    self.check(doc)

    def test_conflicting_pair_or_current_pool_identity_rejected(self):
        for pair_change in [True, False]:
            pairs, research = copy.deepcopy((self.pairs, self.research))
            if pair_change:
                next(p for p in pairs['pools'] if p['index'] == 1130)['token0_symbol'] = 'USDC'
            else:
                next(p for p in research['pools'] if p['index'] == 1130)['address'] = '0x' + 'f' * 40
            with self.assertRaises(ValueError):
                annotate_special_contracts(pairs, research, self.metadata)

    def test_duplicate_entry_rejected(self):
        doc = copy.deepcopy(self.metadata)
        doc['entries'].append(copy.deepcopy(doc['entries'][0]))
        with self.assertRaises(ValueError):
            self.check(doc)


class ContractHttpTest(unittest.TestCase):
    def request_server(self, server, path):
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with urlopen('http://127.0.0.1:' + str(server.server_address[1]) + path, timeout=10) as response:
                return json.load(response)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_pairs_endpoint_classifies_only_1130(self):
        doc = self.request_server(make_server(0), '/api/pairs')
        self.assertEqual([p['index'] for p in doc['pools'] if 'contract_classification' in p], [1130])

    def test_status_separates_pair_coverage_from_classification(self):
        doc = self.request_server(make_server(0), '/api/status')
        self.assertEqual(doc['resolved_pairs'], 949)
        self.assertEqual(doc['unresolved_pairs'], [1130])
        self.assertEqual(doc['classified_special_contracts'], [1130])
        self.assertEqual(doc['unclassified_pair_records'], [])

    def test_missing_metadata_preserves_unknown_pair(self):
        with patch('serve_pool_research_950.load_special_contracts', side_effect=FileNotFoundError):
            server = make_server(0)
        doc = self.request_server(server, '/api/pairs')
        row = next(p for p in doc['pools'] if p['index'] == 1130)
        self.assertNotIn('contract_classification', row)
        self.assertIsNone(row['token0_symbol'])

    def test_corrupt_metadata_does_not_break_weekly_rewards(self):
        with patch('serve_pool_research_950.load_special_contracts', side_effect=ValueError):
            server = make_server(0)
        self.assertFalse(server.snapshot_summary['contract_metadata_available'])
        doc = self.request_server(server, '/api/weekly?index=64')
        self.assertEqual(doc['index'], 64)
        self.assertEqual(len(doc['weeks']), 4)


if __name__ == '__main__':
    unittest.main(verbosity=2)
