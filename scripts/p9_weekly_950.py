"""P9 single-epoch, saved-price weekly reward reader."""
import json
from pathlib import Path
from datetime import datetime, timedelta
from decimal import Decimal, localcontext
from serve_pool_research import saved_decimal, weekly_trend_summary

EPOCH15 = "2026-10-15T00:00:00+00:00"

def weekly_breakdown_950(pool, batch_root):
    """Reprice four saved reward weeks at their batch's SAVED quote, never live."""
    epoch = pool["collection_epoch_utc"]
    batch = pool.get("batch_number")
    if epoch != EPOCH15 or type(batch) is not int or not 1 <= batch <= 38:
        raise ValueError("Invalid batch identity")
    folder = Path(batch_root)
    source = folder / f"incentives_batch_{batch:03d}.json"
    doc = json.loads(source.read_text(encoding="utf-8"))
    if doc.get("chain_id") != 8453 or doc.get("current_epoch_utc") != epoch:
        raise ValueError("Saved incentives do not match collection epoch")
    rows = doc.get("pools")
    if not isinstance(rows, list):
        raise ValueError("Saved incentives missing pool records")
    matching = [x for x in rows if x.get("index") == pool["index"]]
    if len(matching) != 1 or (
        matching[0].get("pool_address", "").lower() != pool["address"].lower()
    ):
        raise ValueError("Saved pool identity differs from research dataset")
    row = matching[0]
    prices = doc.get("prices")
    if not isinstance(prices, dict):
        raise ValueError("Saved token prices unavailable")
    start = datetime.fromisoformat(epoch)
    expected_weeks = [
        (start - timedelta(days=7 * (4 - i))).isoformat() for i in range(4)
    ]
    weeks = [{"week_start_utc": w, "fees_usd": None,
              "bribes_usd": None, "total_usd": None} for w in expected_weeks]
    with localcontext() as context:
        context.prec = 80
        amounts = {}
        for kind in ("fees", "bribes"):
            tokens = row.get(kind)
            if not isinstance(tokens, list):
                raise ValueError("Saved reward category unavailable")
            values = [Decimal(0) for _ in range(4)]
            unknown = [False] * 4
            for token in tokens:
                address = token.get("token_address")
                decimals = token.get("decimals")
                history = token.get("last_four_weeks")
                if (not isinstance(address, str) or
                    (decimals is not None and
                     (type(decimals) is not int or not 0 <= decimals <= 36)) or
                    not isinstance(history, list) or len(history) != 4):
                    raise ValueError("Malformed saved token history")
                quote = prices.get(address.lower())
                price = None
                if isinstance(quote, dict) and quote.get("price_usd") is not None:
                    price = saved_decimal(quote["price_usd"])
                for i, entry in enumerate(history):
                    if entry.get("epoch_start_utc") != expected_weeks[i]:
                        raise ValueError("Saved reward week mismatch")
                    raw = saved_decimal(entry.get("raw"))
                    if raw and (price is None or decimals is None):
                        unknown[i] = True
                    elif price is not None and decimals is not None:
                        values[i] += raw / (Decimal(10) ** decimals) * price
            amounts[kind] = [None if unknown[i] else values[i] for i in range(4)]
        for i, week in enumerate(weeks):
            fees = amounts["fees"][i]
            bribes = amounts["bribes"][i]
            total = fees + bribes if fees is not None and bribes is not None else None
            week.update({
                "fees_usd": str(fees) if fees is not None else None,
                "bribes_usd": str(bribes) if bribes is not None else None,
                "total_usd": str(total) if total is not None else None,
            })
            if pool["usd_coverage_complete"]:
                saved = pool.get("weekly_pool_usd_at_collection_quote")
                if (not isinstance(saved, list) or len(saved) != 4 or
                    total is None or abs(total - saved_decimal(saved[i])) > Decimal("0.00000001")):
                    raise ValueError("Weekly split does not reconcile with audited pool total")
    return {
        "index": pool["index"],
        "address": pool["address"],
        "collection_epoch_utc": epoch,
        "usd_coverage_complete": pool["usd_coverage_complete"],
        "quote_policy": "Batch-saved token USD prices, not historical week prices",
        "weeks": weeks,
        "trend": weekly_trend_summary(weeks, pool["usd_coverage_complete"]),
    }
