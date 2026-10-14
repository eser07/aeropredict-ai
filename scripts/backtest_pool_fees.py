#!/usr/bin/env python3
"""Walk-forward validation of Aerodrome multi-pool FEES token series.

Input comes from scripts/pool_fee_histories_base.py: weekly epoch allocations
queried at Base's *latest* state (NOT archived as-of snapshots).

For each pool/token, use four preceding completed epochs to predict each later
completed epoch. Never add raw amounts of tBTC, WETH, DOLA, USDbC together.
No forecast model is trained; baselines are lag-1, four-week mean and median.

Results are exploratory: eight holdout periods from twelve observed weeks, and
no immutable point-in-time history, price data or voting-power denominator.
"""
import json
import sys
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

INPUT = Path("data/pool_fee_histories_base.json")
OUTPUT = Path("data/pool_fee_backtest_base.json")
WINDOW = 4
MODELS = ("previous_week", "mean_4w", "median_4w")
MIN_POSITIVE_EVAL_FOR_COMPARISON = 4


def round_raw(value):
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def predictions(previous):
    if len(previous) != WINDOW:
        raise ValueError("Expected exactly four prior observations")
    ordered = sorted(previous)
    return {
        "previous_week": int(previous[-1]),
        "mean_4w": round_raw(sum(previous) / Decimal(WINDOW)),
        "median_4w": round_raw((ordered[1] + ordered[2]) / Decimal(2)),
    }


def token_amount(raw, decimals):
    if decimals is None:
        return None
    return format(Decimal(raw) / (Decimal(10) ** decimals), "f")


def measure_series(weeks, decimals):
    observations = sorted(weeks, key=lambda row: row["epoch_start_utc"])
    if len(observations) < WINDOW + 2:
        raise ValueError("Need at least 6 complete weekly observations")
    starts = [datetime.fromisoformat(row["epoch_start_utc"]) for row in observations]
    if any(b - a != timedelta(days=7) for a, b in zip(starts, starts[1:])):
        raise ValueError("Missing, duplicate or nonconsecutive weeks")
    actuals = [Decimal(int(row["raw"])) for row in observations]
    if any(value < 0 for value in actuals):
        raise ValueError("Negative reward allocation")
    folds = []
    for i in range(WINDOW, len(observations)):
        predicted = predictions(actuals[i - WINDOW:i])
        actual = int(actuals[i])
        folds.append({
            "epoch_start_utc": observations[i]["epoch_start_utc"],
            "actual_raw": str(actual),
            "predictions_raw": {k: str(v) for k, v in predicted.items()},
            "abs_errors_raw": {k: str(abs(v - actual)) for k, v in predicted.items()},
        })

    observed_positive = sum(int(row["actual_raw"]) > 0 for row in folds)
    all_positive = sum(value > 0 for value in actuals)
    actual_sum = sum(int(row["actual_raw"]) for row in folds)
    metrics = {}
    for method in MODELS:
        total_abs = sum(int(row["abs_errors_raw"][method]) for row in folds)
        mae_raw = Decimal(total_abs) / Decimal(len(folds))
        wape = (
            Decimal(total_abs) / Decimal(actual_sum) * Decimal(100)
            if actual_sum > 0 else None
        )
        metrics[method] = {
            "mae_raw": str(mae_raw),
            "mae_token_amount": token_amount(mae_raw, decimals),
            "wape_percent": (
                str(wape.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
                if wape is not None else None
            ),
        }
    # Only designate an exploratory winner if at least half the holdout
    # weeks have a nonzero reward. Sparse rewards deserve a no-winner label.
    eligible = (
        observed_positive >= max(
            MIN_POSITIVE_EVAL_FOR_COMPARISON,
            (len(folds) + 1) // 2,
        )
        and actual_sum > 0
    )
    best = (
        min(MODELS, key=lambda name: (
            Decimal(metrics[name]["mae_raw"]), MODELS.index(name)
        ))
        if eligible else None
    )
    baseline = predictions(actuals[-WINDOW:])
    return {
        "observed_week_count": len(observations),
        "positive_observed_weeks": int(all_positive),
        "fold_count": len(folds),
        "holdout_nonzero_weeks": observed_positive,
        "holdout_total_raw": str(actual_sum),
        "sparse_rewards_flag": not eligible,
        "exploratory_best_baseline": best,
        "metric_definitions": {
            "MAE": "mean absolute error in the SAME reward token units",
            "WAPE": "sum absolute errors / sum observed token rewards; "
                    "undefined if observed sum is zero",
        },
        "metrics": metrics,
        "folds": folds,
        "following_epoch_utc": (starts[-1] + timedelta(days=7)).isoformat(),
        "following_epoch_baselines_raw": {
            name: str(value) for name, value in baseline.items()
        },
        "following_epoch_baselines_token_amount": {
            name: token_amount(value, decimals)
            for name, value in baseline.items()
        },
    }


def main():
    if not INPUT.is_file():
        raise RuntimeError(
            "Missing data/pool_fee_histories_base.json; run "
            "python scripts/pool_fee_histories_base.py first"
        )
    data = json.loads(INPUT.read_text(encoding="utf-8"))
    if int(data.get("chain_id", 0)) != 8453:
        raise RuntimeError("Input is not Base Mainnet")
    if data.get("block_tag") != "latest":
        raise RuntimeError("Unexpected input state query methodology")
    if not isinstance(data.get("pools"), list):
        raise RuntimeError("Malformed multi-pool data")

    output = {
        "chain_id": 8453,
        "input": str(INPUT),
        "window_weeks": WINDOW,
        "model_names": list(MODELS),
        "notice": (
            "Exploratory backtests on historical epoch allocations "
            "queried at current state. No immutable point-in-time record, "
            "no voting yield / veAERO income / reward guarantee."
        ),
        "results": [],
    }
    print("AeroPredict AI | multi-pool weekly reward backtest")
    print("Four prior weeks -> each next completed week (walk-forward)")
    print("MAE is in the series' OWN token units; WAPE is a percentage.")
    print()
    count = 0
    for pool in data["pools"]:
        if not pool.get("active_at_collection"):
            print(f"Pool #{pool['index']}: inactive; skipped")
            continue
        for series in pool.get("reward_series", []):
            label = f"Pool #{pool['index']} / {series.get('symbol') or 'UNKNOWN'}"
            try:
                result = measure_series(
                    series["completed_weeks"], series.get("decimals")
                )
            except (KeyError, ValueError, TypeError) as exc:
                raise RuntimeError(f"{label}: {exc}") from exc
            output["results"].append({
                "pool_index": pool["index"],
                "pool_address": pool["pool_address"],
                "fees_contract": pool["fees_contract"],
                "token_address": series["token_address"],
                "token_symbol": series.get("symbol"),
                "token_decimals": series.get("decimals"),
                "analysis": result,
            })
            count += 1
            score_parts = [
                f"{model}: {result['metrics'][model]['wape_percent'] or 'N/A'}%"
                for model in MODELS
            ]
            print(f"{label}: {result['positive_observed_weeks']}"
                  f"/{result['observed_week_count']} weeks nonzero, "
                  f"{result['fold_count']} folds")
            print("  " + " | ".join(score_parts))
            if result["exploratory_best_baseline"]:
                best = result["exploratory_best_baseline"]
                print(
                    f"  Lowest past MAE: {best} | following-epoch baseline: "
                    f"{result['following_epoch_baselines_token_amount'][best]} "
                    f"{series.get('symbol') or 'token'}"
                )
            else:
                print(
                    "  Sparse holdout (or all-zero); no reliable baseline "
                    "winner designated"
                )
    output["series_count"] = count
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(output, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Saved: {OUTPUT} | {count} pool/token series")
    print(
        "CAUTION: Rankings are unstable with few folds. Do not compare "
        "raw amounts or MAE between unlike tokens. Not an AI prediction yet."
    )


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
