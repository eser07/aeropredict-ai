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

**Stop the local dashboard first with Ctrl+C.** The script collects into a
temporary subfolder within `data/`, checks Base chain ID, active pool
identities, reward-series counts, collection epoch and metadata alignment,
and only then publishes the four expanded JSON files. It creates temporary
backups to restore on ordinary publish errors. The four-file publish is
**not one atomic transaction**; do not run the server simultaneously.
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


### Optional Windows 11 + WSL weekly schedule

A local Windows Task Scheduler installer is available for users who run the
project in **WSL Ubuntu** and want a weekly refresh after Aerodrome's Thursday
00:00 UTC epoch boundary. Example for a machine with the named WSL
distribution, Linux user and path (substitute your own as needed):

```bash
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$(wslpath -w scripts/install_weekly_task.ps1)" -Distribution Ubuntu-24.04 -LinuxUser eser -LinuxProjectPath /home/eser/aeropredict-ai
```

The task is named **AeroPredict AI Weekly Refresh**, runs every Thursday at
**03:15 Windows local time** (only correct for Turkey Standard Time, which
the installer explicitly verifies), and invokes
`scripts/weekly_refresh_runner.py` under the project's Python virtualenv.
This runner uses an exclusive Linux file lock and saves stdout/stderr and
completion status under `data/weekly_refresh_logs/`, retaining the 24 most
recent logs. It refuses overlapping launches.

This scheduling mechanism does not need Windows Administrator permissions
and does not store a Windows password. It runs only while the relevant
**Windows user is logged on**; a powered-off machine will not execute tasks
and missed runs are only attempted later when Windows/task scheduling
conditions permit. Keep WSL, the project directory and Python venv
installed and accessible. Task registration itself does **not** trigger a
data refresh. You can inspect it in **Task Scheduler** and optionally trigger
it manually for testing.

Note that the dashboard's USD quote freshness window is **36 hours**.
A Thursday-only refresh will not provide valid optimizer quotes all week.
Do not remove that safety check; introduce more frequent price refreshes or
a separate price-only collector before promising continuously usable yield
scenarios.





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
