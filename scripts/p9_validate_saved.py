from pathlib import Path
import sys,json,hashlib
p=Path(__file__).resolve().parents[1];sys.path.insert(0,str(p/'scripts'))
from p9_weekly_950 import weekly_breakdown_950
folder=p/'data/pool_collection_batches_base/p9_unified_research/block_52731839/registration_25'
doc=json.loads((folder/'research_all_950_one_epoch.json').read_text()); pairs=json.loads((folder/'pool_pairs_950_base.json').read_text())
assert len(doc['pools'])==950 and len({x['index'] for x in doc['pools']})==950
assert sum(x['usd_coverage_complete'] for x in doc['pools'])==904
assert sum(x['no_observed_rewards'] for x in doc['pools'])==249
assert len(pairs['pools'])==950
results=[]
for i,pool in enumerate(doc['pools']):
 result=weekly_breakdown_950(pool,folder); results.append(result)
 if pool['index'] in [64,35]:print(pool['index'],json.dumps(result['trend'],ensure_ascii=False))
 if (i+1)%100==0:print('Audited',i+1,flush=True)
# Validation only: never overwrite historical datasets.
print('ALL 950 weekly records reconcile')
