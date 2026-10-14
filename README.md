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
