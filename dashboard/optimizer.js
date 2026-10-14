/* AeroPredict AI — experimental read-only vote allocation optimizer.
   No wallet actions, no real AI forecasting, no guarantee of user rewards.
   Historical allocations + current token quotes + current vote weights are
   unsynchronized; this produces only a WHAT-IF scenario. */
(function () {
  "use strict";

  var css = document.createElement("style");
  css.textContent = [
    ".opt-fields{display:grid;grid-template-columns:1.1fr 1fr auto;gap:12px;align-items:end;margin:17px 0}",
    ".opt-field{display:flex;flex-direction:column;gap:6px;font-size:12px;color:var(--muted)}",
    ".opt-field input,.opt-field select{background:#142441;color:var(--text);border:1px solid #425576;border-radius:10px;padding:11px 12px;font:inherit;font-size:14px;width:100%}",
    ".opt-run{border:1px solid #20836e;background:linear-gradient(115deg,#126d5d,#174c54);color:#f1fff9;font-weight:700;white-space:nowrap}",
    ".opt-output{border:1px solid #285747;background:linear-gradient(130deg,#102c2b,#172844);border-radius:14px;padding:18px;margin:16px 0}",
    ".opt-output strong{display:block;color:var(--reward-green);font-size:clamp(22px,3vw,33px);letter-spacing:-.02em}",
    ".opt-output .meta{color:var(--muted);font-size:12px;margin-top:5px}",
    ".opt-table-wrap{overflow-x:auto;margin:12px 0}",
    ".opt-table{min-width:780px}",
    ".opt-table td:nth-child(2),.opt-table td:nth-child(3),.opt-table td:nth-child(4){text-align:right}",
    ".opt-table th:nth-child(2),.opt-table th:nth-child(3),.opt-table th:nth-child(4){text-align:right}",
    ".opt-footnote{font-size:12px;color:var(--amber);line-height:1.65;margin-top:16px}",
    ".opt-muted{color:var(--muted);font-size:12px}",
    "@media(max-width:750px){.opt-fields{grid-template-columns:1fr 1fr}.opt-run{grid-column:1/-1}}",
    "@media(max-width:480px){.opt-fields{grid-template-columns:1fr}}"
  ].join("");
  document.head.appendChild(css);

  var anchor = document.getElementById("voter-simulator");
  if (!anchor) return;
  var panel = document.createElement("section");
  panel.className = "panel";
  panel.id = "vote-optimizer";
  panel.innerHTML = [
    '<div class="headerline"><div>',
    '<h2>Vote Allocation Optimizer <span class="status">Experimental</span></h2>',
    '<p class="sub">Enter your locked AERO and remaining lock duration. Compare hypothetical FEES + BRIBES vote shares in USD.</p>',
    '</div><span class="tag">30% MAX / POOL</span></div>',
    '<div class="opt-fields">',
    '<label class="opt-field">Locked AERO amount',
    '<input id="opt-aero" type="number" min="0" max="1000000000" step="any" value="10000" inputmode="decimal"></label>',
    '<label class="opt-field">Remaining lock duration',
    '<select id="opt-years" aria-label="Choose remaining AERO lock duration">',
    '<option value="4">4 years / Auto-Max</option>',
    '<option value="3">3 years</option>',
    '<option value="2">2 years</option>',
    '<option value="1">1 year</option>',
    '<option value="0.5">6 months</option>',
    '</select></label>',
    '<button class="opt-run" type="button" id="opt-calculate">Calculate Optimal Allocation</button>',
    '</div>',
    '<div class="opt-output" aria-live="polite">',
    '<span class="small">Illustrative total weekly voting rewards</span>',
    '<strong id="opt-total">Press Calculate to estimate</strong>',
    '<div class="meta" id="opt-summary">No wallet connection required.</div>',
    '</div>',
    '<div class="opt-table-wrap"><table class="opt-table">',
    '<thead><tr><th>Pool / trading pair</th><th>Vote allocation</th><th>Your votes</th><th>Illustrative USD / week</th></tr></thead>',
    '<tbody id="opt-rows"><tr><td colspan="4">No allocation calculated yet.</td></tr></tbody>',
    '</table></div>',
    '<p class="opt-muted" id="opt-sources"></p>',
    '<p class="opt-footnote"><strong>Important:</strong> This is a deterministic scenario optimizer, NOT trained AI, an investment recommendation, or a payout quote. It applies current token prices to four-week historical pool-level FEES and BRIBES allocations, and uses independently sampled pool vote weights. The source snapshots are NOT synchronized. Future fees, bribes, effective votes, voting eligibility and realized token prices can change. 30% per pool is a voluntary diversification rule in this demo, not an Aerodrome protocol requirement. The ranking covers only sampled and fully priced pools; it does not scan every Aerodrome pool. It assumes new voting power is added to each pool. Actual NFT voting power may differ from the lock-duration approximation.</p>'
  ].join("");
  anchor.before(panel);

  var aeroField = panel.querySelector("#opt-aero");
  var yearsField = panel.querySelector("#opt-years");
  var totalNode = panel.querySelector("#opt-total");
  var summaryNode = panel.querySelector("#opt-summary");
  var rowsNode = panel.querySelector("#opt-rows");
  var sourcesNode = panel.querySelector("#opt-sources");
  var button = panel.querySelector("#opt-calculate");

  function usd(n) {
    if (n > 0 && n < 0.005) return "< $0.01";
    return n.toLocaleString("en-US", {
      style:"currency", currency:"USD",
      minimumFractionDigits:2, maximumFractionDigits:2
    });
  }
  function number(n, places) {
    return n.toLocaleString("en-US", {maximumFractionDigits:places});
  }
  function clearRows() { rowsNode.replaceChildren(); }
  function message(heading, explanation) {
    totalNode.textContent = heading;
    summaryNode.textContent = explanation;
    clearRows();
    var tr = document.createElement("tr");
    var td = document.createElement("td");
    td.colSpan = 4;
    td.textContent = explanation;
    tr.appendChild(td);
    rowsNode.appendChild(tr);
    sourcesNode.textContent = "";
  }
  function projected(pool, votes) {
    // R * x / (W+x) with the new hypothetical votes added to pool weight.
    return pool.usd * votes / (pool.votes + votes);
  }

  function solve(candidates, votingPower) {
    // Finite 1%-point allocation grid. Because each R*x/(W+x) term
    // has diminishing marginal returns for R>0 and W>0, selecting the
    // highest remaining marginal gain per 1% point gives the best result
    // ON THIS GRID. It is not a continuous global-optimum proof.
    var positions = candidates.map(function(c) {
      return {index:c.index, votes:c.votes, usd:c.usd, slices:0};
    });
    var sliceVotes = votingPower / 100;
    for (var unit = 0; unit < 100; unit++) {
      var chosen = -1, best = -Infinity;
      for (var i = 0; i < positions.length; i++) {
        var p = positions[i];
        if (p.slices >= 30) continue;
        var oldVotes = p.slices * sliceVotes;
        var delta = projected(p, oldVotes + sliceVotes) - projected(p, oldVotes);
        if (Number.isFinite(delta) && delta > best) {
          best = delta; chosen = i;
        }
      }
      if (chosen < 0) return null;
      positions[chosen].slices++;
    }
    return positions.filter(function(p){return p.slices > 0;})
      .map(function(p) {
        p.allocatedVotes = p.slices * sliceVotes;
        p.estimatedRewardUsd = projected(p, p.allocatedVotes);
        return p;
      })
      .sort(function(a,b){return b.estimatedRewardUsd - a.estimatedRewardUsd;});
  }

  function eligiblePools(report) {
    return report.pools
      .filter(function(p) {
        if (!p.fully_priced || p.fees_registry_truncated ||
            p.bribes_registry_truncated || p.bribes_error ||
            !Array.isArray(p.missing_components) || p.missing_components.length !== 0 ||
            p.four_week_avg_total_usd_at_current_prices == null ||
            p.pool_vote_weight_raw == null) return false;
        return true;
      })
      .map(function(p) {
        try {
          return {
            index: Number(p.index),
            usd: Number(p.four_week_avg_total_usd_at_current_prices),
            votes: Number(BigInt(p.pool_vote_weight_raw)) / 1e18
          };
        } catch (_) { return null; }
      })
      .filter(function(p) {
        return p && Number.isInteger(p.index) &&
          Number.isFinite(p.usd) && p.usd > 0 &&
          Number.isFinite(p.votes) && p.votes > 0;
      });
  }

  async function calculate() {
    var amount = Number(aeroField.value);
    var years = Number(yearsField.value);
    if (!aeroField.value || !Number.isFinite(amount) ||
        amount <= 0 || amount > 1e9) {
      return message("Invalid AERO amount", "Enter a positive locked AERO amount up to 1 billion.");
    }
    if (!Number.isFinite(years) || years <= 0 || years > 4) {
      return message("Invalid lock duration", "Choose a remaining lock duration from the menu.");
    }
    var effectivePower = amount * years / 4;
    if (!(effectivePower > 0)) {
      return message("Zero voting power", "The effective veAERO amount must be positive.");
    }

    button.disabled = true;
    button.textContent = "Calculating…";
    try {
      var response = await fetch("/api/results", {cache:"no-store"});
      if (!response.ok) throw new Error("Results endpoint returned HTTP " + response.status);
      var data = await response.json();
      var report = data.incentives;
      if (!report || !Array.isArray(report.pools) || report.chain_id !== 8453) {
        throw new Error("No valid saved incentive data; run collect_pool_incentives_base.py first");
      }
      var quoteTime = Date.parse(report.collected_at_utc);
      if (!Number.isFinite(quoteTime) ||
          Math.abs(Date.now() - quoteTime) > 36 * 60 * 60 * 1000) {
        throw new Error("Incentive data are older than 36 hours. Refresh the BRIBES and price collector.");
      }
      var epochTime = Date.parse(report.current_epoch_utc);
      if (!Number.isFinite(epochTime) ||
          Date.now() >= epochTime + 7 * 24 * 60 * 60 * 1000) {
        throw new Error("The weekly epoch has changed; refresh FEES, backtests and incentives.");
      }
      var eligible = eligiblePools(report);
      if (eligible.length < 4) {
        throw new Error("Only " + eligible.length +
          " sampled pools have complete priced rewards and positive vote weight. Need at least 4 for a 30% maximum.");
      }
      var allocation = solve(eligible, effectivePower);
      if (!allocation) throw new Error("Could not construct a full allocation under the 30% cap.");
      var sum = allocation.reduce(function(s,r) {
        return s + r.estimatedRewardUsd;
      }, 0);

      totalNode.textContent = usd(sum) + " / week";
      summaryNode.textContent =
        number(amount, 2) + " locked AERO · " +
        number(effectivePower, 2) + " estimated veAERO · " +
        allocation.length + " pools · exactly 100% allocated · 30% cap per pool";

      // Pair labels are read from the pool contracts' token0()/token1()
      // functions; never infer trading pairs from FEES/BRIBES token names.
      // Match both pool index and pool address to avoid stale mislabeling.
      var pairLabels = new Map();
      if (data.pairs && data.pairs.chain_id === 8453 &&
          Array.isArray(data.pairs.pools)) {
        data.pairs.pools.forEach(function(p) {
          if (Number.isInteger(p.index) && typeof p.pool_address === "string" &&
              typeof p.pair_label === "string" && p.pair_label.length > 0 &&
              p.pair_label.length <= 90) {
            pairLabels.set(p.index + "|" + p.pool_address.toLowerCase(), p.pair_label);
          }
        });
      }
      var incentivePools = new Map();
      report.pools.forEach(function(p) {
        if (Number.isInteger(p.index) && typeof p.pool_address === "string") {
          incentivePools.set(p.index, p.pool_address.toLowerCase());
        }
      });
      clearRows();
      allocation.forEach(function(row) {
        var tr = document.createElement("tr");
        var data = [
          "Pool #" + row.index + " · " +
            (pairLabels.get(row.index + "|" + incentivePools.get(row.index)) || "pair unavailable"),
          row.slices + "%",
          number(row.allocatedVotes, 2) + " veAERO",
          usd(row.estimatedRewardUsd)
        ];
        data.forEach(function(value, j) {
          var td = document.createElement("td");
          if (j === 3) td.className = "reward-amount";
          td.textContent = value;
          tr.appendChild(td);
        });
        rowsNode.appendChild(tr);
      });
      sourcesNode.textContent =
        "Data: " + eligible.length + "/" + report.pools.length +
        " sampled active pools eligible · saved " +
        report.collected_at_utc.slice(0, 16).replace("T", " ") +
        " UTC · 4 completed weekly epochs · quotes from " +
        report.quote_provider +
        " · 1%-point allocation steps";
    } catch (error) {
      message("Cannot calculate", error.message);
    } finally {
      button.disabled = false;
      button.textContent = "Calculate Optimal Allocation";
    }
  }
  button.addEventListener("click", calculate);
})();