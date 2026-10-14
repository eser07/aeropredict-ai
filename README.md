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

The dashboard's data files are created locally:

- `data/pool_scan_base.json` — sampled pools and gauge metadata.
- `data/pool_fee_histories_base.json` — weekly reward allocation series.
- `data/pool_fee_backtest_base.json` — per-series backtest errors and baselines.

Historical reads use the free Base RPC by default (`https://base-rpc.publicnode.com`), or `BASE_RPC_URL` if supplied. The public endpoint may impose rate limits or require an access token for archive-state reads. Never commit credentials.

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
