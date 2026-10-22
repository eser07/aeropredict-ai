// Latest-week allocation on a 1% grid; each selected pool receives 10–25%.
export const CAP=25;
export const MIN=10;
export function baseline(values,model){
 if(model==='previous_week')return Array.isArray(values)&&values.length===4&&values[3]!==null&&values[3]!==''&&Number.isFinite(Number(values[3]))&&Number(values[3])>=0?Number(values[3]):null;
 if(!Array.isArray(values)||values.length!==4||values.some(x=>x===null||x===''||!Number.isFinite(Number(x))||Number(x)<0))return null;
 const xs=values.map(Number);
 if(model==='previous_week')return xs[3];
 if(model==='mean_4w')return xs.reduce((a,b)=>a+b,0)/4;
 if(model==='median_4w'){const s=xs.slice().sort((a,b)=>a-b);return (s[1]+s[2])/2;}
 throw new Error('Bilinmeyen model');
}
export function candidates(pools,model='previous_week',source='both',live=false){
 if(!['both','fees','bribes'].includes(source))throw new Error('Bilinmeyen ödül kaynağı');
 const reasons={missing_usd:0,zero_votes:0,zero_reward:0,not_active:0};const rows=[];
 for(const p of pools){
  if(live&&!p.alive_at_snapshot){reasons.not_active++;continue;}
  const f=source==='bribes'?0:baseline(p.fees,model),b=source==='fees'?0:baseline(p.bribes,model);
  if(f===null||b===null){reasons.missing_usd++;continue;}
  const w=Number(BigInt(p.votes_raw))/1e18;
  if(!Number.isFinite(w)||w<=0){reasons.zero_votes++;continue;}
  const fees=f,bribes=b;
  if(fees+bribes<=0){reasons.zero_reward++;continue;}
  rows.push({...p,votes:w,feesUsd:fees,bribesUsd:bribes,reward:fees+bribes});
 }
 return {rows,reasons};
}
export function solve(rows,power){
 if(!Number.isFinite(power)||power<=0||power>1e9)throw new Error('Oy gücü 0 ile 1 milyar arasında olmalı.');
 if(rows.length<4)throw new Error('%25 sınırı için en az dört uygun havuz gerekir.');
 if(new Set(rows.map(x=>x.index)).size!==rows.length)throw new Error('Yinelenen havuz kimliği');
 if(rows.some(p=>![p.votes,p.feesUsd,p.bribesUsd,p.reward].every(Number.isFinite)||p.votes<=0||p.feesUsd<0||p.bribesUsd<0||p.reward<=0||Math.abs(p.reward-p.feesUsd-p.bribesUsd)>1e-7*Math.max(1,p.reward)))throw new Error('Geçersiz aday');
 const unit=power/100,choices=[];let dp=new Float64Array(101);dp.fill(-Infinity);dp[0]=0;
 // Exact multiple-choice knapsack on the 1% grid: zero or [10%,25%].
 // Starting a pool below its minimum is impossible, rather than rounded later.
 for(const p of rows){
  const next=new Float64Array(101);next.fill(-Infinity);const chosen=new Int8Array(101);chosen.fill(-1);
  const value=Array.from({length:CAP+1},(_,k)=>p.reward*(k*unit)/(p.votes+k*unit));
  for(let used=0;used<=100;used++)if(Number.isFinite(dp[used])){
   if(dp[used]>next[used]){next[used]=dp[used];chosen[used]=0;}
   for(let k=MIN;k<=CAP&&used+k<=100;k++)if(dp[used]+value[k]>next[used+k]){next[used+k]=dp[used]+value[k];chosen[used+k]=k;}
  }
  choices.push(chosen);dp=next;
 }
 if(!Number.isFinite(dp[100]))throw new Error('%10–25 sınırlarında tam dağılım oluşturulamadı.');
 const result=[];let remaining=100;
 for(let i=rows.length-1;i>=0;i--){const k=choices[i][remaining];if(k<0)throw new Error('Dağılım izi geçersiz');if(k){result.push({...rows[i],slices:k});remaining-=k;}}
 if(remaining!==0)throw new Error('Dağılım toplamı eşleşmedi');
 return result.map(p=>{const allocated=p.slices*unit,share=allocated/(p.votes+allocated);return {...p,allocated,feesResult:p.feesUsd*share,bribesResult:p.bribesUsd*share,total:p.reward*share};}).sort((a,b)=>b.total-a.total||a.index-b.index);
}
