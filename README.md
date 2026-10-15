# AeroPredict AI

**English-language, Base-first Aerodrome reward research dashboard and GenLayer verification prototype.**

AeroPredict AI examines Aerodrome pool-level FEES token allocations, displays historical reward series, and evaluates simple statistical forecast baselines with walk-forward backtesting. The project is being developed with [GenLayer](https://genlayer.com/) for eventual verifiable forecast recording and settlement.

> **Prototype status — not a live yield optimizer.** The current dashboard uses locally saved snapshots of real Base Mainnet contract state. There is no automated live data refresh, deployed production contract, validated AI model, user wallet connection, personalized veAERO payout calculation, or guaranteed return.

## What works today

- Read registered Aerodrome pools, gauge status, vote weights, and FEES token allocations from Base Mainnet JSON-RPC.
- Collect completed weekly epoch allocation series from a small registration-order sample of pools.
- Evaluate three transparent baselines independently for each pool/reward-token series: previous week, four-week mean, and four-week median.
- Compare past forecasting errors using MAE (in the specific token's units) and WAPE (percentage).
- Display interactive 12-week history charts, model errors, and next-epoch statistical baselines in an English-language local web dashboard.
- Run an **experimental veAERO voting reward scenario**: supply effective voting power and vote allocation, then examine a pro-rata share of a selected pool's FEES baseline. The data collector also saves its current `Voter.weights(pool)` value (18-decimal units). This is NOT a guaranteed or claimable reward.
- Run an experimental GenLayer contract through the local GLSim environment that can read Base `eth_call(..., "latest")` reward allocations; direct RPC comparison has succeeded for a sample reward.
- Maintain a separate prototype for forecast submission and future settlement, which still requires further verification and suitable historical-state RPC access.

## Local dashboard

Use the project on **Windows with Ubuntu/WSL** or another system with Python 3.10+ and the existing project dependencies installed.

From the repository root, prepare the saved multi-pool data:

```bash
python scripts/scan_pools_base.py --count 5
python scripts/pool_fee_histories_base.py --weeks 12 --max-pools 5 --max-tokens 4
python scripts/backtest_pool_fees.py
```

Start the read-only dashboard:

```bash
python scripts/serve_dashboard.py
```

Open **http://localhost:8765/** in your browser. Press **Ctrl+C** in the dashboard terminal to stop it.

The local server binds only to `127.0.0.1` and serves the dashboard plus a restricted JSON results endpoint. It does not expose the full repository or allow data changes. The **Reload saved data** button re-reads locally saved JSON; it does **not** re-query Base. To refresh the on-chain snapshot, rerun the data collection and backtest commands above.

### Experimental vote allocation optimizer

To include USD-denominated FEES + BRIBES diagnostic data from the registered pool sample, after refreshing `pool_fee_histories_base.json` run:

```bash
python scripts/backtest_pool_fees.py
python scripts/collect_pool_incentives_base.py --max-bribe-tokens 20
python scripts/serve_dashboard.py
```

Collect the actual pool trading pair metadata separately (fast; reads only a few
on-chain values per active pool):

```bash
python scripts/collect_pool_pairs_base.py
```

This queries each pool contract's `token0()` and `token1()`, then queries
the underlying ERC-20 `symbol()` values. It saves
`data/pool_pairs_base.json`. The optimizer joins the pair labels by
**both pool index and contract address** and shows **Pool #11 · TOKEN0 / TOKEN1**
with the *actual* fetched symbols. It never confuses reward tokens with
pool trading pairs; unreadable pairs are explicitly marked as unavailable.
This metadata collection does not alter FEES, BRIBES, prices or reward calculations.

The dashboard now contains **Vote Allocation Optimizer**. Enter an amount of **locked AERO** and select the **remaining lock duration**, then click **Calculate Optimal Allocation**. The app estimates voting power using `locked AERO × remaining years / 4`, a linear approximation based on Aerodrome lock economics; Auto-Max can maintain full four-year weight. This is not a wallet-derived veNFT balance. It is user-initiated and read-only.

Only fully priced pools with positive current vote weight from the saved sampled set qualify. The app selects hypothetical new-voter allocations in **1-percentage-point increments**, allocating exactly 100% under a **voluntary 30%-per-pool maximum**. It maximizes the sum of the chosen pools' illustrative pro-rata payouts ON THAT GRID:

```text
estimated allocation USD = past-four-week-average total pool rewards valued at
                            current token prices
                          × your allocated veAERO votes
                          ÷ (current pool votes + your allocated votes)
```

It reports a hypothetical weekly USD total and a pool-by-pool breakdown. It is a transparent mathematical scenario tool, **not a trained AI optimizer**; it does not connect a wallet, actually vote, or forecast future fees. This 30% maximum is a user-experience diversification rule, not an Aerodrome protocol constraint. If fewer than four sampled pools have complete USD price coverage, the calculator refuses to optimize rather than assigning fabricated zero prices.

It blocks stale saved incentives (older than 36 hours) or a changed weekly epoch. Refresh all data after the epoch changes. Current price quotes are applied to past token allocations; BRIBES, FEES and pool voting-weight snapshots are not perfectly aligned to a real voting epoch; their release/eligibility conditions and actual claimability are not verified. **Do not use this tool as a financial return forecast.**

### Experimental veAERO voting reward simulator

Once you have pulled the latest code, **rerun the pool fee history collector and backtest** so the JSON includes `pool_vote_weight_raw`. Earlier JSON snapshots do not contain voting weights and the simulator will intentionally display *Not available* instead of inventing them.

The simulator accepts **effective veAERO voting power** (not automatically the number of AERO locked), the percentage allocated to a pool, and one historical FEES baseline. For a hypothetical NEW pool voter it calculates:

```text
Your allocated votes = effective veAERO voting power × allocation percentage
Illustrative vote share = your allocated votes / (currently recorded pool votes + your allocated votes)
Illustrative token allocation = chosen FEES baseline token amount × illustrative vote share
```

If the voter's weight is already included in the current pool total, check the **already included** box to avoid adding it twice. This is an approximation for education: voting-power snapshots and historical reward allocations are not from the same epoch; it excludes BRIBES, rewards lag, token prices and actual claimability. No wallet or transaction is involved.

The dashboard's data files are created locally:

- `data/pool_scan_base.json` — sampled pools and gauge metadata.
- `data/pool_fee_histories_base.json` — weekly reward allocation series.
- `data/pool_fee_backtest_base.json` — per-series backtest errors and baselines.
- `data/pool_incentives_base.json` — FEES + BRIBES observations, current USD quotes, price coverage and per-pool approximation data.
- `data/pool_pairs_base.json` — actual pool token0/token1 on-chain symbols and addresses, collected separately.

Historical reads use the free Base RPC by default (`https://base-rpc.publicnode.com`), or `BASE_RPC_URL` if supplied. The public endpoint may impose rate limits or require an access token for archive-state reads. Never commit credentials.

### Safe batched pool discovery

The existing `data/pool_scan_base.json` holds the original sample used by the
current FEES history and dashboard. To inspect later registration indexes
**without overwriting that sample**, specify a different output:

```bash
python scripts/scan_pools_base.py --start 20 --count 25 --output data/pool_scan_20_44.json
```

To combine the **first 20** and **20–44** scan batches into a separate
16-active-candidate input, do not replace the existing demo sample:

```bash
python scripts/merge_active_pool_scans.py data/pool_scan_base.json data/pool_scan_20_44.json --output data/pool_scan_active_expanded.json
```

After checking the printed IDs, collect extended FEES histories separately:

```bash
python scripts/pool_fee_histories_base.py --scan-file data/pool_scan_active_expanded.json --output-file data/pool_fee_histories_expanded_base.json --weeks 12 --max-pools 16 --max-tokens 4
```

Backtest the expanded 12-week FEES histories to a separate result file:

```bash
python scripts/backtest_pool_fees.py --input-file data/pool_fee_histories_expanded_base.json --output-file data/pool_fee_backtest_expanded_base.json
```

Then collect BRIBES and current USD quotes separately for those same pools
(**before** the Base weekly voting epoch changes, or refresh FEES history first):

```bash
python scripts/collect_pool_incentives_base.py --input-file data/pool_fee_histories_expanded_base.json --output-file data/pool_incentives_expanded_base.json --max-bribe-tokens 20
```

Next, collect actual token0/token1 trading pair symbols from each expanded
pool. Keep these separate from the original seven-pool pair labels:

```bash
python scripts/collect_pool_pairs_base.py --input-file data/pool_incentives_expanded_base.json --output-file data/pool_pairs_expanded_base.json
```

After verifying all four expanded files are present, start the **opt-in**
expanded dashboard preview:

```bash
python scripts/serve_dashboard.py --dataset expanded
```

This is still a read-only loopback dashboard on http://localhost:8765/.
The page identifies the expanded research preview, shows the 16 candidate
pools and 32 FEES series if collected, and uses the separately saved
FEES+BRIBES quote data for the what-if optimizer. It does NOT rank the
entire Aerodrome pool universe, guarantee yield, use wallet voting,
or serve synchronized historical block snapshots. Only complete,
fully-priced pools qualify for USD estimates, and tiny/illiquid token
quotes may be misleading even if marked fresh. To return to the
original sample, stop the server and run:

```bash
python scripts/serve_dashboard.py
```

### One-command expanded dataset refresh (after each voting epoch)

Once the 16-pool expanded preview has been created, the following command
refreshes its FEES histories, 12-week statistical backtest, FEES+BRIBES
price estimates and actual pool trading-pair metadata in the correct order:

```bash
python scripts/refresh_expanded_data.py
```

The local dashboard **may remain open** because the refresher publishes an
atomically replaced validated bundle. The script collects into a
temporary subfolder within `data/`, checks Base chain ID, active pool
identities, reward-series counts, collection epoch and metadata alignment,
and only then publishes the four expanded JSON files. It creates temporary
backups to restore on ordinary publish errors. Its four component JSON file
updates are **not one atomic transaction**, but the dashboard reads only the
separately atomically published, complete JSON bundle after a successful run.
A collection-stage error keeps the existing expanded files unchanged.
The original seven-pool demo files and the merged scan candidate list
are never replaced. If a later refresh discovers inactive gauges, the
new panel may show fewer than 16 active pools; no missing rewards are
automatically treated as zero.

The voting epoch begins on Thursdays at **00:00 UTC** (03:00 in
Turkey, UTC+3). Refresh after the boundary when the new epoch starts, and
again whenever price timestamps become stale. This is still a read-only,
non-synchronized, experimental historical reward scenario, **not** a
yield guarantee or a trained AI prediction.

After any Base voting epoch rollover, recollect expanded FEES history and
incentives before expecting the optimizer to run (its epoch freshness
guard is intentional). Backtest and pair metadata can be refreshed as needed.


### Development priorities and safe full-pool discovery

The next milestones, in implementation order, are:

1. **P1 — Complete pool inventory**: discover every registered Aerodrome
   Voter pool and identify gauges alive at one pinned Base block.
2. **P2 — Coverage and collection reliability**: measure how many active
   pools and FEES/BRIBES tokens can be collected; introduce bounded RPC
   concurrency, caching, retry/backoff, and incremental refresh. Require
   validated data before any promotion to the production dashboard.
3. **P3 — Better vote allocation analysis**: rank available pools using
   transparent FEES+BRIBES USD figures, fresh effective voting weights,
   missing-price safeguards, and clear concentration/volatility caveats.
4. **P4 — Discovery interface**: pool/token search, filters, sortable USD
   reward metrics, and labeled data coverage.
5. **P5 — Predictive evaluation**: longer point-in-time archives, held-out
   comparison of real forecasting models against simple baselines.
6. **P6 — Beginner/researcher views**: contextual explanations for beginners
   and richer research controls for advanced users.

**P1 implementation, opt-in (not a dashboard migration):**

```bash
python scripts/discover_active_pools_base.py --page-size 25 --max-pages 1
```

The first run validates the Base chain, pins a block and the Aerodrome Voter
registry length, then scans just 25 registration indices. Subsequent runs
resume from the saved checkpoint. Once small batches have succeeded, run the
**optional automatic full scan**, which scans all remaining indices from the
existing checkpoint without changing the pinned block:

```bash
BASE_RPC_URL=https://mainnet.base.org python scripts/discover_active_pools_base.py --until-complete --page-size 25 --delay-seconds 0.5
```

This long-running command can take considerable time; keep the terminal open.
Press **Ctrl+C** to pause safely and run it again later to resume. Completed
pages are preserved, and a non-blocking lock prevents overlapping discovery
processes from corrupting the checkpoint. The scanner backs off on temporary
RPC errors (default: up to three additional attempts, starting at a 3-second
wait and doubling), but **stops** on forbidden archive requests such as HTTP
403 instead of endlessly retrying. If a provider rejects the original pinned
block, use another archive-capable Base RPC via `BASE_RPC_URL`, without
`--restart`. Changing the RPC **only on this one command** leaves the
Windows hourly refresh task and dashboard RPC configuration unchanged.

A completed page is saved atomically to
`data/pool_discovery_checkpoint_base.json`; RPC interruptions do not publish
partially written pages. The tool only creates
`data/pool_discovery_active_base.json` after inspecting **every** index.
Output explicitly includes the pinned block, registered and active counts,
coverage and a completion flag. `--max-pages` (1-20) and `--page-size`
(1-100) adjust the work done per invocation; default RPC pacing is
0.1 seconds per index. To intentionally discard a checkpoint and take a
new pinned block, use `--restart`.

**A registry inventory is not a weekly reward dataset.** Active gauge status
does not prove that FEES or BRIBES have nonzero rewards, complete USD quotes,
or synchronized voting weights. The discovery result does not modify
`data/pool_scan_active_expanded.json`, the existing 16-pool dashboard files,
the hourly task, the old seven-pool demo, or the web server. P2 must first
support collections greater than the current 50-pool maximum and prove data
quality at larger scale. Public RPC providers can rate-limit calls or refuse
older pinned blocks during long resumptions; in that case the scanner
preserves progress and pauses rather than mix different chain snapshots.
An archive-capable RPC may be necessary for a multi-session complete scan.

Offline regression tests (no network; seven tests cover pagination,
resume, HTTP 429 retry, HTTP 403 archive refusal, exclusive locking,
RPC interruption and checkpoint integrity):

```bash
python -m unittest discover -s tests -p "discover_active_pools_test.py" -v
```

### P2 — Prepare validated collection batches (offline; no dashboard changes)

Once the full Voter inventory reports `COMPLETE` (e.g., **928 gauges
alive among 1,991 registered pools** at a particular pinned Base block),
validate it and build separate scan inputs in batches of 25:

```bash
python scripts/plan_pool_collection_base.py --batch-size 25 --order votes
```

This requires **no network or RPC requests**, and validates the completed
discovery checkpoint's complete/coverage flags, chain ID, Voter address,
pool IDs and counts before planning. It saves a manifest and deterministic
25-pool scan inputs under
`data/pool_collection_batches_base/block_<PINNED_BLOCK>/votes_25/`.
Existing `data/pool_scan_active_expanded.json`, the 16-pool dashboard
and its hourly refresher remain unchanged. Re-running with the same
snapshot is safe; changing the snapshot while targeting the same output
folder is rejected rather than silently mixing versions.

**Why plan batches first?** The existing FEES history collector caps each
run at **50 pools**, while the current expanded hourly refresh also caps its
candidate file at 50. The planner deliberately does **not** alter those
caps or run 928 pools through hourly refresh. Ranking is by **past snapshot
Voter weight** only, NOT by weekly FEES, BRIBES, profitability, opportunities,
current yield or expected veAERO payout. Zero-vote but alive gauges are
retained and explicitly counted. A gauge alive at the recorded block may
not be alive at collection time.

The next P2 step is to pilot a **separate** bounded FEES/BRIBES collector
using a planned 25-pool scan input, checkpoint results, verify USD price
coverage, and only then expand to more batches. This is not a live
928-pool optimizer or a production-dashboard migration.

Offline planner regression tests (six cases):

```bash
python -m unittest discover -s tests -p "plan_pool_collection_test.py" -v
```

### P2 — Independently audit a completed 25-pool FEES+BRIBES batch

After collecting FEES and BRIBES/USD into the *same isolated collection-batch
folder*, inspect their epoch, pool identities, token records, current quote
freshness and missing data **offline**:

```bash
python scripts/audit_pool_rewards_base.py --fees data/pool_collection_batches_base/block_52595092/votes_25/fee_histories_batch_001.json --incentives data/pool_collection_batches_base/block_52595092/votes_25/incentives_batch_001.json --output data/pool_collection_batches_base/block_52595092/votes_25/audit_batch_001.json
```

The audit re-checks FEES entries against the source FEES history and refuses
to mix unrelated epochs, pool addresses or voting weights. It suppresses USD
totals for truncated registries, nonzero rewards without current prices, and
quotes older than 36 hours. Its saved independent JSON includes the four
weekly USD values, count of positive FEES/BRIBES weeks, largest week's
share of the four-week total, approximate mean USD per week and mean USD
per **one million snapshot voting-power units**, which is an *illustrative
relative ratio only*, not a personal payout formula or recommendation.
Pools with zero recorded votes have no vote-efficiency ratio. The script
prints two separate descriptive top-five rankings for the batch.

This does not call Base RPC, fetch fresh token prices, update the current
16-pool panel, or enable a 928-pool optimizer. Four historical epoch
allocations are valued at a **saved current USD quote**, not past prices.
Voting weights and past rewards are not from synchronized blocks; thin or
misleading token quotes can make USD totals appear unrealistic. A ranking by
pool total is not a ranking of voter returns.

Offline regression tests:

```bash
python -m unittest discover -s tests -p "audit_pool_rewards_test.py" -v
```

### P2 — Safely run additional collection batches, one command at a time

After the first 25-pool batch has successfully collected FEES, BRIBES,
current-price USD data, and its independent audit, an opt-in orchestration
script can collect subsequent batches **without touching** the 16-pool
dashboard or automated hourly refresher. For a first dry run:

```bash
python scripts/run_pool_batch_pipeline.py --start-batch 2 --max-batches 1 --dry-run
```

Then, when prepared for live Base RPC and DefiLlama requests:

```bash
BASE_RPC_URL=https://mainnet.base.org python scripts/run_pool_batch_pipeline.py --start-batch 2 --max-batches 1
```

A single call collects FEES (4 weeks, up to 4 tokens), then BRIBES
(up to 40 registered tokens) and their current USD prices, then runs
the independent reward/weight audit. Everything is first written to an
**isolated staging subfolder**; only after the cross-file checks pass are
individual outputs published to the batch folder, with a completed
status marker written **last**. Finished batches are skipped when
re-running the same command. When FEES and BRIBES were already saved in
the per-batch staging folder but the final audit failed, rerunning the
same command validates and reuses both staged datasets (including quote
freshness) **without new RPC or token-price requests**. The staged audit
uses the required `audit_batch_NNN.json` filename. Invalid or
different-epoch staged data are never silently discarded. Failed
batches can be retried later.
The script is intentionally limited to **1–5 batches per invocation**,
with a default 10-second pause between batches. It does not install
a scheduled job or silently run all 928 pools unattended.

The **first batch's already completed 2026-10-08 epoch** is the anchor:
if the on-chain voting epoch rolls over before or during a subsequent
batch, the pipeline **pauses**, retaining completed data, rather than
silently mixing two voting weeks. Starting a new epoch-wide dataset
requires a separate next-epoch collection workflow, not overwriting
the old completed reports. Other limitations remain: archived blocks
are not used for FEES/BRIBES epoch lookups, missing token prices are
not zero, active gauges can change, and snapshot vote weights do not
predict returns. CLI outputs are for research, not wallet payouts.

Offline tests:

```bash
python -m unittest discover -s tests -p "run_pool_batch_pipeline_test.py" -v
```

### P2 — Continue across a Thursday epoch rollover without mixing data

**Do not** rerun an old batch under a new Aerodrome epoch or write over old
reward datasets. When the 2026-10-08 collection has completed the first
15/38 batches (375 pool records; 365 fully USD-priced), create a separate
2026-10-15 plan offline:

```bash
python scripts/prepare_next_epoch_collection.py --through-batch 15 --next-epoch 2026-10-15
```

The script first verifies the already published batch-001 results and
completed batch-002 through batch-015 status/files, including their
matching epoch and counts. It safely creates
`data/pool_collection_batches_base/block_52595092/votes_25/epochs/2026-10-15/`
with an independent, validated manifest and 38 *pool-selection-only*
batch input files, and pins the new `collection_epoch_utc` in the
manifest. It **does not copy any prior FEES/BRIBES/USD results**. Batch
inputs keep the original pinned-block voting-weight snapshot as a
coverage heuristic; **those are not refreshed 2026-10-15 voting weights**.
It does not call Base RPC or fetch prices or touch the 16-pool dashboard.
It is safe to rerun on an already prepared, matching plan; conflicting
files or mismatched old status markers halt without overwrite.

To inspect before live collection:

```bash
python scripts/run_pool_batch_pipeline.py --folder data/pool_collection_batches_base/block_52595092/votes_25/epochs/2026-10-15 --start-batch 16 --max-batches 1 --dry-run
```

Then collect one new-epoch batch, explicitly opting into Base RPC:

```bash
BASE_RPC_URL=https://mainnet.base.org python scripts/run_pool_batch_pipeline.py --folder data/pool_collection_batches_base/block_52595092/votes_25/epochs/2026-10-15 --start-batch 16 --max-batches 1
```

The pinned epoch is compared against the epoch actually reported by
the FEES and BRIBES collectors. If the collection is attempted outside
that epoch, it pauses safely without publishing mixed-epoch output.
New collection begins only at batch 16 or later; batches 1-15 remain
readable **only in the old folder** and are not skipped or faked as
2026-10-15 observations. Do not rank 2026-10-08 USD/weight ratios
directly against 2026-10-15 ratios as if they were a synchronized
point-in-time sample, and never claim the combined coverage reflects
928 simultaneous live pools. Ten older pool quotes were not fully
priced; next-week data does not repair those old observations.

Run the offline preparation regression tests with:

```bash
python -m unittest discover -s tests -p "prepare_next_epoch_collection_test.py" -v
```

### P2 — After a weekly Aerodrome epoch rolls over

A 25-pool collection batch always belongs to a particular Thursday 00:00
UTC Aerodrome reward epoch. The original pinned Base inventory from block
52595092 had 928 active gauges and 38 batches. **Original batches 001–015
were collected for the 2026-10-08 epoch** (375 audited pools); the USD
coverage count can be lower than the audited pool count.

Do **not** try to continue the original plan into a different epoch:
the live pipeline refuses an expired epoch. Instead, after the new epoch
begins, prepare a *new isolated subset plan* for previously uncollected
batches. The preparation operation is **offline** and will first check that
old results and completed status markers are consistent, report incomplete
old USD records with missing/truncated reasons, and reject any already
started batch incorrectly classified as uncollected.

```bash
python scripts/prepare_remaining_epoch_batches_base.py --dry-run
```

When the plan looks right:

```bash
python scripts/prepare_remaining_epoch_batches_base.py
```

This generates a **new manifest and 23 renumbered groups** for the remaining
553 snapshot pools under
`data/pool_collection_batches_base/block_52595092/votes_25/epoch_2026-10-15/`
if run in the new 2026-10-15 Aerodrome week (for later weeks, the script
uses the current Thursday UTC). Old batch inputs, original 375 audits,
and the 16-pool dashboard/hourscheduler are untouched.

The fresh new manifest pins `collection_epoch_utc` and permits bootstrapping
group 1 (former original group 16):

```bash
BASE_RPC_URL=https://mainnet.base.org python scripts/run_pool_batch_pipeline.py --folder data/pool_collection_batches_base/block_52595092/votes_25/epoch_2026-10-15 --start-batch 1 --max-batches 1
```

Continue with subsequent batch numbers within the same newly pinned
weekly epoch. The pipeline allows at most five 25-pool batches in one
call, stages and audits each separately and suppresses USD estimates for
missing token prices or truncated reward lists. When the epoch ends,
prepare a further epoch-specific plan for any **still uncollected** pools
rather than mixing dates.

**Important comparability limits:** old and new four-week windows
overlap but differ. Price quotes are sampled when each batch is run,
not at matched historical blocks. Vote weights remain from the
original pinned Base block, so USD per million snapshot votes is a
descriptive ratio, not a synchronized weekly veAERO yield. Never
merge the old and new batch rankings into one homogeneous
backtest/performance comparison or claim 928 identically dated pools.

Offline regression tests:

```bash
python -m unittest discover -s tests -p "prepare_remaining_epoch_batches_test.py" -v
python -m unittest discover -s tests -p "run_pool_batch_pipeline_test.py" -v
```

### P2 — Finish the complete 928-pool, two-epoch research inventory (offline)

After original batches 001–015 (2026-10-08) and separate next-epoch batches
016–038 (2026-10-15) have all completed, build ONE **read-only research
inventory** from their saved audits, with exact provenance per pool:

```bash
python scripts/build_full_pool_research_base.py
```

Expected source plan: 38 groups, 928 pinned-inventory gauge entries at Base
block 52595092. The original files for 375 entries are in
`data/pool_collection_batches_base/block_52595092/votes_25/`. The
remaining 553 were collected under the separate
`epochs/2026-10-15/` folder. The output is an independent, atomic JSON at
`data/pool_collection_batches_base/block_52595092/votes_25/research_all_928_two_epochs.json`.
It is **not** an input to the existing 16-pool dashboard or refresh job.

The builder validates the original and next-epoch manifests, checks unique
registry pool identities and both source epochs, confirms each completed
batch and per-pool audit coverage, checks positive-week counts against
actual FEES/BRIBES token reward records and suppresses incomplete token
USD values. It reports **USD coverage by epoch**, price-missing pool IDs,
and `no_observed_rewards` separately from `not_audited_at_collection`
(a pool may have become inactive). It preserves token addresses, symbols,
weekly mean token amounts, saved token quotes, reward frequency and
collection epoch per pool for a later searchable research UI. It does not
assume missing token quotes are $0, and does not rank pools across weeks
or present the ratios as a payout forecast.

This offline step reads saved per-batch audit classifications at the time of
collection; an old quote timestamp is retained as provenance rather than
being treated as a *new* quote today. Historical four-week reward quantities
remain valued at each batch's then-current token prices. Pool voting weights
are from the original pinned block, not synchronized to either reward epoch.

Offline regression tests:

```bash
python -m unittest discover -s tests -p "build_full_pool_research_test.py" -v
```

### P3 preview — Separate 928-pool research explorer (no dashboard replacement)

After successfully building `research_all_928_two_epochs.json`, open the
**independent** read-only local research browser:

```bash
python scripts/serve_pool_research.py
```

Open **http://localhost:8766/** in the Windows browser. The old 16-pool
dashboard stays on **http://localhost:8765/**, with its existing refresh jobs
untouched. The explorer has no scheduler, RPC fetch, price fetch, wallet,
transactions, external JS/CDN, or directory-serving endpoints. It binds only
to `127.0.0.1`. Press **Ctrl+C** in its terminal to stop this research UI.

Search by exact/partial pool registry number, pool/gauge address, reward-token
symbol, or reward-token address. Filter by 2026-10-08 vs 2026-10-15 collection
period, observed rewards (0 of 4 vs positive weeks), complete vs incomplete
saved-USD quotes, and paginate through matching pools. The default selected
period is **2026-10-15**. Within one selected epoch, exploratory sorting by
4-week mean reward USD / week or USD per million OLD pinned-block votes is
available; sorting across BOTH periods is intentionally limited to registry
index to prevent cross-epoch yield rankings.

Pool details show separate FEES and BRIBES registered token amounts and saved
USD quotes, number of weeks with rewards, the pool contract and collection
provenance.

A **display-only evidence filter** can require 4 of 4 positive-reward weeks,
$10 or more average pool reward USD per week at saved prices, and 100 or more
votes from the older pinned-block snapshot. These are configurable research
screening assumptions in the UI code—not safety labels, protocol thresholds,
liquidity verification, or yield forecasts. The exploratory old-vote-ratio sort
places low-denominator / tiny-total outliers after larger observations and
marks fragile ratios visibly, so a $0.43/week pool with almost zero old votes
does not appear to be the strongest opportunity merely from a huge ratio.

You may compare up to **three pools from the SAME collection epoch** side by
side, reviewing actual observed positive-reward weeks, separately observed
FEES/BRIBES weeks, saved-price pool USD totals, prior-snapshot vote weights,
and explicit low-evidence/missing-price caveats. Cross-epoch comparisons are
blocked rather than silently treated as synchronized. Comparison does not
claim future income or tradeability. Reward token symbols are **not trading-pair names**. Incomplete
USD totals remain unknown (not zero), and no observed rewards over four weeks
does not predict future zero rewards. This is **not a live APR or veNFT payout
calculator**; neither historical reward observations nor unsynchronized old
voting weights establish current voting profitability. The UI does not offer
cross-epoch optimization until reliable synchronized data is available.

**P5 / P5.1 — Four-week reward evidence.** Pool details and same-epoch
three-pool comparisons include audited four-week FEES and BRIBES USD totals
using each batch's saved token quote. P5.1 adds **retrospective evidence
notes** (not numerical confidence or investment-risk scores): BRIBES reliance,
how many of four weeks contained priced FEES/BRIBES, the largest week's share,
latest-week changes including low prior-week denominator caveats, saved quote
coverage/timing, and separate P4 voting-block provenance. Display-only alert
thresholds are **80% / 50% BRIBES share**, **50% / 40% peak-week share**,
and **100% / 50% absolute latest-week change**. Incomplete USD coverage
returns unknown explanations, never a $0 composition or a confident score;
all-zero observed weeks have undefined reward-mix and concentration shares.
Only four historical weeks exist. No APR, payout, probability, or stability
claim follows from these observations.

**P6.1 — Guided beginner and researcher views.** The research browser starts
in **Beginner view**, with a short three-step guide, explicit historical
reward/vote/quote provenance, searchable pool directory, and a one-click
example (#1930). **Researcher view** exposes the existing advanced
evidence/size and sorting controls, previous research-priority leader list,
and fragile historical vote ratios. Returning to Beginner view clears the
hidden advanced filters so that they cannot invisibly restrict search
results; it does not change saved data, research scores or reward summaries.
Both views keep pool Details, P5.1 evidence and three-pool same-epoch
comparison available. Responsive layout supports narrow displays; the
remaining table scrolls horizontally as needed.

**P6.2 — Beginner and narrow-screen usability.** The beginner presentation
now keeps the original detailed collection limitations available under
expandable provenance notes, a short glossary and an explanatory data note.
A **Search a pool** button jumps directly to the search field. The beginner
directory uses concise introductory text and starts at ten pools per page.
At viewports up to 700px wide, pool rows render as individually labeled
cards instead of forcing a 640–1030px table to scroll sideways; the
**Details** and **Compare** touch targets are at least 44px high.
Researcher mode retains its full advanced metadata, calculations and filters
inside these same narrow-screen cards. The only page-size change is the
initial display preference, not the underlying inventory. The JS and CSS
remain self-hosted on the same read-only service; no RPC, wallets or changes
to the 8765 dashboard or hourly jobs.

**P6.3 — Compact researcher mode on phones.** At viewports of 700px
or narrower, the full top-of-page historical warning, three provenance
cards, and detailed pair-label note are replaced visually by a short
persistent caution and native expandable `<details>` panels. The detailed
data-provenance text remains available on request; the underlying saved
data, scoring, P4 vote observations and P5.1 computations are unchanged.
A **Jump to pool filters** button focuses the existing search without
resetting researcher filters or the selected epoch. The full researcher
screening-methodology note and leaderboard formula now have accessible
expandable explanations. The full top provenance remains visible at
desktop sizes. No extra providers, requests, wallets, or scripts are needed.

This is a presentation-only, English-language local prototype. Research
data remain the historical October 8 / October 15 saved collections.
The separately hosted 16-pool dashboard on 8765 and its Windows hourly
refresh task are not changed. GenLayer is a separate later phase.

Offline server regression tests:

```bash
python -m unittest discover -s tests -p "serve_pool_research_test.py" -v
```

Frontend safety and optional JavaScript syntax tests:

```bash
python -m unittest discover -s tests -p "research_explorer_ui_test.py" -v
```

### Read token amounts and approximate USD equivalents

The expanded dashboard displays token quantity **and** an approximate USD
equivalent side by side in the FEES-only voting simulator, its selected reward
baseline, all three statistical forecast baselines, and the selected reward
history's latest/peak amounts. Individual chart points also include approximate
USD in their hover text. Changing the selected pool, reward token or baseline
recalculates the displayed conversion without calling a pricing API from the
browser.

USD values use **DefiLlama's saved Base contract-address token prices** from
the same validated incentive dataset already used by the optimizer. A quote
must be positive, present, and no more than **36 hours old**, and the incentive
snapshot itself must also be recent. Quotes are never matched by token symbol.
Missing quotes (for example for some HOP/WELL tokens), invalid token amounts,
and stale prices display **USD unavailable**, not an invented value or zero.
Very small positive values retain extra decimal precision.

**Important:** Applying a recent price to a prior week's FEES token amount is
a *present-value approximation*, not the historical USD value at that week's
market price. Pool-level FEES allocations and forecasting baselines are not
personal wallet rewards or payout promises. USD estimates in the FEES-only
simulator still exclude BRIBES. The original demo datasets are unmodified;
if a demo has no corresponding saved fresh quote it displays USD unavailable.

### Start the local dashboard automatically at Windows logon

On Windows 11 with WSL Ubuntu, you can register a **separate**, hidden Task
Scheduler job that launches the expanded dashboard at each Windows user logon.
This does not modify the **AeroPredict AI Hourly Refresh** task:

```bash
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$(wslpath -w scripts/install_dashboard_autostart.ps1)" -Distribution Ubuntu-24.04 -LinuxUser eser -LinuxProjectPath /home/eser/aeropredict-ai
```

Windows registers **AeroPredict AI Dashboard Autostart**, triggered **At log
on** for the interactive Windows account. Its `wscript.exe` launcher is in
`%LOCALAPPDATA%\\AeroPredictAI\\dashboard-autostart-hidden.vbs`. It launches
`scripts/dashboard_autostart_runner.py` under WSL's existing virtualenv,
which supervises `python scripts/serve_dashboard.py --dataset expanded` on
`127.0.0.1:8765`. No public-network listener, wallet connection or elevated
Windows permissions are needed.

The task is deliberately long-running and normally appears **Running** in
Task Scheduler while signed in. It uses a Linux file lock to prevent multiple
supervisors. If someone started the web panel manually in a terminal, the
supervisor detects that port 8765 is already taken and waits without
interfering. If that manual server stops, the supervisor attempts to start its
own server after up to ten seconds. Likewise, if the supervised server exits,
it attempts to start it again. If another application uses port 8765, the
supervisor cannot take that port and will keep waiting. Activity is written to
`data/dashboard_server.log`. The frequent 15-second dashboard status-poll
requests are omitted from this log to avoid log growth.

**Registration does not launch the web server immediately.** To test without
logging out or restarting Windows, run a separate command:

```bash
powershell.exe -NoProfile -Command 'Start-ScheduledTask -TaskName "AeroPredict AI Dashboard Autostart"; Get-ScheduledTask -TaskName "AeroPredict AI Dashboard Autostart" | Select-Object TaskName,State'
```

Keep the Windows PC powered on and its user logged in for this local service
to be available. It is not a public deployment and cannot serve other users
while your PC is off. After registration and testing, stop any previously
manually launched dashboard with **Ctrl+C**; the background supervisor should
take over. The dashboard remains reachable from the Windows browser via
`http://localhost:8765/` once the supervisor has started its server.

### Automatic hourly refresh on Windows 11 + WSL

For fresh USD quote inputs and repeated FEES and BRIBES collection, use the
**hourly** scheduler, not the old Thursday-only installer. It runs at every
**HH:15 Turkey time**, so the Thursday 03:15 run occurs after the 00:00 UTC
Aerodrome epoch boundary. Example for the project WSL environment:

```bash
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$(wslpath -w scripts/install_hourly_task.ps1)" -Distribution Ubuntu-24.04 -LinuxUser eser -LinuxProjectPath /home/eser/aeropredict-ai
```

The Windows task is named **AeroPredict AI Hourly Refresh**. It refreshes
12-week FEES histories, walk-forward backtests, four-week BRIBES and token USD
quotes, and trading pair metadata on every successful run. It uses an exclusive
WSL lock to prevent overlapping scheduled runs. Per-attempt logs are kept in
`data/hourly_refresh_logs/` (most recent 168 runs). If an older
**AeroPredict AI Weekly Refresh** task exists, installation removes that
task after successfully registering the hourly replacement.

The installer creates a user-local hidden launcher under
`%LOCALAPPDATA%\\AeroPredictAI\\hourly-refresh-hidden.vbs` so Task Scheduler
does not open an additional console window every hour. It requires Windows
Script Host (`wscript.exe`), which may be disabled by Windows policy.
After pulling newer code, **rerun the installer** to update an older task that
still launches a visible `wsl.exe` console. Do not close a currently running
console until its data refresh has finished.

No admin rights or Windows password storage are required. Windows must be
powered on and the same Windows user must be **logged on**. If Windows was
unavailable at a scheduled time, the trigger may run later. Repetition is
configured for approximately ten years; renew the task before expiry.
Frequent chain reads can hit public RPC rate limits; a failed attempt
keeps the last complete dashboard data. This is still a *local* computer
workflow, not a cloud-hosted always-on service.

Each completed collection publishes a validated dashboard snapshot in
`data/expanded_dashboard_bundle.json` with an atomic file replacement.
The read-only local dashboard serves this *complete* bundle on
`/api/results`, avoiding mixed-epoch component data while a refresh is in
progress. The original seven-pool demo files remain unchanged.

The dashboard also requests `/api/refresh-status` every 15 seconds.
Its English status strip shows the **last successful data snapshot in Turkey
time**, current progress ("Updating now…"), or failure while retaining
previous data. Once the new bundle is published the analytical panels
reload automatically; press **Calculate Optimal Allocation** again to
recompute hypothetical voting rewards. Starting the hourly task registration
does not itself trigger a refresh; check Task Scheduler and the WSL log
folder to confirm actual runs.

A single-hour schedule is only an update *frequency*: FEES/BRIBES calculations
still represent past completed weekly epochs with current token price quotes
and unsynchronized latest-state onchain reads. It is not new onchain payout
every hour, a guaranteed yield, or a validated forecasting AI.

This initial merge includes only pools that were **active when each scan ran**,
not a synchronized snapshot. The fee collector checks whether each pool remains
active on Base at collection time. Existing demo histories, baseline errors,
incentive data and dashboard are left unchanged. Extended backtest, BRIBES,
USD pricing and dashboard promotion are later steps; don't claim that newly
discovered pools have been profitability-ranked before those steps are done.

The scan uses a pinned Base block and prints how many of the requested
registration-order pools have active gauges. It also displays the largest
vote weights *within that one batch*; this is **not** a ranking of voting
rewards, profitability or a complete Aerodrome scan. The optional scan
file is stored separately so existing history/backtest/incentive snapshots
remain unchanged. Subsequent steps will choose suitable active pools from
these samples and only then expand the reward collector.

## How to interpret the analytics

**A pool's FEES token allocation is not an individual's veAERO income.** It is a reward-contract accounting value for a given token and epoch. To estimate a voter's actual reward, future versions must additionally consider their effective voting power, voted allocation, the pool's total voting weight, bribes, relevant token prices, and Aerodrome's reward/claim rules.

- **WAPE** is the sum of absolute forecast errors divided by the sum of observed rewards in a backtest. Lower values mean lower historical relative forecast error, not greater profitability.
- **MAE** is expressed in the reward token's units. Never compare or sum MAE or raw reward amounts of unrelated tokens as USD.
- **Sparse reward series** are flagged and not assigned a meaningful baseline winner.
- **Twelve weekly observations** yield only eight evaluation periods for a four-week lookback. These tiny samples do not establish predictive skill.
- The **next-epoch baseline** is a statistical reference calculated from recorded history. It has not been registered before the epoch on a production blockchain.

### Important data-integrity limitation

The current collector asks the Base reward contract for **past epoch keys against the latest contract state**, not for archived historical Base block state. This avoids the archive RPC requirement but does **not** recreate what the contract reported at that historical point in time. Reward allocations could be revised. Proper point-in-time historical accuracy will require independently timestamped snapshots or a reliable archive data source.

### GenLayer limitations

The local GLSim `sim_call` experiment proves a contract can execute the Base data-reading path in a local simulator. It does **not** establish that independent GenLayer validators have reached on-chain consensus, nor that the forecast settlement contract is production-ready. Real GenLayer network tests, deterministic epoch timing, immutable data references, and a supported archive strategy remain open work.

## Roadmap

1. Expand pool and token coverage; validate the input sample and preserve trustworthy point-in-time histories.
2. Introduce additional factors such as total voting weight, FEES and BRIBES, epoch changes, and confidence intervals.
3. Add transparent veAERO voting-power simulations and reward estimates **only after** verifying payout formulas and available on-chain inputs.
4. Introduce proper forecast registration, post-epoch settlement, and real independent GenLayer validator testing.
5. Build production-safe data refresh, monitoring, and public deployment infrastructure.

**Not financial advice.** All forecasts and comparisons are experimental research tools, not investment recommendations or promised token rewards.
