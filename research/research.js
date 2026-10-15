"use strict";
(() => {
  const $ = id => document.getElementById(id);
  const doc = { pools: [], meta: null, filtered: [], page: 0 };
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
  function error(message) {
    $("error").hidden = !message;
    $("error").textContent = message || "";
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
  function searchMatch(p, query) {
    if (!query) return true;
    const tokens = (p.token_rewards || []).flatMap(t => [t.symbol || "", t.address || ""]);
    return [
      String(p.index), "#" + p.index, p.address || "",
      p.gauge_address || "", ...tokens,
    ].some(s => String(s).toLowerCase().includes(query));
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
    const sort = $("sort").value;
    const all = period === "both";
    [...$("sort").options].forEach(opt => {
      opt.disabled = all && opt.value !== "index";
    });
    if (all && sort !== "index") $("sort").value = "index";
    doc.filtered = doc.pools.filter(p => {
      if (!all && p.collection_epoch_utc !== period) return false;
      if (!searchMatch(p, query)) return false;
      if (status === "positive" && p.observed_any_reward_positive_weeks === 0) return false;
      if (status === "zero" && p.observed_any_reward_positive_weeks !== 0) return false;
      if (status === "complete" && !p.usd_coverage_complete) return false;
      if (status === "incomplete" && p.usd_coverage_complete) return false;
      return true;
    });
    const direction = $("sort").value;
    doc.filtered.sort((a, b) => {
      if (direction === "index") return a.index - b.index;
      if (direction === "frequency") {
        return b.observed_any_reward_positive_weeks -
          a.observed_any_reward_positive_weeks || a.index - b.index;
      }
      const field = direction === "weekly"
        ? "avg_pool_usd_per_week_at_collection_quote"
        : "illustrative_usd_per_million_inventory_votes";
      const x = a[field] === null ? -Infinity : Number(a[field]);
      const y = b[field] === null ? -Infinity : Number(b[field]);
      return y - x || a.index - b.index;
    });
    drawPage();
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
      identity.append(make("div", "pool-name", "Pool #" + p.index));
      const addr = make("div", "address", shortAddr(p.address));
      identity.append(addr);
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
      cell(tr, p.usd_coverage_complete
        ? money(p.illustrative_usd_per_million_inventory_votes)
        : "Unknown", "right " + (p.usd_coverage_complete ? "num" : "no-data"));
      const action = cell(tr);
      const button = make("button", "detail-button", "Details ↗");
      button.type = "button";
      button.addEventListener("click", () => showDetails(p));
      action.append(button);
      frag.append(tr);
    });
    if (!visible.length) {
      const row = make("tr");
      const empty = cell(row, "No pools match these filters.");
      empty.colSpan = 7;
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
  function showDetails(p) {
    const target = $("detail");
    target.hidden = false;
    $("detail-title").textContent = "Pool #" + p.index + " · Reward breakdown";
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
    root.append(row);
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
    target.scrollIntoView({behavior:"smooth",block:"start"});
  }
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
  ["search", "epoch", "status", "sort"].forEach(id => {
    $(id).addEventListener("input", apply);
    $(id).addEventListener("change", apply);
  });
  $("page-size").addEventListener("change", apply);
  fetch("/api/research", {cache:"no-store"})
    .then(async response => {
      if (!response.ok) {
        let detail = "";
        try { detail = (await response.json()).error || ""; } catch (_err) {}
        throw new Error(detail || "HTTP " + response.status);
      }
      return response.json();
    })
    .then(data => {
      if (data.chain_id !== 8453 || !Array.isArray(data.pools) ||
          data.audited_pool_count !== data.pools.length) {
        throw new Error("Unexpected research data format");
      }
      doc.meta = data;
      doc.pools = data.pools;
      drawStats();
      render();
    })
    .catch(e => {
      error("Research data could not load: " + e.message);
      $("count").textContent = "No research dataset loaded.";
    });
})();
