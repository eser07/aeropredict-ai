// Never run without new explicit human approval of the matching plan hash.
// Keys stay in memory. No faucet, settlement, personal wallet or real funds.
import fs from 'node:fs';
import crypto from 'node:crypto';
import assert from 'node:assert/strict';
import {createClient,createAccount,abi} from './genlayer-cli/node_modules/genlayer-js/dist/index.js';
import {studionet} from './genlayer-cli/node_modules/genlayer-js/dist/chains/index.js';
const sha=b=>crypto.createHash('sha256').update(b).digest('hex');
const canonical=v=>v===null||typeof v!=='object'?JSON.stringify(v):Array.isArray(v)?'['+v.map(canonical).join(',')+']':'{'+Object.keys(v).sort().map(k=>JSON.stringify(k)+':'+canonical(v[k])).join(',')+'}';
const file='outputs/epoch950-20261022/approval-plan.json',bytes=fs.readFileSync(file),plan=JSON.parse(bytes);
assert(process.argv.includes('--execute'),'Preparation only; explicit execute flag and approved plan SHA256 required.');
assert.equal(process.argv[process.argv.indexOf('--approved-plan')+1],sha(bytes),'Approved plan hash does not match.');
const bundleBytes=fs.readFileSync('outputs/epoch950-20261022/batch-plan.json');assert.equal(sha(bundleBytes),plan.batch_plan_sha256);
const bundle=JSON.parse(bundleBytes),code=fs.readFileSync(new URL('./Epoch950Verifier.py',import.meta.url),'utf8');assert.equal(sha(Buffer.from(code)),plan.source_sha256);assert.equal(bundle.batches.length,95);
const endpoint='https://studio.genlayer.com/api',out='outputs/epoch950-20261022/hosted-runtime.json';
const report=fs.existsSync(out)?JSON.parse(fs.readFileSync(out,'utf8')):{plan_sha256:sha(bytes),started_at_utc:new Date().toISOString(),chain_id:61999,transactions:[],broadcast_attempts:0,verified_batches:[],protocol_fee_gen:null,total_usd:null};
report.pool_results ||= {};
assert.equal(report.plan_sha256,sha(bytes));assert(!report.passed,'Completed run is read-only; do not replay.');
const save=()=>fs.writeFileSync(out,JSON.stringify(report,null,2));
const nativeFetch=globalThis.fetch;let nextAt=0,lastEstimate=null;
globalThis.fetch=async(url,options)=>{
 assert.equal(String(url),endpoint);const req=JSON.parse(options.body);
 const isBatch=Array.isArray(req);
 assert(isBatch?req.length<=10&&req.every(q=>q.method==='gen_call'&&q.params[0].type==='read'):['eth_chainId','eth_gasPrice','eth_estimateGas','eth_getBalance','eth_getTransactionCount','eth_getTransactionByHash','eth_getTransactionReceipt','eth_sendRawTransaction','gen_call','gen_getContractCode','gen_getContractSchemaForCode'].includes(req.method),'Unexpected RPC operation');
 if(Date.now()<nextAt)await new Promise(r=>setTimeout(r,nextAt-Date.now()));nextAt=Date.now()+1100;
 if(req.method==='eth_estimateGas')lastEstimate=null;
 if(req.method==='eth_sendRawTransaction'){assert(report.broadcast_attempts<96,'Approved transaction ceiling reached');report.broadcast_attempts++;save();}
 let r;const canRetry=req.method!=='eth_sendRawTransaction';
 for(let attempt=0;attempt<(canRetry?3:1);attempt++){
  r=await nativeFetch(url,{...options,redirect:'error',signal:AbortSignal.timeout(55000)});
  if(r.ok&&String(r.headers.get('content-type')).includes('json'))break;
  report.last_http_failure={method:isBatch?'read-only gen_call batch':req.method,status:r.status,at_utc:new Date().toISOString()};save();
  // Respect denial responses; bounded retries only cover transient read errors.
  if(!canRetry||r.status===403||r.status===401||attempt===2)throw Error('Hosted HTTP/non-JSON '+r.status+' during '+(isBatch?'read batch':req.method)+'; no write retried.');
  report.read_retries=(report.read_retries||0)+1;save();await new Promise(resolve=>setTimeout(resolve,2000*(attempt+1)));
 }
 if(['eth_estimateGas','eth_gasPrice'].includes(req.method)){
  const d=await r.clone().json();assert(!d.error);
  if(req.method==='eth_gasPrice')assert.equal(BigInt(d.result),0n,'Nonzero gas price outside scope');
  else {assert(BigInt(d.result)>0n&&BigInt(d.result)<=30000000n);lastEstimate={sha:sha(Buffer.from(req.params[0].data)),gas:BigInt(d.result),time:Date.now()};}
 }
 return r;
};
async function rpc(method,params=[]){const r=await fetch(endpoint,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({jsonrpc:'2.0',id:1,method,params})});const d=await r.json();if(d.error)throw Error('Hosted RPC '+method+' rejected '+d.error.code);return d.result;}
async function poolBatch(address,entries){
 const requests=entries.map((e,id)=>({jsonrpc:'2.0',id,method:'gen_call',params:[{type:'read',to:address,from:'0x0000000000000000000000000000000000000000',data:abi.transactions.serialize([abi.calldata.encode(abi.calldata.makeCalldataObject('get_pool_result',[e.claim.index],undefined)),false]),transaction_hash_variant:'latest-final'}]}));
 const r=await fetch(endpoint,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(requests)});const body=await r.json();assert(Array.isArray(body)&&body.length===entries.length);const byId=new Map(body.map(v=>[v.id,v]));
 return entries.map((e,i)=>{const d=byId.get(i);assert(d&&!d.error);assert(!d.result?.status||d.result.status.code===0);const hex=typeof d.result==='string'?d.result:d.result.data;assert(typeof hex==='string'&&/^(?:[0-9a-fA-F]{2})+$/.test(hex));return JSON.parse(abi.calldata.decode(Uint8Array.from(hex.match(/../g),x=>parseInt(x,16))));});
}
async function boundary(){assert.equal(parseInt(await rpc('eth_chainId'),16),61999);assert.equal(BigInt(await rpc('eth_gasPrice')),0n);}
function verifyReceipt(tx){assert.equal(tx.status,'FINALIZED');assert(Object.values(tx.consensus_data?.votes||{}).filter(v=>v==='agree').length>=3,'Missing validator majority');}
async function receipt(hash,row){const client=createClient({chain:studionet,endpoint});await client.waitForTransactionReceipt({hash,status:'FINALIZED',interval:4000,retries:75,fullTransaction:true});const tx=await rpc('eth_getTransactionByHash',[hash]);verifyReceipt(tx);row.status=tx.status;row.contract_address=tx.to_address;row.votes=tx.consensus_data.votes;row.finalized_at_utc=new Date().toISOString();row.evm_receipt=await rpc('eth_getTransactionReceipt',[hash]);save();return tx;}
async function send(client,label,run){await boundary();const row={label,state:'PREPARING',at_utc:new Date().toISOString()};report.transactions.push(row);save();const hash=await run();row.hash=hash;row.state='SUBMITTED';save();console.log(label+' submitted');const tx=await receipt(hash,row);row.state='FINALIZED';save();console.log(label+' FINALIZED');return tx;}
try{
 assert.equal(studionet.id,61999);assert.equal(studionet.isStudio,true);await boundary();
 // A pending broadcast is inspected first. An ambiguous send without a hash
 // cannot be replayed automatically, even if the client failed before saving it.
 for(const row of report.transactions.filter(t=>t.state!=='FINALIZED')){
  assert(row.hash,'Ambiguous preparation/broadcast: reconcile it before resuming.');await receipt(row.hash,row);row.state='FINALIZED';if(row.label==='deployment')report.contract_address=row.contract_address;save();
 }
 const schema=await rpc('gen_getContractSchemaForCode',['0x'+Buffer.from(code).toString('hex')]);assert(schema.methods.verify_batch&&schema.methods.get_pool_result);
 const account=createAccount(),original=account.signTransaction;
 account.signTransaction=async tx=>{assert.equal(Number(tx.chainId),61999);assert.equal(BigInt(tx.value??0),0n);assert.equal(BigInt(tx.gasPrice??-1),0n);assert.equal(tx.to.toLowerCase(),studionet.consensusMainContract.address.toLowerCase());assert(lastEstimate&&Date.now()-lastEstimate.time<30000);assert.equal(sha(Buffer.from(tx.data)),lastEstimate.sha);assert.equal(BigInt(tx.gas),lastEstimate.gas);return original(tx);};
 const client=createClient({chain:studionet,endpoint,account});
 if(!report.contract_address){const tx=await send(client,'deployment',()=>client.deployContract({code,args:bundle.constructor_args,leaderOnly:false,consensusMaxRotations:3,value:0n}));report.contract_address=tx.to_address;save();}
 const address=report.contract_address;
 assert.equal(sha(Buffer.from(await rpc('gen_getContractCode',[address]),'base64')),plan.source_sha256);
 const summary=JSON.parse(await client.readContract({address,functionName:'get_summary'}));assert.equal(summary.root,bundle.merkle_root);assert.equal(summary.block_hash,bundle.context.block.hash);
 assert(summary.verified_pools>=Object.keys(report.pool_results).length&&summary.verified_pools<=950);
 if(report.error){report.resumptions ||= [];report.resumptions.push({at_utc:new Date().toISOString(),prior_error:report.error,broadcast_attempts:report.broadcast_attempts,onchain_verified_pools:summary.verified_pools});delete report.error;delete report.stopped_at_utc;save();}
 for(let i=0;i<bundle.batches.length;i++){
  const payload=bundle.batches[i],entries=JSON.parse(payload);
  if(report.verified_batches.includes(i)){
   const tx=report.transactions.find(t=>t.label==='batch_'+i);assert(tx?.state==='FINALIZED'&&Object.values(tx.votes).filter(v=>v==='agree').length>=3);
   for(const e of entries){const saved=report.pool_results[e.claim.index];assert(saved?.status==='VERIFIED'&&saved.claim_sha256===sha(Buffer.from(canonical(e.claim)))&&saved.block_hash===bundle.context.block.hash&&saved.transaction_hash===tx.hash);}
   continue;
  }
  if(!report.transactions.some(t=>t.label==='batch_'+i)){
   await send(client,'batch_'+i,()=>client.writeContract({address,functionName:'verify_batch',args:[payload],leaderOnly:false,consensusMaxRotations:3,value:0n}));
  }
  const states=await poolBatch(address,entries);
  for(let j=0;j<states.length;j++){
   assert.equal(states[j].status,'VERIFIED');assert.equal(states[j].claim_sha256,sha(Buffer.from(canonical(entries[j].claim))));assert.equal(states[j].block_hash,bundle.context.block.hash);
   report.pool_results[states[j].index]={...states[j],transaction_hash:report.transactions.find(t=>t.label==='batch_'+i).hash};
  }
  report.verified_batches=[...new Set([...report.verified_batches,i])];save();
 }
 report.summary=JSON.parse(await client.readContract({address,functionName:'get_summary'}));assert.equal(report.summary.verified_pools,950);report.passed=true;report.completed_at_utc=new Date().toISOString();save();
}catch(e){report.error=String(e.message).slice(0,600);report.stopped_at_utc=new Date().toISOString();save();console.error(report.error);process.exitCode=1;}
