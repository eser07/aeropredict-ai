"use strict";
(function(root,factory){const api=factory();if(typeof module==="object"&&module.exports)module.exports=api;else root.P9Math=api;})(globalThis,()=>{
  const numeric=/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i;
  function finiteNumber(value){
    if(typeof value!=="number" && (typeof value!=="string" || !numeric.test(value)))return null;
    const number=Number(value);return Number.isFinite(number)?number:null;
  }
  function nonnegative(value){const n=finiteNumber(value);return n!==null&&n>=0?n:null;}
  function close(a,b){return a===b || Math.abs(a-b)<=Math.max(Math.abs(a),Math.abs(b))*1e-9;}
  function rewardMix(fees,bribes,complete){
    if(complete!==true)return null;
    const f=nonnegative(fees),b=nonnegative(bribes);
    if(f===null||b===null||!Number.isFinite(f+b)||f+b<=0)return null;
    const share=100*(b/(f+b));
    return {fees:100-share,bribes:share,level:share>=80?"high":share>=50?"attention":"context"};
  }
  function poolMetrics(p){
    if(p.usd_coverage_complete!==true||p.truncated_reward_registry!==false||!Array.isArray(p.missing_or_stale_components)||p.missing_or_stale_components.length)return null;
    const weeks=p.weekly_pool_usd_at_collection_quote;
    if(!Array.isArray(weeks)||weeks.length!==4)return null;
    const values=weeks.map(nonnegative);if(values.some(x=>x===null))return null;
    const tokens=p.token_rewards;if(!Array.isArray(tokens))return null;
    let fees=0,bribes=0;
    for(const token of tokens){const mean=nonnegative(token.mean_usd_at_collection_quote);if(mean===null||!["FEES","BRIBES"].includes(token.type))return null;if(token.type==="FEES")fees+=mean*4;else bribes+=mean*4;}
    const total=values.reduce((a,b)=>a+b,0),average=nonnegative(p.avg_pool_usd_per_week_at_collection_quote);
    if(![fees,bribes,total].every(Number.isFinite)||average===null||!close(fees+bribes,total)||!close(average*4,total))return null;
    return {fees,bribes,total,weeks:values,mix:rewardMix(fees,bribes,true)};
  }
  function researchScore(p){
    const metrics=poolMetrics(p);if(!metrics||metrics.total<=0)return null;
    const feesWeeks=p.observed_fees_positive_weeks,positive=p.observed_any_reward_positive_weeks;
    if(![feesWeeks,positive].every(n=>Number.isInteger(n)&&n>=0&&n<=4)||feesWeeks>positive||positive!==metrics.weeks.filter(n=>n>0).length)return null;
    const components={continuity:25*positive/4,fees:25*feesWeeks/4,composition:25*metrics.mix.fees/100,distribution:25*(1-Math.max(...metrics.weeks)/metrics.total)/0.75};
    const value=Object.values(components).reduce((a,b)=>a+b,0);
    return {value:Math.round(Math.max(0,Math.min(100,value))),components};
  }
  function validateWeekly(pool,data){
    if(!data||data.index!==pool.index||typeof data.address!=="string"||data.address.toLowerCase()!==pool.address.toLowerCase()||data.collection_epoch_utc!==pool.collection_epoch_utc||data.usd_coverage_complete!==pool.usd_coverage_complete||!Array.isArray(data.weeks)||data.weeks.length!==4)throw new Error("Haftalık veri kimliği eşleşmiyor");
    const epoch=Date.parse(pool.collection_epoch_utc);let fees=0,bribes=0,total=0;
    data.weeks.forEach((w,i)=>{
      if(Date.parse(w.week_start_utc)!==epoch-(4-i)*604800000)throw new Error("Haftalık dönem eşleşmiyor");
      const f=nonnegative(w.fees_usd),b=nonnegative(w.bribes_usd),t=nonnegative(w.total_usd);
      if((w.fees_usd!==null&&f===null)||(w.bribes_usd!==null&&b===null)||(w.total_usd!==null&&t===null))throw new Error("Geçersiz haftalık USD");
      if(f!==null&&b!==null){if(t===null||!close(f+b,t))throw new Error("Haftalık toplam eşleşmiyor");}
      else if(t!==null)throw new Error("Eksik fiyat tam toplam olarak sunulamaz");
      if(pool.usd_coverage_complete&&(f===null||b===null||t===null))throw new Error("Tam USD kapsamı eksik");
      fees+=f||0;bribes+=b||0;total+=t||0;
    });
    if(pool.usd_coverage_complete){const t=data.trend;if(t?.status!=="available"||!close(nonnegative(t.fees_four_week_usd)??NaN,fees)||!close(nonnegative(t.bribes_four_week_usd)??NaN,bribes)||!close(nonnegative(t.total_four_week_usd)??NaN,total))throw new Error("Dört haftalık toplam eşleşmiyor");}
    return data;
  }
  return {finiteNumber,nonnegative,rewardMix,poolMetrics,researchScore,validateWeekly};
});
