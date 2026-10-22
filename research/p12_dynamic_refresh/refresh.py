"""Read-only, full-registry Base snapshots. No wallet, env RPC, or transaction API.

Each completed run is immutable. Only a validated complete snapshot can replace
latest.json. This is provider-observed data, not a new GenLayer attestation.
"""
import argparse, concurrent.futures, hashlib, json, os, time, urllib.request
from datetime import datetime, timezone
from decimal import Decimal, localcontext
from pathlib import Path
from eth_abi import encode, decode
from eth_utils import keccak

VOTER='0x16613524e02ad97edfeF371bc883f2f5d6c480a5'.lower()
MULTICALL='0xca11bde05977b3631167028862be2a173976ca11'
ZERO='0x'+'0'*40
WEEK=604800
RPCS=('https://base-rpc.publicnode.com','https://mainnet.base.org')
ALLOWED={'eth_chainId','eth_getBlockByNumber','eth_getBlockByHash','eth_call'}
HEADERS={'Content-Type':'application/json','Accept':'application/json','User-Agent':'AeroPredict/1.0 (read-only research)'}

def now():return datetime.now(timezone.utc).isoformat()
def iso(ts):return datetime.fromtimestamp(ts,timezone.utc).isoformat()
def compact(x):return json.dumps(x,ensure_ascii=False,separators=(',',':'))
def digest(x):return hashlib.sha256(compact(x).encode()).hexdigest()
def save_new(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8') as f:f.write(compact(value))
def replace_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.tmp')
    with tmp.open('w',encoding='utf-8') as f:f.write(compact(value));f.flush();os.fsync(f.fileno())
    os.replace(tmp,path)
def calldata(sig,*args):
    types=sig[sig.index('(')+1:-1].split(',') if args else []
    return '0x'+(keccak(text=sig)[:4]+encode(types,args)).hex()
def rpc(method,params):
    if method not in ALLOWED:raise ValueError('Read-only allowlist')
    payload=compact({'jsonrpc':'2.0','id':1,'method':method,'params':params}).encode()
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(RPCS[attempt%2],payload,HEADERS),timeout=35) as r:result=json.load(r)
            if 'error' in result:raise ValueError('RPC rejected read')
            return result['result']
        except (OSError,ValueError,KeyError):
            if attempt==3:raise RuntimeError('Public Base read unavailable; previous snapshot retained') from None
            time.sleep(2**attempt)
def word(row):
    ok,raw=row
    if not ok or len(raw)!=32:raise ValueError('Missing ABI word')
    return int.from_bytes(raw,'big')
def addr(row):
    n=word(row)
    if n>=2**160:raise ValueError('Invalid ABI address')
    return '0x'+f'{n:040x}'
def optional_address(row):
    try:return addr(row)
    except ValueError:return None
def symbol(row):
    if not row[0]:return 'UNKNOWN'
    try:value=decode(['string'],row[1])[0]
    except Exception:value=row[1][:32].rstrip(b'\0').decode('utf-8','replace')
    # Untrusted token strings are rendered as text by the client.
    return str(value)[:60] or 'UNKNOWN'

class Reader:
    def __init__(self,run,block):self.run=run;self.tag={'blockHash':block['hash'],'requireCanonical':True};self.http_calls=0
    def phase(self,name,calls):
        def part(item):
            n,chunk=item
            encoded='0x'+(keccak(text='aggregate3((address,bool,bytes)[])')[:4]+encode(['(address,bool,bytes)[]'],[[(to,True,bytes.fromhex(data[2:])) for to,data in chunk]])).hex()
            key=digest({'block':self.tag,'data':encoded})
            file=self.run/'checkpoints'/f'{name}-{n:04d}.json'
            if file.exists():
                stored=json.loads(file.read_text(encoding='utf-8'))
                if stored['request_sha256']!=key or digest(stored['result'])!=stored['result_sha256']:raise ValueError('Checkpoint mismatch')
                raw=stored['result']
            else:
                raw=rpc('eth_call',[{'to':MULTICALL,'data':encoded},self.tag]);self.http_calls+=1
                values=decode(['(bool,bytes)[]'],bytes.fromhex(raw[2:]))[0]
                if len(values)!=len(chunk):raise ValueError('Truncated multicall')
                save_new(file,{'request_sha256':key,'block_hash':self.tag['blockHash'],'result':raw,'result_sha256':digest(raw),'observed_at_utc':now(),'count':len(chunk)})
            values=decode(['(bool,bytes)[]'],bytes.fromhex(raw[2:]))[0]
            if len(values)!=len(chunk):raise ValueError('Checkpoint count mismatch')
            return values
        chunks=[calls[i:i+120] for i in range(0,len(calls),120)]
        out=[]
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            for i,values in enumerate(pool.map(part,enumerate(chunks)),1):
                out.extend(values)
                if i%20==0 or i==len(chunks):print(compact({'phase':name,'done':i,'chunks':len(chunks)}),flush=True)
        return out

def get_prices(tokens):
    out={}
    for i in range(0,len(tokens),20):
        part=tokens[i:i+20]
        try:
            req=urllib.request.Request('https://coins.llama.fi/prices/current/'+','.join('base:'+x for x in part),headers=HEADERS)
            with urllib.request.urlopen(req,timeout=25) as r:coins=json.load(r).get('coins',{})
        except (OSError,ValueError):coins={}
        for token in part:
            item=coins.get('base:'+token,{})
            price=None;timestamp=None
            try:
                p=Decimal(str(item['price']));ts=int(item['timestamp'])
                if p.is_finite() and p>0 and -300<=time.time()-ts<=36*3600:price=str(p);timestamp=iso(ts)
            except (KeyError,ValueError,TypeError,ArithmeticError):pass
            out[token]={'usd':price,'timestamp_utc':timestamp}
    return out

def value_usd(raw,metadata,quote):
    if raw is None:return None
    if int(raw)==0:return Decimal(0)
    if metadata.get('decimals') is None or quote.get('usd') is None:return None
    with localcontext() as ctx:
        ctx.prec=90
        return Decimal(raw)/(Decimal(10)**metadata['decimals'])*Decimal(quote['usd'])

def summarize(pools,metadata,prices,weeks,context):
    totals=[]
    for j,start in enumerate(weeks):
        kinds={}
        for kind in ['fees','bribes']:
            known=Decimal(0);unknown_entries=0;incomplete=set();by_token={}
            for p in pools:
                for t in p['rewards'][kind]['tokens']:
                    token=t['token_address'];raw=t['raw'][j];m=metadata.get(token,{});q=prices.get(token,{})
                    value=value_usd(raw,m,q)
                    entry=by_token.setdefault(token,{'address':token,'symbol':m.get('symbol','UNKNOWN'),'decimals':m.get('decimals'),'raw':0,'known_usd':Decimal(0),'unknown':False})
                    if raw is not None:entry['raw']+=int(raw)
                    if value is None:unknown_entries+=1;incomplete.add(p['index']);entry['unknown']=True
                    else:known+=value;entry['known_usd']+=value
            token_rows=[dict(v,raw=str(v['raw']),known_usd=str(v['known_usd'])) for v in by_token.values()]
            token_rows.sort(key=lambda x:Decimal(x['known_usd']),reverse=True)
            kinds[kind]={'known_usd':str(known),'complete_usd':str(known) if unknown_entries==0 else None,'unknown_token_entries':unknown_entries,'incomplete_pools':len(incomplete),'pool_count':len(pools),'tokens':token_rows}
        totals.append({'start_utc':iso(start),'end_utc':iso(start+WEEK),'complete':start+WEEK<=context['block_timestamp'],'fees':kinds['fees'],'bribes':kinds['bribes']})
    rows=[]
    for p in pools:
        amounts={kind:[] for kind in ['fees','bribes']}
        for kind in amounts:
            for j in range(len(weeks)):
                values=[value_usd(t['raw'][j],metadata.get(t['token_address'],{}),prices.get(t['token_address'],{})) for t in p['rewards'][kind]['tokens']]
                amounts[kind].append(None if any(v is None for v in values) else str(sum(values,Decimal(0))))
        rows.append({'index':p['index'],'address':p['pool_address'],'gauge':p['gauge_address'],'pair':p['pair'],'votes_raw':p['vote_weight_raw'],'alive_at_snapshot':p['active_at_collection'],'usd_complete':all(v is not None for a in amounts.values() for v in a[:4]),'fees':amounts['fees'][:4],'bribes':amounts['bribes'][:4],'current_fees':amounts['fees'][4],'current_bribes':amounts['bribes'][4],'source_status':'PROVIDER_OBSERVED','rewards':p['rewards']})
    return {'schema_version':1,'context':context,'pool_count':len(rows),'registry_length':context['registry_length'],'observed_at_utc':context['completed_at_utc'],'genlayer_status':'NOT_ATTESTED_FOR_THIS_SNAPSHOT','totals':totals,'pools':rows}

def validate_snapshot(s,previous=None):
    rows=s['pools'];ctx=s['context']
    if ctx['chain_id']!=8453 or len(rows)!=s['registry_length'] or len({p['index'] for p in rows})!=len(rows):raise ValueError('Incomplete registry')
    if sorted(p['index'] for p in rows)!=list(range(s['registry_length'])):raise ValueError('Registry gap')
    if len(s['totals'])!=5 or any(len(p['fees'])!=4 or len(p['bribes'])!=4 for p in rows):raise ValueError('Incomplete weeks')
    if previous:
        if int(ctx['block_number'])<int(previous['context']['block_number']):raise ValueError('Block regression')
        if s['registry_length']<previous['registry_length']:raise ValueError('Registry shrank')
        current={p['index']:p['address'] for p in rows}
        if any(current.get(p['index'])!=p['address'] for p in previous['pools']):raise ValueError('Existing pool identity changed')
    return True

def collect(output,labels_path,resume=None):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    if int(rpc('eth_chainId',[]),16)!=8453:raise ValueError('Wrong network')
    previous=json.loads((output/'latest.json').read_text(encoding='utf-8')) if (output/'latest.json').exists() else None
    if resume:
        run=Path(resume);ctx=json.loads((run/'context.json').read_text(encoding='utf-8'));block={'hash':ctx['block_hash']}
    else:
        block=rpc('eth_getBlockByNumber',['finalized',False]);ts=int(block['timestamp'],16);end=(ts//WEEK)*WEEK
        if not 0<=time.time()-ts<=3*3600:raise ValueError('Finalized block is stale or in future')
        ctx={'chain_id':8453,'block_number':int(block['number'],16),'block_hash':block['hash'],'block_timestamp':ts,'started_at_utc':now(),'latest_completed_epoch_end_utc':iso(end),'quote_policy':'Current provider price observation; not historical prices','state_policy':'Five epoch keys at one finalized post-period block, not five boundary snapshots'}
        run=output/'runs'/('block_'+str(ctx['block_number'])+'_'+ctx['block_hash'][2:10]);save_new(run/'context.json',ctx)
    reader=Reader(run,block);end=(ctx['block_timestamp']//WEEK)*WEEK;weeks=[end-WEEK*n for n in [4,3,2,1,0]]
    n=word(reader.phase('registry_length',[(VOTER,calldata('length()'))])[0])
    if not 1<=n<=20000:raise ValueError('Unexpected registry size')
    ctx['registry_length']=n
    addresses=[addr(x) for x in reader.phase('pool_addresses',[(VOTER,calldata('pools(uint256)',i)) for i in range(n)])]
    if len(set(addresses))!=n or ZERO in addresses:raise ValueError('Duplicate or zero registered pool')
    if previous and (n<previous['registry_length'] or any(addresses[p['index']]!=p['address'] for p in previous['pools'])):raise ValueError('Registry continuity changed')
    labels=json.loads(Path(labels_path).read_text(encoding='utf-8'))
    for key,p in labels.items():
        if int(key)>=n or addresses[int(key)]!=p['address'].lower():raise ValueError('Seed identity changed')
    vals=reader.phase('gauges_weights',[(VOTER,calldata(sig,p)) for p in addresses for sig in ['gauges(address)','weights(address)']])
    pools=[{'index':i,'pool_address':p,'gauge_address':addr(vals[2*i]),'vote_weight_raw':str(word(vals[2*i+1])),'pair':labels.get(str(i),{}).get('pair') or '#'+str(i),'rewards':{}} for i,p in enumerate(addresses)]
    gauges=[p for p in pools if p['gauge_address']!=ZERO]
    vals=reader.phase('gauge_details',[(VOTER,calldata(sig,p['gauge_address'])) for p in gauges for sig in ['isGauge(address)','isAlive(address)','gaugeToFees(address)','gaugeToBribe(address)']])
    for i,p in enumerate(gauges):
        if word(vals[4*i])!=1:raise ValueError('Unregistered gauge mapping')
        alive=word(vals[4*i+1])
        if alive not in [0,1]:raise ValueError('Invalid active flag')
        p['active_at_collection']=bool(alive);p['fees_contract']=addr(vals[4*i+2]);p['bribes_contract']=addr(vals[4*i+3])
    for p in pools:
        if p['gauge_address']==ZERO:p.update(active_at_collection=False,fees_contract=ZERO,bribes_contract=ZERO)
    targets=[]
    for p in pools:
        for kind in ['fees','bribes']:
            c=p[kind+'_contract'];p['rewards'][kind]={'contract':c,'tokens':[],'registered_count':0}
            if c!=ZERO:targets.append((p,kind,c))
    vals=reader.phase('reward_lengths',[(c,calldata(sig)) for p,k,c in targets for sig in ['DURATION()','rewardsListLength()']])
    token_targets=[]
    for i,(p,k,c) in enumerate(targets):
        duration=word(vals[2*i]);count=word(vals[2*i+1])
        if duration!=WEEK or count>500:raise ValueError('Invalid reward registry')
        p['rewards'][k]['registered_count']=count
        token_targets.extend((p,k,c,j) for j in range(count))
    vals=reader.phase('reward_tokens',[(c,calldata('rewards(uint256)',j)) for p,k,c,j in token_targets])
    tokens=set()
    for (p,k,c,j),row in zip(token_targets,vals):
        token=addr(row)
        if token==ZERO or any(t['token_address']==token for t in p['rewards'][k]['tokens']):raise ValueError('Invalid or duplicate reward token')
        p['rewards'][k]['tokens'].append({'token_address':token,'raw':[]});tokens.add(token)
    pair_vals=reader.phase('pair_tokens',[(p['pool_address'],calldata(sig)) for p in pools for sig in ['token0()','token1()']])
    for i,p in enumerate(pools):
        p['pair_tokens']=[optional_address(pair_vals[2*i]),optional_address(pair_vals[2*i+1])]
        tokens.update(x for x in p['pair_tokens'] if x and x!=ZERO)
    tokens=sorted(tokens)
    vals=reader.phase('metadata',[(t,calldata(sig)) for t in tokens for sig in ['decimals()','symbol()']]);metadata={}
    for i,t in enumerate(tokens):
        try:d=word(vals[2*i]);d=d if d<=36 else None
        except ValueError:d=None
        metadata[t]={'decimals':d,'symbol':symbol(vals[2*i+1])}
    for p in pools:
        if str(p['index']) not in labels:
            pts=p['pair_tokens'];p['pair']=' / '.join(metadata[t]['symbol'] for t in pts) if all(t and t!=ZERO for t in pts) else 'Özel / tanımlanamayan sözleşme'
    amount_targets=[(p,k,t,j,start) for p in pools for k in ['fees','bribes'] for t in p['rewards'][k]['tokens'] for j,start in enumerate(weeks)]
    vals=reader.phase('epoch_amounts',[(p[k+'_contract'],calldata('tokenRewardsPerEpoch(address,uint256)',t['token_address'],start)) for p,k,t,j,start in amount_targets])
    for (p,k,t,j,start),v in zip(amount_targets,vals):t['raw'].append(str(word(v)))
    prices_file=run/'prices.json'
    if prices_file.exists():prices=json.loads(prices_file.read_text(encoding='utf-8'))
    else:prices=get_prices(tokens);save_new(prices_file,prices)
    canonical=rpc('eth_getBlockByNumber',[hex(ctx['block_number']),False])
    if not canonical or canonical['hash'].lower()!=ctx['block_hash'].lower():raise ValueError('Pinned block is no longer canonical')
    ctx.update(completed_at_utc=now(),active_gauge_count=sum(p['active_at_collection'] for p in pools),http_multicalls_this_attempt=reader.http_calls)
    current={p['index'] for p in pools};old={p['index'] for p in previous['pools']} if previous else set(map(int,labels))
    ctx['added_to_tracking']=sorted(current-old);ctx['new_registrations']=list(range(previous['registry_length'],n)) if previous else []
    save_new(run/'raw.json',{'context':ctx,'pools':pools,'metadata':metadata,'prices':prices})
    snapshot=summarize(pools,metadata,prices,weeks,ctx);validate_snapshot(snapshot,previous)
    save_new(run/'snapshot.json',snapshot)
    # This is the only mutable data pointer; failures above cannot erase success.
    for total in snapshot['totals'][:4]:
        file=output/'weekly'/total['end_utc'][:10]/('block_'+str(ctx['block_number'])+'.json')
        save_new(file,{'context':ctx,'totals':total,'pools':[{'index':p['index'],'address':p['address'],'fees':p['fees'][snapshot['totals'].index(total)],'bribes':p['bribes'][snapshot['totals'].index(total)]} for p in snapshot['pools']]})
    replace_json(output/'latest.json',snapshot)
    print(compact({'state':'complete','pool_count':len(pools),'active':ctx['active_gauge_count'],'block':ctx['block_number'],'added_to_tracking':len(ctx['added_to_tracking']),'new_registrations':len(ctx['new_registrations']),'run':str(run)}),flush=True)
    return snapshot

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--labels',type=Path,default=Path(__file__).with_name('labels.json'));p.add_argument('--resume',type=Path);p.add_argument('--live',action='store_true');a=p.parse_args()
    if not a.live:raise SystemExit('Explicit --live required for read-only network collection')
    try:collect(a.output,a.labels,a.resume)
    except Exception as e:
        # No raw URLs, responses, credentials, or environment variables in logs.
        replace_json(a.output/'status.json',{'state':'failed','at_utc':now(),'error_type':type(e).__name__,'message':'Full refresh failed; previous successful data retained'})
        print(compact({'state':'failed','error_type':type(e).__name__,'message':str(e) if isinstance(e,ValueError) else 'Read unavailable; previous data retained'}),flush=True)
        raise SystemExit(1)
    else:replace_json(a.output/'status.json',{'state':'complete','at_utc':now(),'pool_count':json.loads((a.output/'latest.json').read_text(encoding='utf-8'))['pool_count']})
if __name__=='__main__':main()
