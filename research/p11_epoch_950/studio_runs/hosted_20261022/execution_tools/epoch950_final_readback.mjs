// Separate read-only audit. Run only after the 950-pool execution completes.
import fs from 'node:fs';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import {abi} from './genlayer-cli/node_modules/genlayer-js/dist/index.js';
const dir='outputs/epoch950-20261022',run=JSON.parse(fs.readFileSync(dir+'/hosted-runtime.json')),plan=JSON.parse(fs.readFileSync(dir+'/batch-plan.json'));
assert(run.passed&&run.summary.verified_pools===950,'Full execution has not completed.');
const canonical=v=>v===null||typeof v!=='object'?JSON.stringify(v):Array.isArray(v)?'['+v.map(canonical).join(',')+']':'{'+Object.keys(v).sort().map(k=>JSON.stringify(k)+':'+canonical(v[k])).join(',')+'}';
const sha=b=>crypto.createHash('sha256').update(b).digest('hex');
const endpoint='https://studio.genlayer.com/api',ZERO='0x0000000000000000000000000000000000000000';
let serial=1;
async function batch(items){assert(items.length<=10);assert(items.every(x=>['eth_chainId','gen_getContractCode','gen_call','eth_getTransactionByHash'].includes(x.method)));const requests=items.map(x=>({...x,jsonrpc:'2.0',id:serial++}));const r=await fetch(endpoint,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(requests),signal:AbortSignal.timeout(55000)});assert(r.ok);const data=await r.json();assert(Array.isArray(data)&&data.length===items.length);const byId=new Map(data.map(d=>[d.id,d]));return requests.map(q=>{const d=byId.get(q.id);assert(d&&!d.error);return d.result;});}
function view(method,args=[]){return {method:'gen_call',params:[{type:'read',to:run.contract_address,from:ZERO,data:abi.transactions.serialize([abi.calldata.encode(abi.calldata.makeCalldataObject(method,args,undefined)),false]),transaction_hash_variant:'latest-final'}]};}
function decode(value){const h=typeof value==='string'?value:value.data;return JSON.parse(abi.calldata.decode(Uint8Array.from(h.match(/../g),b=>parseInt(b,16))));}
const [chain,code,state]=await batch([{method:'eth_chainId',params:[]},{method:'gen_getContractCode',params:[run.contract_address]},view('get_summary')]);
assert.equal(parseInt(chain,16),61999);assert.equal(sha(Buffer.from(code,'base64')),'b835f9a011c785f780576f09e56f9399b8bbccca11c6121357a053ddbce43436');const summary=decode(state);assert.equal(summary.root,plan.merkle_root);assert.equal(summary.verified_pools,950);assert.equal(summary.block_hash,plan.context.block.hash);
const entries=plan.batches.flatMap(b=>JSON.parse(b));assert.equal(Object.keys(run.pool_results).length,950);
for(const e of entries){const saved=run.pool_results[e.claim.index];assert.equal(saved.status,'VERIFIED');assert.equal(saved.claim_sha256,sha(canonical(e.claim)));assert.equal(saved.block_hash,summary.block_hash);}
const receipts=[];assert.equal(run.transactions.length,96);assert.equal(run.broadcast_attempts,96);
for(let i=0;i<run.transactions.length;i+=10){
 const saved=run.transactions.slice(i,i+10),current=await batch(saved.map(t=>({method:'eth_getTransactionByHash',params:[t.hash]})));
 for(let j=0;j<current.length;j++){const tx=current[j],t=saved[j],votes=Object.values(tx.consensus_data?.votes||{});assert.equal(tx.hash,t.hash);assert.equal(tx.status,'FINALIZED');assert.equal(tx.to_address.toLowerCase(),run.contract_address.toLowerCase());assert(votes.filter(v=>v==='agree').length>=3);receipts.push({hash:t.hash,label:t.label,status:tx.status,agree:votes.filter(v=>v==='agree').length,idle:votes.filter(v=>v==='idle').length});}
 console.log('Receipt audit '+receipts.length+'/96');
}
const samples=Array.from(new Set([0,1130,...Array.from({length:8},(_,i)=>entries[Math.floor(i*949/7)].claim.index)]));
const sampled=await batch(samples.map(index=>view('get_pool_result',[index])));const pool_readbacks=sampled.map((d,i)=>{const result=decode(d);assert.equal(result.index,samples[i]);assert.equal(result.claim_sha256,run.pool_results[samples[i]].claim_sha256);assert.equal(result.status,'VERIFIED');return result;});
fs.writeFileSync(dir+'/hosted-independent-readback.json',JSON.stringify({checked_at_utc:new Date().toISOString(),chain_id:61999,contract_address:run.contract_address,source_sha256:sha(Buffer.from(code,'base64')),summary,receipts,pool_readbacks,execution_all_pool_readbacks_checked:950,independent_pool_view_sample_count:samples.length,transactions_sent:0,independent_public_operator_consensus:false,passed:true},null,2));console.log('PASS: pinned source/root, full950 summary, every96 receipt and independent pool view samples match.');
