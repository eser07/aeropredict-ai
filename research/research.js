"use strict";
(() => {
  const $ = id => document.getElementById(id);
  const doc = { pools: [], meta: null, filtered: [], page: 0, compared: [], compareError: "", pairs: new Map(), view: "beginner" };
  const EPOCH8 = "2026-10-08T00:00:00+00:00";
  const EPOCH15 = "2026-10-15T00:00:00+00:00";
  const make = (tag, cls, val) => {
    const el = document.createElement(tag);
    if (cls) el.className = cls;
    if (val !== undefined && val !== null) el.textContent = String(val);
    return el;
  };
  const cell = (tr, val, cls) => {
    const td = make("td", cls || "", val);
    tr.appendChild(td);
    return td;
  };
  const money = value => {
    if (value === null || value === undefined || value === "") return "Unknown";
    const n = Number(value);
    if (!Number.isFinite(n)) return "Unknown";
    if (n === 0) return "$0.00";
    if (n > 0 && n < 0.01) return "< $0.01";
    return new Intl.NumberFormat("en-US", {
      style: "currency", currency: "USD", maximumFractionDigits: 2,
    }).format(n);
  };
  const plain = value => {
    if (value === null || value === undefined || value === "") return "Unknown";
    const n = Number(value);
    if (!Number.isFinite(n)) return String(value);
    if (n === 0) return "0";
    if (Math.abs(n) < 0.0001) return String(value);
    return new Intl.NumberFormat("en-US", {maximumSignificantDigits: 9}).format(n);
  };
  const shortAddr = text => typeof text === "string"
    ? text.slice(0, 9) + "…" + text.slice(-6) : "Unavailable";
  const epochName = e => e === EPOCH8 ? "Oct 8, 2026" :
    e === EPOCH15 ? "Oct 15, 2026" : "Unknown epoch";
  const numeric = value => {
    if (value === null || value === undefined || value === "") return null;
    const n = Number(value);
    return Number.isFinite(n) && n >= 0 ? n : null;
  };
  // Display-only, explicitly arbitrary research-size thresholds. They do NOT
  // verify voting eligibility, liquidity, tradability or predictable income.
  const MIN_RESEARCH_WEEKLY_USD = 10;
  const MIN_OLD_SNAPSHOT_VOTES = 100;
  function sizeCautions(p) {
    const warnings = [];
    const votes = numeric(p.inventory_snapshot_votes);
    const usd = numeric(p.avg_pool_usd_per_week_at_collection_quote);
    if (votes === null || votes < MIN_OLD_SNAPSHOT_VOTES)
      warnings.push("Tiny / unknown old voting denominator (< 100 veAERO)");
    if (p.usd_coverage_complete && (usd === null || usd < MIN_RESEARCH_WEEKLY_USD))
      warnings.push("Small saved-price reward total (< $10/week)");
    return warnings;
  }
  // Historical RESEARCH-PRIORITY heuristic, not a yield, safety or ROI forecast.
  // Missing USD quotes never receive a numeric score; old votes are unsynchronized.
  function researchScore(p) {
    if (!p.usd_coverage_complete ||
        numeric(p.avg_pool_usd_per_week_at_collection_quote) === null)
      return null;
    const usd = numeric(p.avg_pool_usd_per_week_at_collection_quote);
    const votes = numeric(p.inventory_snapshot_votes);
    const weeks = Math.max(0, Math.min(4, Number(p.observed_any_reward_positive_weeks) || 0));
    const regularity = 30 * weeks / 4;
    const size = 25 * Math.max(0, Math.min(1, Math.log10(Math.max(usd, 10) / 10) / 2));
    const coverage = 25;
    const voteContext = votes === null ? 0 :
      20 * Math.max(0, Math.min(1, Math.log10(Math.max(votes, 100) / 100) / 2));
    const raw = Math.round(regularity + size + coverage + voteContext);
    // Graded evidence discount avoids giving every tiny pool exactly 39/100.
    // These cutoffs are transparent UI heuristics, NOT statistical confidence.
    if (sizeCautions(p).length) {
      const rewardAdequacy = Math.min(1, usd / MIN_RESEARCH_WEEKLY_USD);
      const voteAdequacy = votes === null ? 0 :
        Math.min(1, votes / MIN_OLD_SNAPSHOT_VOTES);
      const evidenceFactor = 0.25 + 0.75 * Math.min(rewardAdequacy, voteAdequacy);
      return Math.min(39, Math.round(raw * evidenceFactor));
    }
    return raw;
  }
  function drawLeaders() {
    const epoch = $("epoch").value;
    const panel = $("leaders-panel");
    panel.hidden = epoch === "both";
    if (panel.hidden) return;
    const leaders = doc.pools.filter(p =>
      p.collection_epoch_utc === epoch && researchScore(p) !== null)
      .sort((a, b) => researchScore(b) - researchScore(a) ||
        Number(b.avg_pool_usd_per_week_at_collection_quote) -
        Number(a.avg_pool_usd_per_week_at_collection_quote) || a.index - b.index)
      .slice(0, 5);
    const target = $("leaders-items");
    target.replaceChildren();
    leaders.forEach((p, i) => {
      const row = make("div", "leader-row");
      const name = make("div");
      name.append(make("strong", "", (i + 1) + ". " + poolName(p)));
      name.append(make("div", "tiny", "Pool #" + p.index + " · " +
        p.observed_any_reward_positive_weeks + "/4 reward weeks · " +
        money(p.avg_pool_usd_per_week_at_collection_quote) + "/week"));
      row.append(name);
      row.append(make("strong", "score-number", researchScore(p) + "/100"));
      target.append(row);
    });
  }
  function evidenceMatch(p, setting) {
    if (setting === "all") return true;
    if (p.observed_any_reward_positive_weeks !== 4) return false;
    if (setting === "regular") return true;
    return setting === "context" && p.usd_coverage_complete &&
      numeric(p.avg_pool_usd_per_week_at_collection_quote) !== null &&
      numeric(p.avg_pool_usd_per_week_at_collection_quote) >= MIN_RESEARCH_WEEKLY_USD &&
      numeric(p.inventory_snapshot_votes) !== null &&
      numeric(p.inventory_snapshot_votes) >= MIN_OLD_SNAPSHOT_VOTES;
  }
  // P7.2: distinct historical source categories use positive token amounts,
  // not USD token prices, old voting weights, or predicted earnings.
  function rewardSource(p) {
    const fees = p.observed_fees_positive_weeks;
    const bribes = p.observed_bribes_positive_weeks;
    if (!Number.isInteger(fees) || !Number.isInteger(bribes) ||
        fees < 0 || fees > 4 || bribes < 0 || bribes > 4)
      return "unknown";
    if (fees > 0 && bribes > 0) return "both";
    if (fees > 0) return "fees";
    if (bribes > 0) return "bribes";
    return "none";
  }
  // Calculate the same four-week share as P5, from each reward token's
  // saved-quote WEEKLY mean (4-week means have the same fraction as sums).
  // Any unpriced positive token, non-positive total or failed reconciliation
  // makes the share undefined, never 0 by assumption.
  function pricedBribesShare(p) {
    if (p.usd_coverage_complete !== true) return null;
    const poolMean = numeric(p.avg_pool_usd_per_week_at_collection_quote);
    if (poolMean === null || poolMean <= 0 || !Array.isArray(p.token_rewards))
      return null;
    let fees = 0, bribes = 0;
    for (const token of p.token_rewards) {
      if (!token || (token.type !== "FEES" && token.type !== "BRIBES") ||
          !Number.isInteger(token.observed_positive_weeks) ||
          token.observed_positive_weeks < 0 || token.observed_positive_weeks > 4)
        return null;
      let value = numeric(token.mean_usd_at_collection_quote);
      // A token that received no raw reward cannot contribute USD; a token
      // with a positive reward and no price MUST remain unknown.
      if (value === null) {
        if (token.observed_positive_weeks !== 0) return null;
        value = 0;
      }
      if (token.type === "FEES") fees += value;
      else bribes += value;
    }
    const total = fees + bribes;
    if (!Number.isFinite(total) || total <= 0 ||
        Math.abs(total - poolMean) > Math.max(1e-8, poolMean * 1e-6))
      return null;
    return Math.max(0, Math.min(100, 100 * bribes / total));
  }
  function matchesP72(p, source, shareFilter) {
    const category = rewardSource(p);
    if (source !== "all" && category !== source) return false;
    if (shareFilter === "all") return true;
    const share = pricedBribesShare(p);
    if (shareFilter === "unknown") return share === null;
    if (share === null) return false;
    if (shareFilter === "atleast25") return share >= 25;
    if (shareFilter === "atleast50") return share >= 50;
    if (shareFilter === "atleast75") return share >= 75;
    return false;
  }
  function error(message) {
    $("error").hidden = !message;
    $("error").textContent = message || "";
  }
  // P7.1 is a read-only inventory distribution, not a profitability signal.
  // Group by the SAVED collection epoch, never current search/filters.
  // Return null on inconsistent metadata rather than show misleading counts.
  function computeDistribution(pools, epoch, meta) {
    if (!Array.isArray(pools) || !meta ||
        !Number.isInteger(meta.audited_pools) || meta.audited_pools < 0)
      return null;
    const rows = pools.filter(p => p.collection_epoch_utc === epoch);
    if (rows.length !== meta.audited_pools) return null;
    const buckets = Array.from({length: 5}, (_, i) => ({
      weeks: i, pools: 0, complete: 0, incomplete: 0,
    }));
    let complete = 0, incomplete = 0, noRewards = 0;
    let feesObservedPools = 0, bribesObservedPools = 0;
    for (const p of rows) {
      const weeks = p.observed_any_reward_positive_weeks;
      const fees = p.observed_fees_positive_weeks;
      const bribes = p.observed_bribes_positive_weeks;
      if (!Number.isInteger(weeks) || weeks < 0 || weeks > 4 ||
          !Number.isInteger(fees) || fees < 0 || fees > weeks ||
          !Number.isInteger(bribes) || bribes < 0 || bribes > weeks ||
          typeof p.usd_coverage_complete !== "boolean" ||
          typeof p.no_observed_rewards !== "boolean" ||
          p.no_observed_rewards !== (weeks === 0) ||
          (weeks > 0 && fees === 0 && bribes === 0)) return null;
      const b = buckets[weeks];
      b.pools++;
      if (p.usd_coverage_complete) { b.complete++; complete++; }
      else { b.incomplete++; incomplete++; }
      if (weeks === 0) noRewards++;
      if (fees > 0) feesObservedPools++;
      if (bribes > 0) bribesObservedPools++;
    }
    if (complete + incomplete !== rows.length ||
        buckets.reduce((n, b) => n + b.pools, 0) !== rows.length ||
        complete !== meta.complete_usd_pools ||
        incomplete !== meta.incomplete_usd_pools ||
        noRewards !== meta.no_observed_rewards_pools ||
        rows.length - noRewards !== meta.positive_reward_pools) return null;
    return {
      epoch, total: rows.length, complete, incomplete, noRewards,
      fourWeeks: buckets[4].pools, feesObservedPools, bribesObservedPools,
      buckets,
    };
  }
  function drawP7Coverage() {
    const target = $("p7-distribution");
    target.replaceChildren();
    const meta = doc.meta;
    if (!meta || !meta.by_collection_epoch) {
      target.append(make("p", "warnline", "Saved cohort metadata unavailable."));
      return;
    }
    const cohorts = [EPOCH8, EPOCH15].map(epoch =>
      computeDistribution(doc.pools, epoch, meta.by_collection_epoch[epoch]));
    if (cohorts.some(c => c === null) ||
        cohorts.reduce((n, c) => n + c.total, 0) !== meta.audited_pool_count ||
        cohorts.reduce((n, c) => n + c.complete, 0) !== meta.audited_usd_complete_pool_count ||
        cohorts.reduce((n, c) => n + c.incomplete, 0) !== meta.audited_usd_incomplete_pool_count) {
      target.append(make("p", "warnline",
        "Distribution unavailable: saved cohort counts do not reconcile. " +
        "No zero or completeness values have been inferred."));
      return;
    }
    for (const c of cohorts) {
      const card = make("article", "p7-cohort");
      card.append(make("h3", "", epochName(c.epoch)));
      card.append(make("p", "p7-subtitle",
        c.total.toLocaleString("en-US") + " separately collected pools · " +
        c.fourWeeks + " with observed rewards in 4/4 weeks"));
      const totals = make("div", "p7-totals");
      const items = [
        ["0/4 reward weeks", c.noRewards],
        ["Complete USD quote coverage", c.complete],
        ["Incomplete USD quote coverage", c.incomplete],
        ["Any FEES observed", c.feesObservedPools],
        ["Any BRIBES observed", c.bribesObservedPools],
      ];
      items.forEach(([label, count]) => {
        const line = make("div", "p7-total");
        line.append(make("span", "", label));
        line.append(make("strong", "", count.toLocaleString("en-US")));
        totals.append(line);
      });
      card.append(totals);
      card.append(make("h4", "", "Observed nonzero reward weeks · 0 to 4"));
      const legend = make("p", "p7-legend");
      legend.append(make("span", "p7-key p7-key-complete", "Complete USD"));
      legend.append(make("span", "p7-key p7-key-incomplete", "Incomplete USD"));
      card.append(legend);
      const bars = make("div", "p7-rows");
      for (const b of c.buckets) {
        const row = make("div", "p7-row");
        row.append(make("span", "p7-week-label", b.weeks + "/4"));
        const track = make("div", "p7-track");
        track.setAttribute("role", "img");
        track.setAttribute("aria-label",
          b.pools + " pools with " + b.weeks + "/4 reward weeks: " +
          b.complete + " complete USD, " + b.incomplete + " incomplete USD");
        const green = make("span", "p7-segment p7-complete");
        const amber = make("span", "p7-segment p7-incomplete");
        green.style.width = (c.total ? 100 * b.complete / c.total : 0).toFixed(3) + "%";
        amber.style.width = (c.total ? 100 * b.incomplete / c.total : 0).toFixed(3) + "%";
        track.append(green, amber);
        row.append(track);
        row.append(make("span", "p7-row-count",
          b.pools + " (" + (c.total ? (100 * b.pools / c.total).toFixed(1) : "0.0") +
          "%)"));
        bars.append(row);
        const breakdown = make("p", "p7-breakdown",
          b.complete + " complete · " + b.incomplete + " incomplete USD");
        bars.append(breakdown);
      }
      card.append(bars);
      target.append(card);
    }
  }
  function drawStats() {
    const m = doc.meta;
    $("stat-pools").textContent = m.audited_pool_count.toLocaleString("en-US");
    $("stat-priced").textContent = m.audited_usd_complete_pool_count.toLocaleString("en-US");
    $("stat-missing").textContent = m.audited_usd_incomplete_pool_count.toLocaleString("en-US");
    $("stat-zero").textContent = doc.pools.filter(p => p.no_observed_rewards).length.toLocaleString("en-US");
    const pct = 100 * m.audited_usd_complete_pool_count / m.audited_pool_count;
    $("stat-coverage").textContent = pct.toFixed(1) + "% saved price coverage";
    $("data-generated").textContent = "Research file generated: " +
      String(m.generated_at_utc || "unknown").slice(0, 19).replace("T", " ") +
      " UTC · No live updates";
  }
  function pairName(p) {
    const pair = doc.pairs.get(p.address.toLowerCase());
    return pair && pair.index === p.index && pair.pair_label
      ? pair.pair_label : null;
  }
  function poolName(p) {
    return pairName(p) || "Pool #" + p.index + " · Pair unavailable";
  }
  function searchMatch(p, query) {
    if (!query) return true;
    const tokens = (p.token_rewards || []).flatMap(t => [t.symbol || "", t.address || ""]);
    return [
      String(p.index), "#" + p.index, p.address || "",
      p.gauge_address || "", pairName(p) || "", ...tokens,
    ].some(s => String(s).toLowerCase().includes(query));
  }
  // P6.1: presentation-only beginner/researcher views.
  // Neither mode changes the saved research data or computes yield.
  function setView(mode) {
    if (mode !== "beginner" && mode !== "researcher") return;
    doc.view = mode;
    document.querySelector(".wrap").dataset.view = mode;
    [["beginner", "view-beginner"], ["researcher", "view-researcher"]]
      .forEach(([name, id]) => {
        const active = name === mode;
        $(id).classList.toggle("active", active);
        $(id).setAttribute("aria-pressed", String(active));
      });
    $("view-intro").textContent = mode === "beginner"
      ? "Begin with a pool search and its observed reward history. Switch to Researcher view for scoring, filters and old-vote ratios."
      : "Researcher view shows all saved-data filters and historical research heuristics; never APR or a current payout.";
    // Hidden advanced filters must not silently restrict beginner results.
    if (mode === "beginner") {
      $("status").value = "all";
      $("evidence").value = "all";
      $("sort").value = "index";
      $("source").value = "all";
      $("bribes-share").value = "all";
    }
    apply();
  }
  function apply() {
    doc.page = 0;
    render();
  }
  function render() {
    if (!doc.meta) return;
    const query = $("search").value.toLowerCase().trim();
    const period = $("epoch").value;
    const status = $("status").value;
    const evidence = $("evidence").value;
    const source = $("source").value;
    const shareFilter = $("bribes-share").value;
    const sort = $("sort").value;
    const all = period === "both";
    [...$("sort").options].forEach(opt => {
      opt.disabled = all && opt.value !== "index";
    });
    if (all && sort !== "index") $("sort").value = "index";
    doc.filtered = doc.pools.filter(p => {
      if (!all && p.collection_epoch_utc !== period) return false;
      if (!searchMatch(p, query) || !evidenceMatch(p, evidence)) return false;
      if (!matchesP72(p, source, shareFilter)) return false;
      if (status === "positive" && p.observed_any_reward_positive_weeks === 0) return false;
      if (status === "zero" && p.observed_any_reward_positive_weeks !== 0) return false;
      if (status === "complete" && !p.usd_coverage_complete) return false;
      if (status === "incomplete" && p.usd_coverage_complete) return false;
      return true;
    });
    const direction = $("sort").value;
    doc.filtered.sort((a, b) => {
      if (direction === "score") {
        const sa = researchScore(a), sb = researchScore(b);
        return (sb === null ? -1 : sb) - (sa === null ? -1 : sa) || a.index - b.index;
      }
      if (direction === "index") return a.index - b.index;
      if (direction === "frequency") {
        return b.observed_any_reward_positive_weeks -
          a.observed_any_reward_positive_weeks || a.index - b.index;
      }
      // An enormous ratio from almost zero old votes and sub-$10 rewards
      // is a denominator artifact, not a leading research opportunity.
      if (direction === "ratio") {
        const qa = Number(!a.usd_coverage_complete || sizeCautions(a).length > 0);
        const qb = Number(!b.usd_coverage_complete || sizeCautions(b).length > 0);
        if (qa !== qb) return qa - qb;
        // Fragile or unpriced ratios are not meaningfully rankable by value.
        if (qa && qb) return a.index - b.index;
      }
      const field = direction === "weekly"
        ? "avg_pool_usd_per_week_at_collection_quote"
        : "illustrative_usd_per_million_inventory_votes";
      const x = a[field] === null ? -Infinity : Number(a[field]);
      const y = b[field] === null ? -Infinity : Number(b[field]);
      return y - x || a.index - b.index;
    });
    drawPage();
    drawLeaders();
  }
  function drawPage() {
    const rows = $("rows");
    rows.replaceChildren();
    const max = Number($("page-size").value) || 25;
    const count = doc.filtered.length;
    const pages = Math.max(1, Math.ceil(count / max));
    doc.page = Math.min(doc.page, pages - 1);
    const start = doc.page * max;
    const visible = doc.filtered.slice(start, start + max);
    const frag = document.createDocumentFragment();
    visible.forEach(p => {
      const tr = make("tr");
      const identity = cell(tr);
      identity.append(make("div", "pool-name", poolName(p)));
      identity.append(make("div", "tiny", "Pool #" + p.index));
      const addr = make("div", "address", shortAddr(p.address));
      identity.append(addr);
      const category = rewardSource(p);
      const categoryText = {fees:"FEES only", bribes:"BRIBES only",
        both:"FEES + BRIBES", none:"No observed rewards", unknown:"Source unknown"};
      const share = pricedBribesShare(p);
      identity.append(make("div", "tiny research-only source-classification",
        "Observed source: " + categoryText[category] +
        " · BRIBES share: " + (share === null ? "Undefined" :
          share.toFixed(1) + "% saved-price USD")));
      cell(tr, epochName(p.collection_epoch_utc), "tiny");
      const activity = cell(tr);
      const active = p.observed_any_reward_positive_weeks;
      activity.append(make("span", "chip " + (active ? "good" : "zero"), active + " / 4 weeks"));
      const coverage = cell(tr);
      coverage.append(make("span", "chip " +
        (p.usd_coverage_complete ? "good" : "warn"),
        p.usd_coverage_complete ? "Complete" : "Incomplete"));
      cell(tr, p.usd_coverage_complete
        ? money(p.avg_pool_usd_per_week_at_collection_quote)
        : "Unknown", "right " + (p.usd_coverage_complete ? "num" : "no-data"));
      cell(tr, researchScore(p) === null ? "Unrated" : researchScore(p) + "/100", "right num");
      const fragileRatio = sizeCautions(p).length > 0;
      const ratio = cell(tr, p.usd_coverage_complete
        ? (fragileRatio && p.illustrative_usd_per_million_inventory_votes !== null
          ? "Unreliable" : money(p.illustrative_usd_per_million_inventory_votes))
        : "Unknown", "right " + (p.usd_coverage_complete ? "num" : "no-data"));
      if (p.usd_coverage_complete && p.illustrative_usd_per_million_inventory_votes !== null) {
        const cautions = sizeCautions(p);
        if (cautions.length) {
          const notice = make("span", "ratio-caution", "⚠ Fragile ratio");
          notice.title = cautions.join("; ");
          ratio.append(notice);
        }
      }
      const action = cell(tr);
      const actions = make("div", "compare-actions");
      const button = make("button", "detail-button", "Details ↗");
      button.type = "button";
      button.addEventListener("click", () => showDetails(p));
      actions.append(button);
      const selected = doc.compared.includes(p.index);
      const cmp = make("button", "compare-button" + (selected ? " selected" : ""),
                       selected ? "Remove" : "+ Compare");
      cmp.type = "button";
      cmp.setAttribute("aria-pressed", String(selected));
      cmp.addEventListener("click", () => toggleCompare(p));
      actions.append(cmp);
      action.append(actions);
      // P6.2 responsive pool cards: visible labels without another data copy.
      const mobileLabels = ["Pool", "Collection epoch", "Rewards observed",
        "USD coverage", "Mean USD / week", "Research score",
        "USD / 1M old votes", "Explore / compare"];
      [...tr.cells].forEach((td, i) => {
        td.dataset.label = mobileLabels[i];
      });
      frag.append(tr);
    });
    if (!visible.length) {
      const row = make("tr");
      const empty = cell(row, "No pools match these filters.");
      empty.colSpan = 8;
      frag.append(row);
    }
    rows.append(frag);
    $("count").textContent = count.toLocaleString("en-US") +
      " matching pools · " + (count
        ? "showing " + (start + 1) + "–" + (start + visible.length)
        : "try changing your filters");
    $("page-count").textContent = "Page " + (doc.page + 1) + " / " + pages;
    $("prev").disabled = doc.page === 0;
    $("next").disabled = doc.page >= pages - 1;
  }
  function sectionValue(parent, label, value) {
    const block = make("div", "detail-box");
    block.append(make("small", "", label));
    block.append(make("strong", "", value));
    parent.append(block);
  }
  // P5.1: explanatory evidence, not a confidence score or yield estimate.
  // Only saved fully priced P5 observations may produce numeric interpretations.
  function renderEvidenceNotes(trend, parent) {
    const section = make("section", "evidence-notes");
    section.append(make("h4", "", "P5.1 · Evidence & interpretation"));
    section.append(make("p", "mini",
      "Descriptive flags for four completed weeks. Not predictions, probability " +
      "scores, investment safety ratings or personal veAERO returns."));
    const observations = trend && Array.isArray(trend.evidence) ? trend.evidence : [];
    if (!observations.length) {
      section.append(make("p", "warnline",
        "Evidence explanations unavailable; update the local research server."));
    } else {
      const list = make("div", "evidence-list");
      const allowed = new Set(["caution", "context", "unknown"]);
      observations.forEach(note => {
        if (!note || typeof note.kind !== "string" ||
            typeof note.text !== "string") return;
        const level = allowed.has(note.level) ? note.level : "unknown";
        const item = make("article", "evidence-item evidence-" + level);
        item.append(make("strong", "evidence-kind", note.kind));
        item.append(make("p", "mini", note.text));
        list.append(item);
      });
      section.append(list);
    }
    parent.append(section);
  }
  // P5: four saved weeks of POOL rewards only. No vote denominators, live
  // pricing, earnings projection or forecast. Incomplete quotes => no metrics.
  function renderTrendSummary(data, parent) {
    const section = make("section", "trend-overview");
    section.append(make("h3", "", "P5 · Four-week reward pattern"));
    section.append(make("p", "mini",
      "Descriptive observations, not a trend forecast. Four weeks are too few to " +
      "establish statistical stability. USD reflects saved collection-time quotes."));
    const t = data.trend;
    if (!t || t.status !== "available") {
      section.append(make("p", "warnline",
        "Four-week USD analysis unavailable: incomplete saved USD quotes or an older server response. " +
        "Missing prices are not $0."));
      renderEvidenceNotes(t, section);
      parent.append(section);
      return;
    }
    const split = numeric(t.fees_share_percent);
    const bribe = numeric(t.bribes_share_percent);
    const grid = make("div", "detail-grid");
    sectionValue(grid, "Four-week FEES · saved-price USD", money(t.fees_four_week_usd));
    sectionValue(grid, "Four-week BRIBES · saved-price USD", money(t.bribes_four_week_usd));
    sectionValue(grid, "Four-week POOL total · saved-price USD", money(t.total_four_week_usd));
    sectionValue(grid, "Positive priced weeks", String(t.positive_priced_weeks) + " / 4");
    sectionValue(grid, "Largest week concentration",
      t.largest_week_share_percent === null ? "No positive priced rewards" :
        plain(t.largest_week_share_percent) + "% of four-week total");
    let comparison = "Unavailable";
    if (t.latest_change_state === "both_zero")
      comparison = "Both weeks $0";
    else if (t.latest_change_state === "new_positive_from_zero")
      comparison = "From $0 to " + money(t.latest_week_usd) + " (percentage undefined)";
    else if (t.latest_change_state === "unchanged")
      comparison = "Unchanged at " + money(t.latest_week_usd);
    else if ((t.latest_change_state === "increased" || t.latest_change_state === "decreased") &&
             t.latest_change_percent !== null) {
      const amount = Number(t.latest_week_delta_usd);
      comparison = (amount > 0 ? "+" : "−") + money(Math.abs(amount)) +
        " (" + (amount > 0 ? "+" : "") + plain(t.latest_change_percent) +
        "%) vs prior week";
    }
    sectionValue(grid, "Latest vs previous completed week", comparison);
    section.append(grid);
    const mix = make("div", "trend-mix");
    mix.append(make("strong", "", "Four-week priced reward mix"));
    if (split === null || bribe === null || split + bribe > 100.1) {
      mix.append(make("p", "mini", "No positive priced reward total; composition undefined."));
    } else {
      const track = make("div", "trend-mix-track");
      const feesBar = make("span", "trend-fees");
      const bribesBar = make("span", "trend-bribes");
      feesBar.style.width = Math.min(100, split).toFixed(2) + "%";
      bribesBar.style.width = Math.min(100, bribe).toFixed(2) + "%";
      track.append(feesBar, bribesBar);
      mix.append(track);
      mix.append(make("p", "mini", "FEES: " + plain(t.fees_share_percent) +
        "% · BRIBES: " + plain(t.bribes_share_percent) +
        "% of the saved-price four-week total."));
    }
    section.append(mix);
    section.append(make("p", "mini",
      "Largest observed week: " + (t.largest_week_start_utc ?
        t.largest_week_start_utc.slice(0, 10) : "None") +
      ". The P4 votes below/above come from DIFFERENT blocks and are never " +
      "used in this reward calculation."));
    renderEvidenceNotes(t, section);
    parent.append(section);
  }
  function renderWeeklyBreakdown(p, root) {
    const section = make("section", "weekly-analysis");
    section.append(make("h3", "", "Four completed weeks · FEES vs BRIBES"));
    section.append(make("p", "mini",
      "USD is based on token prices SAVED at collection, not prices from each historical week. " +
      "Unknown quotes are never treated as $0; this is not current income."));
    const content = make("div", "weekly-content", "Loading saved weekly breakdown…");
    section.append(content);
    root.append(section);
    fetch("/api/weekly?index=" + encodeURIComponent(p.index), {cache: "no-store"})
      .then(async response => {
        if (!response.ok) {
          const problem = await response.json().catch(() => ({}));
          throw new Error(problem.error || "HTTP " + response.status);
        }
        return response.json();
      })
      .then(data => {
        if (doc.detailRequest !== p.index || !section.isConnected) return;
        if (data.index !== p.index ||
            data.address.toLowerCase() !== p.address.toLowerCase() ||
            data.collection_epoch_utc !== p.collection_epoch_utc ||
            !Array.isArray(data.weeks) || data.weeks.length !== 4)
          throw new Error("Saved weekly breakdown does not match this pool");
        content.replaceChildren();
        renderTrendSummary(data, content);
        const maximum = Math.max(1, ...data.weeks.map(w =>
          numeric(w.total_usd) ?? Math.max(numeric(w.fees_usd) ?? 0, numeric(w.bribes_usd) ?? 0)));
        data.weeks.forEach(w => {
          const item = make("article", "weekly-item");
          const header = make("div", "weekly-heading");
          header.append(make("strong", "", w.week_start_utc.slice(0, 10)));
          header.append(make("strong", "weekly-total", "Total " + money(w.total_usd)));
          item.append(header);
          const bars = make("div", "weekly-bars");
          [["fees_usd", "FEES", "fee-bar"], ["bribes_usd", "BRIBES", "bribe-bar"]]
            .forEach(([key, label, style]) => {
              const value = numeric(w[key]);
              const line = make("div", "weekly-bar-line");
              line.append(make("span", "weekly-kind", label));
              const track = make("div", "weekly-track");
              const fill = make("div", "weekly-fill " + style);
              fill.style.width = value === null ? "0%" :
                (100 * Math.min(maximum, value) / maximum).toFixed(2) + "%";
              track.append(fill);
              line.append(track);
              line.append(make("span", "weekly-value", money(w[key])));
              bars.append(line);
            });
          item.append(bars);
          content.append(item);
        });
        if (!p.usd_coverage_complete) content.append(make("p", "warnline",
          "Incomplete USD coverage: totals marked Unknown may contain unpriced rewards."));
      })
      .catch(err => {
        if (doc.detailRequest !== p.index || !section.isConnected) return;
        content.replaceChildren(make("p", "warnline",
          "Saved weekly breakdown unavailable: " + err.message));
      });
  }
  // P4 weights are separate per-page pinned observations, NOT aligned with
  // FEES/BRIBES and NOT a simultaneous 928-pool voting snapshot.
  function renderRollingVotes(p, root) {
    const section = make("section", "vote-analysis");
    section.append(make("h3", "", "P4 · Observed voting weight"));
    section.append(make("p", "mini",
      "Each collection page uses its own pinned Base block. These 928 observations " +
      "were NOT collected in one block or aligned with FEES/BRIBES weeks. " +
      "Vote share is measured against Voter totalWeight at THIS pool's block. " +
      "Not live voting power, future APR or a veNFT income estimate."));
    const content = make("div", "vote-content", "Loading saved vote observation…");
    section.append(content);
    root.append(section);
    fetch("/api/votes?index=" + encodeURIComponent(p.index), {cache:"no-store"})
      .then(async response => {
        if (!response.ok) {
          const problem = await response.json().catch(() => ({}));
          throw new Error(problem.error || "HTTP " + response.status);
        }
        return response.json();
      })
      .then(v => {
        if (doc.detailRequest !== p.index || !section.isConnected) return;
        if (v.index !== p.index || v.address.toLowerCase() !== p.address.toLowerCase() ||
            v.synchronized_with_reward_epochs !== false ||
            !Number.isInteger(v.block_number) || !/^[0-9]+$/.test(v.vote_weight_raw))
          throw new Error("P4 vote observation does not match this pool");
        content.replaceChildren();
        const grid = make("div", "detail-grid");
        sectionValue(grid, "Observed pool weight · veAERO", plain(v.vote_weight_veaero));
        sectionValue(grid, "Share of Voter total at observed block",
          v.voter_share_percent_at_block === null ?
          "Unknown (zero total)" : plain(v.voter_share_percent_at_block) + "%");
        sectionValue(grid, "Observation Base block", String(v.block_number));
        content.append(grid);
        content.append(make("p", "mini",
          "Base block time (UTC): " + v.block_timestamp_utc +
          " · Source: " + (v.collection_type === "preserved_pinned_checkpoint" ?
            "preserved first 180 observations" : "rolling observation page") +
          " · Voter total at SAME block: " + plain(v.voter_total_weight_veaero) +
          " veAERO."));
      })
      .catch(err => {
        if (doc.detailRequest !== p.index || !section.isConnected) return;
        content.replaceChildren(make("p", "warnline",
          "Saved P4 voting observation unavailable: " + err.message));
      });
  }
  function showDetails(p) {
    const target = $("detail");
    target.hidden = false;
    doc.detailRequest = p.index;
    $("detail-title").textContent = poolName(p) + " · Reward breakdown";
    $("detail-intro").textContent = epochName(p.collection_epoch_utc) +
      " · Older Base block " + p.inventory_snapshot_block +
      " · No current pool status or live price verified";
    const root = $("detail-content");
    root.replaceChildren();
    const row = make("div", "detail-grid");
    sectionValue(row, "Mean pool rewards / week · saved quote",
      p.usd_coverage_complete ? money(p.avg_pool_usd_per_week_at_collection_quote) : "Unknown — incomplete USD");
    sectionValue(row, "Observed reward weeks", p.observed_any_reward_positive_weeks +
      " / 4 (" + p.observed_fees_positive_weeks + " FEES, " +
      p.observed_bribes_positive_weeks + " BRIBES)");
    sectionValue(row, "Old snapshot voting power", plain(p.inventory_snapshot_votes) + " veAERO");
    sectionValue(row, "Historical research priority",
      researchScore(p) === null ? "Unrated · incomplete USD" : researchScore(p) + " / 100");
    root.append(row);
    sizeCautions(p).forEach(message =>
      root.append(make("p", "warnline", "⚠ " + message + ". An old vote ratio is not a current yield.")));
    const identity = make("p", "mini");
    identity.append(make("strong", "", "Pool address: "));
    const addr = String(p.address || "");
    if (/^0x[a-f0-9]{40}$/i.test(addr)) {
      const link = make("a", "mono", addr);
      link.href = "https://basescan.org/address/" + addr;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      identity.append(link);
    } else {
      identity.append(make("span", "mono", addr));
    }
    root.append(identity);
    if (!p.usd_coverage_complete) {
      root.append(make("p", "warnline",
        "Full pool USD value is unavailable. Missing token prices are not zero."));
      const list = make("ul", "missing-list");
      const missing = p.missing_or_stale_components || [];
      missing.forEach(problem => list.append(make("li", "", problem)));
      if (p.truncated_reward_registry) list.append(make("li", "", "Reward registry was truncated or unsupported"));
      root.append(list);
    }
    if (p.no_observed_rewards) {
      root.append(make("p", "warnline",
        "No positive FEES/BRIBES were observed in the four completed weeks. "
        + "This does not predict zero future rewards."));
    }
    if (p.illustrative_usd_per_million_inventory_votes !== null) {
      root.append(make("p", "warnline",
        "Illustrative USD per 1,000,000 old snapshot votes: " +
        money(p.illustrative_usd_per_million_inventory_votes) +
        ". This is NOT an attainable, current, or forecast return."));
    }
    root.append(make("h3", "", "Registered reward tokens · not pool trading pairs"));
    const tokens = make("div", "token-list");
    (p.token_rewards || []).forEach(t => {
      const card = make("article", "token");
      const head = make("div", "token-head");
      head.append(make("b", "", t.symbol || "Unknown token"));
      head.append(make("span", "chip", t.type));
      card.append(head);
      card.append(make("p", "mono", t.address));
      card.append(make("p", "", "4-week average token / week: " +
        plain(t.mean_amount_per_week)));
      card.append(make("p", "", "Mean USD at saved quote: " +
        money(t.mean_usd_at_collection_quote)));
      card.append(make("p", "", "Positive weeks: " + t.observed_positive_weeks + "/4"));
      card.append(make("p", "", "Saved quote: " +
        money(t.quote_usd_per_token_at_collection) + " per token"));
      card.append(make("p", "", "Quote time: " +
        (t.quote_timestamp_utc || "Unavailable")));
      if (t.quote_missing_reason) {
        card.append(make("p", "warnline", "Quote status: " + t.quote_missing_reason));
      }
      tokens.append(card);
    });
    if (!p.token_rewards || !p.token_rewards.length) {
      tokens.append(make("p", "mini", "No registered reward tokens were read for this pool."));
    }
    root.append(tokens);
    renderRollingVotes(p, root);
    renderWeeklyBreakdown(p, root);
    target.scrollIntoView({behavior:"smooth",block:"start"});
  }
  // P5 comparison is descriptive. All pools must belong to one saved
  // collection epoch. Saved quotes may still have different timestamps.
  function renderComparisonRewardMix(p, card) {
    const panel = make("section", "compare-reward-mix");
    panel.append(make("h4", "", "P5 · Four-week reward composition"));
    const status = make("p", "mini", "Loading saved FEES / BRIBES breakdown…");
    panel.append(status);
    card.append(panel);
    fetch("/api/weekly?index=" + encodeURIComponent(p.index), {cache: "no-store"})
      .then(async response => {
        if (!response.ok) {
          const problem = await response.json().catch(() => ({}));
          throw new Error(problem.error || "HTTP " + response.status);
        }
        return response.json();
      })
      .then(data => {
        if (!card.isConnected || !doc.compared.includes(p.index)) return;
        if (data.index !== p.index || data.address.toLowerCase() !== p.address.toLowerCase() ||
            data.collection_epoch_utc !== p.collection_epoch_utc ||
            !Array.isArray(data.weeks) || data.weeks.length !== 4)
          throw new Error("Saved reward history does not match selected pool");
        panel.replaceChildren(make("h4", "", "P5 · Four-week reward composition"));
        const t = data.trend;
        if (!t || t.status !== "available" || !p.usd_coverage_complete) {
          panel.append(make("p", "warnline",
            "Unknown: incomplete saved USD prices. Missing values are NOT $0."));
          renderEvidenceNotes(t, panel);
          return;
        }
        const fees = numeric(t.fees_share_percent);
        const bribes = numeric(t.bribes_share_percent);
        const line = make("div", "compare-reward-metrics");
        line.append(make("p", "", "Four-week total: " + money(t.total_four_week_usd)));
        line.append(make("p", "", "FEES: " + money(t.fees_four_week_usd) +
          " · BRIBES: " + money(t.bribes_four_week_usd)));
        line.append(make("p", "", "Positive priced weeks: " +
          t.positive_priced_weeks + " / 4"));
        line.append(make("p", "", "Largest week: " +
          (t.largest_week_share_percent === null ? "Undefined ($0 total)" :
            plain(t.largest_week_share_percent) + "% of observed total")));
        let change = "Undefined";
        if (t.latest_change_state === "both_zero") {
          change = "Both weeks $0";
        } else if (t.latest_change_state === "new_positive_from_zero") {
          change = "New positive week after $0 · % undefined";
        } else if (t.latest_change_percent !== null) {
          // Signed percentage changes are allowed here; decreases are negative.
          const signed = Number(t.latest_change_percent);
          change = Number.isFinite(signed) ? (signed > 0 ? "+" : "") +
            plain(signed) + "% vs preceding week" : "Undefined";
        }
        line.append(make("p", "", "Latest weekly change: " + change));
        panel.append(line);
        if (fees !== null && bribes !== null && fees + bribes <= 100.1) {
          const track = make("div", "trend-mix-track");
          const f = make("span", "trend-fees");
          const b = make("span", "trend-bribes");
          f.style.width = Math.min(100, fees).toFixed(2) + "%";
          b.style.width = Math.min(100, bribes).toFixed(2) + "%";
          track.append(f, b);
          panel.append(track);
          panel.append(make("p", "mini", "FEES " + plain(t.fees_share_percent) +
            "% · BRIBES " + plain(t.bribes_share_percent) + "%"));
        } else {
          panel.append(make("p", "mini", "No positive priced rewards; split undefined."));
        }
        renderEvidenceNotes(t, panel);
        panel.append(make("p", "mini",
          "Historical rewards priced at each batch's saved quote; quote times may " +
          "differ even within the same collection epoch. " +
          "P4 voting weights are NOT synchronized and are not used to compute a payout."));
      })
      .catch(err => {
        if (!card.isConnected || !doc.compared.includes(p.index)) return;
        status.textContent = "Saved four-week comparison unavailable: " + err.message;
        if (status.parentNode !== panel) {
          panel.replaceChildren(make("h4", "", "P5 · Four-week reward composition"), status);
        }
        status.className = "warnline";
      });
  }
  function drawComparison() {
    const section = $("compare-panel");
    section.hidden = doc.compared.length === 0 && !doc.compareError;
    $("compare-error").hidden = !doc.compareError;
    $("compare-error").textContent = doc.compareError;
    const target = $("compare-items");
    target.replaceChildren();
    const selected = doc.compared.map(id => doc.pools.find(p => p.index === id))
      .filter(Boolean);
    $("compare-note").textContent = selected.length
      ? "Selected observation epoch: " + epochName(selected[0].collection_epoch_utc) +
        " · " + selected.length + " / 3 · Other epochs cannot be mixed"
      : "Compare up to three pools from the SAME saved collection epoch.";
    selected.forEach(p => {
      const card = make("article", "compare-card");
      card.append(make("h3", "", poolName(p)));
      card.append(make("p", "mini", "Pool #" + p.index));
      card.append(make("p", "", shortAddr(p.address) +
        " · " + epochName(p.collection_epoch_utc)));
      const metrics = make("div", "compare-metrics");
      const pairs = [
        ["Research priority (historical)", researchScore(p) === null ? "Unrated" : researchScore(p) + "/100"],
        ["Mean weekly pool rewards", p.usd_coverage_complete
          ? money(p.avg_pool_usd_per_week_at_collection_quote) : "Unknown"],
        ["Positive reward weeks", p.observed_any_reward_positive_weeks + " / 4"],
        ["FEES weeks", p.observed_fees_positive_weeks + " / 4"],
        ["BRIBES weeks", p.observed_bribes_positive_weeks + " / 4"],
        ["Old snapshot votes", plain(p.inventory_snapshot_votes) + " veAERO"],
        ["USD coverage", p.usd_coverage_complete ? "Complete" : "Incomplete"],
        ["USD / 1M old votes", p.usd_coverage_complete
          ? (sizeCautions(p).length &&
             p.illustrative_usd_per_million_inventory_votes !== null
             ? "Unreliable — see pool details"
             : money(p.illustrative_usd_per_million_inventory_votes))
          : "Unknown"],
      ];
      pairs.forEach(([label, value]) => {
        const line = make("div");
        line.append(make("span", "", label));
        line.append(make("strong", "", value));
        metrics.append(line);
      });
      card.append(metrics);
      renderComparisonRewardMix(p, card);
      sizeCautions(p).forEach(message => card.append(make("p", "warnline", "⚠ " + message)));
      if (!p.usd_coverage_complete)
        card.append(make("p", "warnline", "⚠ Missing USD quotes; not a $0 reward total."));
      if (p.observed_any_reward_positive_weeks < 4)
        card.append(make("p", "warnline", "⚠ Rewards were not observed in all four weeks."));
      const button = make("button", "compare-button selected", "Remove from comparison");
      button.type = "button";
      button.addEventListener("click", () => toggleCompare(p));
      card.append(button);
      target.append(card);
    });
  }
  function toggleCompare(p) {
    doc.compareError = "";
    if (doc.compared.includes(p.index)) {
      doc.compared = doc.compared.filter(id => id !== p.index);
    } else {
      const selected = doc.compared.map(id => doc.pools.find(t => t.index === id))
        .filter(Boolean);
      if (selected.some(t => t.collection_epoch_utc !== p.collection_epoch_utc))
        doc.compareError = "Cross-epoch comparison is disabled. Clear the existing selection first.";
      else if (selected.length >= 3)
        doc.compareError = "Select at most three pools. Remove one before adding another.";
      else doc.compared.push(p.index);
    }
    drawComparison();
    drawPage();
    if (!$("compare-panel").hidden) $("compare-panel").scrollIntoView({behavior:"smooth",block:"start"});
  }
  $("clear-compare").addEventListener("click", () => {
    doc.compared = [];
    doc.compareError = "";
    drawComparison();
    drawPage();
  });
  $("prev").addEventListener("click", () => { if (doc.page > 0) {doc.page--; drawPage();} });
  $("next").addEventListener("click", () => {
    if ((doc.page + 1) * Number($("page-size").value) < doc.filtered.length) {
      doc.page++; drawPage();
    }
  });
  $("close-detail").addEventListener("click", () => {
    $("detail").hidden = true;
    $("search").focus();
  });
  ["search", "epoch", "status", "sort", "evidence", "source", "bribes-share"].forEach(id => {
    $(id).addEventListener("input", apply);
    $(id).addEventListener("change", apply);
  });
  $("page-size").addEventListener("change", apply);
  $("view-beginner").addEventListener("click", () => setView("beginner"));
  $("view-researcher").addEventListener("click", () => setView("researcher"));
  // P6.3: focus the existing search field; do not reset Researcher filters.
  $("researcher-jump").addEventListener("click", () => {
    const field = $("search");
    field.scrollIntoView({behavior: "smooth", block: "center"});
    field.focus({preventScroll: true});
  });
  $("jump-to-search").addEventListener("click", () => {
    const field = $("search");
    field.scrollIntoView({behavior: "smooth", block: "center"});
    field.focus({preventScroll: true});
  });
  $("try-example").addEventListener("click", () => {
    if (!doc.meta) {
      error("Wait for the saved research inventory to finish loading.");
      return;
    }
    error("");
    setView("beginner");
    $("epoch").value = EPOCH15;
    $("search").value = "1930";
    apply();
    const example = doc.pools.find(p =>
      p.index === 1930 && p.collection_epoch_utc === EPOCH15);
    if (example) showDetails(example);
    else $("search").focus();
  });

  fetch("/api/research", {cache:"no-store"})
    .then(async response => {
      if (!response.ok) {
        let detail = "";
        try { detail = (await response.json()).error || ""; } catch (_err) {}
        throw new Error(detail || "HTTP " + response.status);
      }
      return response.json();
    })
    .then(async data => {
      if (data.chain_id !== 8453 || !Array.isArray(data.pools) ||
          data.audited_pool_count !== data.pools.length) {
        throw new Error("Unexpected research data format");
      }
      doc.meta = data;
      doc.pools = data.pools;
      try {
        const response = await fetch("/api/pairs", {cache:"no-store"});
        if (!response.ok) throw new Error("Pair metadata HTTP " + response.status);
        const saved = await response.json();
        if (saved.chain_id !== 8453 || !Array.isArray(saved.pools))
          throw new Error("Invalid pair metadata");
        for (const pair of saved.pools) {
          if (typeof pair.pool_address === "string" &&
              /^0x[0-9a-f]{40}$/i.test(pair.pool_address) &&
              Number.isInteger(pair.index) &&
              typeof pair.pair_label === "string" &&
              pair.pair_label.length <= 140) {
            doc.pairs.set(pair.pool_address.toLowerCase(), pair);
          }
        }
      } catch (err) {
        console.warn("Trading pair metadata not loaded:", err.message);
      }
      drawStats();
      drawP7Coverage();
      render();
    })
    .catch(e => {
      error("Research data could not load: " + e.message);
      $("count").textContent = "No research dataset loaded.";
    });
})();
