"""Saved P4-to-P9 integration tests: no RPC, source mutations or existing ports."""
import copy
import json
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import urlopen

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from p9_validation import load_snapshot
from p9_votes_950 import INVENTORY,VOTES,load_vote_sources,validate_vote_sources,vote_detail_950
from serve_pool_research_950 import make_server

class SavedVoteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        docs,_=load_snapshot();cls.research=docs[0];cls.context=load_vote_sources(cls.research)
        cls.votes=json.loads(VOTES.read_bytes());cls.inventory=json.loads(INVENTORY.read_bytes())
        cls.pools={p['index']:p for p in cls.research['pools']}

    def check(self,doc):
        return validate_vote_sources(doc,self.inventory,self.research,'test-digest')

    def test_all_950_have_explicit_928_or_22_coverage(self):
        results=[vote_detail_950(p,self.context) for p in self.pools.values()]
        self.assertEqual(sum(r['available'] for r in results),928)
        self.assertEqual(sum(not r['available'] for r in results),22)
        self.assertTrue(all(r['vote_weight_raw'] is None for r in results if not r['available']))

    def test_64_known_weight_and_same_block_share(self):
        r=vote_detail_950(self.pools[64],self.context)
        self.assertEqual(r['vote_weight_raw'],'70375417382509527185740892')
        self.assertEqual(r['block_number'],52646576)
        self.assertEqual(r['voter_share_percent_at_block'],'7.27623728')
        self.assertFalse(r['synchronized_with_reward_epochs'])
        self.assertFalse(r['is_weekly_vote_history'])

    def test_missing_2012_is_unknown_not_zero(self):
        r=vote_detail_950(self.pools[2012],self.context)
        self.assertFalse(r['available']);self.assertIsNone(r['vote_weight_raw'])

    def test_wrong_chain_rejected(self):
        doc=copy.deepcopy(self.votes);doc['chain_id']=1
        with self.assertRaises(ValueError):self.check(doc)

    def test_wrong_inventory_hash_rejected(self):
        doc=copy.deepcopy(self.votes);doc['source_inventory_sha256']='0'*64
        with self.assertRaises(ValueError):self.check(doc)

    def test_incomplete_cohort_rejected(self):
        doc=copy.deepcopy(self.votes);doc['complete']=False
        with self.assertRaises(ValueError):self.check(doc)

    def test_wrong_pool_address_rejected(self):
        doc=copy.deepcopy(self.votes);doc['pages'][0]['pools'][0]['pool_address']='0x'+'f'*40
        with self.assertRaises(ValueError):self.check(doc)

    def test_duplicate_pool_rejected(self):
        doc=copy.deepcopy(self.votes);doc['pages'][0]['pools'][1]=doc['pages'][0]['pools'][0]
        with self.assertRaises(ValueError):self.check(doc)

    def test_naive_timestamp_rejected(self):
        doc=copy.deepcopy(self.votes);doc['pages'][0]['block_timestamp_utc']='2026-10-15T16:41:39'
        with self.assertRaises(ValueError):self.check(doc)

    def test_collection_before_block_rejected(self):
        doc=copy.deepcopy(self.votes);doc['pages'][0]['collected_at_utc']='2026-10-14T00:00:00+00:00'
        with self.assertRaises(ValueError):self.check(doc)

    def test_non_ascii_raw_rejected(self):
        doc=copy.deepcopy(self.votes);doc['pages'][0]['pools'][0]['weight_raw']='１２'
        with self.assertRaises(ValueError):self.check(doc)

    def test_uint256_overflow_rejected(self):
        doc=copy.deepcopy(self.votes);doc['pages'][0]['total_voting_weight_raw']=str(2**256)
        with self.assertRaises(ValueError):self.check(doc)

    def test_weight_above_total_rejected(self):
        doc=copy.deepcopy(self.votes);doc['pages'][0]['total_voting_weight_raw']='1'
        with self.assertRaises(ValueError):self.check(doc)

    def test_future_observation_rejected(self):
        doc=copy.deepcopy(self.votes);doc['pages'][0]['block_number']=52731840
        with self.assertRaises(ValueError):self.check(doc)

class VoteHttpTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=make_server(0);cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.url='http://127.0.0.1:'+str(cls.server.server_address[1])

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join()

    def request(self,path):
        try:
            with urlopen(self.url+path,timeout=10) as response:return response.status,json.load(response)
        except HTTPError as error:return error.code,json.load(error)

    def test_available_endpoint(self):
        code,r=self.request('/api/votes?index=64');self.assertEqual(code,200);self.assertTrue(r['available']);self.assertEqual(r['covered_pools'],928)

    def test_absent_endpoint(self):
        code,r=self.request('/api/votes?index=2012');self.assertEqual(code,200);self.assertFalse(r['available']);self.assertIsNone(r['vote_weight_raw'])

    def test_bad_queries(self):
        for path in ['/api/votes','/api/votes?index=-1','/api/votes?index=64&index=35','/api/votes?index=64&foo=1']:
            with self.subTest(path=path):self.assertEqual(self.request(path)[0],400)

    def test_unknown_pool(self):
        self.assertEqual(self.request('/api/votes?index=9999')[0],404)

    def test_status_coverage(self):
        self.assertEqual(self.request('/api/status')[1]['recorded_vote_pools'],928)

    def test_unavailable_votes_do_not_break_rewards(self):
        with patch('serve_pool_research_950.load_vote_sources',side_effect=ValueError('fixture corruption')):
            server=make_server(0)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        url='http://127.0.0.1:'+str(server.server_address[1])
        try:
            with self.assertRaises(HTTPError) as context:urlopen(url+'/api/votes?index=64',timeout=10)
            self.assertEqual(context.exception.code,503);context.exception.close()
            with urlopen(url+'/api/weekly?index=64',timeout=10) as response:self.assertEqual(response.status,200)
        finally:server.shutdown();server.server_close();thread.join()

if __name__=='__main__':unittest.main(verbosity=2)
