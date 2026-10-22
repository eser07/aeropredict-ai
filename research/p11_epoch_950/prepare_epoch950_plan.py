"""Build exact raw-data claims and exercise contract logic offline, without chain writes."""
import argparse, copy, hashlib, importlib.util, json, sys, types, unittest
from pathlib import Path
from datetime import datetime, timezone
HERE=Path(__file__).resolve().parent
ROOT=HERE.parent if HERE.name=='work' else HERE.parents[1]
args=argparse.ArgumentParser();args.add_argument('--run',type=Path);args.add_argument('--out',type=Path);options=args.parse_args()
sys.path.insert(0,str(ROOT/'work/genlayer-runtime'))
from eth_abi import encode,decode
from eth_utils import keccak
RUN=options.run or (ROOT/'data/epoch_950_runs/2026-10-22/block_52929586_2d62018d')
OUT=options.out or (ROOT/'outputs/epoch950-20261022');OUT.mkdir(parents=True,exist_ok=True)
sdk=types.ModuleType('genlayer');sdk.Contract=object;sdk.u256=int;sdk.__all__=['u256'];sdk.public=types.SimpleNamespace(write=lambda f:f,view=lambda f:f);sdk.eq_principle=types.SimpleNamespace(strict_eq=lambda f:f());sdk.nondet=types.SimpleNamespace(web=types.SimpleNamespace(request=None));sys.modules['genlayer']=sdk
spec=importlib.util.spec_from_file_location('epoch_contract',HERE/'Epoch950Verifier.py');contract=importlib.util.module_from_spec(spec);spec.loader.exec_module(contract)
raw=json.loads((RUN/'raw_dataset.json').read_text());ctx=raw['context'];epoch=int(datetime.fromisoformat(ctx['epoch_end_utc']).timestamp())
claims=sorted(raw['pools'],key=lambda p:p['index']);layers=[[bytes.fromhex(contract.digest(p)) for p in claims]]
while len(layers[-1])>1:
 layer=layers[-1];layers.append([hashlib.sha256(layer[i]+layer[min(i+1,len(layer)-1)]).digest() for i in range(0,len(layer),2)])
root=layers[-1][0].hex();entries=[]
for i,p in enumerate(claims):
 pos=i;proof=[]
 for layer in layers[:-1]:proof.append(layer[min(pos^1,len(layer)-1)].hex());pos//=2
 entries.append({'position':i,'claim':p,'proof':proof})
batches=[entries[i:i+10] for i in range(0,950,10)]
def write(name,value):
 path=OUT/name
 # This preparation is deterministic and may be regenerated before approval.
 path.write_text(json.dumps(value,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
ctor=[root,ctx['block']['hash'],int(ctx['block']['number'],16),epoch,raw['multicall_runtime_sha256']]
bundle={'context':ctx,'merkle_root':root,'constructor_args':ctor,'batches':[contract.canonical(b) for b in batches]}
write('batch-plan.json',bundle)
oracle={}
for path in sorted((RUN/'rpc').glob('*.json')):
 doc=json.loads(path.read_text());calls=decode(['(address,bool,bytes)[]'],bytes.fromhex(doc['calldata'][10:]))[0];responses=decode(['(bool,bytes)[]'],bytes.fromhex(doc['result_hex'][2:]))[0]
 assert len(calls)==len(responses)==doc['call_count']
 for (target,allowed,data),(ok,value) in zip(calls,responses):oracle[(target.lower(),'0x'+data.hex())]=(ok,value)
def fake_request(url,method,headers,body):
 req=json.loads(body);m=req['method'];params=req['params'];tag={'blockHash':ctx['block']['hash'],'requireCanonical':True}
 if m=='eth_chainId':value='0x2105'
 elif m=='eth_getBlockByHash':assert params==[ctx['block']['hash'],False];value={**ctx['block']}
 elif m=='eth_getBlockByNumber':assert params==['finalized',False];value=ctx['block']
 elif m=='eth_getCode':
  assert params==[contract.MULTICALL,tag]
  # Dedicated test uses the matching synthetic code; actual runtime hash is separately pinned.
  value='0x00'
 elif m=='eth_call':
  assert params[1]==tag and params[0]['to']==contract.MULTICALL
  calls=decode(['(address,bool,bytes)[]'],bytes.fromhex(params[0]['data'][10:]))[0]
  value='0x'+encode(['(bool,bytes)[]'],[[oracle[(to.lower(),'0x'+data.hex())] for to,ok,data in calls]]).hex()
 else:raise AssertionError(m)
 return types.SimpleNamespace(status=200,body=json.dumps({'result':value}).encode())
class Checks(unittest.TestCase):
 def test_all950_memberships_and_raw_call_reconstruction(self):
  count=0
  for entry in entries:
   self.assertEqual(contract.verify_membership(entry,root),contract.digest(entry['claim']))
   for to,data,value in contract.claim_calls(entry['claim'],epoch):
    ok,actual=oracle[(to,data)];self.assertTrue(ok);self.assertEqual(actual.hex(),value);count+=1
  self.assertGreater(count,34000)
 def test_encoder_matches_independent_eth_abi(self):
  for batch in batches:
   calls=[c for entry in batch for c in contract.claim_calls(entry['claim'],epoch)]
   for start in range(0,len(calls),150):
    chunk=calls[start:start+150]
    expected='0x'+(keccak(text='aggregate3((address,bool,bytes)[])')[:4]+encode(['(address,bool,bytes)[]'],[[(to,True,bytes.fromhex(data[2:])) for to,data,v in chunk]])).hex()
    self.assertEqual(contract.aggregate(chunk),expected)
    result='0x'+encode(['(bool,bytes)[]'],[[(True,bytes.fromhex(c[2])) for c in chunk]]).hex()
    self.assertEqual(contract.unaggregate(result,len(chunk)),[c[2] for c in chunk])
 def test_forged_claim_and_proof_rejected(self):
  for mutate in [lambda e:e['claim'].update(index=99999),lambda e:e['proof'].__setitem__(0,'00'*32),lambda e:e.update(position=950),lambda e:e['claim']['rewards']['fees']['tokens'][0]['raw'].__setitem__(0,'1')]:
   entry=copy.deepcopy(entries[0]);mutate(entry)
   with self.assertRaises(ValueError):contract.verify_membership(entry,root)
 def test_missing_amount_and_truncated_registry_rejected(self):
  for mutate in [lambda p:p['rewards']['fees']['tokens'][0]['raw'].__setitem__(0,None),lambda p:p['rewards']['fees']['tokens'].pop(),lambda p:p.update(errors=['read_failed'])]:
   p=copy.deepcopy(claims[0]);mutate(p)
   with self.assertRaises(ValueError):contract.claim_calls(p,epoch)
 def test_abi_failures_are_not_zero(self):
  for result in ['0x','0x'+encode(['(bool,bytes)[]'],[[(False,b'')]]).hex(),'0x'+encode(['(bool,bytes)[]'],[[(True,b'')]]).hex()]:
   with self.assertRaises(ValueError):contract.unaggregate(result,1)
 def test_batch_payload_bounds(self):
  self.assertEqual(len(batches),95);self.assertEqual(sum(len(b) for b in batches),950)
  for b in batches:self.assertLess(len(contract.canonical(b)),180000);self.assertLessEqual(sum(len(contract.claim_calls(e['claim'],epoch)) for e in b),2500)
 def test_state_changes_only_after_agreement_and_rejects_duplicates(self):
  args=copy.deepcopy(ctor);args[4]=hashlib.sha256(b'\0').hexdigest();obj=contract.Epoch950Verifier(*args);sdk.nondet.web.request=fake_request
  obj.verify_batch(contract.canonical(batches[0]));self.assertEqual(json.loads(obj.get_summary())['verified_pools'],10)
  with self.assertRaises(ValueError):obj.verify_batch(contract.canonical(batches[0]))
  before=obj.results_json;previous=sdk.nondet.web.request;sdk.nondet.web.request=lambda *a,**k:types.SimpleNamespace(status=403,body=b'')
  with self.assertRaises(ValueError):obj.verify_batch(contract.canonical(batches[1]))
  self.assertEqual(obj.results_json,before);sdk.nondet.web.request=previous
 def test_all950_can_be_stored_and_queried_offline(self):
  args=copy.deepcopy(ctor);args[4]=hashlib.sha256(b'\0').hexdigest();obj=contract.Epoch950Verifier(*args);sdk.nondet.web.request=fake_request
  for b in batches:obj.verify_batch(contract.canonical(b))
  self.assertEqual(json.loads(obj.get_summary())['verified_pools'],950)
  for p in claims:self.assertEqual(json.loads(obj.get_pool_result(p['index']))['claim_sha256'],contract.digest(p))
  self.assertEqual(json.loads(obj.get_pool_result(99999))['status'],'NOT_VERIFIED')
if __name__=='__main__':
 result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Checks))
 report={'checked_at_utc':datetime.now(timezone.utc).isoformat(),'offline_tests':result.testsRun,'passed':result.wasSuccessful(),'real_genlayer_transactions':0,'warning':'Offline SDK stubs are not validator consensus evidence. Real schema/runtime and network integration remain separate.'};write('offline-checks.json',report)
 if not result.wasSuccessful():raise SystemExit(1)
 print(json.dumps({'batches':95,'pools':950,'largest_payload_bytes':max(len(contract.canonical(b).encode()) for b in batches),'largest_batch_calls':max(sum(len(contract.claim_calls(e['claim'],epoch)) for e in b) for b in batches),'root':root}))
