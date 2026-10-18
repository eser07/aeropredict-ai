"use strict";
(() => {
  const $ = id => document.getElementById(id);
  const state = {
    pools: [],
    pairs: new Map(),
    page: 0,
    pageSize: 25,
    comparison: [],
    detailPool: null
  };


  const {finiteNumber,nonnegative,rewardMix,poolMetrics,researchScore,validateWeekly}=P9Math;
  const weeklyCache=new Map();
  let detailRequest=0;
  async function weeklyData(pool){
    if(!weeklyCache.has(pool.index)){
      const pending=fetch("/api/weekly?index="+encodeURIComponent(pool.index),{cache:"no-store"}).then(response=>{if(!response.ok)throw new Error("Haftalık API yanıt vermedi");return response.json();}).then(data=>validateWeekly(pool,data)).catch(error=>{weeklyCache.delete(pool.index);throw error;});
      weeklyCache.set(pool.index,pending);
    }
    return weeklyCache.get(pool.index);
  }

  function appendMix(area, data) {
    const t=data.trend;
    const mix=rewardMix(t?.fees_four_week_usd,t?.bribes_four_week_usd,data.usd_coverage_complete && t?.status === "available");
    const label=document.createElement("p");
    if (!mix) { label.textContent="FEES / BRIBES yüzdesi hesaplanamıyor: USD eksik veya toplam ödül sıfır."; area.append(label); return; }
    label.textContent="FEES %"+mix.fees.toFixed(2)+" · BRIBES %"+mix.bribes.toFixed(2);
    const bar=document.createElement("div"); bar.className="trend-mix-track"; bar.setAttribute("role","img"); bar.setAttribute("aria-label",label.textContent);
    for (const [kind,width] of [["fees",mix.fees],["bribes",mix.bribes]]) {const segment=document.createElement("span");segment.className="trend-"+kind;segment.style.width=width+"%";bar.append(segment);}
    const note=document.createElement("p"); note.className=mix.level === "context" ? "mini" : "warnline";
    note.textContent=mix.level === "high" ? "Yüksek tarihsel teşvik bağımlılığı: ödüllerin en az %80’i BRIBES kaynaklı." : mix.level === "attention" ? "Dikkat: tarihsel ödüllerin %50–80’i BRIBES kaynaklı." : "Tarihsel ödüllerde FEES payı daha yüksek.";
    area.append(label,bar,note);
  }

  function appendWeeks(area,data) {
    const chart=document.createElement("section");chart.className="weekly-chart";
    const heading=document.createElement("h4");heading.textContent="Dört tamamlanmış hafta";chart.append(heading);
    const known=data.weeks.map(w=>nonnegative(w.total_usd)).filter(v=>v!==null),max=Math.max(0,...known);
    for(const w of data.weeks){
      const row=document.createElement("div");row.className="chart-row";
      const date=document.createElement("span");date.textContent=w.week_start_utc.slice(0,10);
      const track=document.createElement("div");track.className="chart-track";track.setAttribute("role","img");
      track.setAttribute("aria-label",date.textContent+" FEES "+dollars(w.fees_usd)+", BRIBES "+dollars(w.bribes_usd));
      const value=document.createElement("span");value.className="num";value.textContent=dollars(w.total_usd);
      if(w.total_usd===null){track.classList.add("unknown");track.textContent="USD eksik";}
      else for(const [kind,amount] of [["fees",w.fees_usd],["bribes",w.bribes_usd]]){const bar=document.createElement("span");bar.className="trend-"+kind;bar.style.width=(max ? Number(amount)/max*100 : 0)+"%";track.append(bar);}
      row.append(date,track,value);chart.append(row);
    }
    const caption=document.createElement("p");caption.className="mini";caption.textContent="Turkuaz: FEES · Mavi: BRIBES. Grafik ölçeği havuza özeldir; havuzları USD tutarlarıyla karşılaştırın.";chart.append(caption);area.append(chart);
    const table=document.createElement("table");table.className="weekly-table";
    const head=table.createTHead().insertRow();for(const title of ["Hafta (UTC)","FEES","BRIBES","Toplam"]){const th=document.createElement("th");th.textContent=title;head.append(th);}
    const body=table.createTBody();for(const w of data.weeks){const row=body.insertRow();for(const value of [w.week_start_utc.slice(0,10),dollars(w.fees_usd),dollars(w.bribes_usd),dollars(w.total_usd)])cell(row,value);}
    const wrap=document.createElement("div");wrap.className="table-wrap";wrap.append(table);area.append(wrap);
    if(data.source_times){const times=document.createElement("p");times.className="mini source-times";
      times.textContent="FEES dosyası: "+(data.source_times.fees_file_collected_at_utc || "bilinmiyor")+" · Teşvik dosyası: "+(data.source_times.incentives_file_collected_at_utc || "bilinmiyor")+" · Fiyat kayıt aralığı: "+(data.source_times.earliest_quote_utc || "bilinmiyor")+" — "+(data.source_times.latest_quote_utc || "bilinmiyor")+". Bu zamanlar ayrı okumalardır.";area.append(times);}
  }

  async function showSavedVotes(pool,area,requestIndex){
    const section=document.createElement("section");section.className="weekly-chart";
    const title=document.createElement("h4");title.textContent="Önceki blokta kaydedilmiş oy ağırlığı";
    const note=document.createElement("p");note.className="mini";note.textContent="Kaydedilmiş oy gözlemi yükleniyor…";
    section.append(title,note);area.append(section);
    try{
      const response=await fetch("/api/votes?index="+pool.index,{cache:"no-store"});
      if(!response.ok)throw new Error();const data=await response.json();
      if(area.dataset.pool!==String(requestIndex))return;
      if(data.index!==pool.index||data.address?.toLowerCase()!==pool.address.toLowerCase()||typeof data.available!=="boolean"||data.synchronized_with_reward_epochs!==false||data.is_weekly_vote_history!==false)throw new Error();
      if(!data.available){note.textContent="Bu havuz için eski blok oy kaydı yok. Önceki kayıtlar 928/950 havuzu kapsıyor; eksik gözlem sıfır oy değildir.";return;}
      if(!/^\d+$/.test(data.vote_weight_raw)||!/^\d+$/.test(data.voter_total_weight_raw)||!/^0x[0-9a-fA-F]{64}$/.test(data.block_hash)||!Number.isSafeInteger(data.block_number)||data.block_number>=pool.inventory_snapshot_block)throw new Error();
      note.textContent="Havuz ağırlığı: "+tokenAmount(data.vote_weight_raw,18)+" veAERO · Aynı bloktaki Voter toplamı: "+tokenAmount(data.voter_total_weight_raw,18)+" veAERO · O bloktaki pay: "+(data.voter_share_percent_at_block===null?"Hesaplanamıyor":data.voter_share_percent_at_block+"%")+".";
      for(const text of ["Base blok: "+data.block_number+" · Blok zamanı (UTC): "+data.block_timestamp_utc,"Toplama zamanı (UTC): "+data.collected_at_utc,"Blok hash'i: "+data.block_hash,"Kaynak SHA256: "+data.source_snapshot_sha256,"Kayıt kapsamı: 928/950 havuz. Her havuz kendi okuma bloğuna bağlıdır; farklı havuzların gözlemleri tek zamanlı dağılım olarak toplanamaz. Bu tek geçmiş gözlem haftalık oy geçmişi değildir ve ödül haftalarıyla eş zamanlı değildir. Oy kaydı Research Score veya kişisel gelir hesabında kullanılmaz."]){const line=document.createElement("p");line.className="mini";line.textContent=text;section.append(line);}
    }catch{if(area.dataset.pool===String(requestIndex))note.textContent="Kaydedilmiş oy gözlemi doğrulanamadı; bu durum sıfır oy anlamına gelmez.";}
  }

  function jumpTo(id){$(id).scrollIntoView({behavior:window.matchMedia?.("(prefers-reduced-motion: reduce)").matches?"auto":"smooth",block:"start"});}
  function syncLocation(){
    const url=new URL(window.location.href);
    for(const [key,value] of [["q",$("search").value.trim()],["coverage",$("status").value==="all"?"":$("status").value],["source",$("source").value==="all"?"":$("source").value],["sort",$("sort").value==="index"?"":$("sort").value],["compare",state.comparison.join(",")]]){if(value)url.searchParams.set(key,value);else url.searchParams.delete(key);}
    history.replaceState(null,"",url);
  }
  function restoreLocation(){
    const params=new URLSearchParams(window.location.search);
    $("search").value=(params.get("q")||"").slice(0,200);
    for(const [id,key] of [["status","coverage"],["source","source"],["sort","sort"]]){const value=params.get(key);if([...$(id).options].some(o=>o.value===value))$(id).value=value;}
    state.comparison=[...new Set((params.get("compare")||"").split(",").filter(v=>/^\d+$/.test(v)).map(Number))].filter(id=>state.pools.some(p=>p.index===id)).slice(0,3);
  }
  function updateDetailNav(){
    const list=filteredPools(),pos=list.findIndex(p=>p.index===state.detailPool);
    $("detail-prev").disabled=pos<=0;$("detail-next").disabled=pos<0||pos>=list.length-1;
    $("detail-position").textContent=pos<0?"Seçili havuz filtre dışında":(pos+1)+" / "+list.length+" filtrelenmiş havuz";
  }

  function dollars(value) {
    if (value === null || value === undefined) return "USD bilinmiyor";
    const n = finiteNumber(value);
    if (n===null) return "USD bilinmiyor";
    if(n>0&&n<0.01)return "< $0.01";
    if(n<0&&n>-0.01)return "−(< $0.01)";
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: "USD",
      maximumFractionDigits: 2
    }).format(n);
  }

  function cell(row, value) {
    const td = document.createElement("td");
    td.dataset.label = ["Havuz","Token çifti","USD/hafta","Ödül kaynağı","Ödül haftası","Research Score"][row.children.length] || "İşlemler";
    td.textContent = String(value);
    row.append(td);
    return td;
  }

  function showError(message) {
    $("error").hidden = !message;
    $("retry-research").hidden=!message;
    $("error").textContent = message || "";
  }



  async function showComparisonWeeks(pool, card) {
    const note = document.createElement("p");
    note.textContent = "FEES / BRIBES geçmişi yükleniyor…";
    card.append(note);

    try {
      const data = await weeklyData(pool);

      if (!card.isConnected || !state.comparison.includes(pool.index)) return;

      appendMix(card, data);
      appendWeeks(card, data);
      const t = data.trend;
      if (!pool.usd_coverage_complete || t?.status !== "available") {
        note.textContent = "USD eksik: FEES / BRIBES toplamı bilinmiyor.";
        return;
      }

      note.textContent = "4 hafta FEES: " +
        dollars(t.fees_four_week_usd) +
        " | BRIBES: " + dollars(t.bribes_four_week_usd) +
        " | TOPLAM: " + dollars(t.total_four_week_usd);

      const change = document.createElement("p");
      change.textContent = "Son hafta: " + dollars(t.latest_week_usd) +
        " | Önceki: " + dollars(t.previous_week_usd) +
        " | Fark: " + dollars(t.latest_week_delta_usd) +
        " | Değişim: " +
        (t.latest_change_percent === null
          ? "Yüzde hesaplanamıyor"
          : t.latest_change_percent + "%");
      card.append(change);
    } catch {
      if (card.isConnected)
        note.textContent = "Haftalık karşılaştırma doğrulanamadı.";
    }
  }

  function updateComparison() {
    const ids = state.comparison;
    $("jump-compare").disabled=ids.length===0;
    $("jump-compare").textContent="Karşılaştırma ("+ids.length+"/3)";
    $("compare-panel").hidden = ids.length === 0;
    $("compare-count").textContent = ids.length + " / 3 havuz seçildi";
    const area = $("compare-items");
    area.replaceChildren();

    for (const id of ids) {
      const p = state.pools.find(x => x.index === id);
      if (!p) continue;

      const card = document.createElement("article");
      card.className="compare-card";
      const heading = document.createElement("h3");
      heading.textContent = "#" + p.index + " — " + pairLabel(p);

      const info = document.createElement("p");
      info.textContent = "Haftalık geçmiş ortalama: " +
        (p.usd_coverage_complete
          ? dollars(p.avg_pool_usd_per_week_at_collection_quote)
          : "USD eksik") +
        " | Ödül haftası: " + p.observed_any_reward_positive_weeks + "/4";

      const view=document.createElement("button");view.type="button";view.textContent="Havuz detayına git";view.addEventListener("click",()=>showDetail(p));
      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "Çıkar";
      remove.addEventListener("click", () => toggleComparison(p));

      card.append(heading, info, view, remove);
      area.append(card);
      showComparisonWeeks(p, card);
    }
  }

  function toggleComparison(p) {
    const index = state.comparison.indexOf(p.index);
    if (index >= 0) {
      state.comparison.splice(index, 1);
    } else if (state.comparison.length < 3) {
      state.comparison.push(p.index);
    }
    updateComparison();
    render();
    syncLocation();
  }

  function filteredPools() {
    const query = $("search").value.trim().toLowerCase();
    const status = $("status").value;

    const result = state.pools.filter(p => {
      const pair = state.pairs.get(p.index);
      const terms = [
        "#" + p.index, String(p.index),
        p.address, p.gauge_address,
        ...(p.token_rewards || []).flatMap(t => [t.symbol, t.address]),
        ...(pair ? Object.values(pair).filter(v => typeof v === "string") : [])
      ].filter(Boolean).join(" ").toLowerCase();

      if (query && (/^#?[0-9]+$/.test(query) ? p.index !== Number(query.replace("#", "")) : !terms.includes(query))) return false;
      if (status === "priced" && !p.usd_coverage_complete) return false;
      if (status === "missing" && p.usd_coverage_complete) return false;
      if (status === "positive" && p.no_observed_rewards) return false;
      if (status === "zero" && !p.no_observed_rewards) return false;
      const source=$("source").value,mix=poolMetrics(p)?.mix;
      if(source==="fees"&&(!mix||mix.bribes>=50))return false;
      if(source==="attention"&&(!mix||mix.bribes<50||mix.bribes>=80))return false;
      if(source==="high"&&(!mix||mix.bribes<80))return false;
      if(source==="unknown"&&mix)return false;
      return true;
    });

    const sort = $("sort").value;
    if (sort === "score") {
      result.sort((a,b)=>(researchScore(b)?.value ?? -1)-(researchScore(a)?.value ?? -1) || a.index-b.index);
    } else if (sort === "rewards") {
      result.sort((a, b) =>
        Number(b.avg_pool_usd_per_week_at_collection_quote ?? -1) -
        Number(a.avg_pool_usd_per_week_at_collection_quote ?? -1) ||
        a.index - b.index);
    } else if (sort === "weeks") {
      result.sort((a, b) =>
        b.observed_any_reward_positive_weeks -
        a.observed_any_reward_positive_weeks || a.index - b.index);
    } else {
      result.sort((a, b) => a.index - b.index);
    }
    return result;
  }

  function pairLabel(p) {
    const pair = state.pairs.get(p.index);
    if (!pair) return "Çift bilgisi doğrulanmadı";
    const a = pair.token0_symbol || pair.token0?.symbol;
    const b = pair.token1_symbol || pair.token1?.symbol;
    return a && b ? a + " / " + b : "Çift bilgisi eksik";
  }

  function render() {
    const pools = filteredPools();
    const pages = Math.max(1, Math.ceil(pools.length / state.pageSize));
    state.page = Math.min(state.page, pages - 1);

    $("rows").replaceChildren();
    const start = state.page * state.pageSize;

    for (const p of pools.slice(start, start + state.pageSize)) {
      const tr = document.createElement("tr");
      cell(tr, "#" + p.index);
      cell(tr, pairLabel(p));
      cell(tr, p.usd_coverage_complete
        ? dollars(p.avg_pool_usd_per_week_at_collection_quote)
        : "USD eksik");
      const mix=poolMetrics(p)?.mix;
      const composition=cell(tr,mix ? "FEES %"+mix.fees.toFixed(2)+" / BRIBES %"+mix.bribes.toFixed(2) : "Oran hesaplanamıyor");
      composition.className=mix?.level==="high"?"source-high":"source-mix";
      cell(tr, p.observed_any_reward_positive_weeks + "/4");

      cell(tr, researchScore(p)?.value ?? "Hesaplanamıyor");
      const td = document.createElement("td");
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = "Detay";
      button.addEventListener("click", () => showDetail(p));
      td.append(button);

      const compare = document.createElement("button");
      compare.type = "button";
      compare.textContent = state.comparison.includes(p.index)
        ? "Çıkar" : "Karşılaştır";
      compare.setAttribute("aria-pressed",String(state.comparison.includes(p.index)));
      compare.disabled = state.comparison.length >= 3 &&
        !state.comparison.includes(p.index);
      compare.addEventListener("click", () => toggleComparison(p));
      td.append(" ", compare);
      tr.append(td);
      $("rows").append(tr);
    }

    $("empty-results").hidden=pools.length!==0;
    $("count").textContent = pools.length + " / 950 havuz gösteriliyor";
    $("page-count").textContent = (state.page + 1) + " / " + pages;
    $("prev").disabled = state.page === 0;
    $("next").disabled = state.page >= pages - 1;
    if(state.detailPool!==null)updateDetailNav();
  }

  async function showDetail(p) {
    state.detailPool=p.index;
    $("detail").hidden = false;
    updateDetailNav();
    jumpTo("detail");
    $("detail-title").textContent = "Havuz #" + p.index;
    $("detail-intro").textContent = "";
    const area = $("detail-content");
    area.replaceChildren();

    function line(text) {
      const el = document.createElement("p");
      el.textContent = text;
      area.append(el);
    }

    line("Token çifti: " + pairLabel(p));
    line("Havuz adresi: " + p.address);
    line("Ödül gözlenen hafta: " +
      p.observed_any_reward_positive_weeks + "/4");
    line("Ortalama haftalık ödül: " +
      (p.usd_coverage_complete
        ? dollars(p.avg_pool_usd_per_week_at_collection_quote)
        : "USD fiyat verisi eksik"));

    line("Envanter oy ağırlığı: " + p.inventory_snapshot_votes + " · Base blok: " + p.inventory_snapshot_block + " (ödül haftalarıyla eş zamanlı değildir)");
    const pair=state.pairs.get(p.index);
    if(pair) for(const key of ["token0_address","token1_address"]) if(pair[key]) line(key+": "+pair[key]);
    for(const token of p.token_rewards || []) line(token.symbol+" · "+token.address+" · fiyat kaydı: "+(token.quote_timestamp_utc || "bilinmiyor"));
    const score=researchScore(p);
    line(score ? "Research Score: "+score.value+"/100 · Süreklilik: "+score.components.continuity.toFixed(1)+" · FEES: "+score.components.fees.toFixed(1)+" · Kaynak: "+score.components.composition.toFixed(1)+" · Dağılım: "+score.components.distribution.toFixed(1) : "Research Score hesaplanamıyor: eksik kanıt veya pozitif USD toplamı yok.");
    line("Kaynak: kaydedilmiş birleşik P9 araştırması ve havuza ait haftalık teşvik kaydı. Fiyatlar tarihsel hafta fiyatı değildir.");
    const loading=document.createElement("p");loading.textContent="Dört haftalık FEES / BRIBES geçmişi yükleniyor…";area.append(loading);
    const requestIndex=++detailRequest; area.dataset.pool=String(requestIndex);
    showSavedVotes(p,area,requestIndex);

    try {
      const data = await weeklyData(p);

      if(area.dataset.pool !== String(requestIndex)) return;
      loading.remove(); appendMix(area,data); appendWeeks(area,data);
    } catch (error) {
      if(area.dataset.pool === String(requestIndex)) {loading.remove();line("Haftalık ayrıntı şu anda doğrulanamadı.");}
    }
  }

  for (const id of ["search", "status", "source", "sort"]) {
    $(id).addEventListener("input", () => {
      state.page = 0;
      render();
      syncLocation();
    });
  }

  $("prev").addEventListener("click", () => {
    if (state.page > 0) {
      state.page--;
      render();
    }
  });

  $("next").addEventListener("click", () => {
    state.page++;
    render();
  });

  $("close-detail").addEventListener("click", () => {
    detailRequest++;
    $("detail-content").dataset.pool=String(detailRequest);
    $("detail").hidden = true;
    state.detailPool = null;
  });

  async function loadResearch() {
    try {
      const response = await fetch("/api/research", {cache: "no-store"});
      if (!response.ok) throw new Error("API: " + response.status);

      const doc = await response.json();
      if (doc.chain_id !== 8453 ||
          doc.inventory_pool_count !== 950 ||
          doc.audited_pool_count !== 950 ||
          doc.audited_usd_complete_pool_count !== 904 ||
          doc.audited_usd_incomplete_pool_count !== 46 ||
          doc.collection_epoch_utc !== "2026-10-15T00:00:00+00:00" ||
          !Array.isArray(doc.pools) ||
          doc.pools.length !== 950 ||
          new Set(doc.pools.map(p => p.index)).size !== 950) {
        throw new Error("950 havuzluk P9 veri doğrulaması başarısız");
      }

      const pairResponse = await fetch("/api/pairs", {cache: "no-store"});
      if (!pairResponse.ok) throw new Error("Token çiftleri yüklenemedi");
      const pairDoc = await pairResponse.json();

      if (pairDoc.chain_id !== 8453 ||
          !Array.isArray(pairDoc.pools) || pairDoc.pools.length !== 950) {
        throw new Error("950 havuzluk token çifti verisi geçersiz");
      }

      const pairMap = new Map(pairDoc.pools.map(p => [p.index, p]));
      if (pairMap.size !== 950 ||
          doc.pools.some(p =>
            pairMap.get(p.index)?.pool_address?.toLowerCase() !==
            p.address.toLowerCase())) {
        throw new Error("Havuz adresleri eşleşmiyor");
      }

      state.pairs = pairMap;
      state.pools = doc.pools;
      restoreLocation();
      const quotes=state.pools.flatMap(p=>(p.token_rewards||[]).map(t=>t.quote_timestamp_utc)).filter(v=>typeof v==="string").sort();
      $("quote-window").textContent=quotes.length ? "Fiyat kayıtları (UTC): "+quotes[0]+" — "+quotes.at(-1) : "Fiyat kayıt zamanları eksik";
      updateComparison();
      $("stat-pools").textContent = "950";
      $("stat-priced").textContent = "904";
      $("stat-missing").textContent = "46";
      $("stat-zero").textContent = String(
        doc.no_observed_rewards_pool_count
      );
      showError("");
      render();
    } catch (error) {
      showError("Araştırma yüklenemedi: " + error.message);
    }
  }

  $("clear-compare").addEventListener("click", () => {
    state.comparison = [];
    updateComparison();
    render();
    syncLocation();
  });

  $("reset-filters").addEventListener("click",()=>{ $("search").value="";$("status").value="all";$("sort").value="index";$("source").value="all";state.page=0;render();syncLocation(); });
  $("retry-research").addEventListener("click",()=>loadResearch());
  $("jump-compare").addEventListener("click",()=>jumpTo("compare-panel"));
  $("page-size").addEventListener("change",()=>{state.pageSize=Number($("page-size").value);state.page=0;render();});
  for(const [id,delta] of [["detail-prev",-1],["detail-next",1]])$(id).addEventListener("click",()=>{const list=filteredPools();const pos=list.findIndex(p=>p.index===state.detailPool);if(list[pos+delta])showDetail(list[pos+delta]);});
  function tokenAmount(raw,decimals) {
    if(raw === null || raw === undefined) return "Henüz yok";
    if(!/^[0-9]+$/.test(raw) || !Number.isInteger(decimals) || decimals<0 || decimals>36) return raw+" ham birim";
    if(decimals===0) return raw;
    const value=raw.padStart(decimals+1,"0");
    const fraction=value.slice(-decimals).replace(/0+$/,"");
    return value.slice(0,-decimals)+(fraction ? "."+fraction : "");
  }
  function pilotStatusLabel(forecast) {
    if(forecast.status==="pending") return "Dönem bekleniyor";
    if(forecast.status==="locally_evaluated") return forecast.forecast_matched ? "Yerel gözlem · tolerans içinde" : "Yerel gözlem · tolerans dışında";
    if(forecast.status==="insufficient_data") return "Veri yetersiz";
    return "Doğrulanamadı";
  }
  $("load-pilot").addEventListener("click", async()=>{
    const area=$("pilot-content"); area.textContent="Yükleniyor…";
    try {
      const response=await fetch("/api/pilot",{cache:"no-store"});if(!response.ok)throw new Error();const data=await response.json();
      if(data.schema_version!==2 || data.forecasts?.length!==5)throw new Error();
      area.replaceChildren();
      const test=document.createElement("p");test.className="notice";
      test.textContent=data.test_validation?.available && data.test_validation.passed ? data.test_validation.tests+" yerel test geçti · Direct Mode · RPC yanıtları kontrollü · Ağ mutabakatı yok" : "Güncel kod için doğrulanmış yerel test raporu bulunamadı.";
      area.append(test);
      const archive=document.createElement("p");archive.className="mini";
      archive.textContent="Yerel kontrol kaydı: "+(data.collection_summary?.scanned_snapshots || 0)+" · Geçersiz kayıt: "+(data.collection_summary?.invalid_snapshots || 0)+". Yerel RPC gözlemi bağımsız GenLayer mutabakatı değildir.";
      area.append(archive);
      const table=document.createElement("table");table.className="weekly-table";const head=table.createTHead().insertRow();
      for(const title of ["Havuz / token","Hedef hafta (UTC)","Tahmin · FEES","Gerçekleşen","Durum"]){const th=document.createElement("th");th.textContent=title;head.append(th);}
      const body=table.createTBody();
      for(const forecast of data.forecasts){
        const c=forecast.commitment;const row=body.insertRow();
        for(const value of ["#"+c.pool_index+" · "+c.token_symbol,c.target_start_utc.slice(0,10)+" → "+c.target_end_utc.slice(0,10),tokenAmount(c.predicted_raw,c.token_decimals)+" "+c.token_symbol,tokenAmount(forecast.actual_raw,c.token_decimals),pilotStatusLabel(forecast)])cell(row,value);
        const details=document.createElement("details");const summary=document.createElement("summary");summary.textContent="#"+c.pool_index+" · Kayıt ve kaynaklar";details.append(summary);
        for(const value of ["FEES sözleşmesi: "+c.fees_contract,"Token: "+c.token_address,"Ham tahmin: "+c.predicted_raw,"Tolerans: %"+c.tolerance_percent,"Kayıt: "+c.created_at_utc,"SHA256: "+forecast.commitment_sha256,"Son kontrol: "+(forecast.collection_attempt?.collected_at_utc || "Henüz yapılmadı"),"Kontrol durumu: "+(forecast.collection_attempt?.collection_status === "pending" ? "Dönem tamamlanmadı; zincir okuması yapılmadı" : forecast.collection_attempt?.collection_status === "collected_local" ? "Yerel RPC gözlemi alındı" : forecast.collection_attempt ? "Kanıt alınamadı" : "Kayıt yok"),"Kanıt bloğu: "+(forecast.evidence_block_number ?? "Henüz yok")]){const line=document.createElement("p");line.className="mono";line.textContent=value;details.append(line);}
        area.append(details);
      }
      const wrap=document.createElement("div");wrap.className="table-wrap";wrap.append(table);area.prepend(wrap);
    }catch{area.textContent="Pilot kaydı veya kaynak bütünlüğü doğrulanamadı.";}
  });
  loadResearch();
})();
