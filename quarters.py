"""Quarterly Theory time engine.

The *True Day* opens at 18:00 America/New_York (configurable). The 90-minute
algorithmic cycle tiles the day from that anchor; each cycle splits into four
22.5-minute micro-quarters:

    Q1  accumulation      (observe range / anchor price / IFVG)
    Q2  manipulation      (Judas swing — sweep against bias)
    Q3  distribution      (the "true move" — execution window)
    Q4  continuation/reversal

All functions accept any timezone-aware datetime and normalize to NY internally.
"""
import os
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

NY = ZoneInfo(os.getenv("QT_TIMEZONE", "America/New_York"))

# True Day open hour in the NY timezone (Daye standard = 18:00).
TRUE_DAY_OPEN_HOUR = int(os.getenv("QT_TRUE_DAY_OPEN_HOUR", "18"))

CYCLE_SECONDS = 90 * 60          # 90-minute algorithmic cycle
QUARTER_SECONDS = CYCLE_SECONDS // 4  # 22.5 min = 1350 s
_QUARTER_LABELS = ("Q1", "Q2", "Q3", "Q4")


def _to_ny(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return ts.astimezone(NY)


def true_day_open(ts: datetime) -> datetime:
    """Return the 18:00-NY datetime that opened the true day containing `ts`."""
    ny_ts = _to_ny(ts)
    open_today = datetime.combine(ny_ts.date(), time(TRUE_DAY_OPEN_HOUR), tzinfo=NY)
    if ny_ts >= open_today:
        return open_today
    return open_today - timedelta(days=1)


def quarter_info(ts: datetime) -> dict:
    """Locate `ts` within the Quarterly-Theory grid.

    Returns a dict with:
        cycle_index    int   — 90-min cycle since the true-day open (0-based)
        micro_quarter  str   — "Q1".."Q4" within the current 90-min cycle
        quarter_start  datetime (NY)
        quarter_end    datetime (NY)
        cycle_start    datetime (NY)
        is_q3          bool  — convenience flag for the execution window
    """
    ny_ts = _to_ny(ts)
    anchor = true_day_open(ny_ts)
    elapsed = int((ny_ts - anchor).total_seconds())

    cycle_index = elapsed // CYCLE_SECONDS
    cycle_start = anchor + timedelta(seconds=cycle_index * CYCLE_SECONDS)

    into_cycle = elapsed - cycle_index * CYCLE_SECONDS
    micro_index = into_cycle // QUARTER_SECONDS
    quarter_start = cycle_start + timedelta(seconds=micro_index * QUARTER_SECONDS)
    quarter_end = quarter_start + timedelta(seconds=QUARTER_SECONDS)
    micro_quarter = _QUARTER_LABELS[micro_index]

    return {
        "cycle_index": cycle_index,
        "micro_quarter": micro_quarter,
        "quarter_start": quarter_start,
        "quarter_end": quarter_end,
        "cycle_start": cycle_start,
        "is_q3": micro_quarter == "Q3",
    }
