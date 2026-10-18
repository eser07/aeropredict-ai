const fs=require('fs'),vm=require('vm'),assert=require('assert');
const root=require('path').resolve(__dirname,'..');
const nodes=new Map(); const get=id=>{if(!nodes.has(id))nodes.set(id,{value:id==='status'?'all':id==='sort'?'index':'',addEventListener(){},replaceChildren(){},append(){}});return nodes.get(id);};
let source=fs.readFileSync(root+'/research/p9_unified/research.js','utf8');
source=source.replace('  loadResearch();','  globalThis.testAPI={rewardMix,researchScore,filteredPools,state,tokenAmount,pilotStatusLabel,dollars,restoreLocation,pairLabel};');
const ctx={P9Math:require(root+'/research/p9_unified/research-math.js'),document:{getElementById:get},Intl,console,URLSearchParams,window:{location:{search:""}}};vm.createContext(ctx);vm.runInContext(source,ctx);
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

get('search').value='';get('status').value='all';
const partitions=new Set();let partitionCount=0;
for(const source of ['fees','attention','high','unknown']){
  get('source').value=source;const rows=a.filteredPools();
  for(const pool of rows){assert(!partitions.has(pool.index));partitions.add(pool.index);}
  partitionCount+=rows.length;
  if(source==='fees')assert(rows.some(p=>p.index===64));
  if(source==='high')assert(rows.some(p=>p.index===35));
}
assert.equal(partitionCount,950);get('source').value='all';
get('search').value='zzzz-no-pool';assert.equal(a.filteredPools().length,0);
assert.equal(a.dollars(null),'USD bilinmiyor');
assert.equal(a.dollars('0.000001'),'< $0.01');assert.equal(a.dollars('0'),'$0.00');
for(const [id,values] of [['status',['all','missing']],['source',['all','high']],['sort',['index','score']]])get(id).options=values.map(value=>({value}));
ctx.window.location.search='?q=%2364&coverage=missing&source=high&sort=score&compare=64,35,64,0,1,999999';
a.restoreLocation();assert.equal(get('search').value,'#64');assert.equal(get('source').value,'high');
assert.equal(get('status').value,'missing');assert.equal(get('sort').value,'score');
assert.deepEqual(Array.from(a.state.comparison),[64,35,0]);
console.log('PASS: all source filters partition 950 pools, subcent display, empty search, URL restore and comparison limit');

// A special contract is not a fabricated token pair; ordinary and unknown pairs stay distinct.
get('search').value='';get('status').value='all';get('source').value='all';get('sort').value='index';
const sink=doc.pools.find(p=>p.index===1130),normal=doc.pools.find(p=>p.index===64);
a.state.pairs.set(1130,{index:1130,contract_name:'SinkPool',token0_symbol:null,token1_symbol:null,contract_classification:{kind:'emission_sink_placeholder'}});
a.state.pairs.set(64,{index:64,token0_symbol:'AERO',token1_symbol:'USDC'});
assert.equal(a.pairLabel(sink),'SinkPool · token çifti yok');assert.equal(a.pairLabel(normal),'AERO / USDC');
get('search').value='SinkPool';assert.deepEqual(Array.from(a.filteredPools(),p=>p.index),[1130]);
a.state.pairs.set(1130,{index:1130,token0_symbol:null,token1_symbol:null});assert.equal(a.pairLabel(sink),'Çift bilgisi eksik');
console.log('PASS: SinkPool classification, exact special-contract search, ordinary pairs and unknown fallback');
