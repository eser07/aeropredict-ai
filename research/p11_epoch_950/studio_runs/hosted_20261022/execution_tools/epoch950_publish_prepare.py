"""Use only real finalized Hosted results to prepare the approved publication."""
from pathlib import Path
import json,hashlib,re
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs/epoch950-20261022';SITE=ROOT/'sites/aeropredict-review';DATA=SITE/'dist/data'
def load(p):return json.loads(p.read_text(encoding='utf-8'))
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
run=load(OUT/'hosted-runtime.json');audit=load(OUT/'hosted-independent-readback.json');bundle=load(OUT/'batch-plan.json')
assert run['passed'] and audit['passed'] and run['summary']['verified_pools']==950 and len(run['pool_results'])==950
assert len(run['transactions'])==96 and run['broadcast_attempts']==96
entries=[e for batch in bundle['batches'] for e in json.loads(batch)]
for entry in entries:
 result=run['pool_results'][str(entry['claim']['index'])]
 assert result['status']=='VERIFIED' and result['claim_sha256']==hashlib.sha256(json.dumps(entry['claim'],sort_keys=True,separators=(',',':')).encode()).hexdigest()
claims={str(e['claim']['index']):e for e in entries};save(DATA/'epoch-claims.json',claims)
research=load(DATA/'p9-research.json')
for pool in research['pools']:
 claim=claims[str(pool['index'])]['claim'];pool['fees_contract']=claim['fees_contract'];pool['bribes_contract']=claim['bribes_contract']
save(DATA/'p9-research.json',research)
receipts=[]
for tx in run['transactions']:
 assert tx['state']=='FINALIZED' and list(tx['votes'].values()).count('agree')>=3
 receipts.append({k:tx[k] for k in ['label','hash','status','contract_address','finalized_at_utc']}|{'agree':list(tx['votes'].values()).count('agree'),'idle':list(tx['votes'].values()).count('idle')})
provenance=load(DATA/'epoch-provenance.json');provenance.update(genlayer_status='VERIFIED',genlayer_verified_pools=950,genlayer_results=run['pool_results'],genlayer_contract_address=run['contract_address'],genlayer_chain_id=61999,genlayer_source_sha256='b835f9a011c785f780576f09e56f9399b8bbccca11c6121357a053ddbce43436',merkle_root=bundle['merkle_root'],genlayer_verified_at_utc=run['completed_at_utc'],independent_readback_at_utc=audit['checked_at_utc'],transactions=receipts,protocol_fee_gen=None,total_usd=None,independent_public_operator_consensus=False);save(DATA/'epoch-provenance.json',provenance)
config=SITE/'src/epoch-config.js';text=config.read_text();text=re.sub(r'export const EPOCH_HASHES = .*;', 'export const EPOCH_HASHES = '+json.dumps([t['hash'] for t in run['transactions'] if t['label'].startswith('batch_')])+';',text);config.write_text(text)
manifest=load(DATA/'manifest.json');manifest['sha256']={str(p.relative_to(DATA.parent)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in DATA.glob('*.json') if p.name!='manifest.json'};save(DATA/'manifest.json',manifest)
print(json.dumps({'prepared_from_real_results':True,'verified_pools':950,'batch_receipts':95,'total_receipts':96}))
