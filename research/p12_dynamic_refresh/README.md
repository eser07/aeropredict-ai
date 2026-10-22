# P12 — hourly provider observations

This is a read-only Base collector for the entire Voter registry, not another
GenLayer deployment. Default example: 10,000 AERO. Each selected pool receives 10–25%; only the latest completed week enters this allocation. Earlier weeks are excluded from the income scenario, while historical research remains available.
The example is hypothetical while active/voting eligibility is unresolved.

## What changes on each successful update

`Voter.length()` and every registered index are checked at one finalized block
with `requireCanonical=true`. Existing IDs cannot disappear or change address.
New indexes enter the same list automatically. First-run expansion from the
old 950 cohort to 2,013 existing registrations is not 1,063 newly created pools.

FEES and BRIBES contract mappings, full reward registries, raw token amounts
for four completed weeks and the current incomplete week, vote weights, active
flags, token metadata and collection-time USD prices are refreshed together.
Each token's raw units remain separate. Unknown nonzero prices remain unknown;
global USD cards show the known subtotal and incomplete-pool counts.

The previous full success remains public if RPC/ABI/registry/canonicality
validation fails. All five epoch keys are read from one current post-period
state; they are not independently captured historical week-boundary states.
Current-period zero means no rewards observed in those contracts at that block,
not a forecast of zero income. These are pool budgets, not personal income/APR.

New data is `PROVIDER_OBSERVED`. Older Studio 950-pool attestations at their
original block/root remain separate. No deployment, transaction, faucet,
private RPC, personal wallet, API key, `.env`, or paid provider is used.

## Local execution

Install `requirements.txt` in a project environment, then:

    python -B research/p12_dynamic_refresh/refresh.py --live --output <new-data-directory>

A failed run can be resumed at the same block with `--resume <its-run-directory>`.
Completed run files are exclusive-create; do not resume a completed snapshot.
The runner is explicit-opt-in and never starts an infinite loop by itself.

## Prepared unattended writer

`aeropredict-hourly.yml` belongs in `.github/workflows/` of the public source
repository `eser07/aeropredict-ai` on its default branch `grass-main`.
It uses a standard Ubuntu public runner, at minute 23 of each hour, and a
40-minute job bound with a concurrency lock. No user token is stored: GitHub's
ephemeral scoped job credential pushes only the isolated `aeropredict-data`
branch, by normal fast-forward. Repository source is not rewritten hourly.
The job refuses private repositories and forks; it does not enable billing.

`publish_feed.py` puts `latest.json`, status and immutable first weekly
observations on that branch. Full raw checkpoints remain in local run output;
they are not uploaded on each hourly run. Git branch history retains earlier
latest snapshots. Budget/storage growth should be reviewed as history grows.

The public browser reads:

https://raw.githubusercontent.com/eser07/aeropredict-ai/aeropredict-data/latest.json

once a minute without credentials. Routine updates therefore need neither a
Sites source push nor a redeployment. GitHub's schedule is best effort; delays,
caching, disabled workflows or service failures can prevent exact hourly
arrival. Show the last successful data time and stale state after 90 minutes.

## Activation state

ACTIVATED with explicit human approval on 2026-10-22. The source branch was
fast-forwarded to 8189391; the clean runner required the explicit
eth-hash[pycryptodome] backend correction c7b8c4e. First successful GitHub run:
https://github.com/eser07/aeropredict-ai/actions/runs/39811460656

It published 2,013 provider records at Base finalized block 52947436,
hash 0xf9e2b38093b6cf9faa529c0dbb20e17ee0aedf669d97cfc58a947ed9ca39130f,
completed 2026-10-22T16:10:30.169348+00:00. Anonymous JSON readback returned 200
with the exact identity count/block and CORS access. Hourly cron is active at
minute 23; the first verified run was manually dispatched. Scheduled arrival
remains best effort, not an exact-time guarantee. Site publication is recorded
separately by its native deployment/version evidence.

`scenario-math.mjs` reproduces the latest-week 10–25% allocation. Dynamic
programming selects zero or 10–25 one-percent units per pool, sums to 100%,
and maximizes the hypothetical R*x/(W+x) value on that grid. Unknown older
weeks do not affect this latest-week computation. This remains hypothetical
while live voting eligibility is unresolved.

Preserve the previous Windows tasks, panels, historical data and dirty scripts.

## Verification

`test_refresh.py`: 8 offline regression tests, including failed-run retention,
unknown prices versus zero, registry growth/identity continuity, no RPC writes,
and immutable weekly first observations. A separate raw-amount audit checks
the real 2,013-pool snapshot. Earlier P9/P10 tests are not re-run by this job.

Official schedule constraints:
https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule

Public standard runner policy:
https://docs.github.com/en/actions/how-tos/write-workflows/choose-where-workflows-run/choose-the-runner-for-a-job
