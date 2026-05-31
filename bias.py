"""HTF bias synchronization against True Opens (TMO / TWO / TDO).

Bullish bias: price trades and holds above the open. Bearish: below. The
strategy only fires when all evaluable opens agree (the bias is *synchronized*).
"""
from __future__ import annotations


def _dir(price: float, open_level) -> str:
    if not isinstance(open_level, (int, float)):
        return "neutral"  # "N/A" or missing
    if price > open_level:
        return "bullish"
    if price < open_level:
        return "bearish"
    return "neutral"


def htf_bias(levels: dict) -> dict:
    """Classify monthly/weekly/daily bias and whether they are synchronized.

    `levels` is the dict from logic.calculate_quarterly_levels
    (keys: Current, TMO, TWO, TDO). Returns directions plus `overall`
    ("bullish"/"bearish"/"neutral") and a `synchronized` bool.
    """
    price = float(levels["Current"])
    monthly = _dir(price, levels.get("TMO"))
    weekly = _dir(price, levels.get("TWO"))
    daily = _dir(price, levels.get("TDO"))

    evaluable = [d for d in (monthly, weekly, daily) if d != "neutral"]
    if evaluable and all(d == "bullish" for d in evaluable):
        overall, synced = "bullish", True
    elif evaluable and all(d == "bearish" for d in evaluable):
        overall, synced = "bearish", True
    else:
        overall, synced = "neutral", False

    return {
        "monthly": monthly,
        "weekly": weekly,
        "daily": daily,
        "overall": overall,
        "synchronized": synced,
    }
