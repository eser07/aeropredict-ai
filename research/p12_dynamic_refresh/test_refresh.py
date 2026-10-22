import copy, json, tempfile, unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from refresh import value_usd, summarize, validate_snapshot, collect, replace_json, rpc, WEEK
from publish_feed import prepare

TOKEN='0x'+'2'*40
TEST_ROOT=Path(__file__).resolve().parent/'.test-work'
TEST_ROOT.mkdir(exist_ok=True)
def fixture():
    context={'chain_id':8453,'block_number':100,'block_hash':'0x'+'3'*64,'block_timestamp':WEEK*100,'registry_length':1,'completed_at_utc':'2026-10-22T12:00:00+00:00'}
    pools=[{'index':0,'pool_address':'0x'+'1'*40,'gauge_address':'0x'+'4'*40,'vote_weight_raw':'1000000000000000000','pair':'TEST / USD','active_at_collection':True,'rewards':{'fees':{'tokens':[{'token_address':TOKEN,'raw':['100','0','300','400','500']}]},'bribes':{'tokens':[]}}}]
    return summarize(pools,{TOKEN:{'decimals':2,'symbol':'TEST'}},{TOKEN:{'usd':'2'}},[WEEK*n for n in range(96,101)],context)

class Tests(unittest.TestCase):
    def test_missing_quote_is_not_zero_but_observed_zero_is_known(self):
        self.assertIsNone(value_usd('1',{'decimals':18},{}))
        self.assertEqual(value_usd('0',{},{}),Decimal(0))
        self.assertIsNone(value_usd(None,{},{}))
        self.assertEqual(value_usd('123',{'decimals':2},{'usd':'2'}),Decimal('2.46'))
    def test_usd_and_raw_token_aggregation_are_separate(self):
        s=fixture();self.assertEqual(s['totals'][3]['fees']['known_usd'],'8');self.assertEqual(s['totals'][3]['bribes']['known_usd'],'0')
        self.assertEqual(s['totals'][3]['fees']['tokens'][0]['raw'],'400');self.assertEqual(s['pools'][0]['fees'],['2','0','6','8'])
        self.assertEqual(s['pools'][0]['current_fees'],'10');self.assertFalse(s['totals'][4]['complete'])
    def test_registry_growth_retains_every_identity(self):
        before=fixture();after=copy.deepcopy(before);after['pools'].append(dict(after['pools'][0],index=1,address='0x'+'5'*40));after['pool_count']=2;after['registry_length']=2;after['context']['registry_length']=2
        self.assertTrue(validate_snapshot(after,before))
        after['pools'][0]['address']='0x'+'6'*40
        with self.assertRaises(ValueError):validate_snapshot(after,before)
    def test_no_gaps_duplicates_or_time_regression(self):
        before=fixture()
        for change in ['gap','duplicate','past']:
            s=copy.deepcopy(before)
            if change=='gap':s['pools'][0]['index']=1
            elif change=='duplicate':s['pools'].append(s['pools'][0]);s['registry_length']=2;s['pool_count']=2
            else:s['context']['block_number']=99
            with self.assertRaises(ValueError):validate_snapshot(s,before)
    def test_failed_collection_never_replaces_latest(self):
        with tempfile.TemporaryDirectory(dir=TEST_ROOT) as d:
            assert Path(d).resolve().is_relative_to(TEST_ROOT)
            root=Path(d);replace_json(root/'latest.json',fixture());before=(root/'latest.json').read_bytes()
            with patch('refresh.rpc',side_effect=RuntimeError('unavailable')):
                with self.assertRaises(RuntimeError):collect(root,root/'unused.json')
            self.assertEqual((root/'latest.json').read_bytes(),before)
    def test_rpc_has_no_write_methods(self):
        for method in ['eth_sendRawTransaction','personal_newAccount','eth_sendTransaction','evm_mine']:
            with self.assertRaises(ValueError):rpc(method,[])
    def test_weekly_first_observations_are_immutable(self):
        with tempfile.TemporaryDirectory(dir=TEST_ROOT) as d:
            assert Path(d).resolve().is_relative_to(TEST_ROOT)
            root=Path(d);output=root/'output';feed=root/'feed';replace_json(output/'latest.json',fixture());prepare(output,feed)
            before={str(p.relative_to(feed)):p.read_bytes() for p in (feed/'weekly').rglob('*.json')}
            s=fixture();s['context']['block_number']=101;s['totals'][0]['fees']['known_usd']='999';replace_json(output/'latest.json',s);prepare(output,feed)
            self.assertEqual(before,{str(p.relative_to(feed)):p.read_bytes() for p in (feed/'weekly').rglob('*.json')})
            self.assertEqual(json.loads((feed/'latest.json').read_text())['context']['block_number'],101)
    def test_real_snapshot_reconciles_complete_and_partial_totals(self):
        f=Path(__file__).resolve().parents[2]/'outputs/p12-dynamic-refresh/data/latest.json'
        # Work tree and canonical checkout use different roots; real data is optional here.
        if not f.exists():self.skipTest('real snapshot is separately checked by snapshot-audit.py')
        self.assertTrue(validate_snapshot(json.loads(f.read_text(encoding='utf-8'))))

if __name__=='__main__':unittest.main()
