"""Read a new completed epoch for the existing 950-pool cohort; never overwrite history.

All EVM reads use one finalized Base block hash with requireCanonical. Multicall3
reduces HTTP traffic. Historical epoch keys are read at this post-period block,
not reconstructed at the original historical week boundary. No transactions.
"""
import argparse, concurrent.futures, hashlib, json, sys, time, urllib.request, urllib.error
from datetime import datetime, timezone
from decimal import Decimal, localcontext
from pathlib import Path
from eth_abi import encode, decode
from eth_utils import keccak

BASE_RPC = 'https://base-rpc.publicnode.com'
VOTER = '0x16613524e02ad97eDfeF371bC883F2F5d6C480A5'.lower()
MULTICALL = '0xcA11bde05977b3631167028862bE2a173976CA11'.lower()
ZERO = '0x'+'0'*40
WEEK = 604800
MAX_TOKENS = 500
ALLOWED = {'eth_chainId','eth_getBlockByNumber','eth_getBlockByHash','eth_getCode','eth_call'}

def iso(timestamp): return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()
def stamp(): return datetime.now(timezone.utc).isoformat()
def digest(value): return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def selector(name): return keccak(text=name)[:4]
def calldata(signature, *args):
    types = signature[signature.index('(')+1:-1].split(',') if args else []
    return '0x'+(selector(signature)+encode(types,args)).hex()
def request(method, params):
    if method not in ALLOWED: raise ValueError('Read-only RPC method required')
    payload=json.dumps({'jsonrpc':'2.0','id':1,'method':method,'params':params}).encode()
    for attempt in range(5):
        try:
            req=urllib.request.Request(BASE_RPC,data=payload,headers={'Content-Type':'application/json','User-Agent':'AeroPredict-Readonly-Epoch/1.0'})
            with urllib.request.urlopen(req,timeout=35) as response: doc=json.load(response)
            if 'error' in doc: raise RuntimeError('RPC rejected read: '+str(doc['error'].get('code')))
            return doc['result']
        except (OSError,ValueError,KeyError,RuntimeError):
            if attempt==4: raise RuntimeError('Base read unavailable after bounded retries') from None
            time.sleep(min(2**attempt,8))

def save_new(path, doc):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8') as f: json.dump(doc,f,ensure_ascii=False,separators=(',',':'))

def aggregate_data(calls):
    return '0x'+(selector('aggregate3((address,bool,bytes)[])')+encode(['(address,bool,bytes)[]'],[[(to,True,bytes.fromhex(data[2:])) for to,data in calls]])).hex()

class Collector:
    def __init__(self, run, context):
        self.run,self.context=run,context
        self.tag={'blockHash':context['block']['hash'],'requireCanonical':True}
        self.http_reads=0

    def phase(self, name, calls):
        chunks=[calls[i:i+150] for i in range(0,len(calls),150)]
        def one(item):
            number,part=item;path=self.run/'rpc'/f'{name}_{number:04d}.json'
            body=aggregate_data(part);key=digest({'block':self.tag,'to':MULTICALL,'data':body})
            if path.exists():
                doc=json.loads(path.read_text())
                if doc['request_sha256']!=key or hashlib.sha256(bytes.fromhex(doc['result_hex'][2:])).hexdigest()!=doc['response_sha256']:raise ValueError('Checkpoint integrity mismatch')
            else:
                result=request('eth_call',[{'to':MULTICALL,'data':body},self.tag]);self.http_reads+=1
                decoded=decode(['(bool,bytes)[]'],bytes.fromhex(result[2:]))[0]
                if len(decoded)!=len(part):raise ValueError('Multicall result count mismatch')
                doc={'phase':name,'chunk':number,'block_hash':self.tag['blockHash'],'call_count':len(part),'request_sha256':key,'calldata':body,'result_hex':result,'response_sha256':hashlib.sha256(bytes.fromhex(result[2:])).hexdigest(),'observed_at_utc':stamp()}
                save_new(path,doc)
            return [(bool(ok),'0x'+data.hex()) for ok,data in decode(['(bool,bytes)[]'],bytes.fromhex(doc['result_hex'][2:]))[0]]
        values=[]
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            for i,rows in enumerate(pool.map(one,enumerate(chunks)),1):
                values.extend(rows)
                if i%10==0 or i==len(chunks):print(json.dumps({'phase':name,'chunks_done':i,'chunks':len(chunks),'calls':len(calls)}),flush=True)
        return values

def uint(result):
    ok,raw=result
    if not ok or len(raw)!=66: raise ValueError('Missing uint256 result')
    return int(raw,16)
def address(result):
    n=uint(result)
    if n>=2**160:raise ValueError('Invalid address result')
    return '0x'+f'{n:040x}'
def text(result):
    if not result[0]:return 'UNKNOWN'
    data=bytes.fromhex(result[1][2:])
    try:return decode(['string'],data)[0][:80]
    except Exception:return data[:32].rstrip(b'\x00').decode('utf-8','replace')[:80] or 'UNKNOWN'

def quotes(tokens):
    output={}
    for i in range(0,len(tokens),15):
        batch=tokens[i:i+15];url='https://coins.llama.fi/prices/current/'+','.join('base:'+t for t in batch)
        try:
            with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'AeroPredict-Readonly-Epoch/1.0'}),timeout=25) as r:items=json.load(r).get('coins',{})
        except (OSError,ValueError):items={}
        for token in batch:
            item=items.get('base:'+token,{});entry={'price_usd':None,'reason':'quote_missing','price_timestamp_utc':None}
            try:
                price=Decimal(str(item['price']));ts=int(item['timestamp']);age=time.time()-ts
                if price.is_finite() and price>0 and -300<=age<=36*3600:
                    entry={'price_usd':str(price),'reason':None,'price_timestamp_utc':iso(ts)}
            except (KeyError,ValueError,TypeError,ArithmeticError):pass
            output[token]=entry
        if (i//15+1)%10==0:print(json.dumps({'phase':'quotes','tokens_done':min(i+15,len(tokens)),'tokens':len(tokens)}),flush=True)
    return output

def collect(root, epoch, resume=None):
    old_path=root/'data/pool_collection_batches_base/p9_unified_research/block_52731839/registration_25/research_all_950_one_epoch.json'
    old=json.loads(old_path.read_text());pools=old['pools']
    if len(pools)!=950 or len({p['index'] for p in pools})!=950:raise ValueError('Expected existing 950 unique identities')
    end=int(datetime.fromisoformat(epoch).timestamp())
    if end%WEEK or datetime.now(timezone.utc).timestamp()<end:raise ValueError('Completed Thursday UTC epoch required')
    if int(request('eth_chainId',[]),16)!=8453:raise ValueError('Wrong chain')
    if resume:
        run=Path(resume);context=json.loads((run/'context.json').read_text())
        if context['epoch_end_utc']!=iso(end) or context['inventory_sha256']!=digest([(p['index'],p['address'].lower()) for p in pools]):raise ValueError('Resume identity/epoch mismatch')
    else:
        block=request('eth_getBlockByNumber',['finalized',False])
        if int(block['timestamp'],16)<end:raise ValueError('Finalized state has not reached period end')
        run=root/'data/epoch_950_runs'/epoch[:10]/('block_'+str(int(block['number'],16))+'_'+block['hash'][2:10])
        context={'schema_version':1,'chain_id':8453,'epoch_end_utc':iso(end),'week_starts_utc':[iso(end-WEEK*n) for n in range(4,0,-1)],'inventory_sha256':digest([(p['index'],p['address'].lower()) for p in pools]),'pool_count':950,'block':{k:block[k] for k in ['number','hash','parentHash','timestamp']},'started_at_utc':stamp(),'multicall_address':MULTICALL,'historical_state_policy':'Historical epoch keys read at one post-period finalized block; not historical week-boundary snapshots'}
        save_new(run/'context.json',context)
    print(json.dumps({'run':str(run),'block':int(context['block']['number'],16),'epoch_end_utc':iso(end),'cohort':950}),flush=True)
    c=Collector(run,context);base=[]
    calls=[]
    for p in pools:
        for sig,arg in [('pools(uint256)',p['index']),('gauges(address)',p['address']),('weights(address)',p['address'])]:calls.append((VOTER,calldata(sig,arg)))
    result=c.phase('01_identity',calls)
    for i,p in enumerate(pools):
        if address(result[i*3]).lower()!=p['address'].lower():raise ValueError('Voter index/address identity changed')
        base.append({'index':p['index'],'pool_address':p['address'].lower(),'gauge_address':address(result[i*3+1]),'vote_weight_raw':str(uint(result[i*3+2])),'errors':[]})
    calls=[]
    for p in base:
        for sig in ['isAlive(address)','gaugeToFees(address)','gaugeToBribe(address)']:calls.append((VOTER,calldata(sig,p['gauge_address'])))
    result=c.phase('02_reward_contracts',calls)
    contracts=[]
    for i,p in enumerate(base):
        p['active_at_collection']=bool(uint(result[i*3]));p['fees_contract']=address(result[i*3+1]);p['bribes_contract']=address(result[i*3+2]);p['rewards']={}
        for kind in ['fees','bribes']:
            contract=p[kind+'_contract'];p['rewards'][kind]={'contract':contract,'tokens':[],'registered_count':0,'duration':None}
            if contract!=ZERO:contracts.append((p,kind,contract))
    calls=[]
    for p,kind,contract in contracts:calls.extend([(contract,calldata('DURATION()')),(contract,calldata('rewardsListLength()'))])
    result=c.phase('03_registry_lengths',calls)
    token_targets=[]
    for i,(p,kind,contract) in enumerate(contracts):
        r=p['rewards'][kind]
        try:
            r['duration']=uint(result[i*2]);r['registered_count']=uint(result[i*2+1])
            if r['duration']!=WEEK or r['registered_count']>MAX_TOKENS:raise ValueError()
            for pos in range(r['registered_count']):token_targets.append((p,kind,contract,pos))
        except ValueError:p['errors'].append(kind+'_registry_unavailable')
    result=c.phase('04_registry_tokens',[(contract,calldata('rewards(uint256)',pos)) for p,kind,contract,pos in token_targets])
    all_tokens=set()
    for target,res in zip(token_targets,result):
        p,kind,contract,pos=target
        try:
            token=address(res)
            if token==ZERO or token in [t['token_address'] for t in p['rewards'][kind]['tokens']]:raise ValueError()
            p['rewards'][kind]['tokens'].append({'token_address':token,'registry_index':pos,'raw':[]});all_tokens.add(token)
        except ValueError:p['errors'].append(kind+'_token_registry_invalid')
    token_list=sorted(all_tokens);calls=[]
    for token in token_list:calls.extend([(token,calldata('decimals()')),(token,calldata('symbol()'))])
    result=c.phase('05_token_metadata',calls);metadata={}
    for i,token in enumerate(token_list):
        try:
            decimals=uint(result[i*2]);decimals=decimals if decimals<=36 else None
        except ValueError:decimals=None
        metadata[token]={'decimals':decimals,'symbol':text(result[i*2+1])}
    reward_targets=[]
    for p in base:
        for kind in ['fees','bribes']:
            for token in p['rewards'][kind]['tokens']:
                for week in range(4):reward_targets.append((p,kind,token,end-WEEK*(4-week)))
    calls=[(p[kind+'_contract'],calldata('tokenRewardsPerEpoch(address,uint256)',token['token_address'],week)) for p,kind,token,week in reward_targets]
    result=c.phase('06_epoch_amounts',calls)
    for target,res in zip(reward_targets,result):
        p,kind,token,week=target
        try:token['raw'].append(str(uint(res)))
        except ValueError:token['raw'].append(None);p['errors'].append(kind+'_amount_unavailable')
    print(json.dumps({'phase':'raw_complete','pools':950,'tokens':len(token_list),'reward_calls':len(calls),'pool_errors':sum(bool(p['errors']) for p in base)}),flush=True)
    quote_path=run/'quotes.json'
    if quote_path.exists():prices=json.loads(quote_path.read_text())
    else:prices=quotes(token_list);save_new(quote_path,prices)
    block=request('eth_getBlockByHash',[context['block']['hash'],False])
    if block is None or block['number']!=context['block']['number']:raise ValueError('Pinned block no longer canonical')
    save_new(run/'raw_dataset.json',{'context':context,'completed_at_utc':stamp(),'pools':base,'token_metadata':metadata,'prices':prices,'rpc_http_calls_this_attempt':c.http_reads,'multicall_runtime_sha256':hashlib.sha256(bytes.fromhex(request('eth_getCode',[MULTICALL,c.tag])[2:])).hexdigest()})
    print(json.dumps({'state':'raw_dataset_complete','pools':950,'pools_with_errors':sum(bool(p['errors']) for p in base),'run':str(run)}),flush=True)
    return run

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]);p.add_argument('--epoch-end',default='2026-10-22T00:00:00+00:00');p.add_argument('--resume',type=Path);args=p.parse_args()
    try:collect(args.root,args.epoch_end,args.resume)
    except Exception as e:print(json.dumps({'state':'stopped','error_type':type(e).__name__,'detail':str(e)[:160] if isinstance(e,ValueError) else 'Collection incomplete; completed checkpoints preserved'}),flush=True);raise SystemExit(1)
if __name__=='__main__':main()
