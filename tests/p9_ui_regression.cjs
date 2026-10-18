const fs=require('fs'),vm=require('vm'),assert=require('assert');
const root=require('path').resolve(__dirname,'..');
const nodes=new Map(); const get=id=>{if(!nodes.has(id))nodes.set(id,{value:id==='status'?'all':id==='sort'?'index':'',addEventListener(){},replaceChildren(){},append(){}});return nodes.get(id);};
let source=fs.readFileSync(root+'/research/p9_unified/research.js','utf8');
source=source.replace('  loadResearch();','  globalThis.testAPI={rewardMix,researchScore,filteredPools,state,tokenAmount,pilotStatusLabel};');
const ctx={document:{getElementById:get},Intl,console};vm.createContext(ctx);vm.runInContext(source,ctx);
const a=ctx.testAPI;
assert.equal(a.rewardMix(20,80,true).level,'high');assert.equal(a.rewardMix(50,50,true).level,'attention');
for(const args of [[0,0,true],[null,10,true],[10,20,false],[-1,10,true],['NaN',10,true]])assert.equal(a.rewardMix(...args),null);
const doc=JSON.parse(fs.readFileSync(root+'/data/pool_collection_batches_base/p9_unified_research/block_52731839/registration_25/research_all_950_one_epoch.json','utf8'));
a.state.pools=doc.pools;
for(const query of ['64','#64']){get('search').value=query;const rows=a.filteredPools();assert.equal(rows.length,1);assert.equal(rows[0].index,64);}
get('search').value='';get('status').value='missing';assert.equal(a.filteredPools().length,46);
get('status').value='priced';assert.equal(a.filteredPools().length,904);
let scored=0;for(const p of doc.pools){const score=a.researchScore(p);if(score){assert(score.value>=0&&score.value<=100);scored++;}if(!p.usd_coverage_complete||p.no_observed_rewards)assert.equal(score,null);}
console.log('PASS: ratio thresholds, missing/zero data, exact search, filters, 950 score bounds; scored',scored);

assert.equal(a.tokenAmount("1",18),"0.000000000000000001");
assert.equal(a.tokenAmount("1000000",6),"1");
assert.equal(a.tokenAmount(null,18),"Henüz yok");

assert.equal(a.pilotStatusLabel({status:"pending"}),"Dönem bekleniyor");
assert.equal(a.pilotStatusLabel({status:"locally_evaluated",forecast_matched:true}),"Yerel gözlem · tolerans içinde");
assert.equal(a.pilotStatusLabel({status:"locally_evaluated",forecast_matched:false}),"Yerel gözlem · tolerans dışında");
assert.equal(a.pilotStatusLabel({status:"unverifiable"}),"Doğrulanamadı");
