#!/usr/bin/env python3
"""Walk-forward backtest for the first AeroPredict AI pool-level FEES baseline.

Uses the completed weekly USDbC allocations collected by
scripts/usdbc_fee_history.py. Every simulated forecast uses only earlier
completed weeks. No LLM, training labels from the future, or external keys.

WARNING: The number of walk-forward examples is dataset length minus four.
Results are illustrative, not proof of reliable APR or income prediction.
"""
import json
import sys
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

INPUT = Path("data/usdbc_fee_history_base.json")
OUTPUT = Path("data/usdbc_backtest_base.json")
EXPECTED_CHAIN = 8453
EXPECTED_FEES = "0x958a5612390bb4134e1e7505c7cb6b0652941174"
EXPECTED_TOKEN = "0xd9aaec86b65d86f6a7b5b1b0c42ffa531710b6ca"
DENOM = Decimal(1_000_000)
WINDOW = 4


def round_raw(raw_decimal):
    return int(Decimal(raw_decimal).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def predict_from_prior(prior):
    """prior is the exactly four known weekly token allocations, oldest first."""
    if len(prior) != WINDOW:
        raise ValueError("Expected exactly four historical weeks")
    ordered = sorted(prior)
    return {
        "previous_week": prior[-1],
        "mean_4w": round_raw(sum(prior) / Decimal(WINDOW)),
        "median_4w": round_raw(
            (Decimal(ordered[1]) + Decimal(ordered[2])) / 2
        ),
    }


def token_amount(raw):
    return f"{Decimal(raw) / DENOM:.6f}"


def main():
    if not INPUT.is_file():
        raise RuntimeError(
            "No data found. First run: python scripts/usdbc_fee_history.py"
        )
    data = json.loads(INPUT.read_text(encoding="utf-8"))
    if int(data.get("chain_id", 0)) != EXPECTED_CHAIN:
        raise RuntimeError("Input does not match Base Mainnet")
    if data.get("reward_contract", "").lower() != EXPECTED_FEES:
        raise RuntimeError("Unexpected Aerodrome FEES contract")
    if data.get("token", "").lower() != EXPECTED_TOKEN:
        raise RuntimeError("Unexpected reward token")
    if int(data.get("token_decimals", -1)) != 6:
        raise RuntimeError("Expected USDbC with six decimals")

    # Data collection writes newest-first; backtesting needs oldest-first.
    weeks = sorted(
        data.get("completed_weeks", []),
        key=lambda row: row["epoch_start_utc"],
    )
    if len(weeks) < 6:
        raise RuntimeError("At least six completed weeks are required")
    if len(set(row["epoch_start_utc"] for row in weeks)) != len(weeks):
        raise RuntimeError("Duplicate epoch timestamps")

    starts = [datetime.fromisoformat(row["epoch_start_utc"]) for row in weeks]
    for first, second in zip(starts, starts[1:]):
        if second - first != timedelta(days=7):
            raise RuntimeError("Missing or nonconsecutive completed weeks")
    values = [Decimal(int(row["raw"])) for row in weeks]
    if any(raw < 0 for raw in values):
        raise RuntimeError("Negative reward allocation is invalid")

    print("AeroPredict AI | historical walk-forward validation")
    print(
        f"Pool #0 FEES / USDbC | {len(weeks)} completed weeks | "
        f"{len(weeks) - WINDOW} holdout forecasts"
    )
    print("Method: each week's prediction uses the four PREVIOUS completed weeks.")
    print()
    print("Target week | Observed  | Prev week | 4w mean  | 4w median")

    rows = []
    models = ("previous_week", "mean_4w", "median_4w")
    for i in range(WINDOW, len(weeks)):
        previous = values[i - WINDOW:i]
        predicted = predict_from_prior(previous)
        actual = int(values[i])
        row = {
            "target_epoch_start_utc": weeks[i]["epoch_start_utc"],
            "actual_raw": str(actual),
            "predictions_raw": {key: str(v) for key, v in predicted.items()},
            "abs_errors_raw": {
                key: str(abs(v - actual)) for key, v in predicted.items()
            },
        }
        rows.append(row)
        print(
            f"{starts[i]:%Y-%m-%d}  | {token_amount(actual):>9} | "
            f"{token_amount(predicted['previous_week']):>9} | "
            f"{token_amount(predicted['mean_4w']):>9} | "
            f"{token_amount(predicted['median_4w']):>9}"
        )

    summary = {}
    for model in models:
        errors = [Decimal(row["abs_errors_raw"][model]) for row in rows]
        mae = sum(errors) / Decimal(len(errors))
        actual_total = sum(Decimal(row["actual_raw"]) for row in rows)
        wape = (
            (sum(errors) / actual_total * Decimal(100))
            if actual_total > 0 else None
        )
        summary[model] = {
            "MAE_USDbC": token_amount(mae),
            "WAPE_percent": str(wape.quantize(Decimal("0.01")))
            if wape is not None else None,
        }

    print("\nMean absolute error (MAE), smaller is better:")
    for model in models:
        wape = summary[model]["WAPE_percent"]
        print(
            f"  {model:>14}: {summary[model]['MAE_USDbC']} USDbC "
            f"| WAPE {wape + '%' if wape is not None else 'N/A'}"
        )

    upcoming_start = starts[-1] + timedelta(days=7)
    next_predictions = predict_from_prior(values[-WINDOW:])
    print(
        f"\nBaseline for the following, NOT YET COMPLETE epoch "
        f"({upcoming_start:%Y-%m-%d}):"
    )
    for model in models:
        print(f"  {model:>14}: {token_amount(next_predictions[model])} USDbC")

    output = {
        "basis": "Pool-level FEES allocation per epoch (USDbC), not veAERO APR",
        "chain_id": EXPECTED_CHAIN,
        "fee_contract": EXPECTED_FEES,
        "token": EXPECTED_TOKEN,
        "history_window_weeks": WINDOW,
        "completed_weeks_in_dataset": len(weeks),
        "walk_forward_folds": len(rows),
        "methodology": "Past-only rolling window; no in-sample current-week data",
        "folds": rows,
        "metrics": summary,
        "next_unfinished_epoch_start_utc": upcoming_start.isoformat(),
        "baseline_for_next_unfinished_epoch_raw": {
            name: str(value) for name, value in next_predictions.items()
        },
        "warnings": [
            "Only a few validation folds: model rankings are unstable.",
            "A zero reward week is retained as an actual observed zero; "
            "it can also require review for protocol or pool status changes.",
            "These are historical epoch mappings read at latest state, "
            "not archived block-by-block snapshots.",
            "The predicted allocations are not guaranteed rewards, "
            "claimable veAERO earnings, USD value or voting APR.",
            "The following epoch may already have started; these baselines "
            "are not a pre-registered live forecast.",
        ],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Saved: {OUTPUT}")
    print(
        "CAUTION: These few backtest folds cannot establish reliable "
        "predictive accuracy. Next: more pools, epochs and realistic features."
    )


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
