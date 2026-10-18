"use strict";
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
const root=path.resolve(__dirname,'..');
const math=require(root+'/research/p9_unified/research-math.js');
const doc=JSON.parse(fs.readFileSync(root+'/data/pool_collection_batches_base/p9_unified_research/block_52731839/registration_25/research_all_950_one_epoch.json','utf8'));
const fixture=()=>({usd_coverage_complete:true,truncated_reward_registry:false,missing_or_stale_components:[],weekly_pool_usd_at_collection_quote:['1','1','1','1'],avg_pool_usd_per_week_at_collection_quote:'1',observed_fees_positive_weeks:4,observed_any_reward_positive_weeks:4,token_rewards:[{type:'FEES',mean_usd_at_collection_quote:'1'}]});

test('numeric input does not coerce unknowns into zero',()=>{
 for(const input of [null,undefined,'',' ',true,false,[],{},'NaN','Infinity'])assert.equal(math.finiteNumber(input),null);
 for(const input of ['0',0,'1.25','1e-12'])assert.notEqual(math.nonnegative(input),null);
 assert.equal(math.nonnegative('-1'),null);
});
test('dependency thresholds use the unrounded ratio',()=>{
 assert.equal(math.rewardMix('20','80',true).level,'high');
 assert.equal(math.rewardMix('20.001','79.999',true).level,'attention');
 assert.equal(math.rewardMix('50','50',true).level,'attention');
 assert.equal(math.rewardMix('50.001','49.999',true).level,'context');
});
test('missing or zero totals have no fabricated shares',()=>{
 for(const values of [['',1,true],[null,1,true],[0,0,true],[1,2,false],[1,2,'true'],[-1,1,true]])assert.equal(math.rewardMix(...values),null);
});
test('uniform positive fees attain the documented 100 points',()=>assert.equal(math.researchScore(fixture()).value,100));
test('one-week concentration lowers the documented score',()=>{
 const p=fixture();p.weekly_pool_usd_at_collection_quote=['4','0','0','0'];p.observed_fees_positive_weeks=1;p.observed_any_reward_positive_weeks=1;
 assert.equal(math.researchScore(p).value,38);
});
test('uniform bribes are distinct from fees',()=>{
 const p=fixture();p.token_rewards=[{type:'BRIBES',mean_usd_at_collection_quote:'1'}];p.observed_fees_positive_weeks=0;
 assert.equal(math.researchScore(p).value,50);
});
test('incomplete quotes and truncated registry have no score',()=>{
 for(const change of [{usd_coverage_complete:false},{truncated_reward_registry:true},{missing_or_stale_components:['missing_quote']}])assert.equal(math.researchScore({...fixture(),...change}),null);
});
test('malformed reward totals and counts have no score',()=>{
 for(const change of [{weekly_pool_usd_at_collection_quote:[null,1,1,1]},{avg_pool_usd_per_week_at_collection_quote:''},{observed_fees_positive_weeks:5},{observed_any_reward_positive_weeks:0},{token_rewards:[{type:'FEES',mean_usd_at_collection_quote:'-1'}]},{token_rewards:[{type:'UNKNOWN',mean_usd_at_collection_quote:'1'}]}])assert.equal(math.researchScore({...fixture(),...change}),null);
});
test('zero observed reward is not assigned a low confidence score',()=>{
 const p=fixture();p.weekly_pool_usd_at_collection_quote=['0','0','0','0'];p.avg_pool_usd_per_week_at_collection_quote='0';p.token_rewards=[];assert.equal(math.researchScore(p),null);
});
test('950 saved pools retain 655 eligible scores and explicit missing states',()=>{
 let count=0;for(const p of doc.pools){const score=math.researchScore(p);if(score){count++;assert(score.value>=0&&score.value<=100);}if(!p.usd_coverage_complete||p.no_observed_rewards)assert.equal(score,null);}assert.equal(count,655);
});
test('pool 64 and 35 preserve source dependence and score',()=>{
 const p64=doc.pools.find(p=>p.index===64),p35=doc.pools.find(p=>p.index===35);
 assert.equal(math.poolMetrics(p64).mix.bribes.toFixed(2),'0.06');assert.equal(math.poolMetrics(p35).mix.bribes.toFixed(2),'94.61');
 assert.equal(math.researchScore(p64).value,97);assert.equal(math.researchScore(p35).value,75);
});
function weekly(){return {index:1,address:'0x'+'a'.repeat(40),collection_epoch_utc:'2026-10-15T00:00:00+00:00',usd_coverage_complete:true,weeks:['2026-09-17','2026-09-24','2026-10-01','2026-10-08'].map(date=>({week_start_utc:date+'T00:00:00+00:00',fees_usd:'1',bribes_usd:'1',total_usd:'2'})),trend:{status:'available',fees_four_week_usd:'4',bribes_four_week_usd:'4',total_four_week_usd:'8'}};}
test('weekly identity and totals reconcile',()=>{const d=weekly();assert.equal(math.validateWeekly(d,d),d);});
test('wrong pool, epoch and duplicate week are rejected',()=>{
 const p=weekly();for(const change of [d=>d.index++,d=>d.address='0x'+'b'.repeat(40),d=>d.weeks[1]=d.weeks[0],d=>d.collection_epoch_utc='2026-10-08T00:00:00+00:00']){const d=weekly();change(d);assert.throws(()=>math.validateWeekly(p,d));}
});
test('blank totals and inaccurate trend fields are rejected',()=>{
 const p=weekly();for(const change of [d=>d.weeks[0].fees_usd='',d=>d.weeks[0].total_usd='3',d=>d.trend.bribes_four_week_usd='999']){const d=weekly();change(d);assert.throws(()=>math.validateWeekly(p,d));}
});
test('partial-price weeks retain null total and unavailable trend',()=>{
 const p=weekly();p.usd_coverage_complete=false;const d=weekly();d.usd_coverage_complete=false;d.weeks[0].fees_usd=null;d.weeks[0].total_usd=null;d.trend={status:'unavailable_incomplete_usd'};assert.equal(math.validateWeekly(p,d),d);d.weeks[0].total_usd='1';assert.throws(()=>math.validateWeekly(p,d));
});
