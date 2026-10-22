# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
"""Pinned Base epoch data attestation. Does not settle forecasts or verify USD.

The constructor commits to exactly 950 complete raw claims with a Merkle root.
Each write has at most ten claims. Validators independently reconstruct and
execute every identity, registry and reward call at the committed canonical
Base block. A successful receipt alone is insufficient: inspect pool results.
"""
import json
import hashlib
import genlayer as gl
from genlayer import *

BASE_RPC = 'https://base-rpc.publicnode.com'
VOTER = '0x16613524e02ad97edfef371bc883f2f5d6c480a5'
MULTICALL = '0xca11bde05977b3631167028862be2a173976ca11'
ZERO = '0x' + '0' * 40
WEEK = 604800
# Keccak selectors are generated from the audited Solidity signatures below.
SELECTORS = {'pools(uint256)': 'ac4afa38', 'gauges(address)': 'b9a09fd5', 'weights(address)': 'a7cac846', 'isAlive(address)': '1703e5f9', 'gaugeToFees(address)': 'c4f08165', 'gaugeToBribe(address)': '929c8dcd', 'DURATION()': '1be05289', 'rewardsListLength()': 'e6886396', 'rewards(uint256)': 'f301af42', 'tokenRewardsPerEpoch(address,uint256)': '92777b29'}

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'))

def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()

def word(n):
    if type(n) is not int or n < 0 or n >= 2**256:
        raise ValueError('Invalid uint256')
    return n.to_bytes(32, 'big')

def address(value):
    if type(value) is not str or len(value) != 42 or not value.startswith('0x'):
        raise ValueError('Invalid address')
    int(value[2:], 16)
    if value != value.lower():
        raise ValueError('Noncanonical address')
    return value

def call(signature, *args):
    data = bytes.fromhex(SELECTORS[signature])
    for arg in args:
        data += word(int(address(arg), 16)) if type(arg) is str and arg.startswith('0x') else word(arg)
    return '0x' + data.hex()

def aggregate(calls):
    items = []
    for target, data, expected in calls:
        raw = bytes.fromhex(data[2:])
        items.append(word(int(address(target),16)) + word(1) + word(96) + word(len(raw)) + raw + b'\0' * (-len(raw) % 32))
    offsets = []; offset = len(items)*32
    for item in items:
        offsets.append(word(offset)); offset += len(item)
    return '0x' + (bytes.fromhex('82ad56cb') + word(32) + word(len(items)) + b''.join(offsets) + b''.join(items)).hex()

def unaggregate(value, expected_count):
    raw = bytes.fromhex(value[2:])
    def uint(pos):
        if pos < 0 or pos+32 > len(raw):
            raise ValueError('Truncated Multicall ABI')
        return int.from_bytes(raw[pos:pos+32], 'big')
    if uint(0) != 32 or uint(32) != expected_count:
        raise ValueError('Unexpected Multicall result count')
    base = 64; result = []
    for i in range(expected_count):
        offset = uint(base+i*32)
        if offset < expected_count*32 or offset % 32:
            raise ValueError('Invalid result offset')
        pos = base+offset
        if uint(pos) != 1 or uint(pos+32) != 64:
            raise ValueError('Required Base call failed')
        size = uint(pos+64)
        if size != 32 or pos+96+size > len(raw):
            raise ValueError('Expected a complete ABI word')
        result.append(raw[pos+96:pos+128].hex())
    return result

def claim_calls(p, epoch):
    if p['errors'] or type(p['index']) is not int or p['index'] < 0:
        raise ValueError('Incomplete claim')
    pool=address(p['pool_address']); gauge=address(p['gauge_address']); output=[]
    def add(target,sig,args,value):
        output.append((target,call(sig,*args),word(value).hex()))
    add(VOTER,'pools(uint256)',[p['index']],int(pool,16))
    add(VOTER,'gauges(address)',[pool],int(gauge,16))
    add(VOTER,'weights(address)',[pool],int(p['vote_weight_raw']))
    if type(p['active_at_collection']) is not bool:
        raise ValueError('Invalid active flag')
    add(VOTER,'isAlive(address)',[gauge],int(p['active_at_collection']))
    for kind,sig in [('fees','gaugeToFees(address)'),('bribes','gaugeToBribe(address)')]:
        target=address(p[kind+'_contract']); registry=p['rewards'][kind]
        add(VOTER,sig,[gauge],int(target,16))
        tokens=registry['tokens'];count=registry['registered_count']
        if registry['contract'] != target or count != len(tokens) or count > 500:
            raise ValueError('Truncated or inconsistent registry')
        if target == ZERO:
            if count or registry['duration'] is not None:
                raise ValueError('Nonempty zero-address registry')
            continue
        if registry['duration'] != WEEK:
            raise ValueError('Unexpected reward duration')
        add(target,'DURATION()',[],WEEK)
        add(target,'rewardsListLength()',[],count)
        seen=set()
        for i,t in enumerate(tokens):
            token=address(t['token_address'])
            if t['registry_index'] != i or token == ZERO or token in seen or len(t['raw']) != 4:
                raise ValueError('Invalid token registry')
            seen.add(token);add(target,'rewards(uint256)',[i],int(token,16))
            for week,value in enumerate(t['raw']):
                if type(value) is not str or not value.isdigit():
                    raise ValueError('Unknown reward is not zero')
                add(target,'tokenRewardsPerEpoch(address,uint256)',[token,epoch-WEEK*(4-week)],int(value))
    return output

def verify_membership(entry,root):
    pos=entry['position']
    if type(pos) is not int or not 0 <= pos < 950 or len(entry['proof']) != 10:
        raise ValueError('Invalid cohort position')
    leaf=digest(entry['claim']);node=bytes.fromhex(leaf)
    for sibling in entry['proof']:
        other=bytes.fromhex(sibling)
        if len(other) != 32:
            raise ValueError('Invalid Merkle proof')
        node=hashlib.sha256(other+node if pos%2 else node+other).digest();pos//=2
    if node.hex()!=root:
        raise ValueError('Claim outside committed cohort')
    return leaf

class Epoch950Verifier(gl.Contract):
    root: str
    block_hash: str
    block_number: u256
    epoch_end: u256
    multicall_sha256: str
    results_json: str

    def __init__(self, root: str, block_hash: str, block_number: int, epoch_end: int, multicall_sha256: str):
        if len(bytes.fromhex(root)) != 32 or len(bytes.fromhex(block_hash[2:])) != 32 or len(bytes.fromhex(multicall_sha256)) != 32 or epoch_end % WEEK or block_number <= 0:
            raise ValueError('Invalid pinned context')
        self.root=root;self.block_hash=block_hash;self.block_number=u256(block_number)
        self.epoch_end=u256(epoch_end);self.multicall_sha256=multicall_sha256;self.results_json='{}'

    @gl.public.write
    def verify_batch(self, payload: str) -> None:
        if len(payload)>180000:
            raise ValueError('Batch too large')
        batch=json.loads(payload)
        if type(batch) is not list or not 1<=len(batch)<=10:
            raise ValueError('One to ten pools required')
        results=json.loads(self.results_json);new={};calls=[]
        for entry in batch:
            leaf=verify_membership(entry,self.root);key=str(entry['claim']['index'])
            if key in results or key in new:
                raise ValueError('Pool already verified')
            new[key]=leaf;calls.extend(claim_calls(entry['claim'],int(self.epoch_end)))
        if len(calls)>2500:
            raise ValueError('Split this batch')
        tag={'blockHash':self.block_hash,'requireCanonical':True}
        def fetch_and_compare() -> str:
            def rpc(method,params):
                response=gl.nondet.web.request(BASE_RPC,method='POST',headers={'Content-Type':'application/json'},body=json.dumps({'jsonrpc':'2.0','id':1,'method':method,'params':params}))
                if response.status!=200 or response.body is None:
                    raise ValueError('Base HTTP read failed')
                doc=json.loads(response.body.decode('utf-8'))
                if 'error' in doc or 'result' not in doc:
                    raise ValueError('Base RPC rejected read')
                return doc['result']
            if int(rpc('eth_chainId',[]),16)!=8453:
                raise ValueError('Wrong Base chain')
            block=rpc('eth_getBlockByHash',[self.block_hash,False]);finalized=rpc('eth_getBlockByNumber',['finalized',False])
            if block is None or block['hash']!=self.block_hash or int(block['number'],16)!=int(self.block_number) or int(block['timestamp'],16)<int(self.epoch_end) or int(finalized['number'],16)<int(self.block_number):
                raise ValueError('Block is not a completed finalized epoch state')
            code=rpc('eth_getCode',[MULTICALL,tag])
            if hashlib.sha256(bytes.fromhex(code[2:])).hexdigest()!=self.multicall_sha256:
                raise ValueError('Unexpected Multicall code')
            for start in range(0,len(calls),150):
                chunk=calls[start:start+150]
                actual=unaggregate(rpc('eth_call',[{'to':MULTICALL,'data':aggregate(chunk)},tag]),len(chunk))
                if actual != [c[2] for c in chunk]:
                    raise ValueError('Base data differs from committed claim')
            return digest(new)
        if gl.eq_principle.strict_eq(fetch_and_compare)!=digest(new):
            raise ValueError('No matching validator result')
        results.update(new);self.results_json=canonical(results)

    @gl.public.view
    def get_summary(self) -> str:
        return canonical({'root':self.root,'block_hash':self.block_hash,'block_number':int(self.block_number),'epoch_end':int(self.epoch_end),'expected_pools':950,'verified_pools':len(json.loads(self.results_json)),'scope':'Raw Base identities, full reward registries and four epoch amounts; USD and forecast outcomes excluded'})

    @gl.public.view
    def get_pool_result(self, index: int) -> str:
        leaf=json.loads(self.results_json).get(str(index))
        return canonical({'index':index,'status':'VERIFIED' if leaf else 'NOT_VERIFIED','claim_sha256':leaf,'block_hash':self.block_hash,'epoch_end':int(self.epoch_end)})
